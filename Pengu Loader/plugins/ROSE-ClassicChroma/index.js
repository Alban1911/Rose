/**
 * @name ROSE-ClassicChroma
 * @description JADE-only chroma selector using the regular client presentation.
 */
(function initJadeChroma() {
  "use strict";

  const BUTTON_ID = "rose-jade-chroma-button";
  const PANEL_ID = "rose-jade-chroma-panel";
  const STYLE_ID = "rose-jade-chroma-style";
  const PANEL_WIDTH = 305;
  const PANEL_MAX_HEIGHT = 420;
  const PANEL_SCALE = 0.9;
  const CLASSIC_BACKGROUND =
    "/lol-game-data/assets/content/src/LeagueClient/GameModeAssets/Classic_SRU/img/champ-select-flyout-background.jpg";
  let bridge = null;
  let isInJadeChampSelect = false;
  let championLocked = false;
  let panelParentRawId = 0;
  let outsideClickHandler = null;

  function api() {
    return window.__roseJadeWheelDebug;
  }

  function rawIdOf(skin) {
    return Number(skin?.id ?? skin?.skinId) || 0;
  }

  function variantsOf(skin) {
    const variants = [
      ...(Array.isArray(skin?.childSkins) ? skin.childSkins : []),
      ...(Array.isArray(skin?.chromas) ? skin.chromas : []),
    ];
    const seen = new Set();
    return variants.filter((variant) => {
      const id = rawIdOf(variant);
      if (!id || seen.has(id)) return false;
      seen.add(id);
      return true;
    });
  }

  function currentSelection() {
    const jade = api();
    const state = jade?.state?.();
    if (state?.active !== true) return null;
    const rawId = Number(
      state.projectedVariantRawSkinId || state.desiredVisualRawSkinId || state.selectedRawSkinId
    );
    const parents = jade.catalogData?.() || [];
    for (const parent of parents) {
      if (rawIdOf(parent) === rawId) return { parent, rawId };
      if (variantsOf(parent).some((child) => rawIdOf(child) === rawId)) {
        return { parent, rawId };
      }
    }
    return null;
  }

  function colorsOf(skin) {
    const colors = Array.isArray(skin?.colors) ? skin.colors.filter(Boolean) : [];
    if (!colors.length && skin?.primaryColor) colors.push(skin.primaryColor);
    return colors.map((color) =>
      String(color).startsWith("#") ? String(color) : `#${color}`
    );
  }

  function primaryColorOf(skin) {
    const colors = colorsOf(skin);
    const value = skin?.primaryColor || colors[1] || colors[0] || "";
    if (!value) return "";
    return String(value).startsWith("#") ? String(value) : `#${value}`;
  }

  function swatch(skin, isBase = false) {
    if (isBase) {
      return "linear-gradient(135deg, #f0e6d2, #f0e6d2 48%, #be1e37 0, #be1e37 52%, #f0e6d2 0, #f0e6d2)";
    }
    return primaryColorOf(skin) || "#c8aa6e";
  }

  function visualPathOf(skin, parent) {
    const directPath =
      skin?.chromaPreviewPath || skin?.imagePath || skin?.chromaPath || skin?.tilePath;
    if (directPath) return String(directPath);

    const resourceId = api()?.resourceSkinId?.(rawIdOf(skin)) || 0;
    const resourceChampionId = Math.floor(resourceId / 1000);
    if (resourceChampionId > 0 && resourceId > 0) {
      return `/lol-game-data/assets/v1/champion-chroma-images/${resourceChampionId}/${resourceId}.png`;
    }

    return String(
      parent?.chromaPreviewPath ||
      parent?.imagePath ||
      parent?.chromaPath ||
      parent?.tilePath ||
      ""
    );
  }

  function createChromaButtonFrame(id, className) {
    const button = document.createElement("button");
    button.id = id;
    button.type = "button";
    button.className = className;
    const outerMask = document.createElement("span");
    outerMask.className = "outer-mask interactive";
    const frameColor = document.createElement("span");
    frameColor.className = "frame-color";
    const content = document.createElement("span");
    content.className = "content";
    const innerMask = document.createElement("span");
    innerMask.className = "inner-mask inner-shadow";
    frameColor.append(content, innerMask);
    outerMask.appendChild(frameColor);
    button.appendChild(outerMask);
    return button;
  }

  function closePanel() {
    document.getElementById(PANEL_ID)?.remove();
    panelParentRawId = 0;
    if (outsideClickHandler) {
      document.removeEventListener("click", outsideClickHandler, true);
      outsideClickHandler = null;
    }
  }

  function remove() {
    document.getElementById(BUTTON_ID)?.remove();
    closePanel();
  }

  function setMainButtonColor(button, selection) {
    const selected = variantsOf(selection.parent).find(
      (child) => rawIdOf(child) === selection.rawId
    );
    const content = button.querySelector(".content");
    if (!content) return;
    if (selected) {
      content.style.background = swatch(selected);
      content.style.backgroundImage = "none";
    } else {
      content.style.background =
        "url(/fe/lol-champ-select/images/config/button-chroma.png) center / contain no-repeat";
    }
  }

  function render() {
    if (!isInJadeChampSelect || !championLocked) {
      remove();
      return;
    }
    const selection = currentSelection();
    if (!selection || !variantsOf(selection.parent).length) {
      remove();
      return;
    }
    if (panelParentRawId && panelParentRawId !== rawIdOf(selection.parent)) closePanel();
    const card = document.querySelector(
      ".rose-jade-native-card.rose-jade-native-card--selected:not(.skins-pane__skin-card--placeholder)"
    );
    if (!card) return;
    let button = document.getElementById(BUTTON_ID);
    if (!button) {
      button = createChromaButtonFrame(BUTTON_ID, "lu-chroma-button rose-jade-chroma-button");
      button.title = "Select chroma";
      button.addEventListener("mousedown", (event) => event.stopPropagation());
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        const latest = currentSelection();
        if (document.getElementById(PANEL_ID)) {
          closePanel();
          return;
        }
        if (latest) renderPanel(latest.parent, latest.rawId);
      });
    }
    if (button.parentElement !== card) card.appendChild(button);
    setMainButtonColor(button, selection);
  }

  function choiceData(parent, selectedRawId) {
    return [parent, ...variantsOf(parent)]
      .map((skin, index) => ({
        skin,
        rawId: rawIdOf(skin),
        resourceId: api().resourceSkinId(rawIdOf(skin)),
        name: String(skin?.name || parent?.name || "Chroma"),
        colors: colorsOf(skin),
        primaryColor: primaryColorOf(skin),
        visualPath: visualPathOf(skin, parent),
        selected: rawIdOf(skin) === selectedRawId,
        isBase: index === 0,
      }))
      .filter((choice) => choice.rawId > 0);
  }

  function renderPanel(parent, selectedRawId) {
    closePanel();
    const button = document.getElementById(BUTTON_ID);
    if (!button) return;
    const choices = choiceData(parent, selectedRawId);
    if (!choices.length) return;
    panelParentRawId = rawIdOf(parent);
    const selectedChoice = choices.find((choice) => choice.selected) || choices[0];

    const panel = document.createElement("div");
    panel.id = PANEL_ID;
    panel.className = "rose-jade-chroma-panel";

    const flyout = document.createElement("lol-uikit-flyout-frame");
    flyout.className = "flyout";
    flyout.setAttribute("orientation", "top");
    flyout.setAttribute("animated", "false");
    flyout.setAttribute("caretoffset", "undefined");
    flyout.setAttribute("borderless", "undefined");
    flyout.setAttribute("caretless", "undefined");
    flyout.setAttribute("show", "true");

    const flyoutContent = document.createElement("lc-flyout-content");
    flyoutContent.className = "lc-flyout-content";
    const modal = document.createElement("div");
    modal.className = "champ-select-chroma-modal chroma-view ember-view";
    modal.classList.add("rose-jade-chroma-modal");
    const border = document.createElement("div");
    border.className = "border";

    const information = document.createElement("div");
    information.className = "chroma-information";
    information.style.backgroundImage = `url('${CLASSIC_BACKGROUND}')`;
    const preview = document.createElement("div");
    preview.className = "chroma-information-image";
    const name = document.createElement("div");
    name.className = "child-skin-name";
    information.append(preview, name);

    const updatePreview = (choice) => {
      name.textContent = choice.name;
      preview.style.backgroundImage = choice.visualPath
        ? `url('${choice.visualPath}')`
        : "none";
    };
    updatePreview(selectedChoice);

    const scrollable = document.createElement("lol-uikit-scrollable");
    scrollable.className = "chroma-selection";
    scrollable.setAttribute("overflow-masks", "enabled");
    const list = document.createElement("ul");
    let hoveredChoice = null;

    for (const choice of choices) {
      const listItem = document.createElement("li");
      const emberView = document.createElement("div");
      emberView.className = "ember-view";
      const choiceButton = document.createElement("div");
      choiceButton.setAttribute("role", "button");
      choiceButton.tabIndex = 0;
      choiceButton.className = `chroma-skin-button${choice.selected ? " selected" : ""}`;
      choiceButton.title = choice.name;
      const contents = document.createElement("div");
      contents.className = "contents";
      contents.style.background = swatch(choice, choice.isBase);
      choiceButton.appendChild(contents);
      emberView.appendChild(choiceButton);
      listItem.appendChild(emberView);
      list.appendChild(listItem);

      choiceButton.addEventListener("mouseenter", () => {
        hoveredChoice = choice;
        updatePreview(choice);
      });
      choiceButton.addEventListener("mouseleave", () => {
        hoveredChoice = null;
        setTimeout(() => {
          if (!hoveredChoice) updatePreview(selectedChoice);
        }, 0);
      });
      choiceButton.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        const resourceId = choice.resourceId;
        const rawId = choice.rawId;
        api().projectResourceSelection(resourceId, "chroma-state");
        bridge?.send({
          type: "chroma-selection",
          skinId: choice.isBase ? 0 : choice.resourceId,
          chromaId: choice.isBase ? 0 : choice.resourceId,
          chromaName: choice.name,
          championId: api().state().championId,
          baseSkinId: api().resourceSkinId(rawIdOf(parent)),
          rawSkinId: rawId,
          primaryColor: choice.primaryColor || null,
          colors: choice.colors,
          timestamp: Date.now(),
        });
        closePanel();
        render();
      });
    }

    scrollable.appendChild(list);
    modal.append(border, information, scrollable);
    flyoutContent.appendChild(modal);
    flyout.appendChild(flyoutContent);
    panel.appendChild(flyout);
    document.body.appendChild(panel);
    positionPanel(panel, button);
    requestAnimationFrame(() => positionPanel(panel, button));

    outsideClickHandler = (event) => {
      if (panel.contains(event.target) || button.contains(event.target)) return;
      closePanel();
    };
    setTimeout(() => {
      if (outsideClickHandler) document.addEventListener("click", outsideClickHandler, true);
    }, 0);
  }

  function handlePhaseChange(data) {
    const phase = String(data?.phase || "");
    const classicMode =
      Number(data?.mapId) === 453 || String(data?.gameMode || "").toUpperCase() === "JADE";
    isInJadeChampSelect =
      classicMode && (phase === "ChampSelect" || phase === "FINALIZATION");
    if (!isInJadeChampSelect) championLocked = false;
    render();
  }

  function handleChampionLocked(data) {
    championLocked = data?.locked === true;
    render();
  }

  function handleWheelLayout(event) {
    if (event?.detail?.active === false) {
      remove();
      return;
    }
    render();
  }

  function positionPanel(panel, button) {
    const flyout = panel?.querySelector(".flyout");
    if (!flyout || !button) return;
    const buttonRect = button.getBoundingClientRect();
    const panelRect = flyout.getBoundingClientRect();
    const width = panelRect.width || PANEL_WIDTH * PANEL_SCALE;
    const height = panelRect.height || PANEL_MAX_HEIGHT * PANEL_SCALE;
    const left = Math.max(
      10,
      Math.min(buttonRect.left + buttonRect.width / 2 - width / 2, window.innerWidth - width - 10)
    );
    flyout.style.left = `${left}px`;
    flyout.style.top = `${Math.max(10, buttonRect.top - height - 15)}px`;
  }

  function injectStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      #${BUTTON_ID} {
        position: absolute; pointer-events: auto; border: 0; padding: 0; background: transparent;
        width: 25px; height: 25px; cursor: pointer; direction: ltr;
        -webkit-user-select: none; list-style-type: none;
      }
      #${BUTTON_ID} .outer-mask {
        display: block; width: 100%; height: 100%; overflow: hidden;
        position: relative; border-radius: 50%; box-shadow: 0 0 4px 1px rgba(1,10,19,.25);
      }
      #${BUTTON_ID} .frame-color {
        display: flex; align-items: center; justify-content: center; width: 100%; height: 100%;
        padding: 2px; box-sizing: border-box; overflow: hidden;
        background-image: linear-gradient(0deg,#695625 0,#a9852d 23%,#b88d35 93%,#c8aa6e);
      }
      #${BUTTON_ID} .content {
        display: block; width: 20px; height: 20px; box-sizing: border-box;
        border: 2px solid #010a13; border-radius: 50%;
        background: url(/fe/lol-champ-select/images/config/button-chroma.png) center / contain no-repeat;
      }
      #${BUTTON_ID} .inner-mask {
        position: absolute; left: 2px; top: 2px; width: calc(100% - 4px); height: calc(100% - 4px);
        border-radius: 50%; box-shadow: inset 0 0 4px 4px rgba(0,0,0,.75); pointer-events: none;
      }
      #${PANEL_ID} { position: fixed; inset: 0; z-index: 10000; pointer-events: none; }
      #${PANEL_ID} .flyout {
        position: absolute; overflow: visible; pointer-events: all; -webkit-user-select: none;
        transform: scale(${PANEL_SCALE}) !important; transform-origin: top left !important;
      }
      #${PANEL_ID} .lc-flyout-content { position: relative; }
      #${PANEL_ID} .rose-jade-chroma-modal {
        position: relative !important; display: flex !important; flex-direction: column !important;
        width: ${PANEL_WIDTH}px !important; min-width: ${PANEL_WIDTH}px !important;
        max-width: ${PANEL_WIDTH}px !important; min-height: 355px !important;
        max-height: ${PANEL_MAX_HEIGHT}px !important; background: #000 !important;
        box-sizing: border-box !important; z-index: 0;
      }
      #${PANEL_ID} .border {
        position: absolute; inset: 0; box-sizing: border-box; z-index: 2; pointer-events: none;
        box-shadow: 0 0 0 1px rgba(1,10,19,.48);
        border: 2px solid transparent; border-bottom: 0;
        border-image: linear-gradient(to top,#785a28 0,#463714 50%,#463714 100%) 1 stretch;
      }
      #${PANEL_ID} .chroma-information {
        position: relative !important; width: 100% !important; height: 315px !important;
        background-size: cover !important; border-bottom: thin solid #463714;
        flex-grow: 1 !important; z-index: 1;
      }
      #${PANEL_ID} .chroma-information-image {
        position: absolute; inset: 0; background-position: center;
        background-size: contain; background-repeat: no-repeat;
      }
      #${PANEL_ID} .child-skin-name {
        position: absolute !important; left: 0 !important; right: 0 !important;
        bottom: 10px !important; width: 100% !important; color: #f7f0de !important;
        font-family: "LoL Display","Times New Roman",Times,Baskerville,Georgia,serif !important;
        font-size: 24px !important; font-weight: 700 !important; text-align: center !important;
      }
      #${PANEL_ID} .chroma-selection {
        min-height: 40px !important; max-height: 92px !important; height: 100% !important;
        width: 100% !important; padding: 7px 0 !important;
        overflow: auto !important; transform: translateZ(0) !important; pointer-events: all;
        display: flex !important; flex-flow: row wrap !important; flex-grow: 0 !important;
        align-items: center !important; justify-content: center !important;
        position: relative; z-index: 1;
        -webkit-mask-box-image-source: url("/fe/lol-static-assets/images/uikit/scrollable/scrollable-content-gradient-mask-bottom.png");
        -webkit-mask-box-image-slice: 0 8 18 0 fill;
      }
      #${PANEL_ID} .chroma-selection ul {
        display: flex !important; align-items: center !important; justify-content: center !important;
        flex-flow: row wrap !important; gap: 0 !important; width: 100% !important;
        margin: 0 !important; padding: 0 !important; list-style: none !important;
      }
      #${PANEL_ID} .chroma-selection li {
        display: flex !important; align-items: center !important; justify-content: center !important;
        margin: 2px 4px !important; padding: 0 !important; list-style: none !important;
      }
      #${PANEL_ID} .chroma-selection li > .ember-view {
        display: flex !important; align-items: center !important; justify-content: center !important;
        flex: 0 0 26px !important; width: 26px !important; height: 26px !important;
        min-width: 26px !important; min-height: 26px !important;
        max-width: 26px !important; max-height: 26px !important;
        margin: 0 !important; padding: 0 !important; transform: none !important;
      }
      #${PANEL_ID} .chroma-skin-button {
        display: flex !important; align-items: center !important; justify-content: center !important;
        flex: 0 0 26px !important; width: 26px !important; height: 26px !important;
        min-width: 26px !important; min-height: 26px !important;
        max-width: 26px !important; max-height: 26px !important; aspect-ratio: 1 / 1 !important;
        margin: 0 !important; padding: 0 !important; border: 0 !important;
        border-radius: 50% !important; box-sizing: border-box !important;
        background: transparent !important; box-shadow: 0 0 2px #010a13;
        cursor: pointer; opacity: 1 !important; transform: scale(1) !important;
      }
      #${PANEL_ID} .chroma-skin-button .contents {
        display: flex !important; align-items: center !important; justify-content: center !important;
        width: 18px !important; height: 18px !important;
        min-width: 18px !important; min-height: 18px !important;
        max-width: 18px !important; max-height: 18px !important; aspect-ratio: 1 / 1 !important;
        border: 2px solid #010a13 !important; border-radius: 50% !important;
        box-shadow: 0 0 0 2px transparent; box-sizing: border-box !important;
        opacity: 1 !important; transform: scale(1) !important;
      }
      #${PANEL_ID} .chroma-skin-button.selected .contents,
      #${PANEL_ID} .chroma-skin-button:hover .contents {
        box-shadow: 0 0 0 2px #c89b3c !important; transform: scale(1) !important;
      }
    `;
    document.head.appendChild(style);
  }

  async function start() {
    while (!window.__roseBridge) {
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    bridge = window.__roseBridge;
    injectStyles();
    bridge.subscribe("phase-change", handlePhaseChange);
    bridge.subscribe("champion-locked", handleChampionLocked);
    bridge.subscribe("chroma-state", render);
    window.addEventListener("rose-jade-wheel-layout", handleWheelLayout);
    new MutationObserver(render).observe(document.body, { childList: true, subtree: true });
    setInterval(render, 500);
  }

  start();
})();
