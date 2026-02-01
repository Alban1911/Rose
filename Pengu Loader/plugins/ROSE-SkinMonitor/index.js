/**
 * @name Rose-SkinMonitor
 * @author Rose Team
 * @description Skin monitor for Pengu Loader
 * @link https://github.com/Alban1911/Rose-SkinMonitor
 */

console.log("[SkinMonitor] Plugin loaded");

const LOG_PREFIX = "[SkinMonitor]";
const STATE_EVENT = "lu-skin-monitor-state";
const SKIN_SELECTORS = [
  ".skin-name-text", // Classic Champ Select
  ".skin-name", // Swiftplay lobby
];
const POLL_INTERVAL_MS = 250;
const RETRY_BASE_MS = 1000;
const RETRY_MAX_MS = 30000;
let BRIDGE_PORT = 50000; // Default, will be updated from /bridge-port endpoint
let BRIDGE_URL = `ws://127.0.0.1:${BRIDGE_PORT}`;
const BRIDGE_PORT_STORAGE_KEY = "rose_bridge_port";
const DISCOVERY_START_PORT = 50000;
const DISCOVERY_END_PORT = 50010;

async function loadBridgePort() {
  try {
    // First, check localStorage for cached port
    const cachedPort = localStorage.getItem(BRIDGE_PORT_STORAGE_KEY);
    if (cachedPort) {
      const port = parseInt(cachedPort, 10);
      if (!isNaN(port) && port > 0) {
        // Verify cached port is still valid with shorter timeout
        try {
          const response = await fetch(`http://127.0.0.1:${port}/bridge-port`, {
            signal: AbortSignal.timeout(50)
          });
          if (response.ok) {
            const portText = await response.text();
            const fetchedPort = parseInt(portText.trim(), 10);
            if (!isNaN(fetchedPort) && fetchedPort > 0) {
              BRIDGE_PORT = fetchedPort;
              BRIDGE_URL = `ws://127.0.0.1:${BRIDGE_PORT}`;
              console.log(`${LOG_PREFIX} Loaded bridge port from cache: ${BRIDGE_PORT}`);
              return true;
            }
          }
        } catch (e) {
          // Cached port invalid, continue to discovery
          localStorage.removeItem(BRIDGE_PORT_STORAGE_KEY);
        }
      }
    }

    // OPTIMIZATION: Try default port 50000 FIRST before scanning all ports
    try {
      const response = await fetch(`http://127.0.0.1:50000/bridge-port`, {
        signal: AbortSignal.timeout(50)
      });
      if (response.ok) {
        const portText = await response.text();
        const fetchedPort = parseInt(portText.trim(), 10);
        if (!isNaN(fetchedPort) && fetchedPort > 0) {
          BRIDGE_PORT = fetchedPort;
          BRIDGE_URL = `ws://127.0.0.1:${BRIDGE_PORT}`;
          localStorage.setItem(BRIDGE_PORT_STORAGE_KEY, String(BRIDGE_PORT));
          console.log(`${LOG_PREFIX} Loaded bridge port: ${BRIDGE_PORT}`);
          return true;
        }
      }
    } catch (e) {
      // Port 50000 not ready, continue to discovery
    }

    // OPTIMIZATION: Try fallback port 50001 SECOND
    try {
      const response = await fetch(`http://127.0.0.1:50001/bridge-port`, {
        signal: AbortSignal.timeout(50)
      });
      if (response.ok) {
        const portText = await response.text();
        const fetchedPort = parseInt(portText.trim(), 10);
        if (!isNaN(fetchedPort) && fetchedPort > 0) {
          BRIDGE_PORT = fetchedPort;
          BRIDGE_URL = `ws://127.0.0.1:${BRIDGE_PORT}`;
          localStorage.setItem(BRIDGE_PORT_STORAGE_KEY, String(BRIDGE_PORT));
          console.log(`${LOG_PREFIX} Loaded bridge port: ${BRIDGE_PORT}`);
          return true;
        }
      }
    } catch (e) {
      // Port 50001 not ready, continue to discovery
    }

    // OPTIMIZATION: Parallel port discovery instead of sequential
    // Try all ports at once, return as soon as one succeeds
    const portPromises = [];
    for (let port = DISCOVERY_START_PORT; port <= DISCOVERY_END_PORT; port++) {
      portPromises.push(
        fetch(`http://127.0.0.1:${port}/bridge-port`, {
          signal: AbortSignal.timeout(100)
        })
          .then(response => {
            if (response.ok) {
              return response.text().then(portText => {
                const fetchedPort = parseInt(portText.trim(), 10);
                if (!isNaN(fetchedPort) && fetchedPort > 0) {
                  return { port: fetchedPort, sourcePort: port };
                }
                return null;
              });
            }
            return null;
          })
          .catch(() => null)
      );
    }

    // Wait for first successful response
    const results = await Promise.allSettled(portPromises);
    for (const result of results) {
      if (result.status === 'fulfilled' && result.value) {
        BRIDGE_PORT = result.value.port;
        BRIDGE_URL = `ws://127.0.0.1:${BRIDGE_PORT}`;
        localStorage.setItem(BRIDGE_PORT_STORAGE_KEY, String(BRIDGE_PORT));
        console.log(`${LOG_PREFIX} Loaded bridge port: ${BRIDGE_PORT}`);
        return true;
      }
    }

    // Fallback: try old /port endpoint (parallel as well)
    const legacyPromises = [];
    for (let port = DISCOVERY_START_PORT; port <= DISCOVERY_END_PORT; port++) {
      legacyPromises.push(
        fetch(`http://127.0.0.1:${port}/port`, {
          signal: AbortSignal.timeout(100)
        })
          .then(response => {
            if (response.ok) {
              return response.text().then(portText => {
                const fetchedPort = parseInt(portText.trim(), 10);
                if (!isNaN(fetchedPort) && fetchedPort > 0) {
                  return { port: fetchedPort, sourcePort: port };
                }
                return null;
              });
            }
            return null;
          })
          .catch(() => null)
      );
    }

    const legacyResults = await Promise.allSettled(legacyPromises);
    for (const result of legacyResults) {
      if (result.status === 'fulfilled' && result.value) {
        BRIDGE_PORT = result.value.port;
        BRIDGE_URL = `ws://127.0.0.1:${BRIDGE_PORT}`;
        localStorage.setItem(BRIDGE_PORT_STORAGE_KEY, String(BRIDGE_PORT));
        console.log(`${LOG_PREFIX} Loaded bridge port (legacy): ${BRIDGE_PORT}`);
        return true;
      }
    }

    console.warn(`${LOG_PREFIX} Failed to load bridge port, using default (50000)`);
    return false;
  } catch (e) {
    console.warn(`${LOG_PREFIX} Error loading bridge port:`, e);
    return false;
  }
}

