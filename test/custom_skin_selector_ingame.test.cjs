// Regression test: ROSE-CustomSkinSelector must stop its body-wide
// MutationObserver and 500ms scan interval while a game is running
// (phase InProgress) and re-arm them in every other phase (GitHub issue #22).
// Runs the real plugin in a VM with a tiny fake DOM and bridge:
//   node --test test/custom_skin_selector_ingame.test.cjs
// CUSTOM_SKIN_SELECTOR_PLUGIN=<path> runs it against another copy of the plugin.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const PLUGIN = process.env.CUSTOM_SKIN_SELECTOR_PLUGIN ||
  path.join(__dirname, "..", "Pengu Loader", "plugins", "ROSE-CustomSkinSelector", "index.js");

async function loadPlugin() {
  const live = { observers: new Set(), intervals: new Set() };
  const handlers = {};
  let nextId = 1;

  class FakeMutationObserver {
    observe() { live.observers.add(this); }
    disconnect() { live.observers.delete(this); }
  }

  const bridge = {
    subscribe: (type, fn) => { handlers[type] = fn; },
    onReady() {},
    send() {},
  };
  const body = { appendChild() {} };
  const document = {
    readyState: "complete",
    body,
    head: { appendChild() {} },
    getElementById: () => null,
    createElement: () => ({}),
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener() {},
    removeEventListener() {},
  };
  const context = {
    document,
    console: { log() {}, warn() {}, error() {} },
    MutationObserver: FakeMutationObserver,
    setTimeout: () => 0,
    clearTimeout() {},
    setInterval: () => { const id = nextId++; live.intervals.add(id); return id; },
    clearInterval: (id) => { live.intervals.delete(id); },
  };
  context.window = context;
  context.__roseBridge = bridge;
  context.addEventListener = () => {};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(PLUGIN, "utf8"), context, { filename: PLUGIN });
  for (let i = 0; i < 5; i++) await new Promise((resolve) => setImmediate(resolve));
  return { live, phase: (p) => handlers["phase-change"]({ phase: p }) };
}

test("observer and scan interval stop in InProgress and re-arm otherwise", async () => {
  const { live, phase } = await loadPlugin();
  assert.equal(live.observers.size, 1, "starts armed before any phase is known");
  assert.equal(live.intervals.size, 1);

  phase("InProgress");
  assert.equal(live.observers.size, 0, "observer disconnected in game");
  assert.equal(live.intervals.size, 0, "interval cleared in game");

  phase("InProgress");
  assert.equal(live.observers.size, 0);

  phase("ChampSelect");
  assert.equal(live.observers.size, 1);
  assert.equal(live.intervals.size, 1);

  phase("ChampSelect");
  assert.equal(live.observers.size, 1, "start is idempotent");
  assert.equal(live.intervals.size, 1);

  phase("InProgress");
  phase("Lobby");
  assert.equal(live.observers.size, 1, "Swiftplay Lobby keeps it running");
  assert.equal(live.intervals.size, 1);
});
