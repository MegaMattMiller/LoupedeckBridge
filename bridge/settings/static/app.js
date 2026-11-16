// LoupedeckBridge settings page: assign Lightroom presets to P1–P8.
// Everything is built with DOM APIs and textContent: preset names are shown as text, never as HTML.
"use strict";

const MAX_RESULTS = 200;
const token = document.querySelector('meta[name="token"]').content;
const $ = (id) => document.getElementById(id);

let ws = null;
let state = null;          // {slots: [...], writable, lightroom}
let presets = null;        // [[id, name], ...]
let presetsRequested = false;
let selected = "p1";

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children) if (c != null) node.append(c);
  return node;
}

function send(msg) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}

function setStatus(kind, text) {
  $("status").dataset.kind = kind;
  $("status-text").textContent = text;
}

function notice(text) {
  const n = $("notice");
  n.textContent = text || "";
  n.hidden = !text;
}

// ---- connection -------------------------------------------------------------
function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.addEventListener("open", () => {
    send({ op: "hello", token });
    setStatus("ok", "Connected to the bridge");
  });
  ws.addEventListener("message", (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === "state") onState(msg);
    else if (msg.type === "presets") onPresets(msg.items);
    else if (msg.type === "error") onError(msg.message);
    else if (msg.type === "pressed") flash(msg.slot);
  });
  ws.addEventListener("close", () => {
    setStatus("down", "Bridge not reachable. Retrying…");
    presetsRequested = false;
    setTimeout(connect, 2000);
  });
}

function requestPresets() {
  presetsRequested = true;
  $("retry").hidden = true;
  $("presets-msg").textContent = "Loading presets from Lightroom…";
  send({ op: "presets" });
}

// ---- messages ---------------------------------------------------------------
function onState(msg) {
  state = msg;
  if (!msg.writable) {
    notice("Your mapping.json couldn't be read, so changes can't be saved. Fix or delete it, then restart the bridge.");
  } else {
    notice("");
  }
  if (!presets && !presetsRequested) requestPresets();
  renderSlots();
  renderResults();
}

function onPresets(items) {
  presets = items.slice().sort((a, b) => a[1].localeCompare(b[1], undefined, { sensitivity: "base" }));
  $("count").textContent = `(${presets.length.toLocaleString()})`;
  renderResults();
}

function onError(message) {
  if (!presets && presetsRequested) {
    $("presets-msg").textContent = message;
    $("retry").hidden = false;
  } else {
    notice(message);
  }
}

function flash(slot) {
  const row = document.querySelector(`[data-slot="${slot}"]`);
  if (!row) return;
  row.classList.remove("pressed");
  void row.offsetWidth; // restart the animation
  row.classList.add("pressed");
}

// ---- rendering ----------------------------------------------------------------
const BADGES = {
  missing: ["warn", "Not found in Lightroom"],
  ambiguous: ["warn", "Several presets have this name"],
  unknown: ["dim", "Not checked yet"],
};

function renderSlots() {
  const list = $("slots");
  list.replaceChildren();
  for (const s of state ? state.slots : []) {
    const empty = s.status === "empty";
    const badge = BADGES[s.status];
    const row = el("li", {
      class: `slot${s.slot === selected ? " selected" : ""}${empty ? " empty" : ""}`,
      "data-slot": s.slot,
    },
      el("button", {
        type: "button", class: "pick", "aria-pressed": String(s.slot === selected),
        "aria-label": `${s.slot.toUpperCase()}: ${empty ? "Empty" : (s.name || s.id)}${badge ? ` (${badge[1]})` : ""}`,
        onclick: () => { selected = s.slot; renderSlots(); renderResults(); $("search").focus(); },
      },
        el("span", { class: "key" }, s.slot.toUpperCase()),
        el("span", { class: "name" }, empty ? "Empty" : (s.name || s.id)),
        badge ? el("span", { class: `badge ${badge[0]}` }, badge[1]) : null),
      empty ? null : el("button", {
        type: "button", class: "clear", title: `Clear ${s.slot.toUpperCase()}`,
        "aria-label": `Clear ${s.slot.toUpperCase()}`,
        onclick: () => send({ op: "clear", slot: s.slot }),
      }, "✕"));
    list.append(row);
  }
}

function renderResults() {
  const list = $("results");
  list.replaceChildren();
  if (!presets) return;
  const q = $("search").value.trim().toLocaleLowerCase();
  const matches = q ? presets.filter(([, name]) => name.toLocaleLowerCase().includes(q)) : presets;
  const shown = matches.slice(0, MAX_RESULTS);
  const current = state && state.slots.find((s) => s.slot === selected);
  $("presets-msg").textContent = matches.length === 0
    ? "No presets match."
    : matches.length > MAX_RESULTS
      ? `Showing ${MAX_RESULTS} of ${matches.length.toLocaleString()}. Keep typing to narrow it down.`
      : `${matches.length.toLocaleString()} preset${matches.length === 1 ? "" : "s"}. Click one to put it on ${selected.toUpperCase()}.`;
  for (const [id, name] of shown) {
    const assigned = current && current.id === id;
    list.append(el("li", {},
      el("button", {
        type: "button", class: `preset${assigned ? " assigned" : ""}`,
        title: `Put “${name}” on ${selected.toUpperCase()}`,
        onclick: () => send({ op: "assign", slot: selected, id, name }),
      }, name, assigned ? el("span", { class: "dim" }, ` · on ${selected.toUpperCase()}`) : null)));
  }
}

$("search").addEventListener("input", renderResults);
$("retry").addEventListener("click", requestPresets);
connect();
