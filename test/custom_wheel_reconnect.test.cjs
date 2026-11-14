// ROSE-CustomWheel when Rose restarts while the League client stays open.
// Runs the real plugin in a VM with a permissive fake DOM and a fake bridge:
//   node --test test/custom_wheel_reconnect.test.cjs
// CUSTOM_WHEEL_PLUGIN=<path> runs it against another copy of the plugin.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const PLUGIN = process.env.CUSTOM_WHEEL_PLUGIN ||
  path.join(__dirname, "..", "Pengu Loader", "plugins", "ROSE-CustomWheel", "index.js");

// ─── Fake DOM: any element, every call answers with another one ──────────

function makeEl() {
  const store = {
    style: { setProperty() {}, removeProperty() {}, getPropertyValue() { return ""; } },
    dataset: {},
    children: [],
    childNodes: [],
    classList: { add() {}, remove() {}, contains() { return false; }, toggle() {} },
  };
  return new Proxy(function () {}, {
    get(t, k) {
      if (k in store) return store[k];
      if (k === Symbol.toPrimitive) return () => "";
      if (k === "querySelector" || k === "closest") return () => null;
      if (k === "querySelectorAll") return () => [];
      if (k === "getBoundingClientRect") return () => ({ left: 0, top: 0, width: 0, height: 0 });
      if (k === "contains") return () => false;
      if (k === "parentNode" || k === "firstChild" || k === "parentElement" || k === "shadowRoot") return null;
      if (k === "textContent" || k === "innerHTML" || k === "className" || k === "id") return "";
      if (k === "offsetHeight" || k === "offsetWidth") return 0;
      if (k === "then") return undefined;
      return () => makeEl();
    },
    set(t, k, v) { store[k] = v; return true; },
  });
}

async function settle() {
  for (let i = 0; i < 10; i++) await new Promise((resolve) => setImmediate(resolve));
}

// ─── Plugin under test, with a fake ROSE-SkinMonitor bridge ──────────────

async function loadPlugin() {
  const document = {
    readyState: "complete",
    head: makeEl(),
    body: makeEl(),
    addEventListener() {},
    removeEventListener() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
    getElementById() { return null; },
    createElement: () => makeEl(),
    createElementNS: () => makeEl(),
    createTextNode: () => makeEl(),
  };
  const sent = [];
  const subscribers = new Map();
  const readyCallbacks = [];
  const bridge = {
    send: (message) => sent.push(message),
    subscribe(type, cb) { (subscribers.get(type) || subscribers.set(type, []).get(type)).push(cb); },
    unsubscribe() {},
    // Like the real bridge: runs at once when already connected, again on every reconnect
    onReady(cb) { readyCallbacks.push(cb); cb(); },
    onDisconnect() {},
  };
  const window = {
    document,
    __roseBridge: bridge,
    addEventListener() {},
    innerWidth: 1280,
    innerHeight: 720,
    getComputedStyle: () => ({ position: "static" }),
  };
  const context = vm.createContext({
    window,
    document,
    console: { log() {}, warn() {}, error() {}, debug() {} },
    // Long timers (give-up timeouts) never fire
    setTimeout: (fn, ms) => (ms && ms >= 10000 ? 0 : setImmediate(fn)),
    clearTimeout() {},
    setInterval() { return 0; },
    clearInterval() {},
    requestAnimationFrame: (fn) => setImmediate(fn),
    MutationObserver: class { observe() {} disconnect() {} },
    Node: { TEXT_NODE: 3 },
    CustomEvent: class {},
  });
  vm.runInContext(fs.readFileSync(PLUGIN, "utf8"), context, { filename: PLUGIN });
  await settle();

  return {
    sent,
    receive(data) { for (const cb of subscribers.get(data.type) || []) cb(data); },
    // The bridge connected to Rose again (a restarted Rose, or the same one)
    reconnect() { for (const cb of readyCallbacks) cb(); },
    selects: () => sent.filter((m) => m.type === "select-other"),
  };
}

const VFX_MOD = { id: "vfx/Cool Particles.fantome", name: "Cool Particles" };
const vfxResponse = () => ({
  type: "category-mods-response",
  category: "vfx",
  mods: [VFX_MOD],
  historicMod: [VFX_MOD.id],
});

test("a saved category mod is selected in Rose again after Rose restarts", async () => {
  const ui = await loadPlugin();
  ui.receive(vfxResponse());
  assert.equal(ui.selects().length, 1, "the saved mod is selected in Rose");

  // Rose restarts with nothing selected; the bridge reconnects and asks again
  const before = ui.sent.length;
  ui.reconnect();
  assert.ok(
    ui.sent.slice(before).some((m) => m.type === "request-category-mods" && m.category === "vfx"),
    "the category is requested again on reconnect",
  );
  ui.receive(vfxResponse());

  const selects = ui.selects();
  assert.equal(selects.length, 2, "the saved mod is selected in the new Rose too");
  assert.deepEqual(
    { category: selects[1].category, otherId: selects[1].otherId, action: selects[1].action },
    { category: "vfx", otherId: VFX_MOD.id, action: "select" },
  );
});

test("a saved category mod is sent once per connection", async () => {
  const ui = await loadPlugin();
  ui.receive(vfxResponse());
  ui.receive(vfxResponse()); // the list is asked for again (panel opened, tab switched)
  assert.equal(ui.selects().length, 1);
});
