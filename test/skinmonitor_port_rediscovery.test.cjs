// ROSE-SkinMonitor when Rose is not running yet as the client starts, then
// takes a port other than 50000 (some of 50000-50099 can be reserved by Windows).
// Runs the real plugin in a VM with fake fetch, WebSocket and timers:
//   node --test test/skinmonitor_port_rediscovery.test.cjs
// SKIN_MONITOR_PLUGIN=<path> runs it against another copy of the plugin.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const PLUGIN = process.env.SKIN_MONITOR_PLUGIN ||
  path.join(__dirname, "..", "Pengu Loader", "plugins", "ROSE-SkinMonitor", "index.js");

// ─── Fake WebSocket ──────────────────────────────────────────────────────

class FakeWebSocket {
  constructor(url) {
    this.url = url;
    this.readyState = FakeWebSocket.CONNECTING;
    this.listeners = {};
    this.sent = [];
    FakeWebSocket.instances.push(this);
  }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  emit(type, event) { for (const fn of this.listeners[type] || []) fn(event); }
  send(message) {
    if (this.readyState !== FakeWebSocket.OPEN) throw new Error("socket is not open");
    this.sent.push(JSON.parse(message));
  }
  close() { this.readyState = FakeWebSocket.CLOSED; }

  // Test controls
  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.emit("open", {});
  }
  fail() {
    this.readyState = FakeWebSocket.CLOSED;
    this.emit("error", {});
    this.emit("close", {});
  }
}
Object.assign(FakeWebSocket, { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 });

async function settle() {
  for (let i = 0; i < 10; i++) await new Promise((resolve) => setImmediate(resolve));
}

// ─── Plugin under test ───────────────────────────────────────────────────

async function loadPlugin({ cachedPort = null } = {}) {
  FakeWebSocket.instances = [];
  const rose = { port: null }; // null: Rose is not running
  const storage = new Map();
  if (cachedPort) storage.set("rose_bridge_port", String(cachedPort));
  const timeouts = new Map();
  let nextTimeout = 1;
  const fetches = [];

  const context = {
    console: { log() {}, warn() {}, error() {} },
    WebSocket: FakeWebSocket,
    AbortSignal: { timeout: () => undefined },
    // Rose answers its discovery endpoints with its port, on that port only
    fetch(url) {
      fetches.push(url);
      const { port, pathname } = new URL(url);
      if (rose.port !== null && Number(port) === rose.port && (pathname === "/bridge-port" || pathname === "/port")) {
        return Promise.resolve({ ok: true, text: () => Promise.resolve(String(rose.port)) });
      }
      return Promise.reject(new TypeError("Failed to fetch"));
    },
    localStorage: {
      getItem: (k) => (storage.has(k) ? storage.get(k) : null),
      setItem: (k, v) => storage.set(k, String(v)),
      removeItem: (k) => storage.delete(k),
    },
    document: {
      readyState: "complete",
      body: {},
      querySelectorAll: () => [],
      addEventListener() {},
    },
    MutationObserver: class { observe() {} disconnect() {} },
    PerformanceObserver: class { observe() {} },
    CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } },
    Node: class {},
    setTimeout(fn, ms) {
      const id = nextTimeout++;
      timeouts.set(id, { fn, ms });
      return id;
    },
    clearTimeout(id) { timeouts.delete(id); },
    setInterval: () => 1,
    clearInterval() {},
    addEventListener() {},
    dispatchEvent() { return true; },
  };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(PLUGIN, "utf8"), context, { filename: PLUGIN });
  await settle();

  return {
    rose,
    storage,
    fetches,
    bridge: () => context.__roseBridge,
    get socket() { return FakeWebSocket.instances[FakeWebSocket.instances.length - 1]; },
    // Run the reconnect timer the plugin set when its connection failed
    async retry() {
      assert.equal(timeouts.size, 1, "one reconnect is scheduled");
      const [[id, { fn }]] = timeouts;
      timeouts.delete(id);
      fn();
      await settle();
    },
  };
}

function assertConnected(plugin, port) {
  assert.equal(plugin.socket.url, `ws://127.0.0.1:${port}`);
  plugin.socket.open();
  assert.equal(plugin.bridge().ready, true);
  assert.equal(plugin.bridge().port, port, "other plugins get Rose's port from __roseBridge");
  assert.deepEqual(plugin.socket.sent[0], { type: "rose-plugin-ready", plugin: "ROSE-SkinMonitor", protocol: 1 });
}

test("Rose started after the client on another port is found on reconnect", async () => {
  const plugin = await loadPlugin();
  assert.equal(plugin.socket.url, "ws://127.0.0.1:50000", "nothing found yet: the default port");
  plugin.socket.fail();

  await plugin.retry(); // still not running
  assert.equal(plugin.socket.url, "ws://127.0.0.1:50000");
  plugin.socket.fail();

  plugin.rose.port = 50060;
  await plugin.retry();
  assertConnected(plugin, 50060);
  assert.equal(plugin.storage.get("rose_bridge_port"), "50060");
});

test("the cached port is kept while Rose is not running", async () => {
  const plugin = await loadPlugin({ cachedPort: 50060 });
  assert.equal(plugin.storage.get("rose_bridge_port"), "50060");
  plugin.socket.fail();

  plugin.rose.port = 50060;
  await plugin.retry();
  assertConnected(plugin, 50060);
  assert.equal(plugin.storage.get("rose_bridge_port"), "50060");
});

test("a stale cached port is replaced by the one Rose took", async () => {
  const plugin = await loadPlugin({ cachedPort: 50003 });
  plugin.socket.fail();

  plugin.rose.port = 50060;
  await plugin.retry();
  assertConnected(plugin, 50060);
  assert.equal(plugin.storage.get("rose_bridge_port"), "50060");
});

test("after Rose restarts on another port, the plugin follows it", async () => {
  const plugin = await loadPlugin();
  plugin.rose.port = 50060;
  plugin.socket.fail();
  await plugin.retry();
  assertConnected(plugin, 50060);

  // Rose restarts and takes another port
  plugin.rose.port = null;
  plugin.socket.fail();
  const fetchesBefore = plugin.fetches.length;
  await plugin.retry(); // the port that just worked is tried first, without scanning
  assert.equal(plugin.fetches.length, fetchesBefore);
  assert.equal(plugin.socket.url, "ws://127.0.0.1:50060");
  plugin.rose.port = 50061;
  plugin.socket.fail();

  await plugin.retry();
  assertConnected(plugin, 50061);
  assert.equal(plugin.storage.get("rose_bridge_port"), "50061");
});
