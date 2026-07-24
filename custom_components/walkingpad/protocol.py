"""Pure protocol layer for the KingSmith WalkingPad A1 BLE interface.

Framing was reverse-engineered by ph4r05 (MIT):
https://github.com/ph4r05/ph4-walkingpad/blob/master/ph4_walkingpad/pad.py

Command packet:
    [0xf7, 0xa2, <cmd>, <arg>, <checksum>, 0xfd]
Preferences packet:
    [0xf7, 0xa6, <key>, <stype>, <b2>, <b1>, <b0>, <checksum>, 0xfd]
Checksum:
    byte[-2] = sum(byte[1:-2]) % 256

Notification payloads (status stream, ~750 ms cadence):
    Current status:  [0xf8, 0xa2, ...] length 20
    Last-run record: [0xf8, 0xa7, ...] length 20

This module is intentionally free of Home Assistant and bleak imports so it can
be unit tested in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

CMD_PREFIX = 0xF7
STATUS_PREFIX = 0xF8
SUFFIX = 0xFD

# Second header byte distinguishing frame families.
FAMILY_CMD_BASIC = 0xA2
FAMILY_CMD_PREFS = 0xA6
FAMILY_STATUS_CUR = 0xA2
FAMILY_STATUS_LAST = 0xA7

STATUS_PACKET_LENGTH = 20

# Speed on the wire is in tenths of km/h (0..60 = 0.0..6.0 km/h).
KMH_PER_MPH = 1.609344


class BeltState(IntEnum):
    """Raw belt_state field values reported by the pad."""

    IDLE = 0
    STARTING = 5
    RUNNING = 1
    STOPPING = 4
    STANDBY = 9


class Mode(IntEnum):
    """WalkingPad operating mode."""

    AUTOMAT = 0
    MANUAL = 1
    STANDBY = 2


class Status(IntEnum):
    """High-level status exposed to Home Assistant entities."""

    STOPPED = 0
    RUNNING = 1
    STARTING = 2
    STOPPING = 3
    STANDBY = 4
    DISCONNECTED = 100


STATUS_STR = {
    Status.STOPPED: "stopped",
    Status.RUNNING: "running",
    Status.STARTING: "starting",
    Status.STOPPING: "stopping",
    Status.STANDBY: "standby",
    Status.DISCONNECTED: "disconnected",
}


@dataclass
class TreadmillData:
    """Snapshot of decoded telemetry from a status notification."""

    status: Status = Status.DISCONNECTED
    mode: Mode = Mode.STANDBY
    speed_cmd: float = 0.0  # target speed in km/h (last set)
    speed_feedback: float = 0.0  # current belt speed in km/h
    distance_km: float = 0.0
    steps: int = 0
    duration_sec: int = 0
    last_button: int = 0


def _fix_crc(packet: bytearray) -> bytearray:
    """Set the checksum byte in-place. The A1 rejects packets with wrong sums."""
    packet[-2] = sum(packet[1:-2]) % 256
    return packet


def _int_to_3bytes(value: int) -> tuple[int, int, int]:
    """Big-endian 3-byte encoding used for time/distance/steps."""
    value &= 0xFFFFFF
    return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)


def _int_from_3bytes(data: bytes) -> int:
    """Inverse of :func:`_int_to_3bytes`."""
    return (data[0] << 16) | (data[1] << 8) | data[2]


# --- Command builders ------------------------------------------------------


def _basic_command(cmd: int, arg: int) -> bytes:
    """Build a 6-byte basic command packet: prefix, family, cmd, arg, crc, suffix."""
    packet = bytearray([CMD_PREFIX, FAMILY_CMD_BASIC, cmd, arg & 0xFF, 0x00, SUFFIX])
    return bytes(_fix_crc(packet))


def start_command() -> bytes:
    """Start the belt (mode-dependent; typically transitions to RUNNING)."""
    return _basic_command(0x04, 0x01)


def stop_command() -> bytes:
    """Stop the belt (speed 0)."""
    return set_speed_command_deci(0)


def set_speed_command_deci(speed_deci_kmh: int) -> bytes:
    """Set target speed. Argument is speed in tenths of km/h (0..60)."""
    speed_deci_kmh = max(0, min(int(speed_deci_kmh), 60))
    return _basic_command(0x01, speed_deci_kmh)


def switch_mode_command(mode: Mode) -> bytes:
    """Switch operating mode."""
    return _basic_command(0x02, int(mode))


def ask_stats_command() -> bytes:
    """Ask the pad to send its current status."""
    return _basic_command(0x00, 0x00)


# --- State decoding --------------------------------------------------------


def _decode_status(belt_state: int, mode: int) -> Status:
    """Map raw belt_state + mode to the high-level Status."""
    if mode == Mode.STANDBY:
        return Status.STANDBY
    if belt_state == BeltState.RUNNING:
        return Status.RUNNING
    if belt_state == BeltState.STARTING:
        return Status.STARTING
    if belt_state == BeltState.STOPPING:
        return Status.STOPPING
    return Status.STOPPED


def parse_state(payload: bytes | None) -> TreadmillData | None:
    """Decode a 20-byte 0xf8 0xa2 current-status notification.

    Returns None for anything else (last-run records, short packets, or
    packets that don't start with the current-status prefix).
    """
    if payload is None or len(payload) < STATUS_PACKET_LENGTH:
        return None
    if payload[0] != STATUS_PREFIX or payload[1] != FAMILY_STATUS_CUR:
        return None

    belt_state = payload[2]
    speed_deci = payload[3]  # tenths of km/h
    mode_raw = payload[4]
    duration_sec = _int_from_3bytes(payload[5:8])
    dist_10m = _int_from_3bytes(payload[8:11])  # in units of 10 m
    steps = _int_from_3bytes(payload[11:14])
    app_speed_deci = payload[14]
    last_button = payload[16]

    try:
        mode = Mode(mode_raw)
    except ValueError:
        mode = Mode.STANDBY

    return TreadmillData(
        status=_decode_status(belt_state, mode_raw),
        mode=mode,
        speed_cmd=app_speed_deci / 10.0,
        speed_feedback=speed_deci / 10.0,
        distance_km=dist_10m / 100.0,
        steps=steps,
        duration_sec=duration_sec,
        last_button=last_button,
    )
