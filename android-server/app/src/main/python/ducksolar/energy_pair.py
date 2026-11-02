"""Prepare timestamps once per pair; retain the original accounting formula."""
from .energy_accounting import number, stamp


class Pair:
    def __init__(self, a, b, max_gap, previous_time=None):
        self.a, self.b, self.max_gap = a, b, max_gap
        self.x, self.y = previous_time or stamp(a['timestamp']), stamp(b['timestamp'])
        self.xt, self.yt = self.x.timestamp(), self.y.timestamp()
        self.dt = self.yt-self.xt

    def _value(self, direction, start, end):
        if self.dt <= 0:
            return None
        boundary=getattr(self,'_boundary',None)
        if boundary is None or boundary[0].timestamp()!=start.timestamp() or boundary[1].timestamp()!=end.timestamp():
            left,right=max(self.x,start,key=lambda t:t.timestamp()),min(self.y,end,key=lambda t:t.timestamp())
            lt=self.xt if left is self.x else left.timestamp();rt=self.yt if right is self.y else right.timestamp()
            boundary=(start,end,left,right,lt,rt,rt-lt);self._boundary=boundary
        _,_,left,right,lt,rt,duration=boundary
        if duration <= 0:
            return None
        a, b, dt = self.a, self.b, self.dt
        value = kind = None
        reason = ''
        reset = False
        if direction == 'pv':
            av, bv = a.get('pv_w'), b.get('pv_w')
            if dt <= self.max_gap and number(av) and number(bv):
                f, g = (lt-self.xt)/dt, (rt-self.xt)/dt
                value = ((av+(bv-av)*f)+(av+(bv-av)*g))*.5*duration/3600000
                kind = 'integrated'
        else:
            key = 'grid_'+direction+'_energy_total_kwh'
            identity = 'grid_'+direction+'_counter_id'
            av, bv = a.get(key), b.get(key)
            same = bool(a.get(identity)) and a.get(identity) == b.get(identity)
            if same and number(av) and number(bv):
                if bv >= av:
                    value = (bv-av)*duration/dt
                    kind = 'counter' if duration == dt else 'counter_estimated_boundary'
                else:
                    limit = a.get('grid_'+direction+'_counter_modulus_kwh')
                    if number(limit) and limit == b.get('grid_'+direction+'_counter_modulus_kwh') and 0 <= bv < av < limit:
                        value = (limit-av+bv)*duration/dt
                        kind = 'counter_rollover' if duration == dt else 'counter_estimated_boundary'
                    else:
                        reset = True
            if value is None and dt <= self.max_gap:
                key = 'grid_'+direction+'_w'
                av, bv = a.get(key), b.get(key)
                source = a.get('grid_'+direction+'_source')
                if number(av) and number(bv) and source in ('measured', 'estimated') and source == b.get('grid_'+direction+'_source') and a.get('grid_'+direction+'_origin') == b.get('grid_'+direction+'_origin'):
                    f, g = (lt-self.xt)/dt, (rt-self.xt)/dt
                    value = ((av+(bv-av)*f)+(av+(bv-av)*g))*.5*duration/3600000
                    kind = source
                    reason = a.get('grid_'+direction+'_reason', '')
        return value,kind,reason,reset,duration,left,right

    def accumulate(self, summaries, start, end):
        """Same arithmetic, without constructing/stringifying detailed intervals."""
        for direction,bucket in summaries.items():
            result=self._value(direction,start,end)
            if result is None:continue
            value,kind,reason,reset,duration,left,right=result
            bucket.resets+=int(reset)
            if value is not None:
                bucket.kwh+=value;bucket.covered+=duration;bucket.count+=1
                if kind in ('counter','counter_rollover','measured'):bucket.measured+=duration

    def energy(self, direction, start, end):
        result=self._value(direction,start,end)
        if result is None:return dict(intervals=[],resets=[])
        value,kind,reason,reset,duration,left,right=result
        intervals=[] if value is None else [dict(start=left.isoformat(),end=right.isoformat(),kwh=value,source=kind,reason=reason)]
        resets=[dict(from_time=self.x.isoformat(),to_time=self.y.isoformat(),reason='counter_decreased')] if reset else []
        return dict(intervals=intervals,resets=resets,duration_s=duration)
