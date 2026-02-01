/**
 * @name ROSE-HistoricMode
 * @author Rose Team
 * @description Historic mode for Pengu Loader
 * @link https://github.com/FlorentTariolle/Rose-HistoricMode
 */
(function initHistoricMode() {
  const LOG_PREFIX = "[ROSE-HistoricMode]";
  const REWARDS_SELECTOR =
    ".skin-selection-item-information.loyalty-reward-icon--rewards";
  const HISTORIC_FLAG_ASSET_PATH = "historic_flag.png";
  const SHOW_SKIN_NAME_ID = "historic-popup-layer";
  // WebSocket bridge for receiving historic state from Python
  let BRIDGE_PORT = 50000; // Default, will be updated from /bridge-port endpoint
  let BRIDGE_URL = `ws://127.0.0.1:${BRIDGE_PORT}`;
  const BRIDGE_PORT_STORAGE_KEY = "rose_bridge_port";
  const DISCOVERY_START_PORT = 50000;
  const DISCOVERY_END_PORT = 50010;
  let bridgeSocket = null;
  let bridgeReady = false;
  let bridgeQueue = [];

  /**
   * Escape HTML special characters to prevent XSS (CWE-79)
   * @param {string} str - String to escape
   * @returns {string} Escaped string safe for innerHTML
   */
  function escapeHtml(str) {
    if (typeof str !== 'string') return String(str);
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Load bridge port with file-based discovery and localStorage caching
  async function loadBridgePort() {
    try {
      // First, check localStorage for cached port
      const cachedPort = localStorage.getItem(BRIDGE_PORT_STORAGE_KEY);
      if (cachedPort) {
        const port = parseInt(cachedPort, 10);
        if (!isNaN(port) && port > 0) {
          // Verify cached port is still valid with shorter timeout
          try {
            const response = await fetch(
              `http://127.0.0.1:${port}/bridge-port`,
              {
                signal: AbortSignal.timeout(50),
              }
            );
            if (response.ok) {
              const portText = await response.text();
              const fetchedPort = parseInt(portText.trim(), 10);
              if (!isNaN(fetchedPort) && fetchedPort > 0) {
                BRIDGE_PORT = fetchedPort;
                BRIDGE_URL = `ws://127.0.0.1:${BRIDGE_PORT}`;
                console.log(
                  `${LOG_PREFIX} Loaded bridge port from cache: ${BRIDGE_PORT}`
                );
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
          signal: AbortSignal.timeout(50),
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
          signal: AbortSignal.timeout(50),
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
      const portPromises = [];
      for (
        let port = DISCOVERY_START_PORT;
        port <= DISCOVERY_END_PORT;
        port++
      ) {
        portPromises.push(
          fetch(`http://127.0.0.1:${port}/bridge-port`, {
            signal: AbortSignal.timeout(100),
          })
            .then((response) => {
              if (response.ok) {
                return response.text().then((portText) => {
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
        if (result.status === "fulfilled" && result.value) {
          BRIDGE_PORT = result.value.port;
          BRIDGE_URL = `ws://127.0.0.1:${BRIDGE_PORT}`;
          localStorage.setItem(BRIDGE_PORT_STORAGE_KEY, String(BRIDGE_PORT));
          console.log(`${LOG_PREFIX} Loaded bridge port: ${BRIDGE_PORT}`);
          return true;
        }
      }

      // Fallback: try old /port endpoint (parallel as well)
      const legacyPromises = [];
      for (
        let port = DISCOVERY_START_PORT;
        port <= DISCOVERY_END_PORT;
        port++
      ) {
        legacyPromises.push(
          fetch(`http://127.0.0.1:${port}/port`, {
            signal: AbortSignal.timeout(100),
          })
            .then((response) => {
              if (response.ok) {
                return response.text().then((portText) => {
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
        if (result.status === "fulfilled" && result.value) {
          BRIDGE_PORT = result.value.port;
          BRIDGE_URL = `ws://127.0.0.1:${BRIDGE_PORT}`;
          localStorage.setItem(BRIDGE_PORT_STORAGE_KEY, String(BRIDGE_PORT));
          console.log(
            `${LOG_PREFIX} Loaded bridge port (legacy): ${BRIDGE_PORT}`
          );
          return true;
        }
      }

      console.warn(
        `${LOG_PREFIX} Failed to load bridge port, using default (50000)`
      );
      return false;
    } catch (e) {
      console.warn(`${LOG_PREFIX} Error loading bridge port:`, e);
      return false;
    }
  }

  let historicModeActive = false;
  let customModPopupActive = false; // Track if popup was shown by custom mod
  let currentRewardsElement = null;
  let historicFlagImageUrl = null; // HTTP URL from Python
  const pendingHistoricFlagRequest = new Map(); // Track pending requests
  let isInChampSelect = false; // Track if we're in ChampSelect phase

  const CSS_RULES = `
    .skin-selection-item-information.loyalty-reward-icon--rewards.lu-historic-flag-active {
      background-repeat: no-repeat !important;
      background-size: contain !important;
      height: 32px !important;
      width: 32px !important;
      position: absolute !important;
      right: -14px !important;
      top: -14px !important;
      pointer-events: none !important;
      cursor: default !important;
      -webkit-user-select: none !important;
      list-style-type: none !important;
      content: " " !important;
    }
  `;

  function log(level, message, data = null) {
    const payload = {
      type: "chroma-log",
      source: "LU-HistoricMode",
      level: level,
      message: message,
      timestamp: Date.now(),
    };
    if (data) payload.data = data;

    if (
      bridgeReady &&
      bridgeSocket &&
      bridgeSocket.readyState === WebSocket.OPEN
    ) {
      bridgeSocket.send(JSON.stringify(payload));
    } else {
      bridgeQueue.push(JSON.stringify(payload));
    }

    // Also log to console for debugging
    const consoleMethod =
      level === "error"
        ? console.error
        : level === "warn"
          ? console.warn
          : console.log;
    consoleMethod(`${LOG_PREFIX} ${message}`, data || "");
  }

  function setupBridgeSocket() {
    if (bridgeSocket && bridgeSocket.readyState === WebSocket.OPEN) {
      return;
    }

    try {
      bridgeSocket = new WebSocket(BRIDGE_URL);

      bridgeSocket.onopen = () => {
        log("info", "WebSocket bridge connected");
        bridgeReady = true;
        flushBridgeQueue();
      };

      bridgeSocket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          handleBridgeMessage(payload);
        } catch (e) {
          log("error", "Failed to parse bridge message", { error: e.message });
        }
      };

      bridgeSocket.onerror = (error) => {
        log("warn", "WebSocket bridge error", {
          error: error.message || "Unknown error",
        });
      };

      bridgeSocket.onclose = () => {
        log("info", "WebSocket bridge closed, reconnecting...");
        bridgeReady = false;
        bridgeSocket = null;
        scheduleBridgeRetry();
      };
    } catch (e) {
      log("error", "Failed to setup WebSocket bridge", { error: e.message });
      scheduleBridgeRetry();
    }
  }

  function scheduleBridgeRetry() {
    setTimeout(() => {
      if (!bridgeReady) {
        setupBridgeSocket();
      }
    }, 3000);
  }

  function flushBridgeQueue() {
    if (
      bridgeQueue.length > 0 &&
      bridgeReady &&
      bridgeSocket &&
      bridgeSocket.readyState === WebSocket.OPEN
    ) {
      bridgeQueue.forEach((message) => {
        bridgeSocket.send(message);
      });
      bridgeQueue = [];
    }
  }

  function handleBridgeMessage(payload) {
    if (payload.type === "historic-state") {
      handleHistoricStateUpdate(payload);
    } else if (payload.type === "custom-mod-state") {
      handleCustomModStateUpdate(payload);
    } else if (payload.type === "skin-state") {
      handleSkinStateUpdate(payload);
    } else if (payload.type === "local-asset-url") {
      handleLocalAssetUrl(payload);
    } else if (payload.type === "phase-change") {
      handlePhaseChange(payload);
    }
  }

  function handlePhaseChange(data) {
    const wasInChampSelect = isInChampSelect;
    // Check if we're entering ChampSelect phase
    isInChampSelect =
      data.phase === "ChampSelect" || data.phase === "FINALIZATION";

    if (isInChampSelect && !wasInChampSelect) {
      log("debug", "Entered ChampSelect phase - enabling plugin");
      // Try to update flag when entering ChampSelect
      if (historicModeActive) {
        setTimeout(() => {
          updateHistoricFlag();
        }, 100);
      }
    } else if (!isInChampSelect && wasInChampSelect) {
      log("debug", "Left ChampSelect phase - disabling plugin");
      // Remove popup and reset flags
      customModPopupActive = false;
      removeHistoricSkinName();
      // Hide flag when leaving ChampSelect
      if (currentRewardsElement) {
        hideFlagOnElement(currentRewardsElement);
        currentRewardsElement = null;
      }
      // Reset retry counters
      if (updateHistoricFlag._retryCount) {
        updateHistoricFlag._retryCount = 0;
      }
    }
  }

  function handleLocalAssetUrl(data) {
    const assetPath = data.assetPath;
    let url = data.url;
    // Fix: Ensure we use 127.0.0.1 for asset URLs to match the bridge connection
    if (url && typeof url === 'string') {
      url = url.replace('localhost', '127.0.0.1');
    }

    if (assetPath === HISTORIC_FLAG_ASSET_PATH && url) {
      historicFlagImageUrl = url;
      pendingHistoricFlagRequest.delete(HISTORIC_FLAG_ASSET_PATH);
      log("info", "Received historic flag image URL from Python", { url: url });

      // Update the flag if it's currently active and we're in ChampSelect
      if (isInChampSelect && historicModeActive) {
        updateHistoricFlag();
      }
    }
  }

  function handleHistoricStateUpdate(data) {
    handleHistoricSkinNameUpdate(data);
    const wasActive = historicModeActive;
    historicModeActive = data.active === true;

    log("info", "Received historic state update", {
      active: historicModeActive,
      wasActive: wasActive,
      historicSkinId: data.historicSkinId,
    });

    // Always update the flag when we receive a state update (even if state didn't change)
    // This ensures the flag is shown even if the element wasn't found initially
    // Use a small delay to ensure DOM is ready
    setTimeout(() => {
      updateHistoricFlag();
    }, 100);

    // Also try again after a longer delay in case DOM updates are delayed
    if (historicModeActive) {
      setTimeout(() => {
        updateHistoricFlag();
      }, 1000);
    }
  }

  function findRewardsElement() {
    // Only try to find elements when in ChampSelect
    if (!isInChampSelect) {
      return null;
    }

    // Try to find the rewards element in the selected skin item first
    const selectedItem = document.querySelector(
      ".skin-selection-item.skin-selection-item-selected"
    );
    if (selectedItem) {
      const info = selectedItem.querySelector(
        ".skin-selection-item-information.loyalty-reward-icon--rewards"
      );
      if (info) {
        return info;
      }
    }

    // Try direct selector
    const element = document.querySelector(REWARDS_SELECTOR);
    if (element) {
      return element;
    }

    // If not found, try to find it in the skin selection carousel
    const carousel = document.querySelector(".skin-selection-carousel");
    if (carousel) {
      const items = carousel.querySelectorAll(".skin-selection-item");
      for (const item of items) {
        const info = item.querySelector(".skin-selection-item-information");
        if (info && info.classList.contains("loyalty-reward-icon--rewards")) {
          return info;
        }
      }
    }

    // Only log if we're actually in ChampSelect (to avoid spam before entering)
    removeHistoricSkinName();
    return null;
  }

  // Inject CSS styles for lol-uikit-dialog-frame
  function injectDialogFrameStyles() {
    const styleId = "rose-historic-mode-dialog-frame-styles";
    if (document.getElementById(styleId)) {
      return; // Styles already injected
    }

    const style = document.createElement("style");
    style.id = styleId;
    style.textContent = `
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.left,
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.right {
        border: none;
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.right {
        border: none;
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.top,
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.bottom {
        border: none;
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.top {
        border: none;
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.top.disabled,
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.bottom.disabled {
        border: none;
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.top.disabled > .lol-uikit-dialog-frame-sub-border::before,
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.bottom.disabled > .lol-uikit-dialog-frame-sub-border::before {
        top: -6px;
        border-image-source: url("/fe/lol-uikit/images/sub-border-secondary-horizontal-disabled.png");
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.top.disabled > .lol-uikit-dialog-frame-sub-border::after,
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.bottom.disabled > .lol-uikit-dialog-frame-sub-border::after {
        bottom: -6px;
        border-image-source: url("/fe/lol-uikit/images/sub-border-primary-horizontal-disabled.png");
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.top .lol-uikit-dialog-frame-sub-border::before,
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.bottom .lol-uikit-dialog-frame-sub-border::before,
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.top .lol-uikit-dialog-frame-sub-border::after,
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.bottom .lol-uikit-dialog-frame-sub-border::after {
        left: 12px;
        width: calc(100% - 24px);
        height: 0;
        border-width: 4px 4px 0 4px;
        border-image-width: 4px 4px 0 4px;
        border-image-slice: 4 4 0 4;
        border-image-repeat: stretch;
        border-style: solid;
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.top .lol-uikit-dialog-frame-sub-border::before,
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.bottom .lol-uikit-dialog-frame-sub-border::before {
        top: -6px;
        border-image-source: url("/fe/lol-uikit/images/sub-border-secondary-horizontal.png");
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.top .lol-uikit-dialog-frame-sub-border::after,
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.bottom .lol-uikit-dialog-frame-sub-border::after {
        bottom: -6px;
        border-image-source: url("/fe/lol-uikit/images/sub-border-primary-horizontal.png");
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.left.disabled,
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.right.disabled {
        border: none;
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.left.disabled > .lol-uikit-dialog-frame-sub-border::before,
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.right.disabled > .lol-uikit-dialog-frame-sub-border::before {
        left: -6px;
        border-image-source: url("/fe/lol-uikit/images/sub-border-secondary-vertical-disabled.png");
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.left.disabled > .lol-uikit-dialog-frame-sub-border::after,
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.right.disabled > .lol-uikit-dialog-frame-sub-border::after {
        right: -6px;
        border-image-source: url("/fe/lol-uikit/images/sub-border-primary-vertical-disabled.png");
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.left .lol-uikit-dialog-frame-sub-border::before,
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.right .lol-uikit-dialog-frame-sub-border::before,
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.left .lol-uikit-dialog-frame-sub-border::after,
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.right .lol-uikit-dialog-frame-sub-border::after {
        top: 12px;
        height: calc(100% - 24px);
        width: 0;
        border-width: 4px 4px 4px 0;
        border-image-width: 4px 4px 4px 0;
        border-image-slice: 4 4 4 0;
        border-image-repeat: stretch;
        border-style: solid;
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.left .lol-uikit-dialog-frame-sub-border::before,
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.right .lol-uikit-dialog-frame-sub-border::before {
        left: -6px;
        border-image-source: url("/fe/lol-uikit/images/sub-border-primary-vertical.png");
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.left .lol-uikit-dialog-frame-sub-border::after,
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.right .lol-uikit-dialog-frame-sub-border::after {
        right: -6px;
        border-image-source: url("/fe/lol-uikit/images/sub-border-secondary-vertical.png");
      }
      #${SHOW_SKIN_NAME_ID} lol-uikit-dialog-frame {
        z-index: 0;
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame {
        position: relative;
        background: #010a13;
        box-shadow: 0 0 0 1px rgba(1,10,19,0.48);
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame::before {
        content: '';
        position: absolute;
        width: calc(100% + 4px);
        height: calc(100% + 4px);
        top: -2px;
        left: -2px;
        box-shadow: 0 0 10px 1px rgba(0,0,0,0.5);
        pointer-events: none;
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame .lol-uikit-dialog-frame-sub-border::before,
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame .lol-uikit-dialog-frame-sub-border::after {
        content: '';
        position: absolute;
        display: flex;
        box-sizing: border-box;
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.top.disabled > .lol-uikit-dialog-frame-sub-border::before {
        border-image-source: url("/fe/lol-uikit/images/sub-border-primary-horizontal-disabled.png");
        transform: rotate(180deg);
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.top.disabled > .lol-uikit-dialog-frame-sub-border::after {
        border-image-source: url("/fe/lol-uikit/images/sub-border-secondary-horizontal-disabled.png");
        transform: rotate(180deg);
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.top .lol-uikit-dialog-frame-sub-border::before {
        border-image-source: url("/fe/lol-uikit/images/sub-border-primary-horizontal.png");
        transform: rotate(180deg);
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.top .lol-uikit-dialog-frame-sub-border::after {
        border-image-source: url("/fe/lol-uikit/images/sub-border-secondary-horizontal.png");
        transform: rotate(180deg);
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.right.disabled > .lol-uikit-dialog-frame-sub-border::before {
        border-image-source: url("/fe/lol-uikit/images/sub-border-primary-vertical-disabled.png");
        transform: rotate(180deg);
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.right.disabled > .lol-uikit-dialog-frame-sub-border::after {
        border-image-source: url("/fe/lol-uikit/images/sub-border-secondary-vertical-disabled.png");
        transform: rotate(180deg);
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.right .lol-uikit-dialog-frame-sub-border::before {
        border-image-source: url("/fe/lol-uikit/images/sub-border-secondary-vertical.png");
        transform: rotate(180deg);
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.right .lol-uikit-dialog-frame-sub-border::after {
        border-image-source: url("/fe/lol-uikit/images/sub-border-primary-vertical.png");
        transform: rotate(180deg);
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.borderless .lol-uikit-dialog-frame-sub-border {
        display: none;
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame .lol-uikit-dialog-frame-close-button {
        display: none;
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame .lol-uikit-dialog-frame-close-button lol-uikit-close-button {
        z-index: 10000000;
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame .lol-uikit-dialog-frame-uikit-close-button {
        display: none;
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.dismissable-icon .lol-uikit-dialog-frame-toast-close-button {
        display: block;
        height: 16px;
        width: 16px;
        position: absolute;
        top: 2px;
        right: 2px;
        background: url("/fe/lol-uikit/images/close.png"), rgba(0,0,0,0.7);
        cursor: pointer;
        border-radius: 50%;
        background-size: 70% 70%, 100% 100%;
        background-position: center;
        background-repeat: no-repeat;
        z-index: 10;
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.dismissable-icon .lol-uikit-dialog-frame-toast-close-button:hover {
        background: url("/fe/lol-uikit/images/close.png"), rgba(200,50,50,0.8);
        background-size: 70% 70%, 100% 100%;
        background-position: center;
        background-repeat: no-repeat;
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.dismissable-icon.dismissable-icon-background .lol-uikit-dialog-frame-toast-close-button {
        width: 24px;
        height: 24px;
        top: 8px;
        right: 8px;
        background-color: #0a1428;
        background-size: 18px 18px;
        background-position: center;
        border-radius: 2px;
        opacity: 0.8;
        transition: opacity 0.05s ease-in-out;
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.dismissable-icon.dismissable-icon-background .lol-uikit-dialog-frame-toast-close-button:hover {
        opacity: 1;
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.dismissable-close-button .lol-uikit-dialog-frame-close-button {
        display: block;
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.dismissable-close-button .lol-uikit-dialog-frame-close-button::before {
        content: '';
        position: absolute;
        width: 38px;
        height: 68px;
        top: -22px;
        right: -22px;
        background-image: url("/fe/lol-uikit/images/frame-button-close-top-down.png");
        background-size: 38px 68px;
        pointer-events: none;
      }
      #${SHOW_SKIN_NAME_ID} .lol-uikit-dialog-frame.dismissable-close-button .lol-uikit-dialog-frame-close-button lol-uikit-close-button {
        display: block;
        position: absolute;
        top: -17px;
        right: -17px;
      }
    `;
    document.head.appendChild(style);
  }

  function showSkinName(skinName) {
    const id = SHOW_SKIN_NAME_ID;
    let text = skinName;
    // If an element with the same id already exists, directly update the content and reset the timer
    let popup = document.getElementById(id);
    if (popup) {
      const pTag = popup.querySelector("p");
      if (pTag) {
        pTag.textContent = text;
      }
      resetTimer(popup);
      return;
    }

    // Inject dialog frame styles
    injectDialogFrameStyles();

    // Create container
    popup = document.createElement("div");
    popup.id = id;

    // Set styles
    Object.assign(popup.style, {
      position: "fixed",
      bottom: "calc(10% + 215px)",
      left: "50%",
      transform: "translate(-50%, 0)",
      zIndex: "0",
      background: "transparent",
      color: "#b2a580",
      padding: "0",
      margin: "0",
      fontSize: "14px",
      lineHeight: "1.4",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      maxWidth: "300px",
      width: "auto",
      boxSizing: "border-box",
    });

    // Create toast-body div
    const toastBody = document.createElement("div");
    toastBody.className = "toast-body";
    Object.assign(toastBody.style, {
      display: "flex",
      flexDirection: "column",
      justifyContent: "space-between",
      boxSizing: "border-box",
      position: "relative",
      width: "auto",
      margin: "0 auto",
    });

    // Create toast-content div
    const toastContent = document.createElement("div");
    toastContent.className = "toast-content";
    Object.assign(toastContent.style, {
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      width: "100%",
    });

    // Create lol-uikit-dialog-frame wrapper
    let dialogFrame;
    try {
      dialogFrame = document.createElement("lol-uikit-dialog-frame");
      dialogFrame.className = "lol-uikit-dialog-frame top dismissable-icon";
    } catch (e) {
      dialogFrame = document.createElement("div");
      dialogFrame.className = "lol-uikit-dialog-frame top dismissable-icon";
    }
    Object.assign(dialogFrame.style, {
      position: "relative",
      display: "inline-block",
    });

    // Create lol-uikit-content-block element
    let contentBlock;
    try {
      contentBlock = document.createElement("lol-uikit-content-block");
      contentBlock.className = "lol-ready-check-notification-party-dodge";
      contentBlock.setAttribute("type", "notification");
    } catch (e) {
      contentBlock = document.createElement("div");
      contentBlock.className =
        "lol-uikit-content-block lol-ready-check-notification-party-dodge";
      contentBlock.setAttribute("type", "notification");
    }

    // Set CSS custom properties
    contentBlock.style.setProperty(
      "--champion-preview-hover-animation-percentage",
      "0%"
    );
    contentBlock.style.setProperty("--column-height", "95px");
    contentBlock.style.setProperty(
      "--font-display",
      '"LoL Display","Times New Roman",Times,Baskerville,Georgia,serif'
    );
    contentBlock.style.setProperty(
      "--font-body",
      '"LoL Body",Arial,"Helvetica Neue",Helvetica,sans-serif'
    );
    contentBlock.style.setProperty(
      "--plug-transform1",
      "scale(1) rotate(0deg)"
    );
    contentBlock.style.setProperty(
      "--plug-transform2",
      "scale(1.075) rotate(1deg)"
    );
    contentBlock.style.setProperty(
      "--plug-filter1",
      "drop-shadow(0 0 0 rgb(66 60 40 / 0%))"
    );
    contentBlock.style.setProperty(
      "--plug-filter2",
      "drop-shadow(0 0 12px rgb(66 59 40 / 80%))"
    );
    contentBlock.style.setProperty("--plug-color1", "#423828");
    contentBlock.style.setProperty("--plug-color2", "#fcf0d7");
    contentBlock.style.setProperty(
      "--plug-box-shadow1",
      "0 0 0 rgb(66 58 40 / 0%)"
    );
    contentBlock.style.setProperty(
      "--plug-box-shadow2",
      "0 0 12px rgb(66 55 40 / 80%), inset 0 0 12px rgb(66 56 40 / 40%)"
    );
    contentBlock.style.setProperty("--plug-color-button", "#857a72");
    contentBlock.style.setProperty("--plug-color-buttonDisabled", "#72655a");
    contentBlock.style.setProperty("--plug-color-buttonHover", "#a89d8f");
    contentBlock.style.setProperty(
      "--plug-selected-item-border",
      "2px solid #7d644b"
    );
    contentBlock.style.setProperty(
      "--plug-selected-item-box-shadow",
      "0 0 10px rgb(194 129 68 / 50%)"
    );
    contentBlock.style.setProperty(
      "--plug-smoothGlow-box-shadow0",
      "0 0 8px rgb(66 55 40 / 40%), 0 0 12px rgb(66 54 40 / 20%)"
    );
    contentBlock.style.setProperty(
      "--plug-smoothGlow-box-shadow25",
      "0 0 10px rgb(66 55 40 / 50%), 0 0 16px rgb(66 57 40 / 10%), 0 0 30px rgb(66 55 40 / 20%)"
    );
    contentBlock.style.setProperty(
      "--plug-smoothGlow-box-shadow50",
      "0 0 12px rgb(66 56 40 / 60%), 0 0 20px rgb(66 54 40 / 30%), 0 0 30px rgb(66 55 40 / 10%)"
    );
    contentBlock.style.setProperty(
      "--plug-smoothGlow-box-shadow75",
      "0 0 10px rgb(66 55 40 / 50%), 0 0 16px rgb(66 56 40 / 10%), 0 0 30px rgb(66 54 40 / 20%)"
    );
    contentBlock.style.setProperty(
      "--plug-smoothGlow-box-shadow100",
      "0 0 8px rgb(66 58 40 / 40%), 0 0 12px rgb(66 56 40 / 20%)"
    );
    contentBlock.style.setProperty(
      "--plug-search-input-border",
      "1px solid #533e1c"
    );
    contentBlock.style.setProperty(
      "--plug-search-inputFocus-border-color",
      "#81602b"
    );
    contentBlock.style.setProperty(
      "--plug-search-inputFocus-box-shadow",
      "0 0 10px rgba(84, 58, 96, 0.3)"
    );
    contentBlock.style.setProperty("--plug-jsbutton-color", "#81602b");
    contentBlock.style.setProperty(
      "--plug-soft-text-glow-kda1",
      "rgb(255 155 0) 0px 0px 17px"
    );
    contentBlock.style.setProperty(
      "--plug-soft-text-glow-kda2",
      "rgb(255 143 0 / 37%) 0px 0px 76px"
    );
    contentBlock.style.setProperty("--plug-scrollable-color", "#785a28");

    // Set regular CSS properties
    Object.assign(contentBlock.style, {
      WebkitUserSelect: "none",
      position: "relative",
      background: "transparent",
      width: "auto",
      display: "inline-block",
      boxSizing: "border-box",
      paddingLeft: "25px",
      paddingRight: "25px",
    });

    // Create paragraph with skin name (preserving case)
    const pTag = document.createElement("p");
    pTag.textContent = text;

    // Create lol-uikit-dialog-frame-sub-border element
    const subBorder = document.createElement("div");
    subBorder.className = "lol-uikit-dialog-frame-sub-border";

    // Set CSS custom properties
    subBorder.style.setProperty(
      "--champion-preview-hover-animation-percentage",
      "0%"
    );
    subBorder.style.setProperty("--column-height", "95px");
    subBorder.style.setProperty(
      "--font-display",
      '"LoL Display","Times New Roman",Times,Baskerville,Georgia,serif'
    );
    subBorder.style.setProperty(
      "--font-body",
      '"LoL Body",Arial,"Helvetica Neue",Helvetica,sans-serif'
    );
    subBorder.style.setProperty("--plug-transform1", "scale(1) rotate(0deg)");
    subBorder.style.setProperty(
      "--plug-transform2",
      "scale(1.075) rotate(1deg)"
    );
    subBorder.style.setProperty(
      "--plug-filter1",
      "drop-shadow(0 0 0 rgb(66 60 40 / 0%))"
    );
    subBorder.style.setProperty(
      "--plug-filter2",
      "drop-shadow(0 0 12px rgb(66 59 40 / 80%))"
    );
    subBorder.style.setProperty("--plug-color1", "#423828");
    subBorder.style.setProperty("--plug-color2", "#fcf0d7");
    subBorder.style.setProperty(
      "--plug-box-shadow1",
      "0 0 0 rgb(66 58 40 / 0%)"
    );
    subBorder.style.setProperty(
      "--plug-box-shadow2",
      "0 0 12px rgb(66 55 40 / 80%), inset 0 0 12px rgb(66 56 40 / 40%)"
    );
    subBorder.style.setProperty("--plug-color-button", "#857a72");
    subBorder.style.setProperty("--plug-color-buttonDisabled", "#72655a");
    subBorder.style.setProperty("--plug-color-buttonHover", "#a89d8f");
    subBorder.style.setProperty(
      "--plug-selected-item-border",
      "2px solid #7d644b"
    );
    subBorder.style.setProperty(
      "--plug-selected-item-box-shadow",
      "0 0 10px rgb(194 129 68 / 50%)"
    );
    subBorder.style.setProperty(
      "--plug-smoothGlow-box-shadow0",
      "0 0 8px rgb(66 55 40 / 40%), 0 0 12px rgb(66 54 40 / 20%)"
    );
    subBorder.style.setProperty(
      "--plug-smoothGlow-box-shadow25",
      "0 0 10px rgb(66 55 40 / 50%), 0 0 16px rgb(66 57 40 / 10%), 0 0 30px rgb(66 55 40 / 20%)"
    );
    subBorder.style.setProperty(
      "--plug-smoothGlow-box-shadow50",
      "0 0 12px rgb(66 56 40 / 60%), 0 0 20px rgb(66 54 40 / 30%), 0 0 30px rgb(66 55 40 / 10%)"
    );
    subBorder.style.setProperty(
      "--plug-smoothGlow-box-shadow75",
      "0 0 10px rgb(66 55 40 / 50%), 0 0 16px rgb(66 56 40 / 10%), 0 0 30px rgb(66 54 40 / 20%)"
    );
    subBorder.style.setProperty(
      "--plug-smoothGlow-box-shadow100",
      "0 0 8px rgb(66 58 40 / 40%), 0 0 12px rgb(66 56 40 / 20%)"
    );
    subBorder.style.setProperty(
      "--plug-search-input-border",
      "1px solid #533e1c"
    );
    subBorder.style.setProperty(
      "--plug-search-inputFocus-border-color",
      "#81602b"
    );
    subBorder.style.setProperty(
      "--plug-search-inputFocus-box-shadow",
      "0 0 10px rgba(84, 58, 96, 0.3)"
    );
    subBorder.style.setProperty("--plug-jsbutton-color", "#81602b");
    subBorder.style.setProperty(
      "--plug-soft-text-glow-kda1",
      "rgb(255 155 0) 0px 0px 17px"
    );
    subBorder.style.setProperty(
      "--plug-soft-text-glow-kda2",
      "rgb(255 143 0 / 37%) 0px 0px 76px"
    );
    subBorder.style.setProperty("--plug-scrollable-color", "#785a28");

    // Set regular CSS properties (subBorder will be styled by CSS rules)
    Object.assign(subBorder.style, {
      WebkitUserSelect: "none",
    });

    // Create before pseudo-element
    const beforeElement = document.createElement("div");
    beforeElement.setAttribute("data-pseudo", "before");
    Object.assign(beforeElement.style, {
      position: "absolute",
      display: "block",
      content: '""',
    });
    subBorder.insertBefore(beforeElement, subBorder.firstChild);

    // Create after pseudo-element
    const afterElement = document.createElement("div");
    afterElement.setAttribute("data-pseudo", "after");
    Object.assign(afterElement.style, {
      position: "absolute",
      display: "block",
      content: '""',
    });
    subBorder.appendChild(afterElement);

    // Close button — lets the user dismiss the popup and cancel injection
    const closeBtn = document.createElement("div");
    closeBtn.className = "lol-uikit-dialog-frame-toast-close-button";
    closeBtn.addEventListener("click", () => {
      removeHistoricSkinName();
      dismissActivePopup();
    });

    // Build the nested structure
    contentBlock.appendChild(pTag);
    dialogFrame.appendChild(contentBlock);
    dialogFrame.appendChild(subBorder);
    dialogFrame.appendChild(closeBtn);
    toastContent.appendChild(dialogFrame);
    toastBody.appendChild(toastContent);

    popup.appendChild(toastBody);

    // Find the same container as the random skin button to match stacking context
    function findNamePanelContainer() {
      // Only try to find container when in ChampSelect
      if (!isInChampSelect) {
        return null;
      }

      // Find the carousel container to match its stacking context (same as random skin button)
      const carouselContainer = document.querySelector(".skin-selection-carousel-container");
      if (carouselContainer) {
        return carouselContainer;
      }

      // Fallback: find the carousel itself
      const carousel = document.querySelector(".skin-selection-carousel");
      if (carousel) {
        return carousel;
      }

      // Last fallback: find the main champ select container and then div.visible
      const mainContainer = document.querySelector(".champion-select-main-container");
      if (mainContainer) {
        const visibleDiv = mainContainer.querySelector("div.visible");
        if (visibleDiv) {
          return visibleDiv;
        }
      }

      return null;
    }

    // Try to append to the same container as random skin button
    const targetContainer = findNamePanelContainer();
    if (targetContainer) {
      // Ensure container has positioning context
      const containerComputedStyle = window.getComputedStyle(targetContainer);
      if (containerComputedStyle.position === 'static') {
        targetContainer.style.position = 'relative';
      }

      // Get container's position relative to viewport
      const containerRect = targetContainer.getBoundingClientRect();

      // Calculate position relative to container (convert from fixed to absolute)
      // The original position is: bottom: calc(10% + 350px), left: 50%
      const viewportHeight = window.innerHeight;
      const bottomOffset = viewportHeight * 0.1 + 265; // 10% + 265px
      const topPosition = viewportHeight - bottomOffset;

      // Update styles for absolute positioning relative to container
      popup.style.position = "absolute";
      popup.style.bottom = "auto";
      popup.style.top = `${topPosition - containerRect.top}px`;
      popup.style.left = "50%";
      popup.style.transform = "translate(-50%, 0)";

      targetContainer.appendChild(popup);
    } else {
      // Fallback: append to body if container not found
      document.body.appendChild(popup);
    }

    // Auto close timer
    resetTimer(popup);

    function resetTimer(el) {
      if (el._timer) clearTimeout(el._timer);
      el._timer = setTimeout(() => el.remove(), 125000); // Remove after 125 seconds
    }
  }

  const handleHistoricSkinNameUpdate = (payload) => {
    if (payload.historicSkinName && payload.historicSkinName !== "None") {
      showSkinName(payload.historicSkinName);
    } else {
      removeHistoricSkinName();
    }
  };

  function handleCustomModStateUpdate(data) {
    if (data.active && data.modName) {
      // Only show popup if the user is currently viewing the mod's target skin
      const currentSkinId = Number((window.__roseSkinState || {}).skinId);
      const modSkinId = data.skinId ? Number(data.skinId) : null;
      if (modSkinId && currentSkinId && modSkinId !== currentSkinId) {
        // User already navigated away — don't show popup
        customModPopupActive = false;
        removeHistoricSkinName();
        return;
      }
      customModPopupActive = true;
      showSkinName(data.modName);
    } else {
      customModPopupActive = false;
      removeHistoricSkinName();
    }
  }

  function handleSkinStateUpdate(data) {
    // When the user hovers a different skin, hide the custom mod popup
    if (customModPopupActive) {
      customModPopupActive = false;
      removeHistoricSkinName();
    }
  }
  function removeHistoricSkinName() {
    document.getElementById(SHOW_SKIN_NAME_ID)?.remove();
  }

  function dismissActivePopup() {
    // Send the right dismiss message depending on what triggered the popup
    const msgType = customModPopupActive ? "dismiss-custom-mod" : "dismiss-historic";
    customModPopupActive = false;
    historicModeActive = false;

    if (bridgeReady && bridgeSocket && bridgeSocket.readyState === WebSocket.OPEN) {
      bridgeSocket.send(JSON.stringify({ type: msgType, timestamp: Date.now() }));
    } else {
      bridgeQueue.push(JSON.stringify({ type: msgType, timestamp: Date.now() }));
    }
  }
  function requestHistoricFlagImage() {
    // Request historic flag image from Python (same way as Elementalist Lux icons)
    if (
      !historicFlagImageUrl &&
      !pendingHistoricFlagRequest.has(HISTORIC_FLAG_ASSET_PATH)
    ) {
      pendingHistoricFlagRequest.set(HISTORIC_FLAG_ASSET_PATH, true);

      const payload = {
        type: "request-local-asset",
        assetPath: HISTORIC_FLAG_ASSET_PATH,
        timestamp: Date.now(),
      };

      log("debug", "Requesting historic flag image from Python", {
        assetPath: HISTORIC_FLAG_ASSET_PATH,
      });

      if (
        bridgeReady &&
        bridgeSocket &&
        bridgeSocket.readyState === WebSocket.OPEN
      ) {
        bridgeSocket.send(JSON.stringify(payload));
      } else {
        bridgeQueue.push(JSON.stringify(payload));
      }
    }
  }

  function updateHistoricFlag() {
    // Only try to update if we're in ChampSelect
    if (!isInChampSelect) {
      return;
    }

    // Always find the element in the currently selected skin (don't use cached element)
    const element = findRewardsElement();

    if (!element) {
      // Only retry if we're still in ChampSelect
      if (!isInChampSelect) {
        return;
      }
      log("debug", "Rewards element not found, will retry");
      // Retry after a short delay (max 5 retries to avoid infinite loop)
      if (!updateHistoricFlag._retryCount) {
        updateHistoricFlag._retryCount = 0;
      }
      if (updateHistoricFlag._retryCount < 5) {
        updateHistoricFlag._retryCount++;
        setTimeout(() => {
          if (isInChampSelect) {
            // Check again before retrying
            updateHistoricFlag();
          } else {
            updateHistoricFlag._retryCount = 0; // Reset if we left ChampSelect
          }
        }, 500);
      } else {
        log("warn", "Rewards element not found after 5 retries, giving up");
        updateHistoricFlag._retryCount = 0; // Reset for next attempt
      }
      return;
    }

    // Reset retry count on success
    updateHistoricFlag._retryCount = 0;

    // If we have a previously cached element that's different from the current one, hide it first
    if (currentRewardsElement && currentRewardsElement !== element) {
      log("debug", "Selected skin changed - hiding flag on previous element");
      hideFlagOnElement(currentRewardsElement);
    }

    currentRewardsElement = element;

    // Check element visibility (no logging to reduce spam)
    const computedStyle = window.getComputedStyle(element);
    const isVisible =
      computedStyle.display !== "none" &&
      computedStyle.visibility !== "hidden" &&
      computedStyle.opacity !== "0";

    if (historicModeActive) {
      // Request image if we don't have it yet
      if (!historicFlagImageUrl) {
        requestHistoricFlagImage();
        // Wait for image URL before applying
        return;
      }

      // Force element to be visible (rewards icon is usually hidden)
      element.style.setProperty("display", "block", "important");
      element.style.setProperty("visibility", "visible", "important");
      element.style.setProperty("opacity", "1", "important");

      // Apply the image URL from Python
      element.classList.add("lu-historic-flag-active");
      element.style.setProperty(
        "background-image",
        `url("${historicFlagImageUrl}")`,
        "important"
      );
      element.style.setProperty("background-repeat", "no-repeat", "important");
      element.style.setProperty("background-size", "contain", "important");
      element.style.setProperty("height", "32px", "important");
      element.style.setProperty("width", "32px", "important");
      element.style.setProperty("position", "absolute", "important");
      element.style.setProperty("right", "-14px", "important");
      element.style.setProperty("top", "-14px", "important");
      element.style.setProperty("pointer-events", "none", "important");
      element.style.setProperty("cursor", "default", "important");
      element.style.setProperty("-webkit-user-select", "none", "important");
      element.style.setProperty("list-style-type", "none", "important");
      element.style.setProperty("content", " ", "important");

      log("info", "Historic flag shown on rewards element", {
        url: historicFlagImageUrl,
        display: element.style.display,
        visibility: element.style.visibility,
      });
    } else {
      // Historic mode is inactive - hide the flag
      hideFlagOnElement(element);
      log("info", "Historic flag hidden on rewards element");
    }
  }

  function hideFlagOnElement(element) {
    if (!element) return;

    // Only remove our flag class
    element.classList.remove("lu-historic-flag-active");

    // Check if random flag is active - if so, don't remove shared styles
    const hasRandomFlag = element.classList.contains("lu-random-flag-active");

    if (!hasRandomFlag) {
      // No other flag is active - safe to remove all styles
      element.style.removeProperty("background-image");
      element.style.removeProperty("background-repeat");
      element.style.removeProperty("background-size");
      element.style.removeProperty("height");
      element.style.removeProperty("width");
      element.style.removeProperty("position");
      element.style.removeProperty("right");
      element.style.removeProperty("top");
      element.style.removeProperty("pointer-events");
      element.style.removeProperty("cursor");
      element.style.removeProperty("-webkit-user-select");
      element.style.removeProperty("list-style-type");
      element.style.removeProperty("content");
      // Explicitly hide the element (rewards icon is usually hidden by default)
      element.style.setProperty("display", "none", "important");
      element.style.setProperty("visibility", "hidden", "important");
      element.style.setProperty("opacity", "0", "important");
    } else {
      // Random flag is active - only remove our background image, keep shared styles
      // Check if the background-image is ours (contains historic_flag.png)
      const bgImage = element.style.getPropertyValue("background-image");
      if (bgImage && bgImage.includes("historic_flag.png")) {
        element.style.removeProperty("background-image");
      }
      // Don't remove other styles as random flag needs them
    }
  }

  async function init() {
    log("info", "Initializing LU-HistoricMode plugin");

    // Load bridge port before initializing socket
    await loadBridgePort();

    // Ensure historic mode starts as inactive
    historicModeActive = false;

    // Inject CSS
    const style = document.createElement("style");
    style.textContent = CSS_RULES;
    document.head.appendChild(style);

    // Setup WebSocket bridge
    setupBridgeSocket();

    // Watch for DOM changes to find rewards element (only when in ChampSelect)
    const observer = new MutationObserver(() => {
      // Only try to update if in ChampSelect and historic mode is active
      if (isInChampSelect && historicModeActive) {
        updateHistoricFlag();
      }
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true,
    });

    // Request historic flag image on init (for when it's needed)
    requestHistoricFlagImage();

    // Don't try to update flag on init - wait for phase-change message to know if we're in ChampSelect

    log("info", "LU-HistoricMode plugin initialized");
  }

  // Start when DOM is ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