let lastLoggedSkin = null;
let pollTimer = null;
let observer = null;
let bridgeSocket = null;
let bridgeReady = false;
let bridgeQueue = [];
let bridgeErrorLogged = false;
let bridgeSetupWarned = false;
let retryTimer = null;
let stopped = false;
let retryDelay = RETRY_BASE_MS;

// --- Bridge subscription infrastructure ---
const _subscribers = new Map(); // type -> Set<callback>
const _readyCallbacks = new Set();

function subscribe(type, cb) {
  if (!_subscribers.has(type)) _subscribers.set(type, new Set());
  _subscribers.get(type).add(cb);
}

function unsubscribe(type, cb) {
  const subs = _subscribers.get(type);
  if (subs) subs.delete(cb);
}

function onReady(cb) {
  _readyCallbacks.add(cb);
  if (bridgeReady) cb();
}

function _notifySubscribers(data) {
  if (!data || !data.type) return;
  const subs = _subscribers.get(data.type);
  if (!subs) return;
  for (const cb of subs) {
    try { cb(data); } catch (e) {
      console.warn(`${LOG_PREFIX} Subscriber error for "${data.type}":`, e);
    }
  }
}

function _notifyReady() {
  for (const cb of _readyCallbacks) {
    try { cb(); } catch (e) {
      console.warn(`${LOG_PREFIX} onReady callback error:`, e);
    }
  }
}

