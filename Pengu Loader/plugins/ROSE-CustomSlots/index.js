/**
 * @name ROSE-CustomSlots
 * @author Rose Team
 * @description Shows the custom skin mods of the hovered skin as slots above the skin carousel
 */
(function createCustomSlots() {
  const LOG_PREFIX = "[ROSE-CustomSlots]";
  const STRIP_ID = "rose-custom-slots";
  const STYLE_ID = "rose-custom-slots-style";
  const MOD_ACTIVE_CLASS = "rose-custom-slot-active";
  const MOD_NAME_POPUP_ID = "historic-popup-layer"; // ROSE-HistoricMode
  const EVENT_SKIN_STATE = "lu-skin-monitor-state";
  const CAROUSEL_SELECTOR = ".skin-selection-carousel-container, .skin-selection-carousel";

  // Rose's menu language (ROSE-I18n); English until it has loaded
  const t = (text) => (window.RoseI18n ? window.RoseI18n.t(text) : text);

  let bridge = null;
  let initialized = false;
  let skinMonitorState = null;
  let championLocked = false;
  let currentPhase = null;
  let mods = [];
  let modsChampionId = null;
  let lastModsRequestAt = 0;
  let selectedModId = null;
  let selectionRequestCounter = 0;
  let activeModState = null;
  const championAliases = new Map();

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

  function normalizeModId(mod) {
    return String(mod?.relativePath || mod?.modName || "").replace(/\\/g, "/");
  }

  function visibleModName(mod) {
    const alias = typeof mod?.displayName === "string" ? mod.displayName.trim() : "";
    return alias || mod?.modName || t("Custom Skin");
  }

  function currentChampionId() {
    const championId = Number(skinMonitorState?.championId);
    return Number.isFinite(championId) && championId > 0 ? championId : null;
  }

  function currentSkinId() {
    const skinId = Number(skinMonitorState?.skinId);
    return Number.isFinite(skinId) && skinId > 0 ? skinId : null;
  }

  // Rose always reports at least one target per mod (the base skin by default)
  function modsForCurrentSkin() {
    const skinId = currentSkinId();
    if (!skinId) return [];
    return mods.filter((mod) => (mod.targetSkinIds || []).map(Number).includes(skinId));
  }

  // --------------------------------------------------------------- bridge I/O

  function requestMods(force = false) {
    const championId = currentChampionId();
    if (!bridge || !championLocked || !championId) return;
    const now = Date.now();
    if (!force && modsChampionId === championId && now - lastModsRequestAt < 5000) return;
    lastModsRequestAt = now;
    bridge.send({
      type: "request-skin-mods",
      championId,
      skinId: currentSkinId() || championId * 1000,
    });
  }

  function createRequestId() {
    selectionRequestCounter += 1;
    return `${LOG_PREFIX}-${Date.now()}-${selectionRequestCounter}`;
  }

  function sendSelect(mod, skinId) {
    const championId = currentChampionId();
    if (!bridge || !championId) return;
    bridge.send({
      type: "select-skin-mod",
      championId,
      skinId,
      modId: normalizeModId(mod),
      modData: mod,
      requestId: createRequestId(),
    });
  }

  function sendDeselect() {
    const championId = currentChampionId();
    const skinId = currentSkinId();
    if (!bridge || !championId || !skinId || !selectedModId) return;
    bridge.send({
      type: "select-skin-mod",
      championId,
      skinId,
      modId: null,
      expectedModId: selectedModId,
      requestId: createRequestId(),
    });
  }

  function activateMod(mod) {
    const skinId = currentSkinId();
    if (!skinId) return;
    if (selectedModId === normalizeModId(mod)) sendDeselect();
    else sendSelect(mod, skinId);
  }

  // ---------------------------------------------------------------------- UI

  function injectCSS() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
#${STRIP_ID} {
  position: fixed; z-index: 9000; display: flex; flex-direction: column; align-items: center;
  gap: 4px; pointer-events: none; -webkit-user-select: none;
}
#${STRIP_ID}[hidden] { display: none; }
.${MOD_ACTIVE_CLASS} #${MOD_NAME_POPUP_ID} { display: none !important; }
#${STRIP_ID} .rcs-title {
  color: #c8aa6e; font-family: "LoL Display","Times New Roman",serif; font-size: 11px;
  font-weight: 700; letter-spacing: .1em; text-transform: uppercase;
  text-shadow: 0 0 4px #000;
}
#${STRIP_ID} .rcs-list { display: flex; gap: 8px; pointer-events: auto; }
#${STRIP_ID} .rcs-slot {
  position: relative; width: 64px; height: 64px; box-sizing: border-box; cursor: pointer;
  background-color: #1e2328; background-size: cover; background-position: center;
  border: 2px solid transparent;
  border-image: linear-gradient(0deg,#4f4f54 0%,#3c3c41 50%,#29272b 100%) 1;
  transition: transform 120ms ease-out;
}
#${STRIP_ID} .rcs-slot:hover { transform: translateY(-2px); }
#${STRIP_ID} .rcs-slot:hover, #${STRIP_ID} .rcs-slot.selected {
  border-image: linear-gradient(0deg,#c8aa6e 0%,#c89b3c 44%,#a07b32 59%,#785a28 100%) 1;
}
#${STRIP_ID} .rcs-slot.selected { box-shadow: 0 0 8px 1px rgba(200,155,60,.6); }
#${STRIP_ID} .rcs-name {
  position: absolute; left: 0; right: 0; bottom: 0; padding: 1px 2px;
  background: rgba(1,10,19,.78); color: #f0e6d2; font-size: 9px; line-height: 12px;
  text-align: center; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
