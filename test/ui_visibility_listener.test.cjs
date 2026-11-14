// ROSE-UI must not leave a document "visibilitychange" listener behind each
// time the skin observer is stopped (InProgress) and started again:
//   node --test test/ui_visibility_listener.test.cjs
// ROSE_UI_PLUGIN=<path> runs it against another copy of the plugin.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const PLUGIN = process.env.ROSE_UI_PLUGIN ||
  path.join(__dirname, "..", "Pengu Loader", "plugins", "ROSE-UI", "index.js");

const stubEl = () => ({
  classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
  style: { setProperty() {}, removeProperty() {} }, dataset: {},
  appendChild() {}, insertBefore() {}, querySelector: () => null,
  querySelectorAll: () => [], addEventListener() {}, setAttribute() {},
});

test("stopping the skin observer removes its visibilitychange listener", async () => {
  const visibility = [];
  const subs = {};
  const document = {
    readyState: "complete", head: stubEl(), body: stubEl(), documentElement: stubEl(),
    visibilityState: "visible", createElement: stubEl,
    getElementById: () => null, querySelector: () => null, querySelectorAll: () => [],
    addEventListener(type, fn) { if (type === "visibilitychange") visibility.push(fn); },
    removeEventListener(type, fn) {
      const i = visibility.indexOf(fn);
      if (type === "visibilitychange" && i >= 0) visibility.splice(i, 1);
    },
  };
  const context = {
    document,
    window: {
      __roseBridge: { port: 50000, subscribe(t, cb) { (subs[t] ||= []).push(cb); } },
      rcp: { postInit() {} },
      addEventListener() {}, removeEventListener() {}, dispatchEvent() {},
    },
    console: { info() {}, warn() {}, error() {}, log() {} },
    MutationObserver: class { observe() {} disconnect() {} },
    setInterval: () => 1, clearInterval() {},
    setTimeout: (fn) => setTimeout(fn, 0), requestAnimationFrame: (fn) => setTimeout(fn, 0),
    fetch: () => Promise.reject(new Error("no Rose in tests")), CustomEvent: class {},
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(PLUGIN, "utf8"), context, { filename: PLUGIN });
  await new Promise((resolve) => setTimeout(resolve, 50));

  const phase = subs["phase-change"][0];
  assert.equal(visibility.length, 1, "one listener while the observer runs");
  for (let game = 1; game <= 5; game++) {
    phase({ phase: "InProgress" });
    assert.equal(visibility.length, 0, "no listener during the game");
    phase({ phase: "EndOfGame" });
    assert.equal(visibility.length, 1, `one listener after game ${game}`);
  }
});
