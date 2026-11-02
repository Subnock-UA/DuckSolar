from __future__ import annotations

from dataclasses import dataclass

# Known read-only commands confirmed for this inverter family.
READ_COMMANDS = {
    "QPI",
    "QID",
    "QMN",
    "QPIGS",
    "QMOD",
    "QPIRI",
    "QVFW",
    "QVFW2",
    "QPIWS",
    "QFLAG",
}


def crc16_xmodem(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def _escape_crc(raw: bytes) -> bytes:
    # PI30 reserves (, CR and LF: increment each CRC byte, never expand it.
    return bytes(b + 1 if b in (0x28, 0x0D, 0x0A) else b for b in raw)


def decode_packet(encoded: bytes) -> bytes:
    if len(encoded) < 4 or not encoded.endswith(b"\r"):
        raise ValueError("Incomplete PI30 packet")
    payload, received = encoded[:-3], encoded[-3:-1]
    expected = _escape_crc(crc16_xmodem(payload).to_bytes(2, "big"))
    if received != expected:
        raise ValueError(f"PI30 CRC mismatch: {received.hex()} != {expected.hex()}")
    return payload


def encode_command(command: str) -> bytes:
    command = command.strip().upper()
    if command not in READ_COMMANDS:
        raise ValueError(f"Local command is read-only: {command}")
    return _encode_packet(command)

def _encode_packet(text):
    """CRC framing only; authorization belongs to the driver command schema."""
    payload = text.encode("ascii")
    crc = crc16_xmodem(payload)
    crc_bytes = bytes(((crc >> 8) & 0xFF, crc & 0xFF))
    return payload + _escape_crc(crc_bytes) + b"\r"


@dataclass
class QPIGS:
    grid_v: float
    grid_hz: float
    output_v: float
    output_hz: float
    output_va: int
    output_w: int
    load_pct: int
    bus_v: int
    battery_v: float
    charge_a: float
    battery_pct: int
    temperature_c: float
    pv_a: float
    pv_v: float
    scc_battery_v: float
    discharge_a: float
    device_status: str
    service_field: str
    eeprom_version: str
    pv_w: float
    extra_status: str


def parse_qpigs(text: str) -> QPIGS:
    s = text.strip().strip("\r\n")
    if s.startswith("("):
        s = s[1:]
    parts = s.split()
    if len(parts) < 21:
        raise ValueError(f"QPIGS field count {len(parts)} < 21")

    return QPIGS(
        grid_v=float(parts[0]),
        grid_hz=float(parts[1]),
        output_v=float(parts[2]),
        output_hz=float(parts[3]),
        output_va=int(float(parts[4])),
        output_w=int(float(parts[5])),
        load_pct=int(float(parts[6])),
        bus_v=int(float(parts[7])),
        battery_v=float(parts[8]),
        charge_a=float(parts[9]),
        battery_pct=int(float(parts[10])),
        temperature_c=float(parts[11]),
        pv_a=float(parts[12]),
        pv_v=float(parts[13]),
        scc_battery_v=float(parts[14]),
        discharge_a=float(parts[15]),
        device_status=parts[16],
        service_field=parts[17],
        eeprom_version=parts[18],
        pv_w=float(parts[19]),
        extra_status=parts[20],
    )


def extract_command_name(encoded: bytes) -> str | None:
    """Decode a complete, CRC-valid command; replies are never command names."""
    try:
        payload = decode_packet(bytes(encoded))
        if payload.startswith(b"("): return None
        return payload.decode("ascii")
    except (ValueError, UnicodeError, TypeError):
        return None


def encode_response_text(text: str) -> bytes:
    payload = ("(" + text).encode("ascii")
    crc = crc16_xmodem(payload)
    crc_bytes = bytes(((crc >> 8) & 0xFF, crc & 0xFF))
    return payload + _escape_crc(crc_bytes) + b"\r"


def encode_nak() -> bytes:
    return encode_response_text("NAK")


QPIRI_FIELDS = [
    ("Номінальна напруга мережі", "V"),
    ("Номінальний струм мережі", "A"),
    ("Номінальна вихідна напруга", "V"),
    ("Номінальна вихідна частота", "Hz"),
    ("Номінальний вихідний струм", "A"),
    ("Номінальна повна потужність", "VA"),
    ("Номінальна активна потужність", "W"),
    ("Номінальна напруга АКБ", "V"),
    ("Напруга повернення до мережі", "V"),
    ("Нижня напруга АКБ", "V"),
    ("Bulk / CV напруга", "V"),
    ("Float напруга", "V"),
    ("Тип АКБ (код PI30)", ""),
    ("Макс. струм заряду від мережі", "A"),
    ("Макс. загальний струм заряду", "A"),
    ("Діапазон AC input (код PI30)", ""),
    ("Пріоритет джерела виходу (код PI30)", ""),
    ("Пріоритет заряджання (код PI30)", ""),
    ("Макс. паралельних модулів", ""),
    ("Тип машини (код PI30)", ""),
    ("Топологія (код PI30)", ""),
    ("Режим виходу (код PI30)", ""),
    ("Напруга повернення з мережі на АКБ", "V"),
]


def parse_qpiri_fields(text: str) -> list[dict[str, str]]:
    s = text.strip().strip("\r\n")
    if s.startswith("("):
        s = s[1:]
    parts = s.split()

    rows: list[dict[str, str]] = []
    for i, value in enumerate(parts):
        if i < len(QPIRI_FIELDS):
            name, unit = QPIRI_FIELDS[i]
        else:
            name, unit = f"Додаткове поле PI30 #{i + 1}", ""
        rows.append({
            "index": str(i + 1),
            "name": name,
            "value": value,
            "unit": unit,
        })
    return rows
