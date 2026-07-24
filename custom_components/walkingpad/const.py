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
