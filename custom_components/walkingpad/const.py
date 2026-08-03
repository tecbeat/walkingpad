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

# Speed slider bounds in km/h. The A1 hardware caps out at 6.0 km/h and
# refuses anything below 0.5 km/h — the belt motor cannot maintain a
# slower target speed and the pad silently clamps or drops the command.
# The slider therefore only offers real speeds. Stopping the belt is the
# Start/Stop button's job.
MIN_SPEED_KMH = 0.5
MAX_SPEED_KMH = 6.0
SPEED_STEP_KMH = 0.1

# The A1 does not stream status frames; we must ask for each one. ~1 s matches
# the pad's minimum command spacing plus some headroom.
POLL_INTERVAL_SEC = 1.0

# Default target speed used the first time a fresh install starts a walk
# (before the user has moved the slider). 1.5 km/h is a comfortable slow
# walking pace.
DEFAULT_START_SPEED_DECI_KMH = 15

# Config-entry options key used to persist the user's preferred walking mode
# (Mode.AUTOMAT or Mode.MANUAL, stored as int) across HA restarts.
CONF_PREFERRED_MODE = "preferred_mode"
