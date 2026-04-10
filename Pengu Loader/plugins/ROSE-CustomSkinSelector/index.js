/**
 * @name ROSE-CustomSkinSelector
 * @author Rose Team & aflons
 * @description ChromaWheel-style selector for custom skin mods
 */
(function createCustomSkinSelector() {
  const LOG_PREFIX = "[ROSE-CustomSkinSelector]";
  const BUTTON_CLASS = "lu-custom-skin-button";
  const BUTTON_SELECTOR = `.${BUTTON_CLASS}`;
  const PANEL_CLASS = "lu-custom-skin-panel";
  const PANEL_ID = "lu-custom-skin-panel-container";
  const EVENT_SKIN_STATE = "lu-skin-monitor-state";
  const REQUEST_TYPE = "request-skin-mods";
  const BUTTON_ICON_ASSET_PATH = "button-skin.png";

  let bridge = null;
  let skinMonitorState = null;
  let championLocked = false;
  let initialized = false;
  let selectedModId = null;
  let selectedModSkinId = null;
  let modsForCurrentSkin = [];
  let panel = null;
  let panelButtonRef = null;
  let panelSkinItemRef = null;
  let customButtonIconUrl = null;

  function logInfo(message, extra) {
    console.log(`${LOG_PREFIX} ${message}`, extra ?? "");
  }

  function applyCustomButtonIcon() {
    if (!customButtonIconUrl) return;

    document.querySelectorAll(`${BUTTON_SELECTOR} .content`).forEach((content) => {
      content.style.backgroundImage = `url('${customButtonIconUrl}')`;
      content.style.backgroundRepeat = "no-repeat";
      content.style.backgroundPosition = "center";
      content.style.backgroundSize = "contain";
    });
  }

  function handleLocalAssetUrl(data) {
    const assetPath = String(data?.assetPath || "").trim();
    if (assetPath !== BUTTON_ICON_ASSET_PATH) return;

    const url = typeof data?.url === "string" ? data.url.replace("localhost", "127.0.0.1") : "";
    if (!url) return;

    customButtonIconUrl = url;
    applyCustomButtonIcon();
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

  function getSkinOffset(skinItem) {
    if (!skinItem) return null;
    const directMatch = skinItem.className.match(/skin-carousel-offset-(\d+)/);
    if (directMatch) return Number(directMatch[1]);
    const nested = skinItem.querySelector("[class*='skin-carousel-offset-']");
    if (!nested) return null;
    const nestedMatch = nested.className.match(/skin-carousel-offset-(\d+)/);
    return nestedMatch ? Number(nestedMatch[1]) : null;
  }

  function isCurrentSkinItem(skinItem) {
    if (!skinItem) return false;

    if (skinItem.classList.contains("skin-selection-item")) {
      return getSkinOffset(skinItem) === 2;
    }

    if (skinItem.classList.contains("thumbnail-wrapper")) {
      return (
        skinItem.classList.contains("active-skin") ||
        skinItem.classList.contains("selected") ||
        skinItem.getAttribute("aria-selected") === "true"
      );
    }

    return false;
  }

  function getSkinIdFromItem(skinItem) {
    if (!skinItem) return null;

    const candidates = [
      skinItem.dataset?.skinId,
      skinItem.dataset?.id,
      skinItem.getAttribute("data-skin-id"),
      skinItem.getAttribute("data-id"),
    ];

    for (const candidate of candidates) {
      const parsed = Number(candidate);
      if (Number.isFinite(parsed) && parsed > 0) {
        return parsed;
      }
    }

    return null;
  }

  function doesSkinItemMatchSkinState(skinItem) {
    const currentSkinId = Number(skinMonitorState?.skinId);
    if (!Number.isFinite(currentSkinId) || currentSkinId <= 0) {
      return true;
    }

    const itemSkinId = getSkinIdFromItem(skinItem);
    if (!Number.isFinite(itemSkinId) || itemSkinId <= 0) {
      return true;
    }

    return itemSkinId === currentSkinId;
  }

  function normalizeModId(mod) {
    return String(mod?.relativePath || mod?.modName || "");
  }

  function getCurrentSkinContext() {
    const championId = Number(skinMonitorState?.championId);
    const skinId = Number(skinMonitorState?.skinId);

    return {
      championId: Number.isFinite(championId) ? championId : null,
      skinId: Number.isFinite(skinId) ? skinId : null,
      skinName: String(skinMonitorState?.name || "Unknown Skin"),
    };
  }

  function injectCSS() {
    const styleId = "lu-custom-skin-selector-style";
    if (document.getElementById(styleId)) return;

    const styleTag = document.createElement("style");
    styleTag.id = styleId;
    styleTag.textContent = `
      .${BUTTON_CLASS} {
        pointer-events: auto;
        -webkit-user-select: none;
        list-style-type: none;
        cursor: pointer;
        display: block !important;
        bottom: 1px;
        height: 25px;
        left: 50%;
        position: absolute;
        transform: translateX(-50%) translateY(-205%);
        width: 25px;
        z-index: 10;
        direction: ltr;
      }

      .${BUTTON_CLASS}[data-hidden],
      .${BUTTON_CLASS}[data-hidden] * {
        pointer-events: none !important;
        cursor: default !important;
        visibility: hidden !important;
      }

      .${BUTTON_CLASS} .outer-mask {
        pointer-events: auto;
        cursor: pointer;
        border-radius: 50%;
        box-shadow: 0 0 4px 1px rgba(1, 10, 19, .25);
        box-sizing: border-box;
        height: 100%;
        overflow: hidden;
        position: relative;
      }

      .${BUTTON_CLASS} .frame-color {
        pointer-events: auto;
        cursor: default;
        background-image: linear-gradient(0deg, #695625 0, #a9852d 23%, #b88d35 93%, #c8aa6e);
        box-sizing: border-box;
        height: 100%;
        overflow: hidden;
        width: 100%;
        padding: 2px;
      }

      .${BUTTON_CLASS} .content {
        pointer-events: auto;
        cursor: pointer;
        display: block;
        background-color: #1e2328;
        background-repeat: no-repeat;
        background-position: center;
        background-size: contain;
        border: 2px solid #010a13;
        border-radius: 50%;
        height: 16px;
        margin: 1px;
        width: 16px;
      }

      .${BUTTON_CLASS} .inner-mask {
        cursor: default;
        border-radius: 50%;
        box-sizing: border-box;
        overflow: hidden;
        pointer-events: none;
        position: absolute;
        box-shadow: inset 0 0 4px 4px rgba(0,0,0,.75);
        width: calc(100% - 4px);
        height: calc(100% - 4px);
        left: 2px;
        top: 2px;
      }

      .thumbnail-wrapper.active-skin,
      .skin-selection-item {
        position: relative;
      }

      .thumbnail-wrapper .${BUTTON_CLASS} {
        direction: ltr;
        background: transparent;
        cursor: pointer;
        height: 28px;
        width: 28px;
        bottom: 1px;
        left: 50%;
        position: absolute;
        transform: translateX(-50%) translateY(-205%);
        z-index: 10;
      }

      .thumbnail-wrapper .${BUTTON_CLASS} .outer-mask {
        display: block;
      }

      .thumbnail-wrapper .${BUTTON_CLASS} .content {
        transform: translate(1px, 1px);
      }

      .${PANEL_CLASS} {
        position: fixed;
        z-index: 10000;
        pointer-events: all;
        -webkit-user-select: none;
      }

      .${PANEL_CLASS}[data-no-button] {
        pointer-events: none;
        cursor: default !important;
      }

      .${PANEL_CLASS}[data-no-button] * {
        pointer-events: none !important;
        cursor: default !important;
      }

      .${PANEL_CLASS} .flyout {
        position: absolute;
        overflow: visible;
        pointer-events: all;
        -webkit-user-select: none;
      }

      .${PANEL_CLASS}[data-no-button] .flyout {
        pointer-events: none !important;
        cursor: default !important;
      }

      .${PANEL_CLASS} .flyout-frame {
        position: relative;
        transition: 250ms all cubic-bezier(0.02, 0.85, 0.08, 0.99);
      }

      .${PANEL_CLASS} .flyout .caret,
      .${PANEL_CLASS} .flyout [class*="caret"],
      .${PANEL_CLASS} lol-uikit-flyout-frame .caret,
      .${PANEL_CLASS} lol-uikit-flyout-frame [class*="caret"],
      .${PANEL_CLASS} .flyout::part(caret),
      .${PANEL_CLASS} lol-uikit-flyout-frame::part(caret) {
        z-index: 3 !important;
        position: relative;
      }

      .${PANEL_CLASS} .chroma-modal {
        background: #000;
        display: flex;
        flex-direction: column;
        width: 305px;
        position: relative;
        z-index: 0;
      }

      .${PANEL_CLASS} .chroma-modal.chroma-view {
        min-height: 355px;
        max-height: 420px;
      }

      .${PANEL_CLASS} .border {
        position: absolute;
        top: 0;
        left: 0;
        box-sizing: border-box;
        background-color: transparent;
        box-shadow: 0 0 0 1px rgba(1,10,19,0.48);
        transition: 250ms all cubic-bezier(0.02, 0.85, 0.08, 0.99);
        border-top: 2px solid transparent;
        border-left: 2px solid transparent;
        border-right: 2px solid transparent;
        border-bottom: none;
        border-image: linear-gradient(to top, #785a28 0, #463714 50%, #463714 100%) 1 stretch;
        border-image-slice: 1 1 0 1;
        width: 100%;
        height: 100%;
        visibility: visible;
        z-index: 2;
        pointer-events: none;
      }

      .${PANEL_CLASS} .lc-flyout-content {
        position: relative;
      }

      .${PANEL_CLASS} .chroma-information {
        background-image: url('lol-game-data/assets/content/src/LeagueClient/GameModeAssets/Classic_SRU/img/champ-select-flyout-background.jpg');
        background-size: cover;
        border-bottom: thin solid #463714;
        flex-grow: 1;
        height: 315px;
        position: relative;
        width: 100%;
        z-index: 1;
      }

      .${PANEL_CLASS} .chroma-information-image {
        bottom: 0;
        left: 0;
        position: absolute;
        right: 0;
        top: 0;
        background-size: contain;
        background-position: center;
        background-repeat: no-repeat;
      }

      .${PANEL_CLASS} .child-skin-name {
        bottom: 10px;
        color: #f7f0de;
        font-family: "LoL Display", "Times New Roman", Times, Baskerville, Georgia, serif;
        font-size: 24px;
        font-weight: 700;
        position: absolute;
        text-align: center;
        width: 100%;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      .${PANEL_CLASS} .chroma-selection {
        pointer-events: all;
        height: 100%;
        overflow: auto;
        transform: translateZ(0);
        -webkit-mask-box-image-source: url("/fe/lol-static-assets/images/uikit/scrollable/scrollable-content-gradient-mask-bottom.png");
        -webkit-mask-box-image-slice: 0 8 18 0 fill;
        align-items: center;
        display: flex;
        flex-direction: row;
        flex-grow: 0;
        flex-wrap: wrap;
        justify-content: center;
        max-height: 92px;
        min-height: 40px;
        padding: 7px 0;
        width: 100%;
        position: relative;
        z-index: 1;
      }

      .${PANEL_CLASS}[data-no-button] .chroma-selection {
        pointer-events: none;
        cursor: default;
      }

      .${PANEL_CLASS} .chroma-selection ul {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-wrap: wrap;
        justify-content: center;
      }

      .${PANEL_CLASS} .chroma-selection li {
        list-style: none;
        margin: 2px 4px;
        padding: 0;
        display: flex;
        align-items: center;
        justify-content: center;
      }

      .${PANEL_CLASS} .chroma-skin-button {
        pointer-events: all;
        align-items: center;
        border-radius: 50%;
        box-shadow: 0 0 2px #010a13;
        border: none;
        display: flex;
        height: 26px;
        width: 26px;
        min-width: 26px;
        min-height: 26px;
        max-width: 26px;
        max-height: 26px;
        aspect-ratio: 1 / 1;
        justify-content: center;
        margin: 0;
        padding: 0;
        cursor: pointer;
        box-sizing: border-box;
        background: transparent !important;
        background-color: transparent !important;
        flex: 0 0 26px;
        transform: scale(1);
      }

      .${PANEL_CLASS}[data-no-button] .chroma-skin-button {
        pointer-events: none !important;
        cursor: default !important;
      }

      .${PANEL_CLASS} .chroma-skin-button:not(.locked) {
        cursor: pointer;
        opacity: 1 !important;
      }

      .${PANEL_CLASS} .chroma-skin-button.locked {
        opacity: 1 !important;
        cursor: pointer;
      }

      .${PANEL_CLASS} .chroma-skin-button .contents {
        pointer-events: all;
        align-items: center;
        border: 2px solid #010a13;
        border-radius: 50%;
        display: flex;
        height: 18px;
        width: 18px;
        min-width: 18px;
        min-height: 18px;
        max-width: 18px;
        max-height: 18px;
        aspect-ratio: 1 / 1;
        justify-content: center;
        background: linear-gradient(135deg, #27211C 0%, #27211C 50%, #27211C 50%, #27211C 100%);
        box-shadow: 0 0 0 2px transparent;
        background-size: cover;
        background-position: center;
        background-repeat: no-repeat;
        background-color: #1e2328;
        transform: scale(1);
      }

      .${PANEL_CLASS} .chroma-skin-button.selected .contents,
      .${PANEL_CLASS} .chroma-skin-button:hover .contents {
        box-shadow: 0 0 0 2px #c89b3c;
        transform: scale(1);
      }

      .${PANEL_CLASS} .chroma-skin-button.locked:hover:not([purchase-disabled]) {
        opacity: 1 !important;
      }

      .${PANEL_CLASS} .chroma-skin-button.locked.purchase-disabled {
        opacity: 1 !important;
        pointer-events: none;
      }
    `;

    document.head.appendChild(styleTag);
  }

  function createFakeButton() {
    const button = document.createElement("div");
    button.className = BUTTON_CLASS;

    const outerMask = document.createElement("div");
    outerMask.className = "outer-mask interactive";

    const frameColor = document.createElement("div");
    frameColor.className = "frame-color";

    const content = document.createElement("div");
    content.className = "content";

    const innerMask = document.createElement("div");
    innerMask.className = "inner-mask inner-shadow";

    frameColor.appendChild(content);
    frameColor.appendChild(innerMask);
    outerMask.appendChild(frameColor);
    button.appendChild(outerMask);

    if (customButtonIconUrl) {
      content.style.backgroundImage = `url('${customButtonIconUrl}')`;
      content.style.backgroundRepeat = "no-repeat";
      content.style.backgroundPosition = "center";
      content.style.backgroundSize = "contain";
    }

    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();

      const skinItem = button.closest(".skin-selection-item, .thumbnail-wrapper");
      if (!skinItem) return;
      if (!modsForCurrentSkin.length) return;

      togglePanel(button, skinItem);
    });

    button.addEventListener("mousedown", (event) => {
      event.stopPropagation();
    });

    return button;
  }

  function updateButtonVisibility(button, shouldShow) {
    if (!button) return;

    if (shouldShow) {
      button.style.display = "block";
      button.style.visibility = "visible";
      button.style.pointerEvents = "auto";
      button.style.opacity = "1";
      button.style.cursor = "pointer";
      button.removeAttribute("data-hidden");
    } else {
      button.style.display = "none";
      button.style.visibility = "hidden";
      button.style.pointerEvents = "none";
      button.style.opacity = "0";
      button.style.cursor = "default";
      button.setAttribute("data-hidden", "true");
      if (panel && panel.parentNode && panelButtonRef === button) {
        closePanel();
      }
    }
  }

  function removeAllButtons() {
    document.querySelectorAll(BUTTON_SELECTOR).forEach((node) => node.remove());
  }

  function sendDeselect() {
    const { championId, skinId } = getCurrentSkinContext();
    if (!bridge || !championId || !skinId) return;

    bridge.send({
      type: "select-skin-mod",
      championId,
      skinId,
      modId: null,
    });
  }

  function sendSelect(modId, modData) {
    const { championId, skinId } = getCurrentSkinContext();
    if (!bridge || !championId || !skinId) return;

    bridge.send({
      type: "select-skin-mod",
      championId,
      skinId,
      modId,
      modData,
    });
  }

  function requestModsForCurrentSkin() {
    if (!bridge) return;
    const { championId, skinId } = getCurrentSkinContext();

    if (!championLocked || !championId || !skinId) {
      modsForCurrentSkin = [];
      scanSkinSelection();
      return;
    }

    bridge.send({
      type: REQUEST_TYPE,
      championId,
      skinId,
    });
  }

  function createPanelForMods(mods, buttonElement) {
    if (!buttonElement || !mods.length) return null;

    const existing = document.getElementById(PANEL_ID);
    if (existing) existing.remove();

    const root = document.createElement("div");
    root.id = PANEL_ID;
    root.className = PANEL_CLASS;
    root.style.position = "fixed";
    root.style.top = "0";
    root.style.left = "0";
    root.style.width = "100%";
    root.style.height = "100%";
    root.style.pointerEvents = "none";

    let flyout;
    try {
      flyout = document.createElement("lol-uikit-flyout-frame");
      flyout.className = "flyout";
      flyout.setAttribute("orientation", "top");
      flyout.setAttribute("animated", "false");
      flyout.setAttribute("caretoffset", "undefined");
      flyout.setAttribute("borderless", "undefined");
      flyout.setAttribute("caretless", "undefined");
      flyout.setAttribute("show", "true");
    } catch {
      flyout = document.createElement("div");
      flyout.className = "flyout";
    }
    flyout.style.position = "absolute";
    flyout.style.overflow = "visible";
    flyout.style.pointerEvents = "all";

    let flyoutContent;
    try {
      flyoutContent = document.createElement("lc-flyout-content");
    } catch {
      flyoutContent = document.createElement("div");
      flyoutContent.className = "lc-flyout-content";
    }

    const modal = document.createElement("div");
    modal.className = "champ-select-chroma-modal chroma-view ember-view";

    const border = document.createElement("div");
    border.className = "border";

    const chromaInfo = document.createElement("div");
    chromaInfo.className = "chroma-information";

    const preview = document.createElement("div");
    preview.className = "chroma-information-image";

    const skinName = document.createElement("div");
    skinName.className = "child-skin-name";
    skinName.textContent = getCurrentSkinContext().skinName;

    chromaInfo.appendChild(preview);
    chromaInfo.appendChild(skinName);

    const scrollable = document.createElement("div");
    scrollable.className = "chroma-selection";

    const list = document.createElement("ul");

    const setPreviewImage = (url, label) => {
      preview.style.display = "block";
      preview.style.backgroundImage = url ? `url('${url}')` : "";
      skinName.textContent = label || getCurrentSkinContext().skinName;
    };

    const noneEntry = {
      id: "__none__",
      modName: "Base Skin",
      thumbnailUrl: "",
      description: "Disable custom skin mod",
      _none: true,
    };

    const visibleMods = [noneEntry, ...mods];

    visibleMods.forEach((mod, index) => {
      const modId = mod._none ? "__none__" : normalizeModId(mod);
      const isSelected = mod._none
        ? !selectedModId
        : (selectedModId === modId && Number(selectedModSkinId) === Number(getCurrentSkinContext().skinId));

      const item = document.createElement("li");
      const emberView = document.createElement("div");
      emberView.className = "ember-view";

      const wheelButton = document.createElement("div");
      wheelButton.className = `chroma-skin-button ${isSelected ? "selected" : ""}`;
      wheelButton.title = mod.modName || `Custom Skin ${index + 1}`;

      const contents = document.createElement("div");
      contents.className = "contents";

      const thumbnailUrl = mod.thumbnailUrl ? String(mod.thumbnailUrl).replace("localhost", "127.0.0.1") : "";
      if (thumbnailUrl) {
        contents.style.backgroundImage = `url('${thumbnailUrl}')`;
      } else if (mod._none) {
        contents.style.backgroundImage = "";
        contents.style.background = "linear-gradient(135deg, #f0e6d2, #f0e6d2 48%, #be1e37 0, #be1e37 52%, #f0e6d2 0, #f0e6d2)";
      } else {
        contents.style.backgroundImage = "";
      }

      const applySelection = () => {
        if (mod._none) {
          if (selectedModId) {
            sendDeselect();
          }
          selectedModId = null;
          selectedModSkinId = null;
          closePanel();
          return;
        }

        if (selectedModId === modId && Number(selectedModSkinId) === Number(getCurrentSkinContext().skinId)) {
          sendDeselect();
          selectedModId = null;
          selectedModSkinId = null;
        } else {
          selectedModId = modId;
          selectedModSkinId = Number(getCurrentSkinContext().skinId);
          sendSelect(modId, mod);
        }

        closePanel();
      };

      wheelButton.addEventListener("mouseenter", () => {
        const hoverLabel = mod._none ? getCurrentSkinContext().skinName : (mod.modName || getCurrentSkinContext().skinName);
        setPreviewImage(thumbnailUrl || "", hoverLabel);
      });

      wheelButton.addEventListener("mouseleave", () => {
        const active = visibleMods.find((entry) => {
          if (entry._none) return !selectedModId;
          return selectedModId === normalizeModId(entry) && Number(selectedModSkinId) === Number(getCurrentSkinContext().skinId);
        });
        const activeUrl = active && active.thumbnailUrl ? String(active.thumbnailUrl).replace("localhost", "127.0.0.1") : "";
        const activeLabel = active && !active._none ? (active.modName || getCurrentSkinContext().skinName) : getCurrentSkinContext().skinName;
        setPreviewImage(activeUrl, activeLabel);
      });

      wheelButton.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        applySelection();
      });

      contents.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        applySelection();
      });

      wheelButton.appendChild(contents);
      emberView.appendChild(wheelButton);
      item.appendChild(emberView);
      list.appendChild(item);
    });

    const active = visibleMods.find((entry) => {
      if (entry._none) return !selectedModId;
      return selectedModId === normalizeModId(entry) && Number(selectedModSkinId) === Number(getCurrentSkinContext().skinId);
    });
    const activeUrl = active && active.thumbnailUrl ? String(active.thumbnailUrl).replace("localhost", "127.0.0.1") : "";
    const activeLabel = active && !active._none ? (active.modName || getCurrentSkinContext().skinName) : getCurrentSkinContext().skinName;
    setPreviewImage(activeUrl, activeLabel);

    scrollable.appendChild(list);
    modal.appendChild(border);
    modal.appendChild(chromaInfo);
    modal.appendChild(scrollable);
    flyoutContent.appendChild(modal);
    flyout.appendChild(flyoutContent);
    root.appendChild(flyout);

    return root;
  }

  function positionPanel(panelElement, buttonElement) {
    if (!panelElement || !buttonElement) return;

    const flyout = panelElement.querySelector(".flyout");
    if (!flyout) return;

    const rect = buttonElement.getBoundingClientRect();
    let flyoutRect = flyout.getBoundingClientRect();
    if (!flyoutRect.width) {
      flyoutRect = { width: 305, height: 420 };
    }

    const centerX = rect.left + rect.width / 2;
    const left = Math.max(10, Math.min(centerX - flyoutRect.width / 2, window.innerWidth - flyoutRect.width - 10));
    const top = Math.max(10, rect.top - flyoutRect.height - 14);

    flyout.style.left = `${left}px`;
    flyout.style.top = `${top}px`;
  }

  function closePanel() {
    const existing = document.getElementById(PANEL_ID);
    if (existing) {
      existing.remove();
    }
    panel = null;
    panelButtonRef = null;
    panelSkinItemRef = null;
  }

  function togglePanel(buttonElement, skinItem) {
    const existing = document.getElementById(PANEL_ID);
    if (existing && panelButtonRef === buttonElement) {
      closePanel();
      return;
    }

    closePanel();

    if (!modsForCurrentSkin.length) {
      return;
    }

    const built = createPanelForMods(modsForCurrentSkin, buttonElement);
    if (!built) return;

    panel = built;
    panelButtonRef = buttonElement;
    panelSkinItemRef = skinItem;

    document.body.appendChild(panel);
    positionPanel(panel, buttonElement);

    const closeHandler = (event) => {
      if (!panel || !panel.parentNode) {
        document.removeEventListener("click", closeHandler);
        return;
      }
      if (panel.contains(event.target) || buttonElement.contains(event.target)) {
        return;
      }
      closePanel();
      document.removeEventListener("click", closeHandler);
    };

    setTimeout(() => {
      document.addEventListener("click", closeHandler);
    }, 100);
  }

  function ensureButtonOnItem(skinItem) {
    if (!skinItem) return;

    const isCurrent = isCurrentSkinItem(skinItem);
    const matchesState = doesSkinItemMatchSkinState(skinItem);
    let existingButton = skinItem.querySelector(BUTTON_SELECTOR);

    if (!championLocked || !isCurrent || !matchesState) {
      if (existingButton) {
        existingButton.remove();
      }
      return;
    }

    if (!existingButton) {
      existingButton = createFakeButton();
      if (
        skinItem.classList.contains("thumbnail-wrapper") &&
        skinItem.classList.contains("active-skin")
      ) {
        skinItem.appendChild(existingButton);
      } else {
        skinItem.appendChild(existingButton);
      }
    }

    updateButtonVisibility(existingButton, modsForCurrentSkin.length > 0);
  }

  function scanSkinSelection() {
    const skinItems = document.querySelectorAll(".skin-selection-item, .thumbnail-wrapper");

    if (!skinItems.length) {
      removeAllButtons();
      closePanel();
      return;
    }

    skinItems.forEach((skinItem) => ensureButtonOnItem(skinItem));

    const validPanelAnchor =
      panelSkinItemRef &&
      panelSkinItemRef.isConnected &&
      panelSkinItemRef.querySelector(BUTTON_SELECTOR) &&
      modsForCurrentSkin.length > 0;

    if (!validPanelAnchor) {
      closePanel();
    }
  }

  function clearSelectedCustomModForSkinSwitch() {
    const currentSkinId = Number(getCurrentSkinContext().skinId);

    if (!selectedModId || !Number.isFinite(selectedModSkinId)) {
      return;
    }

    if (currentSkinId && selectedModSkinId !== currentSkinId) {
      sendDeselect();
      selectedModId = null;
      selectedModSkinId = null;
    }
  }

  function handleModsResponse(data) {
    const detail = data?.detail || data;
    if (!detail || detail.type !== "skin-mods-response") return;

    const { skinId, championId } = getCurrentSkinContext();
    if (!skinId || !championId) {
      modsForCurrentSkin = [];
      scanSkinSelection();
      return;
    }

    const responseChampionId = Number(detail.championId);
    if (responseChampionId && responseChampionId !== championId) {
      return;
    }

    const incoming = Array.isArray(detail.mods) ? detail.mods : [];
    modsForCurrentSkin = incoming.filter((mod) => Number(mod?.skinId) === skinId);

    if (!modsForCurrentSkin.length && selectedModId && Number(selectedModSkinId) === skinId) {
      sendDeselect();
      selectedModId = null;
      selectedModSkinId = null;
    }

    const historicMod = detail.historicMod;
    if (!selectedModId && historicMod) {
      const match = modsForCurrentSkin.find((mod) => {
        const path = String(mod?.relativePath || "").replace(/\\/g, "/");
        return path === String(historicMod).replace(/\\/g, "/");
      });
      if (match) {
        selectedModId = normalizeModId(match);
        selectedModSkinId = skinId;
        sendSelect(selectedModId, match);
      }
    }

    scanSkinSelection();

    if (panel && panel.parentNode && panelButtonRef) {
      closePanel();
    }
  }

  function handleSkinState(event) {
    const detail = event?.detail;
    if (!detail) return;

    skinMonitorState = detail;
    clearSelectedCustomModForSkinSwitch();
    requestModsForCurrentSkin();
    scanSkinSelection();

    if (panel && panel.parentNode && panelButtonRef) {
      positionPanel(panel, panelButtonRef);
    }
  }

  function observeSkinSelection() {
    const observer = new MutationObserver(() => {
      scanSkinSelection();
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["class", "aria-selected"],
    });

    setInterval(scanSkinSelection, 500);
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
    }

    if (window.__roseSkinState) {
      skinMonitorState = window.__roseSkinState;
    }

    if (bridge) {
      bridge.subscribe("skin-mods-response", (data) => handleModsResponse({ detail: data }));
      bridge.subscribe("local-asset-url", (data) => handleLocalAssetUrl(data));
      bridge.subscribe("champion-locked", (data) => {
        championLocked = Boolean(data?.locked);

        if (!championLocked) {
          modsForCurrentSkin = [];
          selectedModId = null;
          selectedModSkinId = null;
          closePanel();
        } else {
          requestModsForCurrentSkin();
        }

        scanSkinSelection();
      });

      bridge.subscribe("custom-mod-state", (data) => {
        if (data && data.active === false) {
          selectedModId = null;
          selectedModSkinId = null;
          scanSkinSelection();
        }
      });

      bridge.onReady(() => {
        bridge.send({
          type: "request-local-asset",
          assetPath: BUTTON_ICON_ASSET_PATH,
          timestamp: Date.now(),
        });
        requestModsForCurrentSkin();
      });

      bridge.send({
        type: "request-local-asset",
        assetPath: BUTTON_ICON_ASSET_PATH,
        timestamp: Date.now(),
      });
    }

    window.addEventListener(EVENT_SKIN_STATE, handleSkinState, { passive: true });
    window.addEventListener("resize", () => {
      if (panel && panel.parentNode && panelButtonRef) {
        positionPanel(panel, panelButtonRef);
      }
    });
    window.addEventListener("scroll", () => {
      if (panel && panel.parentNode && panelButtonRef) {
        positionPanel(panel, panelButtonRef);
      }
    });

    observeSkinSelection();
    requestModsForCurrentSkin();
    scanSkinSelection();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
