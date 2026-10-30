(function createSkinCarrierSelector() {
  // Picks the owned skin (or chroma) an injected skin runs as. Without one, Rose plays the injected skin on the
  // champion's default skin; with one, the others in the game see the owned skin and the player sees the injected
  // one. Rose answers which skins can carry the hovered one (injection/retarget).
  const LOG_PREFIX = "[ROSE-SkinCarrier]";
  const BUTTON_CLASS = "lu-skin-carrier-button";
  const BUTTON_SELECTOR = `.${BUTTON_CLASS}`;
  const PANEL_CLASS = "lu-skin-carrier-panel";
  const PANEL_ID = "lu-skin-carrier-panel-container";
  const EVENT_SKIN_STATE = "lu-skin-monitor-state";
  // A request Rose hasn't answered within this is asked again
  const REQUEST_PENDING_MS = 3000;

  // Rose's menu language (ROSE-I18n); English until it has loaded
  const t = (text, vars) =>
    window.RoseI18n
      ? window.RoseI18n.t(text, vars)
      : text.replace(/\{(\w+)\}/g, (m, k) => (vars && k in vars ? String(vars[k]) : m));

  let bridge = null;
  let skinMonitorState = null;
  // Rose's chroma panel: the chroma (or form) picked on the hovered skin
  let chromaState = null;
  let championLocked = false;
  let initialized = false;
  // Rose's answer for the hovered skin: { championId, skinId, applicable, carrierId, options }
  let carrierInfo = null;
  let requestCounter = 0;
  let pendingRequestId = null;
  let pendingRequestKey = null;
  let pendingRequestAt = 0;
  let pendingSelection = null;
  let panel = null;
  let panelButtonRef = null;

  function logInfo(message, extra) {
    console.log(`${LOG_PREFIX} ${message}`, extra ?? "");
  }

  // Into Rose's log, like the other plugins: what was asked and answered
  function emitBridgeLog(event, data = {}) {
    try {
      if (bridge) bridge.send({ type: "plugin-log", source: "SkinCarrier", event, data, timestamp: Date.now() });
    } catch (error) {
      console.debug(`${LOG_PREFIX} Failed to emit bridge log`, error);
    }
  }

  function waitForBridge() {
    return new Promise((resolve, reject) => {
      const timeout = 10000;
      const interval = 50;
      let elapsed = 0;

      const check = () => {
        if (window.__roseBridge) {
          resolve(window.__roseBridge);
          return;
        }
        elapsed += interval;
        if (elapsed >= timeout) {
          reject(new Error("Bridge not available"));
          return;
        }
        setTimeout(check, interval);
      };

      check();
    });
  }

  function createRequestId() {
    requestCounter += 1;
    return `${LOG_PREFIX}-${Date.now()}-${requestCounter}`;
  }

  // The hovered skin, and the chroma (or form) picked in Rose's wheel. Rose tells whether the chroma is one of the
  // skin's: an unowned chroma is injected even when its skin is owned.
  function getCurrentSkin() {
    const championId = Number(skinMonitorState?.championId);
    const skinId = Number(skinMonitorState?.skinId);
    const chromaId = Number(chromaState?.selectedChromaId);
    const validChampion = Number.isFinite(championId) && championId > 0 ? championId : null;
    return {
      championId: validChampion,
      skinId: Number.isFinite(skinId) && skinId > 0 ? skinId : null,
      chromaId: Number.isFinite(chromaId) && chromaId > 0 && Math.floor(chromaId / 1000) === validChampion
        ? chromaId : null,
      skinName: String(skinMonitorState?.name || ""),
    };
  }

  function infoMatchesCurrentSkin() {
    const { championId, skinId, chromaId } = getCurrentSkin();
    return Boolean(carrierInfo) && carrierInfo.skinId === skinId && carrierInfo.chromaId === chromaId
      && carrierInfo.championId === championId;
  }

  function usableOptions() {
    return infoMatchesCurrentSkin() && carrierInfo.applicable ? carrierInfo.options : [];
  }

  function savedCarrier() {
    if (!infoMatchesCurrentSkin() || !carrierInfo.carrierId) return null;
    return carrierInfo.options.find((option) => option.id === carrierInfo.carrierId) || null;
  }

  function tileUrl(option) {
    return (option.chroma ? option.chromaPath : option.tilePath) || "";
  }

  function swatch(colors) {
    const list = (Array.isArray(colors) ? colors : []).filter(Boolean);
    if (!list.length) return "#1e2328";
    if (list.length === 1) return list[0];
    return `linear-gradient(135deg, ${list[0]} 0, ${list[0]} 50%, ${list[1]} 50%, ${list[1]} 100%)`;
  }

  // ─── Rose ────────────────────────────────────────────────────────────

  function requestCarrierInfo(force = false) {
    const { championId, skinId, chromaId } = getCurrentSkin();
    if (!bridge || !championLocked || !championId || !skinId) {
      carrierInfo = null;
      scanSkinSelection();
      return;
    }
    if (carrierInfo && !infoMatchesCurrentSkin()) {
      carrierInfo = null;
      scanSkinSelection();
    }
    // Rose checks every owned skin against the hovered one: don't ask again while it is answering for this skin
    const key = `${championId}:${skinId}:${chromaId}`;
    if (!force && pendingRequestKey === key && Date.now() - pendingRequestAt < REQUEST_PENDING_MS) return;
    pendingRequestKey = key;
    pendingRequestAt = Date.now();
    pendingRequestId = createRequestId();
    emitBridgeLog("request", { championId, skinId, chromaId });
    bridge.send({ type: "request-skin-carrier", championId, skinId, chromaId, requestId: pendingRequestId });
  }

  function handleCarrierResponse(data) {
    if (!data || data.type !== "skin-carrier-response") return;
    if (pendingRequestId && data.requestId && data.requestId !== pendingRequestId) return;
    const { championId, skinId, chromaId } = getCurrentSkin();
    if (Number(data.skinId) !== skinId || (Number(data.chromaId) || null) !== chromaId
        || Number(data.championId) !== championId) return;

    pendingRequestKey = null;
    emitBridgeLog("response", {
      askedSkinId: data.askedSkinId, applicable: data.applicable, options: (data.options || []).length,
    });
    carrierInfo = {
      championId,
      skinId,
      chromaId,
      applicable: Boolean(data.applicable),
      carrierId: Number(data.carrierId) || null,
      baseTilePath: data.baseTilePath || null,
      options: (Array.isArray(data.options) ? data.options : []).map((option) => ({
        ...option,
        id: Number(option.id),
        parentId: Number(option.parentId) || null,
      })),
    };
    scanSkinSelection();
  }

  function sendSelection(carrierId) {
    const { championId, skinId, chromaId } = getCurrentSkin();
    if (!bridge || !championId || !skinId) return;
    pendingSelection = createRequestId();
    emitBridgeLog("select", { skinId, chromaId, carrierId });
    bridge.send({ type: "select-skin-carrier", championId, skinId, carrierId, requestId: pendingSelection });
  }

  function handleSelectionResult(data) {
    if (!data || data.type !== "skin-carrier-selection-result") return;
    if (pendingSelection && data.requestId && data.requestId !== pendingSelection) return;
    pendingSelection = null;
    if (!data.success) {
      console.warn(`${LOG_PREFIX} Could not save the skin carrier: ${data.error || "unknown error"}`);
      // The row picked was shown right away: ask Rose what is really saved
      requestCarrierInfo(true);
      return;
    }
    if (carrierInfo && Number(data.skinId) === carrierInfo.skinId) {
      carrierInfo.carrierId = Number(data.carrierId) || null;
    }
    scanSkinSelection();
  }

  // ─── Button ──────────────────────────────────────────────────────────

  function injectCSS() {
    const styleId = "lu-skin-carrier-style";
    if (document.getElementById(styleId)) return;
    const btn = BUTTON_CLASS;
    const pnl = PANEL_CLASS;
    const styleTag = document.createElement("style");
    styleTag.id = styleId;
    styleTag.textContent = `
.${btn} {
  pointer-events: auto; -webkit-user-select: none; cursor: pointer; position: absolute;
  top: 6px; right: 6px; width: 28px; height: 28px; z-index: 10; direction: ltr;
}
.${btn}[data-hidden] { display: none !important; }
.${btn} .frame {
  box-sizing: border-box; width: 100%; height: 100%; padding: 2px; border-radius: 50%;
  background-image: linear-gradient(0deg,#695625 0,#a9852d 23%,#b88d35 93%,#c8aa6e);
  box-shadow: 0 0 4px 1px rgba(1,10,19,.5);
}
.${btn}[data-active] .frame { box-shadow: 0 0 6px 2px #c89b3c; }
.${btn} .content {
  box-sizing: border-box; width: 100%; height: 100%; border-radius: 50%; border: 2px solid #010a13;
  background-color: #1e2328; background-size: cover; background-position: center;
  display: flex; align-items: center; justify-content: center;
}
.${btn} .content svg { width: 14px; height: 14px; fill: #c8aa6e; }
.${btn}[data-active] .content svg { display: none; }
.thumbnail-wrapper.active-skin, .skin-selection-item { position: relative; }
.${pnl} { position: fixed; inset: 0; z-index: 10000; pointer-events: none; }
.${pnl} .carrier-flyout {
  position: absolute; width: 280px; max-height: 360px; display: flex; flex-direction: column;
  pointer-events: all; background: #010a13; border: 2px solid transparent;
  border-image: linear-gradient(to top,#785a28 0,#463714 50%,#463714 100%) 1 stretch;
  box-shadow: 0 0 0 1px rgba(1,10,19,.48), 0 4px 16px rgba(0,0,0,.6);
}
.${pnl} .carrier-title {
  padding: 10px 12px 4px; color: #f0e6d2; font-family: "LoL Display","Times New Roman",serif;
  font-size: 14px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase;
}
.${pnl} .carrier-hint { padding: 0 12px 8px; color: #a09b8c; font-size: 11px; line-height: 1.35; }
.${pnl} .carrier-list { overflow-y: auto; padding: 0 6px 6px; border-top: thin solid #463714; }
.${pnl} .carrier-row {
  display: flex; align-items: center; gap: 8px; padding: 5px 6px; margin-top: 4px; cursor: pointer;
  color: #cdbe91; font-size: 12px; border: 1px solid transparent;
}
.${pnl} .carrier-row:hover { background: rgba(200,155,60,.12); color: #f0e6d2; }
.${pnl} .carrier-row.selected { border-color: #c89b3c; color: #f0e6d2; }
.${pnl} .carrier-row.chroma { padding-left: 22px; }
.${pnl} .carrier-row.unavailable { opacity: .4; cursor: default; }
.${pnl} .carrier-row.unavailable:hover { background: none; color: #cdbe91; }
.${pnl} .carrier-tile {
  flex: 0 0 32px; width: 32px; height: 32px; background-color: #1e2328;
  background-size: cover; background-position: center; border: 1px solid #463714;
}
.${pnl} .carrier-row.chroma .carrier-tile { flex-basis: 20px; width: 20px; height: 20px; border-radius: 50%; }
.${pnl} .carrier-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
`;
    document.head.appendChild(styleTag);
  }

  function isCurrentSkinItem(skinItem) {
    if (skinItem.classList.contains("skin-selection-item")) {
      if (
        skinItem.classList.contains("active-skin") ||
        skinItem.classList.contains("selected") ||
        skinItem.getAttribute("aria-selected") === "true"
      ) {
        return true;
      }
      const offset = skinItem.className.match(/skin-carousel-offset-(\d+)/)
        || skinItem.querySelector("[class*='skin-carousel-offset-']")?.className.match(/skin-carousel-offset-(\d+)/);
      return Boolean(offset) && Number(offset[1]) === 2;
    }
    return (
      skinItem.classList.contains("active-skin") ||
      skinItem.classList.contains("selected") ||
      skinItem.getAttribute("aria-selected") === "true"
    );
  }

  function createButton() {
    const button = document.createElement("div");
    button.className = BUTTON_CLASS;
    const frame = document.createElement("div");
    frame.className = "frame";
    const content = document.createElement("div");
    content.className = "content";
    // two arrows: the skin swaps onto another one
    content.innerHTML =
      '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 3h7V1l4 3-4 3V5H4zM12 13H5v2l-4-3 4-3v2h7z"/></svg>';
    frame.appendChild(content);
    button.appendChild(frame);

    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      togglePanel(button);
    });
    button.addEventListener("mousedown", (event) => event.stopPropagation());
    return button;
  }

  function updateButton(button) {
    const options = usableOptions();
    if (!options.length) {
      button.setAttribute("data-hidden", "true");
      if (panelButtonRef === button) closePanel();
      return;
    }
    button.removeAttribute("data-hidden");
    const carrier = savedCarrier();
    const content = button.querySelector(".content");
    content.style.background = "";
    if (carrier) {
      button.setAttribute("data-active", "true");
      button.title = t("Plays as {name}", { name: carrier.name });
      if (tileUrl(carrier)) content.style.backgroundImage = `url('${tileUrl(carrier)}')`;
      else content.style.background = swatch(carrier.colors);
    } else {
      button.removeAttribute("data-active");
      button.title = t("Choose the owned skin this skin plays as");
    }
  }

  function ensureButtonOnItem(skinItem) {
    // Some League builds nest the thumbnail wrapper inside the selection item: one button per item
    if (skinItem.classList.contains("thumbnail-wrapper")) {
      const parentItem = skinItem.closest(".skin-selection-item");
      if (parentItem && Array.from(parentItem.children).some((child) => child.matches(BUTTON_SELECTOR))) {
        return;
      }
    }
    let button = skinItem.querySelector(`:scope > ${BUTTON_SELECTOR}`);
    if (!championLocked || !isCurrentSkinItem(skinItem)) {
      if (button) button.remove();
      return;
    }
    if (!button) {
      button = createButton();
      skinItem.appendChild(button);
    }
    updateButton(button);
  }

  function scanSkinSelection() {
    const skinItems = document.querySelectorAll(".skin-selection-item, .thumbnail-wrapper");
    if (!skinItems.length) {
      document.querySelectorAll(BUTTON_SELECTOR).forEach((node) => node.remove());
      closePanel();
      return;
    }
    skinItems.forEach(ensureButtonOnItem);
    if (panelButtonRef && (!panelButtonRef.isConnected || panelButtonRef.hasAttribute("data-hidden"))) closePanel();
  }

  // ─── Panel ───────────────────────────────────────────────────────────

  function createRow(option) {
    const row = document.createElement("div");
    const selected = option
      ? carrierInfo.carrierId === option.id
      : !savedCarrier();
    const unavailable = option && option.unavailableReason;
    row.className = [
      "carrier-row",
      option?.chroma ? "chroma" : "",
      selected ? "selected" : "",
      unavailable ? "unavailable" : "",
    ].filter(Boolean).join(" ");

    const tile = document.createElement("div");
    tile.className = "carrier-tile";
    const url = option ? tileUrl(option) : carrierInfo.baseTilePath;
    if (url) tile.style.backgroundImage = `url('${url}')`;
    else if (option?.chroma) tile.style.background = swatch(option.colors);

    const name = document.createElement("div");
    name.className = "carrier-name";
    name.textContent = option ? option.name : t("Base Skin");

    row.appendChild(tile);
    row.appendChild(name);
    if (unavailable) {
      // Rose's reason is technical, and stays in English under the translated sentence
      row.title = `${t("This skin can't carry the hovered one")}\n${option.unavailableReason}`;
    } else {
      row.title = option ? option.name : t("Base Skin");
      row.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        sendSelection(option ? option.id : null);
        if (carrierInfo) carrierInfo.carrierId = option ? option.id : null;
        closePanel();
        scanSkinSelection();
      });
    }
    return row;
  }

  function buildPanel() {
    const root = document.createElement("div");
    root.id = PANEL_ID;
    root.className = PANEL_CLASS;

    const flyout = document.createElement("div");
    flyout.className = "carrier-flyout";

    const title = document.createElement("div");
    title.className = "carrier-title";
    title.textContent = t("Play this skin as");
    const hint = document.createElement("div");
    hint.className = "carrier-hint";
    hint.textContent = t("Others in the game see the skin you own, you see this one.");

    const list = document.createElement("div");
    list.className = "carrier-list";
    list.appendChild(createRow(null));
    usableOptions().forEach((option) => list.appendChild(createRow(option)));

    flyout.appendChild(title);
    flyout.appendChild(hint);
    flyout.appendChild(list);
    root.appendChild(flyout);
    return root;
  }

  function positionPanel() {
    if (!panel || !panelButtonRef) return;
    const flyout = panel.querySelector(".carrier-flyout");
    const rect = panelButtonRef.getBoundingClientRect();
    const box = flyout.getBoundingClientRect();
    const width = box.width || 280;
    const height = box.height || 360;
    flyout.style.left = `${Math.max(10, Math.min(rect.left + rect.width / 2 - width / 2, window.innerWidth - width - 10))}px`;
    flyout.style.top = `${Math.max(10, rect.top - height - 10)}px`;
  }

  function closePanel() {
    const existing = document.getElementById(PANEL_ID);
    if (existing) existing.remove();
    panel = null;
    panelButtonRef = null;
  }

  function togglePanel(button) {
    if (panel && panelButtonRef === button) {
      closePanel();
      return;
    }
    closePanel();
    if (!usableOptions().length) return;
    panel = buildPanel();
    panelButtonRef = button;
    document.body.appendChild(panel);
    positionPanel();

    setTimeout(() => {
      document.addEventListener("click", function outside(event) {
        if (!panel) {
          document.removeEventListener("click", outside);
          return;
        }
        if (panel.contains(event.target) || button.contains(event.target)) return;
        closePanel();
        document.removeEventListener("click", outside);
      });
    }, 100);
  }

  // ─── Wiring ──────────────────────────────────────────────────────────

  function handleSkinState(event) {
    const detail = event?.detail;
    if (!detail) return;
    const previous = getCurrentSkin();
    skinMonitorState = detail;
    const current = getCurrentSkin();
    if (previous.skinId !== current.skinId || previous.championId !== current.championId || !carrierInfo) {
      closePanel();
      requestCarrierInfo();
    }
    scanSkinSelection();
  }

  function resetSession() {
    skinMonitorState = null;
    chromaState = null;
    carrierInfo = null;
    pendingRequestId = null;
    pendingRequestKey = null;
    pendingSelection = null;
    closePanel();
  }

  async function init() {
    if (initialized) return;
    initialized = true;
    injectCSS();

    try {
      bridge = await waitForBridge();
      logInfo("Bridge connected");
    } catch (error) {
      console.error(`${LOG_PREFIX} Bridge connection failed`, error);
      return;
    }

    if (window.__roseSkinState) skinMonitorState = window.__roseSkinState;

    bridge.subscribe("skin-carrier-response", handleCarrierResponse);
    bridge.subscribe("skin-carrier-selection-result", handleSelectionResult);
    bridge.subscribe("champion-locked", (data) => {
      championLocked = Boolean(data?.locked);
      if (championLocked) requestCarrierInfo();
      else {
        carrierInfo = null;
        closePanel();
      }
      scanSkinSelection();
    });
    // A custom mod picked on the default skin makes it an injected skin, which a carrier can then take
    bridge.subscribe("custom-mod-state", () => requestCarrierInfo(true));
    bridge.subscribe("chroma-state", (data) => {
      const before = getCurrentSkin().skinId;
      const beforeChroma = getCurrentSkin().chromaId;
      chromaState = data && typeof data === "object" ? data : null;
      if (getCurrentSkin().skinId !== before || getCurrentSkin().chromaId !== beforeChroma) {
        closePanel();
        requestCarrierInfo();
      }
      scanSkinSelection();
    });
    // The owned skins are known once champ select has started
    bridge.subscribe("phase-change", (data) => {
      if (String(data?.phase || "") !== "ChampSelect") resetSession();
    });
    bridge.onReady(() => requestCarrierInfo(true));

    window.addEventListener(EVENT_SKIN_STATE, handleSkinState, { passive: true });
    window.addEventListener("resize", positionPanel);

    const observer = new MutationObserver(() => scanSkinSelection());
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["class", "aria-selected"] });
    setInterval(scanSkinSelection, 500);

    requestCarrierInfo();
    scanSkinSelection();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
