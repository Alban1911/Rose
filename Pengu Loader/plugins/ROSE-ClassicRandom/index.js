/**
 * @name ROSE-ClassicRandom
 * @description JADE-only random button, isolated from the regular carousel.
 */
(function initJadeRandom() {
  "use strict";

  const BUTTON_ID = "rose-jade-random-button";
  const STYLE_ID = "rose-jade-random-style";
  const DISABLED_ASSET = "dice-disabled.png";
  const ENABLED_ASSET = "dice-enabled.png";
  let bridge = null;
  let active = false;
  let enabled = false;
  let disabledUrl = "";
  let enabledUrl = "";
  let isInJadeChampSelect = false;
  let championLocked = false;

  function jadeActive() {
    return window.__roseJadeWheelDebug?.state?.().active === true;
  }

  function selectedCard() {
    return document.querySelector(
      ".rose-jade-native-card.rose-jade-native-card--selected:not(.skins-pane__skin-card--placeholder)"
    );
  }

  function removeButton() {
    document.getElementById(BUTTON_ID)?.remove();
  }

  function render() {
    if (!isInJadeChampSelect || !championLocked || !jadeActive()) {
      removeButton();
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
        const previousState = enabled ? "enabled" : "disabled";
        enabled = !enabled;
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
  }

  function handleAsset(data) {
    const url = String(data?.url || "").replace("localhost", "127.0.0.1");
    if (data?.assetPath === DISABLED_ASSET) disabledUrl = url;
    if (data?.assetPath === ENABLED_ASSET) enabledUrl = url;
    render();
  }

  function requestAssets() {
    for (const assetPath of [DISABLED_ASSET, ENABLED_ASSET]) {
      bridge?.send({ type: "request-local-asset", assetPath, timestamp: Date.now() });
    }
  }

  function handlePhaseChange(data) {
    const phase = String(data?.phase || "");
    const classicMode =
      Number(data?.mapId) === 453 || String(data?.gameMode || "").toUpperCase() === "JADE";
    isInJadeChampSelect =
      classicMode && (phase === "ChampSelect" || phase === "FINALIZATION");
    if (!isInJadeChampSelect) {
      championLocked = false;
      removeButton();
      return;
    }
    render();
  }

  function handleChampionLocked(data) {
    championLocked = data?.locked === true;
    render();
  }

  function handleWheelLayout(event) {
    if (event?.detail?.active === false) {
      removeButton();
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
    `;
    document.head.appendChild(style);
    bridge.subscribe("random-mode-state", (data) => {
      active = data?.active === true;
      enabled = active || data?.diceState === "enabled";
      render();
    });
    bridge.subscribe("local-asset-url", handleAsset);
    bridge.subscribe("phase-change", handlePhaseChange);
    bridge.subscribe("champion-locked", handleChampionLocked);
    window.addEventListener("rose-jade-wheel-layout", handleWheelLayout);
    bridge.onReady(requestAssets);
    requestAssets();
    new MutationObserver(render).observe(document.body, { childList: true, subtree: true });
    setInterval(render, 500);
  }

  start();
})();
