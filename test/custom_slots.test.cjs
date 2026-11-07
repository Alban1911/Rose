// Execute the real plugin through its bridge/events with a small, queued DOM.
// CUSTOM_SLOTS_PLUGIN points at the previous implementation for regression checks.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const plugin = process.env.CUSTOM_SLOTS_PLUGIN || path.join(__dirname, '../Pengu Loader/plugins/ROSE-CustomSlots/index.js');

async function setup(options = {}) {
  const observers = new Set(), intervals = new Map(), subscriptions = new Map(), ready = [], sent = [];
  let now = 0, nextTimer = 0, scans = 0;
  const record = (entry) => {
    for (const observer of observers) if (observer.active) observer.pending.push(entry);
  };
  class Element {
    constructor(tag) {
      this.tagName = tag.toUpperCase(); this.nodeType = 1; this.attrs = new Map();
      this.children = []; this.parentNode = null; this.dataset = {}; this.listeners = {};
      this.hidden = false; this.className = ''; this.textContent = '';
      const values = {}, priorities = {};
      this.style = new Proxy({
        getPropertyValue: (key) => values[key] || '',
        getPropertyPriority: (key) => priorities[key] || '',
        setProperty: (key, value, priority = '') => { values[key] = value; priorities[key] = priority; record({type: 'attributes', target: this}); },
        removeProperty: (key) => { delete values[key]; delete priorities[key]; record({type: 'attributes', target: this}); },
      }, {
        get: (obj, key) => key in obj ? obj[key] : values[key] || '',
        set: (obj, key, value) => { values[key] = value; record({type: 'attributes', target: this}); return true; },
      });
      this.classList = {
        contains: (name) => this.className.split(/\s+/).includes(name),
        add: (name) => { if (!this.classList.contains(name)) this.className += ` ${name}`; },
        toggle: (name, enabled) => {
          this.className = this.className.split(/\s+/).filter((item) => item && item !== name).join(' ');
          if (enabled) this.classList.add(name);
        },
      };
    }
    get id() { return this.attrs.get('id'); }
    set id(value) { this.attrs.set('id', value); }
    get isConnected() { return this === document.documentElement || Boolean(this.parentNode?.isConnected); }
    setAttribute(key, value) { this.attrs.set(key, String(value)); record({type: 'attributes', target: this}); }
    getAttribute(key) { return this.attrs.get(key) ?? null; }
    append(...nodes) {
      for (const node of nodes) { node.parentNode = this; this.children.push(node); }
      record({type: 'childList', target: this, addedNodes: nodes});
    }
    appendChild(node) { this.append(node); return node; }
    replaceChildren(...nodes) { for (const old of this.children) old.parentNode = null; this.children = []; this.append(...nodes); }
    matches(selector) {
      return selector.split(',').some((part) => {
        part = part.trim();
        if (part === "[style*='background']") return Boolean(this.style.backgroundImage);
        if (part === 'img[src]') return this.tagName === 'IMG' && this.attrs.has('src');
        if (part.startsWith('#')) return this.id === part.slice(1);
        if (part.startsWith('.')) return this.classList.contains(part.slice(1));
        return this.tagName === part.toUpperCase();
      });
    }
    querySelectorAll(selector) { return this.children.flatMap((child) => [...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)]); }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    closest(selector) { return this.matches(selector) ? this : this.parentNode?.closest(selector) || null; }
    getBoundingClientRect() { return this.rect || {left: 100, top: 200, width: 400, height: 80}; }
    addEventListener(type, callback) { (this.listeners[type] ||= []).push(callback); }
    click() { for (const fn of this.listeners.click || []) fn({preventDefault() {}, stopPropagation() {}}); }
  }
  const document = {
    readyState: 'complete', createElement: (tag) => new Element(tag),
    getElementById: (id) => document.documentElement.querySelector(`#${id}`),
    querySelector: (selector) => document.documentElement.querySelector(selector),
    querySelectorAll: (selector) => { scans++; return document.documentElement.querySelectorAll(selector); },
  };
  document.documentElement = new Element('html'); document.head = new Element('head'); document.body = new Element('body');
  document.documentElement.append(document.head, document.body);
  const carousel = new Element('div'); carousel.className = 'skin-selection-carousel'; document.body.append(carousel);
  const events = {};
  const bridge = {
    subscribe: (type, callback) => subscriptions.set(type, callback),
    send: (message) => sent.push(message), onReady: (callback) => { ready.push(callback); callback(); },
  };
  const window = {__roseBridge: bridge, __roseSkinState: {championId: 1, skinId: 1000},
    addEventListener: (type, callback) => { events[type] = callback; }};
  const state = {phase: options.phase || 'ChampSelect', locked: options.locked ?? true, aliasFailures: 0, aliasCalls: 0};
  const fetch = async (url) => {
    if (options.fetch) { const response = options.fetch(url); if (response) return response; }
    if (url.includes('gameflow-phase')) return {ok: true, json: async () => state.phase};
    if (url.includes('champ-select')) return {ok: true, json: async () => ({localPlayerCellId: 0, actions: [[{actorCellId: 0, type: 'pick', completed: state.locked}]]})};
    state.aliasCalls++;
    if (state.aliasFailures-- > 0) throw Error('game data unavailable');
    return {ok: true, json: async () => ({alias: 'Annie'})};
  };
  class Observer {
    constructor(callback) { this.callback = callback; this.pending = []; observers.add(this); }
    observe() { this.active = true; }
    disconnect() { this.active = false; this.pending = []; }
  }
  const context = {console, window, document, fetch, Node: {ELEMENT_NODE: 1}, MutationObserver: Observer,
    Date: {now: () => now}, setTimeout: () => {},
    setInterval: (callback) => { const id = ++nextTimer; intervals.set(id, callback); return id; },
    clearInterval: (id) => intervals.delete(id)};
  vm.runInNewContext(fs.readFileSync(plugin, 'utf8'), context, {filename: plugin});
  async function settle() {
    for (let i = 0; i < 20; i++) {
      await Promise.resolve();
      for (const observer of observers) if (observer.active && observer.pending.length) {
        const pending = observer.pending.splice(0); observer.callback(pending);
      }
    }
    assert.ok([...observers].every((o) => !o.pending.length), 'observer feedback loop');
  }
  await settle();
  return {document, carousel, bridge, state, sent, intervals, observers, settle, Element,
    emit: async (type, message) => { subscriptions.get(type)(message); await settle(); },
    skin: async (skinId) => { events['lu-skin-monitor-state']({detail: {championId: 1, skinId}}); await settle(); },
    reconnect: async () => { ready.forEach((callback) => callback()); await settle(); },
    tick: async (milliseconds = 500) => { now += milliseconds; [...intervals.values()].forEach((callback) => callback()); await settle(); },
    scans: () => scans, strip: () => document.getElementById('rose-custom-slots'),
  };
}

