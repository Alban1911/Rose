/**
 * @name ROSE-ClassicWheel
 * @author Rose contributors
 * @description Compatibility adapter for the native JADE skin selector.
 */
(function initJadeWheelAdapter() {
  "use strict";

  const LOG_PREFIX = "[JadeWheel]";
  const JADE_MODE = "JADE";
  const JADE_MAP_ID = 453;
  const JADE_CHAMPION_OFFSET = 60000;
  const JADE_CHAMPION_MIN = 60001;
  const JADE_CHAMPION_MAX = 60999;
  const JADE_FALLBACK_DEFAULT_SKIN_NUMBER = 301;
  const JADE_DEFAULT_CARRIER_OVERRIDES = new Map([
    ...[
      2, 15, 21, 22, 23, 26, 27, 31, 32, 33, 34, 35, 37, 40,
      42, 45, 53, 54, 59, 62, 63, 67, 79, 89, 90, 96, 99, 117,
    ].map((champion) => [champion, 0]),
    [10, 302],
  ]);
  const ROOT_ID = "rose-jade-skin-wheel";
  const STYLE_ID = "rose-jade-skin-wheel-styles";
  const HOST_CLASS = "rose-jade-native-host";
  const CARD_CLASS = "rose-jade-native-card";
  const SELECTED_CLASS = "rose-jade-native-card--selected";
  const UNLOCKED_CLASS = "rose-jade-native-card--unlocked";
  const EMPTY_CLASS = "rose-jade-native-card--empty";
  const ACTIVE_ROOT_CLASS = "rose-jade-wheel-active";
  const VISUAL_PROTECTION_EVENT = "rose-jade-visual-protection";
  const POLL_INTERVAL_MS = 450;
  const CATALOG_REFRESH_MS = 2000;
  const USER_NAVIGATION_WINDOW_MS = 6000;
  const nativeFetch = window.fetch.bind(window);
  const COMPATIBILITY_CLASSES = [
    CARD_CLASS,
    SELECTED_CLASS,
  ];

  let bridge = null;
  let active = false;
  let phase = null;
  let gameMode = null;
  let mapId = null;
  let queueId = null;
  let pane = null;
  let overlay = null;
  let observer = null;
  let pollTimer = null;
  let refreshInFlight = false;
  let requestGeneration = 0;
  let selectionGeneration = 0;
  let rawChampionId = 0;
  let championId = 0;
  let selectedRawSkinId = 0;
  let selectedResourceSkinId = 0;
  let modeDefaultRawSkinId = 0;
  let catalog = [];
  let catalogLoadedAt = 0;
  let adaptedCards = new Set();
  const originalCardState = new WeakMap();
  const adaptedCardState = new WeakMap();
  const projectedImageState = new WeakMap();
  const lockOverlayState = new WeakMap();
  let desiredVisualSelection = null;
  let projectedCatalogIndex = -1;
  let nativeProjectionTargetIndex = -1;
  let nativeProjectionCurrentIndex = -1;
  let nativeProjectionTimer = null;
  let nativeProjectionComplete = null;
  let drivingNativeProjection = false;
  let pendingUserNavigation = false;
  let pendingUserNavigationUntil = 0;
  let pendingUserTargetRawSkinId = 0;
  let pendingUserSelectionPublished = false;
  let pointerSelectionRawSkinId = 0;
  let pointerSelectionUntil = 0;
  let pointerSelectionCommitted = false;
  let pendingHistoricResourceSkinId = 0;
  let lastAppliedHistoricResourceSkinId = 0;
  let historicRestoreGeneration = 0;
  let historicRestoreInProgress = false;
  let randomModeActive = false;
  let visualCarrierProtectionActive = false;
  let projectedVariantRawSkinId = 0;
  let lastVisualCenterRawSkinId = 0;
  let lastLayoutKey = "";
  let lastVisualProtectionKey = "";
  let lastReadRewriteKey = "";
  let lastCatalogSyncKey = "";
  let visualProtectionClearTimer = null;

  function waitForBridge() {
    return new Promise((resolve) => {
      const startedAt = Date.now();
      let warned = false;
      const check = () => {
        if (window.__roseBridge) {
          resolve(window.__roseBridge);
          return;
        }
        if (!warned && Date.now() - startedAt >= 10000) {
          warned = true;
          console.warn(`${LOG_PREFIX} bridge is still unavailable`);
        }
        setTimeout(check, 50);
      };
      check();
    });
  }

  function log(level, message, data = null) {
    const method = level === "error" ? "error" : level === "warn" ? "warn" : "log";
    console[method](`${LOG_PREFIX} ${message}`, data || "");
    if (!bridge) return;
    try {
      bridge.send({
        type: "chroma-log",
        source: "JadeWheel",
        level,
        message,
        data,
        timestamp: Date.now(),
      });
    } catch (_) {
      // The shared bridge owns reconnect handling.
    }
  }

  function numeric(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function isJadeChampionId(value) {
    const id = numeric(value);
    return id !== null && id >= JADE_CHAMPION_MIN && id <= JADE_CHAMPION_MAX;
  }

  function resourceChampionId(value) {
    const id = numeric(value) || 0;
    return isJadeChampionId(id) ? id - JADE_CHAMPION_OFFSET : id;
  }

  function resourceSkinId(value) {
    const id = numeric(value) || 0;
    const rawChampion = Math.floor(id / 1000);
    if (!isJadeChampionId(rawChampion)) return id;

    const resourceChampion = resourceChampionId(rawChampion);
    const skinNumber = id % 1000;
    return resourceChampion * 1000 + skinNumber;
  }

  function jadeSkinId(value) {
    const id = numeric(value) || 0;
    const resourceChampion = Math.floor(id / 1000);
    if (isJadeChampionId(resourceChampion)) return id;
    if (resourceChampion <= 0 || resourceChampion >= 1000) return id;
    return (JADE_CHAMPION_OFFSET + resourceChampion) * 1000 + (id % 1000);
  }

  function fallbackModeDefaultRawSkinId() {
    if (!isJadeChampionId(rawChampionId)) return 0;
    const skinNumber = JADE_DEFAULT_CARRIER_OVERRIDES.get(championId)
      ?? JADE_FALLBACK_DEFAULT_SKIN_NUMBER;
    return rawChampionId * 1000 + skinNumber;
  }

  function isModeDefaultRawSkinId(value) {
    const id = numeric(value) || 0;
    const expected = modeDefaultRawSkinId || fallbackModeDefaultRawSkinId();
    return id > 0 && expected > 0 && id === expected;
  }

  function isModeDefaultResourceSkinId(value) {
    const id = resourceSkinId(value);
    const expected = resourceSkinId(
      modeDefaultRawSkinId || fallbackModeDefaultRawSkinId()
    );
    return id > 0 && expected > 0 && id === expected;
  }

  async function fetchJson(endpoint) {
    // Always read the real LCU state here. The native JADE controller receives
    // a visual-only projection below, while Python and this adapter must keep
    // observing the official carrier selected in the client.
    const response = await nativeFetch(endpoint, { credentials: "include" });
    if (!response || !response.ok) {
      throw new Error(`HTTP ${response ? response.status : "NO_RESPONSE"} for ${endpoint}`);
    }
    if (response.status === 204) return null;
    return response.json();
  }

  function requestPath(input) {
    try {
      const value = typeof input === "string" ? input : input?.url;
      return new URL(value, window.location.origin).pathname;
    } catch (_) {
      return "";
    }
  }

  function requestMethod(input, init) {
    return String(init?.method || input?.method || "GET").toUpperCase();
  }

  function rewriteSessionSelection(data, desiredRawSkinId) {
    if (!data || typeof data !== "object") return false;
    const localCellId = numeric(data.localPlayerCellId);
    if (localCellId === null || !Array.isArray(data.myTeam)) return false;
    const localPlayer = data.myTeam.find(
      (player) => numeric(player?.cellId) === localCellId
    );
    if (!localPlayer || numeric(localPlayer.selectedSkinId) === desiredRawSkinId) {
      return false;
    }
    localPlayer.selectedSkinId = desiredRawSkinId;
    return true;
  }

  function rewriteNativeRead(path, data) {
    const desired = desiredVisualSelection;
    if (
      !active ||
      !desired ||
      (!visualCarrierProtectionActive && (desired.available || desired.isBase))
    ) return false;
    const desiredRawSkinId = desired.rawSkinId;

    if (path === "/lol-champ-select/v1/skin-selector-info") {
      if (!data || typeof data !== "object") return false;
      if (numeric(data.selectedSkinId) === desiredRawSkinId) return false;
      data.selectedSkinId = desiredRawSkinId;
      return true;
    }
    if (path === "/lol-champ-select/v1/session") {
      return rewriteSessionSelection(data, desiredRawSkinId);
    }
    return false;
  }

  function shouldSuppressVisualRollback(selectedSkinId) {
    const protection = window.__roseJadeVisualProtection;
    if (!active || !protection?.active) return false;
    const selected = numeric(selectedSkinId);
    const desired = numeric(protection.desiredRawSkinId);
    const carriers = new Set(
      (protection.carrierRawSkinIds || []).map(numeric).filter(Number.isFinite)
    );
    return selected !== null && desired !== null && selected !== desired && carriers.has(selected);
  }

  function cloneWebsocketEvent(event, payload) {
    try {
      return new MessageEvent(event.type || "message", {
        data: JSON.stringify(payload),
        origin: event.origin,
        lastEventId: event.lastEventId,
        source: event.source,
        ports: event.ports,
      });
    } catch (_) {
      return { data: JSON.stringify(payload) };
    }
  }

  function installNativeWebsocketProjection() {
    if (installNativeWebsocketProjection.registered || !window.rcp?.postInit) return;
    installNativeWebsocketProjection.registered = true;
    window.rcp.postInit("rcp-fe-lol-champ-select", (api) => {
      try {
        const ws = api.champSelectBinding.socket._websocket;
        if (!ws || ws.__roseJadeReadProjection) return;
        const parentOnMessage = ws.onmessage;
        ws.onmessage = function roseJadeProjectedMessage(event) {
          try {
            const payload = JSON.parse(event.data);
            if (payload?.[1] !== "OnJsonApiEvent") {
              return parentOnMessage.call(this, event);
            }
            const eventData = payload[2];
            if (eventData?.uri === "/lol-champ-select/v1/skin-selector-info") {
              const selectedSkinId = eventData.data?.selectedSkinId;
              if (shouldSuppressVisualRollback(selectedSkinId)) {
                log("info", "Suppressed classic selector rollback", { selectedSkinId });
                return;
              }
            } else if (eventData?.uri === "/lol-champ-select/v1/session") {
              const protection = window.__roseJadeVisualProtection;
              if (
                protection?.active &&
                rewriteSessionSelection(eventData.data, numeric(protection.desiredRawSkinId))
              ) {
                return parentOnMessage.call(this, cloneWebsocketEvent(event, payload));
              }
            }
          } catch (error) {
            log("warn", "Classic websocket projection failed", String(error));
          }
          return parentOnMessage.call(this, event);
        };
        ws.__roseJadeReadProjection = true;
        log("info", "Classic websocket projection installed");
      } catch (error) {
        log("warn", "Classic websocket projection unavailable", String(error));
      }
    });
  }

  function installNativeReadProjection() {
    if (window.fetch?.__roseJadeReadProjection) return;

    const projectedFetch = async function roseJadeProjectedFetch(input, init) {
      const path = requestPath(input);
      const method = requestMethod(input, init);
      if (
        active &&
        visualCarrierProtectionActive &&
        method === "PATCH" &&
        path === "/lol-champ-select/v1/session/my-selection"
      ) {
        try {
          const body = JSON.parse(String(init?.body || "{}"));
          const requestedRawSkinId = numeric(body.selectedSkinId) || 0;
          if (catalogEntryForRawSkinId(requestedRawSkinId)) {
            log("info", "Deferred classic LCU write to finalization", {
              requestedRawSkinId,
            });
            return new Response(null, { status: 204 });
          }
        } catch (_) {
          // Let malformed or unrelated requests follow the native path.
        }
      }
      const response = await nativeFetch(input, init);
      if (
        method !== "GET" ||
        !response?.ok ||
        (path !== "/lol-champ-select/v1/skin-selector-info" &&
          path !== "/lol-champ-select/v1/session")
      ) {
        return response;
      }

      try {
        const data = await response.clone().json();
        if (!rewriteNativeRead(path, data)) return response;

        const rewriteKey = `${path}|${desiredVisualSelection?.rawSkinId || 0}`;
        if (rewriteKey !== lastReadRewriteKey) {
          lastReadRewriteKey = rewriteKey;
          log("info", "Projected classic visual selection into native read", {
            path,
            desiredRawSkinId: desiredVisualSelection?.rawSkinId || 0,
          });
        }
        const headers = new Headers(response.headers);
        headers.delete("content-length");
        headers.delete("content-encoding");
        return new Response(JSON.stringify(data), {
          status: response.status,
          statusText: response.statusText,
          headers,
        });
      } catch (error) {
        log("warn", "Classic native read projection failed", {
          path,
          error: String(error),
        });
        return response;
      }
    };
    projectedFetch.__roseJadeReadProjection = true;
    window.fetch = projectedFetch;
  }

  function syncVisualSelection(entry, reason, userInitiated = false) {
    if (!bridge || !entry?.name || !entry.resourceSkinId) return;
    if (userInitiated) selectionGeneration += 1;
    try {
      // Python validates this ID against the active JADE carousel before it
      // updates the same injection state used by regular champion select.
      bridge.send({
        type: "classic-skin-selection",
        schemaVersion: 1,
        mode: JADE_MODE,
        primeChampionId: entry.championId,
        modeChampionId: entry.rawChampionId,
        carrierLcuSkinId: modeDefaultRawSkinId || fallbackModeDefaultRawSkinId(),
        carrierSkinNumber: (modeDefaultRawSkinId || fallbackModeDefaultRawSkinId()) % 1000,
        visualSkinId: entry.resourceSkinId,
        skin: entry.name,
        originalName: entry.name,
        skinId: entry.resourceSkinId,
        rawSkinId: entry.rawSkinId,
        rawChampionId: entry.rawChampionId,
        baseRawSkinId: modeDefaultRawSkinId || fallbackModeDefaultRawSkinId(),
        catalog: catalogBridgeEntries(),
        source: "jade-wheel",
        reason,
        userInitiated,
        selectionGeneration,
        available: entry.available === true,
        timestamp: Date.now(),
      });
      log("info", "Classic visual skin synced", {
        reason,
        rawSkinId: entry.rawSkinId,
        resourceSkinId: entry.resourceSkinId,
        name: entry.name,
      });
    } catch (error) {
      log("warn", "Classic visual skin sync failed", {
        reason,
        resourceSkinId: entry.resourceSkinId,
        error: String(error),
      });
    }
  }

  function catalogBridgeEntries() {
    const entries = [];
    const append = (skin, fallbackChampionId) => {
      if (!skin || typeof skin !== "object") return;
      const id = numeric(skin.id ?? skin.skinId) || 0;
      if (id > 0) {
        entries.push({
          id,
          championId: numeric(skin.championId) || fallbackChampionId,
        });
      }
      for (const child of variantsOf(skin)) {
        append(child, fallbackChampionId);
      }
    };
    for (const entry of catalog) append(entry.rawSkin, entry.rawChampionId);
    return entries;
  }

  function syncModeCatalog(reason) {
    if (!bridge || !rawChampionId || !catalog.length) return;
    const entries = catalogBridgeEntries();
    const baseRawSkinId = modeDefaultRawSkinId || fallbackModeDefaultRawSkinId();
    const assetSnapshot = catalogAssetSnapshot();
    const key = `${rawChampionId}|${baseRawSkinId}|${assetSnapshot
      .map((entry) => `${entry.rawSkinId}:${entry.visualPath}`)
      .join(",")}`;
    if (key === lastCatalogSyncKey && reason !== "forced-refresh") return;
    lastCatalogSyncKey = key;
    const defaultAsset = assetSnapshot.find(
      (entry) => entry.rawSkinId === baseRawSkinId
    ) || null;
    window.__roseJadeCatalogAssets = assetSnapshot;
    window.__roseJadeModeDefaultAsset = defaultAsset;
    bridge.send({
      type: "classic-mode-catalog",
      schemaVersion: 1,
      mode: JADE_MODE,
      primeChampionId: championId,
      modeChampionId: rawChampionId,
      carrierLcuSkinId: baseRawSkinId,
      carrierSkinNumber: baseRawSkinId % 1000,
      rawChampionId,
      selectedRawSkinId,
      baseRawSkinId,
      catalog: entries,
      reason,
      timestamp: Date.now(),
    });
    log("info", "Classic skin catalog synced", {
      reason,
      rawChampionId,
      baseRawSkinId,
      skinCount: entries.length,
      defaultAsset,
    });
  }

  function setVisualProtection(entry, reason, force = false) {
    const protectedEntry = active && entry && (force || (!entry.available && !entry.isBase))
      ? entry
      : null;
    const carrierRawSkinIds = protectedEntry
      ? Array.from(
          new Set(
            [
              jadeSkinId(protectedEntry.championId * 1000),
              ...catalog
                .filter((candidate) => candidate.isBase)
                .flatMap((candidate) => [candidate.rawSkinId, candidate.resourceSkinId]),
            ]
              .filter((value) => Number.isFinite(value) && value > 0)
          )
        )
      : [];
    const detail = {
      active: Boolean(protectedEntry),
      reason,
      desiredRawSkinId: protectedEntry?.rawSkinId || 0,
      desiredResourceSkinId: protectedEntry?.resourceSkinId || 0,
      carrierRawSkinIds,
    };
    const protectionKey = JSON.stringify(detail);
    window.__roseJadeVisualProtection = detail;
    window.dispatchEvent(new CustomEvent(VISUAL_PROTECTION_EVENT, { detail }));
    if (protectionKey !== lastVisualProtectionKey) {
      lastVisualProtectionKey = protectionKey;
      log("info", detail.active ? "Classic visual selection protected" : "Classic visual protection cleared", detail);
    }
  }

  function shouldPatchLcuSelection() {
    if (!active) return true;
    const visualEntry = desiredVisualSelection || catalog.find(
      (entry) => entry.rawSkinId === lastVisualCenterRawSkinId
    );
    return !visualEntry || visualEntry.available || visualEntry.isBase;
  }

  function isJadeClassicContext() {
    return String(gameMode || "").toUpperCase() === JADE_MODE ||
      Number(queueId) === 3260 || Number(mapId) === JADE_MAP_ID;
  }

  function isChampSelectPhase() {
    return phase === "ChampSelect" || phase === "FINALIZATION" || phase === "GameStart";
  }

  function normalizeAssetPath(value) {
    const input = String(value || "").trim();
    if (!input) return "";
    try {
      return decodeURIComponent(new URL(input, window.location.origin).pathname).toLowerCase();
    } catch (_) {
      return input.split(/[?#]/, 1)[0].toLowerCase();
    }
  }

  function assetFileName(value) {
    const path = normalizeAssetPath(value);
    return path.slice(path.lastIndexOf("/") + 1);
  }

  function normalizeCatalogEntry(entry) {
    if (!entry || typeof entry !== "object") return null;
    const rawSkinId = numeric(entry.id ?? entry.skinId) || 0;
    if (!rawSkinId) return null;
    const rawEntryChampion = numeric(entry.championId) || Math.floor(rawSkinId / 1000);
    const normalizedSkinId = resourceSkinId(rawSkinId);
    const ownership = entry.ownership && typeof entry.ownership === "object"
      ? entry.ownership
      : {};
    const rental = ownership.rental && typeof ownership.rental === "object"
      ? ownership.rental
      : {};
    const isBase = isModeDefaultRawSkinId(rawSkinId);
    const isHiddenModeSkin0 = rawSkinId % 1000 === 0 && !isBase;
    const available = isBase || ownership.owned === true || rental.rented === true;
    const paths = [
      entry.tilePath,
      entry.splashPath,
      entry.uncenteredSplashPath,
      entry.loadScreenPath,
    ].filter(Boolean);
    return {
      rawChampionId: rawEntryChampion,
      championId: resourceChampionId(rawEntryChampion),
      rawSkinId,
      resourceSkinId: normalizedSkinId,
      name: String(entry.name || ""),
      isBase,
      isHiddenModeSkin0,
      available,
      visualPath: String(
        entry.loadScreenPath || entry.splashPath || entry.uncenteredSplashPath || entry.tilePath || ""
      ),
      paths: paths.map(normalizeAssetPath).filter(Boolean),
      files: paths.map(assetFileName).filter(Boolean),
      rawSkin: entry,
    };
  }

  function variantsOf(skin) {
    const variants = [
      ...(Array.isArray(skin?.childSkins) ? skin.childSkins : []),
      ...(Array.isArray(skin?.chromas) ? skin.chromas : []),
    ];
    const seen = new Set();
    return variants.filter((variant) => {
      const id = numeric(variant?.id ?? variant?.skinId) || 0;
      if (!id || seen.has(id)) return false;
      seen.add(id);
      return true;
    });
  }

  function catalogAssetDetails(entry) {
    if (!entry) return null;
    const skin = entry.rawSkin && typeof entry.rawSkin === "object"
      ? entry.rawSkin
      : {};
    return {
      rawSkinId: entry.rawSkinId,
      resourceSkinId: entry.resourceSkinId,
      name: entry.name,
      isBase: entry.isBase,
      available: entry.available,
      visualPath: entry.visualPath,
      tilePath: String(skin.tilePath || ""),
      splashPath: String(skin.splashPath || ""),
      uncenteredSplashPath: String(skin.uncenteredSplashPath || ""),
      loadScreenPath: String(skin.loadScreenPath || ""),
    };
  }

  function catalogAssetSnapshot() {
    return catalog.map(catalogAssetDetails).filter(Boolean);
  }

  function getModeSkinData(rawSkinId) {
    const id = numeric(rawSkinId);
    if (!active || id === null) return null;
    for (const entry of catalog) {
      if (entry.rawSkinId === id) return entry.rawSkin;
      const child = variantsOf(entry.rawSkin).find(
        (candidate) => numeric(candidate?.id ?? candidate?.skinId) === id
      );
      if (child) return child;
    }
    return null;
  }

  function variantPresentation(rawSkinId, fallbackEntry) {
    const skin = getModeSkinData(rawSkinId);
    const colors = Array.isArray(skin?.colors)
      ? skin.colors.filter(Boolean)
      : [];
    return {
      skinName: String(skin?.name || fallbackEntry?.name || ""),
      rawSkinId: numeric(rawSkinId) || fallbackEntry?.rawSkinId || 0,
      resourceSkinId: resourceSkinId(rawSkinId || fallbackEntry?.rawSkinId || 0),
      colors,
      primaryColor: String(skin?.primaryColor || colors[0] || ""),
    };
  }

  function catalogEntryForRawSkinId(rawSkinId) {
    const id = numeric(rawSkinId);
    if (id === null) return null;
    return catalog.find((entry) => {
      if (entry.rawSkinId === id) return true;
      return variantsOf(entry.rawSkin).some(
        (child) => numeric(child?.id ?? child?.skinId) === id
      );
    }) || null;
  }

  function catalogSelectionForResourceSkinId(resourceId) {
    const id = numeric(resourceId) || 0;
    const isResourceBase = championId > 0 && id === championId * 1000;
    if (isResourceBase) {
      const defaultRawSkinId = modeDefaultRawSkinId || fallbackModeDefaultRawSkinId();
      const defaultEntry = catalog.find((entry) => entry.rawSkinId === defaultRawSkinId);
      if (defaultEntry) {
        return { entry: defaultEntry, rawSkinId: defaultEntry.rawSkinId };
      }
    }
    for (const entry of catalog) {
      if (entry.resourceSkinId === id) {
        return { entry, rawSkinId: entry.rawSkinId };
      }
      const child = variantsOf(entry.rawSkin).find(
        (candidate) => resourceSkinId(candidate?.id ?? candidate?.skinId) === id
      );
      if (child) {
        return {
          entry,
          rawSkinId: numeric(child?.id ?? child?.skinId) || entry.rawSkinId,
        };
      }
    }
    return null;
  }

  function projectResourceSelection(resourceId, reason = "external-state") {
    if (!active || !catalog.length) return false;
    const selection = catalogSelectionForResourceSkinId(resourceId);
    if (!selection) return false;
    const { entry, rawSkinId } = selection;
    if (reason === "random-state" || reason === "chroma-state") {
      pendingHistoricResourceSkinId = 0;
      lastAppliedHistoricResourceSkinId = 0;
    }
    visualCarrierProtectionActive = !isModeDefaultResourceSkinId(resourceId);
    projectedVariantRawSkinId = rawSkinId;
    desiredVisualSelection = entry;
    projectedCatalogIndex = catalog.indexOf(entry);
    lastVisualCenterRawSkinId = 0;
    clearUserNavigation();
    setVisualProtection(entry, reason, visualCarrierProtectionActive);
    scheduleNativeProjection(projectedCatalogIndex);
    adaptNativeController();
    log("info", "Classic resource selection projected into native selector", {
      reason,
      resourceSkinId: numeric(resourceId) || 0,
      visualRawSkinId: entry.rawSkinId,
      variantRawSkinId: rawSkinId,
    });
    return true;
  }

  function setHistoricPresentationReady(ready, reason) {
    window.dispatchEvent(new CustomEvent("rose-jade-historic-presentation-state", {
      detail: { ready: ready === true, reason: String(reason || "") },
    }));
  }

  function cancelHistoricVisualRestore(reason, hidePresentation = false) {
    historicRestoreGeneration += 1;
    historicRestoreInProgress = false;
    if (hidePresentation) setHistoricPresentationReady(false, reason);
  }

  function finishHistoricVisualSelection(resourceId, generation) {
    if (
      !active || generation !== historicRestoreGeneration ||
      pendingHistoricResourceSkinId !== resourceId
    ) {
      return;
    }
    if (projectResourceSelection(resourceId, "historic-restore")) {
      const selection = catalogSelectionForResourceSkinId(resourceId);
      scheduleNativeProjection(projectedCatalogIndex, () => {
        if (
          !active || generation !== historicRestoreGeneration ||
          pendingHistoricResourceSkinId !== resourceId
        ) {
          return;
        }
        historicRestoreInProgress = false;
        lastAppliedHistoricResourceSkinId = resourceId;
        const presentation = variantPresentation(
          selection?.rawSkinId,
          selection?.entry
        );
        window.dispatchEvent(new CustomEvent("rose-jade-historic-presentation", {
          detail: presentation,
        }));
        log("info", "Classic history projected after native default staging", {
          historicResourceSkinId: resourceId,
          visualRawSkinId: selection?.entry?.rawSkinId || 0,
          variantRawSkinId: selection?.rawSkinId || 0,
        });
      });
      return;
    }
    historicRestoreInProgress = false;
  }

  function applyHistoricVisualSelection() {
    if (!active || !pendingHistoricResourceSkinId || !catalog.length) return;
    if (!isModeDefaultResourceSkinId(pendingHistoricResourceSkinId)) {
      const selection = catalogSelectionForResourceSkinId(pendingHistoricResourceSkinId);
      if (!selection) return;
      if (pendingHistoricResourceSkinId === lastAppliedHistoricResourceSkinId) {
        // The catalog is rebuilt every two seconds, so its entry objects are
        // not stable. Rebind the active projection by ID without replaying the
        // default-card staging animation.
        visualCarrierProtectionActive = true;
        projectedVariantRawSkinId = selection.rawSkinId;
        desiredVisualSelection = selection.entry;
        projectedCatalogIndex = catalog.indexOf(selection.entry);
        setVisualProtection(selection.entry, "historic-catalog-refresh", true);
        adaptNativeController();
        return;
      }
      if (historicRestoreInProgress) return;
      const defaultEntry = catalog.find((entry) => entry.isBase) || null;
      if (!defaultEntry || defaultEntry === selection.entry) {
        finishHistoricVisualSelection(
          pendingHistoricResourceSkinId,
          historicRestoreGeneration
        );
        return;
      }
      historicRestoreInProgress = true;
      const resourceId = pendingHistoricResourceSkinId;
      const generation = ++historicRestoreGeneration;
      setHistoricPresentationReady(false, "historic-default-stage");
      visualCarrierProtectionActive = false;
      projectedVariantRawSkinId = defaultEntry.rawSkinId;
      desiredVisualSelection = defaultEntry;
      projectedCatalogIndex = catalog.indexOf(defaultEntry);
      lastVisualCenterRawSkinId = 0;
      clearUserNavigation();
      setVisualProtection(null, "historic-default-stage");
      adaptNativeController();
      scheduleNativeProjection(projectedCatalogIndex, () => {
        setTimeout(
          () => finishHistoricVisualSelection(resourceId, generation),
          100
        );
      });
      log("info", "Classic history restore staged from native default", {
        historicResourceSkinId: resourceId,
        defaultRawSkinId: defaultEntry.rawSkinId,
      });
      return;
    }
    cancelHistoricVisualRestore("historic-default", true);
    pendingHistoricResourceSkinId = 0;
    lastAppliedHistoricResourceSkinId = 0;
  }

  function handleHistoricState(data) {
    if (randomModeActive) {
      cancelHistoricVisualRestore("random-mode", true);
      pendingHistoricResourceSkinId = 0;
      lastAppliedHistoricResourceSkinId = 0;
      return;
    }
    pendingHistoricResourceSkinId = data?.active === true
      ? numeric(data.historicSkinId) || 0
      : 0;
    if (!pendingHistoricResourceSkinId) {
      cancelHistoricVisualRestore("historic-disabled", true);
      lastAppliedHistoricResourceSkinId = 0;
    }
    if (pendingHistoricResourceSkinId) applyHistoricVisualSelection();
  }

  function handleRandomModeState(data) {
    randomModeActive = data?.active === true;
    if (!randomModeActive) return;
    cancelHistoricVisualRestore("random-mode", true);
    pendingHistoricResourceSkinId = 0;
    lastAppliedHistoricResourceSkinId = 0;
    projectedVariantRawSkinId = 0;
    clearUserNavigation();
    const defaultEntry = catalog.find((entry) => entry.isBase) || null;
    if (!defaultEntry) return;
    visualCarrierProtectionActive = false;
    desiredVisualSelection = defaultEntry;
    projectedCatalogIndex = catalog.indexOf(defaultEntry);
    lastVisualCenterRawSkinId = 0;
    setVisualProtection(null, "random-default-presentation");
    adaptNativeController();
    scheduleNativeProjection(projectedCatalogIndex);
    log("info", "Random mode skipped history and centered the classic default", {
      rawSkinId: defaultEntry.rawSkinId,
      resourceSkinId: defaultEntry.resourceSkinId,
    });
  }

  function findNativePane() {
    const center = document.querySelector(".champion-select-center-container--picking-skins");
    const candidate = center?.querySelector(".skins-pane__content") || null;
    if (!candidate) return null;
    const rect = candidate.getBoundingClientRect();
    if (rect.width < 200 || rect.height < 120) return null;
    return candidate;
  }

  function nativeCards(host = pane) {
    if (!host) return [];
    const cards = Array.from(host.children).filter(
      (child) => child.classList?.contains("skins-pane__skin-card")
    );

    // JADE recycles its five card nodes and does not keep DOM order aligned
    // with their visual left-to-right order. Historic projection can move the
    // center node to DOM index 0, which used to erase every inferred card on
    // its left. Always calculate carousel offsets from rendered positions.
    return cards
      .map((card, domIndex) => {
        const rect = card.getBoundingClientRect();
        const visualX = rect.width > 0
          ? rect.left + rect.width / 2
          : Number.POSITIVE_INFINITY;
        return { card, domIndex, visualX };
      })
      .sort((left, right) => {
        if (left.visualX !== right.visualX) return left.visualX - right.visualX;
        return left.domIndex - right.domIndex;
      })
      .map(({ card }) => card);
  }

  function selectedNativeCard(cards) {
    return (
      cards.find((card) => card.classList.contains("skins-pane__skin-card--center-tile")) ||
      cards.find(
        (card) =>
          card.classList.contains("skins-pane__skin-card--selected-skin") &&
          !card.classList.contains("skins-pane__skin-card--placeholder")
      ) ||
      null
    );
  }

  function elementSkinId(card) {
    const attributes = ["data-skin-id", "data-champion-skin-id", "skin-id"];
    const original = originalCardState.get(card);
    for (const attribute of attributes) {
      const value = numeric(original?.attributes.get(attribute));
      if (value && value > 0) return value;
    }

    // Ignore the adapter attributes on the card itself. Native JADE recycles
    // these nodes while moving the carousel, so those values may be stale.
    const nodes = card.querySelectorAll(
      "[data-skin-id], [data-champion-skin-id], [skin-id]"
    );
    for (const node of nodes) {
      for (const attribute of attributes) {
        const value = numeric(node.getAttribute?.(attribute));
        if (value && value > 0) return value;
      }
    }
    return 0;
  }

  function cardAssets(card) {
    const values = [];
    for (const image of card.querySelectorAll("img[src], source[srcset]")) {
      values.push(image.currentSrc, image.getAttribute("src"), image.getAttribute("srcset"));
    }
    for (const node of [card, ...card.querySelectorAll("[style*='background']")]) {
      const background = node.style?.backgroundImage || "";
      const match = background.match(/url\(["']?([^"')]+)["']?\)/i);
      if (match) values.push(match[1]);
    }
    const paths = values.map(normalizeAssetPath).filter(Boolean);
    return {
      paths,
      files: paths.map(assetFileName).filter(Boolean),
    };
  }

  function matchCardToCatalog(card) {
    // JADE recycles its five card nodes while changing their images. Match the
    // live visual assets before attributes remembered from an earlier slot.
    const assets = cardAssets(card);
    for (const entry of catalog) {
      if (entry.paths.some((path) => assets.paths.includes(path))) return entry;
    }
    for (const entry of catalog) {
      if (entry.files.some((file) => file && assets.files.includes(file))) return entry;
    }

    const label = String(
      card.getAttribute("aria-label") ||
      card.getAttribute("title") ||
      card.querySelector("img[alt]")?.getAttribute("alt") ||
      ""
    ).trim();
    if (label) {
      const nameMatch = catalog.find((entry) => entry.name && entry.name === label);
      if (nameMatch) return nameMatch;
    }

    const directId = elementSkinId(card);
    if (directId) {
      const rawMatch = catalog.find((entry) => entry.rawSkinId === directId);
      if (rawMatch) return rawMatch;
      const resourceId = resourceSkinId(directId);
      const resourceMatch = catalog.find((entry) => entry.resourceSkinId === resourceId);
      if (resourceMatch) return resourceMatch;
    }
    return null;
  }

  function rememberOriginalCardState(card) {
    if (originalCardState.has(card)) return;
    const attributes = new Map();
    for (const name of [
      "data-skin-id",
      "data-champion-skin-id",
      "skin-id",
      "data-rose-lcu-skin-id",
      "data-rose-resource-skin-id",
      "data-rose-carousel-offset",
    ]) {
      attributes.set(name, card.hasAttribute(name) ? card.getAttribute(name) : null);
    }
    originalCardState.set(card, {
      attributes,
      classes: new Set(
        Array.from(card.classList).filter(
          (name) => COMPATIBILITY_CLASSES.includes(name)
        )
      ),
    });
  }

  function clearCompatibility(card) {
    if (!card) return;
    adaptedCardState.delete(card);
    card.querySelectorAll(".skins-pane__locked-overlay, .skins-pane__locked-icon").forEach(
      (element) => {
        const original = lockOverlayState.get(element);
        if (!original) return;
        if (original.display) element.style.setProperty("display", original.display.value, original.display.priority);
        else element.style.removeProperty("display");
        if (original.pointerEvents) {
          element.style.setProperty(
            "pointer-events",
            original.pointerEvents.value,
            original.pointerEvents.priority
          );
        } else {
          element.style.removeProperty("pointer-events");
        }
        lockOverlayState.delete(element);
      }
    );
    card.classList.remove(UNLOCKED_CLASS, EMPTY_CLASS);
    const original = originalCardState.get(card);
    card.querySelectorAll("img").forEach((image) => {
      if (image.hasAttribute("data-rose-jade-projected-image")) {
        image.remove();
        return;
      }
      const state = projectedImageState.get(image);
      if (!state) return;
      for (const [name, value] of Object.entries(state)) {
        if (value === null) image.removeAttribute(name);
        else image.setAttribute(name, value);
      }
      projectedImageState.delete(image);
    });
    for (const className of COMPATIBILITY_CLASSES) {
      if (!original?.classes.has(className)) card.classList.remove(className);
    }
    for (const name of [
      "data-skin-id",
      "data-rose-lcu-skin-id",
      "data-rose-resource-skin-id",
      "data-rose-carousel-offset",
    ]) {
      const value = original?.attributes.get(name);
      if (value === null || value === undefined) card.removeAttribute(name);
      else card.setAttribute(name, value);
    }
  }

  function unlockNativeCard(card, entry) {
    if (!card || !entry || entry.available || entry.isBase) return;
    card.classList.add(UNLOCKED_CLASS);
    card.querySelectorAll(".skins-pane__locked-overlay, .skins-pane__locked-icon").forEach(
      (element) => {
        if (!lockOverlayState.has(element)) {
          lockOverlayState.set(element, {
            display: element.style.getPropertyValue("display")
              ? {
                  value: element.style.getPropertyValue("display"),
                  priority: element.style.getPropertyPriority("display"),
                }
              : null,
            pointerEvents: element.style.getPropertyValue("pointer-events")
              ? {
                  value: element.style.getPropertyValue("pointer-events"),
                  priority: element.style.getPropertyPriority("pointer-events"),
                }
              : null,
          });
        }
        element.style.setProperty("display", "none", "important");
        element.style.setProperty("pointer-events", "none", "important");
      }
    );
  }

  function applyCompatibility(
    card,
    entry,
    offset,
    selected,
    stabilize = false
  ) {
    rememberOriginalCardState(card);
    const stateKey = entry
      ? `${entry.rawSkinId}|${entry.resourceSkinId}|${offset}|${selected}|${entry.available}`
      : `empty|${offset}`;
    const alreadyAdapted =
      adaptedCardState.get(card) === stateKey &&
      card.classList.contains(CARD_CLASS) &&
      card.classList.contains(SELECTED_CLASS) === selected &&
      card.getAttribute("data-rose-carousel-offset") === String(offset) &&
      card.classList.contains(UNLOCKED_CLASS) === !entry?.available &&
      card.getAttribute("data-rose-lcu-skin-id") === String(entry?.rawSkinId || "");
    card.classList.toggle("rose-jade-native-card--stabilizing", stabilize);
    card.classList.toggle(EMPTY_CLASS, !entry);
    if (alreadyAdapted) {
      // JADE recycles card nodes and may recreate the native lock overlay
      // after our first pass. Reapply the idempotent unlock state here.
      unlockNativeCard(card, entry);
      adaptedCards.add(card);
      return;
    }
    clearCompatibility(card);
    if (!entry || card.classList.contains("skins-pane__skin-card--placeholder")) {
      card.classList.toggle(EMPTY_CLASS, !entry);
      return;
    }
    card.classList.add(CARD_CLASS);
    card.classList.toggle(SELECTED_CLASS, selected);
    card.setAttribute("data-rose-carousel-offset", String(offset));
    card.setAttribute("data-rose-resource-skin-id", String(entry.resourceSkinId));
    card.setAttribute("data-rose-lcu-skin-id", String(entry.rawSkinId));
    unlockNativeCard(card, entry);
    adaptedCardState.set(card, stateKey);
    adaptedCards.add(card);
  }

  function projectCardVisual(card, entry) {
    const visualPath = entry?.visualPath || "";
    if (!card || !visualPath) return;
    if (!card.querySelector(".skins-pane__skin-image")) {
      const image = document.createElement("img");
      image.className = "skins-pane__skin-image";
      image.setAttribute("data-rose-jade-projected-image", "true");
      card.appendChild(image);
    }
    card.setAttribute("aria-label", entry.name);
    card.setAttribute("title", entry.name);
    for (const image of card.querySelectorAll(".skins-pane__skin-image")) {
      if (!image.hasAttribute("data-rose-jade-projected-image") && !projectedImageState.has(image)) {
        projectedImageState.set(image, {
          src: image.hasAttribute("src") ? image.getAttribute("src") : null,
          srcset: image.hasAttribute("srcset") ? image.getAttribute("srcset") : null,
          alt: image.hasAttribute("alt") ? image.getAttribute("alt") : null,
        });
      }
      if (image.getAttribute("src") !== visualPath) image.setAttribute("src", visualPath);
      image.removeAttribute("srcset");
      image.setAttribute("alt", entry.name);
    }
  }

  function beginUserNavigation(targetRawSkinId = 0) {
    if (pendingHistoricResourceSkinId || lastAppliedHistoricResourceSkinId) {
      setHistoricPresentationReady(false, "user-navigation");
    }
    if (visualCarrierProtectionActive) {
      visualCarrierProtectionActive = false;
      projectedCatalogIndex = -1;
      setVisualProtection(null, "user-navigation");
      for (const card of Array.from(adaptedCards)) clearCompatibility(card);
      adaptedCards.clear();
    }
    pendingUserNavigation = true;
    pendingUserNavigationUntil = Date.now() + USER_NAVIGATION_WINDOW_MS;
    pendingUserTargetRawSkinId = numeric(targetRawSkinId) || 0;
    pendingUserSelectionPublished = false;
  }

  function clearUserNavigation() {
    pendingUserNavigation = false;
    pendingUserNavigationUntil = 0;
    pendingUserTargetRawSkinId = 0;
    pendingUserSelectionPublished = false;
  }

  function publishNativeCardSelection(entry, reason) {
    if (!entry) return;
    if (pendingHistoricResourceSkinId || lastAppliedHistoricResourceSkinId) {
      cancelHistoricVisualRestore("explicit-selection", true);
      pendingHistoricResourceSkinId = 0;
      lastAppliedHistoricResourceSkinId = 0;
    }
    projectedVariantRawSkinId = 0;
    visualCarrierProtectionActive = !entry.available && !entry.isBase;
    setVisualProtection(entry, reason, visualCarrierProtectionActive);
    desiredVisualSelection = entry;
    projectedCatalogIndex = catalog.indexOf(entry);
    syncVisualSelection(entry, reason, true);
    pendingUserSelectionPublished = true;
  }

  function scheduleNativeProjection(targetIndex, onComplete = null) {
    nativeProjectionTargetIndex = Number.isInteger(targetIndex) ? targetIndex : -1;
    nativeProjectionComplete = typeof onComplete === "function" ? onComplete : null;
    const cards = nativeCards();
    const centerCard = selectedNativeCard(cards);
    const centerEntry = centerCard ? matchCardToCatalog(centerCard) : null;
    nativeProjectionCurrentIndex = centerEntry ? catalog.indexOf(centerEntry) : -1;
    if (nativeProjectionTimer) clearTimeout(nativeProjectionTimer);
    nativeProjectionTimer = setTimeout(stepNativeProjection, 0);
  }

  function stepNativeProjection() {
    nativeProjectionTimer = null;
    if (!active || nativeProjectionTargetIndex < 0 || !catalog.length) return;
    const currentIndex = nativeProjectionCurrentIndex;
    if (currentIndex === nativeProjectionTargetIndex) {
      const complete = nativeProjectionComplete;
      nativeProjectionTargetIndex = -1;
      nativeProjectionCurrentIndex = -1;
      nativeProjectionComplete = null;
      adaptNativeController();
      if (complete) setTimeout(complete, 0);
      return;
    }
    if (currentIndex < 0) {
      nativeProjectionTimer = setTimeout(stepNativeProjection, 80);
      return;
    }
    const direction = nativeProjectionTargetIndex < currentIndex ? "left" : "right";
    const arrow = pane?.parentElement?.querySelector(`.skins-pane__arrow--${direction}`);
    if (!arrow || arrow.classList.contains("skins-pane__arrow--disabled")) return;
    drivingNativeProjection = true;
    arrow.click();
    drivingNativeProjection = false;
    nativeProjectionCurrentIndex += direction === "left" ? -1 : 1;
    nativeProjectionTimer = setTimeout(stepNativeProjection, 80);
  }

  function syncFooterPresentation(entry) {
    if (!pane || !entry) return;
    const root = pane.parentElement || pane;
    const title = root.querySelector(".skins-pane__footer .skins-pane__skin-title");
    const subtitle = root.querySelector(".skins-pane__footer .skins-pane__sub-title");
    if (title && title.textContent !== entry.name) title.textContent = entry.name;
    if (!subtitle) return;
    const status = entry.available || entry.isBase
      ? "OWNED"
      : "UNLOCKED";
    if (subtitle.textContent !== status) subtitle.textContent = status;
    subtitle.classList.add("skins-pane__sub-title--unlocked");
  }

  function handleNativePaneClick(event) {
    if (
      event.target?.closest?.(
        ".chroma-button, .lu-chroma-button, .forms-wheel-button, .lu-random-dice-button"
      )
    ) {
      return;
    }
    const card = event.target?.closest?.(`.${CARD_CLASS}`);
    if (!card || !pane?.contains(card)) return;
    const clickRawSkinId = numeric(card.getAttribute("data-rose-lcu-skin-id")) || 0;
    if (Date.now() <= pointerSelectionUntil && pointerSelectionRawSkinId) {
      if (pointerSelectionCommitted) return;
      const pointerEntry = catalog.find(
        (candidate) => candidate.rawSkinId === pointerSelectionRawSkinId
      );
      if (!pointerEntry) return;
      if (clickRawSkinId !== pointerSelectionRawSkinId) {
        log("info", "Ignored recycled classic carousel click", {
          pointerRawSkinId: pointerSelectionRawSkinId,
          clickRawSkinId,
        });
      }
      beginUserNavigation(pointerEntry.rawSkinId);
      if (card.classList.contains("skins-pane__skin-card--center-tile")) {
        publishNativeCardSelection(pointerEntry, "native-card-click");
        clearUserNavigation();
      }
      pointerSelectionCommitted = true;
      return;
    }
    const entry = catalog.find((candidate) => candidate.rawSkinId === clickRawSkinId);
    if (!entry) return;
    beginUserNavigation(entry.rawSkinId);
    if (card.classList.contains("skins-pane__skin-card--center-tile")) {
      publishNativeCardSelection(entry, "native-card-click");
      clearUserNavigation();
    }
  }

  function handleUserNavigation(event) {
    if (!active) return;
    const arrow = event.target?.closest?.(
      ".skins-pane__arrow--left, .skins-pane__arrow--right"
    );
    if (arrow && !drivingNativeProjection) {
      const cards = nativeCards();
      const centerCard = selectedNativeCard(cards);
      const centerEntry = centerCard ? matchCardToCatalog(centerCard) : null;
      const currentIndex = centerEntry ? catalog.indexOf(centerEntry) : -1;
      const direction = arrow.classList.contains("skins-pane__arrow--left") ? -1 : 1;
      const target = currentIndex >= 0 ? catalog[currentIndex + direction] : null;
      if (target) {
        pendingHistoricResourceSkinId = 0;
        projectedVariantRawSkinId = 0;
        beginUserNavigation(target.rawSkinId);
      }
      return;
    }
    if (
      event.target?.closest?.(
        ".chroma-button, .lu-chroma-button, .forms-wheel-button, .lu-random-dice-button"
      )
    ) {
      return;
    }
    const card = event.target?.closest?.(`.${CARD_CLASS}`);
    if (card && pane?.contains(card)) {
      pendingHistoricResourceSkinId = 0;
      projectedVariantRawSkinId = 0;
      const rawSkinId = numeric(card.getAttribute("data-rose-lcu-skin-id")) || 0;
      const entry = catalog.find((candidate) => candidate.rawSkinId === rawSkinId);
      if (!entry) return;
      pointerSelectionRawSkinId = entry.rawSkinId;
      pointerSelectionUntil = Date.now() + 1500;
      pointerSelectionCommitted = false;
      beginUserNavigation(entry.rawSkinId);
      return;
    }
    if (event.target?.closest?.(".champion-select-center-container--picking-skins")) {
      pendingHistoricResourceSkinId = 0;
      projectedVariantRawSkinId = 0;
      beginUserNavigation();
    }
  }

  function handleUserNavigationKey(event) {
    if (active && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
      pendingHistoricResourceSkinId = 0;
      projectedVariantRawSkinId = 0;
      beginUserNavigation();
    }
  }

  function ensureOverlay() {
    if (!pane) return;
    if (overlay && overlay.isConnected) return;
    document.getElementById(ROOT_ID)?.remove();
    overlay = document.createElement("div");
    overlay.id = ROOT_ID;
    overlay.className = "rose-jade-wheel-jade-pane";
    overlay.setAttribute("aria-hidden", "true");

    pane.classList.add(HOST_CLASS);
    pane.addEventListener("click", handleNativePaneClick, true);
    pane.appendChild(overlay);
    window.dispatchEvent(
      new CustomEvent("rose-jade-wheel-layout", {
        detail: { active: true, rootId: ROOT_ID, native: true },
      })
    );
  }

  function ensureHistoryAnchor(centerCard) {
    if (!centerCard) return;
    document.querySelectorAll(".rose-jade-history-anchor").forEach((anchor) => {
      if (anchor.parentElement !== centerCard) anchor.remove();
    });
    let anchor = Array.from(centerCard.children).find(
      (child) => child.classList?.contains("rose-jade-history-anchor")
    );
    if (!anchor) {
      anchor = document.createElement("div");
      anchor.className =
        "rose-jade-history-anchor skin-selection-item-information loyalty-reward-icon--rewards";
      centerCard.appendChild(anchor);
    }
  }

  function adaptNativeController() {
    if (!active || !catalog.length) return;
    const nextPane = findNativePane();
    if (!nextPane) return;
    if (pane && pane !== nextPane) cleanupDom();
    pane = nextPane;
    ensureOverlay();

    const cards = nativeCards();
    const centerCard = selectedNativeCard(cards);
    if (!centerCard) return;
    if (overlay?.parentElement !== centerCard) {
      if (window.getComputedStyle(centerCard).position === "static") {
        centerCard.style.position = "relative";
      }
      centerCard.appendChild(overlay);
    }
    ensureHistoryAnchor(centerCard);
    const centerSlot = cards.indexOf(centerCard);
    const visualCenterEntry = matchCardToCatalog(centerCard);
    const selectedCatalogEntry = catalogEntryForRawSkinId(selectedRawSkinId);
    let selectedIndex = selectedCatalogEntry ? catalog.indexOf(selectedCatalogEntry) : -1;
    if (selectedIndex < 0) {
      selectedIndex = catalog.findIndex(
        (entry) => entry.resourceSkinId === selectedResourceSkinId
      );
    }
    if (selectedIndex < 0) selectedIndex = 0;
    let centerEntry = visualCenterEntry || catalog[selectedIndex] || null;
    if (visualCenterEntry) selectedIndex = catalog.indexOf(visualCenterEntry);
    const navigationPending =
      pendingUserNavigation && Date.now() <= pendingUserNavigationUntil;
    if (pendingUserNavigation && !navigationPending) clearUserNavigation();
    const followsUserNavigation = Boolean(
      navigationPending &&
      pendingUserTargetRawSkinId &&
      centerEntry &&
      pendingUserTargetRawSkinId === centerEntry.rawSkinId
    );
    const isIntermediateUserNavigation = Boolean(
      navigationPending &&
      pendingUserTargetRawSkinId &&
      centerEntry &&
      pendingUserTargetRawSkinId !== centerEntry.rawSkinId
    );
    const isAutomaticLcuRollback = Boolean(
      centerEntry &&
      desiredVisualSelection &&
      desiredVisualSelection.rawSkinId !== centerEntry.rawSkinId &&
      visualCarrierProtectionActive &&
      !followsUserNavigation
    );
    if (isAutomaticLcuRollback) {
      centerEntry = desiredVisualSelection;
      selectedIndex = projectedCatalogIndex >= 0
        ? projectedCatalogIndex
        : catalog.indexOf(centerEntry);
    }
    const projectionActive = Boolean(
      desiredVisualSelection &&
      projectedCatalogIndex >= 0 &&
      visualCarrierProtectionActive &&
      !followsUserNavigation
    );
    if (projectionActive) {
      centerEntry = desiredVisualSelection;
      selectedIndex = projectedCatalogIndex;
    }
    const usedRawSkinIds = new Set(centerEntry ? [centerEntry.rawSkinId] : []);

    if (centerEntry && centerEntry.rawSkinId !== lastVisualCenterRawSkinId) {
      lastVisualCenterRawSkinId = centerEntry.rawSkinId;
      if (isAutomaticLcuRollback) {
        log("info", "Ignored automatic classic skin rollback", {
          desiredResourceSkinId: desiredVisualSelection.resourceSkinId,
          lcuResourceSkinId: visualCenterEntry?.resourceSkinId || selectedResourceSkinId,
        });
      } else if (!isIntermediateUserNavigation) {
        visualCarrierProtectionActive =
          !centerEntry.available && !centerEntry.isBase;
        setVisualProtection(
          centerEntry,
          "visual-center-change",
          visualCarrierProtectionActive
        );
        if (followsUserNavigation) {
          desiredVisualSelection = centerEntry;
          projectedCatalogIndex = catalog.indexOf(centerEntry);
          if (!pendingUserSelectionPublished) {
            syncVisualSelection(centerEntry, "visual-center-change", true);
            pendingUserSelectionPublished = true;
          }
        }
      }
      if (followsUserNavigation) clearUserNavigation();
    }

    for (const oldCard of Array.from(adaptedCards)) {
      if (!cards.includes(oldCard)) {
        clearCompatibility(oldCard);
        adaptedCards.delete(oldCard);
      }
    }

    const mapped = [];
    for (let slot = 0; slot < cards.length; slot += 1) {
      const card = cards[slot];
      if (card.classList.contains("skins-pane__skin-card--placeholder")) {
        clearCompatibility(card);
        continue;
      }
      const directMatch = projectionActive ? null : matchCardToCatalog(card);
      const inferredMatch = catalog[selectedIndex + (slot - centerSlot)] || null;
      let entry = centerEntry || directMatch;
      if (card !== centerCard) {
        entry = [inferredMatch, directMatch].find(
          (candidate) => candidate && !usedRawSkinIds.has(candidate.rawSkinId)
        ) || null;
      }
      const offset = slot - centerSlot;
      applyCompatibility(
        card,
        entry,
        offset,
        card === centerCard,
        isAutomaticLcuRollback
      );
      if (projectionActive && entry) {
        projectCardVisual(card, entry);
      }
      if (entry) {
        usedRawSkinIds.add(entry.rawSkinId);
        mapped.push(`${offset}:${entry.rawSkinId}:${entry.available ? "official" : "unlocked"}`);
      }
    }
    syncFooterPresentation(centerEntry);
    const footer = pane.parentElement?.querySelector(".skins-pane__footer");
    const leftArrow = pane.parentElement?.querySelector(".skins-pane__arrow--left");
    const rightArrow = pane.parentElement?.querySelector(".skins-pane__arrow--right");
    if (projectionActive && footer) {
      leftArrow?.classList.toggle("skins-pane__arrow--disabled", selectedIndex <= 0);
      rightArrow?.classList.toggle("skins-pane__arrow--disabled", selectedIndex >= catalog.length - 1);
    }

    const layoutKey = `${cards.length}|${catalog.length}|${selectedRawSkinId}|${mapped.join(",")}`;
    if (layoutKey !== lastLayoutKey) {
      lastLayoutKey = layoutKey;
      log("info", "Native classic skin selector adapted", {
        nativeCardCount: cards.length,
        modeSkinCount: catalog.length,
        selectedRawSkinId,
        selectedResourceSkinId,
        visualCenterRawSkinId: centerEntry?.rawSkinId || null,
        visualCenterResourceSkinId: centerEntry?.resourceSkinId || null,
        nativeCenterRawSkinId: visualCenterEntry?.rawSkinId || null,
        visualProjectionActive: isAutomaticLcuRollback,
        mapped,
      });
    }
  }

  async function loadModeCatalog(force = false) {
    if (!active || !rawChampionId) return;
    if (!force && catalog.length && Date.now() - catalogLoadedAt < CATALOG_REFRESH_MS) return;
    const generation = requestGeneration;
    if (!modeDefaultRawSkinId) {
      try {
        const pickableSkinIds = await fetchJson(
          "/lol-lobby-team-builder/champ-select/v1/pickable-skin-ids"
        );
        if (!active || generation !== requestGeneration) return;
        const candidates = (Array.isArray(pickableSkinIds) ? pickableSkinIds : [])
          .map((value) => numeric(value) || 0)
          .filter((value) => Math.floor(value / 1000) === rawChampionId);
        const expected = fallbackModeDefaultRawSkinId();
        modeDefaultRawSkinId = candidates.find((value) => value === expected)
          || candidates.find((value) => value % 1000 >= 300)
          || candidates.find((value) => value % 1000 === 0)
          || 0;
      } catch (error) {
        log("debug", "Waiting for classic default skin catalog", String(error));
      }
      if (!modeDefaultRawSkinId) {
        modeDefaultRawSkinId = fallbackModeDefaultRawSkinId();
      }
    }
    const modeSkins = await fetchJson("/lol-champ-select/v1/skin-carousel-skins");
    if (!active || generation !== requestGeneration) return;
    const nextCatalog = (Array.isArray(modeSkins) ? modeSkins : [])
      .map(normalizeCatalogEntry)
      .filter(
        (entry) =>
          entry && entry.championId === championId && !entry.isHiddenModeSkin0
      );
    catalogLoadedAt = Date.now();
    if (!nextCatalog.length) return;
    // Riot's JADE component always moves its native classic default to index
    // zero. Mirror that exact order so projected history/random navigation and
    // the native finite carousel share the same left/right boundaries.
    const defaultIndex = nextCatalog.findIndex((entry) => entry.isBase);
    if (defaultIndex > 0) {
      const [defaultEntry] = nextCatalog.splice(defaultIndex, 1);
      nextCatalog.unshift(defaultEntry);
    }
    catalog = nextCatalog;
    syncModeCatalog(force ? "forced-refresh" : "refresh");
    applyHistoricVisualSelection();
  }

  async function refreshSelection(forceCatalog = false) {
    if (!active || refreshInFlight) return;
    refreshInFlight = true;
    try {
      const info = await fetchJson("/lol-champ-select/v1/skin-selector-info");
      if (!active || !info) return;
      const nextRawChampion = numeric(info.selectedChampionId) || 0;
      const nextChampion = resourceChampionId(nextRawChampion);
      const nextRawSkin = numeric(info.selectedSkinId) || 0;
      const championChanged = nextRawChampion !== rawChampionId;
      rawChampionId = nextRawChampion;
      championId = nextChampion;
      selectedRawSkinId = nextRawSkin;
      selectedResourceSkinId = resourceSkinId(nextRawSkin);
      if (championChanged) {
        cancelHistoricVisualRestore("champion-change", true);
        visualCarrierProtectionActive = false;
        projectedCatalogIndex = -1;
        lastAppliedHistoricResourceSkinId = 0;
        projectedVariantRawSkinId = 0;
        setVisualProtection(null, "champion-change");
        desiredVisualSelection = null;
        pendingUserNavigation = false;
        pendingUserNavigationUntil = 0;
        pendingUserTargetRawSkinId = 0;
        pendingUserSelectionPublished = false;
        catalog = [];
        catalogLoadedAt = 0;
        modeDefaultRawSkinId = 0;
        lastCatalogSyncKey = "";
      }
      await loadModeCatalog(forceCatalog || championChanged || !catalog.length);
      adaptNativeController();
    } catch (error) {
      log("debug", "Waiting for native classic skin selector", String(error));
    } finally {
      refreshInFlight = false;
    }
  }

  function injectStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      .${HOST_CLASS} {
        position: relative !important;
      }

      #${ROOT_ID}.rose-jade-wheel-jade-pane {
        position: absolute !important;
        inset: 0 !important;
        z-index: 20 !important;
        pointer-events: none !important;
      }

      .${CARD_CLASS}.${SELECTED_CLASS} > .rose-jade-history-anchor {
        position: absolute !important;
        top: -14px !important;
        right: -14px !important;
        left: auto !important;
        width: 32px !important;
        height: 32px !important;
        display: block !important;
        visibility: visible !important;
        opacity: 1 !important;
        z-index: 24 !important;
        pointer-events: none !important;
      }

      .${CARD_CLASS}.${SELECTED_CLASS} > .lu-chroma-button,
      .${CARD_CLASS}.${SELECTED_CLASS} > .forms-wheel-button {
        top: -12px !important;
        bottom: auto !important;
        left: 50% !important;
        transform: translateX(-50%) !important;
        z-index: 14 !important;
      }

      .${CARD_CLASS}.${SELECTED_CLASS} > .lu-random-dice-button {
        top: -43px !important;
        left: 50% !important;
        transform: translateX(-50%) !important;
        z-index: 15 !important;
      }

      .${UNLOCKED_CLASS} {
        cursor: pointer !important;
      }

      .${CARD_CLASS}.rose-jade-native-card--stabilizing,
      .${CARD_CLASS}.rose-jade-native-card--stabilizing * {
        transition: none !important;
        animation: none !important;
      }

      .${UNLOCKED_CLASS} .skins-pane__locked-overlay,
      .${UNLOCKED_CLASS} .skins-pane__locked-icon {
        display: none !important;
        pointer-events: none !important;
      }

      .${ACTIVE_ROOT_CLASS} .champion-select-center-container--picking-skins
        .skins-pane__content .skins-pane__locked-overlay,
      .${ACTIVE_ROOT_CLASS} .champion-select-center-container--picking-skins
        .skins-pane__content .skins-pane__locked-icon {
        display: none !important;
        pointer-events: none !important;
      }

      .${EMPTY_CLASS} {
        visibility: hidden !important;
        pointer-events: none !important;
        border-color: transparent !important;
      }

      .${ACTIVE_ROOT_CLASS} .champion-select-center-container--picking-skins
        .skins-pane__skin-card--placeholder {
        border: none !important;
        visibility: hidden !important;
        pointer-events: none !important;
      }
    `;
    document.head.appendChild(style);
  }

  function cleanupDom() {
    for (const card of Array.from(adaptedCards)) clearCompatibility(card);
    adaptedCards.clear();
    pane?.removeEventListener("click", handleNativePaneClick, true);
    document.querySelectorAll(`.${HOST_CLASS}`).forEach((element) => {
      element.classList.remove(HOST_CLASS);
    });
    document.getElementById(ROOT_ID)?.remove();
    document.querySelectorAll(".rose-jade-history-anchor").forEach((element) => element.remove());
    pane = null;
    overlay = null;
    lastLayoutKey = "";
  }

  function startActiveRuntime() {
    if (active) return;
    if (visualProtectionClearTimer) clearTimeout(visualProtectionClearTimer);
    visualProtectionClearTimer = null;
    active = true;
    requestGeneration += 1;
    selectionGeneration = 0;
    lastAppliedHistoricResourceSkinId = 0;
    installNativeReadProjection();
    installNativeWebsocketProjection();
    injectStyles();
    document.documentElement.classList.add(ACTIVE_ROOT_CLASS);
    observer = new MutationObserver(() => adaptNativeController());
    observer.observe(document.body, { childList: true, subtree: true });
    document.addEventListener("pointerdown", handleUserNavigation, true);
    document.addEventListener("keydown", handleUserNavigationKey, true);
    pollTimer = setInterval(refreshSelection, POLL_INTERVAL_MS);
    refreshSelection(true);
    log("info", "Native classic skin adapter enabled", { phase, gameMode, mapId, queueId });
  }

  function stopActiveRuntime() {
    if (!active) return;
    active = false;
    document.documentElement.classList.remove(ACTIVE_ROOT_CLASS);
    requestGeneration += 1;
    observer?.disconnect();
    observer = null;
    document.removeEventListener("pointerdown", handleUserNavigation, true);
    document.removeEventListener("keydown", handleUserNavigationKey, true);
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
    if (nativeProjectionTimer) clearTimeout(nativeProjectionTimer);
    nativeProjectionTimer = null;
    nativeProjectionTargetIndex = -1;
    nativeProjectionCurrentIndex = -1;
    drivingNativeProjection = false;
    cleanupDom();
    rawChampionId = 0;
    championId = 0;
    selectedRawSkinId = 0;
    selectedResourceSkinId = 0;
    modeDefaultRawSkinId = 0;
    catalog = [];
    catalogLoadedAt = 0;
    desiredVisualSelection = null;
    projectedCatalogIndex = -1;
    clearUserNavigation();
    visualCarrierProtectionActive = false;
    pendingHistoricResourceSkinId = 0;
    lastAppliedHistoricResourceSkinId = 0;
    cancelHistoricVisualRestore("runtime-stop", true);
    nativeProjectionComplete = null;
    randomModeActive = false;
    projectedVariantRawSkinId = 0;
    pointerSelectionRawSkinId = 0;
    pointerSelectionUntil = 0;
    pointerSelectionCommitted = false;
    lastVisualCenterRawSkinId = 0;
    lastVisualProtectionKey = "";
    lastReadRewriteKey = "";
    refreshInFlight = false;
    if (visualProtectionClearTimer) clearTimeout(visualProtectionClearTimer);
    visualProtectionClearTimer = setTimeout(() => {
      visualProtectionClearTimer = null;
      setVisualProtection(null, "runtime-stop");
    }, 3000);
    window.dispatchEvent(
      new CustomEvent("rose-jade-wheel-layout", {
        detail: { active: false, rootId: ROOT_ID, native: true },
      })
    );
    log("info", "Native classic skin adapter disabled");
  }

  function reconcileRuntime() {
    if (isChampSelectPhase() && isJadeClassicContext()) startActiveRuntime();
    else stopActiveRuntime();
  }

  async function syncContextFromLcu() {
    try {
      const [flowPhase, session] = await Promise.all([
        fetchJson("/lol-gameflow/v1/gameflow-phase").catch(() => null),
        fetchJson("/lol-gameflow/v1/session").catch(() => null),
      ]);
      if (flowPhase) phase = flowPhase;
      const queue = session?.gameData?.queue || {};
      gameMode = queue.gameMode || session?.map?.gameMode || gameMode;
      mapId = queue.mapId || session?.map?.id || mapId;
      queueId = queue.id || queueId;
      reconcileRuntime();
    } catch (error) {
      log("debug", "LCU context sync deferred", String(error));
    }
  }

  function handlePhaseChange(data) {
    if (!data || typeof data !== "object") return;
    phase = data.phase || phase;
    gameMode = data.gameMode || gameMode;
    mapId = data.mapId ?? mapId;
    queueId = data.queueId ?? queueId;
    reconcileRuntime();
    if (isChampSelectPhase() && !isJadeClassicContext()) syncContextFromLcu();
  }

  async function start() {
    if (typeof document === "undefined" || !document.body) {
      requestAnimationFrame(start);
      return;
    }
    bridge = await waitForBridge();
    bridge.subscribe("phase-change", handlePhaseChange);
    bridge.subscribe("champion-locked", () => {
      if (active) refreshSelection(true);
    });
    bridge.subscribe("historic-state", handleHistoricState);
    bridge.subscribe("random-mode-state", handleRandomModeState);
    await syncContextFromLcu();
    log("info", "Plugin initialized");
  }

  window.__roseJadeWheelDebug = {
    refresh: () => refreshSelection(true),
    state: () => ({
      active,
      phase,
      gameMode,
      mapId,
      queueId,
      championId,
      rawChampionId,
      selectedRawSkinId,
      selectedResourceSkinId,
      modeSkinCount: catalog.length,
      nativeCardCount: nativeCards().length,
      adaptedCardCount: adaptedCards.size,
      desiredVisualRawSkinId: desiredVisualSelection?.rawSkinId || 0,
      projectedVariantRawSkinId,
      pendingUserTargetRawSkinId,
    }),
    resourceChampionId,
    resourceSkinId,
    jadeSkinId,
    shouldPatchLcuSelection,
    getModeSkinData,
    catalogAssetSnapshot,
    catalogData: () => catalog.map((entry) => entry.rawSkin),
    projectResourceSelection,
  };

  start().catch((error) => log("error", "Plugin initialization failed", String(error)));
})();
