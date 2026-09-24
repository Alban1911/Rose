/**
 * @name Rose-UI
 * @author Rose Team
 * @description Interface unlocker for Pengu Loader
 * @link https://github.com/Alban1911/Rose-UI
 */
(function enableLockedSkinPreview() {
  const LOG_PREFIX = "[Rose-UI][skin-preview]";
  const INLINE_ID = "lpp-ui-unlock-skins-css-inline";
  const BORDER_CLASS = "lpp-skin-border";
  const HIDDEN_CLASS = "lpp-skin-hidden";
  const CHROMA_CONTAINER_CLASS = "lpp-chroma-container";
  const VISIBLE_OFFSETS = new Set([0, 1, 2, 3, 4]);

  const GOLDEN_ROSE_ICON = "data:image/png;base64,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";
  const DISCORD_INVITE_URL = "https://discord.com/invite/roseskins";
  const ROSE_DISCORD_GUILD_ID = "1490473857075642621";
  const ROSE_GITHUB_REPO_API_URL =
    "https://api.github.com/repos/Alban1911/Rose";
  const ROSE_GITHUB_BADGE_FALLBACK_URL =
    "https://img.shields.io/badge/GitHub-Stars-32A832?style=flat&logo=github&logoColor=white";
  let roseGithubStarsPromise = null;

  // The welcome modal is rendered by Pengu's signed core module. Keep its
  // links working without modifying the signed binary when external badge
  // providers change or the embedded server ID becomes stale.
  function getRoseGithubStars() {
    if (roseGithubStarsPromise) return roseGithubStarsPromise;

    roseGithubStarsPromise = fetch(ROSE_GITHUB_REPO_API_URL, {
      cache: "no-store",
    })
      .then((response) => {
        if (!response.ok) throw new Error("GitHub API request failed");
        return response.json();
      })
      .then((repository) => {
        const stars = Number(repository && repository.stargazers_count);
        return Number.isSafeInteger(stars) && stars >= 0 ? stars : null;
      })
      .catch(() => null);

    return roseGithubStarsPromise;
  }

  function getRoseGithubBadgeUrl(stars) {
    const message = encodeURIComponent(stars + " stars");
    return (
      "https://img.shields.io/badge/GitHub-" +
      message +
      "-32A832?style=flat&logo=github&logoColor=white"
    );
  }

  function fixPenguWelcomeBadges(shadowRoot) {
    const badges = shadowRoot.querySelectorAll(
      'img[src*="img.shields.io/discord/"], img[src*="img.shields.io/github/stars/"]'
    );

    badges.forEach((badge) => {
      const source = badge.getAttribute("src") || "";

      if (source.includes("/discord/")) {
        const fixedSource = source.replace(
          /\/discord\/\d+/,
          "/discord/" + ROSE_DISCORD_GUILD_ID
        );
        if (fixedSource !== source) {
          badge.setAttribute("src", fixedSource);
        }
        return;
      }

      if (source.includes("/github/stars/")) {
        badge.setAttribute("src", ROSE_GITHUB_BADGE_FALLBACK_URL);
        getRoseGithubStars().then((stars) => {
          if (stars === null || !badge.isConnected) return;
          badge.setAttribute("src", getRoseGithubBadgeUrl(stars));
        });
      }
    });
  }

  function setupPenguWelcomeBadgeFix() {
    let attachedHost = null;
    let shadowObserver = null;

    const attach = () => {
      const host = document.getElementById("pengu-root");
      const shadowRoot = host && host.shadowRoot;
      if (!shadowRoot) return false;

      if (attachedHost === host) {
        fixPenguWelcomeBadges(shadowRoot);
        return true;
      }

      if (shadowObserver) shadowObserver.disconnect();
      attachedHost = host;
      fixPenguWelcomeBadges(shadowRoot);
      shadowObserver = new MutationObserver(() => {
        fixPenguWelcomeBadges(shadowRoot);
      });
      shadowObserver.observe(shadowRoot, {
        attributes: true,
        attributeFilter: ["src"],
        childList: true,
        subtree: true,
      });
      return true;
    };

    if (attach()) return;

    const documentObserver = new MutationObserver(() => {
      if (attach()) documentObserver.disconnect();
    });
    documentObserver.observe(document.documentElement, {
      childList: true,
      subtree: true,
    });
    setTimeout(() => documentObserver.disconnect(), 30000);
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

  let lastBaseSkinSkipRequest = 0;
  const BASE_SKIN_SKIP_REQUEST_TIME_WINDOW_MS = 5000;

  function handleSkipBaseSkin(payload) {
    lastBaseSkinSkipRequest = Date.now();
    log.info("received base skin skip request from rose");
  }

  // TODO Preferably move bridge communication logic and websocket interception to a separate Pengu plugin like ROSE-CORE,
  // which provides a simple interface for adding custom observers for bridge and socket instead of duplicating this kind
  // of code over all the plugins; this will do for now though
  function interceptChampSelectWebsocket() {
    window.rcp.postInit("rcp-fe-lol-champ-select", (api) => {
      try {
        const ws = api.champSelectBinding.socket._websocket;
        const parentOnMessage = ws.onmessage;

        ws.onmessage = function (event) {
          try {
            const payload = JSON.parse(event.data);
            if (payload[1] == "OnJsonApiEvent") {
              const eventData = payload[2];
              if (eventData["uri"] == "/lol-champ-select/v1/skin-selector-info") {
                // // **Bridge-less implementation** (don't use: bridge implementation is more reliable)
                //
                // const data = eventData["data"];
                // 
                // data is null in event type DELETE
                // check if base skin
                // if (data?.["selectedSkinId"] % 1000 == 0) {
                //   log.info("skipping base skin");
                //   // skip delegation
                //   return;
                // }

                // Not a DELETE event
                if (eventData["data"]?.["selectedSkinId"] != 0) {
                  if (Date.now() - lastBaseSkinSkipRequest < BASE_SKIN_SKIP_REQUEST_TIME_WINDOW_MS) {
                    log.info("skipping base skin");
                    // skip delegation
                    return;
                  } else {
                    log.info("not skipping base skin: no request received from rose (in time)");
                  }
                }
              }
            }

            return parentOnMessage.call(this, event);
          } catch(e) {
            log.error("Error during WebSocket response parse: ", e);
          }
        };
        log.info("Websocket Interception successful");
      } catch (e) {
        log.error("Failed WebSocket interception: ", e);
      }
    });
  }

  const INLINE_RULES = `
    lol-uikit-navigation-item.menu_item_Golden\\ Rose {
      position: relative;
    }

    lol-uikit-navigation-item.menu_item_Golden\\ Rose .menu-item-icon {
      -webkit-mask-size: contain !important;
      -webkit-mask-repeat: no-repeat !important;
      -webkit-mask-position: center !important;
      mask-size: contain !important;
      mask-repeat: no-repeat !important;
      mask-position: center !important;
    }

    /* Prevent active state styling for Golden Rose */
    lol-uikit-navigation-item.menu_item_Golden\\ Rose .section.active::before,
    lol-uikit-navigation-item.menu_item_Golden\\ Rose .section.active::after,
    lol-uikit-navigation-item.menu_item_Golden\\ Rose .section.active,
    lol-uikit-navigation-item.menu_item_Golden\\ Rose .section.active .section-glow,
    lol-uikit-navigation-item.menu_item_Golden\\ Rose .section.active .section-glow-container {
      display: none !important;
      background: none !important;
      background-image: none !important;
    }

    /* Prevent hover state from showing navigation pointer */
    lol-uikit-navigation-item.menu_item_Golden\\ Rose .section:hover::after {
      opacity: 0 !important;
      background: none !important;
      background-image: none !important;
    }

    .skin-selection-carousel .skin-selection-item {
      position: relative;
      z-index: 1;
    }

    .skin-selection-carousel .skin-selection-item .skin-selection-item-information {
      position: relative;
      z-index: 2;
    }

    .skin-selection-carousel .skin-selection-item.disabled,
    .skin-selection-carousel .skin-selection-item[aria-disabled="true"] {
      filter: grayscale(0) saturate(1.1) contrast(1.05) !important;
      -webkit-filter: grayscale(0) saturate(1.1) contrast(1.05) !important;
      pointer-events: auto !important;
      cursor: pointer !important;
    }

    .skin-selection-carousel .skin-selection-item.disabled .skin-selection-thumbnail,
    .skin-selection-carousel .skin-selection-item[aria-disabled="true"] .skin-selection-thumbnail {
      filter: grayscale(0) saturate(1.15) contrast(1.05) !important;
      -webkit-filter: grayscale(0) saturate(1.15) contrast(1.05) !important;
      transition: filter 0.25s ease;
    }

    /* Hover glow effect for owned skins (matching official client) */
    .skin-selection-carousel .skin-selection-item:not(.disabled):not([aria-disabled="true"]):not(.skin-selection-item-selected):hover .skin-selection-thumbnail {
      filter: brightness(1.2) saturate(1.1) !important;
      -webkit-filter: brightness(1.2) saturate(1.1) !important;
      transition: filter 0.25s ease;
    }

    /* Hover glow effect for unowned skins (identical to owned - override base filters on hover) */
    .skin-selection-carousel .skin-selection-item.disabled:not(.skin-selection-item-selected):hover .skin-selection-thumbnail,
    .skin-selection-carousel .skin-selection-item[aria-disabled="true"]:not(.skin-selection-item-selected):hover .skin-selection-thumbnail {
      filter: brightness(1.2) saturate(1.1) !important;
      -webkit-filter: brightness(1.2) saturate(1.1) !important;
      transition: filter 0.25s ease;
    }

    .skin-selection-carousel .skin-selection-item.disabled::before,
    .skin-selection-carousel .skin-selection-item.disabled::after,
    .skin-selection-carousel .skin-selection-item[aria-disabled="true"]::before,
    .skin-selection-carousel .skin-selection-item[aria-disabled="true"]::after,
    .skin-selection-carousel .skin-selection-item.disabled .skin-selection-thumbnail::before,
    .skin-selection-carousel .skin-selection-item.disabled .skin-selection-thumbnail::after,
    .skin-selection-carousel .skin-selection-item[aria-disabled="true"] .skin-selection-thumbnail::before,
    .skin-selection-carousel .skin-selection-item[aria-disabled="true"] .skin-selection-thumbnail::after {
      display: none !important;
    }

    .skin-selection-carousel .skin-selection-item.disabled .locked-state,
    .skin-selection-carousel .skin-selection-item[aria-disabled="true"] .locked-state {
      display: none !important;
    }

    .skin-selection-carousel .skin-selection-item.${HIDDEN_CLASS} {
      pointer-events: none !important;
    }

    .champion-select .uikit-background-switcher.locked:after {
      background: none !important;
    }

    .unlock-skin-hit-area {
      display: none !important;
      pointer-events: none !important;
    }

    .unlock-skin-hit-area .locked-state {
      display: none !important;
    }

    .skin-selection-carousel-container .skin-selection-carousel .skin-selection-item .skin-selection-thumbnail {
      height: 100% !important;
      margin: 0 !important;
      transition: filter 0.25s ease !important;
      transform: none !important;
    }

    .skin-selection-carousel-container .skin-selection-carousel .skin-selection-item.skin-selection-item-selected {
      background: #3c3c41 !important;
    }

    .skin-selection-carousel-container .skin-selection-carousel .skin-selection-item.skin-selection-item-selected .skin-selection-thumbnail {
      height: 100% !important;
      margin: 0 !important;
    }

    .skin-selection-carousel .skin-selection-item .lpp-skin-border {
      position: absolute;
      inset: -2px;
      border: 2px solid transparent;
      border-image-source: linear-gradient(0deg, #4f4f54 0%, #3c3c41 50%, #29272b 100%);
      border-image-slice: 1;
      border-radius: inherit;
      box-sizing: border-box;
      pointer-events: none;
      z-index: 0;
    }

    .skin-selection-carousel .skin-selection-item.skin-carousel-offset-2 .lpp-skin-border {
      border: 2px solid transparent;
      border-image-source: linear-gradient(0deg, #c8aa6e 0%, #c89b3c 44%, #a07b32 59%, #785a28 100%);
      border-image-slice: 1;
      box-shadow: inset 0 0 0 1px rgba(1, 10, 19, 0.6);
    }

    /* Golden border on hover for all skins (matching official client) */
    .skin-selection-carousel .skin-selection-item:not(.skin-selection-item-selected):hover .lpp-skin-border {
      border: 2px solid transparent;
      border-image-source: linear-gradient(0deg, #c8aa6e 0%, #c89b3c 44%, #a07b32 59%, #785a28 100%);
      border-image-slice: 1;
      box-shadow: inset 0 0 0 1px rgba(1, 10, 19, 0.6);
    }

    .skin-selection-carousel .skin-selection-item .${CHROMA_CONTAINER_CLASS} {
      position: absolute;
      inset: 0;
      display: flex;
      align-items: flex-end;
      justify-content: center;
      pointer-events: none;
      z-index: 4;
      overflow: hidden;
    }

    .skin-selection-carousel .skin-selection-item .${CHROMA_CONTAINER_CLASS} .chroma-button {
      display: none !important;
      pointer-events: none !important;
    }
    /* Rose owns chroma selection; keep the native client flyout closed. */
    .shared-skin-chroma-modal {
      display: none !important;
      pointer-events: none !important;
    }
    .chroma-button.chroma-selection {
      display: none !important;
    }

    /* Remove grey filters and locks */
    .thumbnail-wrapper {
      filter: grayscale(0) saturate(1) contrast(1) !important;
      -webkit-filter: grayscale(0) saturate(1) contrast(1) !important;
    }

    .skin-thumbnail-img {
      filter: grayscale(0) saturate(1) contrast(1) !important;
      -webkit-filter: grayscale(0) saturate(1) contrast(1) !important;
    }

    .locked-state {
      display: none !important;
    }

    .unlock-skin-hit-area {
      display: none !important;
      pointer-events: none !important;
    }

    .skin-selection-carousel-container {
      clip-path: inset(-200px -9999px -9999px -9999px) !important;
    }
  `;

  const log = {
    info: (msg, extra) => console.info(`${LOG_PREFIX} ${msg}`, extra ?? ""),
    warn: (msg, extra) => console.warn(`${LOG_PREFIX} ${msg}`, extra ?? ""),
    error: (msg, extra) => console.error(`${LOG_PREFIX} ${msg}`, extra ?? ""),
  };

  function injectInlineRules() {
    if (document.getElementById(INLINE_ID)) {
      return;
    }

    const styleTag = document.createElement("style");
    styleTag.id = INLINE_ID;
    styleTag.textContent = INLINE_RULES;
    document.head.appendChild(styleTag);
    log.info("inline styles applied");
  }

  function ensureBorderFrame(skinItem) {
    if (!skinItem) {
      return;
    }

    let border = skinItem.querySelector(`.${BORDER_CLASS}`);
    if (!border) {
      border = document.createElement("div");
      border.className = BORDER_CLASS;
      border.setAttribute("aria-hidden", "true");
    }

    const chromaContainer = skinItem.querySelector(
      `.${CHROMA_CONTAINER_CLASS}`
    );
    if (chromaContainer && border.nextSibling !== chromaContainer) {
      skinItem.insertBefore(border, chromaContainer);
      return;
    }

    if (border.parentElement !== skinItem || border !== skinItem.firstChild) {
      skinItem.insertBefore(border, skinItem.firstChild || null);
    }
  }

  function ensureChromaContainer(skinItem) {
    if (!skinItem) {
      return;
    }

    const chromaButton = skinItem.querySelector(".outer-mask .chroma-button");
    if (!chromaButton) {
      return;
    }

    let container = skinItem.querySelector(`.${CHROMA_CONTAINER_CLASS}`);
    if (!container) {
      container = document.createElement("div");
      container.className = CHROMA_CONTAINER_CLASS;
      container.setAttribute("aria-hidden", "true");
      skinItem.appendChild(container);
    } else if (container.parentElement !== skinItem) {
      skinItem.appendChild(container);
    }

    if (
      container.previousSibling &&
      !container.previousSibling.classList?.contains(BORDER_CLASS)
    ) {
      const border = skinItem.querySelector(`.${BORDER_CLASS}`);
      if (border) {
        skinItem.insertBefore(border, container);
      }
    }

    if (chromaButton.parentElement !== container) {
      container.appendChild(chromaButton);
    }
  }

  function parseCarouselOffset(skinItem) {
    const offsetClass = Array.from(skinItem.classList).find((cls) =>
      cls.startsWith("skin-carousel-offset")
    );
    if (!offsetClass) {
      return null;
    }

    const match = offsetClass.match(/skin-carousel-offset-(-?\d+)/);
    if (!match) {
      return null;
    }

    const value = Number.parseInt(match[1], 10);
    return Number.isNaN(value) ? null : value;
  }

  function isOffsetVisible(offset) {
    if (offset === null) {
      return true;
    }

    return VISIBLE_OFFSETS.has(offset);
  }

  function applyOffsetVisibility(skinItem) {
    if (!skinItem) {
      return;
    }

    const offset = parseCarouselOffset(skinItem);
    const shouldBeVisible = isOffsetVisible(offset);

    skinItem.classList.toggle("lpp-visible-skin", shouldBeVisible);
    skinItem.classList.toggle(HIDDEN_CLASS, !shouldBeVisible);

    if (shouldBeVisible) {
      skinItem.style.removeProperty("pointer-events");
    } else {
      skinItem.style.setProperty("pointer-events", "none", "important");
    }
  }

  function markSkinsAsOwned() {
    // Remove unowned class and add owned class to thumbnail-wrapper elements
    document
      .querySelectorAll(".thumbnail-wrapper.unowned")
      .forEach((wrapper) => {
        wrapper.classList.remove("unowned");
        wrapper.classList.add("owned");
      });

    // Replace purchase-available with active
    document.querySelectorAll(".purchase-available").forEach((element) => {
      element.classList.remove("purchase-available");
      element.classList.add("active");
    });

    // Remove purchase-disabled class from any element
    document.querySelectorAll(".purchase-disabled").forEach((element) => {
      element.classList.remove("purchase-disabled");
    });
  }

  function removeAgeRatingInChampSelect() {
    if (!document.querySelector(".champion-select") && !document.querySelector(".skin-selection-carousel")) {
      return;
    }
    document.querySelectorAll(".vng-age-rating").forEach((el) => el.remove());
    document.querySelectorAll(".vng-age-rating-container").forEach((el) => el.remove());
  }

  function scanSkinSelection() {
    injectInlineRules();

    document.querySelectorAll(".skin-selection-item").forEach((skinItem) => {
      ensureChromaContainer(skinItem);
      ensureBorderFrame(skinItem);
      applyOffsetVisibility(skinItem);
    });

    // Mark skins as owned in Swiftplay
    markSkinsAsOwned();

    // Remove age rating classes when in champ select
    removeAgeRatingInChampSelect();
  }

  function setupSkinObserver() {
    const observer = new MutationObserver(() => {
      scanSkinSelection();
      markSkinsAsOwned();
    });
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["class"],
    });

    // Re-scan periodically as a safety net (LCU sometimes swaps DOM wholesale)
    const intervalId = setInterval(() => {
      scanSkinSelection();
      markSkinsAsOwned();
    }, 500);

    const handleResize = () => {
      scanSkinSelection();
    };
    window.addEventListener("resize", handleResize, { passive: true });

    document.addEventListener(
      "visibilitychange",
      () => {
        if (document.visibilityState === "visible") {
          scanSkinSelection();
        }
      },
      false
    );

    // Return cleanup in case we ever need it
    return () => {
      observer.disconnect();
      clearInterval(intervalId);
      window.removeEventListener("resize", handleResize);
    };
  }

  // Observer lifecycle - only run during ChampSelect/FINALIZATION.
  // See GitHub issue #22: the 500ms poll + MutationObserver steal CPU
  // from the League game process during matches.
  let skinObserverCleanup = null;

  function startSkinObserverGated() {
    if (skinObserverCleanup) return;
    skinObserverCleanup = setupSkinObserver();
  }

  function stopSkinObserverGated() {
    if (!skinObserverCleanup) return;
    try {
      skinObserverCleanup();
    } catch (e) {
      // ignore cleanup errors
    }
    skinObserverCleanup = null;
  }

  function handlePhaseChangeFromPython(data) {
    const phase = data && data.phase;
    if (!phase) return;
    // Stop only during actively-playing InProgress.  markSkinsAsOwned() is
    // Swiftplay-specific and runs during Lobby phase, so we can't restrict
    // to ChampSelect.  See GitHub issue #22.
    if (phase === "InProgress") {
      stopSkinObserverGated();
    } else {
      startSkinObserverGated();
    }
  }

  function attachGoldenRoseListeners(navItem) {
    // Check if listeners already attached
    if (navItem.dataset.lppDiscordAttached === "true") {
      return;
    }

    // Add click handler to nav item - open settings panel
    navItem.addEventListener(
      "click",
      (e) => {
        const lastActiveNavItem = document.querySelector(".main-nav-bar > * > lol-uikit-navigation-item[active]");
        if (lastActiveNavItem) {
          lastActiveNavItem.setAttribute("roseLastActive", true);
        }

        // Dispatch event to open settings panel
        const event = new CustomEvent("rose-open-settings", {
          detail: { navItem: navItem },
          bubbles: true,
          cancelable: true,
        });
        window.dispatchEvent(event);
        log.info("Dispatched rose-open-settings event from Golden Rose button");
      },
      true
    ); // Use capture phase to intercept early

    // Also prevent section click from bubbling up - wait for section to exist
    const setupSectionHandlers = () => {
      const section = navItem.querySelector(".section");
      if (section && !section.dataset.lppDiscordHandler) {
        section.dataset.lppDiscordHandler = "true";

        section.addEventListener(
          "click",
          (e) => {
            e.stopPropagation();
            e.preventDefault();

            // Dispatch event to open settings panel
            const event = new CustomEvent("rose-open-settings", {
              detail: { navItem: navItem },
              bubbles: true,
              cancelable: true,
            });
            window.dispatchEvent(event);
            log.info(
              "Dispatched rose-open-settings event from Golden Rose section"
            );

            // Prevent active class
            section.classList.remove("active");
          },
          true
        );

        // Watch for active class being added and remove it immediately
        const activeObserver = new MutationObserver((mutations) => {
          mutations.forEach((mutation) => {
            if (
              mutation.type === "attributes" &&
              mutation.attributeName === "class"
            ) {
              if (section.classList.contains("active")) {
                section.classList.remove("active");
              }
            }
          });
        });

        activeObserver.observe(section, {
          attributes: true,
          attributeFilter: ["class"],
        });

        // Store observer reference for cleanup if needed
        navItem.dataset.lppActiveObserver = "true";
        return true;
      }
      return false;
    };

    // Try immediately, then watch for section to appear
    if (!setupSectionHandlers()) {
      const sectionObserver = new MutationObserver(() => {
        if (setupSectionHandlers()) {
          sectionObserver.disconnect();
        }
      });

      sectionObserver.observe(navItem, {
        childList: true,
        subtree: true,
      });

      // Also try after a short delay (Ember might take time to initialize)
      setTimeout(() => {
        setupSectionHandlers();
        sectionObserver.disconnect();
      }, 500);
    }

    // Mark as attached
    navItem.dataset.lppDiscordAttached = "true";
  }

  function injectGoldenRoseNavItem() {
    const rightNavMenu = document.querySelector(".right-nav-menu");
    if (!rightNavMenu) {
      return false;
    }

    // Check if Golden Rose item already exists
    const existingItem = rightNavMenu.querySelector(
      '.menu_item_Golden, lol-uikit-navigation-item .menu-item-icon[style*="golden_rose"]'
    );
    if (existingItem) {
      const navItem = existingItem.closest("lol-uikit-navigation-item") || existingItem;
      if (navItem) {
        attachGoldenRoseListeners(navItem);
        const iconEl = navItem.querySelector(".menu-item-icon");
        if (iconEl) {
          iconEl.style.webkitMaskImage = `url("${GOLDEN_ROSE_ICON}")`;
          iconEl.style.maskImage = `url("${GOLDEN_ROSE_ICON}")`;
        }
      }
      return true;
    }

    // Create the navigation item
    const navItem = document.createElement("lol-uikit-navigation-item");
    navItem.id = `ember${Date.now()}`;
    navItem.className =
      "main-navigation-menu-item menu_item_Golden Rose ember-view";

    // Create icon wrapper structure
    const iconWrapper = document.createElement("div");
    iconWrapper.className = "menu-item-icon-wrapper";

    const glow = document.createElement("div");
    glow.className = "menu-item-glow";

    const icon = document.createElement("div");
    icon.className = "menu-item-icon";
    icon.style.webkitMaskImage = `url("${GOLDEN_ROSE_ICON}")`;
    icon.style.maskImage = `url("${GOLDEN_ROSE_ICON}")`;

    iconWrapper.appendChild(glow);
    iconWrapper.appendChild(icon);
    navItem.appendChild(iconWrapper);

    // Insert at the beginning of the nav menu
    const firstChild = rightNavMenu.firstChild;
    if (firstChild) {
      rightNavMenu.insertBefore(navItem, firstChild);
    } else {
      rightNavMenu.appendChild(navItem);
    }

    // Add separator after the Golden Rose item
    const separator = document.createElement("div");
    separator.className = "right-nav-vertical-rule";
    rightNavMenu.insertBefore(separator, navItem.nextSibling);

    // Attach Discord click listeners
    attachGoldenRoseListeners(navItem);

    log.info("Golden Rose navigation item injected");
    return true;
  }

  function setupNavObserver() {
    // Try to inject immediately
    if (injectGoldenRoseNavItem()) {
      return;
    }

    // If not found, observe for nav menu creation
    const observer = new MutationObserver(() => {
      if (injectGoldenRoseNavItem()) {
        observer.disconnect();
      }
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true,
    });

    // Also check periodically as a safety net
    const intervalId = setInterval(() => {
      if (injectGoldenRoseNavItem()) {
        clearInterval(intervalId);
        observer.disconnect();
      }
    }, 500);

    // Cleanup after a reasonable time
    setTimeout(() => {
      observer.disconnect();
      clearInterval(intervalId);
    }, 30000);
  }

  let _initializing = false;
  let _initialized = false;
  let _retryCount = 0;
  const MAX_RETRIES = 100; // Maximum number of retry attempts

  async function init() {
    // Prevent multiple concurrent initializations (but allow recursive retry)
    if (_initialized) {
      return;
    }
    // If already initializing, only proceed if this is a recursive retry call
    // (indicated by document being ready now when it wasn't before)
    if (_initializing) {
      // Allow recursive call to proceed only if document is now ready
      if (!document || !document.head) {
        // Check retry limit to prevent unbounded retries
        if (_retryCount >= MAX_RETRIES) {
          log.error(
            `Init failed: Maximum retry count (${MAX_RETRIES}) reached. Document still not ready.`
          );
          _initializing = false;
          _retryCount = 0; // Reset for next attempt
          return;
        }
        _retryCount++;
        // Still not ready, schedule another retry
        requestAnimationFrame(() => {
          init().catch((err) => {
            log.error("Init failed:", err);
            _initializing = false;
          });
        });
        return;
      }
      // Document is now ready, proceed with initialization
    } else {
      // First call - set flag BEFORE document check to prevent race condition
      _initializing = true;
      // Don't reset retry counter here - it should persist across retries
      // Only reset on successful initialization

      if (!document || !document.head) {
        // Check retry limit BEFORE incrementing to prevent unbounded retries
        if (_retryCount >= MAX_RETRIES) {
          log.error(
            `Init failed: Maximum retry count (${MAX_RETRIES}) reached. Document still not ready.`
          );
          _initializing = false;
          _retryCount = 0; // Reset for next attempt
          return;
        }
        _retryCount++;
        // Use synchronous wrapper to prevent multiple concurrent schedules
        requestAnimationFrame(() => {
          init().catch((err) => {
            log.error("Init failed:", err);
            _initializing = false;
          });
        });
        return;
      }
    }
    
    try {
      // Wait for bridge to be available (provides port)
      const bridge = await waitForBridge();

      // Subscribe to skip-base-skin messages from the shared bridge
      bridge.subscribe("skip-base-skin", handleSkipBaseSkin);
      bridge.subscribe("phase-change", handlePhaseChangeFromPython);
      setupPenguWelcomeBadgeFix();

      interceptChampSelectWebsocket();
      injectInlineRules();
      scanSkinSelection();
      // Default-on: first phase-change from Python will shut the observer
      // off again if we're already in-game.  See issue #22.
      startSkinObserverGated();
      setupNavObserver();
      log.info("skin preview overrides active");
      _initialized = true;
      _retryCount = 0; // Reset retry counter on success
    } catch (err) {
      log.error("Init failed:", err);
      throw err; // Re-throw to propagate error to .catch() handlers
    } finally {
      _initializing = false;
    }
  }

  if (typeof document === "undefined") {
    log.warn("document unavailable; aborting");
    return;
  }

  if (document.readyState === "loading") {
    document.addEventListener(
      "DOMContentLoaded",
      () => {
        init().catch((err) => {
          log.error("Init failed:", err);
        });
      },
      { once: true }
    );
  } else {
    init().catch((err) => {
      log.error("Init failed:", err);
    });
  }
})();
