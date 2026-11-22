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
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(msg));
    return true;
  }
  notice("Not connected to the bridge right now, so that wasn't saved. Try again in a moment.");
  return false;
}

function setStatus(kind, text) {
  $("status").dataset.kind = kind;
  $("status-text").textContent = text;
}

function notice(text, kind) {
  const n = $("notice");
  n.textContent = text || "";
  n.dataset.kind = kind || "warn";
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
    else if (msg.type === "progress") onProgress(msg.done, msg.total);
    else if (msg.type === "error") onError(msg.message);
    else if (msg.type === "used") onUsed(msg);
    else if (msg.type === "reloaded") onReloaded(msg);
    else if (msg.type === "catalog" || msg.type === "layout" || msg.type === "fn") toRemap(msg);
  });
  ws.addEventListener("close", (e) => {
    presetsRequested = false;
    if (e.code === 1008) return reloadForNewToken();
    setStatus("down", "Bridge not reachable. Retrying…");
    setTimeout(connect, 2000);
  });
}

// The bridge makes a new token each time it starts, so a page left open across a restart is
// refused (1008). Reloading fetches the new one; the guard stops a loop if that ever fails.
function reloadForNewToken() {
  let last = 0;
  try { last = Number(sessionStorage.getItem("reloadedAt")) || 0; } catch (_) { /* storage blocked */ }
  if (Date.now() - last < 10000) {
    setStatus("down", "The bridge refused this page. Reload it to try again.");
    return;
  }
  try { sessionStorage.setItem("reloadedAt", String(Date.now())); } catch (_) { /* storage blocked */ }
  setStatus("down", "The bridge restarted. Reloading…");
  location.reload();
}

function requestPresets(refresh) {
  if (!send({ op: "presets", refresh: Boolean(refresh) })) return;
  presetsRequested = true;
  $("retry").hidden = true;
  $("refresh").disabled = true;
  if (refresh) { presets = null; $("results").replaceChildren(); }
  $("presets-msg").textContent = "Loading presets from Lightroom…";
}

function onProgress(done, total) {
  // Only shown while names are being fetched (the first time, or after Refresh list).
  if (!presets) {
    $("presets-msg").textContent =
      `Loading preset names from Lightroom… ${done.toLocaleString()} of ${total.toLocaleString()}. ` +
      "This only takes long the first time.";
  }
}

// ---- messages ---------------------------------------------------------------
function onState(msg) {
  state = msg;
  const MODES = { ratings: "Ratings", colours: "Colours", keys: "Keys" };
  $("five-mode").hidden = !MODES[msg.five_mode];
  $("five-mode").textContent = `Five buttons: ${MODES[msg.five_mode] || ""}`;
  $("five-mode").dataset.mode = msg.five_mode || "";
  setStatus(msg.lightroom ? "ok" : "warn",
    msg.lightroom ? "Connected to the bridge and Lightroom" : "Connected to the bridge · waiting for Lightroom");
  if (!msg.writable) {
    notice("Your mapping.json couldn't be read, so changes can't be saved. Fix or delete it, then click Reload from file.");
  } else {
    notice("");
  }
  if (!presets && !presetsRequested) {
    if (msg.lightroom) requestPresets();  // also when Lightroom shows up after the page opened
    else $("presets-msg").textContent = "Open Lightroom to load your presets.";
  }
  renderSlots();
  renderResults();
  if (typeof Remap !== "undefined") Remap.render();  // e.g. the file became (un)writable
}

// Reload from file's answer. It comes after the new state and layout, whose state message clears the notice line.
function onReloaded(msg) {
  notice(msg.changed ? `Reloaded the layout from ${msg.file}.` : `${msg.file} hasn't changed since it was read.`, "info");
}

// Messages for the Buttons & dials tab (remap.js).
function toRemap(msg) {
  if (typeof Remap !== "undefined") Remap.onMessage(msg);
}

function onUsed(msg) {
  if (/^p[1-8]$/.test(msg.control)) flash(msg.control);  // the Presets tab lights up P slots
  toRemap(msg);
}

function onPresets(items) {
  $("refresh").disabled = false;
  presets = items.slice().sort((a, b) => String(a[1]).localeCompare(String(b[1]), undefined, { sensitivity: "base" }));
  $("count").textContent = `(${presets.length.toLocaleString()})`;
  renderResults();
}

function onError(message) {
  $("refresh").disabled = false;
  if (!presets && presetsRequested) {
    presetsRequested = false;  // so it's asked again when Lightroom connects
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
  other: ["dim", "Not a preset"],
};

function renderSlots() {
  const list = $("slots");
  list.replaceChildren();
  for (const s of state ? state.slots : []) {
    const empty = s.status === "empty";
    const other = s.status === "other";  // e.g. a hand-edited action: shown as what it is
    const shown = empty ? "Empty" : other ? s.label : (s.name || s.id);
    const badge = BADGES[s.status];
    const row = el("li", {
      class: `slot${s.slot === selected ? " selected" : ""}${empty ? " empty" : ""}`,
      "data-slot": s.slot,
    },
      el("button", {
        type: "button", class: "pick", "aria-pressed": String(s.slot === selected),
        "aria-label": `${s.slot.toUpperCase()}: ${shown}${badge ? ` (${badge[1]})` : ""}`,
        onclick: () => { selected = s.slot; renderSlots(); renderResults(); $("search").focus(); },
      },
        el("span", { class: "key" }, s.slot.toUpperCase()),
        el("span", { class: "name" }, shown),
        badge ? el("span", { class: `badge ${badge[0]}` }, badge[1]) : null),
      empty || other ? null : el("button", {
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
  const matches = q ? presets.filter(([, name]) => String(name).toLocaleLowerCase().includes(q)) : presets;
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

// ---- tabs -------------------------------------------------------------------------
function showTab(name) {
  for (const t of ["presets", "remap"]) {
    $(`tab-${t}`).hidden = t !== name;
    $(`tab-btn-${t}`).setAttribute("aria-selected", String(t === name));
  }
  try { localStorage.setItem("lb.tab", name); } catch (_) { /* storage blocked: the tab just isn't remembered */ }
  if (name === "remap" && typeof Remap !== "undefined") Remap.render();
}
$("tab-btn-presets").addEventListener("click", () => showTab("presets"));
$("tab-btn-remap").addEventListener("click", () => showTab("remap"));
let startTab = "presets";
try { if (localStorage.getItem("lb.tab") === "remap") startTab = "remap"; } catch (_) { /* storage blocked */ }
showTab(startTab);

$("search").addEventListener("input", renderResults);
$("retry").addEventListener("click", () => requestPresets(false));
$("refresh").addEventListener("click", () => requestPresets(true));
$("reload").addEventListener("click", () => send({ op: "reload" }));
connect();
