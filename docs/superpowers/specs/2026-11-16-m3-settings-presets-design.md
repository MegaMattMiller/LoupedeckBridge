# Milestone 3: settings page for presets (design)

Date: 2026-11-16 · Status: approved by the user · Part of: [the bridge design](2026-11-16-loupedeck-bridge-design.md)

## Intent
Assign Lightroom presets to the Loupedeck's P1–P8 buttons from a page in the browser, without
hand-editing JSON. Changes apply immediately, with no restart.

## What the user gets
- A page at **http://127.0.0.1:7690** (bookmarkable). It opens from `tools/bridgectl settings`, the
  address in the log, or the Loupedeck's **custom mode** button.
- **P1–P8 slots:** each shows its preset name, "empty", or a warning when the preset is missing or
  ambiguous in Lightroom. Select a slot to assign to it; a slot can be cleared.
- **Search** over all presets (1,572 today). Clicking a preset assigns it to the selected slot.
- Pressing a P-button on the device **highlights** its slot on the page (the preset still applies as usual).
- Saving writes the user's `mapping.json` immediately and takes effect without a restart.

## Decided
- **Approach (from the bridge design):** the bridge serves the page itself on `127.0.0.1` with the
  `websockets` server it already has. GET serves the page; every change travels over the page's
  WebSocket, because the server only accepts GET. No new dependencies, and no external resources (no CDN).
- **Security:**
  - the server binds 127.0.0.1 only
  - requests with a `Host` other than `127.0.0.1:<port>` or `localhost:<port>` are refused (guards against DNS rebinding)
  - the WebSocket requires the page's own `Origin` **and** a random per-run token embedded in the page
- **Preset names** load when the page asks for them (~1–2 s), and are cached until Lightroom reconnects.
- **Defaults follow control by control** (user-approved change): a control the user never changed
  follows new default layouts, and a control they changed (e.g. P1–P8) stays as they set it. This
  replaces "an edited file stops following defaults altogether".
- **custom mode** opens the settings page by default (a new `open_settings` action).
- An unreadable `mapping.json` is never overwritten. The page says why it can't save.

## Not in this milestone
Remapping other controls (milestone 4), the status display (milestone 5).
