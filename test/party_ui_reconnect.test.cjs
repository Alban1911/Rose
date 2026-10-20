// ROSE-PartyMode when its connection to Rose drops mid-request.
// Runs the real plugin in a VM with a small fake DOM and WebSocket:
//   node --test test/party_ui_reconnect.test.cjs
// PARTY_MODE_PLUGIN=<path> runs it against another copy of the plugin.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const PLUGIN = process.env.PARTY_MODE_PLUGIN ||
  path.join(__dirname, "..", "Pengu Loader", "plugins", "ROSE-PartyMode", "index.js");

// ─── Fake DOM: the parts of it the plugin uses ───────────────────────────

const VOID_TAGS = new Set(["input", "br", "img", "meta", "link"]);
const ENTITIES = { "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#039;": "'", "&amp;": "&" };
const decode = (text) => text.replace(/&(lt|gt|quot|#039|amp);/g, (m) => ENTITIES[m]);

class TextNode {
  constructor(text) {
    this.text = text;
    this.parentNode = null;
  }
}

class Element {
  constructor(tag, document) {
    this.localName = tag.toLowerCase();
    this.ownerDocument = document;
    this.attrs = new Map();
    this.childNodes = [];
    this.parentNode = null;
    this.listeners = {};
    this.style = {};
    this.value = "";
    this.disabled = false;
    const self = this;
    this.classList = {
      contains: (c) => self.classes().includes(c),
      add: (...cs) => self.setClasses([...new Set([...self.classes(), ...cs])]),
      remove: (...cs) => self.setClasses(self.classes().filter((c) => !cs.includes(c))),
      toggle(c, force) {
        const on = force === undefined ? !this.contains(c) : force;
        if (on) this.add(c); else this.remove(c);
        return on;
      },
    };
  }

  classes() { return (this.attrs.get("class") || "").split(/\s+/).filter(Boolean); }
  setClasses(list) { this.attrs.set("class", list.join(" ")); }
  get id() { return this.attrs.get("id") || ""; }
  set id(v) { this.attrs.set("id", String(v)); }
  get className() { return this.attrs.get("class") || ""; }
  set className(v) { this.attrs.set("class", String(v)); }

  setAttribute(name, value) {
    this.attrs.set(name, String(value));
    if (name === "disabled") this.disabled = true;
    if (name === "value") this.value = String(value);
    if (name === "style") {
      for (const rule of String(value).split(";")) {
        const [k, v] = rule.split(":").map((x) => x && x.trim());
        if (k) this.style[k] = v;
      }
    }
  }
  getAttribute(name) { return this.attrs.has(name) ? this.attrs.get(name) : null; }
  hasAttribute(name) { return this.attrs.has(name); }
  removeAttribute(name) { this.attrs.delete(name); }

  get children() { return this.childNodes.filter((n) => n instanceof Element); }
  appendChild(node) { return this.insertBefore(node, null); }
  insertBefore(node, ref) {
    if (node.parentNode) node.parentNode.removeChild(node);
    const index = ref ? this.childNodes.indexOf(ref) : -1;
    if (index < 0) this.childNodes.push(node); else this.childNodes.splice(index, 0, node);
    node.parentNode = this;
    return node;
  }
  removeChild(node) {
    this.childNodes = this.childNodes.filter((n) => n !== node);
    node.parentNode = null;
    return node;
  }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  get nextSibling() {
    if (!this.parentNode) return null;
    const siblings = this.parentNode.childNodes;
    return siblings[siblings.indexOf(this) + 1] || null;
  }
  get isConnected() {
    let node = this;
    while (node.parentNode) node = node.parentNode;
    return node === this.ownerDocument.documentElement;
  }

  get textContent() {
    return this.childNodes.map((n) => (n instanceof TextNode ? n.text : n.textContent)).join("");
  }
  set textContent(value) {
    this.childNodes = [];
    this.appendChild(new TextNode(String(value)));
  }
  get innerHTML() { return this.childNodes.map(serialize).join(""); }
  set innerHTML(html) {
    this.childNodes = [];
    parseInto(this, String(html));
  }

  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  removeEventListener(type, fn) { this.listeners[type] = (this.listeners[type] || []).filter((f) => f !== fn); }
  dispatchEvent(event) {
    event.target = this;
    for (const fn of [...(this.listeners[event.type] || [])]) fn(event);
    return true;
  }
  click() { this.dispatchEvent({ type: "click", stopPropagation() {}, preventDefault() {} }); }
  getBoundingClientRect() { return { left: 0, top: 0, bottom: 0, width: 0, height: 0 }; }

  descendants() {
    const out = [];
    for (const child of this.children) out.push(child, ...child.descendants());
    return out;
  }
  matches(selector) {
    const parts = selector.trim().split(/\s+/);
    if (!matchesCompound(this, parts[parts.length - 1])) return false;
    let node = this.parentNode;
    for (let i = parts.length - 2; i >= 0; i--) {
      while (node instanceof Element && !matchesCompound(node, parts[i])) node = node.parentNode;
      if (!(node instanceof Element)) return false;
      node = node.parentNode;
    }
    return true;
  }
  querySelectorAll(selector) { return this.descendants().filter((el) => el.matches(selector)); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) {
    for (let node = this; node instanceof Element; node = node.parentNode) {
      if (node.matches(selector)) return node;
    }
    return null;
  }
}

function matchesCompound(el, compound) {
  const tokens = compound.match(/[#.]?[^#.]+/g) || [];
  return tokens.every((token) => {
    if (token[0] === "#") return el.id === token.slice(1);
    if (token[0] === ".") return el.classList.contains(token.slice(1));
    return el.localName === token.toLowerCase();
  });
}

function serialize(node) {
  if (node instanceof TextNode) return node.text;
  const attrs = [...node.attrs].map(([k, v]) => ` ${k}="${v}"`).join("");
  return `<${node.localName}${attrs}>${node.childNodes.map(serialize).join("")}</${node.localName}>`;
}

function parseInto(root, html) {
  const document = root.ownerDocument;
  const stack = [root];
  const tagRe = /<\/?([a-zA-Z][\w-]*)((?:\s+[^\s=/>]+(?:\s*=\s*(?:"[^"]*"|'[^']*'))?)*)\s*(\/?)>/g;
  let last = 0;
  let match;
  while ((match = tagRe.exec(html))) {
    const text = html.slice(last, match.index);
    if (text) stack[stack.length - 1].appendChild(new TextNode(decode(text)));
    last = tagRe.lastIndex;
    const [whole, tag, attrText, selfClose] = match;
    if (whole[1] === "/") {
      while (stack.length > 1 && stack.pop().localName !== tag.toLowerCase());
      continue;
    }
    const el = document.createElement(tag);
    const attrRe = /([^\s=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'))?/g;
    let attr;
    while ((attr = attrRe.exec(attrText))) el.setAttribute(attr[1], decode(attr[2] ?? attr[3] ?? ""));
    stack[stack.length - 1].appendChild(el);
    if (!selfClose && !VOID_TAGS.has(tag.toLowerCase())) stack.push(el);
  }
  const rest = html.slice(last);
  if (rest) stack[stack.length - 1].appendChild(new TextNode(decode(rest)));
}

class FakeDocument {
  constructor() {
    this.readyState = "complete";
    this.documentElement = new Element("html", this);
    this.head = this.documentElement.appendChild(new Element("head", this));
    this.body = this.documentElement.appendChild(new Element("body", this));
  }
  createElement(tag) { return new Element(tag, this); }
  getElementById(id) { return this.documentElement.descendants().find((el) => el.id === id) || null; }
  querySelector(selector) { return this.documentElement.querySelector(selector); }
  querySelectorAll(selector) { return this.documentElement.querySelectorAll(selector); }
  addEventListener() {}
}

// ─── Fake WebSocket and timers ───────────────────────────────────────────

class FakeWebSocket {
  constructor(url) {
    this.url = url;
    this.readyState = FakeWebSocket.CONNECTING;
    this.sent = [];
    FakeWebSocket.instances.push(this);
  }
  send(message) {
    if (this.readyState !== FakeWebSocket.OPEN) throw new Error("socket is not open");
    this.sent.push(JSON.parse(message));
  }
  close() { this.drop(); }

  // Test controls
  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen && this.onopen({});
  }
  receive(data) { this.onmessage({ data: JSON.stringify(data) }); }
  drop() {
    if (this.readyState === FakeWebSocket.CLOSED) return;
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose && this.onclose({});
  }
  types() { return this.sent.map((m) => m.type); }
}
Object.assign(FakeWebSocket, { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 });

async function settle() {
  for (let i = 0; i < 5; i++) await new Promise((resolve) => setImmediate(resolve));
}

// ─── Plugin under test ───────────────────────────────────────────────────

async function loadPlugin() {
  FakeWebSocket.instances = [];
  const document = new FakeDocument();
  // The social bar the party button goes into
  document.body.innerHTML = '<div class="lol-social-actions-bar"><div class="buttons"></div></div>';
  const timeouts = [];
  const storage = new Map();
  const context = {
    document,
    console: { log() {}, warn() {}, error() {} },
    WebSocket: FakeWebSocket,
    AbortSignal,
    fetch: () => Promise.reject(new Error("no Rose in tests")),
    localStorage: {
      getItem: (k) => (storage.has(k) ? storage.get(k) : null),
      setItem: (k, v) => storage.set(k, String(v)),
      removeItem: (k) => storage.delete(k),
    },
    setTimeout: (fn, ms) => timeouts.push({ fn, ms }),
    clearTimeout() {},
    setInterval: () => 1,
    clearInterval() {},
    requestAnimationFrame() {},
    navigator: { clipboard: { writeText: async () => {} } },
    addEventListener() {},
  };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(PLUGIN, "utf8"), context, { filename: PLUGIN });
  await settle();

  const ui = {
    document,
    get socket() { return FakeWebSocket.instances[FakeWebSocket.instances.length - 1]; },
    get sockets() { return FakeWebSocket.instances; },
    el: (id) => document.getElementById(id),
    text: (id) => document.getElementById(id).textContent.replace(/\s+/g, " ").trim(),
    dialog: () => document.querySelector(".party-dialog"),
    panelVisible: () => document.getElementById("rose-party-panel").classList.contains("visible"),
    openPanel() { document.getElementById("rose-party-lobby-button").click(); },
    // Run the reconnect timer the plugin set when its connection dropped
    reconnect() {
      const index = timeouts.findIndex((t) => t.ms === 1000);
      assert.notEqual(index, -1, "a reconnect is scheduled");
      timeouts.splice(index, 1)[0].fn();
    },
    state(enabled, extra = {}) {
      this.socket.receive({ type: "party-state", enabled, connection: enabled ? "online" : "offline", my_token: enabled ? "ROSE:mine" : null, peers: [], ...extra });
    },
  };
  ui.socket.open();
  return ui;
}

function assertPanelUnlocked(ui) {
  assert.ok(ui.dialog().hasAttribute("close-button"), "the panel can be closed");
  assert.notEqual(ui.el("party-done-btn").style.display, "none", "Done is shown");
  assert.equal(ui.el("add-peer-input").disabled, false);
  assert.equal(ui.el("add-peer-btn").disabled, false);
  assert.equal(ui.text("add-peer-btn"), "Add");
  assert.equal(ui.el("party-toggle-btn").disabled, false);
}

test("a dropped connection while adding a friend gives the panel back, token included", async () => {
  const ui = await loadPlugin();
  ui.state(true);
  ui.openPanel();
  assert.ok(ui.panelVisible());

  ui.el("add-peer-input").value = "ROSE:friend";
  ui.el("add-peer-btn").click();
  assert.deepEqual(ui.socket.sent.at(-1), { type: "party-add-peer", token: "ROSE:friend" });
  assert.equal(ui.dialog().hasAttribute("close-button"), false, "locked while Rose connects");

  const first = ui.socket;
  first.drop();

  assertPanelUnlocked(ui);
  assert.ok(ui.panelVisible(), "the panel stays open");
  assert.equal(ui.el("add-peer-input").value, "ROSE:friend", "the token is back, ready to retry");
  assert.match(ui.text("add-peer-message"), /Lost the connection to Rose/);

  // Back online: nothing is sent again on its own; the user retries
  ui.reconnect();
  ui.socket.open();
  assert.notEqual(ui.socket, first);
  assert.deepEqual(ui.socket.types(), ["party-get-state"]);
  assert.equal(ui.text("add-peer-message"), "", "the connection error is gone");
  ui.state(true);
  ui.el("add-peer-btn").click();
  assert.deepEqual(ui.socket.sent.at(-1), { type: "party-add-peer", token: "ROSE:friend" });

  // And the panel closes again once Rose answers
  ui.socket.receive({ type: "party-peer-added", success: true, message: "Connected to B" });
  ui.dialog().dispatchEvent({ type: "dialogFrameDismissed" });
  assert.equal(ui.panelVisible(), false);
});

for (const [enabled, request, label] of [[false, "party-enable", "Enable Party Mode"], [true, "party-disable", "Disable Party Mode"]]) {
  test(`a dropped connection during ${request} gives the toggle back`, async () => {
    const ui = await loadPlugin();
    ui.state(enabled);
    ui.openPanel();

    ui.el("party-toggle-btn").click();
    assert.equal(ui.socket.sent.at(-1).type, request);
    assert.equal(ui.el("party-toggle-btn").disabled, true);

    ui.socket.drop();
    assert.equal(ui.el("party-toggle-btn").disabled, false);
    assert.equal(ui.text("party-toggle-btn"), label);
    assert.match(ui.text("party-toggle-message"), /Lost the connection to Rose/);
    assert.ok(ui.panelVisible());

    ui.reconnect();
    ui.socket.open();
    assert.deepEqual(ui.socket.types(), ["party-get-state"]);
    ui.state(enabled);
    assert.equal(ui.el("party-toggle-btn").disabled, false);
    ui.el("party-toggle-btn").click();
    assert.equal(ui.socket.sent.at(-1).type, request);
  });
}

test("a request made while Rose is unreachable is refused at once, never sent later", async () => {
  const ui = await loadPlugin();
  ui.state(true);
  ui.openPanel();
  ui.socket.drop();

  ui.el("add-peer-input").value = "ROSE:friend";
  ui.el("add-peer-btn").click();
  assert.match(ui.text("add-peer-message"), /Rose is not reachable/);
  assertPanelUnlocked(ui);
  assert.equal(ui.el("add-peer-input").value, "ROSE:friend");

  ui.el("party-toggle-btn").click();
  assert.match(ui.text("party-toggle-message"), /Rose is not reachable/);
  assert.equal(ui.el("party-toggle-btn").disabled, false);

  ui.reconnect();
  ui.socket.open();
  assert.deepEqual(ui.socket.types(), ["party-get-state"]);
});

test("Rose's party state settles a request whose answer was lost", async () => {
  const ui = await loadPlugin();
  ui.state(false);
  ui.openPanel();

  ui.el("party-toggle-btn").click();
  assert.equal(ui.el("party-toggle-btn").disabled, true);
  ui.state(true); // party mode is on: the enable request is done
  assert.equal(ui.el("party-toggle-btn").disabled, false);
  assert.equal(ui.text("party-toggle-btn"), "Disable Party Mode");

  ui.el("add-peer-input").value = "ROSE:friend";
  ui.el("add-peer-btn").click();
  ui.state(true, { connection: "reconnecting" }); // still adding: stays locked
  assert.equal(ui.dialog().hasAttribute("close-button"), false);
  assert.equal(ui.el("party-toggle-btn").disabled, true);
  ui.state(false); // party mode went off: no friend is being added any more
  assert.ok(ui.dialog().hasAttribute("close-button"));
  assert.equal(ui.el("party-toggle-btn").disabled, false);
});
