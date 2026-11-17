# Milestone 4: remapper with an Fn layer (design)

Date: 2026-11-16 · Status: approved by the user · Part of: [the bridge design](2026-11-16-loupedeck-bridge-design.md)
· Builds on: [milestone 3, the settings page](2026-11-16-m3-settings-presets-design.md)

## Intent
Change what the Loupedeck's controls do from the settings page, without editing JSON. Holding **Fn**
gives a second layer of actions. The user mainly wants this for **L1–L3 and C1–C6** (nine buttons that
do little or nothing today), with **Lightroom commands** as the actions for now.

## What the user gets
- A second tab on the settings page, **Buttons & dials**, next to **Presets**.
- A list with two columns, **Normal** and **With Fn held** (layout A, chosen from mockups). L1–L3 and
  C1–C6 come first. Other buttons, the dials, and the colour dials (grouped by bank: Hue, Sat, Lum, B&W)
  are folded sections below.
- Select a control (and a layer) by clicking its row, or by **using it on the device**: pressing a
  button or turning a dial selects it on the page. Holding Fn on the device switches the page to the
  Fn column. The control still does its action when used; selecting doesn't swallow the press.
- An editor for the selected control and layer:
  - **Buttons and dial clicks:** any Lightroom command from a searchable, grouped list with plain names
    (e.g. "Rating: ★★★", "Colour label: red", "Next photo", "Zoom to fit", "Crop tool", "Auto tone"),
    "Open this settings page", or **Nothing**. Dial clicks also offer **Reset this dial's slider** (below).
  - **Dial turns:** any Lightroom slider (number-type parameters from `docs/lr_parameters_10.0.json`,
    searchable by label), a **command pair** (one command per direction, from a short curated list such as
    previous/next photo, rating down/up, zoom out/in), or **Nothing**.
  - In the Fn column, also **Same as normal** (the default for every Fn slot).
  - Clicking a choice saves it at once and it works without a restart, as on the Presets tab.
- **Reset** on each control restores its default layout (both layers).
- **Restore default layout** resets every control, after an in-page confirmation (no browser dialog).
- Actions the page can't create (keyboard keys, shortcuts) still show as what they are, e.g.
  "Key: Shift", and can be replaced with a command. Reset brings them back.
- **Fn + Export = export with previous settings, fixed** (the user's decision). It's in the default
  layout, the page shows it as fixed, and that command isn't offered anywhere else. Plain Export keeps
  opening the export dialog. Before exporting, the bridge asks `canExportWithPrevious`; if Lightroom
  says no, nothing happens and the log says why.

## How Fn layers behave
- **Verified on the device (capture, 2026-11-16):** every control sends the same MIDI with and without
  Fn. Fn itself sends a press (note 110 on) and a release (note 110 off). Layers are entirely the
  bridge's job.
- Fn is the **layer key**. It has no action of its own and isn't editable on the page.
- While Fn is held, a control uses its Fn action if it has one; otherwise its normal action
  ("same as normal"). An Fn slot set to **Nothing** does nothing while Fn is held.
- **A press belongs to the layer it started in:** if Fn is let go before the button, the button's
  release still ends the Fn action (matters for held keys and repeating actions).
- Dial turns use the layer at the moment of each turn message.
- Fn counts as released when the device disconnects or reconnects, so a layer can't stick.
- One layer only. Shift, Ctrl, Cmd and Alt stay real keyboard keys.

## Decided
- **Mapping file:** Fn actions live inside each control's entry:
  `"c3": {"press": {…}, "fn": {"press": {…}}}`. `fn` holds `turn` and/or `press`; a missing slot means
  "same as normal". The file stays one line per control, and per-control default following (milestone 3)
  works unchanged because it compares whole entries. An existing user mapping whose Export entry was
  never changed picks up the new Fn + Export default by itself.
- **Command list:** a hand-made file in the repo, `config/commands.json`: for each command a stable id,
  a plain label, a group, the Lightroom message and any fixed arguments (e.g. Crop tool =
  `selectTool("crop")`), and the curated dial pairs. The page and the server both use it. It's curated
  from Adobe's reference (local only, never committed) and checked against the real Lightroom.
- **Left out of the list:** commands that act without asking (export with previous, except on
  Fn + Export), commands that need a typed name or an id (albums, masks), getters (`get…`, `is…`, `can…`),
  setup calls (`setTrackingDelay`, observers), and presets (they have their own tab).
- **What the page can change, checked by the server:**
  - only controls in the hardware map; never Fn itself, clr/bw, the fixed Fn + Export, or P1–P8's
    normal layer
  - only these actions: a command from `commands.json` (sent by id; the server fills in message and
    arguments), a number-type slider for a dial turn, a curated pair for a dial turn, Reset this dial's
    slider (dial clicks), Nothing, Same as normal (Fn column only), Open this settings page
  - never a keyboard key or shortcut, so the page's secret can't be used to make the Loupedeck type keys
- **Dial clicks follow the dial** (the milestone 1 rule "a dial click resets that dial's parameter",
  kept when the dial is remapped): a new action, **Reset this dial's slider**
  (`{"type": "reset_dial"}`), resets whatever slider the dial's turn adjusts **in the layer in use**:
  the Fn turn while Fn is held (if it has one), else the normal turn. If that turn isn't a slider
  (a command pair, or Nothing), the click does nothing. It replaces the 46 explicit
  `resetToDefault(<param>)` clicks in the default layout (unedited mappings follow it by themselves);
  an explicit `resetToDefault(<param>)` from an older or hand-edited file still runs and shows as
  "Reset <slider label>". So Exposure turned into a next/previous-photo dial no longer zeroes Exposure
  on a click, and Fn + click on a dial whose Fn turn is another slider resets that slider. *(Builder
  check; my call.)*
- **The B&W-bank guard** (B&W-bank dials do nothing unless the photo is black & white) applies to
  actions on the B&W mix sliders (`GrayMixer…` adjust and reset), not to anything else a B&W-bank dial
  is remapped to. *(My call.)*
- **clr/bw is fixed, in both layers:** the device flips its own colour/B&W mode on every clr/bw press,
  whatever the bridge does and whether Fn is held, so every clr/bw press keeps the photo in step with the
  device (the milestone 1 sync, now tied to the button instead of the mapped command). A plain
  "Black & white" toggle isn't in the command list, since on another button it would bring back the
  lights-versus-photo mismatch. HUE, SAT and LUM can be given an action; the editor notes they also
  switch the colour dials' bank. *(Builder check; my call, from the user's earlier out-of-sync report.)*
