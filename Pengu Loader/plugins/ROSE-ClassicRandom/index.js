/**
 * @name ROSE-ClassicRandom
 * @description JADE-only random button, isolated from the regular carousel.
 */
(function initJadeRandom() {
  "use strict";

  const BUTTON_ID = "rose-jade-random-button";
  const MARK_ID = "rose-jade-random-mark";
  const STYLE_ID = "rose-jade-random-style";
  const DISABLED_ASSET = "dice-disabled.png";
  const ENABLED_ASSET = "dice-enabled.png";
  const FLAG_ASSET = "random_flag.png";
  let bridge = null;
  let active = false;
  let enabled = false;
  let disabledUrl = "";
  let enabledUrl = "";
  let flagUrl = "";
  let isInJadeChampSelect = false;
  let championLocked = false;
  let phase = "";
  let randomSkinId = 0;
  let projectedRandomSkinId = 0;
  let projectionSuppressed = false;

  function log(level, message, data = null) {
    const method = level === "error" ? "error" : level === "warn" ? "warn" : "log";
    console[method](`[ClassicRandom] ${message}`, data || "");
    try {
      bridge?.send({ type: "plugin-log", source: "ClassicRandom", level, message, data, timestamp: Date.now() });
    } catch (_) {}
  }

  function jadeActive() {
    return window.__roseClassicWheelApi?.state?.().active === true;
  }

  function selectedCard() {
    return document.querySelector(
      ".rose-jade-native-card.rose-jade-native-card--selected:not(.skins-pane__skin-card--placeholder)"
    );
  }

  function projectionReady() {
    return phase === "FINALIZATION" || phase === "GameStart" ||
      document.querySelector(".champion-select.timer-less-than-11-seconds") !== null;
  }

  function projectPendingRandomSelection(reason = "random-state") {
    const wheel = window.__roseClassicWheelApi;
    if (
      !active || projectionSuppressed || !randomSkinId ||
      !isInJadeChampSelect || !jadeActive() || !projectionReady()
    ) {
      return;
    }
    if (projectedRandomSkinId === randomSkinId) return;
    if (wheel?.projectResourceSelection?.(randomSkinId, "random-state") !== true) return;
    projectedRandomSkinId = randomSkinId;
    log("info", "Random skin projected during finalization", {
      skinId: randomSkinId,
      reason,
    });
  }

  function removeButton() {
    document.getElementById(BUTTON_ID)?.remove();
  }

  function removeMarker() {
    document.getElementById(MARK_ID)?.remove();
  }

  function renderMarker() {
    if (!enabled) {
      removeMarker();
      return;
    }
    const card = selectedCard();
    if (!card) {
      removeMarker();
      return;
    }
    let marker = document.getElementById(MARK_ID);
    if (!marker) {
      marker = document.createElement("div");
      marker.id = MARK_ID;
      marker.title = "Random skin";
      marker.setAttribute("aria-label", "Random skin");
    }
    if (flagUrl) marker.style.backgroundImage = `url("${flagUrl}")`;
    if (marker.parentElement !== card) card.appendChild(marker);
  }

  function render() {
    if (!isInJadeChampSelect || !championLocked || !jadeActive()) {
      removeButton();
      removeMarker();
      return;
    }
    const card = selectedCard();
    if (!card) return;
    let button = document.getElementById(BUTTON_ID);
    if (!button) {
      button = document.createElement("button");
      button.id = BUTTON_ID;
      button.className = "lu-random-dice-button rose-jade-random-button";
      button.type = "button";
      button.title = "Random skin";
      button.addEventListener("pointerdown", (event) => event.stopPropagation());
      button.addEventListener("mousedown", (event) => event.stopPropagation());
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        const previousState = active ? "enabled" : "disabled";
        active = !active;
        enabled = active;
        log("info", "Random toggle requested", { previousState, nextState: active ? "enabled" : "disabled" });
        render();
        bridge?.send({
          type: "dice-button-click",
          state: previousState,
          timestamp: Date.now(),
        });
      });
    }
    if (button.parentElement !== card) card.appendChild(button);
    const image = enabled ? enabledUrl : disabledUrl;
    button.style.backgroundImage = image ? `url("${image}")` : "none";
    button.classList.toggle("rose-jade-random-button--enabled", enabled);
    button.dataset.active = enabled ? "true" : "false";
    button.setAttribute("aria-pressed", enabled ? "true" : "false");
    renderMarker();
  }

  function handleAsset(data) {
    const url = String(data?.url || "").replace("localhost", "127.0.0.1");
    if (data?.assetPath === DISABLED_ASSET) disabledUrl = url;
    if (data?.assetPath === ENABLED_ASSET) enabledUrl = url;
    if (data?.assetPath === FLAG_ASSET) flagUrl = url;
    render();
  }

  function requestAssets() {
    for (const assetPath of [DISABLED_ASSET, ENABLED_ASSET, FLAG_ASSET]) {
      bridge?.send({ type: "request-local-asset", assetPath, timestamp: Date.now() });
    }
  }

  function handlePhaseChange(data) {
    phase = String(data?.phase || "");
    const classicMode =
      Number(data?.mapId) === 453 ||
      Number(data?.queueId) === 3260 ||
      String(data?.gameMode || "").toUpperCase() === "JADE";
    isInJadeChampSelect =
      classicMode && (phase === "ChampSelect" || phase === "FINALIZATION");
    if (!isInJadeChampSelect) {
      championLocked = false;
      active = false;
      enabled = false;
      randomSkinId = 0;
      projectedRandomSkinId = 0;
      projectionSuppressed = false;
      removeButton();
      removeMarker();
      return;
    }
    render();
    projectPendingRandomSelection("phase-change");
  }

  function handleChampionLocked(data) {
    championLocked = data?.locked === true;
    render();
  }

  function handleWheelLayout(event) {
    if (event?.detail?.active === false) {
      removeButton();
      removeMarker();
      return;
    }
    render();
  }

  async function start() {
    while (!window.__roseBridge) await new Promise((resolve) => setTimeout(resolve, 50));
    bridge = window.__roseBridge;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      #${BUTTON_ID} {
        position: absolute; top: -43px; left: 50%; transform: translateX(-50%);
        width: 38px; height: 23px; padding: 0; border: 0; z-index: 25;
        background: transparent center / contain no-repeat; cursor: pointer;
      }
      #${MARK_ID} {
        position: absolute; top: -14px; right: -14px; width: 32px; height: 32px;
        z-index: 24; pointer-events: none; background: center / contain no-repeat;
      }
    `;
    document.head.appendChild(style);
    bridge.subscribe("random-mode-state", (data) => {
      const wasActive = active;
      const nextRandomSkinId = Number(data?.randomSkinId) || 0;
      active = data?.active === true;
      enabled = active;
      if (!active) {
        randomSkinId = 0;
        projectedRandomSkinId = 0;
        projectionSuppressed = false;
      } else {
        if (!wasActive || nextRandomSkinId !== randomSkinId) {
          projectedRandomSkinId = 0;
          projectionSuppressed = false;
        }
        randomSkinId = nextRandomSkinId;
      }
      log("info", "Random state confirmed", { active, randomSkinId });
      render();
      projectPendingRandomSelection();
    });
    bridge.subscribe("local-asset-url", handleAsset);
    bridge.subscribe("phase-change", handlePhaseChange);
    bridge.subscribe("champion-locked", handleChampionLocked);
    const classicState = window.__roseClassicWheelApi?.state?.();
    if (classicState) handlePhaseChange(classicState);
    window.addEventListener("rose-jade-wheel-layout", handleWheelLayout);
    window.addEventListener("rose-classic-selection-change", (event) => {
      const reason = String(event?.detail?.reason || "");
      if (
        active && reason !== "random-state" &&
        (reason === "native-card-click" || reason === "visual-center-change")
      ) {
        projectionSuppressed = true;
        projectedRandomSkinId = 0;
      }
      render();
    });
    bridge.onReady(requestAssets);
    requestAssets();
    log("info", "Classic random plugin initialized");
    new MutationObserver(render).observe(document.body, { childList: true, subtree: true });
    setInterval(() => {
      render();
      projectPendingRandomSelection("poll");
    }, 500);
  }

  start();
})();
