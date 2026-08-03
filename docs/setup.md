# WalkingPad Home Assistant integration - setup

## What you need

- KingSmith **WalkingPad A1** (other KingSmith models may work, untested)
- **Home Assistant** 2024.12 or newer, with the Bluetooth integration enabled
- **One ESP32** in Bluetooth range of the pad (same room, line of sight)

That's it. No MQTT broker, no separate bridge daemon, no dedicated
single-board computer next to the treadmill.

## Why the ESP32?

BLE is short-range (~5-10 m). If your HA instance runs on a NAS or in a rack
somewhere else, the pad is out of range. The ESP32 runs an
[ESPHome Bluetooth Proxy](https://esphome.io/components/bluetooth_proxy.html)
which relays BLE connections from the pad to HA over Wi-Fi (or Ethernet).

Any ESP32 with Wi-Fi works. The
[Olimex ESP32-POE-ISO-EA](https://www.olimex.com/Products/IoT/ESP32/ESP32-POE-ISO/)
is what the HA Bluetooth team uses for development (Ethernet + PoE, best RF
performance), but a plain ~10 EUR ESP32-DevKit is also fine.

**Critical:** the proxy must be in **active** mode (`bluetooth_proxy.active:
true`). Passive/scanner-only proxies can see the pad advertising but cannot
establish a connection to it, which means the integration will fail to
control it.

## Step 1: Flash the ESP32

Easiest route:

1. Plug the ESP32 into a computer via USB.
2. Open <https://esphome.io/projects/?type=bluetooth> in Chrome or Edge.
3. Click **Connect** on the "Bluetooth Proxy" project and follow the wizard.

That's the ready-made proxy firmware. It defaults to active mode and joins
your Wi-Fi automatically after the web-flash finishes.

If you prefer to write the YAML yourself (e.g. for the Olimex board or an
Ethernet setup), use [`docs/bluetooth-proxy.yaml`](./bluetooth-proxy.yaml)
as a starting point.

Place the flashed ESP32 within a few meters of the WalkingPad.

## Step 2: Add the proxy to Home Assistant

If HA's Bluetooth integration is enabled (it is under
`default_config:`), the proxy is auto-discovered:

**Settings > Devices & Services > Discovered > "ESPHome Bluetooth Proxy" > Add**

## Step 3: Install this integration via HACS

1. In HACS: **... menu (top right) > Custom repositories**
2. Add `https://git.teccave.de/tecbeat/walkingpad`, category **Integration**
3. Install **KingSmith WalkingPad** and restart Home Assistant

## Step 4: Add the WalkingPad

1. Power on the pad.
2. **Make sure the vendor app is disconnected.** The pad only accepts one BLE
   connection at a time -- if your phone's KingSmith app is connected, HA
   cannot reach the pad.
3. HA auto-discovers the pad through the proxy:
   **Settings > Devices & Services > Discovered > "KingSmith WalkingPad" >
   Add**
4. If it doesn't appear automatically:
   **Add Integration > KingSmith WalkingPad**, then pick it from the list.

## Entities

The control surface mirrors the physical remote — one speed setpoint,
one mode selector, and one start/stop toggle. Everything else the pad
reports (live speed, distance, duration, steps, state) is shown as a
sensor. Nothing goes `unavailable` when the pad is asleep or
unreachable: the sensors keep their last-known values and the setpoints
stay editable so the user can pre-configure the next walk.

| Entity | Type | Purpose |
|---|---|---|
| Speed | `number` (slider) | Target speed for the next walk (or the live setpoint while walking). Always editable, also when the pad is asleep. Adjusting it while the belt is running sends one BLE write to the pad. |
| Mode | `select` | Preferred walking mode: `manual` or `automat`. Persists across HA restarts. Applied on the next wake if the pad is currently asleep. |
| Start/Stop | `button` | Toggle. If the belt is stopped: wake the pad if needed, wait 1 s for the belt controller to settle, arm the belt, then set the current slider speed. If the belt is running: stop it. Concurrent clicks during the start sequence are ignored so the pad never receives an overlapping second sequence. |
| State | `sensor` | `stopped` / `running` / `starting` / `stopping` / `standby` / `disconnected`. |
| Speed | `sensor` | Live belt speed reported by the pad (in km/h). |
| Distance | `sensor` | Session distance in km. |
| Duration | `sensor` | Session duration in seconds. |
| Steps | `sensor` | Step count. |
| Mode (raw) | `sensor` (diagnostic, disabled by default) | Debug view on the pad's own mode field. |

### Why the pad is normally-off

The A1 draws non-trivial standby power over the mains switch on the
side of the treadmill. Most users plug it in only when they intend to
walk. Home Assistant reflects that gracefully: an unplugged / unpowered
pad shows up with the State sensor as `disconnected`, all sensor
values held at their last-known state, and the setpoints still fully
editable. Pressing Start/Stop after plugging the pad back in
transparently re-establishes the BLE connection, wakes the pad, and
starts the walk.

### The single-beep start flow

The A1 emits one beep for every accepted BLE command. The integration
therefore only sends what is strictly necessary for the pad's current
state:

- Selecting a different **Mode** while the pad is awake → one
  `switch_mode` → one beep. Selecting the mode while the pad is asleep
  stores the preference silently and applies it on the next start.
- Pressing **Start/Stop** on a sleeping pad → one `switch_mode(preferred)`
  (auto-wake), a 1 s pause for the belt controller to settle, then one
  `start_belt` and one `set_speed` at the slider's current value. Three
  beeps in total — the minimum the pad accepts to physically start
  walking.
- Pressing **Start/Stop** on an already-awake pad → one `start_belt`
  and one `set_speed`. Two beeps.
- Pressing **Start/Stop** while the belt is running → one `set_speed(0)`.
  One beep.
- Moving the **Speed** slider while the belt is running → one
  `set_speed` → one beep. Moving it while stopped is silent — the pad
  only sees the new setpoint on the next Start/Stop press.

## Troubleshooting

### Pad is not discovered

- The pad only advertises while **not connected** to another central. Force-
  close the KingSmith app on every phone that has it.
- Verify the ESPHome device shows up under **Settings > Bluetooth > Adapters**
  and its capabilities include "active connections".
- Power-cycle the pad (physical switch, wait ~10 s).

### Discovered, but the integration keeps saying "Retrying"

- Same cause as above: another BLE central is holding the connection. Close
  vendor apps.
- Check that no other HA integration is trying to control the same address.
- The ESPHome proxy has a `connection_slots` limit (default 3). If it's
  already full, the pad cannot connect.

### Commands don't take effect

- The A1 must be **awake** (not in `standby`) to accept walking commands.
  Start/Stop handles the wake transparently — press it once on a
  sleeping pad and the integration will send `switch_mode(preferred)`,
  wait 1 s, then arm the belt and set the target speed.
- The A1 rejects speed commands issued too close together (~750 ms is
  the KingSmith app's own poll cadence). The integration enforces this
  spacing internally, so rapid slider drags coalesce into one BLE write
  every ~1 s.

## Local development

The repository ships a Docker Compose stack that starts a disposable HA
container with the integration mounted read-only, for verifying that the
component loads without errors:

```bash
docker compose -f docker-compose.dev.yml up -d
docker compose -f docker-compose.dev.yml logs -f homeassistant
docker compose -f docker-compose.dev.yml down -v
```

Unit tests for the reverse-engineered wire protocol (frame construction and
state decoding, verified against the reference frame from the ph4-walkingpad
README):

```bash
python -m venv .venv
.venv/bin/pip install pytest
.venv/bin/pytest tests/ -v
```

## Credits

The A1 BLE protocol was reverse-engineered by
[ph4r05/ph4-walkingpad](https://github.com/ph4r05/ph4-walkingpad) (MIT). The
HACS integration structure is derived from
[sirfergy/HomeAssistantWalkingPad](https://github.com/sirfergy/HomeAssistantWalkingPad)
(GPL-3.0), which targets the PitPat/Superun family of pads. This project
retains the same GPL-3.0 license.
