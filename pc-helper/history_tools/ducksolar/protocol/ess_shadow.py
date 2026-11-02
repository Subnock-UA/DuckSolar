"""Bounded, passive ESS correlation. Never generates or modifies cloud replies."""
from collections import OrderedDict,deque
import statistics
from dataclasses import dataclass
import threading
import time


def modbus_crc(data):
    crc = 0xffff
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xa001 if crc & 1 else 0)
    return crc


def valid_modbus(data):
    return len(data) >= 4 and modbus_crc(data[:-2]) == int.from_bytes(data[-2:], 'little')


def native_read(start=4501, count=45):
    body = bytes((5, 3)) + start.to_bytes(2, 'big') + count.to_bytes(2, 'big')
    return body + modbus_crc(body).to_bytes(2, 'little')


@dataclass(frozen=True)
class CloudSample:
    payload: bytes
    values: dict | None
    requested: float
    received: float
    token: tuple
    connection: str
    operation: str


# Candidate map derived from the observed 4501 bank, not an imported driver.
# Reuse is enabled only after agreement with direct PI30 readings in this session.
LIVE_FIELDS = {
    'grid_v': (1, 10), 'grid_hz': (2, 10), 'pv_v': (3, 10), 'pv_w': (4, 1),
    'battery_v': (5, 10), 'battery_pct': (6, 1), 'charge_a': (7, 1),
    'discharge_a': (8, 1), 'output_v': (9, 10), 'output_hz': (10, 10),
    'output_va': (11, 1), 'output_w': (12, 1), 'load_pct': (13, 1),
}


def decode_live(body, count):
    if not valid_modbus(body) or body[:2] != b'\x05\x03':
        return None
    if len(body) != 5 + count * 2 or body[2] != count * 2 or count < 14:
        return None
    words = [int.from_bytes(body[i:i+2], 'little') for i in range(3, len(body)-2, 2)]
    values = {key: words[index] / scale for key, (index, scale) in LIVE_FIELDS.items()}
    ranges = {'grid_v':(0,300), 'grid_hz':(0,70), 'output_v':(0,300), 'output_hz':(0,70),
              'pv_v':(0,600), 'pv_w':(0,15000), 'battery_v':(0,100), 'battery_pct':(0,100),
              'charge_a':(0,300), 'discharge_a':(0,400), 'output_va':(0,15000),
              'output_w':(0,15000), 'load_pct':(0,200)}
    if any(not low <= values[key] <= high for key, (low, high) in ranges.items()):
        return None
    return values


