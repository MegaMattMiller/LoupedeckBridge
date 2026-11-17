// LoupedeckBridge settings page: the Buttons & dials tab (milestone 4).
// Uses app.js's helpers ($, el, send, notice, state). Built with DOM APIs and textContent only:
// labels are shown as text, never as HTML.
"use strict";

const Remap = (() => {
  const LAYER_NAMES = { normal: "Normal", fn: "With Fn held" };
  const SLOT_NAMES = { turn: "Turn", press: "Click" };
  const SECTIONS = [  // [group, title, always open]
    ["your", "Your buttons", true],
    ["buttons", "Other buttons", false],
    ["dials", "Dials", false],
    ["colour", "Colour dials", false],
  ];
  const BANK_NAMES = { hue: "Hue", sat: "Saturation", lum: "Luminance", bw: "B&W mix" };
  const RESTORE_TEXT = "Restore default layout";

  let catalog = null;        // {commands: [{id, label, group}], pairs: [{id, label}], sliders: [[param, label]]}
  let rows = null;           // the server's layout rows
  let sel = null;            // {control, layer, slot}
  let fnHeld = false;
  let query = "";
  let pendingCustom = null;  // a choice waiting for its second click (changing custom mode)
  let restoreTimer = null;   // set while "Restore default layout" waits for its second click
  const open = {};           // folded sections the user opened

  const keyOf = (choice) => JSON.stringify(choice);
  const rowOf = (control) => (rows || []).find((r) => r.control === control);
  const visible = () => !$("tab-remap").hidden;
  const writable = () => !state || state.writable;

  function onMessage(msg) {
    if (msg.type === "catalog") {
      catalog = msg;
    } else if (msg.type === "layout") {
      rows = msg.rows;
      if (!sel || !rowOf(sel.control)) sel = { control: rows[0].control, layer: "normal", slot: rows[0].slots[0] };
    } else if (msg.type === "used") {
      // Using a control on the device selects it, but only while this tab is showing.
      if (visible() && rowOf(msg.control)) select(msg.control, msg.layer, msg.slot, true);
      return;
    } else if (msg.type === "fn") {
      fnHeld = msg.held;
      // Pressing Fn switches to the Fn layer; letting go keeps it, so you can reach for the mouse.
      if (msg.held && visible() && sel) { sel.layer = "fn"; pendingCustom = null; }
    }
    render();
  }

  function select(control, layer, slot, fromDevice) {
    const row = rowOf(control);
    sel = { control, layer, slot: row.slots.includes(slot) ? slot : row.slots[0] };
    pendingCustom = null;
    if (fromDevice && row.group !== "your") open[row.group] = true;
    render();
    if (fromDevice) {
      const tr = document.querySelector(`tr[data-control="${CSS.escape(control)}"]`);
      if (tr) tr.scrollIntoView({ block: "nearest" });
    }
  }

  function render() {
    renderList();
    renderEditor();
    $("restore").disabled = !writable();
  }

  // ---- the list ---------------------------------------------------------------
  function renderList() {
    const box = $("remap-list");
    box.replaceChildren();
    if (!rows) return;
    for (const [group, title, alwaysOpen] of SECTIONS) {
      const groupRows = rows.filter((r) => r.group === group);
      if (!groupRows.length) continue;
      const body = el("tbody");
      let bank = null;
      for (const r of groupRows) {
        if (r.bank && r.bank !== bank) {
          bank = r.bank;
          body.append(el("tr", { class: "bank" }, el("th", { colspan: "3", scope: "colgroup" }, BANK_NAMES[bank])));
        }
        body.append(renderRow(r));
      }
      const table = el("table", { class: "remap-table" },
        el("thead", {}, el("tr", {},
          el("th", { scope: "col" }, el("span", { class: "visually-hidden" }, "Control")),
          el("th", { scope: "col" }, LAYER_NAMES.normal),
          el("th", { scope: "col" }, LAYER_NAMES.fn))),
        body);
      if (alwaysOpen) {
        box.append(el("h2", {}, title), table);
      } else {
        const det = el("details", {}, el("summary", {}, `${title} (${groupRows.length})`), table);
        det.open = Boolean(open[group]);
        det.addEventListener("toggle", () => { open[group] = det.open; });
        box.append(det);
      }
    }
  }

  function renderRow(r) {
    const selected = sel && sel.control === r.control;
    return el("tr", { "data-control": r.control, class: selected ? "selected" : "" },
      el("th", { scope: "row" }, r.name), cell(r, "normal"), cell(r, "fn"));
  }

  function cell(r, layer) {
    const td = el("td", {});
    for (const slot of r.slots) {
      const d = r[layer][slot];
      const fixed = r.fixed[`${layer}.${slot}`];
      const isSel = sel && sel.control === r.control && sel.layer === layer && sel.slot === slot;
      const text = d ? d.label : "Same as normal";
      const classes = ["cellbtn"];
      if (isSel) classes.push("sel");
      if (!d) classes.push("same");
      if (d && d.label === "Nothing") classes.push("nothing");
      if (fixed) classes.push("fixed");
      td.append(el("button", {
        type: "button", class: classes.join(" "), "aria-pressed": String(isSel),
        "aria-label": `${r.name}, ${LAYER_NAMES[layer]}${r.slots.length > 1 ? `, ${SLOT_NAMES[slot]}` : ""}: ` +
          `${text}${fixed ? " (fixed)" : ""}`,
        onclick: () => select(r.control, layer, slot, false),
      }, r.slots.length > 1 ? el("span", { class: "slotname" }, `${SLOT_NAMES[slot]}: `) : null, text));
    }
    return td;
  }

  // ---- the editor ---------------------------------------------------------------
  function renderEditor() {
    const box = $("editor");
    const hadFocus = document.activeElement && document.activeElement.id === "remap-search";
    box.replaceChildren();
    const r = sel && rowOf(sel.control);
    if (!r) return;
    box.append(el("h2", {}, r.name, fnHeld ? el("span", { class: "fnbadge" }, "Fn held") : null));
    if (r.note) box.append(el("p", { class: "hint" }, r.note));
    box.append(toggle(LAYER_NAMES, ["normal", "fn"], sel.layer, "Layer", (v) => { sel.layer = v; }));
    if (r.slots.length > 1) box.append(toggle(SLOT_NAMES, r.slots, sel.slot, "Turn or click", (v) => { sel.slot = v; }));
    const current = r[sel.layer][sel.slot];
    const fixed = r.fixed[`${sel.layer}.${sel.slot}`];
    box.append(el("p", { class: "now" }, el("span", { class: "dim" }, "Now: "), current ? current.label : "Same as normal"));
    if (fixed) {
      box.append(el("p", { class: "fixednote" }, fixed));
    } else {
      const search = el("input", {
        id: "remap-search", type: "search", autocomplete: "off", spellcheck: "false", "aria-label": "Search choices",
        placeholder: sel.slot === "turn" ? "Search sliders and pairs…" : "Search Lightroom commands…",
      });
      search.value = query;
      search.addEventListener("input", () => { query = search.value; renderChoices(r, current); });
      box.append(search, el("div", { id: "choices" }));
      renderChoices(r, current);
      if (hadFocus) search.focus();
    }
    const reset = el("button", { type: "button", class: "secondary", onclick: () => send({ op: "reset", control: r.control }) },
      `Reset ${r.name} to default`);
    reset.disabled = !writable();
    box.append(el("div", { class: "editor-actions" }, reset));
  }

  function toggle(names, values, current, label, onPick) {
    return el("div", { class: "seg", role: "group", "aria-label": label },
      ...values.map((v) => el("button", {
        type: "button", class: v === current ? "on" : "", "aria-pressed": String(v === current),
        onclick: () => { onPick(v); pendingCustom = null; render(); },
      }, names[v])));
  }

  function choicesFor(r) {
    const specials = [];
    if (sel.layer === "fn") specials.push({ label: "Same as normal", choice: { kind: "same" } });
    specials.push({ label: "Nothing", choice: { kind: "none" } });
    if (sel.slot === "press" && r.slots.includes("turn")) specials.push({ label: "Reset this dial's slider", choice: { kind: "reset_dial" } });
    if (sel.slot === "press") specials.push({ label: "Open this settings page", choice: { kind: "open_settings" } });
    const out = [["", specials]];
    if (!catalog) return out;
    if (sel.slot === "press") {
      const groups = new Map();
      for (const c of catalog.commands) {
        if (!groups.has(c.group)) groups.set(c.group, []);
        groups.get(c.group).push({ label: c.label, choice: { kind: "command", id: c.id } });
      }
      out.push(...groups);
    } else {
      out.push(["Command pairs (one per direction)", catalog.pairs.map((p) => ({ label: p.label, choice: { kind: "pair", id: p.id } }))]);
      out.push(["Sliders", catalog.sliders.map(([param, label]) => ({ label, choice: { kind: "slider", param } }))]);
    }
    return out;
  }

  function renderChoices(r, current) {
    const box = $("choices");
    if (!box) return;
    box.replaceChildren();
    const q = query.trim().toLocaleLowerCase();
    const currentKey = keyOf(current ? current.choice : { kind: "same" });
    let shown = 0;
    for (const [group, list] of choicesFor(r)) {
      const items = q ? list.filter((x) => x.label.toLocaleLowerCase().includes(q) || group.toLocaleLowerCase().includes(q)) : list;
      if (!items.length) continue;
      if (group) box.append(el("h3", {}, group));
      const ul = el("ul", { class: "choices" });
      for (const x of items) {
        const k = keyOf(x.choice);
        const isCurrent = k === currentKey;
        const pending = pendingCustom === k;
        const b = el("button", {
          type: "button", class: `choice${isCurrent ? " current" : ""}${pending ? " pending" : ""}`,
          onclick: () => choose(r, x.choice, k),
        }, pending ? `Click again to change the button that opens this page: ${x.label}` : x.label,
        isCurrent ? el("span", { class: "dim" }, " ✓") : null);
        if (isCurrent) b.setAttribute("aria-current", "true");
        b.disabled = !writable();
        ul.append(el("li", {}, b));
        shown++;
      }
      box.append(ul);
    }
    if (!shown) box.append(el("p", { class: "hint" }, "Nothing matches."));
  }

  function choose(r, choice, k) {
    // Custom mode opens this page: changing its normal press takes a second click.
    if (r.control === "custom_mode" && sel.layer === "normal" && sel.slot === "press" && pendingCustom !== k) {
      pendingCustom = k;
      renderEditor();
      return;
    }
    pendingCustom = null;
    send({ op: "set", control: r.control, layer: sel.layer, slot: sel.slot, choice });
  }

  // ---- restore default layout (two clicks) ----------------------------------------
  $("restore").addEventListener("click", () => {
    const b = $("restore");
    if (restoreTimer) {
      clearTimeout(restoreTimer);
      restoreTimer = null;
      b.textContent = RESTORE_TEXT;
      send({ op: "restore_defaults" });
      return;
    }
    b.textContent = "Click again to restore the default layout (your P1–P8 presets are kept)";
    restoreTimer = setTimeout(() => { restoreTimer = null; b.textContent = RESTORE_TEXT; }, 5000);
  });

  return { onMessage, render };
})();