#${STRIP_ID} .rcs-badge {
  position: absolute; top: 2px; right: 2px; padding: 0 3px; background: #c89b3c;
  color: #010a13; font-size: 8px; font-weight: 700; line-height: 11px;
}
`;
    document.head.appendChild(style);
  }

  function ensureStrip() {
    let strip = document.getElementById(STRIP_ID);
    if (!strip) {
      strip = document.createElement("div");
      strip.id = STRIP_ID;
      strip.hidden = true;
      const title = document.createElement("div");
      title.className = "rcs-title";
      const list = document.createElement("div");
      list.className = "rcs-list";
      strip.append(title, list);
      document.body.appendChild(strip);
    }
    return strip;
  }

  function slotThumbnail(mod, championId, skinId) {
    if (mod.thumbnailUrl) return String(mod.thumbnailUrl).replace("localhost", "127.0.0.1");
    return `/lol-game-data/assets/v1/champion-tiles/${championId}/${skinId}.jpg`;
  }

  function render() {
    applyPreview();
    const strip = ensureStrip();
    const championId = currentChampionId();
    const skinId = currentSkinId();
    const skinMods = modsChampionId === championId ? modsForCurrentSkin() : [];
    const carousel = document.querySelector(CAROUSEL_SELECTOR);
    const visible =
      currentPhase !== "InProgress" &&
      championLocked &&
      skinMods.length > 0 &&
      carousel &&
      carousel.getBoundingClientRect().width > 0;

    if (!visible) {
      strip.hidden = true;
      return;
    }

    strip.querySelector(".rcs-title").textContent = t("Custom Skins");
    const list = strip.querySelector(".rcs-list");
    const signature = JSON.stringify([championId, skinId, selectedModId, skinMods.map(normalizeModId)]);
    if (list.dataset.signature !== signature) {
      list.dataset.signature = signature;
      list.replaceChildren(
        ...skinMods.map((mod) => {
          const modId = normalizeModId(mod);
          const slot = document.createElement("div");
          slot.className = "rcs-slot";
          if (modId === selectedModId) slot.classList.add("selected");
          slot.title = visibleModName(mod);
          slot.style.backgroundImage = `url('${slotThumbnail(mod, championId, skinId)}')`;

          const badge = document.createElement("div");
          badge.className = "rcs-badge";
          badge.textContent = "CUSTOM";
          const name = document.createElement("div");
          name.className = "rcs-name";
          name.textContent = visibleModName(mod);
          slot.append(badge, name);

          slot.addEventListener("mousedown", (event) => event.stopPropagation());
          slot.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            activateMod(mod);
          });
          return slot;
        })
      );
    }

    strip.hidden = false;
    const rect = carousel.getBoundingClientRect();
    const stripRect = strip.getBoundingClientRect();
    strip.style.left = `${Math.round(rect.left + rect.width / 2 - stripRect.width / 2)}px`;
    strip.style.top = `${Math.round(Math.max(4, rect.top - stripRect.height - 8))}px`;
  }

  // ----------------------------------------------------------------- events

  function resetSession() {
    mods = [];
    modsChampionId = null;
    lastModsRequestAt = 0;
    selectedModId = null;
    activeModState = null;
  }

  function handleModsResponse(data) {
    const championId = currentChampionId();
    const responseChampionId = Number(data.championId);
    if (!championId || (responseChampionId && responseChampionId !== championId)) return;
    mods = Array.isArray(data.mods) ? data.mods : [];
    modsChampionId = championId;
    render();
  }

  function handleSelectionResult(data) {
    if (!String(data?.requestId || "").startsWith(LOG_PREFIX) || data.success) return;
    console.warn(`${LOG_PREFIX} Custom skin selection failed: ${data.error || "unknown error"}`);
  }

  function handleCustomModState(data) {
    if (!data) return;
    selectedModId = data.active === false
      ? null
      : String(data.relativePath || data.modName || "").replace(/\\/g, "/") || null;
    activeModState = selectedModId ? data : null;
    render();
  }

  // ----------------------------------------------------------- splash preview
  //
  // While a custom mod is selected and the carousel shows its target skin, the
  // client still draws the official splash. Swap every image of that skin
  // (champ select background and the carousel thumbnail) for the mod's preview
  // image, and put the client's own image back once the mod is off.

  async function loadChampionAlias(championId) {
    if (championAliases.has(championId)) return championAliases.get(championId);
    championAliases.set(championId, null);
    try {
      const response = await fetch(`/lol-game-data/assets/v1/champions/${championId}.json`);
      const data = response.ok ? await response.json() : null;
      if (data?.alias) championAliases.set(championId, String(data.alias));
    } catch {
      // Champion-specific path patterns are skipped without the alias
    }
    return championAliases.get(championId);
  }

  function escapeRegExp(text) {
    return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function skinUrlPattern(championId, skinId) {
    const num = skinId % 1000;
    const parts = [
      `champion-splashes/(?:uncentered/)?${championId}/${skinId}\\.`,
      `champion-tiles/${championId}/${skinId}\\.`,
    ];
    const alias = championAliases.get(championId);
    if (alias) {
      const a = escapeRegExp(alias);
      const folder = num === 0 ? "(?:Base|Skin0*0)" : `Skin0*${num}`;
      parts.push(`/Characters/${a}/Skins/${folder}/`);
      parts.push(`/${a}_splash_(?:centered|uncentered|tile)_${num}\\.`);
    }
    return new RegExp(parts.join("|"), "i");
  }

  // Whether the carousel shows a skin the selected custom mod applies to
  function activeModOnCurrentSkin() {
    const championId = currentChampionId();
    const skinId = currentSkinId();
    if (!activeModState || !championId || !skinId || currentPhase === "InProgress") return false;
    if (Number(activeModState.championId) && Number(activeModState.championId) !== championId) return false;

    const targets = (activeModState.targetSkinIds || []).map(Number);
    const fallbackTarget = Number(activeModState.skinId);
    return targets.length ? targets.includes(skinId) : fallbackTarget === skinId;
  }

  function previewForActiveMod() {
    if (!activeModOnCurrentSkin()) return null;
    const championId = currentChampionId();
    const skinId = currentSkinId();
    const mod = mods.find((entry) => normalizeModId(entry) === selectedModId);
    const url = mod?.thumbnailUrl ? String(mod.thumbnailUrl).replace("localhost", "127.0.0.1") : "";
    return url ? { url, championId, skinId } : null;
  }

  function cssUrl(url) {
    return `url("${url}")`;
  }

  function backgroundUrl(element) {
    const match = /url\(["']?([^"')]+)["']?\)/.exec(element.style.backgroundImage || "");
    return match ? match[1] : "";
  }

  function shownImage(element) {
    return element.dataset.roseCsKind === "bg" ? backgroundUrl(element) : element.getAttribute("src");
  }

  // Put the client's image back, unless the client has already drawn a new
  // one over the preview (for example after moving to another skin)
  function restorePreviewElements() {
    document.querySelectorAll("[data-rose-cs-original]").forEach((element) => {
      const { roseCsOriginal: original, roseCsKind: kind, roseCsPreview: preview } = element.dataset;
      if (kind === "video") element.style.removeProperty("visibility");
      else if (shownImage(element) === preview) {
        if (kind === "bg") element.style.backgroundImage = cssUrl(original);
        else element.setAttribute("src", original);
      }
      delete element.dataset.roseCsOriginal;
      delete element.dataset.roseCsKind;
      delete element.dataset.roseCsPreview;
    });
  }

  function applyPreview() {
    // The selected slot already names the mod: hide ROSE-HistoricMode's
    // name popup for it
    document.documentElement.classList.toggle(MOD_ACTIVE_CLASS, activeModOnCurrentSkin());

    const preview = previewForActiveMod();
    if (!preview) {
      restorePreviewElements();
      return;
    }
    if (!championAliases.has(preview.championId)) {
      loadChampionAlias(preview.championId).then(applyPreview);
    }

    const pattern = skinUrlPattern(preview.championId, preview.skinId);

    // An element we swapped that the client has since given a new image is
    // treated as fresh by the scan below
    document.querySelectorAll("[data-rose-cs-original]").forEach((element) => {
      if (element.dataset.roseCsKind !== "video" && shownImage(element) !== preview.url) {
        delete element.dataset.roseCsOriginal;
        delete element.dataset.roseCsKind;
        delete element.dataset.roseCsPreview;
      }
    });

    document.querySelectorAll("[src], [style*='background']").forEach((element) => {
      if (element.dataset.roseCsOriginal !== undefined || element.closest(`#${STRIP_ID}`)) return;

      if (element.tagName === "VIDEO") {
        // Animated splashes play over the image layer; hide the video
        const src = element.getAttribute("src") || element.querySelector("source")?.getAttribute("src") || "";
        if (pattern.test(src) || pattern.test(element.getAttribute("poster") || "")) {
          element.dataset.roseCsOriginal = src;
          element.dataset.roseCsKind = "video";
          element.style.setProperty("visibility", "hidden", "important");
        }
        return;
      }

      const src = element.getAttribute("src");
      if (src && pattern.test(src)) {
        element.dataset.roseCsOriginal = src;
        element.dataset.roseCsKind = "src";
        element.dataset.roseCsPreview = preview.url;
        element.setAttribute("src", preview.url);
        return;
      }

      const bg = backgroundUrl(element);
      if (bg && pattern.test(bg)) {
        element.dataset.roseCsOriginal = bg;
        element.dataset.roseCsKind = "bg";
        element.dataset.roseCsPreview = preview.url;
        element.style.backgroundImage = cssUrl(preview.url);
      }
    });
  }

  function handleSkinState(event) {
    if (!event?.detail) return;
    const previousChampionId = currentChampionId();
    skinMonitorState = event.detail;
    if (currentChampionId() !== previousChampionId) {
      mods = [];
      modsChampionId = null;
      requestMods(true);
    } else {
      requestMods();
    }
    render();
  }

  async function init() {
    if (initialized) return;
    initialized = true;
    injectCSS();

    try {
      bridge = await waitForBridge();
      console.log(`${LOG_PREFIX} Bridge connected`);
    } catch (error) {
      console.error(`${LOG_PREFIX} Bridge connection failed`, error);
      return;
    }

    if (window.__roseSkinState) skinMonitorState = window.__roseSkinState;

    bridge.subscribe("skin-mods-response", handleModsResponse);
    bridge.subscribe("custom-mod-selection-result", handleSelectionResult);
    bridge.subscribe("custom-mod-state", handleCustomModState);
    bridge.subscribe("phase-change", (data) => {
      const phase = String(data?.phase || "");
      const previous = currentPhase;
      currentPhase = phase;
      if ((phase === "ChampSelect") !== (previous === "ChampSelect")) resetSession();
      render();
    });
    bridge.subscribe("champion-locked", (data) => {
      championLocked = Boolean(data?.locked);
      if (championLocked) requestMods(true);
      else resetSession();
      render();
    });
    bridge.onReady(() => requestMods(true));

    window.addEventListener(EVENT_SKIN_STATE, handleSkinState, { passive: true });
    window.addEventListener("resize", render);
    setInterval(render, 500);
    render();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