function sanitizeSkinName(name) {
  // Keep the raw UI name intact.
  // Any matching/normalization (including chroma suffix handling) should happen server-side.
  return String(name || "").trim();
}

function resyncSkinAfterConnect() {
  try {
    // On reconnect, backend may have missed the last hover (or hover happened before lock).
    // Send a best-effort snapshot immediately so injection doesn't depend on a new hover.
    const current = readCurrentSkin();
    const name = current || lastLoggedSkin || null;
    if (!name) return;

    // Match logHover() sanitization
    const cleanName = sanitizeSkinName(name);
    if (!cleanName) return;

    sendBridgePayload({
      type: "skin-sync",
      skin: cleanName,
      originalName: name,
      timestamp: Date.now(),
    });
  } catch {
    // ignore
  }
}

function publishSkinState(payload) {
  // Use payload name, fallback to lastLoggedSkin if available (improves reliability if backend doesn't echo name)
  const name = payload?.skinName || lastLoggedSkin || null;

  const detail = {
    name: name,
    skinId: Number.isFinite(payload?.skinId) ? payload.skinId : null,
    championId: Number.isFinite(payload?.championId)
      ? payload.championId
      : null,
    hasChromas: Boolean(payload?.hasChromas),
    updatedAt: Date.now(),
  };
  window.__roseSkinState = detail;
  try {
    window.__roseCurrentSkin = detail.name;
    // Update lastLoggedSkin to match ensuring consistency if payload brought a new name
    if (name) lastLoggedSkin = name;
  } catch {
    // ignore
  }
  window.dispatchEvent(new CustomEvent(STATE_EVENT, { detail }));
}

function logHover(skinName) {
  // Sanitize skin name (currently: keep raw text, only trim).
  const cleanName = sanitizeSkinName(skinName);

  if (cleanName !== skinName) {
    console.log(`${LOG_PREFIX} Sanitized skin name: '${skinName}' -> '${cleanName}'`);
  }

  console.log(`${LOG_PREFIX} Hovered skin: ${cleanName}`);
  sendBridgePayload({ skin: cleanName, originalName: skinName, timestamp: Date.now() });
}

function sendBridgePayload(obj) {
  try {
    const payload = JSON.stringify(obj);
    sendToBridge(payload);
  } catch (error) {
    console.warn(`${LOG_PREFIX} Failed to serialize bridge payload`, error);
  }
}

// window.__roseBridge is exposed in start() after port discovery completes,
// so that consumer plugins' waitForBridge() won't resolve until the port is known.
if (typeof window !== "undefined") {
  window.__roseBridgeEmit = sendBridgePayload; // backward compat (available early)
}

function sendToBridge(payload) {
  if (
    !bridgeSocket ||
    bridgeSocket.readyState === WebSocket.CLOSING ||
    bridgeSocket.readyState === WebSocket.CLOSED
  ) {
    bridgeQueue.push(payload);
    setupBridgeSocket();
    return;
  }

  if (bridgeSocket.readyState === WebSocket.CONNECTING) {
    bridgeQueue.push(payload);
    return;
  }

  try {
    bridgeSocket.send(payload);
  } catch (error) {
    console.warn(`${LOG_PREFIX} Bridge send failed`, error);
    bridgeQueue.push(payload);
    resetBridgeSocket();
  }
}