const mod = (name = 'A', targets = [1000, 1001]) => ({relativePath: `skin/1000/${name}`, modName: name, displayName: `Alias ${name}`, thumbnailUrl: `http://127.0.0.1:1234/${name}.png`, targetSkinIds: targets});
const active = (entry) => ({...entry, championId: 1, skinId: 1000, active: true});
async function select(h, entries = [mod()], selected = entries[0]) {
  await h.emit('skin-mods-response', {championId: 1, mods: entries, customModState: active(selected)});
}
function image(h, skinId = 1000) {
  const node = new h.Element('img'); node.setAttribute('src', `/lol-game-data/assets/v1/champion-tiles/1/${skinId}.jpg`); h.document.body.append(node); return node;
}

test('switch A to B, restore stock art, and restore the previous multi-target tile', async () => {
  const h = await setup(), first = image(h), second = image(h, 1001), original = first.getAttribute('src');
  const a = mod(), b = mod('B');
  await select(h, [a, b]); assert.equal(first.getAttribute('src'), a.thumbnailUrl);
  await h.emit('custom-mod-state', active(b)); assert.equal(first.getAttribute('src'), b.thumbnailUrl);
  await h.skin(1001); assert.equal(first.getAttribute('src'), original); assert.equal(second.getAttribute('src'), b.thumbnailUrl);
  await h.emit('custom-mod-state', {active: false}); assert.match(second.getAttribute('src'), /1001.jpg$/);
});

test('video src and source children are hidden without changing media URLs; layered art restores', async () => {
  const h = await setup(), direct = new h.Element('video'), nested = new h.Element('video'), source = new h.Element('source'), bg = new h.Element('div');
  const media = '/Characters/Annie/Skins/Base/AnimatedSplash/video.webm';
  direct.setAttribute('src', media); source.setAttribute('src', media); nested.append(source);
  direct.style.setProperty('visibility', 'visible', 'important');
  const background = 'linear-gradient(red, blue), url("/lol-game-data/assets/v1/champion-splashes/1/1000.jpg"), url("overlay.png")';
  bg.style.backgroundImage = background; h.document.body.append(direct, nested, bg);
  await select(h); assert.equal(direct.style.getPropertyValue('visibility'), 'hidden'); assert.equal(nested.style.getPropertyValue('visibility'), 'hidden');
  assert.equal(source.getAttribute('src'), media); assert.equal(direct.getAttribute('src'), media);
  assert.ok(bg.style.backgroundImage.includes('linear-gradient(red, blue)')); assert.ok(bg.style.backgroundImage.includes('overlay.png'));
  source.setAttribute('src', 'unrelated.webm'); await h.settle(); assert.equal(nested.style.getPropertyValue('visibility'), '');
  await h.emit('custom-mod-state', {active: false}); assert.equal(bg.style.backgroundImage, background);
  assert.equal(direct.style.getPropertyValue('visibility'), 'visible'); assert.equal(direct.style.getPropertyPriority('visibility'), 'important');
});

