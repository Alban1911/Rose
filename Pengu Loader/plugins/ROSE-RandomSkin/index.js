/**
 * @name Rose-RandomSkin
 * @author Rose Team
 * @description Random skin for Pengu Loader
 * @link https://github.com/FlorentTariolle/Rose-RandomSkin
 */
(function initRandomSkin() {
  const LOG_PREFIX = "[Rose-RandomSkin]";
  const REWARDS_SELECTOR = ".skin-selection-item-information.loyalty-reward-icon--rewards";
  const RANDOM_FLAG_ASSET_PATH = "random_flag.png";
  const DICE_DISABLED_ASSET_PATH = "dice-disabled.png";
  const DICE_ENABLED_ASSET_PATH = "dice-enabled.png";

  // Shared bridge (provided by ROSE-SkinMonitor)
  let bridge = null;

  function waitForBridge() {
    return new Promise((resolve, reject) => {
      const timeout = 10000;
      const interval = 50;
      let elapsed = 0;
      const check = () => {
        if (window.__roseBridge) return resolve(window.__roseBridge);
        elapsed += interval;
        if (elapsed >= timeout) return reject(new Error("Bridge not available"));
        setTimeout(check, interval);
      };
      check();
    });
  }

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

  let randomModeActive = false;
  let currentRewardsElement = null;
  let randomFlagImageUrl = null; // HTTP URL from Python
  const pendingRandomFlagRequest = new Map(); // Track pending requests
  let isInChampSelect = false; // Track if we're in ChampSelect phase
  let championLocked = false; // Track if a champion is locked

  // Dice button state
  let diceButtonElement = null;
  let diceButtonState = 'disabled'; // 'disabled' or 'enabled'
  let diceDisabledImageUrl = null; // HTTP URL from Python
  let diceEnabledImageUrl = null; // HTTP URL from Python
  const pendingDiceImageRequests = new Map(); // Track pending requests

  const CSS_RULES = `
    .skin-selection-item-information.loyalty-reward-icon--rewards.lu-random-flag-active {
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
    
    .lu-random-dice-button {
      position: absolute !important;
      width: 38px !important;
      height: 23px !important;
      cursor: pointer !important;
      z-index: 0 !important;
      pointer-events: auto !important;
      background-size: contain !important;
      background-repeat: no-repeat !important;
      background-position: center !important;
      opacity: 1 !important;
      display: block !important;
      visibility: visible !important;
    }
    
    .lu-random-dice-button:hover {
      opacity: 0.8 !important;
    }
  `;

  function log(level, message, data = null) {
    const payload = {
      type: "chroma-log",
      source: "LU-RandomSkin",
      level: level,
      message: message,
      timestamp: Date.now(),
    };
    if (data) payload.data = data;

    if (bridge) bridge.send(payload);

    // Also log to console for debugging
    const consoleMethod = level === "error" ? console.error : level === "warn" ? console.warn : console.log;
    consoleMethod(`${LOG_PREFIX} ${message}`, data || "");
  }

  function handleChampionLocked(data) {
    const wasLocked = championLocked;
    championLocked = data.locked === true;

    log("debug", "Received champion lock state update", { locked: championLocked, wasLocked: wasLocked });

    // Only create dice button if entering ChampSelect and champion is now locked
    if (isInChampSelect && championLocked && !wasLocked) {
      log("debug", "Champion locked - creating dice button");
      setTimeout(() => {
        createDiceButton();
        if (randomModeActive) {
          updateRandomFlag();
        }
      }, 100);
    } else if (!championLocked && wasLocked) {
      // Champion unlocked - remove dice button
      log("debug", "Champion unlocked - removing dice button");
      if (diceButtonElement) {
        diceButtonElement.remove();
        diceButtonElement = null;
      }
    }
  }

  function handlePhaseChange(data) {
    const wasInChampSelect = isInChampSelect;
    // Check if we're entering ChampSelect phase
    isInChampSelect = data.phase === "ChampSelect" || data.phase === "FINALIZATION";

    if (isInChampSelect && !wasInChampSelect) {
      log("debug", "Entered ChampSelect phase - enabling plugin");
      // Only create dice button if champion is already locked
      if (championLocked) {
        setTimeout(() => {
          createDiceButton();
          if (randomModeActive) {
            updateRandomFlag();
          }
        }, 100);
      } else {
        log("debug", "Waiting for champion lock before creating dice button");
      }
    } else if (!isInChampSelect && wasInChampSelect) {
      log("debug", "Left ChampSelect phase - disabling plugin");
      // Hide flag and remove dice button when leaving ChampSelect
      if (currentRewardsElement) {
        hideFlagOnElement(currentRewardsElement);
        currentRewardsElement = null;
      }
      if (diceButtonElement) {
        diceButtonElement.remove();
        diceButtonElement = null;
      }
      // Reset retry counters
      if (updateRandomFlag._retryCount) {
        updateRandomFlag._retryCount = 0;
      }
      // Reset champion lock state when leaving ChampSelect
      championLocked = false;
      // Update button if it exists and is in enabled state
      if (diceButtonElement && diceButtonState === 'enabled') {
        updateDiceButtonImage();
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

    if (assetPath === RANDOM_FLAG_ASSET_PATH && url) {
      randomFlagImageUrl = url;
      pendingRandomFlagRequest.delete(RANDOM_FLAG_ASSET_PATH);
      log("info", "Received random flag image URL from Python", { url: url });

      // Update the flag if it's currently active and we're in ChampSelect
      if (isInChampSelect && randomModeActive) {
        updateRandomFlag();
      }
    } else if (assetPath === DICE_DISABLED_ASSET_PATH && url) {
      diceDisabledImageUrl = url;
      pendingDiceImageRequests.delete(DICE_DISABLED_ASSET_PATH);
      log("info", "Received dice disabled image URL from Python", { url: url });

      // Update button if it exists and is in disabled state
      if (diceButtonElement && diceButtonState === 'disabled') {
        updateDiceButtonImage();
      }
    } else if (assetPath === DICE_ENABLED_ASSET_PATH && url) {
      diceEnabledImageUrl = url;
      pendingDiceImageRequests.delete(DICE_ENABLED_ASSET_PATH);
      log("info", "Received dice enabled image URL from Python", { url: url });

      // Update button if it exists and is in enabled state
      if (diceButtonElement && diceButtonState === 'enabled') {
        updateDiceButtonImage();
      }
    }
  }

  function handleRandomModeStateUpdate(data) {
    const wasActive = randomModeActive;
    const previousState = diceButtonState;
    randomModeActive = data.active === true;
    diceButtonState = data.diceState || 'disabled';

    log("info", "Received random mode state update", {
      active: randomModeActive,
      wasActive: wasActive,
      diceState: diceButtonState,
      randomSkinId: data.randomSkinId
    });

    // Only update if we're in ChampSelect
    if (!isInChampSelect) {
      return;
    }

    // Update dice button state
    updateDiceButton();

    // Always update the flag when we receive a state update (even if state didn't change)
    // This ensures the flag is shown even if the element wasn't found initially
    updateRandomFlag();
  }

  function findRewardsElement() {
    // Only try to find elements when in ChampSelect
    if (!isInChampSelect) {
      return null;
    }

    // Only consider the central skin item (offset-2) in the carousel
    const allItems = document.querySelectorAll(".skin-selection-item");
    for (const item of allItems) {
      // Check if this is the central item (offset-2)
      if (item.classList.contains("skin-carousel-offset-2")) {
        const info = item.querySelector(".skin-selection-item-information.loyalty-reward-icon--rewards");
        if (info) {
          return info;
        }
      }
    }

    // Only log if we're actually in ChampSelect (to avoid spam before entering)
    return null;
  }

  function findDiceButtonContainer() {
    // Only try to find container when in ChampSelect
    if (!isInChampSelect) {
      return null;
    }

    // Find the carousel container to match its stacking context
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

  function findDiceButtonLocation() {
    // Only try to find location when in ChampSelect
    if (!isInChampSelect) {
      return null;
    }

    // Always find the central skin item (offset-2) in the carousel
    const allItems = document.querySelectorAll(".skin-selection-item");
    for (const item of allItems) {
      // Check if this is the central item (offset-2)
      if (item.classList.contains("skin-carousel-offset-2")) {
        const rect = item.getBoundingClientRect();
        // Position at same x (centered) but 78px lower in y than central skin
        return {
          x: rect.left + rect.width / 2 - 19, // Half of button width (38px) - centered
          y: rect.top + 78, // 78px lower than the top of the central skin
          width: 38,
          height: 23,
          relativeTo: item
        };
      }
    }

    // Fallback: try selected item if central item not found
    const selectedItem = document.querySelector(".skin-selection-item.skin-selection-item-selected");
    if (selectedItem) {
      const rect = selectedItem.getBoundingClientRect();
      return {
        x: rect.left + rect.width / 2 - 19, // Half of button width (38px) - centered
        y: rect.top + 78, // 78px lower than the top of the selected skin
        width: 38,
        height: 23,
        relativeTo: selectedItem
      };
    }

    return null;
  }

  function createDiceButton() {
    // Don't create button if champion is not locked
    if (!championLocked) {
      log("debug", "Cannot create dice button - champion not locked");
      return;
    }

    // Remove existing button if it exists
    if (diceButtonElement) {
      diceButtonElement.remove();
      diceButtonElement = null;
    }

    // Find the target container (div.visible in main champ select container)
    const targetContainer = findDiceButtonContainer();
    if (!targetContainer) {
      // Don't log error on every attempt - only log occasionally
      if (!createDiceButton._lastLogTime || Date.now() - createDiceButton._lastLogTime > 5000) {
        log("debug", "Could not find dice button container (will retry)");
        createDiceButton._lastLogTime = Date.now();
      }
      return;
    }

    const location = findDiceButtonLocation();
    if (!location) {
      // Don't log error on every attempt - only log occasionally
      if (!createDiceButton._lastLogTime || Date.now() - createDiceButton._lastLogTime > 5000) {
        log("debug", "Could not find dice button location (will retry)");
        createDiceButton._lastLogTime = Date.now();
      }
      return;
    }

    // Request images if not already loaded
    requestDiceButtonImages();

    // Get container's position relative to viewport for absolute positioning
    const containerRect = targetContainer.getBoundingClientRect();

    // Ensure container has positioning context for absolute children
    const containerComputedStyle = window.getComputedStyle(targetContainer);
    if (containerComputedStyle.position === 'static') {
      targetContainer.style.position = 'relative';
    }

    const button = document.createElement("div");
    button.className = `lu-random-dice-button ${diceButtonState}`;
    button.style.position = "absolute"; // Use absolute positioning relative to container
    // Calculate position relative to container
    // getBoundingClientRect() already accounts for scroll, transforms, etc.
    button.style.left = `${location.x - containerRect.left}px`;
    button.style.top = `${location.y - containerRect.top}px`;
    button.style.width = `${location.width}px`;
    button.style.height = `${location.height}px`;
    button.style.zIndex = "0";
    button.style.display = "block"; // Ensure button is visible
    button.style.visibility = "visible"; // Ensure button is visible
    button.style.opacity = "1"; // Ensure button is visible

    // Append to the target container instead of document.body
    targetContainer.appendChild(button);
    diceButtonElement = button;

    // Set initial background image based on state (after appending to DOM)
    updateDiceButtonImage();

    // Add click handler
    button.addEventListener("click", (e) => {
      e.stopPropagation();
      e.preventDefault();
      handleDiceButtonClick();
    });

    // Store the relative element for repositioning
    diceButtonElement._relativeTo = location.relativeTo;
    diceButtonElement._container = targetContainer;

    // Force browser to render the button immediately
    void button.offsetHeight; // Trigger reflow
    button.style.display = "block"; // Ensure it's set again after reflow

    log("info", "Created dice button", { x: location.x, y: location.y, state: diceButtonState });
  }

  function updateDiceButtonImage() {
    if (!diceButtonElement) {
      return;
    }

    // Use local images if available, otherwise wait for them to load
    if (diceButtonState === 'disabled' && diceDisabledImageUrl) {
      diceButtonElement.style.backgroundImage = `url("${diceDisabledImageUrl}")`;
    } else if (diceButtonState === 'enabled' && diceEnabledImageUrl) {
      diceButtonElement.style.backgroundImage = `url("${diceEnabledImageUrl}")`;
    } else {
      // Images not loaded yet, request them
      requestDiceButtonImages();
    }
  }

  function requestDiceButtonImages() {
    // Request disabled image
    if (!diceDisabledImageUrl && !pendingDiceImageRequests.has(DICE_DISABLED_ASSET_PATH)) {
      pendingDiceImageRequests.set(DICE_DISABLED_ASSET_PATH, true);

      const payload = {
        type: "request-local-asset",
        assetPath: DICE_DISABLED_ASSET_PATH,
        timestamp: Date.now(),
      };

      log("debug", "Requesting dice disabled image from Python", { assetPath: DICE_DISABLED_ASSET_PATH });

      if (bridge) bridge.send(payload);
    }

    // Request enabled image
    if (!diceEnabledImageUrl && !pendingDiceImageRequests.has(DICE_ENABLED_ASSET_PATH)) {
      pendingDiceImageRequests.set(DICE_ENABLED_ASSET_PATH, true);

      const payload = {
        type: "request-local-asset",
        assetPath: DICE_ENABLED_ASSET_PATH,
        timestamp: Date.now(),
      };

      log("debug", "Requesting dice enabled image from Python", { assetPath: DICE_ENABLED_ASSET_PATH });

      if (bridge) bridge.send(payload);
    }
  }

  function updateDiceButton() {
    if (!diceButtonElement) {
      createDiceButton();
      return;
    }

    // Don't update position dynamically - it's set once on creation
    // Only update button state and image

    // Update button state
    diceButtonElement.className = `lu-random-dice-button ${diceButtonState}`;

    // Update button image based on state
    updateDiceButtonImage();

    log("debug", "Updated dice button state", { state: diceButtonState });
  }

  function handleDiceButtonClick() {
    log("info", "Dice button clicked", { currentState: diceButtonState });

    // Send click event to Python
    const payload = {
      type: "dice-button-click",
      state: diceButtonState,
      timestamp: Date.now(),
    };

    if (bridge) {
      bridge.send(payload);
    } else {
      log("warn", "Bridge not ready, dice button click lost");
    }
  }

  function requestRandomFlagImage() {
    // Request random flag image from Python (same way as HistoricMode)
    if (!randomFlagImageUrl && !pendingRandomFlagRequest.has(RANDOM_FLAG_ASSET_PATH)) {
      pendingRandomFlagRequest.set(RANDOM_FLAG_ASSET_PATH, true);

      const payload = {
        type: "request-local-asset",
        assetPath: RANDOM_FLAG_ASSET_PATH,
        timestamp: Date.now(),
      };

      log("debug", "Requesting random flag image from Python", { assetPath: RANDOM_FLAG_ASSET_PATH });

      if (bridge) bridge.send(payload);
    }
  }

  function updateRandomFlag() {
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
      if (!updateRandomFlag._retryCount) {
        updateRandomFlag._retryCount = 0;
      }
      if (updateRandomFlag._retryCount < 5) {
        updateRandomFlag._retryCount++;
        setTimeout(() => {
          if (isInChampSelect) { // Check again before retrying
            updateRandomFlag();
          } else {
            updateRandomFlag._retryCount = 0; // Reset if we left ChampSelect
          }
        }, 500);
      } else {
        log("warn", "Rewards element not found after 5 retries, giving up");
        updateRandomFlag._retryCount = 0; // Reset for next attempt
      }
      return;
    }

    // Reset retry count on success
    updateRandomFlag._retryCount = 0;

    // If we have a previously cached element that's different from the current one, hide it first
    if (currentRewardsElement && currentRewardsElement !== element) {
      log("debug", "Selected skin changed - hiding flag on previous element");
      hideFlagOnElement(currentRewardsElement);
    }

    currentRewardsElement = element;

    // Check element visibility (no logging to reduce spam)
    const computedStyle = window.getComputedStyle(element);
    const isVisible = computedStyle.display !== "none" && computedStyle.visibility !== "hidden" && computedStyle.opacity !== "0";

    if (randomModeActive) {
      // Request image if we don't have it yet
      if (!randomFlagImageUrl) {
        requestRandomFlagImage();
        // Wait for image URL before applying
        return;
      }

      // Force element to be visible (rewards icon is usually hidden)
      element.style.setProperty("display", "block", "important");
      element.style.setProperty("visibility", "visible", "important");
      element.style.setProperty("opacity", "1", "important");

      // Apply the image URL from Python
      element.classList.add("lu-random-flag-active");
      element.style.setProperty("background-image", `url("${randomFlagImageUrl}")`, "important");
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

      log("info", "Random flag shown on rewards element", {
        url: randomFlagImageUrl,
        display: element.style.display,
        visibility: element.style.visibility
      });
    } else {
      // Random mode is inactive - hide the flag
      hideFlagOnElement(element);
      log("info", "Random flag hidden on rewards element");
    }
  }

  function hideFlagOnElement(element) {
    if (!element) return;

    // Only remove our flag class
    element.classList.remove("lu-random-flag-active");

    // Check if historic flag is active - if so, don't remove shared styles
    const hasHistoricFlag = element.classList.contains("lu-historic-flag-active");

    if (!hasHistoricFlag) {
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
      // Historic flag is active - only remove our background image, keep shared styles
      // Check if the background-image is ours (contains random_flag.png)
      const bgImage = element.style.getPropertyValue("background-image");
      if (bgImage && bgImage.includes("random_flag.png")) {
        element.style.removeProperty("background-image");
      }
      // Don't remove other styles as historic flag needs them
    }
  }

  async function init() {
    log("info", "Initializing LU-RandomSkin plugin");

    // Wait for shared bridge
    bridge = await waitForBridge();

    // Ensure random mode starts as inactive
    randomModeActive = false;
    diceButtonState = 'disabled';

    // Inject CSS
    const style = document.createElement("style");
    style.textContent = CSS_RULES;
    document.head.appendChild(style);

    // Subscribe to bridge message types
    bridge.subscribe("random-mode-state", handleRandomModeStateUpdate);
    bridge.subscribe("local-asset-url", handleLocalAssetUrl);
    bridge.subscribe("phase-change", handlePhaseChange);
    bridge.subscribe("champion-locked", handleChampionLocked);

    // On bridge (re)connect, re-request assets
    bridge.onReady(() => {
      requestRandomFlagImage();
      requestDiceButtonImages();
    });

    // Watch for DOM changes to find rewards element and dice button location (only when in ChampSelect)
    const observer = new MutationObserver(() => {
      if (!isInChampSelect) {
        return; // Don't do anything if not in ChampSelect
      }

      if (randomModeActive && !currentRewardsElement) {
        updateRandomFlag();
      }
      // Only create dice button if it doesn't exist and champion is locked - don't update position dynamically
      if (!diceButtonElement && championLocked) {
        createDiceButton();
      }
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true,
    });

    // Don't try to create elements on init - wait for phase-change message to know if we're in ChampSelect

    log("info", "LU-RandomSkin plugin initialized");
  }

  // Start when DOM is ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

