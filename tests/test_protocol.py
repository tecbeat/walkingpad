"""Unit tests for the WalkingPad A1 wire protocol.

Verifies against the reverse-engineered byte sequences from ph4-walkingpad:
https://github.com/ph4r05/ph4-walkingpad/blob/master/ph4_walkingpad/pad.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PROTOCOL_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "walkingpad"
    / "protocol.py"
)
_spec = importlib.util.spec_from_file_location("walkingpad_protocol", _PROTOCOL_PATH)
assert _spec is not None and _spec.loader is not None
_protocol = importlib.util.module_from_spec(_spec)
sys.modules["walkingpad_protocol"] = _protocol
_spec.loader.exec_module(_protocol)

Mode = _protocol.Mode
Status = _protocol.Status
_fix_crc = _protocol._fix_crc
parse_state = _protocol.parse_state
set_speed_command_deci = _protocol.set_speed_command_deci
start_command = _protocol.start_command
stop_command = _protocol.stop_command
switch_mode_command = _protocol.switch_mode_command


def _crc_ok(packet: bytes) -> bool:
    return packet[-2] == sum(packet[1:-2]) % 256


def test_fix_crc_matches_ph4_formula() -> None:
    """Checksum is sum(bytes[1..-3]) mod 256, written into byte[-2]."""
    packet = bytearray([0xF7, 0xA2, 0x01, 0x1E, 0x00, 0xFD])
    _fix_crc(packet)
    assert packet[-2] == (0xA2 + 0x01 + 0x1E) % 256
    assert packet[-2] == 0xC1


def test_start_command_frames_correctly() -> None:
    packet = start_command()
    assert packet[0] == 0xF7
    assert packet[1] == 0xA2
    assert packet[2] == 0x04  # start
    assert packet[3] == 0x01
    assert packet[-1] == 0xFD
    assert _crc_ok(packet)


def test_set_speed_encodes_deci_kmh() -> None:
    """Speed argument is the pad's tenths-of-kmh value."""
    packet = set_speed_command_deci(30)  # 3.0 km/h
    assert packet[2] == 0x01
    assert packet[3] == 30
    assert _crc_ok(packet)


def test_set_speed_clamps_to_valid_range() -> None:
    assert set_speed_command_deci(-5)[3] == 0
    assert set_speed_command_deci(999)[3] == 60


def test_stop_command_is_speed_zero() -> None:
    stop = stop_command()
    zero_speed = set_speed_command_deci(0)
    assert stop == zero_speed


def test_switch_mode_manual() -> None:
    packet = switch_mode_command(Mode.MANUAL)
    assert packet[2] == 0x02
    assert packet[3] == int(Mode.MANUAL)
    assert _crc_ok(packet)


def test_parse_state_decodes_example_from_ph4_readme() -> None:
    """The example status frame in the ph4-walkingpad README.

    Bytes: f8 a2 01 0f 01 00 0f d1 00 00 ab 00 12 ae 3c 00 00 00 3a fd
    Meaning per README:
      - belt_state = 1 (running, ph4 reference variant)
      - speed = 0x0f = 15  -> 1.5 km/h
      - manual mode flag = 1
      - time = 0x000fd1 = 4049 s
      - distance = 0x0000ab = 171 (units of 10 m) -> 1.71 km
      - steps = 0x0012ae = 4782
    """
    payload = bytes.fromhex("f8a2010f01000fd10000ab0012ae3c0000003afd")
    data = parse_state(payload)
    assert data is not None
    assert data.status is Status.RUNNING
    assert data.mode is Mode.MANUAL
    assert data.speed_feedback == 1.5
    assert data.duration_sec == 4049
    assert data.distance_km == 1.71
    assert data.steps == 4782


def test_parse_state_running_state_2_from_real_a1() -> None:
    """Real 2026 A1 unit reports belt_state=2 while running.

    Frame observed during dev/ble_baseline_run.py at feedback=1.5 km/h.
    Both belt_state=1 (ph4) and belt_state=2 (real unit) must map to RUNNING.
    """
    payload = bytes.fromhex("f8a2020f010000030000000000002d000000e4fd")
    data = parse_state(payload)
    assert data is not None
    assert data.status is Status.RUNNING
    assert data.speed_feedback == 1.5


def test_parse_state_running_with_zero_feedback_is_stopping() -> None:
    """belt_state=2 but feedback=0 means the belt is ramping down.

    Prevents the status entity from showing 'running' during the last
    second or so of a stop transition.
    """
    payload = bytes.fromhex("f8a20200010000030000000000002d000000d5fd")
    data = parse_state(payload)
    assert data is not None
    assert data.status is Status.STOPPING


def test_parse_state_standby_reports_status_standby() -> None:
    payload = bytes.fromhex("f8a205000200000000000000000000000000a9fd")
    data = parse_state(payload)
    assert data is not None
    assert data.mode is Mode.STANDBY
    assert data.status is Status.STANDBY


def test_handshake_command_matches_ph4_reference() -> None:
    """The 0xA5 handshake payload is copied verbatim from ph4-walkingpad."""
    packet = _protocol.handshake_command()
    assert packet == bytes.fromhex("f7a5604a4d937129c9fd")


def test_ask_stats_command_frames_correctly() -> None:
    packet = _protocol.ask_stats_command()
    assert packet[0:2] == b"\xf7\xa2"
    assert packet[2] == 0x00
    assert packet[3] == 0x00
    assert packet[-1] == 0xFD
    assert _crc_ok(packet)


def test_parse_state_rejects_short_payload() -> None:
    assert parse_state(b"\xf8\xa2\x00") is None


def test_parse_state_rejects_wrong_prefix() -> None:
    payload = bytes.fromhex("f8a7010f01000fd10000ab0012ae3c0000003afd")
    assert parse_state(payload) is None


def test_parse_state_rejects_none() -> None:
    assert parse_state(None) is None