test('reconnect to an unlocked session restores previews and stops timer/observer, relock resyncs selection', async () => {
  const h = await setup(), img = image(h), original = img.getAttribute('src'); await select(h);
  h.state.locked = false; await h.reconnect();
  assert.equal(h.strip().hidden, true); assert.equal(img.getAttribute('src'), original); assert.equal(h.intervals.size, 0);
  assert.ok([...h.observers].every((o) => !o.active));
  await h.emit('champion-locked', {locked: true}); await select(h);
  const selected = h.strip().querySelector('.selected'); assert.ok(selected); selected.click();
  assert.equal(h.sent.at(-1).modId, null); assert.equal(h.sent.at(-1).expectedModId, mod().relativePath);
});

test('same-ID response refreshes visible alias, thumbnail, and selected preview', async () => {
  const h = await setup(), img = image(h); await select(h);
  const refreshed = {...mod(), displayName: 'Renamed', thumbnailUrl: 'http://127.0.0.1:1234/new.png'};
  await select(h, [refreshed]);
  const slot = h.strip().querySelector('.selected'); assert.equal(slot.title, 'Renamed');
  assert.ok(slot.style.backgroundImage.includes('new.png')); assert.equal(img.getAttribute('src'), refreshed.thumbnailUrl);
});

test('live unlock clears UI, then relock recovers backend selection rather than selecting it again', async () => {
  const h = await setup(), img = image(h), original = img.getAttribute('src'); await select(h);
  await h.emit('champion-locked', {locked: false});
  assert.equal(h.strip().hidden, true); assert.equal(img.getAttribute('src'), original); assert.equal(h.intervals.size, 0);
  await h.emit('champion-locked', {locked: true});
  assert.equal(h.sent.at(-1).type, 'request-skin-mods');
  await select(h); h.strip().querySelector('.selected').click();
  assert.equal(h.sent.at(-1).modId, null);
});

test('active state before the mods response keeps HistoricMode name visible', async () => {
  const h = await setup(); await h.emit('custom-mod-state', active(mod()));
  assert.equal(h.strip().hidden, true);
  assert.equal(h.document.documentElement.classList.contains('rose-custom-slot-active'), false);
});

test('popup suppression requires a visible selected slot and phase exit restores all art', async () => {
  const h = await setup(), img = image(h); const original = img.getAttribute('src'); await select(h);
  const suppressed = () => h.document.documentElement.classList.contains('rose-custom-slot-active');
  assert.equal(suppressed(), true); h.carousel.rect = {width: 0}; await h.tick(); assert.equal(suppressed(), false);
  h.carousel.rect = {left: 0, top: 100, width: 400, height: 80}; await h.tick(); assert.equal(suppressed(), true);
  await h.emit('phase-change', {phase: 'Lobby'}); const scans = h.scans(); await h.tick(5000);
  assert.equal(suppressed(), false); assert.equal(img.getAttribute('src'), original); assert.equal(h.scans(), scans); assert.equal(h.intervals.size, 0);
});

test('failed alias lookup retries, and late-added art uses observer without document rescans', async () => {
  const h = await setup(); h.state.aliasFailures = 1; await select(h); assert.equal(h.state.aliasCalls, 1);
  await h.tick(2000); assert.equal(h.state.aliasCalls, 2);
  const scans = h.scans(), img = image(h); await h.settle(); assert.equal(img.getAttribute('src'), mod().thumbnailUrl);
  await h.tick(); assert.equal(h.scans(), scans);
});

test('a live phase/lock update wins over a late client snapshot', async () => {
  let resolvePhase;
  const h = await setup({fetch: (url) => url.includes('gameflow-phase') ? new Promise((resolve) => { resolvePhase = resolve; }) : null});
  await h.emit('phase-change', {phase: 'ChampSelect'}); await h.emit('champion-locked', {locked: true}); await select(h);
  resolvePhase({ok: true, json: async () => 'Lobby'}); await h.settle();
  assert.equal(h.strip().hidden, false); assert.equal(h.intervals.size, 1);
});

test('mid-session initialization synchronizes selection and normalizes deselection IDs', async () => {
  const h = await setup(); const entry = {...mod(), relativePath: 'skin\\1000\\A'}; await select(h, [entry]);
  assert.ok(h.sent.some((message) => message.type === 'request-skin-mods'));
  h.strip().querySelector('.selected').click(); assert.equal(h.sent.at(-1).expectedModId, 'skin/1000/A');
});
