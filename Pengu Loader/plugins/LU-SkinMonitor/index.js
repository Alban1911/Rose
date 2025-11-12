console.log("[SkinMonitor] Plugin loaded");

const LOG_PREFIX = "[SkinMonitor]";
const BRIDGE_URL = "ws://localhost:3000";
const SKIN_REQUEST_REGEX = /\/lol-store\/v1\/skins\/(\d+)/i;

let bridgeSocket = null;
let bridgeReady = false;
let bridgeQueue = [];
let interceptorsInstalled = false;
let lastReportedSkinId = null;

function logSkinSelection(skinId) {
    console.log(`${LOG_PREFIX} Detected skin ID: ${skinId}`);
    notifyBridge({ skinId, timestamp: Date.now() });
}

function notifyBridge(payload) {
    try {
        const message = JSON.stringify(payload);
        sendToBridge(message);
    } catch (error) {
        console.warn(`${LOG_PREFIX} Failed to encode payload`, error);
    }
}

function sendToBridge(message) {
    if (!bridgeSocket || bridgeSocket.readyState === WebSocket.CLOSING || bridgeSocket.readyState === WebSocket.CLOSED) {
        bridgeQueue.push(message);
        setupBridgeSocket();
        return;
    }

    if (bridgeSocket.readyState === WebSocket.CONNECTING) {
        bridgeQueue.push(message);
        return;
    }

    try {
        bridgeSocket.send(message);
    } catch (error) {
        console.warn(`${LOG_PREFIX} Bridge send failed`, error);
        bridgeQueue.push(message);
        resetBridgeSocket();
    }
}

function setupBridgeSocket() {
    if (bridgeSocket && (bridgeSocket.readyState === WebSocket.OPEN || bridgeSocket.readyState === WebSocket.CONNECTING)) {
        return;
    }

    try {
        bridgeSocket = new WebSocket(BRIDGE_URL);
    } catch (error) {
        console.warn(`${LOG_PREFIX} Bridge socket setup failed`, error);
        scheduleBridgeRetry();
        return;
    }

    bridgeSocket.addEventListener("open", () => {
        bridgeReady = true;
        flushBridgeQueue();
    });

    bridgeSocket.addEventListener("message", (event) => {
        console.log(`${LOG_PREFIX} Bridge message: ${event.data}`);
    });

    bridgeSocket.addEventListener("close", () => {
        bridgeReady = false;
        scheduleBridgeRetry();
    });

    bridgeSocket.addEventListener("error", (error) => {
        console.warn(`${LOG_PREFIX} Bridge socket error`, error);
        bridgeReady = false;
        scheduleBridgeRetry();
    });
}

function flushBridgeQueue() {
    if (!bridgeSocket || bridgeSocket.readyState !== WebSocket.OPEN) {
        return;
    }

    while (bridgeQueue.length) {
        const message = bridgeQueue.shift();
        try {
            bridgeSocket.send(message);
        } catch (error) {
            console.warn(`${LOG_PREFIX} Bridge flush failed`, error);
            bridgeQueue.unshift(message);
            resetBridgeSocket();
            break;
        }
    }
}

function scheduleBridgeRetry() {
    if (bridgeReady) {
        return;
    }

    setTimeout(setupBridgeSocket, 1000);
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
    scheduleBridgeRetry();
}

function extractSkinIdFromUrl(url) {
    if (!url || typeof url !== "string") {
        return null;
    }

    const match = SKIN_REQUEST_REGEX.exec(url);
    if (!match) {
        return null;
    }

    const skinId = parseInt(match[1], 10);
    if (!Number.isFinite(skinId)) {
        return null;
    }

    return skinId;
}

function handlePotentialSkinRequest(url) {
    const skinId = extractSkinIdFromUrl(url);
    if (!skinId || skinId === lastReportedSkinId) {
        return;
    }

    lastReportedSkinId = skinId;
    logSkinSelection(skinId);
}

function installInterceptors() {
    if (interceptorsInstalled) {
        return;
    }
    interceptorsInstalled = true;

    if (typeof window.fetch === "function") {
        const originalFetch = window.fetch;
        window.fetch = function patchedFetch(...args) {
            try {
                const request = args[0];
                const url = typeof request === "string" ? request : request && request.url;
                handlePotentialSkinRequest(url);
            } catch (error) {
                console.warn(`${LOG_PREFIX} Failed to inspect fetch request`, error);
            }
            return originalFetch.apply(this, args);
        };
    }

    if (typeof window.XMLHttpRequest === "function") {
        const originalOpen = window.XMLHttpRequest.prototype.open;
        window.XMLHttpRequest.prototype.open = function patchedOpen(method, url, ...rest) {
            try {
                handlePotentialSkinRequest(url);
            } catch (error) {
                console.warn(`${LOG_PREFIX} Failed to inspect XHR request`, error);
            }
            return originalOpen.call(this, method, url, ...rest);
        };
    }
}

function start() {
    setupBridgeSocket();
    installInterceptors();
}

function stop() {
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
