"""Constants for the WalkingPad treadmill integration."""

from __future__ import annotations

DOMAIN = "walkingpad"

# GATT layout of the KingSmith WalkingPad A1.
# See: https://github.com/ph4r05/ph4-walkingpad/blob/master/ph4_walkingpad/pad.py
SERVICE_PAD_UUID = "0000fe00-0000-1000-8000-00805f9b34fb"
CHARACTERISTIC_NOTIFY_STATE_UUID = "0000fe01-0000-1000-8000-00805f9b34fb"
CHARACTERISTIC_WRITE_UUID = "0000fe02-0000-1000-8000-00805f9b34fb"

# Advertised name prefix used for Bluetooth discovery.
DEVICE_NAME_PREFIX = "WalkingPad"

DEFAULT_NAME = "WalkingPad Treadmill"
MANUFACTURER = "KingSmith"
MODEL = "WalkingPad A1"

# Speed slider bounds in km/h. The A1 hardware caps out at 6.0 km/h.
MIN_SPEED_KMH = 0.0
MAX_SPEED_KMH = 6.0
SPEED_STEP_KMH = 0.1

# Any commanded speed at or below this (in km/h) is treated as a stop request.
STOP_THRESHOLD_KMH = 0.1

# The A1 does not stream status frames; we must ask for each one. ~1 s matches
# the pad's minimum command spacing plus some headroom.
POLL_INTERVAL_SEC = 1.0

# Speed the pad ramps up to when async_start is called without a target
# (e.g. via the Start button). 1.5 km/h is slow enough to be safe but fast
# enough that the belt visibly moves so the user sees the command worked.
DEFAULT_START_SPEED_DECI_KMH = 15
