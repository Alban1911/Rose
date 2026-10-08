/**
 * @name ROSE-ClassicHistoric
 * @description JADE-only history marker and standard history toast.
 */
(function initJadeHistoric() {
  "use strict";

  const MARK_ID = "rose-jade-historic-mark";
  const TOAST_ID = "rose-jade-historic-toast";
  const STYLE_ID = "rose-jade-historic-style";
  const ASSET = "historic_flag.png";
  let bridge = null;
  let active = false;
  let skinName = "";
  let imageUrl = "";
  let isInJadeChampSelect = false;
  let randomModeActive = false;
  let presentationReady = false;
  let customModActive = false;
  let customModName = "";
  let customModTargetSkinIds = new Set();

  function log(level, message, data = null) {
    const method = level === "error" ? "error" : level === "warn" ? "warn" : "log";
    console[method](`[ClassicHistoric] ${message}`, data || "");
    try {
      bridge?.send({ type: "plugin-log", source: "ClassicHistoric", level, message, data, timestamp: Date.now() });
    } catch (_) {}
  }

  function jadeActive() {
    return window.__roseClassicWheelApi?.state?.().active === true;
  }

  function cleanup() {
    document.getElementById(MARK_ID)?.remove();
    document.getElementById(TOAST_ID)?.remove();
  }

  function currentSkinId() {
    return Number(window.__roseClassicWheelApi?.currentSelection?.()?.skinId) || 0;
  }

  function customModApplies() {
    const skinId = currentSkinId();
    return customModActive && skinId > 0 && customModTargetSkinIds.has(skinId);
  }

  function renderMarker() {
    const anchor = document.querySelector(
      ".rose-jade-native-card.rose-jade-native-card--selected:not(.skins-pane__skin-card--placeholder) > .rose-jade-history-anchor"
    );
    if (!anchor) {
      document.getElementById(MARK_ID)?.remove();
      return;
    }
    let mark = document.getElementById(MARK_ID);
    if (!mark) {
      mark = document.createElement("div");
      mark.id = MARK_ID;
      mark.setAttribute("aria-label", "Historic skin");
    }
    mark.title = "Historic skin";
    if (imageUrl) mark.style.backgroundImage = `url("${imageUrl}")`;
    if (mark.parentElement !== anchor) anchor.appendChild(mark);
  }

  function createToast() {
    const toast = document.createElement("div");
    toast.id = TOAST_ID;

    const toastBody = document.createElement("div");
    toastBody.className = "toast-body";

    const toastContent = document.createElement("div");
    toastContent.className = "toast-content";
    const frame = document.createElement("lol-uikit-dialog-frame");
    frame.className = "lol-uikit-dialog-frame top dismissable-icon";
    const content = document.createElement("lol-uikit-content-block");
    content.className = "lol-ready-check-notification-party-dodge";
    content.setAttribute("type", "notification");
    const text = document.createElement("p");
    text.className = "rose-jade-historic-text";
    const subBorder = document.createElement("div");
    subBorder.className = "lol-uikit-dialog-frame-sub-border";
    const close = document.createElement("div");
    close.className = "lol-uikit-dialog-frame-toast-close-button";
    close.setAttribute("role", "button");
    close.tabIndex = 0;
    close.title = "Close";
    close.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const dismissType = customModApplies() ? "dismiss-custom-mod" : "dismiss-historic";
      if (dismissType === "dismiss-custom-mod") customModActive = false;
      else active = false;
      cleanup();
      bridge?.send({ type: dismissType, timestamp: Date.now() });
    });

    content.appendChild(text);
    frame.append(content, subBorder, close);
    toastContent.appendChild(frame);
    toastBody.appendChild(toastContent);
    toast.appendChild(toastBody);
    return toast;
  }

  function renderToast(displayName) {
    if (!displayName) {
      document.getElementById(TOAST_ID)?.remove();
      return;
    }
    let toast = document.getElementById(TOAST_ID);
    if (!toast) {
      toast = createToast();
      document.body.appendChild(toast);
    }
    const text = toast.querySelector(".rose-jade-historic-text");
    if (text && text.textContent !== displayName) text.textContent = displayName;
  }

  function render() {
    const showHistoric = active && !randomModeActive && presentationReady;
    const showCustomMod = customModApplies();
    if (!isInJadeChampSelect || !jadeActive() || (!showHistoric && !showCustomMod)) {
      cleanup();
      return;
    }
    if (showHistoric) renderMarker();
    else document.getElementById(MARK_ID)?.remove();
    renderToast(showCustomMod ? customModName : skinName);
  }

  function injectStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      #${MARK_ID} {
        position: absolute; inset: 0; width: 100%; height: 100%;
        z-index: 24; pointer-events: none; background: center / contain no-repeat;
      }
      #${TOAST_ID} {
        position: fixed; left: 50%; bottom: calc(10% + 215px);
        transform: translateX(-50%); z-index: 10000; display: flex;
        align-items: center; justify-content: center; width: auto; max-width: 300px;
        margin: 0; padding: 0; box-sizing: border-box;
        color: #b2a580; font-size: 14px; line-height: 1.4; pointer-events: none;
      }
      #${TOAST_ID} .toast-body {
        position: relative; display: flex; flex-direction: column;
        justify-content: space-between; box-sizing: border-box; width: auto; margin: 0 auto;
      }
      #${TOAST_ID} .toast-content {
        display: flex; align-items: center; justify-content: center; width: 100%;
      }
      #${TOAST_ID} .lol-uikit-dialog-frame {
        position: relative; display: inline-block; border: none;
        background: #010a13; box-shadow: 0 0 0 1px rgba(1,10,19,.48);
      }
      #${TOAST_ID} .lol-uikit-dialog-frame::before {
        content: ""; position: absolute; width: calc(100% + 4px); height: calc(100% + 4px);
        top: -2px; left: -2px; box-shadow: 0 0 10px 1px rgba(0,0,0,.5);
        pointer-events: none;
      }
      #${TOAST_ID} lol-uikit-content-block {
        display: inline-block; position: relative; box-sizing: border-box;
        width: auto; padding-left: 25px; padding-right: 25px;
        background: transparent; text-align: center;
        font-family: "LoL Body",Arial,"Helvetica Neue",Helvetica,sans-serif;
      }
      #${TOAST_ID} .rose-jade-historic-text {
        margin: 0; color: #b2a580; font-size: 14px; line-height: 1.4;
        letter-spacing: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
      }
      #${TOAST_ID} .lol-uikit-dialog-frame-sub-border::before,
      #${TOAST_ID} .lol-uikit-dialog-frame-sub-border::after {
        content: ""; position: absolute; display: flex; box-sizing: border-box;
        left: 12px; width: calc(100% - 24px); height: 0;
        border-width: 4px 4px 0 4px; border-image-width: 4px 4px 0 4px;
        border-image-slice: 4 4 0 4; border-image-repeat: stretch; border-style: solid;
      }
      #${TOAST_ID} .lol-uikit-dialog-frame-sub-border::before {
        top: -6px; border-image-source: url("/fe/lol-uikit/images/sub-border-primary-horizontal.png");
        transform: rotate(180deg);
      }
      #${TOAST_ID} .lol-uikit-dialog-frame-sub-border::after {
        bottom: -6px; border-image-source: url("/fe/lol-uikit/images/sub-border-secondary-horizontal.png");
        transform: rotate(180deg);
      }
      #${TOAST_ID} .lol-uikit-dialog-frame-toast-close-button {
        position: absolute; top: 2px; right: 2px; width: 16px; height: 16px;
        padding: 0; border: 0; border-radius: 50%; cursor: pointer; pointer-events: auto;
        background: url("/fe/lol-uikit/images/close.png"), rgba(0,0,0,.7);
        background-size: 70% 70%, 100% 100%; background-position: center;
        background-repeat: no-repeat; z-index: 10;
      }
      #${TOAST_ID} .lol-uikit-dialog-frame-toast-close-button:hover {
        background: url("/fe/lol-uikit/images/close.png"), rgba(200,50,50,.8);
        background-size: 70% 70%, 100% 100%; background-position: center;
        background-repeat: no-repeat;
      }
    `;
    document.head.appendChild(style);
  }

  function handlePhaseChange(data) {
    const phase = String(data?.phase || "");
    const classicMode =
      Number(data?.mapId) === 453 ||
      Number(data?.queueId) === 3260 ||
      String(data?.gameMode || "").toUpperCase() === "JADE";
    isInJadeChampSelect =
      classicMode && (phase === "ChampSelect" || phase === "FINALIZATION");
    if (!isInJadeChampSelect) {
      presentationReady = false;
      cleanup();
    }
    else render();
  }

  function handleWheelLayout(event) {
    if (event?.detail?.active === false) {
      presentationReady = false;
      cleanup();
      return;
    }
    render();
  }

  async function start() {
    while (!window.__roseBridge) {
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    bridge = window.__roseBridge;
    injectStyles();
    bridge.subscribe("historic-state", (data) => {
      const nextActive = data?.active === true;
      const nextSkinName = String(data?.historicSkinName || "");
      if (!nextActive || nextSkinName !== skinName) presentationReady = false;
      active = nextActive;
      skinName = nextSkinName;
      log("info", "Historic state updated", { active, skinName, randomModeActive });
      render();
    });
    bridge.subscribe("random-mode-state", (data) => {
      randomModeActive = data?.active === true;
      log("info", "Random state observed", { active: randomModeActive });
      render();
    });
    bridge.subscribe("custom-mod-state", (data) => {
      customModActive = data?.active === true;
      customModName = customModActive ? String(data?.modName || "") : "";
      customModTargetSkinIds = new Set(
        (Array.isArray(data?.targetSkinIds) ? data.targetSkinIds : [])
          .map(Number)
          .filter((value) => Number.isFinite(value) && value > 0)
      );
      const directSkinId = Number(data?.skinId);
      if (Number.isFinite(directSkinId) && directSkinId > 0) {
        customModTargetSkinIds.add(directSkinId);
      }
      render();
    });
    bridge.subscribe("local-asset-url", (data) => {
      if (data?.assetPath !== ASSET) return;
      imageUrl = String(data.url || "").replace("localhost", "127.0.0.1");
      render();
    });
    window.addEventListener("rose-jade-historic-presentation", (event) => {
      skinName = String(event?.detail?.skinName || skinName);
      presentationReady = true;
      render();
    });
    window.addEventListener("rose-jade-historic-presentation-state", (event) => {
      presentationReady = event?.detail?.ready === true;
      render();
    });
    window.addEventListener("rose-classic-selection-change", render);
    bridge.subscribe("phase-change", handlePhaseChange);
    const classicState = window.__roseClassicWheelApi?.state?.();
    if (classicState) handlePhaseChange(classicState);
    window.addEventListener("rose-jade-wheel-layout", handleWheelLayout);
    bridge.onReady(() => bridge.send({ type: "request-local-asset", assetPath: ASSET }));
    bridge.send({ type: "request-local-asset", assetPath: ASSET });
    log("info", "Classic historic plugin initialized");
    new MutationObserver(render).observe(document.body, { childList: true, subtree: true });
  }

  start();
})();