- **P1–P8:** their normal action is a preset, set on the Presets tab only. On the Buttons & dials tab
  their Normal column is read-only ("set on the Presets tab") and the server refuses non-preset normal
  actions for them; their Fn action is set on the new tab. A P button holding some other action (from a
  hand edit) shows as that action on both tabs, not as "Empty"; assigning or clearing it on the Presets
  tab makes it a preset slot again. Reset on a P button resets only its Fn layer, and Restore default
  layout leaves P1–P8's normal actions as they are (the confirmation says so).
- **Custom mode** can be remapped, but the editor warns first that it's the button that opens this page.
  Reset or `tools/bridgectl settings` gets the page back.
- **Hand edits:** a command in `mapping.json` that isn't in `commands.json` still runs and shows as
  "Lightroom: <message>". `exportWithPrevious` anywhere but Export's Fn slot is rejected at load with a
  warning (it becomes Nothing), so a no-dialog export can only come from that one press.
- Device-mode tracking (HUE/SAT/LUM/clr-bw lights) keeps working whatever those buttons are mapped to.
- **Selecting from the device** doesn't swallow the press: the control does its action as usual
  (as P buttons do on the Presets tab today). *(My call: a "capture the next press" mode can come later.)*
- **Command pairs** for dial turns come from a curated list, not any two commands, so a direction
  can't end up with something odd (e.g. "export dialog" on one side). *(My call.)*

## Addendum: --/Col modes for the five buttons (approved by the user, 2026-11-16)
The user's request: **--/Col** switches the five buttons next to it between **star ratings 1–5** and
**colour labels**, and **Fn + --/Col** turns them into **keyboard modifiers**.
- **Verified on the device (capture, 2026-11-16):** the five buttons always send notes 66–70 (today's
  Shift, Ctrl, Cmd, Alt, Tab, in that physical order), whatever --/Col (note 65) or Fn + --/Col did, and no
  lights change. The modes are entirely the bridge's job, and the page is the only place to see them.
- **Three modes**, by position:
  - **Ratings:** rating 1–5
  - **Colours:** red, yellow, green, blue, purple
  - **Keys:** Shift, Ctrl, Cmd, Alt, Tab, as before
- **Switching:**
  - --/Col swaps Ratings and Colours; in Keys it goes back to whichever of those two was last used
  - **Fn + --/Col** turns Keys on and off
  - the bridge always **starts in Ratings** (the user's choice: predictable without a light)
  - a device reconnect keeps the current mode
- **--/Col is fixed in both layers** (it's the mode switch), like clr/bw.
- **A press belongs to the mode it started in:** a key held when the mode changes is still let go properly.
- **Remapper:** each mode's five buttons are their own rows, in a "Five buttons (--/Col)" section with
  Ratings, Colours and Keys sub-headings, like the colour-dial banks. Any of the 15 can be changed, each with
  its Fn layer as usual. Keys-mode rows keep today's control ids, so existing mappings are unchanged.
- The page shows the current mode, and the log notes each switch.
- *(My call, how it's built: per-mode control ids, `ratings_1`…`ratings_5` and `colours_1`…`colours_5` plus the
  existing ids for Keys, chosen by the bridge from its mode. That reuses the colour-dial pattern; a "mode
  layer" inside each entry would need a second kind of layer everywhere.)*

## Goals and anti-goals
- **Goals:** remap any control in both layers from the page; Fn layers that never stick; changes live
  at once; nothing about today's default behaviour changes except the new Fn + Export.
- **Anti-goals:** a key left held because its release went to the other layer; a stuck Fn layer;
  a web page or the page's secret able to make the device type keys; an export without a dialog from
  anything but Fn + Export; Restore default wiping preset assignments; Fn making other controls dead.

## Not in this milestone
Editing keyboard keys and shortcuts on the page (they can be replaced and reset, not created); presets
on Fn layers; more layers or long-press; the status strip and start at login (milestone 5); Windows
(milestone 6).

## Left to the builder
- The exact commands, groups, labels and dial pairs in `commands.json` (curate from the reference;
  verify each against the real Lightroom on the test photo).
- How often a turning dial re-selects its row on the page (it sends up to ~150 messages a second).
- The editor's details, keyboard behaviour and wording, within the layout chosen from the mockups.
- How the server tells pages about Fn and device use (new message types alongside `state` and `pressed`).
