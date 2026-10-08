/**
 * @name ROSE-CustomSlots
 * @author Rose Team
 * @description Shows each installed custom skin mod as its own slot above the skin carousel
 */
(function createCustomSlots() {
  const LOG_PREFIX = "[ROSE-CustomSlots]";
  const STRIP_ID = "rose-custom-slots";
  const STYLE_ID = "rose-custom-slots-style";
  const EVENT_SKIN_STATE = "lu-skin-monitor-state";
  const CAROUSEL_SELECTOR = ".skin-selection-carousel-container, .skin-selection-carousel";
  const CENTER_OFFSET = 2;
  const NAV_STEP_DELAY_MS = 220;
  const NAV_MAX_STEPS = 60;
  const SKIN_STATE_TIMEOUT_MS = 4000;

  // Rose's menu language (ROSE-I18n); English until it has loaded
  const t = (text, vars) =>
    window.RoseI18n
      ? window.RoseI18n.t(text, vars)
      : text.replace(/\{(\w+)\}/g, (m, k) => (vars && k in vars ? String(vars[k]) : m));

  let bridge = null;
  let initialized = false;
  let skinMonitorState = null;
  let championLocked = false;
  let currentPhase = null;
  let mods = [];
  let modsChampionId = null;
  let lastModsRequestAt = 0;
  let selectedModId = null;
  let busyModId = null;
  let selectionRequestCounter = 0;
  let pendingSelectionRequest = null;

  function log(message, extra) {
    console.log(`${LOG_PREFIX} ${message}`, extra ?? "");
  }

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

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

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

  // The skin a mod's slot moves the carousel to: the current skin when the mod
  // targets it, otherwise its first target, otherwise the champion's base skin.
  function targetSkinIdForMod(mod, championId) {
    const targets = (Array.isArray(mod?.targetSkinIds) ? mod.targetSkinIds : [])
      .map(Number)
      .filter((id) => Number.isFinite(id) && id > 0 && Math.floor(id / 1000) === championId);
    const current = currentSkinId();
    if (current && targets.includes(current)) return current;
    if (targets.length) return targets[0];
    return championId * 1000;
  }

  // ---------------------------------------------------------------- carousel

  function parseOffset(skinItem) {
    const cls = Array.from(skinItem.classList).find((c) => c.startsWith("skin-carousel-offset"));
    const match = cls && cls.match(/skin-carousel-offset-(-?\d+)/);
    return match ? Number.parseInt(match[1], 10) : null;
  }

  function carouselSkinId(skinItem) {
    const dataId =
      skinItem.getAttribute("data-skin-id") ||
      skinItem.querySelector("[data-skin-id]")?.getAttribute("data-skin-id");
    if (dataId && Number(dataId) > 0) return Number(dataId);

    const thumbnail = skinItem.querySelector(".skin-selection-thumbnail");
    if (thumbnail) {
      const bg = thumbnail.style.backgroundImage || window.getComputedStyle(thumbnail).backgroundImage;
      const match = bg && bg.match(/champion-(?:splashes|tiles)\/(\d+)\/(\d+)\.jpg/);
      if (match) return Number(match[2]);
    }
    return null;
  }

  function carouselItems() {
    return Array.from(document.querySelectorAll(".skin-selection-carousel .skin-selection-item"))
      .map((element) => ({ element, offset: parseOffset(element), skinId: carouselSkinId(element) }))
      .filter((item) => item.offset !== null);
  }

  function clickElement(element) {
    const target = element.querySelector(".skin-selection-thumbnail") || element;
    for (const type of ["mousedown", "mouseup", "click"]) {
      target.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
    }
  }

  // Step the carousel one visible item at a time until the target skin sits
  // in the center slot. Returns false when the target cannot be reached.
  async function centerCarouselOn(skinId) {
    for (let step = 0; step < NAV_MAX_STEPS; step += 1) {
      const items = carouselItems();
      if (!items.length) return false;

      const center = items.find((item) => item.offset === CENTER_OFFSET);
      if (center && center.skinId === skinId) return true;

      const target = items.find((item) => item.skinId === skinId);
      if (!target) return false;

      // Click the visible item closest to the target (offsets 0..4 are visible)
      const clickOffset = Math.max(0, Math.min(4, target.offset));
      const clickItem = items.find((item) => item.offset === clickOffset);
      if (!clickItem || clickOffset === CENTER_OFFSET) return false;

      clickElement(clickItem.element);
      await sleep(NAV_STEP_DELAY_MS);
    }
    return false;
  }

  async function selectOwnedSkinViaApi(skinId) {
    try {
      const response = await fetch("/lol-champ-select/v1/session/my-selection", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ selectedSkinId: skinId }),
      });
      return response.ok;
    } catch {
      return false;
    }
  }

  function waitForSkinState(skinId, timeoutMs) {
    if (currentSkinId() === skinId) return Promise.resolve(true);
    return new Promise((resolve) => {
      const onState = (event) => {
        if (Number(event?.detail?.skinId) !== skinId) return;
        cleanup();
        resolve(true);
      };
      const timer = setTimeout(() => {
        cleanup();
        resolve(false);
      }, timeoutMs);
      const cleanup = () => {
        clearTimeout(timer);
        window.removeEventListener(EVENT_SKIN_STATE, onState);
      };
      window.addEventListener(EVENT_SKIN_STATE, onState);
    });
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
    const requestId = createRequestId();
    pendingSelectionRequest = { requestId, modId: normalizeModId(mod) };
    bridge.send({
      type: "select-skin-mod",
      championId,
      skinId,
      modId: normalizeModId(mod),
      modData: mod,
      requestId,
    });
  }

  function sendDeselect() {
    const championId = currentChampionId();
    const skinId = currentSkinId();
    if (!bridge || !championId || !skinId || !selectedModId) return;
    const requestId = createRequestId();
    pendingSelectionRequest = { requestId, modId: null };
    bridge.send({
      type: "select-skin-mod",
      championId,
      skinId,
      modId: null,
      expectedModId: selectedModId,
      requestId,
    });
  }

  async function activateMod(mod) {
    const championId = currentChampionId();
    if (!championId || busyModId) return;

    const modId = normalizeModId(mod);
    if (selectedModId === modId) {
      sendDeselect();
      return;
    }

    busyModId = modId;
    render();
    try {
      const skinId = targetSkinIdForMod(mod, championId);
      let centered = await centerCarouselOn(skinId);
      if (!centered) centered = await selectOwnedSkinViaApi(skinId);
      if (!centered) {
        console.warn(`${LOG_PREFIX} Could not move the carousel to skin ${skinId}`);
        return;
      }
      if (!(await waitForSkinState(skinId, SKIN_STATE_TIMEOUT_MS))) {
        console.warn(`${LOG_PREFIX} Rose did not report skin ${skinId} in time`);
        return;
      }
      sendSelect(mod, skinId);
      log(`Selected ${visibleModName(mod)} on skin ${skinId}`);
    } finally {
      busyModId = null;
      render();
    }
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
#${STRIP_ID} .rcs-slot.busy { opacity: .55; cursor: progress; }
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

  function slotThumbnail(mod, championId) {
    if (mod.thumbnailUrl) return String(mod.thumbnailUrl).replace("localhost", "127.0.0.1");
    const skinId = targetSkinIdForMod(mod, championId);
    return `/lol-game-data/assets/v1/champion-tiles/${championId}/${skinId}.jpg`;
  }

  function render() {
    const strip = ensureStrip();
    const championId = currentChampionId();
    const carousel = document.querySelector(CAROUSEL_SELECTOR);
    const visible =
      currentPhase !== "InProgress" &&
      championLocked &&
      championId &&
      modsChampionId === championId &&
      mods.length > 0 &&
      carousel &&
      carousel.getBoundingClientRect().width > 0;

    if (!visible) {
      strip.hidden = true;
      return;
    }

    strip.querySelector(".rcs-title").textContent = t("Custom Skins");
    const list = strip.querySelector(".rcs-list");
    const signature = JSON.stringify([championId, selectedModId, busyModId, mods.map(normalizeModId)]);
    if (list.dataset.signature !== signature) {
      list.dataset.signature = signature;
      list.replaceChildren(
        ...mods.map((mod) => {
          const modId = normalizeModId(mod);
          const slot = document.createElement("div");
          slot.className = "rcs-slot";
          if (modId === selectedModId) slot.classList.add("selected");
          if (modId === busyModId) slot.classList.add("busy");
          slot.title = visibleModName(mod);
          slot.style.backgroundImage = `url('${slotThumbnail(mod, championId)}')`;

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
    busyModId = null;
    pendingSelectionRequest = null;
    render();
  }

  function handleModsResponse(data) {
    if (!data || data.type !== "skin-mods-response") return;
    const championId = currentChampionId();
    const responseChampionId = Number(data.championId);
    if (!championId || (responseChampionId && responseChampionId !== championId)) return;
    mods = Array.isArray(data.mods) ? data.mods : [];
    modsChampionId = championId;
    render();
  }

  function handleSelectionResult(data) {
    if (!data || data.type !== "custom-mod-selection-result") return;
    if (!pendingSelectionRequest || data.requestId !== pendingSelectionRequest.requestId) return;
    pendingSelectionRequest = null;
    if (!data.success) {
      console.warn(`${LOG_PREFIX} Custom skin selection failed: ${data.error || "unknown error"}`);
    }
    render();
  }

  function handleCustomModState(data) {
    if (!data) return;
    selectedModId = data.active === false
      ? null
      : String(data.relativePath || data.modName || "").replace(/\\/g, "/") || null;
    render();
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
      log("Bridge connected");
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
