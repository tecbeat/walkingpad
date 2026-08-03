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

The pad is treated as normally-off: unplugged, powered down, or in
`standby` is a **regular state**, not an error. Only Power, Mode, and
the State sensor stay usable in that state; every other control becomes
`unavailable` (greyed-out) until the pad is awake.

| Entity | Type | Purpose |
|---|---|---|
| Power | `switch` | On = wake pad into the selected walking mode; Off = put pad into `standby`. Always available (also when the pad is unreachable). |
| Mode | `select` | Preferred walking mode: `manual` or `automat`. Persists across restarts. Applied when the pad is next woken. |
| State | `sensor` | `stopped` / `running` / `starting` / `stopping` / `standby` / `disconnected`. Always available. |
| Speed | `number` (slider) | Set target speed. Non-zero starts the belt; 0 stops it. Unavailable when the pad is asleep. |
| Speed | `sensor` | Live belt speed. |
| Distance | `sensor` | Session distance in km. |
| Duration | `sensor` | Session duration in seconds. |
| Steps | `sensor` | Step count. |
| Start | `button` | Start the belt at a safe default speed. Single command, single beep. |
| Stop | `button` | Stop the belt. |
| Mode (raw) | `sensor` (diagnostic, disabled by default) | Debug view on the pad's own mode field. |

### Why the pad is normally-off

The A1 draws non-trivial standby power over the mains switch on the
side of the treadmill. Most users plug it in only when they intend to
walk. Home Assistant reflects that: an unplugged / unpowered pad shows
up with the Power switch as **off**, the State sensor as
`disconnected`, and every walking control as `unavailable`. There is no
error, no failed integration, no red notification — just an off
appliance.

### The single-beep start flow

The A1 emits one beep for every accepted BLE command. The integration
therefore only sends what is strictly necessary for the pad's current
state:

- Pressing **Power = On** while the pad is in standby → one
  `switch_mode(preferred)` → one beep.
- Selecting a different **Mode** while the pad is awake → one
  `switch_mode` → one beep. Selecting the mode while the pad is in
  standby stores the preference silently and applies it on next wake.
- Pressing **Start** on an awake pad in the preferred mode → one
  `start_belt` + one `set_speed` → one beep pair (the pad requires the
  belt to be armed before it will accept a target speed).
- Moving the **Speed** slider while the belt is running → one
  `set_speed` → one beep.

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

- The A1 must be **awake** (not in `standby`) to accept speed changes.
  Turn the **Power** switch on first, or set the **Mode** select before
  waking.
- The A1 rejects any walking command while it thinks it is still in
  `standby`. Waking is one `switch_mode` command; the integration sends
  it as part of turning the Power switch on.

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
