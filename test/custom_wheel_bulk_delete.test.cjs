// ROSE-CustomWheel must drop mods deleted through the mod manager's
// multi-select "Delete selected" (bulk messages) from its selection.
//   node --test test/custom_wheel_bulk_delete.test.cjs
// CUSTOM_WHEEL_PLUGIN=<path> runs it against another copy of the plugin.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const PLUGIN = process.env.CUSTOM_WHEEL_PLUGIN ||
  path.join(__dirname, "..", "Pengu Loader", "plugins", "ROSE-CustomWheel", "index.js");

// Permissive fake element: plain props are stored, any other method is a no-op
// returning another fake element. Enough to boot the plugin and read the badge.
function fakeElement() {
  const own = { shadowRoot: null, style: { setProperty() {}, removeProperty() {} }, dataset: {}, children: [], childNodes: [], textContent: "" };
  own.classList = { add() {}, remove() {}, toggle() {}, contains: () => false };
  return new Proxy(own, {
    get(o, k) {
      if (k in o) return o[k];
      if (typeof k === "symbol" || k === "then") return undefined;
      if (k === "querySelector" || k === "closest" || k === "getAttribute") return () => null;
      if (k === "querySelectorAll") return () => [];
      return () => fakeElement();
    },
  });
}

async function bootWheel() {
  const handlers = {};
  const sent = [];
  const bridge = {
    subscribe: (type, fn) => { handlers[type] = fn; },
    send: (msg) => { sent.push(msg); },
    onReady() {},
  };
  const created = [];
  const document = {
    readyState: "complete",
    head: fakeElement(),
    body: fakeElement(),
    createElement: () => { const el = fakeElement(); created.push(el); return el; },
    addEventListener() {},
    getElementById: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
  };
  const window = {
    __roseBridge: bridge, addEventListener() {}, setTimeout, clearTimeout,
    getComputedStyle: () => ({ getPropertyValue: () => "" }),
  };
  const sandbox = {
    window, document, console: { log() {}, warn() {}, error() {} },
    setTimeout: (fn, ms) => setTimeout(fn, ms).unref(), clearTimeout, setInterval: () => 0, clearInterval() {},
    requestAnimationFrame: (fn) => setTimeout(fn, 0),
    MutationObserver: class { observe() {} disconnect() {} },
    CustomEvent: class {}, Event: class {}, localStorage: { getItem: () => null, setItem() {} },
  };
  window.document = document;
  vm.runInNewContext(fs.readFileSync(PLUGIN, "utf8"), sandbox, { filename: PLUGIN });
  await new Promise((resolve) => setTimeout(resolve, 20));
  // The wheel's button is the element that got a count badge attached.
  const badge = created.find((el) => "_countBadge" in el)._countBadge;
  return { handlers, sent, badge };
}

test("bulk delete of the selected map clears the selection and badge", async () => {
  const { handlers, sent, badge } = await bootWheel();
  handlers["maps-response"]({
    type: "maps-response",
    maps: [{ id: "maps/Foo", name: "Foo" }],
    historicMod: "maps/Foo",
  });
  assert.equal(badge.style.display, "flex");
  assert.equal(badge.textContent, "1");

  sent.length = 0;
  handlers["category-mods-bulk-deleted"]?.({
    type: "category-mods-bulk-deleted",
    category: "maps",
    success: true,
    deletedCount: 1,
    results: [{ success: true, modName: "Foo" }],
  });
  assert.equal(badge.style.display, "none");
  assert.ok(sent.some((m) => m.type === "request-maps"), "refreshes the maps list");
});

test("bulk delete ignores items that failed to delete", async () => {
  const { handlers, badge } = await bootWheel();
  handlers["maps-response"]({
    type: "maps-response",
    maps: [{ id: "maps/Foo", name: "Foo" }],
    historicMod: "maps/Foo",
  });
  handlers["category-mods-bulk-deleted"]?.({
    type: "category-mods-bulk-deleted",
    category: "maps",
    success: false,
    partial: false,
    deletedCount: 0,
    results: [{ success: false, modName: "Foo", error: "Mod not found" }],
  });
  assert.equal(badge.style.display, "flex");
});
