# LoupedeckBridge

Use a **Loupedeck+** with **Adobe Lightroom** (the cloud-based desktop app, *not* Lightroom Classic) on macOS.

Loupedeck's own software only supports Lightroom Classic. Lightroom 10 has an external-controller
WebSocket API, so this is a small local Python bridge: Loupedeck+ MIDI in → Lightroom API calls out,
over `127.0.0.1` only.

**Status:** the hardware map and the Lightroom client work. Next are the control → action mapping
and the bridge loop. See [docs/HANDOFF.md](docs/HANDOFF.md) for the plan and
[docs/FINDINGS.md](docs/FINDINGS.md) for everything verified so far.

## Setup

1. Lightroom: **Preferences → Interface → Enable external controllers**, then restart Lightroom.
2. Quit the Loupedeck / Logi software so it doesn't grab the device.
3. Python environment:
   ```bash
   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   ```
4. The first connection shows an **Allow** dialog in Lightroom. The client ID it hands back is
   saved to `~/Library/Application Support/loupedeck-lr-bridge/client.json`, so the dialog
   only appears once.

## Layout

| Path | What |
|---|---|
| `bridge/lightroom.py` | Async Lightroom Controller API client (register, requests, observers) |
| `config/loupedeck_plus.json` | Loupedeck+ MIDI map: every dial, colour-dial mode bank and button |
| `docs/lr_parameters_10.0.json` | Type, label, default and range of all 170 Lightroom edit parameters |
| `tools/midi_dump.py` | Labelled raw MIDI capture |
| `tools/summarize_capture.py` | Turn a capture into a per-control table |
| `tools/find_unknown.py` | Chime on the first control not in the map yet |
| `tools/lr_probe.py` | Read-only Lightroom smoke test (shows reply shapes) |
| `tools/lr_dump_params.py` | Regenerate `docs/lr_parameters_<version>.json` (read-only) |
| `captures/` | Raw MIDI / Lightroom frame logs the map and notes are based on |

Not affiliated with Adobe, Loupedeck or Logitech.