class ESSShadow:
    def __init__(self, targets, clock=time.monotonic):
        self.targets = targets
        self.clock = clock
        self.lock = threading.RLock()
        self.reset('')

    def reset(self, connection):
        with self.lock:
            self.connection = connection
            self.buffers = {}
            self.pending = OrderedDict()
            self.samples = {}
            self.aux = {}
            self.calibration = {}
            self.last_calibrated = {}
            self.used = {}
            self.live_requests=deque(maxlen=6)
            self.stats = dict(cloud_reads=0, reuse=0, invalid=0, calibration_matches=0)

    def _prune(self, now):
        for key, item in list(self.pending.items()):
            # The physical logger sometimes replies after 8–9 s. Admission
            # must retain that outstanding request beyond the old 4 s limit.
            lifetime = 4 if item.get('metadata') else 12
            if now - item['time'] > lifetime or (item.get('metadata') and item.get('last_reply') is not None and now-item['last_reply']>.25):
                self.pending.pop(key, None)
        while len(self.pending) > 128:
            self.pending.popitem(last=False)

    def cloud_reconnected(self):
        with self.lock:
            self.buffers.clear();self.pending.clear();self.samples.clear();self.aux.clear()
            self.live_requests.clear()

    def feed(self, direction, data):
        """Observation only: malformed/unknown bytes still pass through the proxy."""
        with self.lock:
            now = self.clock()
            self._prune(now)
            buffer = self.buffers.setdefault(direction, bytearray())
            buffer.extend(data)
            while len(buffer) >= 8:
                length = int.from_bytes(buffer[4:6], 'big')
                if not 2 <= length <= 8192:
                    del buffer[0]
                    continue
                total = length + 6
                if len(buffer) < total:
                    break
                frame = bytes(buffer[:total])
                del buffer[:total]
                self._frame(direction, frame, now)
            if len(buffer) > 16384:
                buffer.clear()

    def _frame(self, direction, frame, now):
        tid = int.from_bytes(frame[:2], 'big')
        code = int.from_bytes(frame[2:4], 'big')
        address, function = frame[6:8]
        body = frame[8:]
        key = (tid, address, function)
        if direction == 'request':
            if function not in (1,2,4,17,18,19):
                return
            route = (code, address)
            target = self.targets.get(route)
            operation = target['requests'].get(body) if target and function==4 else None
            native = function==4 and code in (1, 0x0102) and valid_modbus(body) and len(body) == 8 and body[:2] == b'\x05\x03'
            if native and body[2:6]==bytes.fromhex('1195002d'):
                self.live_requests.append(now)
            write = function == 4 and (valid_modbus(body) and body[1] in (6,16)
                or bool(target and target.get('write_validator',lambda r:False)(body)))
            opaque = not operation and not native and not write
            self.pending[key] = dict(time=now, code=code, body=body, route=route, operation=operation,
                                     native=native, write=write or function==18, opaque=opaque,
                                     metadata=function==2,last_reply=None)
            self._prune(now)
            return
        request = self.pending.get(key)
        if not request:
            return
        # Native replies can retain 0001 or use collector code 0102.
        allowed = (1, 0x0102) if request['code'] in (1,0x0102) else (request['code'],)
        if code not in allowed:
            return
        if request.get('metadata'):
            # One metadata request has several replies with the same TID.
            request['last_reply']=now
            return
        self.pending.pop(key, None)
        if request['write']:
            # The response is forwarded unchanged, including proprietary non-echo ACKs.
            self.samples.clear()
            return
        if request.get('opaque'):
            return
        route, operation = request['route'], request['operation']
        values = None
        if request['native']:
            start = int.from_bytes(request['body'][2:4], 'big')
            count = int.from_bytes(request['body'][4:6], 'big')
            if start==4546 and count==16 and len(self.targets)==1:
                if valid_modbus(body) and len(body)==37 and body[:3]==bytes((5,3,32)):
                    temperature=int.from_bytes(body[25:27],'little')
                    if 0<=temperature<=120:
                        self.aux[next(iter(self.targets))]=(now,self.connection,{'temperature_c':temperature})
                return
            if start != 4501 or count != 45 or len(self.targets) != 1:
                return
            values = decode_live(body, count)
            if values is None:
                self.stats['invalid'] += 1
                return
            route = next(iter(self.targets))
            operation = 'QPIGS'
        else:
            try:
                target=self.targets[route]
                if not target['valid_response'](body): raise ValueError('Invalid response')
                if 'decode_response' in target: target['decode_response'](body,operation)
            except (ValueError,UnicodeError):
                self.stats['invalid'] += 1
                return
        token = (self.connection, tid, request['time'])
        self.samples[(route, operation)] = CloudSample(body, values, request['time'], now,
                                                       token, self.connection, operation)
        self.stats['cloud_reads'] += 1

    def auxiliary(self,route,max_age=5):
        with self.lock:
            item=self.aux.get(route)
            if not item or item[1]!=self.connection or self.clock()-item[0]>max_age:return {}
            return dict(item[2],_received_monotonic=item[0])

    def calibrate(self, route, local_values):
        with self.lock:
            sample = self.samples.get((route, 'QPIGS'))
            # Real PI30 round trips can take >1 s. Compare a still-fresh bank
            # with the direct read, using the same 5 s freshness ceiling.
            if not sample or sample.values is None or self.clock()-sample.requested>5 or self.clock()-sample.received>3:
                return
            if self.last_calibrated.get(route) == sample.token:
                return
            self.last_calibrated[route] = sample.token
            # Broad physical coverage prevents accepting an all-zero or constant field match.
            tolerance = {'grid_v':1, 'output_v':1, 'battery_v':.3, 'grid_hz':.5, 'output_hz':.5,
                         'pv_v':3, 'pv_w':40, 'output_w':40, 'output_va':40,
                         'battery_pct':1, 'load_pct':2, 'charge_a':2, 'discharge_a':2}
            matches = sample.values['battery_v'] > 1 and sample.values['output_v'] > 1
            for key, value in sample.values.items():
                direct = local_values.get(key)
                matches = matches and isinstance(direct, (int, float)) and abs(value-direct) <= max(tolerance[key], abs(direct)*.02)
            self.calibration[route] = min(3, self.calibration.get(route, 0)+1) if matches else 0
            if matches:
                self.stats['calibration_matches'] += 1

    def take(self, route, operation, since, max_age=5):
        with self.lock:
            now = self.clock()
            sample = self.samples.get((route, operation))
            if not sample or sample.connection != self.connection or sample.requested <= since:
                return None
            if now - sample.requested > max_age or sample.received - sample.requested > 3:
                return None
            if self.used.get((route, operation)) == sample.token:
                return None
            if sample.values is not None and self.calibration.get(route, 0) < 3:
                return None
            self.used[(route, operation)] = sample.token
            self.stats['reuse'] += 1
            return sample

    def in_flight(self):
        with self.lock:
            self._prune(self.clock())
            # A local frame must never be inserted between TCP fragments of
            # the same ESS request, even before its full header is available.
            return bool(self.pending or self.buffers.get('request'))

    def snapshot(self):
        with self.lock:
            return dict(self.stats, calibrated=any(v >= 3 for v in self.calibration.values()),
                        pending=len(self.pending), native_fields=list(LIVE_FIELDS))

    def approaching_live_read(self, duration):
        """Learn the actual ESS cadence; do not assume a premium subscription."""
        with self.lock:
            if len(self.live_requests)<3:return False
            gaps=[b-a for a,b in zip(self.live_requests,list(self.live_requests)[1:])]
            period=statistics.median(gaps)
            if not 4<=period<=90 or any(abs(gap-period)>max(.6,period*.15) for gap in gaps):return False
            expected=self.live_requests[-1]+period;now=self.clock()
            return now<expected+.6 and now+duration+.2>=expected
