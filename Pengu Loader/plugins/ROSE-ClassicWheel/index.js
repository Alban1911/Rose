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
  const ROOT_ID = "rose-jade-skin-wheel";
  const STYLE_ID = "rose-jade-skin-wheel-styles";
  const HOST_CLASS = "rose-jade-native-host";
  const CARD_CLASS = "rose-jade-native-card";
  const SELECTED_CLASS = "rose-jade-native-card--selected";
  const UNLOCKED_CLASS = "rose-jade-native-card--unlocked";
  const ACTIVE_ROOT_CLASS = "rose-jade-wheel-active";
  const VISUAL_PROTECTION_EVENT = "rose-jade-visual-protection";
  const SELECTION_CHANGE_EVENT = "rose-classic-selection-change";
  const POLL_INTERVAL_MS = 450;
  const CATALOG_REFRESH_MS = 2000;
  const USER_NAVIGATION_WINDOW_MS = 6000;
  const nativeFetch = window.fetch.bind(window);

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
  const lockOverlayState = new WeakMap();
  let footerPresentationState = null;
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
  let pendingRandomResourceSkinId = 0;
  let appliedRandomResourceSkinId = 0;
  let randomProjectionSuppressed = false;
  let visualRollbackProtectionActive = false;
  let projectedVariantRawSkinId = 0;
  let lastVisualCenterRawSkinId = 0;
  let lastLayoutKey = "";
  let lastVisualProtectionKey = "";
  let lastReadRewriteKey = "";
  let refreshNativeSkinPresentation = null;
  let latestNativeSkinSelectorEvent = null;
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
        type: "plugin-log",
        source: "ClassicWheel",
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

  function isModeDefaultRawSkinId(value) {
    const id = numeric(value) || 0;
    const expected = modeDefaultRawSkinId;
    return id > 0 && expected > 0 && id === expected;
  }

  function isModeDefaultResourceSkinId(value) {
    const id = resourceSkinId(value);
    const expected = resourceSkinId(modeDefaultRawSkinId);
    return id > 0 && expected > 0 && id === expected;
  }

  async function fetchJson(endpoint) {
    // Always read the real LCU state here. The native JADE controller receives
    // a visual-only projection below, while Python and this adapter must keep
    // observing the official default selected in the client.
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
    const protection = window.__roseJadeVisualProtection;
    const desiredRawSkinId = numeric(protection?.desiredRawSkinId);
    if (!active || !protection?.active || !desiredRawSkinId) return false;
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
    const defaults = new Set(
      (protection.defaultLcuSkinIds || []).map(numeric).filter(Number.isFinite)
    );
    const automaticProjectionSettled =
      nativeProjectionTargetIndex < 0 && !pendingUserNavigation;
    return selected !== null && desired !== null && selected !== desired &&
      (defaults.has(selected) || automaticProjectionSettled);
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
        refreshNativeSkinPresentation = (desiredRawSkinId) => {
          if (!active || !latestNativeSkinSelectorEvent || !desiredRawSkinId) return;
          const payload = JSON.parse(JSON.stringify(latestNativeSkinSelectorEvent.payload));
          const selectedChampionId = numeric(payload[2]?.data?.selectedChampionId);
          if (selectedChampionId && selectedChampionId !== Math.floor(desiredRawSkinId / 1000)) {
            return;
          }
          payload[2].data.selectedSkinId = desiredRawSkinId;
          parentOnMessage.call(
            ws,
            cloneWebsocketEvent(latestNativeSkinSelectorEvent.event, payload)
          );
          log("info", "Refreshed native classic skin presentation", {
            selectedSkinId: desiredRawSkinId,
          });
        };
        ws.onmessage = function roseJadeProjectedMessage(event) {
          try {
            const payload = JSON.parse(event.data);
            if (payload?.[1] !== "OnJsonApiEvent") {
              return parentOnMessage.call(this, event);
            }
            const eventData = payload[2];
            if (eventData?.uri === "/lol-champ-select/v1/skin-selector-info") {
              const selectedSkinId = eventData.data?.selectedSkinId;
              latestNativeSkinSelectorEvent = { event, payload };
              if (shouldSuppressVisualRollback(selectedSkinId)) {
                eventData.data.selectedSkinId = numeric(
                  window.__roseJadeVisualProtection?.desiredRawSkinId
                );
                log("info", "Projected classic selector rollback", {
                  selectedSkinId,
                  projectedSkinId: eventData.data.selectedSkinId,
                });
                return parentOnMessage.call(this, cloneWebsocketEvent(event, payload));
              }
            } else if (eventData?.uri === "/lol-champ-select/v1/session") {
              const protection = window.__roseJadeVisualProtection;
              if (
                protection?.active &&
                rewriteSessionSelection(
                  eventData.data,
                  numeric(protection.desiredRawSkinId)
                )
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
        method === "PATCH" &&
        path === "/lol-champ-select/v1/session/my-selection"
      ) {
        try {
          const body = JSON.parse(String(init?.body || "{}"));
          const requestedRawSkinId = numeric(body.selectedSkinId) || 0;
          const requestedEntry = catalogEntryForRawSkinId(requestedRawSkinId);
          if (requestedEntry && !requestedEntry.available && !requestedEntry.isBase) {
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
        const desiredRawSkinId = numeric(
          window.__roseJadeVisualProtection?.desiredRawSkinId
        ) || 0;
        const rewriteKey = `${path}|${desiredRawSkinId}`;
        if (rewriteKey !== lastReadRewriteKey) {
          lastReadRewriteKey = rewriteKey;
          log("info", "Projected classic visual selection into native read", {
            path,
            desiredRawSkinId,
          });
        }
        const headers = new Headers(response.headers);
        headers.delete("content-length");
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
    if (visualRollbackProtectionActive) {
      refreshNativeSkinPresentation?.(entry.rawSkinId);
    }
    try {
      const entries = catalogBridgeEntries();
      // Python validates this ID against the active JADE carousel before it
      // updates the same injection state used by regular champion select.
      bridge.send({
        type: "classic-skin-selection",
        schemaVersion: 1,
        mode: JADE_MODE,
        championId: entry.championId,
        defaultSkinId: resourceSkinId(modeDefaultRawSkinId),
        skin: entry.name,
        originalName: entry.name,
        skinId: entry.resourceSkinId,
        catalog: entries,
        randomEligibleSkinIds: entries.map((item) => item.id),
        source: "jade-wheel",
        reason,
        userInitiated,
        selectionGeneration,
        available: entry.available === true,
        timestamp: Date.now(),
      });
      dispatchSelectionChange(reason);
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
          id: resourceSkinId(id),
          championId: resourceChampionId(
            numeric(skin.championId) || fallbackChampionId
          ),
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
    const baseRawSkinId = modeDefaultRawSkinId;
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
      championId,
      selectedSkinId: selectedResourceSkinId,
      defaultSkinId: resourceSkinId(baseRawSkinId),
      catalog: entries,
      randomEligibleSkinIds: entries.map((entry) => entry.id),
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
    const defaultLcuSkinIds = protectedEntry && modeDefaultRawSkinId
      ? [modeDefaultRawSkinId]
      : [];
    const detail = {
      active: Boolean(protectedEntry),
      reason,
      desiredRawSkinId: protectedEntry?.rawSkinId || 0,
      desiredResourceSkinId: protectedEntry?.resourceSkinId || 0,
      defaultLcuSkinIds,
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
        entry.tilePath || entry.splashPath || entry.uncenteredSplashPath || entry.loadScreenPath || ""
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

  function resolveModeCarrierRawSkinId(rawEntries, pickableSkinIds) {
    const entryIds = new Set(
      rawEntries.map((entry) => numeric(entry?.id ?? entry?.skinId) || 0).filter(Boolean)
    );
    const pickable = pickableSkinIds.filter((value) => entryIds.has(value));
    const isSpecialCarrier = (value) => value % 1000 === 301 || value % 1000 === 302;
    const declaredDefault = rawEntries.find(
      (entry) => entry?.isBase === true || entry?.isDefault === true
    );
    const declaredDefaultId = numeric(declaredDefault?.id ?? declaredDefault?.skinId) || 0;

    // JADE initially selects its champion carrier. Preserve Skin301/Skin302
    // when present; Skin0 is the carrier only for champions without one.
    return (
      (entryIds.has(selectedRawSkinId) && isSpecialCarrier(selectedRawSkinId)
        ? selectedRawSkinId
        : 0) ||
      pickable.find(isSpecialCarrier) ||
      declaredDefaultId ||
      (entryIds.has(selectedRawSkinId) ? selectedRawSkinId : 0) ||
      pickable[0] ||
      [...entryIds][0] ||
      0
    );
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
      const defaultRawSkinId = modeDefaultRawSkinId;
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

  function projectResourceSelection(
    resourceId,
    reason = "external-state",
    onComplete = null
  ) {
    if (!active || !catalog.length) return false;
    const selection = catalogSelectionForResourceSkinId(resourceId);
    if (!selection) return false;
    const { entry, rawSkinId } = selection;
    if (reason === "random-state" || reason === "chroma-state") {
      pendingHistoricResourceSkinId = 0;
      lastAppliedHistoricResourceSkinId = 0;
    }
    visualRollbackProtectionActive = !isModeDefaultResourceSkinId(resourceId);
    projectedVariantRawSkinId = rawSkinId;
    desiredVisualSelection = entry;
    projectedCatalogIndex = catalog.indexOf(entry);
    lastVisualCenterRawSkinId = 0;
    clearUserNavigation();
    setVisualProtection(entry, reason, visualRollbackProtectionActive);
    scheduleNativeProjection(projectedCatalogIndex, () => {
      if (
        active &&
        desiredVisualSelection?.rawSkinId === entry.rawSkinId &&
        visualRollbackProtectionActive
      ) {
        refreshNativeSkinPresentation?.(entry.rawSkinId);
      }
      if (typeof onComplete === "function") onComplete();
    });
    adaptNativeController();
    dispatchSelectionChange(reason);
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
    const selection = catalogSelectionForResourceSkinId(resourceId);
    if (
      projectResourceSelection(resourceId, "historic-restore", () => {
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
        log("info", "Classic history projected into native selector", {
          historicResourceSkinId: resourceId,
          visualRawSkinId: selection?.entry?.rawSkinId || 0,
          variantRawSkinId: selection?.rawSkinId || 0,
        });
      })
    ) {
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
        visualRollbackProtectionActive = true;
        projectedVariantRawSkinId = selection.rawSkinId;
        desiredVisualSelection = selection.entry;
        projectedCatalogIndex = catalog.indexOf(selection.entry);
        setVisualProtection(selection.entry, "historic-catalog-refresh", true);
        adaptNativeController();
        return;
      }
      if (historicRestoreInProgress) return;
      historicRestoreInProgress = true;
      const resourceId = pendingHistoricResourceSkinId;
      const generation = ++historicRestoreGeneration;
      setHistoricPresentationReady(false, "historic-restore");
      finishHistoricVisualSelection(resourceId, generation);
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
      cancelNativeProjection();
      lastAppliedHistoricResourceSkinId = 0;
    }
    if (pendingHistoricResourceSkinId) applyHistoricVisualSelection();
  }

  function handleRandomModeState(data) {
    const wasActive = randomModeActive;
    randomModeActive = data?.active === true;
    if (!randomModeActive) {
      if (wasActive && appliedRandomResourceSkinId) cancelNativeProjection();
      pendingRandomResourceSkinId = 0;
      appliedRandomResourceSkinId = 0;
      randomProjectionSuppressed = false;
      return;
    }
    cancelHistoricVisualRestore("random-mode", true);
    pendingHistoricResourceSkinId = 0;
    lastAppliedHistoricResourceSkinId = 0;
    const nextRandomResourceSkinId = numeric(data?.randomSkinId) || 0;
    const resultChanged = nextRandomResourceSkinId !== pendingRandomResourceSkinId;
    if (resultChanged) appliedRandomResourceSkinId = 0;
    pendingRandomResourceSkinId = nextRandomResourceSkinId;
    if (!wasActive || resultChanged) {
      cancelNativeProjection();
      clearUserNavigation();
    }
    if (!wasActive) randomProjectionSuppressed = false;
    applyPendingRandomVisualSelection();
  }

  function randomProjectionReady() {
    return phase === "FINALIZATION" || phase === "GameStart" ||
      document.querySelector(".champion-select.timer-less-than-11-seconds") !== null;
  }

  function applyPendingRandomVisualSelection() {
    if (
      !active || !randomModeActive || randomProjectionSuppressed ||
      !pendingRandomResourceSkinId || !randomProjectionReady() || !catalog.length
    ) {
      return;
    }
    const selection = catalogSelectionForResourceSkinId(pendingRandomResourceSkinId);
    if (!selection) return;
    if (pendingRandomResourceSkinId === appliedRandomResourceSkinId) {
      projectedVariantRawSkinId = selection.rawSkinId;
      visualRollbackProtectionActive = !selection.entry.isBase;
      desiredVisualSelection = selection.entry;
      projectedCatalogIndex = catalog.indexOf(selection.entry);
      setVisualProtection(selection.entry, "random-catalog-refresh", true);
      adaptNativeController();
      return;
    }
    if (!projectResourceSelection(pendingRandomResourceSkinId, "random-state")) return;
    appliedRandomResourceSkinId = pendingRandomResourceSkinId;
    log("info", "Classic random result projected during finalization window", {
      rawSkinId: selection.rawSkinId,
      resourceSkinId: resourceSkinId(selection.rawSkinId),
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
    // with their visual left-to-right order. Sort by the rendered position;
    // descendant carousel-offset classes can remain stale after projection.
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
    for (const attribute of attributes) {
      const value = numeric(card.getAttribute(attribute));
      if (value && value > 0) return value;
    }

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

  function clearCompatibility(card) {
    if (!card) return;
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
    card.classList.remove(CARD_CLASS, SELECTED_CLASS, UNLOCKED_CLASS);
  }

  function unlockNativeCard(card) {
    if (!card) return;
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

  function applyCompatibility(card, selected) {
    if (!card) return;
    if (card.classList.contains("skins-pane__skin-card--placeholder")) {
      clearCompatibility(card);
      return;
    }
    card.classList.add(CARD_CLASS);
    card.classList.toggle(SELECTED_CLASS, selected);
    unlockNativeCard(card);
    adaptedCards.add(card);
  }

  function beginUserNavigation(targetRawSkinId = 0) {
    const targetId = numeric(targetRawSkinId) || 0;
    const targetEntry = targetId ? catalogEntryForRawSkinId(targetId) : null;
    const hadVisualProtection = visualRollbackProtectionActive;
    if (
      historicRestoreInProgress || pendingHistoricResourceSkinId ||
      lastAppliedHistoricResourceSkinId
    ) {
      cancelHistoricVisualRestore("user-navigation", true);
      pendingHistoricResourceSkinId = 0;
      lastAppliedHistoricResourceSkinId = 0;
    }
    cancelNativeProjection();
    if (randomModeActive) {
      appliedRandomResourceSkinId = 0;
      randomProjectionSuppressed = true;
    }
    if (targetEntry) {
      visualRollbackProtectionActive = !targetEntry.available && !targetEntry.isBase;
      desiredVisualSelection = targetEntry;
      projectedCatalogIndex = catalog.indexOf(targetEntry);
      setVisualProtection(
        targetEntry,
        "user-navigation-target",
        visualRollbackProtectionActive
      );
    }
    if (targetEntry && hadVisualProtection && !visualRollbackProtectionActive) {
      for (const card of Array.from(adaptedCards)) clearCompatibility(card);
      adaptedCards.clear();
    }
    pendingUserNavigation = true;
    pendingUserNavigationUntil = Date.now() + USER_NAVIGATION_WINDOW_MS;
    pendingUserTargetRawSkinId = targetId;
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
    visualRollbackProtectionActive = !entry.available && !entry.isBase;
    setVisualProtection(entry, reason, visualRollbackProtectionActive);
    desiredVisualSelection = entry;
    projectedCatalogIndex = catalog.indexOf(entry);
    syncVisualSelection(entry, reason, true);
    pendingUserSelectionPublished = true;
  }

  function cancelNativeProjection() {
    if (nativeProjectionTimer) clearTimeout(nativeProjectionTimer);
    nativeProjectionTimer = null;
    nativeProjectionTargetIndex = -1;
    nativeProjectionCurrentIndex = -1;
    nativeProjectionComplete = null;
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
    if (!arrow || arrow.classList.contains("skins-pane__arrow--disabled")) {
      log("warn", "Native classic carousel reached a boundary before projection target", {
        currentIndex,
        targetIndex: nativeProjectionTargetIndex,
        direction,
      });
      nativeProjectionTargetIndex = -1;
      nativeProjectionCurrentIndex = -1;
      nativeProjectionComplete = null;
      adaptNativeController();
      return;
    }
    drivingNativeProjection = true;
    arrow.click();
    drivingNativeProjection = false;
    nativeProjectionCurrentIndex += direction === "left" ? -1 : 1;
    nativeProjectionTimer = setTimeout(stepNativeProjection, 80);
  }

  function syncFooterPresentation(entry) {
    if (!pane || !entry) return;
    const root = pane.parentElement || pane;
    const subtitle = root.querySelector(".skins-pane__footer .skins-pane__sub-title");
    if (!subtitle) return;
    if (footerPresentationState?.element !== subtitle) restoreFooterPresentation();
    if (!footerPresentationState) {
      footerPresentationState = {
        element: subtitle,
        text: subtitle.textContent,
        unlocked: subtitle.classList.contains("skins-pane__sub-title--unlocked"),
      };
    }
    if (subtitle.textContent !== "UNLOCKED") subtitle.textContent = "UNLOCKED";
    subtitle.classList.add("skins-pane__sub-title--unlocked");
  }

  function restoreFooterPresentation() {
    const state = footerPresentationState;
    footerPresentationState = null;
    if (!state?.element?.isConnected) return;
    state.element.textContent = state.text;
    state.element.classList.toggle("skins-pane__sub-title--unlocked", state.unlocked);
  }

  function handleNativePaneClick(event) {
    if (
      event.target?.closest?.(
        ".chroma-button, .lu-chroma-button, .forms-wheel-button, .lu-random-dice-button"
      )
    ) {
      return;
    }
    const card = event.target?.closest?.(".skins-pane__skin-card");
    if (!card || !pane?.contains(card)) return;
    const clickEntry = matchCardToCatalog(card);
    const clickRawSkinId = clickEntry?.rawSkinId || 0;
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
    const entry = clickEntry;
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
      pendingHistoricResourceSkinId = 0;
      projectedVariantRawSkinId = 0;
      beginUserNavigation(target?.rawSkinId || 0);
      return;
    }
    if (
      event.target?.closest?.(
        ".chroma-button, .lu-chroma-button, .forms-wheel-button, .lu-random-dice-button"
      )
    ) {
      return;
    }
    const card = event.target?.closest?.(".skins-pane__skin-card");
    if (card && pane?.contains(card)) {
      pendingHistoricResourceSkinId = 0;
      projectedVariantRawSkinId = 0;
      const entry = matchCardToCatalog(card);
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
      const cards = nativeCards();
      const centerCard = selectedNativeCard(cards);
      const centerEntry = centerCard ? matchCardToCatalog(centerCard) : null;
      const currentIndex = centerEntry ? catalog.indexOf(centerEntry) : -1;
      const direction = event.key === "ArrowLeft" ? -1 : 1;
      const target = currentIndex >= 0 ? catalog[currentIndex + direction] : null;
      beginUserNavigation(target?.rawSkinId || 0);
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
      anchor.className = "rose-jade-history-anchor";
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
    const visualCenterEntry = matchCardToCatalog(centerCard);
    const selectedCatalogEntry = catalogEntryForRawSkinId(selectedRawSkinId)
      || catalog.find((entry) => entry.resourceSkinId === selectedResourceSkinId)
      || null;
    const centerEntry = visualCenterEntry || selectedCatalogEntry;
    const settledOwnedUserSelection = Boolean(
      pendingUserNavigation &&
      Date.now() <= pendingUserNavigationUntil &&
      selectedRawSkinId !== modeDefaultRawSkinId &&
      selectedCatalogEntry?.available &&
      visualCenterEntry?.rawSkinId === selectedCatalogEntry.rawSkinId &&
      desiredVisualSelection?.rawSkinId !== selectedCatalogEntry.rawSkinId &&
      nativeProjectionTargetIndex < 0
    );
    if (settledOwnedUserSelection) {
      log("info", "Accepted native owned selection over stale carousel target", {
        selectedRawSkinId,
        staleTargetRawSkinId: desiredVisualSelection?.rawSkinId || 0,
      });
      publishNativeCardSelection(selectedCatalogEntry, "lcu-owned-selection");
      clearUserNavigation();
    }
    const navigationPending =
      pendingUserNavigation && Date.now() <= pendingUserNavigationUntil;
    if (pendingUserNavigation && !navigationPending) clearUserNavigation();
    const followsKnownUserNavigation = Boolean(
      navigationPending &&
      pendingUserTargetRawSkinId &&
      centerEntry &&
      pendingUserTargetRawSkinId === centerEntry.rawSkinId
    );
    const followsUnresolvedUserNavigation = Boolean(
      navigationPending &&
      !pendingUserTargetRawSkinId &&
      centerEntry &&
      centerEntry.rawSkinId !== lastVisualCenterRawSkinId
    );
    const followsUserNavigation =
      followsKnownUserNavigation || followsUnresolvedUserNavigation;
    const isIntermediateUserNavigation = Boolean(
      navigationPending &&
      pendingUserTargetRawSkinId &&
      centerEntry &&
      pendingUserTargetRawSkinId !== centerEntry.rawSkinId
    );
    const isIntermediateNativeProjection = Boolean(
      nativeProjectionTargetIndex >= 0 &&
      centerEntry &&
      catalog.indexOf(centerEntry) !== nativeProjectionTargetIndex
    );
    const isAutomaticSelectionDrift = Boolean(
      centerEntry &&
      desiredVisualSelection &&
      desiredVisualSelection.rawSkinId !== centerEntry.rawSkinId &&
      visualRollbackProtectionActive &&
      !followsUserNavigation &&
      !navigationPending &&
      nativeProjectionTargetIndex < 0
    );
    if (centerEntry && centerEntry.rawSkinId !== lastVisualCenterRawSkinId) {
      lastVisualCenterRawSkinId = centerEntry.rawSkinId;
      if (isAutomaticSelectionDrift) {
        scheduleNativeProjection(projectedCatalogIndex);
        log("info", "Restoring classic selection through native carousel", {
          observedRawSkinId: centerEntry.rawSkinId,
          desiredRawSkinId: desiredVisualSelection.rawSkinId,
        });
      } else if (!isIntermediateUserNavigation && !isIntermediateNativeProjection) {
        const projectedChromaActive = Boolean(
          projectedVariantRawSkinId &&
          desiredVisualSelection?.rawSkinId === centerEntry.rawSkinId &&
          projectedVariantRawSkinId !== centerEntry.rawSkinId
        );
        visualRollbackProtectionActive =
          projectedChromaActive || (!centerEntry.available && !centerEntry.isBase);
        setVisualProtection(
          centerEntry,
          "visual-center-change",
          visualRollbackProtectionActive
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

    for (const card of cards) {
      if (card.classList.contains("skins-pane__skin-card--placeholder")) {
        clearCompatibility(card);
        continue;
      }
      // Native JADE owns the card content and position. ClassicWheel only
      // removes the visual lock state and keeps its own center marker for
      // companion plugins.
      applyCompatibility(card, card === centerCard);
    }
    syncFooterPresentation(centerEntry);

    const layoutKey = `${cards.length}|${catalog.length}|${selectedRawSkinId}|${centerEntry?.rawSkinId || 0}`;
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
        visualProjectionActive: false,
        nativeContentPreserved: true,
        frontendUnlocked: true,
      });
    }
  }

  async function loadModeCatalog(force = false) {
    if (!active || !rawChampionId) return;
    if (!force && catalog.length && Date.now() - catalogLoadedAt < CATALOG_REFRESH_MS) return;
    const generation = requestGeneration;
    const modeSkins = await fetchJson("/lol-champ-select/v1/skin-carousel-skins");
    if (!active || generation !== requestGeneration) return;
    if (!modeDefaultRawSkinId) {
      const rawEntries = (Array.isArray(modeSkins) ? modeSkins : []).filter(
        (entry) => Math.floor((numeric(entry?.id ?? entry?.skinId) || 0) / 1000) === rawChampionId
      );
      let candidates = [];
      try {
        const pickableSkinIds = await fetchJson(
          "/lol-lobby-team-builder/champ-select/v1/pickable-skin-ids"
        );
        if (!active || generation !== requestGeneration) return;
        candidates = (Array.isArray(pickableSkinIds) ? pickableSkinIds : [])
          .map((value) => numeric(value) || 0)
          .filter((value) => Math.floor(value / 1000) === rawChampionId);
      } catch (error) {
        log("debug", "Waiting for classic default skin catalog", String(error));
      }
      modeDefaultRawSkinId = resolveModeCarrierRawSkinId(rawEntries, candidates);
      if (!modeDefaultRawSkinId) return;
      log("info", "Classic champion carrier resolved", {
        rawChampionId,
        carrierRawSkinId: modeDefaultRawSkinId,
        initialSelectedRawSkinId: selectedRawSkinId,
      });
    }
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
    applyPendingRandomVisualSelection();
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
        visualRollbackProtectionActive = false;
        projectedCatalogIndex = -1;
        lastAppliedHistoricResourceSkinId = 0;
        appliedRandomResourceSkinId = 0;
        randomProjectionSuppressed = false;
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
      dispatchSelectionChange(championChanged ? "champion-change" : "selection-refresh");
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

    `;
    document.head.appendChild(style);
  }

  function cleanupDom() {
    for (const card of Array.from(adaptedCards)) clearCompatibility(card);
    adaptedCards.clear();
    restoreFooterPresentation();
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
    visualRollbackProtectionActive = false;
    pendingHistoricResourceSkinId = 0;
    lastAppliedHistoricResourceSkinId = 0;
    cancelHistoricVisualRestore("runtime-stop", true);
    nativeProjectionComplete = null;
    randomModeActive = false;
    pendingRandomResourceSkinId = 0;
    appliedRandomResourceSkinId = 0;
    randomProjectionSuppressed = false;
    projectedVariantRawSkinId = 0;
    pointerSelectionRawSkinId = 0;
    pointerSelectionUntil = 0;
    pointerSelectionCommitted = false;
    lastVisualCenterRawSkinId = 0;
    lastVisualProtectionKey = "";
    lastReadRewriteKey = "";
    latestNativeSkinSelectorEvent = null;
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
    applyPendingRandomVisualSelection();
    if (isChampSelectPhase() && !isJadeClassicContext()) syncContextFromLcu();
  }

  function currentSelection() {
    if (!active) return null;
    const rawSkinId = numeric(
      projectedVariantRawSkinId ||
      desiredVisualSelection?.rawSkinId ||
      selectedRawSkinId
    ) || 0;
    const catalogEntry = catalogEntryForRawSkinId(rawSkinId);
    if (!catalogEntry || !rawSkinId) return null;
    const parentEntry = catalogEntry.rawSkin;
    const selectedEntry = catalogEntry.rawSkinId === rawSkinId
      ? parentEntry
      : variantsOf(parentEntry).find(
          (entry) => numeric(entry?.id ?? entry?.skinId) === rawSkinId
        ) || parentEntry;
    return {
      championId,
      skinId: resourceSkinId(rawSkinId),
      lcuChampionId: rawChampionId,
      lcuSkinId: rawSkinId,
      selectedEntry,
      parentEntry,
    };
  }

  function dispatchSelectionChange(reason) {
    window.dispatchEvent(new CustomEvent(SELECTION_CHANGE_EVENT, {
      detail: {
        reason: String(reason || ""),
        selection: currentSelection(),
      },
    }));
  }

  function replayBridgeState() {
    if (!active || !catalog.length) return;
    lastCatalogSyncKey = "";
    syncModeCatalog("bridge-ready");

    const selection = currentSelection();
    const parent = catalogEntryForRawSkinId(selection?.lcuSkinId);
    if (!selection || !parent) return;
    const presentation = variantPresentation(selection.lcuSkinId, parent);
    syncVisualSelection(
      {
        ...parent,
        rawSkinId: presentation.rawSkinId,
        resourceSkinId: presentation.resourceSkinId,
        name: presentation.skinName,
      },
      "bridge-ready"
    );
    log("info", "Classic state replayed after bridge connection", {
      rawSkinId: presentation.rawSkinId,
      resourceSkinId: presentation.resourceSkinId,
    });
  }

  async function start() {
    if (typeof document === "undefined" || !document.body) {
      requestAnimationFrame(start);
      return;
    }
    bridge = await waitForBridge();
    installNativeWebsocketProjection();
    bridge.subscribe("phase-change", handlePhaseChange);
    bridge.subscribe("champion-locked", () => {
      if (active) refreshSelection(true);
    });
    bridge.subscribe("historic-state", handleHistoricState);
    bridge.subscribe("random-mode-state", handleRandomModeState);
    bridge.onReady?.(replayBridgeState);
    await syncContextFromLcu();
    log("info", "Plugin initialized");
  }

  const classicWheelApi = {
    refresh: () => refreshSelection(true),
    currentSelection,
    state: () => ({
      active,
      phase,
      gameMode,
      mapId,
      queueId,
      championId,
      selectedSkinId: selectedResourceSkinId,
      lcuChampionId: rawChampionId,
      selectedLcuSkinId: selectedRawSkinId,
      modeSkinCount: catalog.length,
      nativeCardCount: nativeCards().length,
      adaptedCardCount: adaptedCards.size,
      desiredVisualRawSkinId: desiredVisualSelection?.rawSkinId || 0,
      projectedVariantRawSkinId,
      pendingUserTargetRawSkinId,
    }),
    championIdFromLcu: resourceChampionId,
    skinIdFromLcu: resourceSkinId,
    skinIdForLcu: jadeSkinId,
    shouldPatchLcuSelection,
    getModeSkinData,
    catalogAssetSnapshot,
    catalogData: () => catalog.map((entry) => entry.rawSkin),
    projectResourceSelection,
  };
  window.__roseClassicWheelApi = classicWheelApi;
  window.__roseJadeWheelDebug = classicWheelApi;

  start().catch((error) => log("error", "Plugin initialization failed", String(error)));
})();