function setupBridgeSocket() {
  if (stopped) {
    return;
  }

  if (
    bridgeSocket &&
    (bridgeSocket.readyState === WebSocket.OPEN ||
      bridgeSocket.readyState === WebSocket.CONNECTING)
  ) {
    return;
  }

  try {
    bridgeSocket = new WebSocket(BRIDGE_URL);
  } catch (error) {
    if (!bridgeSetupWarned) {
      console.warn(`${LOG_PREFIX} Bridge socket setup failed`, error);
      bridgeSetupWarned = true;
    }
    scheduleBridgeRetry();
    return;
  }

  bridgeSocket.addEventListener("open", () => {
    bridgeReady = true;
    retryDelay = RETRY_BASE_MS;
    if (retryTimer) {
      clearTimeout(retryTimer);
      retryTimer = null;
    }
    flushBridgeQueue();
    resyncSkinAfterConnect();
    bridgeErrorLogged = false;
    bridgeSetupWarned = false;
    window.__roseBridgeEmit = sendBridgePayload;
    _notifyReady();
  });

  bridgeSocket.addEventListener("message", (event) => {
    let data = null;
    try {
      data = JSON.parse(event.data);
    } catch (error) {
      console.log(`${LOG_PREFIX} Bridge message: ${event.data}`);
      return;
    }

    // Notify all bridge subscribers
    _notifySubscribers(data);

    if (data && data.type === "skin-state") {
      publishSkinState(data);
      return;
    }

    if (data && data.type === "skin-mods-response") {
      window.dispatchEvent(
        new CustomEvent("rose-custom-wheel-skin-mods", { detail: data })
      );
      return;
    }

    if (data && data.type === "maps-response") {
      window.dispatchEvent(
        new CustomEvent("rose-custom-wheel-maps", { detail: data })
      );
      return;
    }

    if (data && data.type === "fonts-response") {
      window.dispatchEvent(
        new CustomEvent("rose-custom-wheel-fonts", { detail: data })
      );
      return;
    }

    if (data && data.type === "announcers-response") {
      window.dispatchEvent(
        new CustomEvent("rose-custom-wheel-announcers", { detail: data })
      );
      return;
    }

    if (data && data.type === "category-mods-response") {
      window.dispatchEvent(
        new CustomEvent("rose-custom-wheel-category-mods", { detail: data })
      );
      return;
    }

    if (data && data.type === "others-response") {
      window.dispatchEvent(
        new CustomEvent("rose-custom-wheel-others", { detail: data })
      );
      return;
    }

    // Reset skin state when entering Lobby phase (so same skin in next game triggers detection)
    if (data && data.type === "champion-locked") {
      window.dispatchEvent(
        new CustomEvent("rose-custom-wheel-champion-locked", { detail: data })
      );
      return;
    }

    if (data && data.type === "phase-change" && data.phase === "Lobby") {
      lastLoggedSkin = null;
      console.log(`${LOG_PREFIX} Reset skin state for new game (Lobby phase)`);
      window.dispatchEvent(new CustomEvent("rose-custom-wheel-reset"));
      return;
    }

    console.log(`${LOG_PREFIX} Bridge message: ${event.data}`);
  });

  bridgeSocket.addEventListener("close", () => {
    bridgeReady = false;
    scheduleBridgeRetry();
  });

  bridgeSocket.addEventListener("error", (error) => {
    if (!bridgeErrorLogged) {
      console.warn(`${LOG_PREFIX} Bridge socket error`, error);
      bridgeErrorLogged = true;
    }
    bridgeReady = false;
    scheduleBridgeRetry();
  });
}

function flushBridgeQueue() {
  if (!bridgeSocket || bridgeSocket.readyState !== WebSocket.OPEN) {
    return;
  }

  while (bridgeQueue.length) {
    const payload = bridgeQueue.shift();
    try {
      bridgeSocket.send(payload);
    } catch (error) {
      console.warn(`${LOG_PREFIX} Bridge flush failed`, error);
      bridgeQueue.unshift(payload);
      resetBridgeSocket();
      break;
    }
  }
}

