/**
 * @name Rose-RandomSkin
 * @author Rose Team & Spok0jny
 * @description Dual Random Skin & Favorites Roll for Pengu Loader
 * @link https://github.com/Alban1911/Rose
 */
(function initRandomSkin() {
  const LOG_PREFIX = "[Rose-RandomSkin]";
  const DICE_DISABLED_ASSET_PATH = "dice-disabled.png";
  const DICE_ENABLED_ASSET_PATH = "dice-enabled.png";

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

  let activeDiceTooltipWrapper = null;

  function hideDiceTooltip() {
    if (activeDiceTooltipWrapper) {
      try { activeDiceTooltipWrapper.remove(); } catch (e) {}
      activeDiceTooltipWrapper = null;
    }
    document.querySelectorAll(".rose-dice-tooltip-wrapper").forEach((el) => {
      try { el.remove(); } catch (e) {}
    });
  }

  function attachTooltip(el, textGetter) {
    el.addEventListener("mouseenter", () => {
      hideDiceTooltip();
      const text = typeof textGetter === "function" ? textGetter() : textGetter;
      if (!text) return;

      const wrapper = document.createElement("div");
      wrapper.className = "rose-dice-tooltip-wrapper";
      wrapper.style.cssText = "position:fixed;pointer-events:none;z-index:10000;visibility:hidden";
      const tip = document.createElement("lol-uikit-tooltip");
      tip.setAttribute("data-tooltip-position", "bottom");
      const content = document.createElement("lol-uikit-content-block");
      content.setAttribute("type", "tooltip-system");
      const p = document.createElement("p");
      p.textContent = text;
      content.appendChild(p);
      tip.appendChild(content);
      wrapper.appendChild(tip);
      document.body.appendChild(wrapper);
      activeDiceTooltipWrapper = wrapper;

      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          if (!wrapper || !wrapper.isConnected) return;
          const btnRect = el.getBoundingClientRect();
          const wrapRect = wrapper.getBoundingClientRect();
          const centerX = btnRect.left + btnRect.width / 2;
          wrapper.style.left = `${centerX - wrapRect.width / 2}px`;
          wrapper.style.top = `${btnRect.bottom + 6}px`;
          wrapper.style.visibility = "visible";
        });
      });
    });

    el.addEventListener("mouseleave", hideDiceTooltip);
    el.addEventListener("click", hideDiceTooltip);
  }

  let randomModeActive = false;
  let randomModeType = "all";
  let randomSkinId = null;
  let isInChampSelect = false;
  let championLocked = false;
  let currentChampionFavoritesCount = 0;

  let diceContainerElement = null;
  let regularDiceBtn = null;
  let favoriteDiceBtn = null;
  let diceButtonState = "disabled";
  let diceDisabledImageUrl = null;
  let diceEnabledImageUrl = null;
  const pendingDiceImageRequests = new Map();

  const CSS_RULES = `
    .lu-random-dice-group {
      position: absolute !important;
      display: flex !important;
      flex-direction: row !important;
      align-items: center !important;
      justify-content: center !important;
      gap: 10px !important;
      z-index: 10 !important;
      pointer-events: auto !important;
    }

    .lu-random-dice-button {
      width: 38px !important;
      height: 23px !important;
      cursor: pointer !important;
      pointer-events: auto !important;
      background-size: contain !important;
      background-repeat: no-repeat !important;
      background-position: center !important;
      opacity: 1 !important;
      display: flex !important;
      align-items: center !important;
      justify-content: center !important;
      transition: transform 0.15s ease, opacity 0.15s ease, filter 0.15s ease !important;
      position: relative !important;
    }
    
    .lu-random-dice-button:hover:not(.disabled-fav) {
      transform: scale(1.12) !important;
      opacity: 0.95 !important;
    }

    .lu-random-dice-button.favorite-dice {
      filter: drop-shadow(0 0 4px rgba(245, 211, 101, 0.7));
    }

    .lu-random-dice-button.favorite-dice:hover:not(.disabled-fav) {
      filter: drop-shadow(0 0 8px rgba(245, 211, 101, 1));
    }

    .lu-random-dice-button.favorite-dice .dice-star-badge {
      position: absolute;
      top: -6px;
      right: -6px;
      width: 14px;
      height: 14px;
      pointer-events: none;
      filter: drop-shadow(0 0 3px #ffd700);
    }

    .lu-random-dice-button.disabled-fav {
      opacity: 0.45 !important;
      filter: grayscale(0.8) !important;
      cursor: default !important;
    }

    @keyframes lu-dice-roll {
      0% { transform: rotate(0deg) scale(1); }
      35% { transform: rotate(-30deg) scale(1.25); }
      75% { transform: rotate(20deg) scale(1.1); }
      100% { transform: rotate(0deg) scale(1); }
    }

    .lu-random-dice-button.rolling {
      animation: lu-dice-roll 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275) !important;
      pointer-events: none !important;
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

    const consoleMethod = level === "error" ? console.error : level === "warn" ? console.warn : console.log;
    consoleMethod(`${LOG_PREFIX} ${message}`, data || "");
  }

  function handleChampionLocked(data) {
    const wasLocked = championLocked;
    championLocked = data.locked === true;

    log("debug", "Received champion lock state update", { locked: championLocked, wasLocked: wasLocked });

    if (isInChampSelect && championLocked && !wasLocked) {
      log("debug", "Champion locked - creating dual dice buttons");
      setTimeout(() => {
        createDiceButtons();
      }, 100);
    } else if (!championLocked && wasLocked) {
      log("debug", "Champion unlocked - removing dice buttons");
      hideDiceTooltip();
      if (diceContainerElement) {
        diceContainerElement.remove();
        diceContainerElement = null;
      }
    }
  }

  function handlePhaseChange(data) {
    const wasInChampSelect = isInChampSelect;
    isInChampSelect = data.phase === "ChampSelect" || data.phase === "FINALIZATION" || data.phase === "Lobby";

    hideDiceTooltip();

    if (isInChampSelect && !wasInChampSelect) {
      log("debug", "Entered ChampSelect phase - enabling plugin");
      if (championLocked) {
        setTimeout(() => {
          createDiceButtons();
        }, 100);
      }
    } else if (!isInChampSelect && wasInChampSelect) {
      log("debug", "Left ChampSelect phase - disabling plugin");
      hideDiceTooltip();
      if (diceContainerElement) {
        diceContainerElement.remove();
        diceContainerElement = null;
      }
      championLocked = false;
    }
  }

  function handleLocalAssetUrl(data) {
    const assetPath = data.assetPath;
    let url = data.url;

    if (url && typeof url === "string") {
      url = url.replace("localhost", "127.0.0.1");
    }

    if (assetPath === DICE_DISABLED_ASSET_PATH && url) {
      diceDisabledImageUrl = url;
      pendingDiceImageRequests.delete(DICE_DISABLED_ASSET_PATH);
      updateDiceButtonsImages();
    } else if (assetPath === DICE_ENABLED_ASSET_PATH && url) {
      diceEnabledImageUrl = url;
      pendingDiceImageRequests.delete(DICE_ENABLED_ASSET_PATH);
      updateDiceButtonsImages();
    }
  }

  function handleRandomModeStateUpdate(data) {
    const wasActive = randomModeActive;
    randomModeActive = data.active === true;
    randomModeType = data.randomModeType || "all";
    randomSkinId = data.randomSkinId;
    diceButtonState = data.diceState || "disabled";

    log("info", "Received random mode state update", {
      active: randomModeActive,
      wasActive: wasActive,
      diceState: diceButtonState,
      randomSkinId: data.randomSkinId,
      randomChromaId: data.randomChromaId,
      randomModeType: randomModeType,
    });

    updateDiceButtons();
  }

  function findDiceButtonContainer() {
    const carouselContainer = document.querySelector(".skin-selection-carousel-container");
    if (carouselContainer) return carouselContainer;

    const carousel = document.querySelector(".skin-selection-carousel");
    if (carousel) return carousel;

    const mainContainer = document.querySelector(".champion-select-main-container");
    if (mainContainer) {
      const visibleDiv = mainContainer.querySelector("div.visible");
      if (visibleDiv) return visibleDiv;
    }

    return null;
  }

  function findDiceButtonLocation() {
    const allItems = document.querySelectorAll(".skin-selection-item");
    for (const item of allItems) {
      if (item.classList.contains("skin-carousel-offset-2")) {
        const rect = item.getBoundingClientRect();
        return {
          x: rect.left + rect.width / 2 - 43,
          y: rect.top + 78,
          width: 86,
          height: 23,
          relativeTo: item,
        };
      }
    }

    const selectedItem = document.querySelector(".skin-selection-item.skin-selection-item-selected");
    if (selectedItem) {
      const rect = selectedItem.getBoundingClientRect();
      return {
        x: rect.left + rect.width / 2 - 43,
        y: rect.top + 78,
        width: 86,
        height: 23,
        relativeTo: selectedItem,
      };
    }

    return null;
  }

  function createDiceButtons() {
    if (!championLocked) return;

    if (diceContainerElement) {
      diceContainerElement.remove();
      diceContainerElement = null;
    }

    const targetContainer = findDiceButtonContainer();
    if (!targetContainer) return;

    const location = findDiceButtonLocation();
    if (!location) return;

    requestDiceButtonImages();

    const containerRect = targetContainer.getBoundingClientRect();
    const containerComputedStyle = window.getComputedStyle(targetContainer);
    if (containerComputedStyle.position === "static") {
      targetContainer.style.position = "relative";
    }

    const group = document.createElement("div");
    group.className = "lu-random-dice-group";
    group.style.position = "absolute";
    group.style.left = `${location.x - containerRect.left}px`;
    group.style.top = `${location.y - containerRect.top}px`;
    group.style.width = `${location.width}px`;
    group.style.height = `${location.height}px`;

    // 1. Regular Dice (Roll All)
    const regBtn = document.createElement("div");
    regBtn.className = `lu-random-dice-button regular-dice ${diceButtonState}`;
    regBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      e.preventDefault();
      handleDiceClick("all");
    });
    attachTooltip(regBtn, "Roll Random Skin (All Skins)");

    // 2. Favorite Dice (Roll Favorites)
    const favBtn = document.createElement("div");
    favBtn.className = `lu-random-dice-button favorite-dice ${diceButtonState}`;
    favBtn.innerHTML = `
      <svg viewBox="0 0 24 24" class="dice-star-badge">
        <polygon points="12,2 15.09,8.26 22,9.27 17,14.14 18.18,21.02 12,17.77 5.82,21.02 7,14.14 2,9.27 8.91,8.26" 
                 fill="#ffd700" stroke="#785a28" stroke-width="1.5"/>
      </svg>
    `;
    favBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      e.preventDefault();
      if (currentChampionFavoritesCount <= 0) return;
      handleDiceClick("favorites");
    });
    attachTooltip(favBtn, () => {
      if (currentChampionFavoritesCount > 0) {
        return `Roll Random Favorite Skin (${currentChampionFavoritesCount} favorited)`;
      }
      return "No favorite skins for this champion. Star skins in Quickplay to add favorites!";
    });

    group.appendChild(regBtn);
    group.appendChild(favBtn);
    targetContainer.appendChild(group);

    diceContainerElement = group;
    regularDiceBtn = regBtn;
    favoriteDiceBtn = favBtn;

    updateDiceButtonsImages();
    updateFavoritesState();

    log("info", "Created dual dice buttons", { x: location.x, y: location.y });
  }

  function updateDiceButtonsImages() {
    if (!regularDiceBtn || !favoriteDiceBtn) return;

    if (diceButtonState === "disabled" && diceDisabledImageUrl) {
      regularDiceBtn.style.backgroundImage = `url("${diceDisabledImageUrl}")`;
      favoriteDiceBtn.style.backgroundImage = `url("${diceDisabledImageUrl}")`;
    } else if (diceButtonState === "enabled" && diceEnabledImageUrl) {
      if (randomModeType === "favorites") {
        favoriteDiceBtn.style.backgroundImage = `url("${diceEnabledImageUrl}")`;
        regularDiceBtn.style.backgroundImage = diceDisabledImageUrl ? `url("${diceDisabledImageUrl}")` : "";
      } else {
        regularDiceBtn.style.backgroundImage = `url("${diceEnabledImageUrl}")`;
        favoriteDiceBtn.style.backgroundImage = diceDisabledImageUrl ? `url("${diceDisabledImageUrl}")` : "";
      }
    } else {
      requestDiceButtonImages();
    }
  }

  function updateFavoritesState(favDetail) {
    if (favDetail && favDetail.favorites && Array.isArray(favDetail.favorites.skins)) {
      currentChampionFavoritesCount = favDetail.favorites.skins.length;
    }

    if (favoriteDiceBtn) {
      if (currentChampionFavoritesCount > 0) {
        favoriteDiceBtn.classList.remove("disabled-fav");
      } else {
        favoriteDiceBtn.classList.add("disabled-fav");
      }
    }
  }

  function updateDiceButtons() {
    if (!diceContainerElement) {
      createDiceButtons();
      return;
    }
    updateDiceButtonsImages();
    updateFavoritesState();
  }

  let lastDiceClickTime = 0;

  function handleDiceClick(mode) {
    const now = Date.now();
    if (now - lastDiceClickTime < 450) {
      log("debug", "Debouncing rapid dice click");
      return;
    }
    lastDiceClickTime = now;

    // Trigger visual roll animation on clicked button
    const targetBtn = mode === "favorites" ? favoriteDiceBtn : regularDiceBtn;
    if (targetBtn) {
      targetBtn.classList.remove("rolling");
      void targetBtn.offsetWidth; // trigger reflow
      targetBtn.classList.add("rolling");
      setTimeout(() => {
        if (targetBtn) targetBtn.classList.remove("rolling");
      }, 400);
    }

    // Determine state for Python:
    // If random mode is active in the SAME mode, clicking it toggles off (sends 'enabled')
    // If random mode is NOT active OR active in a DIFFERENT mode, clicking it activates/switches (sends 'disabled')
    let sendState = "disabled";
    if (randomModeActive && randomModeType === mode) {
      sendState = "enabled";
    } else {
      sendState = "disabled";
    }

    log("info", "Dice button clicked", {
      mode: mode,
      sendState: sendState,
      currentActive: randomModeActive,
      currentType: randomModeType,
    });

    const payload = {
      type: "dice-button-click",
      state: sendState,
      mode: mode,
      timestamp: Date.now(),
    };

    if (bridge) {
      bridge.send(payload);
    }
  }

  function requestDiceButtonImages() {
    if (!diceDisabledImageUrl && !pendingDiceImageRequests.has(DICE_DISABLED_ASSET_PATH)) {
      pendingDiceImageRequests.set(DICE_DISABLED_ASSET_PATH, true);
      if (bridge) bridge.send({ type: "request-local-asset", assetPath: DICE_DISABLED_ASSET_PATH, timestamp: Date.now() });
    }

    if (!diceEnabledImageUrl && !pendingDiceImageRequests.has(DICE_ENABLED_ASSET_PATH)) {
      pendingDiceImageRequests.set(DICE_ENABLED_ASSET_PATH, true);
      if (bridge) bridge.send({ type: "request-local-asset", assetPath: DICE_ENABLED_ASSET_PATH, timestamp: Date.now() });
    }
  }

  function injectCSS() {
    if (document.getElementById("rose-random-skin-css")) return;
    const style = document.createElement("style");
    style.id = "rose-random-skin-css";
    style.textContent = CSS_RULES;
    document.head.appendChild(style);
  }

  async function start() {
    injectCSS();

    try {
      bridge = await waitForBridge();
      log("info", "Bridge ready in ROSE-RandomSkin");

      if (bridge.subscribe) {
        bridge.subscribe("phase-change", handlePhaseChange);
        bridge.subscribe("champion-locked", handleChampionLocked);
        bridge.subscribe("local-asset-url", handleLocalAssetUrl);
        bridge.subscribe("random-mode-state", handleRandomModeStateUpdate);
        bridge.subscribe("favorites-state", (data) => {
          if (data && data.championFavorites) {
            updateFavoritesState({ favorites: data.championFavorites });
          }
        });
      }

      window.addEventListener("rose-favorites-updated", (e) => {
        if (e.detail) {
          updateFavoritesState(e.detail);
        }
      });

      window.addEventListener("blur", hideDiceTooltip);
      window.addEventListener("pointerdown", (e) => {
        if (activeDiceTooltipWrapper && !e.target.closest(".lu-random-dice-button")) {
          hideDiceTooltip();
        }
      });
    } catch (e) {
      log("error", "Failed to initialize RandomSkin bridge:", e);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
