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

from .const import CHARACTERISTIC_NOTIFY_STATE_UUID, CHARACTERISTIC_WRITE_UUID
from .protocol import (
    Mode,
    Status,
    TreadmillData,
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
            _LOGGER.debug("%s: disconnected unexpectedly", self.name)
        self._data = replace(self._data, status=Status.DISCONNECTED)
        self._fire_callbacks()

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
            self._fire_callbacks()

    async def async_ensure_connected_safe(self) -> None:
        try:
            await self.async_ensure_connected()
        except TRANSIENT_ERRORS as err:
            _LOGGER.debug("%s: reconnect attempt failed: %s", self.name, err)

    async def _async_send(self, payload: bytes) -> None:
        async with self._operation_lock:
            await self.async_ensure_connected()
            assert self._client is not None
            loop = asyncio.get_running_loop()
            wait = MIN_COMMAND_SPACING_SEC - (loop.time() - self._last_command_at)
            if wait > 0:
                await asyncio.sleep(wait)
            _LOGGER.debug("%s: writing %s", self.name, payload.hex())
            await self._client.write_gatt_char(
                CHARACTERISTIC_WRITE_UUID, payload, response=True
            )
            self._last_command_at = loop.time()

    async def async_switch_mode(self, mode: Mode) -> None:
        """Switch operating mode (STANDBY / MANUAL / AUTOMAT)."""
        await self._async_send(switch_mode_command(mode))

    async def async_start(self) -> None:
        """Start the belt. Requires MANUAL or AUTOMAT mode first."""
        if self._data.mode is Mode.STANDBY:
            await self._async_send(switch_mode_command(Mode.MANUAL))
        await self._async_send(start_command())

    async def async_set_speed(self, speed_deci_kmh: int) -> None:
        """Set target belt speed in tenths of km/h (0..60)."""
        if self._data.mode is Mode.STANDBY:
            await self._async_send(switch_mode_command(Mode.MANUAL))
        await self._async_send(set_speed_command_deci(speed_deci_kmh))

    async def async_stop(self) -> None:
        """Stop the belt."""
        await self._async_send(stop_command())

    async def async_shutdown(self) -> None:
        """Tear down the connection (called on entry unload)."""
        self._expected_disconnect = True
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
