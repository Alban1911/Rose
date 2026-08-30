/**
 * @name Rose-Favorites
 * @author Rose Team & Spok0jny
 * @description Non-invasive favorite skins & chromas manager for Pengu Loader
 * @link https://github.com/Alban1911/Rose
 */
(function initFavorites() {
  const LOG_PREFIX = "[Rose-Favorites]";

  let bridge = null;
  let currentChampionId = null;
  let currentSkinId = null;
  let currentFavorites = { skins: [], chromas: {} };
  let allFavorites = {};

  function log(level, message, data = null) {
    const payload = {
      type: "chroma-log",
      source: "LU-Favorites",
      level: level,
      message: message,
      timestamp: Date.now(),
    };
    if (data) payload.data = data;
    if (bridge) bridge.send(payload);

    const consoleMethod =
      level === "error" ? console.error : level === "warn" ? console.warn : console.log;
    consoleMethod(`${LOG_PREFIX} ${message}`, data || "");
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

  const GOLD_STAR_SVG = `
    <svg viewBox="0 0 24 24" width="100%" height="100%">
      <polygon points="12,2 15.09,8.26 22,9.27 17,14.14 18.18,21.02 12,17.77 5.82,21.02 7,14.14 2,9.27 8.91,8.26" 
               fill="#ffd700" stroke="#785a28" stroke-width="1.5" stroke-linejoin="round"/>
    </svg>
  `;

  const INACTIVE_STAR_SVG = `
    <svg viewBox="0 0 24 24" width="100%" height="100%">
      <polygon points="12,2 15.09,8.26 22,9.27 17,14.14 18.18,21.02 12,17.77 5.82,21.02 7,14.14 2,9.27 8.91,8.26" 
               fill="rgba(0, 0, 0, 0.45)" stroke="#c8aa6e" stroke-width="1.5" stroke-linejoin="round"/>
    </svg>
  `;

  const CYAN_STAR_SVG = `
    <svg viewBox="0 0 24 24" width="100%" height="100%">
      <polygon points="12,2 15.09,8.26 22,9.27 17,14.14 18.18,21.02 12,17.77 5.82,21.02 7,14.14 2,9.27 8.91,8.26" 
               fill="#0acbe6" stroke="#005a82" stroke-width="1.5" stroke-linejoin="round"/>
    </svg>
  `;

  const INACTIVE_CYAN_STAR_SVG = `
    <svg viewBox="0 0 24 24" width="100%" height="100%">
      <polygon points="12,2 15.09,8.26 22,9.27 17,14.14 18.18,21.02 12,17.77 5.82,21.02 7,14.14 2,9.27 8.91,8.26" 
               fill="rgba(0, 0, 0, 0.5)" stroke="#0acbe6" stroke-width="1.5" stroke-linejoin="round"/>
    </svg>
  `;

  const CSS_RULES = `
    /* Active Skin Title Star Button */
    .rose-title-star-btn {
      display: inline-flex !important;
      align-items: center !important;
      justify-content: center !important;
      width: 26px !important;
      height: 26px !important;
      padding: 4px !important;
      box-sizing: content-box !important;
      margin-left: 8px !important;
      vertical-align: middle !important;
      cursor: pointer !important;
      pointer-events: auto !important;
      transition: transform 0.15s ease, filter 0.15s ease !important;
      filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.8)) !important;
      z-index: 999 !important;
    }

    .rose-title-star-btn:hover {
      transform: scale(1.25) !important;
    }

    .rose-title-star-btn.active {
      filter: drop-shadow(0 0 8px #ffd700) !important;
    }

    /* Individual Chroma Swatch Star Button */
    .chroma-selection li,
    .chroma-modal .chroma-list li,
    .chroma-information ~ .chroma-selection li {
      position: relative !important;
      overflow: visible !important;
    }

    .rose-chroma-fav-btn {
      position: absolute !important;
      top: -10px !important;
      right: -10px !important;
      width: 22px !important;
      height: 22px !important;
      padding: 4px !important;
      box-sizing: content-box !important;
      cursor: pointer !important;
      pointer-events: auto !important;
      z-index: 1000 !important;
      opacity: 0.75;
      transition: transform 0.15s ease, opacity 0.15s ease, filter 0.15s ease !important;
      filter: drop-shadow(0 0 3px rgba(0, 0, 0, 0.9)) !important;
    }

    .chroma-selection li:hover .rose-chroma-fav-btn,
    .rose-chroma-fav-btn:hover,
    .rose-chroma-fav-btn.active {
      opacity: 1 !important;
    }

    .rose-chroma-fav-btn:hover {
      transform: scale(1.3) !important;
    }

    .rose-chroma-fav-btn.active {
      filter: drop-shadow(0 0 6px #0acbe6) !important;
    }
  `;

  function injectCSS() {
    if (document.getElementById("rose-favorites-css")) return;
    const style = document.createElement("style");
    style.id = "rose-favorites-css";
    style.textContent = CSS_RULES;
    document.head.appendChild(style);
  }

  function getActiveSkinId() {
    const skinState = window.__roseSkinState || {};
    return skinState.skinId || currentSkinId || null;
  }

  function extractSkinId(el) {
    if (!el) return null;
    const dataId =
      el.getAttribute("data-skin-id") ||
      el.getAttribute("data-id") ||
      el.querySelector("[data-skin-id]")?.getAttribute("data-skin-id") ||
      el.querySelector("[data-id]")?.getAttribute("data-id");

    if (dataId && !isNaN(parseInt(dataId, 10)) && parseInt(dataId, 10) > 0) {
      return parseInt(dataId, 10);
    }

    try {
      if (window.Ember && window.Ember.View && window.Ember.View.views && el.id && window.Ember.View.views[el.id]) {
        const view = window.Ember.View.views[el.id];
        const ctx = view.context || view._context || (typeof view.get === "function" ? view.get("context") : null);
        if (ctx) {
          const skin = ctx.skin || ctx.item?.skin || ctx;
          if (skin && (skin.id || skin.skinId)) {
            return parseInt(skin.id || skin.skinId, 10);
          }
        }
      }
    } catch (e) {}

    const img = el.querySelector("img") || (el.tagName === "IMG" ? el : null);
    const bgImage = (img && (img.src || img.getAttribute("src"))) || el.style?.backgroundImage || "";
    const match =
      bgImage.match(/champion-(?:splashes|tiles|chroma-images)\/\d+\/(\d+)\.(?:jpg|png)/i) ||
      bgImage.match(/\/(\d{4,8})\.(?:jpg|png)/i);

    if (match && match[1] && parseInt(match[1], 10) > 0) {
      return parseInt(match[1], 10);
    }

    return null;
  }

  function toggleSkinFavorite(skinId) {
    let targetSkin = skinId || getActiveSkinId();
    if (!targetSkin) return;

    let champId = currentChampionId;
    if (!champId && targetSkin) {
      champId = Math.floor(targetSkin / 1000);
    }
    if (!champId) return;

    log("info", "Toggling skin favorite", { champId, skinId: targetSkin });

    if (bridge) {
      bridge.send({
        type: "favorite-toggle-skin",
        championId: champId,
        skinId: targetSkin,
        timestamp: Date.now(),
      });
    }

    if (!currentFavorites.skins) currentFavorites.skins = [];
    const idx = currentFavorites.skins.indexOf(targetSkin);
    if (idx >= 0) {
      currentFavorites.skins.splice(idx, 1);
      if (currentFavorites.chromas && currentFavorites.chromas[String(targetSkin)]) {
        delete currentFavorites.chromas[String(targetSkin)];
      }
    } else {
      currentFavorites.skins.push(targetSkin);
      if (!currentFavorites.chromas) currentFavorites.chromas = {};
      const skinKey = String(targetSkin);
      if (!currentFavorites.chromas[skinKey]) currentFavorites.chromas[skinKey] = [];
      if (!currentFavorites.chromas[skinKey].includes(targetSkin)) {
        currentFavorites.chromas[skinKey].push(targetSkin);
      }
    }

    updateUI();
  }

  function toggleChromaFavorite(chromaId, skinId) {
    let targetSkin = skinId || getActiveSkinId();
    let targetChroma = chromaId;

    let champId = currentChampionId;
    if (!champId && targetSkin) {
      champId = Math.floor(targetSkin / 1000);
    }
    if (!champId || !targetSkin || !targetChroma) return;

    log("info", "Toggling chroma favorite", { champId, skinId: targetSkin, chromaId: targetChroma });

    if (bridge) {
      bridge.send({
        type: "favorite-toggle-chroma",
        championId: champId,
        skinId: targetSkin,
        chromaId: targetChroma,
        timestamp: Date.now(),
      });
    }

    if (!currentFavorites.skins) currentFavorites.skins = [];
    if (!currentFavorites.skins.includes(targetSkin)) {
      currentFavorites.skins.push(targetSkin);
    }
    if (!currentFavorites.chromas) currentFavorites.chromas = {};
    const skinKey = String(targetSkin);
    if (!currentFavorites.chromas[skinKey]) currentFavorites.chromas[skinKey] = [];

    const cIdx = currentFavorites.chromas[skinKey].indexOf(targetChroma);
    if (cIdx >= 0) {
      currentFavorites.chromas[skinKey].splice(cIdx, 1);
    } else {
      currentFavorites.chromas[skinKey].push(targetChroma);
    }

    updateUI();
  }

  let isInChampSelect = false;

  function updateUI() {
    // Check if we are in Champ Select
    const champSelectEl = document.querySelector(
      ".skin-selection-carousel, #champ-select, .champ-select-bg, .champion-select-main-container, .skin-selection-carousel-container"
    );
    if (isInChampSelect || champSelectEl) {
      // Remove all star buttons from DOM when in Champ Select
      document.querySelectorAll(".rose-title-star-btn, .rose-chroma-fav-btn").forEach((btn) => btn.remove());

      // Still dispatch update to ROSE-RandomSkin so it knows favorite counts
      window.dispatchEvent(
        new CustomEvent("rose-favorites-updated", {
          detail: {
            championId: currentChampionId,
            favorites: currentFavorites,
            allFavorites: allFavorites,
          },
        })
      );
      return;
    }

    const activeSkin = getActiveSkinId();

    // 1. Single Golden Star next to Active Skin Title in Quickplay / Lobby
    if (activeSkin) {
      const isFav = currentFavorites.skins && currentFavorites.skins.includes(activeSkin);

      const titleSelectors = [
        ".champion-name-title",
        ".child-skin-name",
        ".skin-name",
        ".skin-title",
        "[class*='skin-name']",
        "[class*='skin-title']",
      ];

      let targetTitleEl = null;
      for (const selector of titleSelectors) {
        const nodes = document.querySelectorAll(selector);
        for (const node of nodes) {
          if (node.offsetParent !== null && node.textContent.trim().length > 0) {
            targetTitleEl = node;
            break;
          }
        }
        if (targetTitleEl) break;
      }

      // Remove any duplicate star buttons in document
      document.querySelectorAll(".rose-title-star-btn").forEach((btn) => {
        if (btn.parentElement !== targetTitleEl) {
          btn.remove();
        }
      });

      if (targetTitleEl) {
        let starBtn = targetTitleEl.querySelector(".rose-title-star-btn");
        if (!starBtn) {
          starBtn = document.createElement("span");
          starBtn.className = "rose-title-star-btn";
          starBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            e.preventDefault();
            // Dynamically get the currently active skin at click time!
            const currentActive = getActiveSkinId();
            toggleSkinFavorite(currentActive);
          });
          targetTitleEl.appendChild(starBtn);
        }

        starBtn.className = `rose-title-star-btn ${isFav ? "active" : ""}`;
        starBtn.innerHTML = isFav ? GOLD_STAR_SVG : INACTIVE_STAR_SVG;
        starBtn.title = isFav
          ? "Favorited Skin ⭐ (Click to remove from favorites)"
          : "Click to add to Favorite Skins ⭐";
      }
    }

    // 2. Attach Click & Right-Click Favorite Toggle to Quickplay Thumbnails only
    const cards = document.querySelectorAll(".thumbnail-wrapper");
    cards.forEach((card) => {
      if (!card._roseCtxAttached) {
        card._roseCtxAttached = true;
        // On click thumbnail: update currentSkinId dynamically
        card.addEventListener("click", () => {
          const sid = extractSkinId(card);
          if (sid) {
            currentSkinId = sid;
            setTimeout(updateUI, 50);
          }
        });
        // On right-click thumbnail: toggle favorite for that skin
        card.addEventListener("contextmenu", (e) => {
          e.stopPropagation();
          e.preventDefault();
          const sid = extractSkinId(card) || getActiveSkinId();
          if (sid) toggleSkinFavorite(sid);
        });
      }
    });

    // 3. Decorate each individual Chroma button in Chroma Panel (.chroma-selection li)
    if (activeSkin) {
      const chromaItems = document.querySelectorAll(
        ".chroma-selection li, .chroma-modal .chroma-list li, .chroma-list li"
      );
      chromaItems.forEach((li, index) => {
        let chromaId =
          parseInt(
            li.getAttribute("data-chroma-id") ||
              li.getAttribute("data-id") ||
              li.querySelector(".chroma-skin-button")?.getAttribute("data-chroma-id") ||
              li.querySelector(".chroma-skin-button")?.getAttribute("data-id"),
            10
          );

        if (!chromaId || isNaN(chromaId)) {
          chromaId = index === 0 ? activeSkin : activeSkin + index;
        }

        const skinKey = String(activeSkin);
        const isChromaFav =
          currentFavorites.chromas &&
          currentFavorites.chromas[skinKey] &&
          currentFavorites.chromas[skinKey].includes(chromaId);

        let starBtn = li.querySelector(".rose-chroma-fav-btn");
        if (!starBtn) {
          starBtn = document.createElement("div");
          starBtn.className = "rose-chroma-fav-btn";
          starBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            e.preventDefault();
            const currentActive = getActiveSkinId();
            const targetChrId = parseInt(li.dataset.chromaId, 10) || chromaId;
            toggleChromaFavorite(targetChrId, currentActive);
          });
          li.appendChild(starBtn);
        }

        starBtn.className = `rose-chroma-fav-btn ${isChromaFav ? "active" : ""}`;
        starBtn.innerHTML = isChromaFav ? CYAN_STAR_SVG : INACTIVE_CYAN_STAR_SVG;
        starBtn.title = isChromaFav
          ? "Favorited Chroma ⭐ (Click to remove)"
          : "Click to add this Chroma to favorites ⭐";

        if (!li._roseChrCtx) {
          li._roseChrCtx = true;
          li.addEventListener("contextmenu", (e) => {
            e.stopPropagation();
            e.preventDefault();
            const currentActive = getActiveSkinId();
            const targetChrId = parseInt(li.dataset.chromaId, 10) || chromaId;
            toggleChromaFavorite(targetChrId, currentActive);
          });
        }
      });
    }

    // Dispatch update to ROSE-RandomSkin
    window.dispatchEvent(
      new CustomEvent("rose-favorites-updated", {
        detail: {
          championId: currentChampionId,
          favorites: currentFavorites,
          allFavorites: allFavorites,
        },
      })
    );
  }

  function handleFavoritesState(data) {
    log("info", "Received favorites-state", data);
    if (data.championFavorites) currentFavorites = data.championFavorites;
    if (data.allFavorites) allFavorites = data.allFavorites;
    if (data.championId) currentChampionId = data.championId;
    updateUI();
  }

  function handleSkinState(data) {
    if (!data) return;
    if (data.skinId) {
      currentSkinId = data.skinId;
      window.__roseSkinState = Object.assign(window.__roseSkinState || {}, data);
    }
    if (data.championId) {
      if (data.championId !== currentChampionId) {
        currentChampionId = data.championId;
        if (bridge) {
          bridge.send({ type: "request-favorites", championId: currentChampionId });
        }
      }
    }
    setTimeout(updateUI, 50);
  }

  async function start() {
    injectCSS();

    setInterval(updateUI, 400);

    try {
      bridge = await waitForBridge();
      log("info", "Bridge ready in ROSE-Favorites");

      if (bridge.subscribe) {
        bridge.subscribe("favorites-state", handleFavoritesState);
        bridge.subscribe("skin-state", handleSkinState);
        bridge.subscribe("phase-change", (data) => {
          if (data && data.phase) {
            isInChampSelect = data.phase === "ChampSelect" || data.phase === "FINALIZATION";
          }
          if (bridge) bridge.send({ type: "request-favorites", championId: currentChampionId });
          updateUI();
        });
        bridge.subscribe("champion-locked", (data) => {
          if (data.locked && bridge) {
            bridge.send({ type: "request-favorites", championId: currentChampionId });
          }
        });
      }

      window.addEventListener("lu-skin-monitor-state", (e) => {
        if (e.detail) handleSkinState(e.detail);
      });

      bridge.send({ type: "request-favorites" });
    } catch (e) {
      log("error", "Failed to init favorites bridge:", e);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
