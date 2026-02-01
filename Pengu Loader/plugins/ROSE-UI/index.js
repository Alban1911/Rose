/**
 * @name Rose-UI
 * @author Rose Team
 * @description Interface unlocker for Pengu Loader
 * @link https://github.com/Alban1911/Rose-UI
 */
(function enableLockedSkinPreview() {
  const LOG_PREFIX = "[Rose-UI][skin-preview]";
  const STYLE_ID = "lpp-ui-unlock-skins-css";
  const INLINE_ID = `${STYLE_ID}-inline`;
  const STYLESHEET_NAME = "style.css";
  const BORDER_CLASS = "lpp-skin-border";
  const HIDDEN_CLASS = "lpp-skin-hidden";
  const CHROMA_CONTAINER_CLASS = "lpp-chroma-container";
  const VISIBLE_OFFSETS = new Set([0, 1, 2, 3, 4]);

  const DISCORD_INVITE_URL = "https://discord.gg/cDepnwVS8Z";

  let BRIDGE_PORT = 50000; // Default, will be updated from /bridge-port endpoint
  const BRIDGE_PORT_STORAGE_KEY = "rose_bridge_port";
  const DISCOVERY_START_PORT = 50000;
  const DISCOVERY_END_PORT = 50010;

  // Load bridge port with file-based discovery and localStorage caching
  async function loadBridgePort() {
    try {
      // First, check localStorage for cached port
      const cachedPort = localStorage.getItem(BRIDGE_PORT_STORAGE_KEY);
      if (cachedPort) {
        const port = parseInt(cachedPort, 10);
        if (!isNaN(port) && port > 0) {
          // Verify cached port is still valid with shorter timeout
          try {
            const response = await fetch(`http://127.0.0.1:${port}/bridge-port`, {
              signal: AbortSignal.timeout(50)
            });
            if (response.ok) {
              const portText = await response.text();
              const fetchedPort = parseInt(portText.trim(), 10);
              if (!isNaN(fetchedPort) && fetchedPort > 0) {
                BRIDGE_PORT = fetchedPort;
                if (window?.console) {
                  console.log(`${LOG_PREFIX} Loaded bridge port from cache: ${BRIDGE_PORT}`);
                }
                return true;
              }
            }
          } catch (e) {
            // Cached port invalid, continue to discovery
            localStorage.removeItem(BRIDGE_PORT_STORAGE_KEY);
          }
        }
      }

      // OPTIMIZATION: Try default port 50000 FIRST before scanning all ports
      try {
        const response = await fetch(`http://127.0.0.1:50000/bridge-port`, {
          signal: AbortSignal.timeout(50)
        });
        if (response.ok) {
          const portText = await response.text();
          const fetchedPort = parseInt(portText.trim(), 10);
          if (!isNaN(fetchedPort) && fetchedPort > 0) {
            BRIDGE_PORT = fetchedPort;
            localStorage.setItem(BRIDGE_PORT_STORAGE_KEY, String(BRIDGE_PORT));
            if (window?.console) {
              console.log(`${LOG_PREFIX} Loaded bridge port: ${BRIDGE_PORT}`);
            }
            return true;
          }
        }
      } catch (e) {
        // Port 50000 not ready, continue to discovery
      }

      // OPTIMIZATION: Try fallback port 50001 SECOND
      try {
        const response = await fetch(`http://127.0.0.1:50001/bridge-port`, {
          signal: AbortSignal.timeout(50)
        });
        if (response.ok) {
          const portText = await response.text();
          const fetchedPort = parseInt(portText.trim(), 10);
          if (!isNaN(fetchedPort) && fetchedPort > 0) {
            BRIDGE_PORT = fetchedPort;
            localStorage.setItem(BRIDGE_PORT_STORAGE_KEY, String(BRIDGE_PORT));
            if (window?.console) {
              console.log(`${LOG_PREFIX} Loaded bridge port: ${BRIDGE_PORT}`);
            }
            return true;
          }
        }
      } catch (e) {
        // Port 50001 not ready, continue to discovery
      }

      // OPTIMIZATION: Parallel port discovery instead of sequential
      const portPromises = [];
      for (let port = DISCOVERY_START_PORT; port <= DISCOVERY_END_PORT; port++) {
        portPromises.push(
          fetch(`http://127.0.0.1:${port}/bridge-port`, {
            signal: AbortSignal.timeout(100)
          })
            .then(response => {
              if (response.ok) {
                return response.text().then(portText => {
                  const fetchedPort = parseInt(portText.trim(), 10);
                  if (!isNaN(fetchedPort) && fetchedPort > 0) {
                    return { port: fetchedPort, sourcePort: port };
                  }
                  return null;
                });
              }
              return null;
            })
            .catch(() => null)
        );
      }

      // Wait for first successful response
      const results = await Promise.allSettled(portPromises);
      for (const result of results) {
        if (result.status === 'fulfilled' && result.value) {
          BRIDGE_PORT = result.value.port;
          localStorage.setItem(BRIDGE_PORT_STORAGE_KEY, String(BRIDGE_PORT));
          if (window?.console) {
            console.log(`${LOG_PREFIX} Loaded bridge port: ${BRIDGE_PORT}`);
          }
          return true;
        }
      }

      // Fallback: try old /port endpoint (parallel as well)
      const legacyPromises = [];
      for (let port = DISCOVERY_START_PORT; port <= DISCOVERY_END_PORT; port++) {
        legacyPromises.push(
          fetch(`http://127.0.0.1:${port}/port`, {
            signal: AbortSignal.timeout(100)
          })
            .then(response => {
              if (response.ok) {
                return response.text().then(portText => {
                  const fetchedPort = parseInt(portText.trim(), 10);
                  if (!isNaN(fetchedPort) && fetchedPort > 0) {
                    return { port: fetchedPort, sourcePort: port };
                  }
                  return null;
                });
              }
              return null;
            })
            .catch(() => null)
        );
      }

      const legacyResults = await Promise.allSettled(legacyPromises);
      for (const result of legacyResults) {
        if (result.status === 'fulfilled' && result.value) {
          BRIDGE_PORT = result.value.port;
          localStorage.setItem(BRIDGE_PORT_STORAGE_KEY, String(BRIDGE_PORT));
          if (window?.console) {
            console.log(`${LOG_PREFIX} Loaded bridge port (legacy): ${BRIDGE_PORT}`);
          }
          return true;
        }
      }

      if (window?.console) {
        console.warn(
          `${LOG_PREFIX} Failed to load bridge port, using default (50000)`
        );
      }
      return false;
    } catch (e) {
      if (window?.console) {
        console.warn(`${LOG_PREFIX} Error loading bridge port:`, e);
      }
      return false;
    }
  }


  const INLINE_RULES = `
    lol-uikit-navigation-item.menu_item_Golden\\ Rose {
      position: relative;
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
    }

    .skin-selection-carousel .skin-selection-item .${CHROMA_CONTAINER_CLASS} .chroma-button {
      pointer-events: auto;
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

  `;

  const log = {
    info: (msg, extra) => console.info(`${LOG_PREFIX} ${msg}`, extra ?? ""),
    warn: (msg, extra) => console.warn(`${LOG_PREFIX} ${msg}`, extra ?? ""),
  };

  function resolveStylesheetHref() {
    try {
      const script =
        document.currentScript ||
        document.querySelector('script[src$="index.js"]') ||
        document.querySelector('script[src*="LPP-UI"]');

      if (script?.src) {
        return new URL(STYLESHEET_NAME, script.src).toString();
      }
    } catch (error) {
      log.warn(
        "failed to resolve stylesheet URL; falling back to relative path",
        error
      );
    }

    return STYLESHEET_NAME;
  }

  function injectInlineRules() {
    if (document.getElementById(INLINE_ID)) {
      return;
    }

    const styleTag = document.createElement("style");
    styleTag.id = INLINE_ID;
    styleTag.textContent = INLINE_RULES;
    document.head.appendChild(styleTag);
    log.warn("applied inline fallback styling");
  }

  function removeInlineRules() {
    const existing = document.getElementById(INLINE_ID);
    if (existing) {
      existing.remove();
    }
  }

  function attachStylesheet() {
    if (document.getElementById(STYLE_ID)) {
      return;
    }

    const link = document.createElement("link");
    link.id = STYLE_ID;
    link.rel = "stylesheet";
    link.href = resolveStylesheetHref();

    link.addEventListener("load", () => {
      removeInlineRules();
      log.info("external stylesheet loaded");
    });

    link.addEventListener("error", () => {
      link.remove();
      injectInlineRules();
    });

    document.head.appendChild(link);
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

    // Check if Golden Rose item already exists by checking for the golden_rose.png image
    const existingItem = rightNavMenu.querySelector(
      'lol-uikit-navigation-item .menu-item-icon[style*="golden_rose.png"]'
    );
    if (existingItem) {
      const navItem = existingItem.closest("lol-uikit-navigation-item");
      if (navItem) {
        attachGoldenRoseListeners(navItem);
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
    icon.style.webkitMaskImage = `url(http://127.0.0.1:${BRIDGE_PORT}/asset/golden_rose.png)`;

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
      // Load bridge port before initializing
      await loadBridgePort();

      attachStylesheet();
      scanSkinSelection();
      setupSkinObserver();
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
