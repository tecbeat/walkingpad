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
    DEFAULT_START_SPEED_DECI_KMH,
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
        self._data = data
        self._fire_callbacks()

    def _disconnected_callback(self, _client: BleakClientWithServiceCache) -> None:
        self._connected = False
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
            self._fire_callbacks()

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
        """Switch operating mode (STANDBY / MANUAL / AUTOMAT)."""
        await self._async_send(switch_mode_command(mode))

    async def async_start(self) -> None:
        """Start the belt at DEFAULT_START_SPEED_DECI_KMH.

        The A1 requires start_belt AND a non-zero set_speed to actually move.
        A bare start_belt only puts the pad into 'ready' (belt_state=9). We
        therefore always follow up with set_speed so pressing Start visibly
        does something.
        """
        await self.async_set_speed(DEFAULT_START_SPEED_DECI_KMH)

    async def async_set_speed(self, speed_deci_kmh: int) -> None:
        """Set target belt speed in tenths of km/h (0..60).

        If the belt is not already running, sends switch_mode(MANUAL) and
        start_belt first. On the A1, set_speed alone is ignored unless the
        belt has been armed via start_belt in the same 'session'.
        """
        if self._data.mode is not Mode.MANUAL:
            await self._async_send(switch_mode_command(Mode.MANUAL))
        if self._data.status not in (Status.RUNNING, Status.STARTING):
            await self._async_send(start_command())
        await self._async_send(set_speed_command_deci(speed_deci_kmh))

    async def async_stop(self) -> None:
        """Stop the belt."""
        await self._async_send(stop_command())

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
