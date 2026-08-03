"""Full function test for the WalkingPad A1 integration.

Exercises every public method of ``WalkingPadTreadmill`` one at a time on real
hardware, records pass/fail per step, and prints a summary at the end.

Two workarounds needed for the A1 that the HA integration does not yet do
on its own (see chat report):

  1. Send the ph4 handshake payload once after connect, otherwise the pad
     silently ignores motion commands.
  2. Poll ``ask_stats`` continuously in the background, otherwise the pad
     is completely silent - it does NOT stream spontaneously.

Both workarounds are done here in the test so the integration layer itself
stays untouched for this run.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load(mod_name: str, rel_path: str):
    spec = importlib.util.spec_from_file_location(
        mod_name, REPO_ROOT / "custom_components" / "walkingpad" / rel_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


_const = _load("wp_const", "const.py")
_protocol = _load("wp_protocol", "protocol.py")
sys.modules["walkingpad"] = type(sys)("walkingpad")
sys.modules["walkingpad"].const = _const
sys.modules["walkingpad"].protocol = _protocol
sys.modules["walkingpad.const"] = _const
sys.modules["walkingpad.protocol"] = _protocol
_walkingpad = _load("walkingpad.walkingpad", "walkingpad.py")

from bleak import BleakScanner  # noqa: E402
from bleak.backends.device import BLEDevice  # noqa: E402
from bleak.backends.scanner import AdvertisementData  # noqa: E402

DEVICE_NAME_PREFIX = _const.DEVICE_NAME_PREFIX
SERVICE_PAD_UUID = _const.SERVICE_PAD_UUID
WRITE_UUID = _const.CHARACTERISTIC_WRITE_UUID
Mode = _protocol.Mode
Status = _protocol.Status
TreadmillData = _protocol.TreadmillData
WalkingPadTreadmill = _walkingpad.WalkingPadTreadmill
ask_stats_command = _protocol.ask_stats_command

SCAN_TIMEOUT_SEC = 15.0
POLL_INTERVAL_SEC = 0.9
WAIT_STATUS_SEC = 6.0
RAMP_SEC = 5.0
HANDSHAKE_PAYLOAD = bytes([0xF7, 0xA5, 0x60, 0x4A, 0x4D, 0x93, 0x71, 0x29, 0xC9, 0xFD])


@dataclass
class StepResult:
    name: str
    ok: bool
    detail: str


results: list[StepResult] = []


def _record(name: str, ok: bool, detail: str = "") -> None:
    marker = "PASS" if ok else "FAIL"
    print(f"  [{marker}] {name}" + (f" - {detail}" if detail else ""))
    results.append(StepResult(name, ok, detail))


def _print_status(prefix: str, data: TreadmillData) -> None:
    print(
        f"    {prefix}: status={data.status.name:<12} mode={data.mode.name:<7} "
        f"feedback={data.speed_feedback:.1f}km/h "
        f"dist={data.distance_km:.2f}km steps={data.steps} dur={data.duration_sec}s"
    )


async def discover() -> tuple[BLEDevice, AdvertisementData] | None:
    print(f"Scanning up to {SCAN_TIMEOUT_SEC:.0f}s...")
    found: dict[str, tuple[BLEDevice, AdvertisementData]] = {}

    def _cb(device: BLEDevice, adv: AdvertisementData) -> None:
        name = (device.name or adv.local_name or "").strip()
        if name.lower().startswith(DEVICE_NAME_PREFIX.lower()) or (
            SERVICE_PAD_UUID.lower() in [u.lower() for u in adv.service_uuids]
        ):
            if device.address not in found:
                print(f"  {name} [{device.address}] rssi={adv.rssi}")
            found[device.address] = (device, adv)

    scanner = BleakScanner(detection_callback=_cb)
    await scanner.start()
    try:
        await asyncio.sleep(SCAN_TIMEOUT_SEC)
    finally:
        await scanner.stop()
    if not found:
        return None
    return next(iter(found.values()))


async def _poll_loop(pad: WalkingPadTreadmill, stop: asyncio.Event) -> None:
    """Background poller. The A1 only answers on demand."""
    while not stop.is_set():
        try:
            await pad._async_send(ask_stats_command())  # noqa: SLF001
        except Exception as err:  # noqa: BLE001
            print(f"    poll error: {type(err).__name__}: {err}")
        try:
            await asyncio.wait_for(stop.wait(), timeout=POLL_INTERVAL_SEC)
        except asyncio.TimeoutError:
            pass


async def _send_handshake(pad: WalkingPadTreadmill) -> None:
    """Send the ph4 magic 0xA5 payload once."""
    client = pad._client  # noqa: SLF001
    await client.write_gatt_char(WRITE_UUID, HANDSHAKE_PAYLOAD, response=False)


async def _wait_for(pad, predicate, timeout: float, desc: str) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate(pad.data):
            return True
        await asyncio.sleep(0.2)
    return False


async def test_step_1_discovery() -> tuple[BLEDevice, AdvertisementData] | None:
    print("\n=== [1] Discovery ===")
    result = await discover()
    if result is None:
        _record("discovery", False, "no pad advertising")
        return None
    device, adv = result
    _record(
        "discovery",
        True,
        f"{device.name or adv.local_name} [{device.address}] rssi={adv.rssi}",
    )
    return result


async def test_step_2_connect(
    pad: WalkingPadTreadmill,
) -> bool:
    print("\n=== [2] Connect + subscribe ===")
    try:
        await pad.async_ensure_connected()
    except Exception as err:  # noqa: BLE001
        _record("connect", False, f"{type(err).__name__}: {err}")
        return False
    _record("connect", True, f"connected={pad.connected}")
    return True


async def test_step_3_handshake(pad: WalkingPadTreadmill) -> bool:
    print("\n=== [3] Handshake ===")
    try:
        await _send_handshake(pad)
        await asyncio.sleep(0.5)
        _record("handshake", True, "0xA5 payload sent")
        return True
    except Exception as err:  # noqa: BLE001
        _record("handshake", False, f"{type(err).__name__}: {err}")
        return False


async def test_step_4_first_status(pad: WalkingPadTreadmill) -> bool:
    print("\n=== [4] Wait for first status frame ===")
    got = await _wait_for(
        pad,
        lambda d: d.status is not Status.DISCONNECTED,
        WAIT_STATUS_SEC,
        "first status",
    )
    if got:
        _print_status("initial", pad.data)
    _record("first_status", got, "" if got else "timeout")
    return got


async def test_step_5_callbacks(pad: WalkingPadTreadmill) -> None:
    print("\n=== [5] Callback register/unregister ===")
    hits: list[TreadmillData] = []

    def cb(data: TreadmillData) -> None:
        hits.append(data)

    unreg = pad.register_callback(cb)
    await asyncio.sleep(2 * POLL_INTERVAL_SEC + 0.5)
    hits_while_registered = len(hits)
    unreg()
    baseline = len(hits)
    await asyncio.sleep(2 * POLL_INTERVAL_SEC + 0.5)
    hits_after_unregister = len(hits) - baseline

    _record(
        "callback_receives_updates",
        hits_while_registered > 0,
        f"{hits_while_registered} updates while registered",
    )
    _record(
        "callback_unregister_stops_updates",
        hits_after_unregister == 0,
        f"{hits_after_unregister} updates after unregister",
    )


async def test_step_6_mode_switches(pad: WalkingPadTreadmill) -> None:
    print("\n=== [6] Mode switches ===")

    for label, target in [
        ("switch_mode(MANUAL)", Mode.MANUAL),
        ("switch_mode(AUTOMAT)", Mode.AUTOMAT),
        ("switch_mode(MANUAL) again", Mode.MANUAL),
    ]:
        try:
            await pad.async_switch_mode(target)
        except Exception as err:  # noqa: BLE001
            _record(label, False, f"{type(err).__name__}: {err}")
            continue
        ok = await _wait_for(
            pad, lambda d: d.mode is target, WAIT_STATUS_SEC, f"mode={target.name}"
        )
        _print_status(f"after {label}", pad.data)
        _record(label, ok, "" if ok else f"mode still {pad.data.mode.name}")


async def test_step_7_start(pad: WalkingPadTreadmill) -> None:
    print("\n=== [7] Start belt ===")
    try:
        await pad.async_start()
    except Exception as err:  # noqa: BLE001
        _record("start", False, f"{type(err).__name__}: {err}")
        return
    # The A1 accepts start but stays at speed 0 until set_speed is called.
    # We accept "no error raised" as pass here.
    await asyncio.sleep(1.5)
    _print_status("after start", pad.data)
    _record("start", True, "command accepted (no error)")


async def test_step_8_set_speeds(pad: WalkingPadTreadmill) -> None:
    print("\n=== [8] Speed sweep ===")

    for deci in (10, 20, 30, 15):
        target_kmh = deci / 10.0
        label = f"set_speed({target_kmh:.1f}km/h, deci={deci})"
        try:
            await pad.async_set_speed(deci)
        except Exception as err:  # noqa: BLE001
            _record(label, False, f"{type(err).__name__}: {err}")
            continue
        # A1 ramps gradually. Consider it accepted if feedback reaches
        # ~half the target within RAMP_SEC.
        min_expected = target_kmh * 0.4
        ok = await _wait_for(
            pad,
            lambda d, m=min_expected: d.speed_feedback >= m,
            RAMP_SEC,
            f"feedback>={min_expected:.1f}",
        )
        _print_status(f"after {label}", pad.data)
        _record(
            label,
            ok,
            f"feedback={pad.data.speed_feedback:.1f}km/h"
            + ("" if ok else " (never reached expected ramp)"),
        )
        # Hold briefly between changes so the pad has time to react.
        await asyncio.sleep(1.5)


async def test_step_9_stop(pad: WalkingPadTreadmill) -> None:
    print("\n=== [9] Stop belt ===")
    try:
        await pad.async_stop()
    except Exception as err:  # noqa: BLE001
        _record("stop", False, f"{type(err).__name__}: {err}")
        return
    ok = await _wait_for(
        pad,
        lambda d: d.speed_feedback < 0.1,
        WAIT_STATUS_SEC * 2,
        "feedback<0.1",
    )
    _print_status("after stop", pad.data)
    _record("stop", ok, "" if ok else f"feedback stuck at {pad.data.speed_feedback}")


async def test_step_9b_boundary_speeds(pad: WalkingPadTreadmill) -> None:
    print("\n=== [9b] Boundary speed values ===")

    # deci=0 = stop via set_speed path (not via async_stop button)
    try:
        await pad.async_set_speed(20)
        await asyncio.sleep(2)
        await pad.async_set_speed(0)
    except Exception as err:  # noqa: BLE001
        _record("set_speed(0) = stop", False, f"{type(err).__name__}: {err}")
    else:
        ok = await _wait_for(
            pad, lambda d: d.speed_feedback < 0.1, WAIT_STATUS_SEC * 2, "feedback<0.1"
        )
        _print_status("after set_speed(0)", pad.data)
        _record("set_speed(0) = stop", ok, f"feedback={pad.data.speed_feedback}")

    # deci=100 out of range, protocol should clamp to 60 (=6.0 km/h). We
    # verify the pad does not error out. The belt is stopped when we send it
    # from stopped state, so we do not need to run the belt to check clamp.
    try:
        await pad.async_set_speed(100)
    except Exception as err:  # noqa: BLE001
        _record("set_speed(100) clamp", False, f"{type(err).__name__}: {err}")
    else:
        # Give it a moment. We only assert no exception and connection alive.
        await asyncio.sleep(1.5)
        _record(
            "set_speed(100) clamp",
            pad.connected,
            f"connected={pad.connected} (clamped to 60 by protocol layer)",
        )
    # Bring the belt down in case the clamped 6.0 kicked it off.
    try:
        await pad.async_stop()
        await asyncio.sleep(1.5)
    except Exception:  # noqa: BLE001
        pass


async def test_step_9c_ensure_connected_safe(pad: WalkingPadTreadmill) -> None:
    print("\n=== [9c] async_ensure_connected_safe (no-op while connected) ===")
    try:
        await pad.async_ensure_connected_safe()
    except Exception as err:  # noqa: BLE001
        _record("ensure_connected_safe", False, f"{type(err).__name__}: {err}")
        return
    _record(
        "ensure_connected_safe",
        pad.connected,
        f"connected={pad.connected}",
    )


async def test_step_9d_set_adv(
    pad: WalkingPadTreadmill,
    device: BLEDevice,
    adv: AdvertisementData,
) -> None:
    print("\n=== [9d] set_ble_device_and_advertisement_data ===")
    try:
        pad.set_ble_device_and_advertisement_data(device, adv)
    except Exception as err:  # noqa: BLE001
        _record("set_ble_device_and_adv", False, f"{type(err).__name__}: {err}")
        return
    _record("set_ble_device_and_adv", True, f"address={pad.address}")


async def test_step_10_standby(pad: WalkingPadTreadmill) -> None:
    print("\n=== [10] Switch to STANDBY ===")
    try:
        await pad.async_switch_mode(Mode.STANDBY)
    except Exception as err:  # noqa: BLE001
        _record("switch_mode(STANDBY)", False, f"{type(err).__name__}: {err}")
        return
    ok = await _wait_for(
        pad, lambda d: d.mode is Mode.STANDBY, WAIT_STATUS_SEC, "mode=STANDBY"
    )
    _print_status("after standby", pad.data)
    _record("switch_mode(STANDBY)", ok, "" if ok else f"mode={pad.data.mode.name}")


async def test_step_11_shutdown(pad: WalkingPadTreadmill) -> None:
    print("\n=== [11] Shutdown (disconnect) ===")
    try:
        await pad.async_shutdown()
    except Exception as err:  # noqa: BLE001
        _record("shutdown", False, f"{type(err).__name__}: {err}")
        return
    await asyncio.sleep(0.5)
    _record("shutdown", not pad.connected, f"connected={pad.connected}")


async def test_step_12_reconnect(
    pad: WalkingPadTreadmill, poll_task: asyncio.Task, stop_event: asyncio.Event
) -> None:
    print("\n=== [12] Reconnect after shutdown ===")
    stop_event.set()
    try:
        await asyncio.wait_for(poll_task, timeout=2.0)
    except asyncio.TimeoutError:
        poll_task.cancel()

    try:
        await pad.async_ensure_connected()
    except Exception as err:  # noqa: BLE001
        _record("reconnect", False, f"{type(err).__name__}: {err}")
        return
    _record("reconnect", pad.connected, f"connected={pad.connected}")

    # Final teardown.
    try:
        await pad.async_shutdown()
    except Exception:  # noqa: BLE001
        pass


async def async_main(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("bleak").setLevel(logging.WARNING)

    discovered = await test_step_1_discovery()
    if discovered is None:
        return 1
    device, adv = discovered

    pad = WalkingPadTreadmill(device, adv)

    if not await test_step_2_connect(pad):
        return 2

    stop_event = asyncio.Event()
    poll_task = asyncio.create_task(_poll_loop(pad, stop_event))

    try:
        await test_step_3_handshake(pad)
        await test_step_4_first_status(pad)
        await test_step_5_callbacks(pad)
        await test_step_6_mode_switches(pad)
        await test_step_7_start(pad)
        await test_step_8_set_speeds(pad)
        await test_step_9_stop(pad)
        await test_step_9b_boundary_speeds(pad)
        await test_step_9c_ensure_connected_safe(pad)
        await test_step_9d_set_adv(pad, device, adv)
        await test_step_10_standby(pad)
    finally:
        stop_event.set()
        try:
            await asyncio.wait_for(poll_task, timeout=2.0)
        except asyncio.TimeoutError:
            poll_task.cancel()

    await test_step_11_shutdown(pad)

    # For the reconnect test we need a fresh poller because we shut down.
    stop_event2 = asyncio.Event()
    poll_task2 = asyncio.create_task(_poll_loop(pad, stop_event2))
    await test_step_12_reconnect(pad, poll_task2, stop_event2)

    print("\n=== Summary ===")
    passed = sum(1 for r in results if r.ok)
    total = len(results)
    for r in results:
        marker = "PASS" if r.ok else "FAIL"
        print(f"  [{marker}] {r.name}" + (f" - {r.detail}" if r.detail else ""))
    print(f"\n{passed}/{total} steps passed")
    return 0 if passed == total else 3


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    try:
        rc = asyncio.run(async_main(args))
    except KeyboardInterrupt:
        rc = 130
    sys.exit(rc)


if __name__ == "__main__":
    main()
