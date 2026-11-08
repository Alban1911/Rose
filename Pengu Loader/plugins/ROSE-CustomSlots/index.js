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
  const LAYOUT_INTERVAL_MS = 500;
  const ALIAS_RETRY_MS = 2000;

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
  let layoutTimer = null;
  let roseUpdates = 0; // phase-change and champion-locked messages received
  let clientSyncs = 0; // client reads started (the latest one wins)

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

  // Works for a mod from skin-mods-response and for a custom-mod-state message
  function normalizeModId(mod) {
    return String(mod?.relativePath || mod?.modName || "").replace(/\\/g, "/");
  }

  function visibleModName(mod) {
    const alias = typeof mod?.displayName === "string" ? mod.displayName.trim() : "";
    return alias || mod?.modName || t("Custom Skin");
  }

  // Rose serves the preview image at http://127.0.0.1:<port>/mod-asset/...
  function modPreviewUrl(mod) {
    return mod?.thumbnailUrl ? String(mod.thumbnailUrl) : "";
  }

  function currentChampionId() {
    const championId = Number(skinMonitorState?.championId);
    return Number.isFinite(championId) && championId > 0 ? championId : null;
  }

  function currentSkinId() {
    const skinId = Number(skinMonitorState?.skinId);
    return Number.isFinite(skinId) && skinId > 0 ? skinId : null;
  }

  // Rose only tells plugins about a lock once it happens, and it does not
  // unlock when champ select ends: the phase is checked as well
  function inLockedChampSelect() {
    return championLocked && currentPhase === "ChampSelect";
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
    if (!bridge || !inLockedChampSelect() || !championId) return;
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
    return modPreviewUrl(mod) || `/lol-game-data/assets/v1/champion-tiles/${championId}/${skinId}.jpg`;
  }

  function render() {
    applyPreview();
    const strip = ensureStrip();
    const championId = currentChampionId();
    const skinId = currentSkinId();
    const skinMods = modsChampionId === championId ? modsForCurrentSkin() : [];
    const carousel = document.querySelector(CAROUSEL_SELECTOR);
    const visible =
      inLockedChampSelect() &&
      skinMods.length > 0 &&
      carousel &&
      carousel.getBoundingClientRect().width > 0;

    // The selected slot names the mod, so ROSE-HistoricMode's name popup is
    // hidden only while that slot is actually on screen
    const selectedSlotShown =
      Boolean(visible && selectedModId) && skinMods.some((mod) => normalizeModId(mod) === selectedModId);
    document.documentElement.classList.toggle(MOD_ACTIVE_CLASS, selectedSlotShown);

    if (!visible) {
      strip.hidden = true;
      return;
    }

    strip.querySelector(".rcs-title").textContent = t("Custom Skins");
    const list = strip.querySelector(".rcs-list");
    const signature = JSON.stringify([
      championId, skinId, selectedModId,
      skinMods.map((mod) => [normalizeModId(mod), visibleModName(mod), slotThumbnail(mod, championId, skinId)]),
    ]);
    if (list.dataset.signature !== signature) {
      list.dataset.signature = signature;
      list.replaceChildren(
        ...skinMods.map((mod) => {
          const modId = normalizeModId(mod);
          const slot = document.createElement("div");
          slot.className = "rcs-slot";
          if (modId === selectedModId) slot.classList.add("selected");
          slot.title = visibleModName(mod);
          slot.style.backgroundImage = cssUrl(slotThumbnail(mod, championId, skinId));

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

  // Only the plugin's copy is dropped: Rose still knows the selected mod and
  // the next skin-mods-response carries it back (customModState)
  function resetSession() {
    mods = [];
    modsChampionId = null;
    lastModsRequestAt = 0;
    selectedModId = null;
    activeModState = null;
  }

  function applyCustomModState(data) {
    if (!data || typeof data !== "object") return;
    selectedModId = data.active === false ? null : normalizeModId(data) || null;
    activeModState = selectedModId ? data : null;
  }

  function handleModsResponse(data) {
    const championId = currentChampionId();
    const responseChampionId = Number(data.championId);
    if (!championId || (responseChampionId && responseChampionId !== championId)) return;
    mods = Array.isArray(data.mods) ? data.mods : [];
    modsChampionId = championId;
    applyCustomModState(data.customModState);
    render();
  }

  function handleSelectionResult(data) {
    if (!String(data?.requestId || "").startsWith(LOG_PREFIX) || data.success) return;
    console.warn(`${LOG_PREFIX} Custom skin selection failed: ${data.error || "unknown error"}`);
  }

  function handleCustomModState(data) {
    applyCustomModState(data);
    render();
  }

  // ----------------------------------------------------------- splash preview
  //
  // While a custom mod is selected and the carousel shows a skin it targets,
  // the client still draws the official art. Every image of that skin (the
  // champ select background, the carousel thumbnail) shows the mod's preview
  // instead, and gets the client's own image back once it no longer should.
  //
  // `swapped` remembers what was written to each element. An element that no
  // longer shows it has been redrawn by the client: it is forgotten (never
  // restored over the client's new image) and checked again like any other.

  const PREVIEW_TARGETS = "img[src], video, [style*='background']";
  const swapped = new Map(); // element -> { kind, original, written, previewUrl }
  let previewKey = null;
  let previewObserver = null;

  const championAliases = new Map(); // championId -> alias ("" if the client has none)
  const aliasRequests = new Set(); // championIds being fetched
  const aliasRetryAt = new Map(); // championId -> earliest retry after a failed fetch

  function loadChampionAlias(championId) {
    if (championAliases.has(championId) || aliasRequests.has(championId)) return;
    if (Date.now() < (aliasRetryAt.get(championId) || 0)) return;

    aliasRequests.add(championId);
    fetch(`/lol-game-data/assets/v1/champions/${championId}.json`)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((data) => {
        championAliases.set(championId, data?.alias ? String(data.alias) : "");
        aliasRetryAt.delete(championId);
      })
      .catch(() => {
        // Game data can be missing early in champ select; ask again later
        aliasRetryAt.set(championId, Date.now() + ALIAS_RETRY_MS);
      })
      .finally(() => {
        aliasRequests.delete(championId);
        render();
      });
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
    if (!activeModState || !inLockedChampSelect() || !championId || !skinId) return false;
    if (Number(activeModState.championId) && Number(activeModState.championId) !== championId) return false;

    const targets = (activeModState.targetSkinIds || []).map(Number);
    const fallbackTarget = Number(activeModState.skinId);
    return targets.length ? targets.includes(skinId) : fallbackTarget === skinId;
  }

  function previewForActiveMod() {
    if (!activeModOnCurrentSkin()) return null;
    const championId = currentChampionId();
    const skinId = currentSkinId();
    const url = modPreviewUrl(mods.find((entry) => normalizeModId(entry) === selectedModId));
    return url ? { url, championId, skinId } : null;
  }

  // CSS url() tokens: double quoted, single quoted or bare
  const CSS_URL = /url\(\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'|([^"'()\s]*))\s*\)/gi;

  function cssUrl(url) {
    return `url("${String(url).replace(/["\\]/g, "\\$&")}")`;
  }

  function cssUrls(value) {
    return Array.from(String(value || "").matchAll(CSS_URL), (match) =>
      (match[1] ?? match[2] ?? match[3] ?? "").replace(/\\(.)/g, "$1")
    );
  }

  // `value` with the skin's url() layers pointed at `url`; other layers
  // (gradients, other images) are kept. null if no layer is the skin's.
  function swapSkinUrls(value, pattern, url) {
    let swappedAny = false;
    const result = String(value || "").replace(CSS_URL, (token, doubleQuoted, singleQuoted, bare) => {
      const tokenUrl = (doubleQuoted ?? singleQuoted ?? bare ?? "").replace(/\\(.)/g, "$1");
      if (!pattern.test(tokenUrl)) return token;
      swappedAny = true;
      return cssUrl(url);
    });
    return swappedAny ? result : null;
  }

  // Animated splashes play over the image layer as <video src> or
  // <video><source src></video>
  function videoMatches(video, pattern) {
    const urls = [video.getAttribute("src"), video.getAttribute("poster")];
    video.querySelectorAll("source").forEach((source) => urls.push(source.getAttribute("src")));
    return urls.some((url) => url && pattern.test(url));
  }

  function shownValue(element, kind) {
    return kind === "img" ? element.getAttribute("src") : element.style.backgroundImage;
  }

  function originalMatches(record, pattern) {
    if (record.kind === "img") return pattern.test(record.original);
    return cssUrls(record.original).some((url) => pattern.test(url));
  }

  // Write the preview over the client's image and remember both
  function writePreview(element, kind, original, pattern, previewUrl) {
    if (kind === "img") {
      element.setAttribute("src", previewUrl);
    } else {
      const value = swapSkinUrls(original, pattern, previewUrl);
      if (value === null) return false;
      element.style.backgroundImage = value;
    }
    // Read back: the browser normalizes what is written to the style
    swapped.set(element, { kind, original, written: shownValue(element, kind), previewUrl });
    return true;
  }

  function restore(element, record) {
    swapped.delete(element);
    if (record.kind === "video") {
      if (record.original.value) {
        element.style.setProperty("visibility", record.original.value, record.original.priority);
      } else {
        element.style.removeProperty("visibility");
      }
    } else if (record.kind === "img") {
      element.setAttribute("src", record.original);
    } else {
      element.style.backgroundImage = record.original;
    }
  }

  // Bring one element in line with the wanted preview (null: none)
  function reconcile(element, preview, pattern) {
    if (element.closest(`#${STRIP_ID}`)) return;

    const record = swapped.get(element);
    if (record) {
      if (!element.isConnected) {
        // The client may attach it again: leave its own image on it
        if (record.kind === "video" || shownValue(element, record.kind) === record.written) restore(element, record);
        else swapped.delete(element);
        return;
      }
      if (record.kind === "video") {
        if (!preview || !videoMatches(element, pattern)) restore(element, record);
        return;
      }
      if (shownValue(element, record.kind) !== record.written) {
        // The client drew a new image over the preview: look at it afresh
        swapped.delete(element);
      } else if (preview && originalMatches(record, pattern)) {
        if (record.previewUrl !== preview.url) {
          writePreview(element, record.kind, record.original, pattern, preview.url);
        }
        return;
      } else {
        // Another skin, another target of the mod, or no mod at all
        restore(element, record);
        return;
      }
    }

    if (!preview) return;
    if (element.tagName === "VIDEO") {
      if (!videoMatches(element, pattern)) return;
      const original = {
        value: element.style.getPropertyValue("visibility"),
        priority: element.style.getPropertyPriority("visibility"),
      };
      element.style.setProperty("visibility", "hidden", "important");
      swapped.set(element, { kind: "video", original });
    } else if (element.tagName === "IMG") {
      const src = element.getAttribute("src");
      if (src && pattern.test(src)) writePreview(element, "img", src, pattern, preview.url);
    } else if (element.style.backgroundImage) {
      writePreview(element, "bg", element.style.backgroundImage, pattern, preview.url);
    }
  }

  function reconcileTracked(preview, pattern) {
    Array.from(swapped.keys()).forEach((element) => reconcile(element, preview, pattern));
  }

  // Images the client adds or redraws while a preview is shown
  function handlePreviewMutations(records) {
    const preview = previewForActiveMod();
    if (!preview) return;
    const pattern = skinUrlPattern(preview.championId, preview.skinId);
    const candidates = new Set();
    const collect = (node, withSubtree) => {
      if (node.nodeType !== Node.ELEMENT_NODE) return;
      if (node.tagName === "SOURCE") {
        const video = node.closest("video");
        if (video) candidates.add(video);
        return;
      }
      if (node.matches(PREVIEW_TARGETS)) candidates.add(node);
      if (withSubtree) node.querySelectorAll(PREVIEW_TARGETS).forEach((element) => candidates.add(element));
    };
    records.forEach((record) => {
      if (record.type === "attributes") {
        // Only the element itself: style changes on containers are frequent
        collect(record.target, false);
        return;
      }
      record.addedNodes.forEach((node) => collect(node, true));
      // A <video> that lost or swapped a <source> may no longer be the skin's
      const video = record.target.nodeType === Node.ELEMENT_NODE ? record.target.closest("video") : null;
      if (video) candidates.add(video);
    });
    candidates.forEach((element) => reconcile(element, preview, pattern));
  }

  function setPreviewObserver(enabled) {
    if (enabled && !previewObserver) {
      previewObserver = new MutationObserver(handlePreviewMutations);
      previewObserver.observe(document.documentElement, {
        subtree: true,
        childList: true,
        attributes: true,
        attributeFilter: ["src", "style", "poster"],
      });
    } else if (!enabled && previewObserver) {
      previewObserver.disconnect();
      previewObserver = null;
    }
  }

  function applyPreview() {
    const preview = previewForActiveMod();
    if (preview && !championAliases.has(preview.championId)) loadChampionAlias(preview.championId);

    const pattern = preview ? skinUrlPattern(preview.championId, preview.skinId) : null;
    const key = preview ? `${preview.url}|${pattern.source}` : null;
    reconcileTracked(preview, pattern);
    if (preview && key !== previewKey) {
      document.querySelectorAll(PREVIEW_TARGETS).forEach((element) => {
        if (!swapped.has(element)) reconcile(element, preview, pattern);
      });
    }
    previewKey = key;
    setPreviewObserver(Boolean(preview));
  }

  // ------------------------------------------------------------------ setup

  // The strip follows the carousel, so it is laid out again while it can be
  // shown
  function syncLayoutTimer() {
    const enabled = inLockedChampSelect();
    if (enabled && !layoutTimer) layoutTimer = setInterval(render, LAYOUT_INTERVAL_MS);
    else if (!enabled && layoutTimer) {
      clearInterval(layoutTimer);
      layoutTimer = null;
    }
  }

  function ownChampionLocked(session) {
    const cellId = session?.localPlayerCellId;
    if (typeof cellId !== "number" || cellId < 0) return false; // -1: spectating
    const picks = (session.actions || [])
      .flat()
      .filter((action) => action?.actorCellId === cellId && action.type === "pick");
    if (picks.length) return picks.some((action) => action.completed);
    // Modes without a pick turn (ARAM) hand the champion out directly; this
    // part follows Rose's compute_locked (lcu/data/utils.py)
    const player = (session.myTeam || []).find((member) => member?.cellId === cellId);
    const intent = Number(player?.championPickIntent || player?.pickIntentChampionId || 0);
    return Number(player?.championId) > 0 && intent === 0 && !player.isPickIntenting;
  }

  function setPhase(phase) {
    const previous = currentPhase;
    currentPhase = phase;
    if ((phase === "ChampSelect") !== (previous === "ChampSelect")) {
      resetSession();
      championLocked = false;
    }
  }

  // Rose announces the phase and the lock only when they change, so a plugin
  // loaded during champ select (a client reload) or a bridge that reconnects
  // can miss them: read them from the client. Rose's own phase-change or
  // champion-locked message wins if one arrives meanwhile.
  async function syncFromClient() {
    const roseUpdatesAtStart = roseUpdates;
    const sync = ++clientSyncs;
    try {
      const phaseResponse = await fetch("/lol-gameflow/v1/gameflow-phase");
      if (!phaseResponse.ok) return;
      const phase = await phaseResponse.json();
      if (typeof phase !== "string") return;

      let locked = false;
      if (phase === "ChampSelect") {
        const sessionResponse = await fetch("/lol-champ-select/v1/session");
        locked = sessionResponse.ok && ownChampionLocked(await sessionResponse.json());
      }
      if (roseUpdates !== roseUpdatesAtStart || sync !== clientSyncs) return;

      setPhase(phase);
      if (!locked && championLocked) resetSession();
      championLocked = locked;
      syncLayoutTimer();
      requestMods(); // onReady has just asked already
      render();
    } catch (error) {
      console.warn(`${LOG_PREFIX} Could not read the champ select state`, error);
    }
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
      roseUpdates += 1;
      setPhase(String(data?.phase || ""));
      syncLayoutTimer();
      render();
    });
    bridge.subscribe("champion-locked", (data) => {
      roseUpdates += 1;
      championLocked = Boolean(data?.locked);
      // Rose only reports a lock in champ select; its phase-change may have
      // been sent while the bridge was down
      if (championLocked && currentPhase !== "ChampSelect") currentPhase = "ChampSelect";
      if (championLocked) requestMods(true);
      else resetSession();
      syncLayoutTimer();
      render();
    });
    // Runs now if the bridge is up, then on every reconnect
    bridge.onReady(() => {
      requestMods(true);
      syncFromClient();
    });

    window.addEventListener(EVENT_SKIN_STATE, handleSkinState, { passive: true });
    window.addEventListener("resize", render);
    render();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
