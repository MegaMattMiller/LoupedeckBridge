# Milestone 9: reload the layout from its file (short design)

## Why
The user keeps one Loupedeck layout on several machines with Syncthing, syncing only `mapping.json`. Today the bridge
reads that file once, at start, and the settings page saves its whole in-memory copy. So a layout synced in from the
other machine takes effect only after a restart, and an edit made before that restart writes the old copy back,
undoing the synced change on every machine. The layout won't change often, so a manual reload is enough.

## Goals
1. **Reload from file:** a button in the settings page re-reads `mapping.json`. The Loupedeck's controls and every
   open settings tab switch to it at once, and the P1–P8 presets are looked up again.
2. **Re-read before each save:** every change made in the settings page is applied to the file as it is on disk now,
   never to the copy read earlier. A save never undoes a change that arrived since, and the page then shows the file
   as saved.
3. **The Syncthing setup, documented** in the README: sync only `mapping.json` (ignore patterns `!/mapping.json`
   then `*`), leave `mapping.base.json` and the Mac's other files out, move a joining machine's own `mapping.json`
   aside first, and click Reload after a change arrives.

## Non-goals
- Reloading by itself when the file changes (approach B or C below).
- Spotting Syncthing's `mapping.sync-conflict-…` copies (the layout changes rarely).
- Anything for machines on different versions: with `mapping.base.json` left out of the sync, an older version can't
  reset untouched controls (an action it doesn't know yet does nothing until it updates).
- Per-machine preset ids: not needed (below).

## What's known
- **Lightroom gives a synced preset the same id on every machine.** Checked 2026-11-22 with a one-off script on a Mac
  (Apple Silicon) and the Windows PC, Lightroom 10.0 on both: the same 1,572 ids, names and order. So a synced layout
  finds its presets by id on both machines. (Goes into `docs/FINDINGS.md`.)
- The settings server and the dispatcher share one `Mapping` object and read it on every event, so reloading it in
  place reaches both. A held key is remembered by its physical control, so it's still let go after a reload.
- `mapping.json` is written atomically (temporary file, then a rename), and so is a file Syncthing brings in.

## Approaches
- **A. A Reload button only.** The user clicks it after a sync. The Loupedeck keeps the old layout until then.
  **Chosen** by the user: "this won't be changing that often".
- B. Reload automatically: check the file's modification time every couple of seconds. Nothing to remember, but a
  background check for something that rarely happens.
- C. Both. B, plus the button as a fallback.

## Decided
- **Where:** a **Reload from file** button beside the tabs, since it applies to both. Its result shows in the page's
  existing notice line.
  ```
  LoupedeckBridge                                    ● Lightroom connected
  [ Presets ] [ Buttons & dials ]                       Reload from file
  Reloaded the layout from mapping.json.
  ```
- **What a reload does:** the same as a restart does with the file, done in place:
  - a readable file becomes the layout, and the layout becomes writable again if it wasn't;
  - a file that can't be read leaves the layout in use as it is, and the page says why, with the file's name and
    the reader's error;
  - a missing file is recreated from the default layout, as at start.

  Then the P1–P8 presets are looked up again, and every open tab gets the new layout and state.
- **The result line** says whether the file changed: "Reloaded the layout from mapping.json." or "mapping.json
  hasn't changed since it was read." Any warnings from reading it (an invalid action, say) show as they do at start.
- **A save re-reads first:**
  - **Unreadable file:** if the file can't be read at the moment of saving, the save is refused with the same
    message as today, and the file is left alone.
  - **Changed file:** if it changed since it was last read, the change is applied on top, saved, and the bridge and
    every tab take the whole saved file. The P1–P8 presets are looked up again whenever a save brought in other
    changes.

## Constraints
- Python 3.9, UTF-8 for every read and write, no new dependencies. The settings page stays on 127.0.0.1.
- Test-first, then one fresh review of the whole branch, then a live check on two machines.
- Version: v0.8.0 (my call: a new feature).

## Left to the builder
- How `Mapping` swaps in a re-read file (one method, used by both the button and the save path).
- The websocket message's name, and the button's exact place and style within the page's design.

## Live check (two machines, with the user)
1. Change a dial on the Mac, and let Syncthing bring it to the PC. Click **Reload from file** on the PC: the
   Loupedeck follows, and the PC's page shows the change.
2. Change P1 on the Mac. Before reloading on the PC, change a button there. The Mac's P1 change survives on both
   machines.
3. Break `mapping.json` by hand: Reload keeps the layout and says why. Fix it: Reload brings it back, with no
   restart.