function scheduleBridgeRetry() {
  if (bridgeReady || stopped) {
    return;
  }

  if (retryTimer) {
    return;
  }

  retryTimer = setTimeout(() => {
    retryTimer = null;
    setupBridgeSocket();
  }, retryDelay);
  retryDelay = Math.min(retryDelay * 2, RETRY_MAX_MS);
}

function resetBridgeSocket() {
  if (bridgeSocket) {
    try {
      bridgeSocket.close();
    } catch (error) {
      console.warn(`${LOG_PREFIX} Bridge socket close failed`, error);
    }
  }

  bridgeSocket = null;
  bridgeReady = false;
}

function isVisible(element) {
  if (typeof element.offsetParent === "undefined") {
    return true;
  }
  return element.offsetParent !== null;
}

function readCurrentSkin() {
  for (const selector of SKIN_SELECTORS) {
    const nodes = document.querySelectorAll(selector);
    if (!nodes.length) {
      continue;
    }

    let candidate = null;

    nodes.forEach((node) => {
      const name = node.textContent.trim();
      if (!name) {
        return;
      }

      if (isVisible(node)) {
        candidate = name;
      } else if (!candidate) {
        candidate = name;
      }
    });

    if (candidate) {
      return candidate;
    }
  }

  return null;
}

function reportSkinIfChanged() {
  const name = readCurrentSkin();
  if (!name || name === lastLoggedSkin) {
    return;
  }

  lastLoggedSkin = name;
  logHover(name);
}

function attachObservers() {
  if (observer) {
    observer.disconnect();
  }

  observer = new MutationObserver(reportSkinIfChanged);
  observer.observe(document.body, { childList: true, subtree: true });

  document.querySelectorAll("*").forEach((node) => {
    if (!node.shadowRoot || !(node.shadowRoot instanceof Node)) {
      return;
    }

    try {
      observer.observe(node.shadowRoot, { childList: true, subtree: true });
    } catch (error) {
      console.warn(`${LOG_PREFIX} Cannot observe shadowRoot`, error);
    }
  });

  if (!pollTimer) {
    pollTimer = setInterval(reportSkinIfChanged, POLL_INTERVAL_MS);
  }
}

function installFindMatchObserver() {
  try {
    const po = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (entry.name && entry.name.includes("sfx-lobby-button-find-match-hover")) {
          console.log(`${LOG_PREFIX} Find-Match hover detected via PerformanceObserver`);
          sendBridgePayload({ type: "find-match-hover", timestamp: Date.now() });
        }
      }
    });
    po.observe({ type: "resource", buffered: false });
    console.log(`${LOG_PREFIX} Find-Match observer installed`);
  } catch (e) {
    console.warn(`${LOG_PREFIX} Failed to install Find-Match observer`, e);
  }
}

async function start() {
  if (!document.body) {
    console.log(`${LOG_PREFIX} Waiting for document.body...`);
    setTimeout(start, 250);
    return;
  }

  stopped = false;
  retryDelay = RETRY_BASE_MS;

  // Load bridge port before initializing socket
  await loadBridgePort();

  // Expose the shared bridge API now that the port is known.
  // Consumer plugins poll for this object via waitForBridge().
  if (typeof window !== "undefined") {
    window.__roseBridge = Object.freeze({
      send: sendBridgePayload,
      subscribe,
      unsubscribe,
      onReady,
      get port() { return BRIDGE_PORT; },
      get ready() { return bridgeReady; },
    });
  }

  installFindMatchObserver();
  setupBridgeSocket();
  attachObservers();
  reportSkinIfChanged();
}

function stop() {
  stopped = true;

  if (retryTimer) {
    clearTimeout(retryTimer);
    retryTimer = null;
  }

  if (observer) {
    observer.disconnect();
    observer = null;
  }

  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }

  if (bridgeSocket) {
    bridgeSocket.close();
    bridgeSocket = null;
  }
}

function whenReady(callback) {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", callback, { once: true });
    return;
  }

  callback();
}

whenReady(start);
window.addEventListener("beforeunload", stop);
