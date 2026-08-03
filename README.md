<div align="center">

# Walkingpad
<p>
  <a href="https://git.teccave.de/tecbeat/walkingpad/-/commits/main"><img src="https://git.teccave.de/tecbeat/walkingpad/-/badges/main/pipeline.svg" alt="Pipeline Status"></a>
  <a href="https://git.teccave.de/tecbeat/walkingpad/-/releases"><img src="https://git.teccave.de/tecbeat/walkingpad/-/badges/release.svg" alt="Latest Release"></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-AGPLv3-blue?style=flat-square" alt="License"></a>
</p>

<p>
  <a href="https://git.teccave.de/tecbeat/walkingpad/-/issues"><img src="https://img.shields.io/gitlab/issues/open/tecbeat%2Fwalkingpad?gitlab_url=https%3A%2F%2Fgit.teccave.de&style=flat-square&label=Issues&color=orange" alt="Open Issues"></a>
  <a href="https://git.teccave.de/tecbeat/walkingpad/-/merge_requests"><img src="https://img.shields.io/gitlab/merge-requests/open/tecbeat%2Fwalkingpad?gitlab_url=https%3A%2F%2Fgit.teccave.de&style=flat-square&label=Merge%20Requests&color=blue" alt="Open Merge Requests"></a>
  <a href="https://git.teccave.de/tecbeat/walkingpad/-/commits/main"><img src="https://img.shields.io/gitlab/last-commit/tecbeat%2Fwalkingpad?gitlab_url=https%3A%2F%2Fgit.teccave.de&style=flat-square&label=Last%20commit" alt="Last commit"></a>
</p>

</div>

---

Home Assistant custom integration for the KingSmith WalkingPad A1 treadmill. Talks to the pad over Bluetooth Low Energy through Home Assistant's own Bluetooth stack, so any HA-supported adapter can drive it -- including an ESP32 Bluetooth proxy running ESPHome in active mode.

## Quick Start

```bash
See docs/setup.md for HACS installation.
```

## Features

- **Remote-mirrored controls** — Speed slider (0.5..6.0 km/h), Mode select (manual / automat), and a single Start/Stop toggle button -- exactly what the physical remote offers, nothing more.
- **Never-fails UI** — Sensors keep their last-known values when the pad is off, in standby, or out of range. The setpoints stay editable. No red error states for a normal power-off appliance.
- **Single-beep control flow** — Every user action produces the minimum number of BLE commands the pad accepts -- one beep per intent, three beeps at most for a full wake+arm+set_speed sequence from cold standby.
- **Auto-wake on start** — Pressing Start/Stop on a sleeping pad transparently wakes it into the preferred mode, waits for the belt controller to settle, then starts the belt at the slider speed.
- **ESP32 Bluetooth proxy support** — Works transparently with an ESPHome Bluetooth Proxy in active mode -- ideal when the HA host itself is out of BLE range.
- **Config Flow with auto-discovery** — The pad appears automatically in Settings > Devices & Services once it is powered on and in range of the proxy or a local BT adapter.
- **Reverse-engineered A1 protocol** — Based on the ph4-walkingpad protocol (0xf7/0xa2 command framing, 0xf8/0xa2 status stream), verified against a real 2026 A1 unit.

## Contributing

Contributions are welcome. Please open an [Issue](https://git.teccave.de/tecbeat/walkingpad/-/issues) or [Merge Request](https://git.teccave.de/tecbeat/walkingpad/-/merge_requests) on GitLab.

## License

Walkingpad is Free Software: You can use, study, share, and improve it at your will. Specifically you can redistribute and/or modify it under the terms of the [AGPLv3 License](./LICENSE).
