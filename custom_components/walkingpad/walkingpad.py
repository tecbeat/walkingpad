"""BLE connection manager for the KingSmith WalkingPad A1.

Wraps bleak (via bleak-retry-connector) so the treadmill can be driven through
any Home Assistant Bluetooth adapter, including ESP32 Bluetooth proxies running
in active mode. Proxy handling is transparent: as long as
``async_ble_device_from_address`` returns a connectable device, the connection
is routed through whichever adapter can reach it.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import replace

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakError
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    BleakNotFoundError,
    establish_connection,
)

from .const import (
    CHARACTERISTIC_NOTIFY_STATE_UUID,
    CHARACTERISTIC_WRITE_UUID,
    POLL_INTERVAL_SEC,
)
from .protocol import (
    Mode,
    Status,
    TreadmillData,
    ask_stats_command,
    handshake_command,
    parse_state,
    set_speed_command_deci,
    start_command,
    stop_command,
    switch_mode_command,
)

_LOGGER = logging.getLogger(__name__)

# Errors that mean "try again later" rather than a hard failure.
TRANSIENT_ERRORS = (BleakError, BleakNotFoundError, TimeoutError, EOFError)

# Minimum spacing between commands. The A1 drops commands sent too close
# together (~750 ms is the app's own status poll cadence).
MIN_COMMAND_SPACING_SEC = 0.7

# Pause between waking the pad from STANDBY and sending walking commands.
# The A1 needs a moment to bring the belt controller online after a mode
# switch; sending start_belt immediately after switch_mode(MANUAL) can be
# silently dropped.
WAKE_SETTLE_DELAY_SEC = 1.0

# Grace window after issuing async_start_walking / async_stop during which
# the pad's own status frames are overridden with the intended status.
# The A1 keeps reporting the previous state for a second or two while the
# belt spins up / down, and without this window a rapid second toggle
# click would race the poll loop and re-trigger the wrong action.
OPTIMISTIC_STATUS_WINDOW_SEC = 3.0

# Backoff schedule for auto-reconnect after an unexpected disconnect. Starts
# small so a transient BLE hiccup recovers within seconds, then backs off so
# a truly offline pad does not busy-poll the ESP32 proxy.
RECONNECT_INITIAL_DELAY_SEC = 2.0
RECONNECT_MAX_DELAY_SEC = 60.0

TreadmillCallback = Callable[[TreadmillData], None]


class WalkingPadTreadmill:
    """Maintains a connection to a single WalkingPad A1 and decodes telemetry."""

    def __init__(
        self,
        ble_device: BLEDevice,
        advertisement_data: AdvertisementData | None = None,
    ) -> None:
        self._ble_device = ble_device
        self._advertisement_data = advertisement_data
        self._client: BleakClientWithServiceCache | None = None
        self._connect_lock = asyncio.Lock()
        self._operation_lock = asyncio.Lock()
        self._data = TreadmillData()
        self._callbacks: list[TreadmillCallback] = []
        self._expected_disconnect = False
        self._connected = False
        self._last_command_at: float = 0.0
        self._poll_task: asyncio.Task[None] | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        # Mode the pad should be in for walking commands (start, set_speed).
        # Users can change this via the mode select entity; the integration
        # will only send switch_mode when the pad's current mode differs.
        self._preferred_mode: Mode = Mode.MANUAL
        # Serialises the multi-step start sequence (wake → wait → arm →
        # set_speed) so a mid-sequence toggle click is ignored instead of
        # queueing a second, overlapping sequence.
        self._toggle_lock = asyncio.Lock()
        # Optimistic status pinning. When the user starts or stops the
        # belt, the pad keeps reporting the previous status for a second
        # or two. During that grace window we overrule the pad's status
        # frames with the intended one so the UI (and the toggle button)
        # sees the change instantly instead of racing the poll loop.
        self._optimistic_status: Status | None = None
        self._optimistic_until: float = 0.0

    @property
    def address(self) -> str:
        return self._ble_device.address

    @property
    def name(self) -> str:
        return self._ble_device.name or self._ble_device.address

    @property
    def data(self) -> TreadmillData:
        return self._data

    @property
    def connected(self) -> bool:
        return (
            self._connected
            and self._client is not None
            and self._client.is_connected
        )

    @property
    def preferred_mode(self) -> Mode:
        return self._preferred_mode

    def set_preferred_mode(self, mode: Mode) -> None:
        """Store the mode the pad should be in for walking commands.

        Only MANUAL or AUTOMAT make sense here — STANDBY is not a
        walking mode. Callers passing STANDBY are silently coerced to
        MANUAL so the walking flow always has a valid target.

        This does NOT send anything to the pad — the mode select entity
        sends switch_mode itself via async_switch_mode. It only records
        the preference so subsequent start_walking / set_speed calls
        know whether a switch_mode is needed.
        """
        if mode is Mode.STANDBY:
            _LOGGER.debug(
                "%s: refusing to set STANDBY as preferred walking mode, using MANUAL",
                self.name,
            )
            mode = Mode.MANUAL
        self._preferred_mode = mode

    def set_ble_device_and_advertisement_data(
        self, ble_device: BLEDevice, advertisement_data: AdvertisementData
    ) -> None:
        self._ble_device = ble_device
        self._advertisement_data = advertisement_data

    def register_callback(self, callback: TreadmillCallback) -> Callable[[], None]:
        self._callbacks.append(callback)

        def _unregister() -> None:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

        return _unregister

    def _fire_callbacks(self) -> None:
        for callback in list(self._callbacks):
            callback(self._data)

    def _notification_handler(self, _sender: int, payload: bytearray) -> None:
        data = parse_state(bytes(payload))
        if data is None:
            _LOGGER.debug(
                "%s: ignoring non-status payload (%d bytes)", self.name, len(payload)
            )
            return
        # During the optimistic status window, keep the user-intended
        # status on top of whatever the pad currently reports. Telemetry
        # (speed, distance, steps, mode) still comes from the pad — only
        # the status field is overridden.
        if self._optimistic_status is not None:
            try:
                now = asyncio.get_running_loop().time()
            except RuntimeError:
                now = self._optimistic_until  # force cleanup
            if now < self._optimistic_until:
                data = replace(data, status=self._optimistic_status)
            else:
                self._optimistic_status = None
        self._data = data
        self._fire_callbacks()

    def _pin_optimistic_status(self, status: Status) -> None:
        # Set the deadline BEFORE the status flag so a concurrent
        # notification handler that reads them cannot see the new
        # status paired with a stale (expired) deadline.
        try:
            loop = asyncio.get_running_loop()
            self._optimistic_until = loop.time() + OPTIMISTIC_STATUS_WINDOW_SEC
        except RuntimeError:
            # No running loop (extremely unlikely — every call site is
            # inside an async coroutine). Fall back to "not pinned" so
            # we don't leave a stale override lying around.
            self._optimistic_status = None
            self._optimistic_until = 0.0
            return
        self._optimistic_status = status

    def _disconnected_callback(self, _client: BleakClientWithServiceCache) -> None:
        self._connected = False
        # Drop any optimistic status pin — the pad session is gone, and
        # once a reconnect happens we want the pad's real status to
        # show up immediately without a stale STARTING/STOPPING override.
        self._optimistic_status = None
        if self._expected_disconnect:
            _LOGGER.debug("%s: disconnected (expected)", self.name)
        else:
            _LOGGER.debug(
                "%s: disconnected unexpectedly, scheduling reconnect", self.name
            )
            self._schedule_reconnect()
        self._data = replace(self._data, status=Status.DISCONNECTED)
        self._fire_callbacks()

    def _schedule_reconnect(self) -> None:
        """Kick off a background reconnect task if none is running.

        Called from :meth:`_disconnected_callback` (a synchronous bleak
        callback), so we cannot ``await`` here — we schedule the coroutine
        on the running loop instead.
        """
        if self._expected_disconnect:
            return
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._reconnect_task = loop.create_task(self._reconnect_with_backoff())

    def start_reconnect_in_background(self) -> None:
        """Public entry point that mirrors :meth:`_schedule_reconnect`.

        Used by the HA integration to keep the setup non-fatal when the pad
        is not currently reachable (off / standby / out of range). A single
        reconnect task runs in the background until the pad is reachable
        again.
        """
        self._schedule_reconnect()

    async def _reconnect_with_backoff(self) -> None:
        """Keep trying to reconnect until it works or shutdown is requested."""
        delay = RECONNECT_INITIAL_DELAY_SEC
        while not self._expected_disconnect and not self.connected:
            await asyncio.sleep(delay)
            if self._expected_disconnect or self.connected:
                return
            try:
                await self.async_ensure_connected()
                _LOGGER.debug("%s: reconnect succeeded", self.name)
                return
            except TRANSIENT_ERRORS as err:
                _LOGGER.debug(
                    "%s: reconnect failed (%s), retrying in %.1fs",
                    self.name,
                    err,
                    delay,
                )
            delay = min(delay * 2, RECONNECT_MAX_DELAY_SEC)

    async def async_ensure_connected(self) -> None:
        if self.connected:
            return
        async with self._connect_lock:
            if self.connected:
                return
            _LOGGER.debug("%s: connecting", self.name)
            client = await establish_connection(
                BleakClientWithServiceCache,
                self._ble_device,
                self.name,
                self._disconnected_callback,
                ble_device_callback=lambda: self._ble_device,
            )
            try:
                await client.start_notify(
                    CHARACTERISTIC_NOTIFY_STATE_UUID, self._notification_handler
                )
            except (BleakError, EOFError):
                await client.disconnect()
                raise
            self._client = client
            self._expected_disconnect = False
            self._connected = True
            _LOGGER.debug("%s: connected", self.name)
            # The A1 silently ignores start_belt/set_speed until it has seen
            # this handshake frame at least once per connection.
            try:
                await self._write_raw(handshake_command())
            except TRANSIENT_ERRORS as err:
                _LOGGER.debug("%s: handshake failed: %s", self.name, err)
            self._start_polling()
            # No callback fire here: the poll loop starts immediately and
            # its first ask_stats reply triggers _notification_handler,
            # which pushes real telemetry to the callbacks. Firing here
            # would only redistribute the stale DISCONNECTED snapshot.

    def _start_polling(self) -> None:
        if self._poll_task is not None and not self._poll_task.done():
            return
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def _poll_loop(self) -> None:
        """Poll the pad for status frames.

        The A1 does not stream. It answers each ask_stats with exactly one
        frame, so we must keep asking to keep entities up to date.
        """
        while self.connected:
            try:
                await self._async_send(ask_stats_command())
            except TRANSIENT_ERRORS as err:
                _LOGGER.debug("%s: poll error: %s", self.name, err)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("%s: unexpected poll error", self.name)
                return
            await asyncio.sleep(POLL_INTERVAL_SEC)

    async def async_ensure_connected_safe(self) -> None:
        try:
            await self.async_ensure_connected()
        except TRANSIENT_ERRORS as err:
            _LOGGER.debug("%s: reconnect attempt failed: %s", self.name, err)

    async def _async_send(self, payload: bytes) -> None:
        async with self._operation_lock:
            await self.async_ensure_connected()
            loop = asyncio.get_running_loop()
            wait = MIN_COMMAND_SPACING_SEC - (loop.time() - self._last_command_at)
            if wait > 0:
                await asyncio.sleep(wait)
            await self._write_raw(payload)
            self._last_command_at = loop.time()

    async def _write_raw(self, payload: bytes) -> None:
        """Write to fe02 without acquiring the operation lock or spacing.

        Used from inside code paths that already hold the lock (or where
        spacing is irrelevant, like the once-per-connection handshake).
        """
        assert self._client is not None
        _LOGGER.debug("%s: writing %s", self.name, payload.hex())
        await self._client.write_gatt_char(
            CHARACTERISTIC_WRITE_UUID, payload, response=False
        )

    async def async_switch_mode(self, mode: Mode) -> None:
        """Switch operating mode (STANDBY / MANUAL / AUTOMAT).

        Updates the preferred *walking* mode (MANUAL or AUTOMAT) as a
        side effect so subsequent start_walking calls don't switch it
        back. Sending STANDBY here does NOT change the preferred mode
        — it is treated as a "put the pad to sleep now" action and the
        walking preference is preserved for the next wake.
        """
        if mode is not Mode.STANDBY:
            self._preferred_mode = mode
        await self._async_send(switch_mode_command(mode))

    async def async_start_walking(self, speed_deci_kmh: int) -> None:
        """Start the belt at ``speed_deci_kmh``, waking the pad if needed.

        This is the single "start" entry point exposed to the UI. It
        does exactly what the physical remote does:

        1. If the pad is in STANDBY, wake it into the preferred mode
           (one BLE write, one pad beep) and wait a moment for the belt
           controller to settle. Without the pause, ``start_belt`` after
           a fresh wake is often silently dropped.
        2. Arm the belt (``start_belt``) unless it is already running.
        3. Send the target speed.

        Steady-state (pad already awake, belt already running) reduces
        to a single ``set_speed`` write.

        The whole sequence is guarded by an asyncio.Lock so a second
        click while the first sequence is still in flight is dropped —
        no queued double-start, no chaos.
        """
        if self._toggle_lock.locked():
            _LOGGER.debug("%s: start ignored, sequence already running", self.name)
            return
        async with self._toggle_lock:
            if self._data.mode is Mode.STANDBY:
                await self._async_send(switch_mode_command(self._preferred_mode))
                await asyncio.sleep(WAKE_SETTLE_DELAY_SEC)
            elif self._data.mode is not self._preferred_mode:
                await self._async_send(switch_mode_command(self._preferred_mode))
            if self._data.status not in (Status.RUNNING, Status.STARTING):
                await self._async_send(start_command())
            await self._async_send(set_speed_command_deci(speed_deci_kmh))
            # Optimistically pin local status to STARTING so a rapid
            # second toggle from the UI is interpreted as "stop", not
            # "start again". The pad's own status frames still update
            # every other field, but the status is held for the grace
            # window so the poll loop cannot flip it back.
            self._pin_optimistic_status(Status.STARTING)
            self._data = replace(self._data, status=Status.STARTING)
            self._fire_callbacks()

    async def async_set_speed(self, speed_deci_kmh: int) -> None:
        """Set target belt speed on a belt that is already running.

        Assumes the belt is already armed. If it is not, the pad simply
        ignores this — the caller should use :meth:`async_start_walking`
        to arm+start. This is the single-write "change speed while
        walking" path that produces exactly one beep.
        """
        await self._async_send(set_speed_command_deci(speed_deci_kmh))

    async def async_stop(self) -> None:
        """Stop the belt.

        Optimistically pins local status to STOPPING so a rapid second
        toggle press does not race the pad's own status notification —
        the pad keeps reporting RUNNING for ~1 s after the belt starts
        decelerating.
        """
        await self._async_send(stop_command())
        self._pin_optimistic_status(Status.STOPPING)
        self._data = replace(self._data, status=Status.STOPPING)
        self._fire_callbacks()

    async def async_shutdown(self) -> None:
        """Tear down the connection (called on entry unload)."""
        self._expected_disconnect = True
        for task_attr in ("_poll_task", "_reconnect_task"):
            task = getattr(self, task_attr)
            setattr(self, task_attr, None)
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
        client = self._client
        self._client = None
        self._connected = False
        if client is None or not client.is_connected:
            return
        try:
            await client.stop_notify(CHARACTERISTIC_NOTIFY_STATE_UUID)
        except BleakError:
            pass
        try:
            await client.disconnect()
        except BleakError as err:
            _LOGGER.debug("%s: error during disconnect: %s", self.name, err)
