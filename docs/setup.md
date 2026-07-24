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

| Entity | Type | Purpose |
|---|---|---|
| Speed | `number` (slider) | Set target speed. Non-zero starts the belt; 0 stops it. |
| Speed | `sensor` | Live belt speed. |
| State | `sensor` | `stopped` / `running` / `starting` / `stopping` / `standby` / `disconnected` |
| Mode | `sensor` (diagnostic) | `automat` / `manual` / `standby` |
| Distance | `sensor` | Session distance in km. |
| Duration | `sensor` | Session duration in seconds. |
| Steps | `sensor` | Step count. |
| Start | `button` | Start the belt. |
| Stop | `button` | Stop the belt. |
| Start/Stop | `button` | Toggles depending on current state. |
| Switch to manual mode | `button` (disabled by default) | Explicit mode switch. |
| Switch to standby | `button` (disabled by default) | Explicit mode switch. |

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

- The A1 must be in **manual mode** to accept speed changes. The integration
  auto-switches to manual on the first start/set-speed command. If the pad
  is unresponsive, use the "Switch to manual mode" button once (enable it
  first if it's hidden as a diagnostic entity).

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
