"""Integration tests for the WalkingPad connection layer against a fake pad.

These tests wire ``WalkingPadTreadmill`` up to a ``FakePad`` that behaves like
a KingSmith A1 over BLE: it captures every ``write_gatt_char`` payload sent to
the write characteristic (0xfe02) and lets the test push notification frames
back through the registered handler (0xfe01). The connection layer is
otherwise unmodified -- so what runs here is the real code that will run in
Home Assistant.
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

# conftest.py has loaded the module under sys.modules["wp_pkg.walkingpad"].
# Use the ``wp_pkg.protocol`` alias, because that is the module walkingpad.py
# actually imports from -- using the ``walkingpad_protocol`` alias would give
# us a second, distinct copy of the IntEnum classes and break ``is`` checks.
_protocol = sys.modules["wp_pkg.protocol"]
_walkingpad = sys.modules["wp_pkg.walkingpad"]

Mode = _protocol.Mode
Status = _protocol.Status
parse_state = _protocol.parse_state

WalkingPadTreadmill = _walkingpad.WalkingPadTreadmill
MIN_COMMAND_SPACING_SEC = _walkingpad.MIN_COMMAND_SPACING_SEC

CHARACTERISTIC_WRITE_UUID = "0000fe02-0000-1000-8000-00805f9b34fb"
CHARACTERISTIC_NOTIFY_STATE_UUID = "0000fe01-0000-1000-8000-00805f9b34fb"


class FakePad:
    """A KingSmith A1 simulator.

    Records every command byte the treadmill layer writes; lets the test push
    status notifications back through the handler the treadmill registered.
    """

    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.write_response_flags: list[bool] = []
        self.is_connected = True
        self._notify_handler = None
        self._disconnected_callback = None

    async def start_notify(self, uuid: str, handler) -> None:
        assert uuid == CHARACTERISTIC_NOTIFY_STATE_UUID
        self._notify_handler = handler

    async def stop_notify(self, uuid: str) -> None:
        assert uuid == CHARACTERISTIC_NOTIFY_STATE_UUID
        self._notify_handler = None

    async def write_gatt_char(
        self, uuid: str, data: bytes, *, response: bool = False
    ) -> None:
        assert uuid == CHARACTERISTIC_WRITE_UUID
        self.writes.append(bytes(data))
        self.write_response_flags.append(response)

    async def disconnect(self) -> None:
        self.is_connected = False
        if self._disconnected_callback is not None:
            self._disconnected_callback(self)

    def push_status(self, payload: bytes) -> None:
        """Simulate a notification from the pad."""
        assert self._notify_handler is not None, "start_notify not called"
        self._notify_handler(0, bytearray(payload))

    def simulate_disconnect(self) -> None:
        """Simulate the pad unexpectedly dropping the link."""
        self.is_connected = False
        if self._disconnected_callback is not None:
            self._disconnected_callback(self)


def _make_ble_device() -> object:
    """Minimal BLEDevice stand-in with the attributes walkingpad.py touches."""
    device = MagicMock()
    device.address = "AA:BB:CC:DD:EE:FF"
    device.name = "WalkingPad-A1"
    return device


@pytest.fixture
def fake_pad() -> FakePad:
    return FakePad()


@pytest_asyncio.fixture
async def treadmill(monkeypatch, fake_pad):
    """A connected WalkingPadTreadmill talking to the FakePad.

    The background poll loop is neutralised (interval set to 1 hour) so tests
    can make exact assertions about which commands the code under test sent.
    Post-connect handshake writes are consumed here as well.
    """

    async def _fake_establish_connection(
        client_class, ble_device, name, disconnected_callback, **_kwargs
    ):
        fake_pad._disconnected_callback = disconnected_callback
        return fake_pad

    monkeypatch.setattr(
        _walkingpad, "establish_connection", _fake_establish_connection
    )
    monkeypatch.setattr(_walkingpad, "POLL_INTERVAL_SEC", 3600)

    treadmill = WalkingPadTreadmill(_make_ble_device())
    await treadmill.async_ensure_connected()
    assert treadmill.connected
    # Let the initial poll iteration (which fires once immediately) run and
    # be captured, then discard so tests see a clean write log.
    await asyncio.sleep(0)
    fake_pad.writes.clear()
    fake_pad.write_response_flags.clear()
    yield treadmill
    # Cancel the background poll task cleanly after each test.
    await treadmill.async_shutdown()


def _make_status_frame(
    *,
    belt_state: int = 0,
    speed_deci: int = 0,
    mode: int = int(Mode.STANDBY),
    duration: int = 0,
    dist_10m: int = 0,
    steps: int = 0,
    app_speed_deci: int = 0,
    last_button: int = 0,
) -> bytes:
    """Build a 20-byte 0xf8 0xa2 status frame."""

    def _b3(v: int) -> bytes:
        return bytes([(v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF])

    frame = bytearray(20)
    frame[0] = 0xF8
    frame[1] = 0xA2
    frame[2] = belt_state
    frame[3] = speed_deci
    frame[4] = mode
    frame[5:8] = _b3(duration)
    frame[8:11] = _b3(dist_10m)
    frame[11:14] = _b3(steps)
    frame[14] = app_speed_deci
    frame[16] = last_button
    frame[19] = 0xFD
    return bytes(frame)


def _crc_ok(packet: bytes) -> bool:
    return packet[-2] == sum(packet[1:-2]) % 256


# --- Test cases -------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_registers_notify_handler(monkeypatch, fake_pad):
    async def _fake_establish_connection(*_args, **_kwargs):
        fake_pad._disconnected_callback = _args[3] if len(_args) >= 4 else None
        return fake_pad

    monkeypatch.setattr(
        _walkingpad, "establish_connection", _fake_establish_connection
    )
    treadmill = WalkingPadTreadmill(_make_ble_device())
    await treadmill.async_ensure_connected()

    assert treadmill.connected
    assert fake_pad._notify_handler is not None


@pytest.mark.asyncio
async def test_start_sends_start_and_default_speed(treadmill, fake_pad):
    """async_start must arm the belt (start_belt) AND set a non-zero speed.

    The A1 ignores a bare start_belt; the belt only moves once a set_speed
    command follows in the same session.
    """
    # Simulate the pad already being in MANUAL mode so no mode-switch is sent.
    fake_pad.push_status(_make_status_frame(mode=int(Mode.MANUAL)))
    fake_pad.writes.clear()
    fake_pad.write_response_flags.clear()

    await treadmill.async_start()

    assert len(fake_pad.writes) == 2
    start_packet, speed_packet = fake_pad.writes
    assert start_packet[0:2] == b"\xf7\xa2"
    assert start_packet[2] == 0x04  # start command byte
    assert start_packet[3] == 0x01
    assert _crc_ok(start_packet)
    assert speed_packet[2] == 0x01  # set-speed command byte
    assert speed_packet[3] > 0  # non-zero, otherwise belt won't move
    assert _crc_ok(speed_packet)
    assert fake_pad.write_response_flags == [False, False]


@pytest.mark.asyncio
async def test_set_speed_from_stopped_arms_belt_first(treadmill, fake_pad):
    """From MANUAL/stopped, set_speed must send start_belt then set_speed.

    Without the intermediate start_belt the A1 accepts the frame but the
    belt does not move.
    """
    fake_pad.push_status(_make_status_frame(mode=int(Mode.MANUAL)))
    fake_pad.writes.clear()

    await treadmill.async_set_speed(30)  # 3.0 km/h

    assert len(fake_pad.writes) == 2
    start_packet, speed_packet = fake_pad.writes
    assert start_packet[2] == 0x04  # start_belt
    assert speed_packet[2] == 0x01  # set-speed
    assert speed_packet[3] == 30
    assert _crc_ok(start_packet)
    assert _crc_ok(speed_packet)


@pytest.mark.asyncio
async def test_set_speed_while_running_skips_start_belt(treadmill, fake_pad):
    """If the belt is already running, set_speed must NOT re-send start_belt."""
    fake_pad.push_status(
        _make_status_frame(belt_state=2, speed_deci=15, mode=int(Mode.MANUAL))
    )
    assert treadmill.data.status is Status.RUNNING
    fake_pad.writes.clear()

    await treadmill.async_set_speed(30)

    assert len(fake_pad.writes) == 1
    assert fake_pad.writes[0][2] == 0x01  # only set-speed
    assert fake_pad.writes[0][3] == 30


@pytest.mark.asyncio
async def test_stop_sends_speed_zero(treadmill, fake_pad):
    fake_pad.push_status(_make_status_frame(mode=int(Mode.MANUAL)))
    fake_pad.writes.clear()

    await treadmill.async_stop()

    assert len(fake_pad.writes) == 1
    packet = fake_pad.writes[0]
    assert packet[2] == 0x01
    assert packet[3] == 0


@pytest.mark.asyncio
async def test_start_from_standby_wakes_and_starts(treadmill, fake_pad):
    """From STANDBY, async_start must send: switch_manual, start_belt, set_speed."""
    fake_pad.push_status(_make_status_frame(belt_state=5, mode=int(Mode.STANDBY)))
    fake_pad.writes.clear()

    await treadmill.async_start()

    assert len(fake_pad.writes) == 3
    mode_switch, start, set_speed = fake_pad.writes
    assert mode_switch[2] == 0x02
    assert mode_switch[3] == int(Mode.MANUAL)
    assert start[2] == 0x04
    assert set_speed[2] == 0x01
    assert set_speed[3] > 0
    for pkt in (mode_switch, start, set_speed):
        assert _crc_ok(pkt)


@pytest.mark.asyncio
async def test_set_speed_from_standby_wakes_and_arms(treadmill, fake_pad):
    fake_pad.push_status(_make_status_frame(belt_state=5, mode=int(Mode.STANDBY)))
    fake_pad.writes.clear()

    await treadmill.async_set_speed(20)

    assert len(fake_pad.writes) == 3
    mode_switch, start, set_speed = fake_pad.writes
    assert mode_switch[3] == int(Mode.MANUAL)
    assert start[2] == 0x04
    assert set_speed[2] == 0x01
    assert set_speed[3] == 20


@pytest.mark.asyncio
async def test_stop_does_not_switch_mode(treadmill, fake_pad):
    """Stop must work in any mode without an extra mode-switch write."""
    fake_pad.push_status(_make_status_frame(mode=int(Mode.STANDBY)))
    fake_pad.writes.clear()

    await treadmill.async_stop()

    assert len(fake_pad.writes) == 1


@pytest.mark.asyncio
async def test_status_notification_updates_data_and_fires_callback(
    treadmill, fake_pad
):
    received: list = []
    treadmill.register_callback(received.append)

    frame = _make_status_frame(
        belt_state=2,  # RUNNING on real A1
        speed_deci=15,  # 1.5 km/h
        mode=int(Mode.MANUAL),
        duration=4049,
        dist_10m=171,
        steps=4782,
        app_speed_deci=60,
    )
    fake_pad.push_status(frame)

    assert treadmill.data.status is Status.RUNNING
    assert treadmill.data.mode is Mode.MANUAL
    assert treadmill.data.speed_feedback == 1.5
    assert treadmill.data.distance_km == 1.71
    assert treadmill.data.steps == 4782
    assert treadmill.data.duration_sec == 4049
    assert received  # callback was fired
    assert received[-1] is treadmill.data


@pytest.mark.asyncio
async def test_invalid_status_frame_is_ignored(treadmill, fake_pad):
    initial = treadmill.data
    fake_pad.push_status(b"\xff\x00\x01")  # too short, not 0xf8 0xa2

    assert treadmill.data is initial  # unchanged


@pytest.mark.asyncio
async def test_disconnect_callback_marks_status_disconnected(treadmill, fake_pad):
    fake_pad.push_status(
        _make_status_frame(belt_state=2, speed_deci=10, mode=int(Mode.MANUAL))
    )
    assert treadmill.data.status is Status.RUNNING

    received: list = []
    treadmill.register_callback(received.append)

    fake_pad.simulate_disconnect()

    assert not treadmill.connected
    assert treadmill.data.status is Status.DISCONNECTED
    assert received[-1].status is Status.DISCONNECTED


@pytest.mark.asyncio
async def test_command_spacing_enforced(monkeypatch, treadmill, fake_pad):
    """Consecutive commands wait MIN_COMMAND_SPACING_SEC between writes."""
    fake_pad.push_status(_make_status_frame(mode=int(Mode.MANUAL)))
    fake_pad.writes.clear()

    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def _tracking_sleep(seconds: float) -> None:
        # Only record waits that look like the spacing wait (positive, small)
        # to avoid picking up the poll-loop's own sleep or teardown sleeps.
        if 0 < seconds < 5:
            sleeps.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(_walkingpad.asyncio, "sleep", _tracking_sleep)

    await treadmill.async_stop()
    await treadmill.async_stop()

    assert len(fake_pad.writes) == 2
    assert sleeps, "second command must sleep for spacing"
    assert max(sleeps) > MIN_COMMAND_SPACING_SEC / 2


@pytest.mark.asyncio
async def test_shutdown_stops_notifications_and_disconnects(treadmill, fake_pad):
    await treadmill.async_shutdown()

    assert not fake_pad.is_connected
    assert fake_pad._notify_handler is None


@pytest.mark.asyncio
async def test_unexpected_disconnect_schedules_reconnect(monkeypatch, fake_pad):
    """After a lost BLE session the treadmill must reconnect on its own.

    Regression test: previously ``_disconnected_callback`` marked the state
    as DISCONNECTED and stopped the poll loop, but never tried to reconnect.
    HA entities stayed unavailable until the user reloaded the config entry.
    """
    connect_calls = 0

    async def _fake_establish_connection(
        client_class, ble_device, name, disconnected_callback, **_kwargs
    ):
        nonlocal connect_calls
        connect_calls += 1
        fake_pad.is_connected = True
        fake_pad._disconnected_callback = disconnected_callback
        return fake_pad

    monkeypatch.setattr(
        _walkingpad, "establish_connection", _fake_establish_connection
    )
    monkeypatch.setattr(_walkingpad, "POLL_INTERVAL_SEC", 3600)
    monkeypatch.setattr(_walkingpad, "RECONNECT_INITIAL_DELAY_SEC", 0.05)
    monkeypatch.setattr(_walkingpad, "RECONNECT_MAX_DELAY_SEC", 0.05)

    treadmill = WalkingPadTreadmill(_make_ble_device())
    await treadmill.async_ensure_connected()
    assert connect_calls == 1
    assert treadmill.connected

    fake_pad.simulate_disconnect()
    assert not treadmill.connected

    # Give the scheduled reconnect task time to fire.
    for _ in range(20):
        if connect_calls >= 2:
            break
        await asyncio.sleep(0.05)

    assert connect_calls >= 2, "expected auto-reconnect after unexpected disconnect"
    assert treadmill.connected

    await treadmill.async_shutdown()
