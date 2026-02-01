/**
 * @name ROSE-FormsWheel
 * @author Rose Team
 * @description Custom chroma wheel with asset-based buttons - Adapted from ROSE-ChromaWheel
 * @link https://github.com/Alban1911/Rose-FormsWheel
 */
(function createFormsWheel() {
  const LOG_PREFIX = "[FormsWheel]";
  console.log(`${LOG_PREFIX} JS Loaded`);
  const BUTTON_CLASS = "forms-wheel-button";
  const BUTTON_SELECTOR = `.${BUTTON_CLASS}`;
  const PANEL_CLASS = "forms-wheel-panel";
  const PANEL_ID = "forms-wheel-panel-container";
  const SKIN_SELECTORS = [
    ".skin-name-text", // Classic Champ Select
    ".skin-name", // Swiftplay lobby
  ];
  // Supported skins configuration - IMPORTANT: These skins have FORMS, not chromas
  const SUPPORTED_SKINS = new Map([
    [
      82054,
      {
        // Sahn Uzal Mordekaiser - has Forms, not chromas
        buttonFolder: "uzal_buttons",
        formIds: [82054, 82998, 82999], // Base + 2 forms
        formNames: ["Default", "Form 1", "Form 2"],
        championId: 82,
      },
    ],
    [
      25080,
      {
        // Spirit Blossom Morgana - has Forms, not chromas
        buttonFolder: "sbmorg_buttons",
        formIds: [25080, 25999], // Base + 1 form
        formNames: ["Default", "Form 1"],
        championId: 25,
      },
    ],
    [
      875066,
      {
        // Radiant Sett - has Forms, not chromas
        buttonFolder: "radiantsett_buttons",
        formIds: [875066, 875998, 875999], // Base + 2 forms
        formNames: ["Default", "Form 2", "Form 3"],
        championId: 875,
      },
    ],
    [
      147001,
      {
        // KDA Seraphine - has Forms, not chromas
        buttonFolder: "kdasera_buttons",
        formIds: [147001, 147002, 147003], // Base + 2 forms
        formNames: ["Default", "Form 1", "Form 2"],
        championId: 147,
      },
    ],
    [
      37006,
      {
        // DJ Sona - has Forms, not chromas
        buttonFolder: "djsona_buttons",
        formIds: [37006, 37998, 37999], // Base + 2 forms
        formNames: ["Default", "Form 1", "Form 2"],
        championId: 37,
      },
    ],
    [
      222060,
      {
        // Arcane Fractured Jinx - has Forms, not chromas
        buttonFolder: "arcanejinx_buttons",
        formIds: [222060, 222998, 222999], // Base + 2 forms
        formNames: ["Default", "Form 1", "Form 2"],
        championId: 222,
      },
    ],
    [
      145070,
      {
        // Uzi Kaisa - has Forms, not chromas
        buttonFolder: "uzikaisa_buttons",
        formIds: [145070, 145071, 145999], // Base + 2 forms
        formNames: ["Default", "Form 1", "Form 2"],
        championId: 145,
      },
    ],
    [
      234043,
      {
        // Viego - has Forms, not chromas
        buttonFolder: "rrviego_buttons",
        formIds: [234043, 234994, 234995, 234996, 234997, 234998, 234999], // Base + 6 forms
        formNames: ["Default", "Form 2", "Form 3", "Form 4", "Form 5", "Form 6", "Form 7"],
        championId: 234,
      },
    ],
  ]);

  /**
   * Escape HTML special characters to prevent XSS (CWE-79)
   * @param {string} str - String to escape
   * @returns {string} Escaped string safe for innerHTML
   */
  function escapeHtml(str) {
    if (typeof str !== 'string') return String(str);
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function isSupportedSkin(skinId) {
    if (!skinId) return false;
    if (SUPPORTED_SKINS.has(skinId)) return true;
    for (const config of SUPPORTED_SKINS.values()) {
      if (config.formIds.includes(skinId)) return true;
    }
    // Check for HoL skins (Ahri) - these are forms, not chromas
    // Note: Kaisa (145070, 145071, 145999) is now handled via SUPPORTED_SKINS
    if (
      SPECIAL_BASE_SKIN_IDS.has(skinId) ||
      SPECIAL_CHROMA_SKIN_IDS.has(skinId)
    ) {
      // Check if it's a HoL skin (103085, 103086, 103087) - Ahri only
      if (
        skinId === 103085 ||
        skinId === 103086 ||
        skinId === 103087
      ) {
        return true;
      }
    }
    return false;
  }

  function getSkinConfig(skinId) {
    if (!skinId) return null;
    if (SUPPORTED_SKINS.has(skinId)) return SUPPORTED_SKINS.get(skinId);
    for (const [baseSkinId, config] of SUPPORTED_SKINS.entries()) {
      if (config.formIds.includes(skinId)) return config;
    }
    return null;
  }

  function getBaseSkinId(skinId) {
    if (!skinId) return null;
    if (SUPPORTED_SKINS.has(skinId)) return skinId;
    for (const [baseSkinId, config] of SUPPORTED_SKINS.entries()) {
      if (config.formIds.includes(skinId)) return baseSkinId;
    }
    return null;
  }

  const SPECIAL_BASE_SKIN_IDS = new Set([99007, 25080, 103085]);
  const SPECIAL_CHROMA_SKIN_IDS = new Set([100001, 103086, 103087, 88888]);
  const chromaParentMap = new Map();
  let skinMonitorState = null;
  const championSkinCache = new Map(); // championId -> Map(skinId -> skin data)
  const skinChromaCache = new Map(); // skinId -> boolean
  const skinToChampionMap = new Map(); // skinId -> championId
  const pendingChampionRequests = new Map(); // championId -> Promise

  // Track selected chroma for button color update (controlled by Python)
  let selectedChromaData = null; // { id, primaryColor, colors, name }
  let pythonChromaState = null; // { selectedChromaId, chromaColor, chromaColors, currentSkinId }
  let championLocked = false; // Track if a champion is locked

  // Asset paths for custom hover button
  const HOVER_BUTTON_ASSET = "hol-button.png";
  const HOVER_BUTTON_HOVER_ASSET = "hol-button-hover.png";
  let hoverButtonNormalUrl = null;
  let hoverButtonHoverUrl = null;

  // Shared bridge API (provided by ROSE-BridgeInit)
  let bridge = null;

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


  // Audio: play official chroma click sound when a chroma panel button is clicked
  // Using the same endpoint the client uses: sfx-cs-button-chromas-click.ogg
  const CHROMA_CLICK_SOUND_URL =
    "https://127.0.0.1:65236/fe/lol-champ-select/sounds/sfx-cs-button-chromas-click.ogg";

  let chromaClickAudio = null;
  function playChromaClickSound() {
    try {
      if (!chromaClickAudio) {
        chromaClickAudio = new Audio(CHROMA_CLICK_SOUND_URL);
      } else {
        // Reset playback so rapid clicks replay the sound from the start
        chromaClickAudio.currentTime = 0;
      }
      chromaClickAudio.play().catch((err) => {
        // Ignore playback errors (e.g. autoplay restrictions) but log for debugging
        if (window?.console) {
          console.debug("[FormsWheel] Failed to play chroma click sound:", err);
        }
      });
    } catch (err) {
      if (window?.console) {
        console.debug(
          "[FormsWheel] Error initializing chroma click sound:",
          err
        );
      }
    }
  }

  const CSS_RULES = `
    .${BUTTON_CLASS} {
      pointer-events: auto;
      -webkit-user-select: none;
      list-style-type: none;
      cursor: pointer;
      display: block !important;
      bottom: 1px;
      height: 36px;
      left: 50%;
      position: absolute;
      transform: translateX(-50%) translateY(50%);
      width: 36px;
      z-index: 1000 !important;
      background-size: contain;
      background-position: center;
      background-repeat: no-repeat;
      transition: opacity 0.2s, background-color 0.2s;
      border: none !important;
      border-radius: 0 !important;
    }

    .${BUTTON_CLASS}[data-hidden],
    .${BUTTON_CLASS}[data-hidden] * {
      pointer-events: none !important;
      cursor: default !important;
      visibility: hidden !important;
    }

    /* Hide nested ChromaWheel structure - we use custom assets directly */
    .${BUTTON_CLASS} .outer-mask,
    .${BUTTON_CLASS} .frame-color,
    .${BUTTON_CLASS} .content,
    .${BUTTON_CLASS} .inner-mask {
      display: none !important;
    }

    /* Ensure thumbnail-wrapper has relative positioning for absolute button */
    .thumbnail-wrapper.active-skin {
      position: relative;
    }

    .thumbnail-wrapper .${BUTTON_CLASS} {
      direction: ltr;
      background: transparent;
      cursor: pointer;
      height: 36px;
      width: 36px;
      /* Keep the same positioning as base button for consistency */
      bottom: 1px;
      left: 50%;
      position: absolute;
      transform: translateX(-50%) translateY(50%);
      z-index: 10;
    }

    /* Show outer-mask and content in Swiftplay so they are visible */
    .thumbnail-wrapper .${BUTTON_CLASS} .outer-mask {
      display: block !important;
    }

    .thumbnail-wrapper .${BUTTON_CLASS} .frame-color,
    .thumbnail-wrapper .${BUTTON_CLASS} .content {
      display: block !important;
    }

    /* Adjust content positioning in Swiftplay buttons */
    .thumbnail-wrapper .${BUTTON_CLASS} .content {
      transform: translate(1px, 1px);
    }

    .chroma.icon {
      display: none !important;
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

    .${PANEL_CLASS} .chroma-modal {
      background: #000;
      display: flex;
      flex-direction: column;
      width: 305px;
      position: relative;
      z-index: 0;
    }
    
    .${PANEL_CLASS} .chroma-modal.chroma-view {
      max-height: 420px;
      min-height: 355px;
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
    
    /* Target the caret/notch element to be above the border */
    .${PANEL_CLASS} .flyout .caret,
    .${PANEL_CLASS} .flyout [class*="caret"],
    .${PANEL_CLASS} lol-uikit-flyout-frame .caret,
    .${PANEL_CLASS} lol-uikit-flyout-frame [class*="caret"],
    .${PANEL_CLASS} .flyout::part(caret),
    .${PANEL_CLASS} lol-uikit-flyout-frame::part(caret) {
      z-index: 3 !important;
      position: relative;
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
      background-size: cover;
      border-bottom: thin solid #463714;
      flex-grow: 1;
      height: 315px;
      position: relative;
      width: 100%;
      z-index: 1;
    }

    .${PANEL_CLASS} .chroma-information-image {
      background-repeat: no-repeat;
      background-size: contain;
      bottom: 0;
      left: 0;
      position: absolute;
      right: 0;
      top: 0;
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
      flex-direction: row;
      flex-wrap: wrap;
      align-items: center;
      justify-content: center;
      gap: 0;
      width: 100%;
    }

    .${PANEL_CLASS} .chroma-selection li {
      list-style: none;
      margin: 2px 4px; /* Add 1px extra horizontal spacing between buttons */
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
      aspect-ratio: 1 / 1; /* Force square to keep outer circle circular under scaling */
      justify-content: center;
      margin: 0;
      padding: 0;
      cursor: pointer;
      box-sizing: border-box;
      background: transparent !important;
      background-color: transparent !important;
      flex: 0 0 26px; /* Fixed size in flex to prevent any stretching */
      transform: scale(1); /* Override any parent scaling transforms */
    }

    .${PANEL_CLASS}[data-no-button] .chroma-skin-button {
      pointer-events: none !important;
      cursor: default !important;
    }

    .${PANEL_CLASS} .chroma-skin-button:not(.locked) {
      cursor: pointer;
      opacity: 1 !important; /* Always 100% opacity for non-locked buttons */
    }

    .${PANEL_CLASS} .chroma-skin-button.locked {
      opacity: 1 !important; /* All buttons at 100% opacity, including locked */
      cursor: pointer;
      /* Keep colors visible, no opacity reduction */
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
      aspect-ratio: 1 / 1; /* Force inner circle to remain perfectly circular */
      justify-content: center;
      background: linear-gradient(135deg, #27211C 0%, #27211C 50%, #27211C 50%, #27211C 100%);
      box-shadow: 0 0 0 2px transparent; /* Reserve space for the hover ring so layout never shifts */
      opacity: 1 !important; /* All button contents at 100% opacity always */
      transform: scale(1); /* Override any parent scaling transforms */
      /* Background will be set/overridden inline based on chroma color */
    }

    /* Selected / hover state: just change ring color, thickness is constant so no squeezing */
    .${PANEL_CLASS} .chroma-skin-button.selected .contents,
    .${PANEL_CLASS} .chroma-skin-button:hover .contents {
      box-shadow: 0 0 0 2px #c89b3c;
      transform: scale(1); /* Maintain perfect circle even on hover */
    }
    
    /* All buttons at 100% opacity, no variation on hover or state */
    .${PANEL_CLASS} .chroma-skin-button.locked:hover:not([purchase-disabled]) {
      opacity: 1 !important;
    }
    
    .${PANEL_CLASS} .chroma-skin-button.locked.purchase-disabled {
      opacity: 1 !important;
      pointer-events: none;
    }
  `;

  function emitBridgeLog(event, data = {}) {
    try {
      const payload = {
        type: "chroma-log",
        source: "FormsWheel",
        event,
        data,
        timestamp: Date.now(),
      };
      if (bridge) bridge.send(payload);
    } catch (error) {
      // Can't use log here since it's not defined yet
      console.debug(`${LOG_PREFIX} Failed to emit bridge log`, error);
    }
  }


  // Track pending local preview/asset requests
  const pendingLocalPreviews = new Map(); // chromaId -> { chromaImage, chroma }
  const pendingLocalAssets = new Map(); // chromaId -> { contents, chroma }

  function handleLocalPreviewUrl(data) {
    // Handle local preview URL response from Python
    const { championId, skinId, chromaId, url } = data;
    log.debug(
      `[FormsWheel] Received local preview URL: ${url} for chroma ${chromaId}`
    );

    // Find the chroma image element that requested this preview
    const pending = pendingLocalPreviews.get(chromaId);
    if (pending && pending.chromaImage) {
      // Use the file:// URL (may not work due to browser security, but worth trying)
      // If it doesn't work, Python should serve via HTTP instead
      pending.chromaImage.style.background = "";
      pending.chromaImage.style.backgroundImage = `url('${url}')`;
      pending.chromaImage.style.backgroundSize = "contain";
      pending.chromaImage.style.backgroundPosition = "center";
      pending.chromaImage.style.backgroundRepeat = "no-repeat";
      pending.chromaImage.style.display = "";
      log.debug(`[FormsWheel] Applied local preview URL to chroma image`);
    }

    // Clean up pending request
    pendingLocalPreviews.delete(chromaId);
  }

  function handleLocalAssetUrl(data) {
    // Handle local asset URL response from Python
    let { assetPath, chromaId, url } = data;
    // Fix: Ensure we use 127.0.0.1 for asset URLs to match the bridge connection
    if (url && typeof url === 'string') {
      url = url.replace('localhost', '127.0.0.1');
    }
    log.debug(
      `[FormsWheel] Received local asset URL: ${url} for chroma ${chromaId || "N/A"
      }`
    );

    // Special handling: Hover button assets
    if (assetPath === HOVER_BUTTON_ASSET && url) {
      hoverButtonNormalUrl = url;
      log.info(`[FormsWheel] Received hover button normal asset URL: ${url}`);
      // Update all existing hover buttons directly
      const buttons = document.querySelectorAll(BUTTON_SELECTOR);
      log.info(
        `[FormsWheel] Updating ${buttons.length} existing buttons with asset URL`
      );
      buttons.forEach((btn) => {
        updateHoverButtonImage(btn);
      });
      return;
    } else if (assetPath === HOVER_BUTTON_HOVER_ASSET && url) {
      hoverButtonHoverUrl = url;
      log.info(`[FormsWheel] Received hover button hover asset URL: ${url}`);
      return;
    }

    // Special handling: ARAM background image for the panel
    if (assetPath === ARAM_BACKGROUND_ASSET_PATH && url) {
      aramBackgroundImageUrl = url;
      aramBackgroundRequestPending = false;

      if (currentChromaInfoElement) {
        currentChromaInfoElement.style.backgroundImage = `url('${url}')`;
        log.debug("[FormsWheel] Applied ARAM background image to chroma panel");
      }
    }

    // Find the button contents element that requested this asset
    const pending = pendingLocalAssets.get(chromaId);
    if (pending && pending.contents) {
      // Use the file:// URL (may not work due to browser security, but worth trying)
      // If it doesn't work, Python should serve via HTTP instead
      pending.contents.style.background = "";
      pending.contents.style.backgroundImage = `url('${url}')`;
      pending.contents.style.backgroundSize = "contain";
      pending.contents.style.backgroundPosition = "center";
      pending.contents.style.backgroundRepeat = "no-repeat";
      pending.contents.style.backgroundColor = "";

      // Mark that this chroma ID's icon has been applied
      pending.contents.setAttribute("data-last-chroma-id", String(chromaId));

      log.debug(
        `[FormsWheel] Applied local asset URL to button icon for chroma ${chromaId}`
      );
    }

    // Clean up pending request
    pendingLocalAssets.delete(chromaId);
  }

  function handleChromaStateUpdate(data) {
    // Update Python chroma state
    pythonChromaState = {
      selectedChromaId: data.selectedChromaId,
      chromaColor: data.chromaColor,
      chromaColors: data.chromaColors,
      currentSkinId: data.currentSkinId,
    };

    log.info(
      `[FormsWheel] Received chroma state from Python: selectedChromaId=${data.selectedChromaId}, chromaColor=${data.chromaColor}`
    );

    // Check if this is an Elementalist Lux form (ID 99991-99999 or base 99007)
    const isElementalistLux = (id) => {
      return id === 99007 || (id >= 99991 && id <= 99999);
    };

    // Check if this is a Sahn Uzal Mordekaiser form (IDs 82998, 82999 or base 82054)
    const isMordekaiser = (id) => {
      return id === 82054 || id === 82998 || id === 82999;
    };

    // Check if this is a Spirit Blossom Morgana form (ID 25999 or base 25080)
    const isMorgana = (id) => {
      return id === 25080 || id === 25999;
    };

    // Check if this is a HOL chroma (Kai'Sa or Ahri)
    const isHolChroma = (id) => {
      // Kaisa (145070, 145071, 145999) now uses forms, so only check Ahri HOL IDs
      return id === 103085 || id === 103086 || id === 103087;
    };

    // Helper to get buttonIconPath for Elementalist Lux forms
    const getButtonIconPathForElementalist = (chromaId) => {
      if (isElementalistLux(chromaId)) {
        return getElementalistButtonIconPath(chromaId);
      }
      return null;
    };

    // Helper to get buttonIconPath for Sahn Uzal Mordekaiser forms
    const getButtonIconPathForMordekaiser = (chromaId) => {
      if (isMordekaiser(chromaId)) {
        return getMordekaiserButtonIconPath(chromaId);
      }
      return null;
    };

    // Helper to get buttonIconPath for Spirit Blossom Morgana forms
    const getButtonIconPathForMorgana = (chromaId) => {
      if (isMorgana(chromaId)) {
        return getMorganaButtonIconPath(chromaId);
      }
      return null;
    };

    // Helper to get buttonIconPath for Radiant Sett forms
    const getButtonIconPathForSett = (chromaId) => {
      if (isSett(chromaId)) {
        return getSettButtonIconPath(chromaId);
      }
      return null;
    };

    // Helper to get buttonIconPath for KDA Seraphine forms
    const getButtonIconPathForSeraphine = (chromaId) => {
      if (isSeraphine(chromaId)) {
        return getSeraphineButtonIconPath(chromaId);
      }
      return null;
    };

    // Helper to get buttonIconPath for DJ Sona forms
    const getButtonIconPathForSona = (chromaId) => {
      if (isSona(chromaId)) {
        return getSonaButtonIconPath(chromaId);
      }
      return null;
    };

    // Helper to get buttonIconPath for Arcane Fractured Jinx forms
    const getButtonIconPathForJinx = (chromaId) => {
      if (isJinx(chromaId)) {
        return getJinxButtonIconPath(chromaId);
      }
      return null;
    };

    // Helper to get buttonIconPath for Uzi Kaisa forms
    const getButtonIconPathForKaisa = (chromaId) => {
      if (isKaisa(chromaId)) {
        return getKaisaButtonIconPath(chromaId);
      }
      return null;
    };

    // Helper to get buttonIconPath for Viego forms
    const getButtonIconPathForViego = (chromaId) => {
      if (isViego(chromaId)) {
        return getViegoButtonIconPath(chromaId);
      }
      return null;
    };

    // Helper to get buttonIconPath for HOL chromas (Ahri only - Kaisa now uses forms)
    const getButtonIconPathForHol = (chromaId) => {
      if (isHolChroma(chromaId)) {
        // Determine base skin ID and champion ID (Ahri only)
        let baseSkinId;
        let championId;

        if (chromaId === 103085 || chromaId === 103086 || chromaId === 103087) {
          // Ahri HOL
          baseSkinId = 103085;
          championId = 103;
        } else {
          return null;
        }

        return getHolButtonIconPath(championId, chromaId, baseSkinId);
      }
      return null;
    };

    // Update selectedChromaData based on Python state
    if (data.selectedChromaId && data.chromaColor) {
      // Python provided the color directly
      const buttonIconPath =
        getButtonIconPathForElementalist(data.selectedChromaId) ||
        getButtonIconPathForMordekaiser(data.selectedChromaId) ||
        getButtonIconPathForMorgana(data.selectedChromaId) ||
        getButtonIconPathForSett(data.selectedChromaId) ||
        getButtonIconPathForSeraphine(data.selectedChromaId) ||
        getButtonIconPathForSona(data.selectedChromaId) ||
        getButtonIconPathForJinx(data.selectedChromaId) ||
        getButtonIconPathForKaisa(data.selectedChromaId) ||
        getButtonIconPathForViego(data.selectedChromaId) ||
        getButtonIconPathForHol(data.selectedChromaId) ||
        (selectedChromaData && selectedChromaData.id === data.selectedChromaId
          ? selectedChromaData.buttonIconPath
          : null);
      selectedChromaData = {
        id: data.selectedChromaId,
        primaryColor: data.chromaColor,
        colors: data.chromaColors || [data.chromaColor],
        name: "Selected", // Name will be updated when panel opens
        buttonIconPath: buttonIconPath,
      };
    } else if (data.selectedChromaId) {
      // Python provided selectedChromaId but no color - try to find it from cache
      let foundChroma = null;

      // Get base skin ID - check if currentSkinId is a chroma ID first
      // Also check if baseSkinId was provided in the payload (from selectChroma)
      let baseSkinId =
        data.baseSkinId || data.currentSkinId || skinMonitorState?.skinId;

      // If currentSkinId is a chroma ID, get the base skin ID from chromaParentMap
      if (baseSkinId && chromaParentMap.has(baseSkinId)) {
        baseSkinId = chromaParentMap.get(baseSkinId);
        log.debug(
          `[FormsWheel] Found base skin ID ${baseSkinId} for chroma ${data.currentSkinId} from chromaParentMap`
        );
      }

      // Also check if selectedChromaId itself is in the map (in case currentSkinId wasn't set correctly)
      if (!baseSkinId && chromaParentMap.has(data.selectedChromaId)) {
        baseSkinId = chromaParentMap.get(data.selectedChromaId);
        log.debug(
          `[FormsWheel] Found base skin ID ${baseSkinId} for selected chroma ${data.selectedChromaId} from chromaParentMap`
        );
      }

      // Check if this is Elementalist Lux - if so, use local data
      if (isElementalistLux(data.selectedChromaId)) {
        // Elementalist Lux form - get data from local functions
        const baseFormId = 99007;
        const luxChampionId = 99;

        // Check if it's the base form or a form
        if (data.selectedChromaId === baseFormId) {
          // Base form
          selectedChromaData = {
            id: data.selectedChromaId,
            primaryColor: null,
            colors: [],
            name: "Default",
            buttonIconPath: getElementalistButtonIconPath(baseFormId),
          };
        } else {
          // Elementalist Lux form (99991-99999)
          const forms = getElementalistForms();
          const form = forms.find((f) => f.id === data.selectedChromaId);
          if (form) {
            selectedChromaData = {
              id: data.selectedChromaId,
              primaryColor: null,
              colors: [],
              name: form.name || "Selected",
              buttonIconPath: getElementalistButtonIconPath(form.id),
            };
          } else {
            // Form not found - use button icon path anyway
            selectedChromaData = {
              id: data.selectedChromaId,
              primaryColor: null,
              colors: [],
              name: "Selected",
              buttonIconPath: getElementalistButtonIconPath(
                data.selectedChromaId
              ),
            };
          }
        }
        log.debug(
          `[FormsWheel] Elementalist Lux form detected: ${data.selectedChromaId}, buttonIconPath: ${selectedChromaData.buttonIconPath}`
        );
        // Note: Mordekaiser handling removed - now handled by ROSE-FormsWheel plugin
      } else if (isMorgana(data.selectedChromaId)) {
        // Spirit Blossom Morgana form - get data from local functions
        const baseFormId = 25080;
        const morganaChampionId = 25;

        // Check if it's the base form or a form
        if (data.selectedChromaId === baseFormId) {
          // Base form
          selectedChromaData = {
            id: data.selectedChromaId,
            primaryColor: null,
            colors: [],
            name: "Default",
            buttonIconPath: getMorganaButtonIconPath(baseFormId),
          };
        } else {
          // Spirit Blossom Morgana form (25999)
          const forms = getMorganaForms();
          const form = forms.find((f) => f.id === data.selectedChromaId);
          if (form) {
            selectedChromaData = {
              id: data.selectedChromaId,
              primaryColor: null,
              colors: [],
              name: form.name || "Selected",
              buttonIconPath: getMorganaButtonIconPath(form.id),
            };
          } else {
            // Form not found - use button icon path anyway
            selectedChromaData = {
              id: data.selectedChromaId,
              primaryColor: null,
              colors: [],
              name: "Selected",
              buttonIconPath: getMorganaButtonIconPath(data.selectedChromaId),
            };
          }
        }
        log.debug(
          `[FormsWheel] Spirit Blossom Morgana form detected: ${data.selectedChromaId}, buttonIconPath: ${selectedChromaData.buttonIconPath}`
        );
      } else if (isSett(data.selectedChromaId)) {
        // Radiant Sett form - get data from local functions
        const baseFormId = 875066;
        const settChampionId = 875;

        // Check if it's the base form or a form
        if (data.selectedChromaId === baseFormId) {
          // Base form
          selectedChromaData = {
            id: data.selectedChromaId,
            primaryColor: null,
            colors: [],
            name: "Default",
            buttonIconPath: getSettButtonIconPath(baseFormId),
          };
        } else {
          // Radiant Sett form (875998, 875999)
          const forms = getSettForms();
          const form = forms.find((f) => f.id === data.selectedChromaId);
          if (form) {
            selectedChromaData = {
              id: data.selectedChromaId,
              primaryColor: null,
              colors: [],
              name: form.name || "Selected",
              buttonIconPath: getSettButtonIconPath(form.id),
            };
          } else {
            // Form not found - use button icon path anyway
            selectedChromaData = {
              id: data.selectedChromaId,
              primaryColor: null,
              colors: [],
              name: "Selected",
              buttonIconPath: getSettButtonIconPath(data.selectedChromaId),
            };
          }
        }
        log.debug(
          `[FormsWheel] Radiant Sett form detected: ${data.selectedChromaId}, buttonIconPath: ${selectedChromaData.buttonIconPath}`
        );
      } else if (isSeraphine(data.selectedChromaId)) {
        // KDA Seraphine form - get data from local functions
        const baseFormId = 147001;
        const seraphineChampionId = 147;

        // Check if it's the base form or a form
        if (data.selectedChromaId === baseFormId) {
          // Base form
          selectedChromaData = {
            id: data.selectedChromaId,
            primaryColor: null,
            colors: [],
            name: "Default",
            buttonIconPath: getSeraphineButtonIconPath(baseFormId),
          };
        } else {
          // KDA Seraphine form (147002, 147003)
          const forms = getSeraphineForms();
          const form = forms.find((f) => f.id === data.selectedChromaId);
          if (form) {
            selectedChromaData = {
              id: data.selectedChromaId,
              primaryColor: null,
              colors: [],
              name: form.name || "Selected",
              buttonIconPath: getSeraphineButtonIconPath(form.id),
            };
          } else {
            // Form not found - use button icon path anyway
            selectedChromaData = {
              id: data.selectedChromaId,
              primaryColor: null,
              colors: [],
              name: "Selected",
              buttonIconPath: getSeraphineButtonIconPath(data.selectedChromaId),
            };
          }
        }
        log.debug(
          `[FormsWheel] KDA Seraphine form detected: ${data.selectedChromaId}, buttonIconPath: ${selectedChromaData.buttonIconPath}`
        );
      } else if (isSona(data.selectedChromaId)) {
        // DJ Sona form - get data from local functions
        const baseFormId = 37006;
        const sonaChampionId = 37;

        // Check if it's the base form or a form
        if (data.selectedChromaId === baseFormId) {
          // Base form
          selectedChromaData = {
            id: data.selectedChromaId,
            primaryColor: null,
            colors: [],
            name: "Default",
            buttonIconPath: getSonaButtonIconPath(baseFormId),
          };
        } else {
          // DJ Sona form (37998, 37999)
          const forms = getSonaForms();
          const form = forms.find((f) => f.id === data.selectedChromaId);
          if (form) {
            selectedChromaData = {
              id: data.selectedChromaId,
              primaryColor: null,
              colors: [],
              name: form.name || "Selected",
              buttonIconPath: getSonaButtonIconPath(form.id),
            };
          } else {
            // Form not found - use button icon path anyway
            selectedChromaData = {
              id: data.selectedChromaId,
              primaryColor: null,
              colors: [],
              name: "Selected",
              buttonIconPath: getSonaButtonIconPath(data.selectedChromaId),
            };
          }
        }
        log.debug(
          `[FormsWheel] DJ Sona form detected: ${data.selectedChromaId}, buttonIconPath: ${selectedChromaData.buttonIconPath}`
        );
      } else if (isJinx(data.selectedChromaId)) {
        // Arcane Fractured Jinx form - get data from local functions
        const baseFormId = 222060;
        const jinxChampionId = 222;

        // Check if it's the base form or a form
        if (data.selectedChromaId === baseFormId) {
          // Base form
          selectedChromaData = {
            id: data.selectedChromaId,
            primaryColor: null,
            colors: [],
            name: "Default",
            buttonIconPath: getJinxButtonIconPath(baseFormId),
          };
        } else {
          // Arcane Fractured Jinx form (222998, 222999)
          const forms = getJinxForms();
          const form = forms.find((f) => f.id === data.selectedChromaId);
          if (form) {
            selectedChromaData = {
              id: data.selectedChromaId,
              primaryColor: null,
              colors: [],
              name: form.name || "Selected",
              buttonIconPath: getJinxButtonIconPath(form.id),
            };
          } else {
            // Form not found - use button icon path anyway
            selectedChromaData = {
              id: data.selectedChromaId,
              primaryColor: null,
              colors: [],
              name: "Selected",
              buttonIconPath: getJinxButtonIconPath(data.selectedChromaId),
            };
          }
        }
        log.debug(
          `[FormsWheel] Arcane Fractured Jinx form detected: ${data.selectedChromaId}, buttonIconPath: ${selectedChromaData.buttonIconPath}`
        );
      } else if (isKaisa(data.selectedChromaId)) {
        // Uzi Kaisa form - get data from local functions
        const baseFormId = 145070;
        const kaisaChampionId = 145;

        // Check if it's the base form or a form
        if (data.selectedChromaId === baseFormId) {
          // Base form
          selectedChromaData = {
            id: data.selectedChromaId,
            primaryColor: null,
            colors: [],
            name: "Default",
            buttonIconPath: getKaisaButtonIconPath(baseFormId),
          };
        } else {
          // Uzi Kaisa form (145071, 145999)
          const forms = getKaisaForms();
          const form = forms.find((f) => f.id === data.selectedChromaId);
          if (form) {
            selectedChromaData = {
              id: data.selectedChromaId,
              primaryColor: null,
              colors: [],
              name: form.name || "Selected",
              buttonIconPath: getKaisaButtonIconPath(form.id),
            };
          } else {
            // Form not found - use button icon path anyway
            selectedChromaData = {
              id: data.selectedChromaId,
              primaryColor: null,
              colors: [],
              name: "Selected",
              buttonIconPath: getKaisaButtonIconPath(data.selectedChromaId),
            };
          }
        }
        log.debug(
          `[FormsWheel] Uzi Kaisa form detected: ${data.selectedChromaId}, buttonIconPath: ${selectedChromaData.buttonIconPath}`
        );
      } else if (isViego(data.selectedChromaId)) {
        // Viego form - get data from local functions
        const baseFormId = 234043;
        const viegoChampionId = 234;

        // Check if it's the base form or a form
        if (data.selectedChromaId === baseFormId) {
          // Base form
          selectedChromaData = {
            id: data.selectedChromaId,
            primaryColor: null,
            colors: [],
            name: "Default",
            buttonIconPath: getViegoButtonIconPath(baseFormId),
          };
        } else {
          // Viego form (234994-234999)
          const forms = getViegoForms();
          const form = forms.find((f) => f.id === data.selectedChromaId);
          if (form) {
            selectedChromaData = {
              id: data.selectedChromaId,
              primaryColor: null,
              colors: [],
              name: form.name || "Selected",
              buttonIconPath: getViegoButtonIconPath(form.id),
            };
          } else {
            // Form not found - use button icon path anyway
            selectedChromaData = {
              id: data.selectedChromaId,
              primaryColor: null,
              colors: [],
              name: "Selected",
              buttonIconPath: getViegoButtonIconPath(data.selectedChromaId),
            };
          }
        }
        log.debug(
          `[FormsWheel] Viego form detected: ${data.selectedChromaId}, buttonIconPath: ${selectedChromaData.buttonIconPath}`
        );
      } else if (isHolChroma(data.selectedChromaId)) {
        // HOL chroma - get data from local functions (Ahri only - Kaisa now uses forms)
        let baseSkinId;
        let championId;

        if (
          data.selectedChromaId === 103085 ||
          data.selectedChromaId === 103086 ||
          data.selectedChromaId === 103087
        ) {
          // Ahri HOL
          baseSkinId = 103085;
          championId = 103;
        } else {
          // Not a known HOL chroma
          return;
        }

        // Check if it's the base skin or HOL chroma
        if (data.selectedChromaId === baseSkinId) {
          // Base skin
          selectedChromaData = {
            id: data.selectedChromaId,
            primaryColor: null,
            colors: [],
            name: "Default",
            buttonIconPath: getHolButtonIconPath(
              championId,
              baseSkinId,
              baseSkinId
            ),
          };
        } else {
          // HOL chroma
          const holChromas = getAhriHolChromas();
          const holChroma = holChromas.find(
            (c) => c.id === data.selectedChromaId
          );
          if (holChroma) {
            selectedChromaData = {
              id: data.selectedChromaId,
              primaryColor: null,
              colors: [],
              name: holChroma.name || "Selected",
              buttonIconPath: getHolButtonIconPath(
                championId,
                data.selectedChromaId,
                baseSkinId
              ),
            };
          } else {
            // HOL chroma not found - use button icon path anyway
            selectedChromaData = {
              id: data.selectedChromaId,
              primaryColor: null,
              colors: [],
              name: "Selected",
              buttonIconPath: getHolButtonIconPath(
                championId,
                data.selectedChromaId,
                baseSkinId
              ),
            };
          }
        }
        log.debug(
          `[FormsWheel] HOL chroma detected: ${data.selectedChromaId}, buttonIconPath: ${selectedChromaData.buttonIconPath}`
        );
      } else {
        // Regular chroma - try to find from cache
        // Fallback: try to infer base skin ID from chroma ID (chroma IDs are typically baseSkinId + offset)
        if (!baseSkinId && Number.isFinite(data.selectedChromaId)) {
          // Try to find base skin by checking if any cached skin has this chroma
          // Or use the base skin ID from skinMonitorState if available
          baseSkinId = skinMonitorState?.skinId;
          // If skinMonitorState.skinId is also a chroma, try to get base from it
          if (baseSkinId && chromaParentMap.has(baseSkinId)) {
            baseSkinId = chromaParentMap.get(baseSkinId);
          }
        }

        if (baseSkinId) {
          const cachedChromas = getCachedChromasForSkin(baseSkinId);
          foundChroma = cachedChromas.find(
            (c) => c.id === data.selectedChromaId
          );
          log.debug(
            `[FormsWheel] Looking for chroma ${data.selectedChromaId
            } in base skin ${baseSkinId}, found: ${foundChroma ? "yes" : "no"}`
          );
        }

        if (foundChroma && foundChroma.primaryColor) {
          // Preserve buttonIconPath if it exists in foundChroma or in existing selectedChromaData
          const buttonIconPath =
            foundChroma.buttonIconPath ||
            (selectedChromaData &&
              selectedChromaData.id === data.selectedChromaId
              ? selectedChromaData.buttonIconPath
              : null);
          selectedChromaData = {
            id: data.selectedChromaId,
            primaryColor: foundChroma.primaryColor,
            colors: foundChroma.colors || [foundChroma.primaryColor],
            name: foundChroma.name || "Selected",
            buttonIconPath: buttonIconPath,
          };
          log.debug(
            `[FormsWheel] Found chroma color from cache: ${foundChroma.primaryColor}`
          );
        } else {
          // Chroma selected but no color available - try to keep existing selectedChromaData if it matches
          if (
            selectedChromaData &&
            selectedChromaData.id === data.selectedChromaId
          ) {
            log.debug(
              `[FormsWheel] Keeping existing selectedChromaData for chroma ${data.selectedChromaId}`
            );
            // Keep the existing data, just update the ID to be sure
            selectedChromaData.id = data.selectedChromaId;
            // Preserve buttonIconPath if it exists
            if (!selectedChromaData.buttonIconPath) {
              selectedChromaData.buttonIconPath = null;
            }
          } else {
            // No existing data or it doesn't match - treat as default
            selectedChromaData = {
              id: data.selectedChromaId,
              primaryColor: null,
              colors: [],
              name: "Default",
              buttonIconPath: null,
            };
            log.debug(
              `[FormsWheel] Could not find chroma color for ${data.selectedChromaId}, using default`
            );
          }
        }
      }
    } else {
      // Default/base chroma selected
      // Check if currentSkinId is Elementalist Lux base, Sahn Uzal Mordekaiser base, Spirit Blossom Morgana base, or HOL base
      let buttonIconPath = null;
      if (isElementalistLux(data.currentSkinId)) {
        buttonIconPath = getElementalistButtonIconPath(data.currentSkinId);
        // Note: Mordekaiser handling removed - now handled by ROSE-FormsWheel plugin
      } else if (isMorgana(data.currentSkinId)) {
        buttonIconPath = getMorganaButtonIconPath(data.currentSkinId);
      } else if (isSett(data.currentSkinId)) {
        buttonIconPath = getSettButtonIconPath(data.currentSkinId);
      } else if (isSeraphine(data.currentSkinId)) {
        buttonIconPath = getSeraphineButtonIconPath(data.currentSkinId);
      } else if (isSona(data.currentSkinId)) {
        buttonIconPath = getSonaButtonIconPath(data.currentSkinId);
      } else if (isJinx(data.currentSkinId)) {
        buttonIconPath = getJinxButtonIconPath(data.currentSkinId);
      } else if (isKaisa(data.currentSkinId)) {
        buttonIconPath = getKaisaButtonIconPath(data.currentSkinId);
      } else if (isViego(data.currentSkinId)) {
        buttonIconPath = getViegoButtonIconPath(data.currentSkinId);
      } else if (isHolChroma(data.currentSkinId)) {
        // Determine base skin ID and champion ID for HOL (Ahri only - Kaisa now uses forms)
        let baseSkinId;
        let championId;

        if (
          data.currentSkinId === 103085 ||
          data.currentSkinId === 103086 ||
          data.currentSkinId === 103087
        ) {
          baseSkinId = 103085;
          championId = 103;
        }

        if (baseSkinId && championId) {
          buttonIconPath = getHolButtonIconPath(
            championId,
            data.currentSkinId,
            baseSkinId
          );
        }
      }

      selectedChromaData = {
        id: data.currentSkinId || null,
        primaryColor: null,
        colors: [],
        name: "Default",
        buttonIconPath: buttonIconPath,
      };
    }

    // Update button color
    updateChromaButtonColor();
  }

  function handlePhaseChangeFromPython(data) {
    // Use Python-detected game mode to drive ARAM detection for the JS panel
    try {
      const phase = data.phase;
      const gameMode = data.gameMode;
      const mapId = data.mapId;

      if (phase === "ChampSelect" || phase === "FINALIZATION") {
        const isAram =
          mapId === 12 ||
          (typeof gameMode === "string" && gameMode.toUpperCase() === "ARAM");

        isAramFromPython = Boolean(isAram);
      } else {
        // Leaving champ select / finalization â€“ clear flag
        isAramFromPython = false;
      }
    } catch (e) {
      // Fail silently â€“ fallback to Ember-based detection
    }
  }

  function requestAramBackgroundImage() {
    // Request ARAM panel background image from Python when in ARAM game modes
    if (aramBackgroundImageUrl || aramBackgroundRequestPending) {
      return;
    }

    aramBackgroundRequestPending = true;

    const payload = {
      type: "request-local-asset",
      assetPath: ARAM_BACKGROUND_ASSET_PATH,
      timestamp: Date.now(),
    };

    log.debug("[FormsWheel] Requesting ARAM background image from Python", {
      assetPath: ARAM_BACKGROUND_ASSET_PATH,
    });

    if (bridge) {
      bridge.send(payload);
    } else {
      aramBackgroundRequestPending = false;
    }
  }

  const log = {
    info: (msg, extra) => {
      console.log(`${LOG_PREFIX} ${msg}`, extra ?? "");
      emitBridgeLog("info", { message: msg, data: extra });
    },
    warn: (msg, extra) => {
      console.warn(`${LOG_PREFIX} ${msg}`, extra ?? "");
      emitBridgeLog("warn", { message: msg, data: extra });
    },
    debug: (msg, extra) => {
      console.debug(`${LOG_PREFIX} ${msg}`, extra ?? "");
      emitBridgeLog("debug", { message: msg, data: extra });
    },
  };

  function getNumericId(value) {
    if (typeof value === "number" && Number.isFinite(value)) {
      return value;
    }
    if (typeof value === "string" && value.trim() !== "") {
      const parsed = parseInt(value, 10);
      if (!Number.isNaN(parsed)) {
        return parsed;
      }
    }
    return null;
  }

  function extractSkinIdFromData(skinData) {
    if (!skinData || typeof skinData !== "object") {
      return null;
    }
    const candidates = [
      skinData.skinId,
      skinData.id,
      skinData.skin?.skinId,
      skinData.skin?.id,
      skinData.championSkinId,
      skinData.parentSkinId,
    ];
    for (const candidate of candidates) {
      const numeric = getNumericId(candidate);
      if (numeric !== null) {
        return numeric;
      }
    }
    return null;
  }

  function extractSkinIdFromElement(element) {
    if (!element) {
      return null;
    }
    const direct = element.getAttribute?.("data-skin-id");
    if (direct) {
      return getNumericId(direct);
    }
    const nested = element
      .querySelector?.("[data-skin-id]")
      ?.getAttribute("data-skin-id");
    if (nested) {
      return getNumericId(nested);
    }
    return null;
  }

  function getSkinIdFromContext(skinData, element) {
    return extractSkinIdFromData(skinData) ?? extractSkinIdFromElement(element);
  }

  function getChampionIdFromContext(skinData, skinId, element) {
    if (skinData && Number.isFinite(skinData.championId)) {
      return skinData.championId;
    }

    if (element?.dataset?.championId) {
      const attrId = getNumericId(element.dataset.championId);
      if (Number.isFinite(attrId)) {
        return attrId;
      }
    }

    const championElement = element?.closest?.("[data-champion-id]");
    if (championElement) {
      const attrId = getNumericId(
        championElement.getAttribute("data-champion-id")
      );
      if (Number.isFinite(attrId)) {
        return attrId;
      }
    }

    if (Number.isFinite(skinId)) {
      const mappedChampion = skinToChampionMap.get(skinId);
      if (Number.isFinite(mappedChampion)) {
        return mappedChampion;
      }

      const inferred = Math.floor(skinId / 1000);
      if (Number.isFinite(inferred) && inferred > 0) {
        return inferred;
      }
    }

    return null;
  }

  function isElementalistFormSkinId(skinId) {
    return Number.isFinite(skinId) && skinId >= 99991 && skinId <= 99999;
  }

  // Get Elementalist Lux Forms data locally (same as Python's _get_elementalist_forms)
  function getElementalistForms() {
    const forms = [
      {
        id: 99991,
        name: "Air",
        colors: [],
        form_path: "Lux/Forms/Lux Elementalist Air.zip",
      },
      {
        id: 99992,
        name: "Dark",
        colors: [],
        form_path: "Lux/Forms/Lux Elementalist Dark.zip",
      },
      {
        id: 99993,
        name: "Ice",
        colors: [],
        form_path: "Lux/Forms/Lux Elementalist Ice.zip",
      },
      {
        id: 99994,
        name: "Magma",
        colors: [],
        form_path: "Lux/Forms/Lux Elementalist Magma.zip",
      },
      {
        id: 99995,
        name: "Mystic",
        colors: [],
        form_path: "Lux/Forms/Lux Elementalist Mystic.zip",
      },
      {
        id: 99996,
        name: "Nature",
        colors: [],
        form_path: "Lux/Forms/Lux Elementalist Nature.zip",
      },
      {
        id: 99997,
        name: "Storm",
        colors: [],
        form_path: "Lux/Forms/Lux Elementalist Storm.zip",
      },
      {
        id: 99998,
        name: "Water",
        colors: [],
        form_path: "Lux/Forms/Lux Elementalist Water.zip",
      },
      {
        id: 99999,
        name: "Fire",
        colors: [],
        form_path: "Lux/Forms/Elementalist Lux Fire.zip",
      },
    ];
    log.debug(
      `[getElementalistForms] Created ${forms.length} Elementalist Lux Forms with fake IDs (99991-99999)`
    );
    return forms;
  }

  // Get Uzi Kaisa Forms data locally
  function getKaisaForms() {
    const forms = [
      {
        id: 145071,
        name: "Form 1",
        colors: [],
        form_path: "Kaisa/Forms/Uzi Kaisa Form 1.zip",
      },
      {
        id: 145999,
        name: "Form 2",
        colors: [],
        form_path: "Kaisa/Forms/Uzi Kaisa Form 2.zip",
      },
    ];
    log.debug(
      `[getKaisaForms] Created ${forms.length} Uzi Kaisa Forms with real IDs (145071, 145999)`
    );
    return forms;
  }

  // Get Viego Forms data locally
  function getViegoForms() {
    const forms = [
      {
        id: 234994,
        name: "Form 2",
        colors: [],
        form_path: "Viego/Forms/Viego Form 2.zip",
      },
      {
        id: 234995,
        name: "Form 3",
        colors: [],
        form_path: "Viego/Forms/Viego Form 3.zip",
      },
      {
        id: 234996,
        name: "Form 4",
        colors: [],
        form_path: "Viego/Forms/Viego Form 4.zip",
      },
      {
        id: 234997,
        name: "Form 5",
        colors: [],
        form_path: "Viego/Forms/Viego Form 5.zip",
      },
      {
        id: 234998,
        name: "Form 6",
        colors: [],
        form_path: "Viego/Forms/Viego Form 6.zip",
      },
      {
        id: 234999,
        name: "Form 7",
        colors: [],
        form_path: "Viego/Forms/Viego Form 7.zip",
      },
    ];
    log.debug(
      `[getViegoForms] Created ${forms.length} Viego Forms with real IDs (234994-234999)`
    );
    return forms;
  }

  // Get Risen Legend Ahri HOL chroma data locally (same as Python's _get_ahri_hol_chromas)
  function getAhriHolChromas() {
    const chromas = [
      { id: 103086, skinId: 103085, name: "Immortalized Legend", colors: [] },
      { id: 103087, skinId: 103085, name: "Form 2", colors: [] },
    ];
    log.debug(
      `[getAhriHolChromas] Created ${chromas.length} Risen Legend Ahri HOL chromas with real skin IDs (103086, 103087)`
    );
    return chromas;
  }

  // Get Sahn Uzal Mordekaiser Forms data locally (same as Python's get_mordekaiser_forms)
  function getMordekaiserForms() {
    const forms = [
      {
        id: 82998,
        name: "Form 1",
        colors: [],
        form_path: "Mordekaiser/Forms/Sahn Uzal Mordekaiser Form 1.zip",
      },
      {
        id: 82999,
        name: "Form 2",
        colors: [],
        form_path: "Mordekaiser/Forms/Sahn Uzal Mordekaiser Form 2.zip",
      },
    ];
    log.debug(
      `[getMordekaiserForms] Created ${forms.length} Sahn Uzal Mordekaiser Forms with real IDs (82998, 82999)`
    );
    return forms;
  }

  // Get Spirit Blossom Morgana Forms data locally (same as Python's get_morgana_forms)
  function getMorganaForms() {
    const forms = [
      {
        id: 25999,
        name: "Form 1",
        colors: [],
        form_path: "Morgana/Forms/Spirit Blossom Morgana Form 1.zip",
      },
    ];
    log.debug(
      `[getMorganaForms] Created ${forms.length} Spirit Blossom Morgana Forms with real ID (25999)`
    );
    return forms;
  }

  // Get Radiant Sett Forms data locally (same as Python's get_sett_forms)
  function getSettForms() {
    const forms = [
      {
        id: 875998,
        name: "Form 2",
        colors: [],
        form_path: "Sett/Forms/Radiant Sett Form 2.zip",
      },
      {
        id: 875999,
        name: "Form 3",
        colors: [],
        form_path: "Sett/Forms/Radiant Sett Form 3.zip",
      },
    ];
    log.debug(
      `[getSettForms] Created ${forms.length} Radiant Sett Forms with real IDs (875998, 875999)`
    );
    return forms;
  }

  // Get KDA Seraphine Forms data locally (same as Python's get_seraphine_forms)
  function getSeraphineForms() {
    const forms = [
      {
        id: 147002,
        name: "Form 1",
        colors: [],
        form_path: "Seraphine/Forms/KDA Seraphine Form 1.zip",
      },
      {
        id: 147003,
        name: "Form 2",
        colors: [],
        form_path: "Seraphine/Forms/KDA Seraphine Form 2.zip",
      },
    ];
    log.debug(
      `[getSeraphineForms] Created ${forms.length} KDA Seraphine Forms with real IDs (147002, 147003)`
    );
    return forms;
  }

  // Get DJ Sona Forms data locally
  function getSonaForms() {
    const forms = [
      {
        id: 37998,
        name: "Form 1",
        colors: [],
        form_path: "Sona/Forms/DJ Sona Form 1.zip",
      },
      {
        id: 37999,
        name: "Form 2",
        colors: [],
        form_path: "Sona/Forms/DJ Sona Form 2.zip",
      },
    ];
    log.debug(
      `[getSonaForms] Created ${forms.length} DJ Sona Forms with real IDs (37998, 37999)`
    );
    return forms;
  }

  // Get Arcane Fractured Jinx Forms data locally
  function getJinxForms() {
    const forms = [
      {
        id: 222998,
        name: "Form 1",
        colors: [],
        form_path: "Jinx/Forms/Arcane Fractured Jinx Form 1.zip",
      },
      {
        id: 222999,
        name: "Form 2",
        colors: [],
        form_path: "Jinx/Forms/Arcane Fractured Jinx Form 2.zip",
      },
    ];
    log.debug(
      `[getJinxForms] Created ${forms.length} Arcane Fractured Jinx Forms with real IDs (222998, 222999)`
    );
    return forms;
  }

  // Get local preview image path for special skins (like Python's ChromaPreviewManager)
  // Path structure: {champion_id}/{skin_id}/{chroma_id}/{chroma_id}.png
  // For base skin: {champion_id}/{skin_id}/{skin_id}.png
  function getLocalPreviewPath(championId, skinId, chromaId, isBase = false) {
    if (!Number.isFinite(championId) || !Number.isFinite(skinId)) {
      return null;
    }

    // Request preview path from Python via bridge
    // Python will return the local file path or serve it via HTTP
    // For now, construct the expected path structure
    // Note: JavaScript can't access local files directly, so we'll need Python to serve these
    const previewId = isBase ? skinId : chromaId;
    const path = `local-preview://${championId}/${skinId}/${previewId}/${previewId}.png`;
    return path;
  }

  // Get local button icon path for Elementalist Lux forms
  // Path: assets/elementalist_buttons/{form_id}.png
  function getElementalistButtonIconPath(formId) {
    // Request icon path from Python via bridge
    // Python will return the local file path or serve it via HTTP
    // For now, construct the expected path structure
    const path = `local-asset://elementalist_buttons/${formId}.png`;
    return path;
  }

  // Get local button icon path for Sahn Uzal Mordekaiser forms
  // Path: assets/mordekaiser_buttons/{form_id}.png
  function getMordekaiserButtonIconPath(formId) {
    // Request icon path from Python via bridge
    // Python will return the local file path or serve it via HTTP
    // For now, construct the expected path structure
    const path = `local-asset://mordekaiser_buttons/${formId}.png`;
    return path;
  }

  // Get local button icon path for Spirit Blossom Morgana forms
  // Path: assets/sbmorg_buttons/{button_number}.png
  // Maps: 25080 (base) -> 1.png, 25999 (form) -> 2.png
  function getMorganaButtonIconPath(formId) {
    // Request icon path from Python via bridge
    // Python will return the local file path or serve it via HTTP
    // Map form IDs to button numbers
    let buttonNumber;
    if (formId === 25080) {
      buttonNumber = 1; // Base skin
    } else if (formId === 25999) {
      buttonNumber = 2; // Form 1
    } else {
      // Fallback to form ID if unknown
      buttonNumber = formId;
    }
    const path = `local-asset://sbmorg_buttons/${buttonNumber}.png`;
    return path;
  }

  // Get local button icon path for Radiant Sett forms
  // Path: assets/radiantsett_buttons/{button_number}.png
  // Maps: 875066 (base) -> 1.png, 875998 (form 2) -> 2.png, 875999 (form 3) -> 3.png
  function getSettButtonIconPath(formId) {
    // Request icon path from Python via bridge
    // Python will return the local file path or serve it via HTTP
    // Map form IDs to button numbers
    let buttonNumber;
    if (formId === 875066) {
      buttonNumber = 1; // Base skin
    } else if (formId === 875998) {
      buttonNumber = 2; // Form 2
    } else if (formId === 875999) {
      buttonNumber = 3; // Form 3
    } else {
      // Fallback to form ID if unknown
      buttonNumber = formId;
    }
    const path = `local-asset://radiantsett_buttons/${buttonNumber}.png`;
    return path;
  }

  // Get local button icon path for KDA Seraphine forms
  // Path: assets/kdasera_buttons/{button_number}.png
  // Maps: 147001 (base) -> 1.png, 147002 (form 1) -> 2.png, 147003 (form 2) -> 3.png
  function getSeraphineButtonIconPath(formId) {
    // Request icon path from Python via bridge
    // Python will return the local file path or serve it via HTTP
    // Map form IDs to button numbers
    let buttonNumber;
    if (formId === 147001) {
      buttonNumber = 1; // Base skin
    } else if (formId === 147002) {
      buttonNumber = 2; // Form 1
    } else if (formId === 147003) {
      buttonNumber = 3; // Form 2
    } else {
      // Fallback to form ID if unknown
      buttonNumber = formId;
    }
    const path = `local-asset://kdasera_buttons/${buttonNumber}.png`;
    return path;
  }

  // Get local button icon path for DJ Sona forms
  // Path: assets/djsona_buttons/{button_number}.png
  // Maps: 37006 (base) -> 1.png, 37998 (form 1) -> 2.png, 37999 (form 2) -> 3.png
  function getSonaButtonIconPath(formId) {
    // Request icon path from Python via bridge
    // Python will return the local file path or serve it via HTTP
    // Map form IDs to button numbers
    let buttonNumber;
    if (formId === 37006) {
      buttonNumber = 1; // Base skin
    } else if (formId === 37998) {
      buttonNumber = 2; // Form 1
    } else if (formId === 37999) {
      buttonNumber = 3; // Form 2
    } else {
      // Fallback to form ID if unknown
      buttonNumber = formId;
    }
    const path = `local-asset://djsona_buttons/${buttonNumber}.png`;
    return path;
  }

  // Get local button icon path for Arcane Fractured Jinx forms
  // Path: assets/arcanejinx_buttons/{button_number}.png
  // Maps: 222060 (base) -> 1.png, 222998 (form 1) -> 2.png, 222999 (form 2) -> 3.png
  function getJinxButtonIconPath(formId) {
    // Request icon path from Python via bridge
    // Python will return the local file path or serve it via HTTP
    // Map form IDs to button numbers
    let buttonNumber;
    if (formId === 222060) {
      buttonNumber = 1; // Base skin
    } else if (formId === 222998) {
      buttonNumber = 2; // Form 1
    } else if (formId === 222999) {
      buttonNumber = 3; // Form 2
    } else {
      // Fallback to form ID if unknown
      buttonNumber = formId;
    }
    const path = `local-asset://arcanejinx_buttons/${buttonNumber}.png`;
    return path;
  }

  // Get local button icon path for Uzi Kaisa forms
  // Path: assets/uzikaisa_buttons/{button_number}.png
  // Maps: 145070 (base) -> 1.png, 145071 (form 1) -> 2.png, 145999 (form 2) -> 3.png
  function getKaisaButtonIconPath(formId) {
    // Request icon path from Python via bridge
    // Python will return the local file path or serve it via HTTP
    // Map form IDs to button numbers
    let buttonNumber;
    if (formId === 145070) {
      buttonNumber = 1; // Base skin
    } else if (formId === 145071) {
      buttonNumber = 2; // Form 1
    } else if (formId === 145999) {
      buttonNumber = 3; // Form 2
    } else {
      // Fallback to form ID if unknown
      buttonNumber = formId;
    }
    const path = `local-asset://uzikaisa_buttons/${buttonNumber}.png`;
    return path;
  }

  // Get local button icon path for Viego forms
  // Path: assets/rrviego_buttons/{button_number}.png
  // Maps: 234043 (base) -> 1.png, 234994 (2nd form) -> 2.png, 234995 (3rd form) -> 3.png, etc.
  function getViegoButtonIconPath(formId) {
    // Request icon path from Python via bridge
    // Python will return the local file path or serve it via HTTP
    // Map form IDs to button numbers
    let buttonNumber;
    if (formId === 234043) {
      buttonNumber = 1; // Base skin
    } else if (formId === 234994) {
      buttonNumber = 2; // 2nd form
    } else if (formId === 234995) {
      buttonNumber = 3; // 3rd form
    } else if (formId === 234996) {
      buttonNumber = 4; // 4th form
    } else if (formId === 234997) {
      buttonNumber = 5; // 5th form
    } else if (formId === 234998) {
      buttonNumber = 6; // 6th form
    } else if (formId === 234999) {
      buttonNumber = 7; // 7th form
    } else {
      // Fallback to form ID if unknown
      buttonNumber = formId;
    }
    const path = `local-asset://rrviego_buttons/${buttonNumber}.png`;
    return path;
  }

  // Get button icon path for HOL chromas (Ahri only - Kaisa now uses forms)
  function getHolButtonIconPath(championId, chromaId, baseSkinId) {
    // Ahri forms (103085, 103086, 103087) use fakerahri_buttons folder with numbered images
    if (championId === 103 || baseSkinId === 103085) {
      // Map form IDs to button numbers
      // 103085 (base) -> 1.png, 103086 (form 1) -> 2.png, 103087 (form 2) -> 3.png
      let buttonNumber;
      if (chromaId === 103085) {
        buttonNumber = 1; // Base skin
      } else if (chromaId === 103086) {
        buttonNumber = 2; // Form 1
      } else if (chromaId === 103087) {
        buttonNumber = 3; // Form 2
      } else {
        // Fallback to form ID if unknown
        buttonNumber = chromaId;
      }
      const path = `local-asset://fakerahri_buttons/${buttonNumber}.png`;
      return path;
    }

    // Kaisa is now handled via forms, so this only applies to Ahri
    // If we reach here for Kaisa, return null (should not happen)
    return null;
  }

  function isSpecialBaseSkin(skinId) {
    return (
      Number.isFinite(skinId) &&
      (SPECIAL_BASE_SKIN_IDS.has(skinId) || skinId === 99007)
    );
  }

  function isMordekaiser(skinId) {
    return (
      Number.isFinite(skinId) &&
      (skinId === 82054 || skinId === 82998 || skinId === 82999)
    );
  }

  function isMorgana(skinId) {
    return Number.isFinite(skinId) && (skinId === 25080 || skinId === 25999);
  }

  function isSett(skinId) {
    return (
      Number.isFinite(skinId) &&
      (skinId === 875066 || skinId === 875998 || skinId === 875999)
    );
  }

  function isSeraphine(skinId) {
    return (
      Number.isFinite(skinId) &&
      (skinId === 147001 || skinId === 147002 || skinId === 147003)
    );
  }

  function isSona(skinId) {
    return (
      Number.isFinite(skinId) &&
      (skinId === 37006 || skinId === 37998 || skinId === 37999)
    );
  }

  function isJinx(skinId) {
    return (
      Number.isFinite(skinId) &&
      (skinId === 222060 || skinId === 222998 || skinId === 222999)
    );
  }

  function isKaisa(skinId) {
    return (
      Number.isFinite(skinId) &&
      (skinId === 145070 || skinId === 145071 || skinId === 145999)
    );
  }

  function isViego(skinId) {
    return (
      Number.isFinite(skinId) &&
      (skinId === 234043 || skinId === 234994 || skinId === 234995 || 
       skinId === 234996 || skinId === 234997 || skinId === 234998 || skinId === 234999)
    );
  }

  function isSpecialChromaSkin(skinId) {
    return (
      Number.isFinite(skinId) &&
      (SPECIAL_CHROMA_SKIN_IDS.has(skinId) || isElementalistFormSkinId(skinId))
    );
  }

  function isLikelyChromaId(skinId) {
    if (!Number.isFinite(skinId)) {
      return false;
    }
    if (isSpecialChromaSkin(skinId)) {
      return true;
    }
    if (chromaParentMap.has(skinId)) {
      return true;
    }
    return skinId >= 1000000;
  }

  function getChildSkinsFromData(skinData) {
    if (!skinData || typeof skinData !== "object") {
      return [];
    }

    const candidates = [
      skinData.childSkins,
      skinData.skin?.childSkins,
      skinData.skin?.chromas,
      Array.isArray(skinData.chromas) ? skinData.chromas : null,
      skinData.chromaDetails,
    ];

    for (const candidate of candidates) {
      if (Array.isArray(candidate) && candidate.length > 0) {
        return candidate;
      }
    }

    return [];
  }

  function markSkinHasChromas(skinId, hasChromas) {
    const numericId = getNumericId(skinId);
    if (!Number.isFinite(numericId)) {
      return;
    }
    skinChromaCache.set(numericId, Boolean(hasChromas));
  }

  function registerChromaChildren(baseSkinId, childSkins) {
    const numericBaseId = getNumericId(baseSkinId);
    if (!Number.isFinite(numericBaseId) || !Array.isArray(childSkins)) {
      return;
    }
    markSkinHasChromas(numericBaseId, true);
    childSkins.forEach((child) => {
      const childId = extractSkinIdFromData(child);
      if (Number.isFinite(childId)) {
        chromaParentMap.set(childId, numericBaseId);
        markSkinHasChromas(childId, true);
      }
    });
  }

  function getCachedChromasForSkin(skinId) {
    const numericId = getNumericId(skinId);
    if (!Number.isFinite(numericId)) {
      log.debug(`[getCachedChromasForSkin] Invalid skin ID: ${skinId}`);
      return [];
    }

    const championId = skinToChampionMap.get(numericId);
    if (!Number.isFinite(championId)) {
      log.debug(
        `[getCachedChromasForSkin] No champion ID found for skin ${numericId}`
      );
      return [];
    }

    const championCache = championSkinCache.get(championId);
    if (!championCache) {
      log.debug(
        `[getCachedChromasForSkin] No champion cache found for champion ${championId}`
      );
      return [];
    }

    const entry = championCache.get(numericId);
    if (!entry || !Array.isArray(entry.chromas)) {
      log.debug(
        `[getCachedChromasForSkin] No chromas entry found for skin ${numericId} in champion ${championId} cache`
      );
      return [];
    }

    log.debug(
      `[getCachedChromasForSkin] Found ${entry.chromas.length} chromas for skin ${numericId}`
    );

    // Ensure chromaParentMap is populated for these chromas
    entry.chromas.forEach((chroma) => {
      if (chroma.id && Number.isFinite(chroma.id) && chroma.id !== numericId) {
        // Only map if it's not the base skin itself
        if (!chromaParentMap.has(chroma.id)) {
          chromaParentMap.set(chroma.id, numericId);
          log.debug(
            `[getCachedChromasForSkin] Registered chroma ${chroma.id} -> base skin ${numericId} in chromaParentMap`
          );
        }
      }
    });

    return entry.chromas.map((chroma) => ({ ...chroma }));
  }

  function fetchChampionEndpoint(endpoint) {
    return window
      .fetch(endpoint, {
        method: "GET",
        credentials: "include",
      })
      .then((response) => {
        if (!response || !response.ok) {
          throw new Error(
            `HTTP ${response ? response.status : "NO_RESPONSE"} for ${endpoint}`
          );
        }
        return response.json();
      });
  }

  function requestChampionDataSequentially(endpoints, index = 0) {
    if (index >= endpoints.length) {
      return Promise.resolve(null);
    }
    const endpoint = endpoints[index];
    return fetchChampionEndpoint(endpoint)
      .then((data) => {
        if (data && Array.isArray(data.skins)) {
          return data;
        }
        throw new Error("Invalid champion data");
      })
      .catch((err) => {
        log.debug(`Failed to fetch champion data from ${endpoint}`, err);
        return requestChampionDataSequentially(endpoints, index + 1);
      });
  }

  function storeChampionSkins(championId, skins) {
    const skinMap = new Map();
    if (!Array.isArray(skins)) {
      return;
    }

    skins.forEach((skin) => {
      const skinId = getNumericId(skin?.id);
      if (!Number.isFinite(skinId)) {
        return;
      }

      const chromas = Array.isArray(skin.chromas) ? skin.chromas : [];
      const formattedChromas = chromas.map((chroma, index) => {
        const chromaId =
          getNumericId(chroma?.id) ?? getNumericId(chroma?.skinId) ?? index;
        const imagePath =
          chroma?.chromaPath ||
          chroma?.chromaPreviewPath ||
          chroma?.imagePath ||
          chroma?.splashPath ||
          "";
        // Extract colors from chroma data
        const colors = Array.isArray(chroma?.colors) ? chroma.colors : [];
        // Use the second color if available (typically the main chroma color), otherwise first color
        const primaryColor =
          colors.length > 1 ? colors[1] : colors.length > 0 ? colors[0] : null;
        return {
          id: chromaId,
          name: chroma?.name || chroma?.shortName || `Chroma ${index}`,
          imagePath,
          colors: colors,
          primaryColor: primaryColor,
          locked: !chroma?.ownership?.owned,
          purchaseDisabled: chroma?.purchaseDisabled,
        };
      });

      skinMap.set(skinId, {
        chromas: formattedChromas,
        rawSkin: skin,
      });

      skinToChampionMap.set(skinId, championId);
      const hasChromas =
        formattedChromas.length > 0 || isSpecialBaseSkin(skinId);
      markSkinHasChromas(skinId, hasChromas);
      if (formattedChromas.length > 0) {
        registerChromaChildren(skinId, formattedChromas);
      }
    });

    championSkinCache.set(championId, skinMap);
  }

  function fetchChampionSkinData(championId) {
    if (!Number.isFinite(championId)) {
      return null;
    }

    if (championSkinCache.has(championId)) {
      log.debug(`Champion ${championId} skin data already cached`);
      return Promise.resolve(championSkinCache.get(championId));
    }

    if (pendingChampionRequests.has(championId)) {
      return pendingChampionRequests.get(championId);
    }

    const endpoints = [
      `/lol-game-data/assets/v1/champions/${championId}.json`,
      `/lol-champions/v1/inventories/scouting/champions/${championId}`,
    ];

    log.debug(`Loading champion ${championId} skin data...`);
    const requestPromise = requestChampionDataSequentially(endpoints)
      .then((data) => {
        if (data && Array.isArray(data.skins)) {
          storeChampionSkins(championId, data.skins);
          const cacheEntry = championSkinCache.get(championId);
          log.debug(
            `Champion ${championId} skin data cached (${cacheEntry ? cacheEntry.size : 0
            } skins)`
          );
          return championSkinCache.get(championId);
        }
        return null;
      })
      .catch((err) => {
        log.debug(
          `Failed to load champion ${championId} skin data from all endpoints`,
          err
        );
        return null;
      })
      .finally(() => {
        pendingChampionRequests.delete(championId);
        setTimeout(() => {
          try {
            if (typeof scanSkinSelection === "function") {
              scanSkinSelection();
            }
          } catch (e) {
            log.debug("Rescan after champion fetch failed", e);
          }
        }, 0);
      });

    pendingChampionRequests.set(championId, requestPromise);
    return requestPromise;
  }

  function cacheSkinData(element, skinData) {
    if (!element || !skinData) {
      return;
    }
    try {
      element.__luChromaSkinData = skinData;
    } catch (e) {
      log.debug("Failed to cache skin data", e);
    }
  }

  function getCachedSkinData(element) {
    if (!element) {
      return null;
    }
    if (element.__luChromaSkinData) {
      return element.__luChromaSkinData;
    }
    const skinData = getSkinData(element);
    if (skinData) {
      cacheSkinData(element, skinData);
    }
    return skinData;
  }

  function injectCSS() {
    const styleId = "forms-wheel-button-css";
    if (document.getElementById(styleId)) {
      return;
    }

    const styleTag = document.createElement("style");
    styleTag.id = styleId;
    styleTag.textContent = CSS_RULES;
    document.head.appendChild(styleTag);
    log.debug("injected CSS rules");
  }

  function updateHoverButtonImage(button) {
    if (!button) return;
    if (hoverButtonNormalUrl) {
      button.style.backgroundImage = `url('${hoverButtonNormalUrl}')`;
      button.style.backgroundSize = "contain";
      button.style.backgroundRepeat = "no-repeat";
      button.style.backgroundPosition = "center";
      button.style.backgroundColor = "transparent";
      button.style.border = "none";
    } else {
      // Placeholder until asset loads
      button.style.backgroundColor = "#c89b3c";
      button.style.backgroundImage = "none";
      button.style.border = "2px solid #010a13";
      button.style.borderRadius = "4px";
    }
  }

  function createFakeButton() {
    const button = document.createElement("div");
    button.className = BUTTON_CLASS;

    // Request hover button assets from Python
    if (!hoverButtonNormalUrl && bridge) {
      bridge.send({
        type: "request-local-asset",
        assetPath: HOVER_BUTTON_ASSET,
        timestamp: Date.now(),
      });
    }
    if (!hoverButtonHoverUrl && bridge) {
      bridge.send({
        type: "request-local-asset",
        assetPath: HOVER_BUTTON_HOVER_ASSET,
        timestamp: Date.now(),
      });
    }

    // Apply custom asset directly to button (no nested structure)
    updateHoverButtonImage(button);

    // Hover handlers
    button.addEventListener("mouseenter", () => {
      if (hoverButtonHoverUrl) {
        button.style.backgroundImage = `url('${hoverButtonHoverUrl}')`;
        button.style.backgroundColor = "transparent";
        button.style.backgroundRepeat = "no-repeat";
        button.style.backgroundPosition = "center";
        button.style.border = "none";
      } else {
        button.style.backgroundColor = "#f0e6d2";
        button.style.border = "2px solid #c89b3c";
      }
    });

    button.addEventListener("mouseleave", () => {
      updateHoverButtonImage(button);
    });

    // Add click handler to open chroma panel
    const handleClick = (e) => {
      e.stopPropagation();
      e.preventDefault();
      log.info("[FormsWheel] Forms button clicked!");
      const skinItem = button.closest(
        ".skin-selection-item, .thumbnail-wrapper"
      );
      if (skinItem) {
        // Check if this skin has offset 2
        const offset = getSkinOffset(skinItem);
        const isSwiftplayActive =
          skinItem.classList.contains("thumbnail-wrapper") &&
          skinItem.classList.contains("active-skin");
        log.info(`[FormsWheel] Skin offset: ${offset}, isSwiftplayActive: ${isSwiftplayActive}`);

        if (offset === 2 || isSwiftplayActive) {
          log.info(
            `[FormsWheel] Found valid skin item (offset=${offset}, swiftplay=${isSwiftplayActive}), opening panel`
          );
          toggleChromaPanel(button, skinItem);
        } else {
          log.info(
            `[FormsWheel] Skin offset is ${offset}, not 2, and not Swiftplay active. Panel will not open.`
          );
        }
      } else {
        log.warn("[FormsWheel] Could not find skin item for forms button");
      }
    };

    button.addEventListener("click", handleClick);
    button.addEventListener("mousedown", (e) => {
      // Also handle mousedown as fallback
      e.stopPropagation();
    });

    return button;
  }

  const ARAM_BACKGROUND_ASSET_PATH = "champ-select-flyout-background-aram.png";
  let aramBackgroundImageUrl = null;
  let aramBackgroundRequestPending = false;
  let currentChromaInfoElement = null;
  let isAramFromPython = false; // Preferred ARAM detection source (via WebSocket)

  function getGameModeFromEmber() {
    try {
      if (!window.Ember) {
        return null;
      }

      const championSelectEl = document.querySelector(".champion-select");
      if (!championSelectEl) {
        return null;
      }

      if (window.Ember.getOwner) {
        const application = window.Ember.getOwner(championSelectEl);
        if (application) {
          const rootComponent = application.lookup("component:champion-select");
          if (rootComponent) {
            const gameMode = rootComponent.get("gameMode");
            if (gameMode) {
              return gameMode;
            }
          }
        }
      }

      // Fallback: try accessing via __ember_view__
      const emberView =
        championSelectEl.__ember_view__ || championSelectEl._view;
      if (emberView) {
        const context = emberView.context || emberView._context;
        if (context) {
          const gameMode =
            context.gameMode ||
            (context.gameflow &&
              context.gameflow.gameData &&
              context.gameflow.gameData.queue &&
              context.gameflow.gameData.queue.gameMode);
          if (gameMode) {
            return gameMode;
          }
        }
      }
    } catch (e) {
      // Silently fail
    }

    return null;
  }

  function isSwiftplayMode() {
    // Check if game mode is Swiftplay
    try {
      const gameMode = getGameModeFromEmber();
      if (
        gameMode &&
        (gameMode.toLowerCase().includes("swiftplay") ||
          gameMode === "SWIFTPLAY")
      ) {
        return true;
      }
    } catch (e) {
      // Silently fail
    }
    return false;
  }

  function isAramMode() {
    // Check if current game mode is ARAM (Howling Abyss)
    // Prefer Python-detected state from WebSocket when available.
    if (isAramFromPython) {
      return true;
    }

    try {
      const gameMode = getGameModeFromEmber();
      if (
        gameMode &&
        (gameMode.toLowerCase().includes("aram") || gameMode === "ARAM")
      ) {
        return true;
      }
    } catch (e) {
      // Silently fail
    }
    return false;
  }

  function isSessionInitialized() {
    // Check if champ-select-init has completed by checking for session data
    try {
      // Check if session timer exists (indicates session is initialized)
      const timer = document.querySelector(".timer");
      if (timer && timer.textContent && timer.textContent.trim() !== "") {
        return true;
      }

      // Check if skin carousel exists (indicates session is initialized)
      const skinCarousel = document.querySelector(".skin-selection-carousel");
      if (skinCarousel && skinCarousel.children.length > 0) {
        return true;
      }

      // Check if session data exists via API or Ember
      if (window.Ember) {
        const championSelectEl = document.querySelector(".champion-select");
        if (championSelectEl) {
          if (window.Ember.getOwner) {
            const application = window.Ember.getOwner(championSelectEl);
            if (application) {
              const rootComponent = application.lookup(
                "component:champion-select"
              );
              if (rootComponent) {
                const session = rootComponent.get("session");
                if (session && session.timer) {
                  return true;
                }
              }
            }
          }
        }
      }
    } catch (e) {
      // Silently fail
    }
    return false;
  }

  function updateButtonVisibility(button, hasChromas) {
    if (!button) return;

    const shouldShow = Boolean(hasChromas);
    const lastState = button._luLastVisibilityState;
    const willChange = lastState === undefined || lastState !== shouldShow;

    // Only log when visibility actually changes
    if (willChange) {
      emitBridgeLog("button_visibility_update", {
        shouldShow,
        hasChromas,
        buttonExists: true,
      });
      button._luLastVisibilityState = shouldShow;
    }

    if (shouldShow) {
      button.style.display = "block";
      button.style.visibility = "visible";
      button.style.pointerEvents = "auto";
      button.style.opacity = "1";
      button.style.cursor = "pointer";
      button.removeAttribute("data-hidden");
      // Re-enable pointer events on all children
      const children = button.querySelectorAll("*");
      children.forEach((child) => {
        child.style.pointerEvents = "";
        child.style.cursor = "";
        child.style.visibility = "";
      });
    } else {
      button.style.display = "none";
      button.style.visibility = "hidden";
      button.style.pointerEvents = "none";
      button.style.opacity = "0";
      button.style.cursor = "default";
      button.setAttribute("data-hidden", "true");

      // Disable pointer events on all children to prevent any hover effects
      const children = button.querySelectorAll("*");
      children.forEach((child) => {
        child.style.pointerEvents = "none";
        child.style.cursor = "default";
        child.style.visibility = "hidden";
      });

      // Close and disable any open panel when button becomes hidden
      const existingPanel = document.getElementById(PANEL_ID);
      if (existingPanel) {
        log.info(
          "[FormsWheel] Button hidden, closing panel and marking as non-interactive"
        );
      }
    }
  }

  function isCurrentSkinItem(skinItem) {
    if (!skinItem) {
      return false;
    }

    // Carousel items: rely on offset 2 (center/current slot)
    if (skinItem.classList.contains("skin-selection-item")) {
      const offset = getSkinOffset(skinItem);
      if (offset === 2) {
        return true;
      }
    }

    // Thumbnail wrappers (e.g., Swiftplay lobby) typically flag selection via attributes/classes
    if (skinItem.classList.contains("thumbnail-wrapper")) {
      // Check for active-skin class (Swiftplay mode)
      if (skinItem.classList.contains("active-skin")) {
        return true;
      }
      if (
        skinItem.classList.contains("selected") ||
        skinItem.getAttribute("aria-selected") === "true"
      ) {
        return true;
      }
    }

    return false;
  }

  function doesSkinItemMatchSkinState(skinItem) {
    if (!skinMonitorState?.skinId) {
      return true;
    }
    const skinData = getCachedSkinData(skinItem);
    const skinId = getSkinIdFromContext(skinData, skinItem);
    return Number.isFinite(skinId) && skinId === skinMonitorState.skinId;
  }

  function getSkinItemFromButton(button) {
    return button.closest(".skin-selection-item, .thumbnail-wrapper");
  }

  function handleChampionLocked(data) {
    const wasLocked = championLocked;
    championLocked = data.locked === true;

    log.debug(
      `[FormsWheel] Champion lock state updated: ${championLocked} (was: ${wasLocked})`
    );

    // If champion was unlocked, remove all buttons
    if (!championLocked && wasLocked) {
      log.debug("[FormsWheel] Champion unlocked - removing all chroma buttons");
      const allButtons = document.querySelectorAll(BUTTON_SELECTOR);
      allButtons.forEach((button) => button.remove());
    } else if (championLocked && !wasLocked) {
      // Champion just locked - scan for buttons
      log.debug("[FormsWheel] Champion locked - scanning for chroma buttons");
      setTimeout(() => {
        if (typeof scanSkinSelection === "function") {
          scanSkinSelection();
        }
      }, 100);
    }
  }

  function ensureFakeButton(skinItem) {
    if (!skinItem) {
      return;
    }

    // CHECK 4 (Strict Wrapper Mode):
    // If ANY active-skin wrapper exists globally, we are in Swiftplay/Grid mode.
    // In this mode, we STRICTLY BLOCK generic parent items (skin-selection-item) from having buttons.
    // The button MUST only be on the thumbnail-wrapper.
    const isWrapperMode = document.querySelector(".thumbnail-wrapper.active-skin") !== null;
    const isGenericParent =
      skinItem.classList.contains("skin-selection-item") &&
      !skinItem.classList.contains("thumbnail-wrapper");

    if (isWrapperMode && isGenericParent) {
      // We are in Swiftplay mode and this is a generic parent.
      // It is NOT allowed to have a button. Remove if exists.
      const existingButton = skinItem.querySelector(BUTTON_SELECTOR);
      if (existingButton) {
        existingButton.remove();
        // Also ensure we remove any direct children that look like our buttons
        // (Just in case specific selector fails but class matches)
        Array.from(skinItem.children).forEach(child => {
          if (child.classList.contains(BUTTON_CLASS)) {
            child.remove();
          }
        });
      }
      return;
    }



    // Check if this is Swiftplay mode
    const isSwiftplayActive =
      skinItem.classList.contains("thumbnail-wrapper") &&
      skinItem.classList.contains("active-skin");

    // Don't create button if champion is not locked (except in Swiftplay)
    if (!championLocked && !isSwiftplayActive) {
      // Remove existing button if champion is not locked
      const existingButton = skinItem.querySelector(BUTTON_SELECTOR);
      if (existingButton) {
        existingButton.remove();
      }
      return;
    }

    const isCurrent = isCurrentSkinItem(skinItem);
    const currentSkinId = skinMonitorState?.skinId ?? null;

    // FormsWheel: Check if this is a supported skin (has Forms, not chromas)
    // Check both currentSkinId from state and skinId from the skinItem itself
    const skinData = getCachedSkinData(skinItem);
    const itemSkinId = getSkinIdFromContext(skinData, skinItem);
    const skinIdToCheck = currentSkinId || itemSkinId;

    // Check if this skin (current or item) is supported
    const isSupported =
      skinIdToCheck &&
      (isSupportedSkin(skinIdToCheck) || getSkinConfig(skinIdToCheck) !== null);
    const hasChromas = isSupported; // For FormsWheel, supported skins show buttons

    // Only show button for supported skins
    if (isCurrent && !isSupported) {
      const existingButton = skinItem.querySelector(BUTTON_SELECTOR);
      if (existingButton) {
        existingButton.remove();
      }
      return;
    }

    // Don't show button if not current skin
    if (!isCurrent) {
      const existingButton = skinItem.querySelector(BUTTON_SELECTOR);
      if (existingButton) {
        existingButton.remove();
      }
      return;
    }

    // Check if button already exists
    let existingButton = skinItem.querySelector(BUTTON_SELECTOR);

    // Only log current skin eval when skin actually changes
    const lastEval = ensureFakeButton._lastEval;
    if (
      !lastEval ||
      lastEval.skinId !== currentSkinId ||
      lastEval.hasChromas !== hasChromas
    ) {
      emitBridgeLog("current_skin_eval", {
        stateSkinId: currentSkinId,
        hasChromas,
        elementClasses: skinItem.className,
      });
      ensureFakeButton._lastEval = { skinId: currentSkinId, hasChromas };
    }

    // Create and inject the fake button
    try {
      if (!existingButton) {
        const fakeButton = createFakeButton();

        // For Swiftplay mode (thumbnail-wrapper with active-skin), place button directly on thumbnail-wrapper
        if (
          skinItem.classList.contains("thumbnail-wrapper") &&
          skinItem.classList.contains("active-skin")
        ) {
          // Always place directly on thumbnail-wrapper for Swiftplay
          skinItem.appendChild(fakeButton);
          existingButton = fakeButton;
          log.debug(
            `[FormsWheel] Placed button on Swiftplay thumbnail-wrapper for skin ${currentSkinId}`
          );
        } else {
          // Normal champ select: ensure parent has relative positioning
          if (window.getComputedStyle(skinItem).position === "static") {
            skinItem.style.position = "relative";
          }
          skinItem.appendChild(fakeButton);
          existingButton = fakeButton;
        }

        emitBridgeLog("button_created", {
          skinId: currentSkinId,
          hasChromas,
          isSupported,
          championLocked,
        });
      }

      updateButtonVisibility(existingButton, hasChromas);
    } catch (e) {
      log.warn("Failed to create forms button", e);
      emitBridgeLog("button_creation_error", { error: String(e) });
    }
  }

  function scanSkinSelection() {
    const skinItems = document.querySelectorAll(".skin-selection-item");
    const thumbnailWrappers = document.querySelectorAll(".thumbnail-wrapper");

    // Only log when state actually changes
    const prevState = scanSkinSelection._lastState;
    const currentState = {
      skinItemsCount: skinItems.length,
      currentSkinId: skinMonitorState?.skinId,
      hasChromas: skinMonitorState?.hasChromas,
    };
    if (
      !prevState ||
      prevState.currentSkinId !== currentState.currentSkinId ||
      prevState.hasChromas !== currentState.hasChromas
    ) {
      emitBridgeLog("scan_skin_selection", {
        ...currentState,
        thumbnailWrappersCount: thumbnailWrappers.length,
      });
      scanSkinSelection._lastState = currentState;
    }

    // Attempt 6: Exclusive Scan Mode
    // If we have thumbnail wrappers (Grid/Swiftplay), ONLY they should have buttons.
    // Generic skin-selection-item parents are strictly forbidden in this mode.
    const hasWrappers = thumbnailWrappers.length > 0;

    // 1. Always process wrappers if they exist
    thumbnailWrappers.forEach((wrapper) => ensureFakeButton(wrapper));

    // 2. Process skin items CONDITIONALLY
    skinItems.forEach((skinItem) => {
      // If we are in Wrapper Mode (hasWrappers is true), 
      // STRICTLY BLOCK generic items from having buttons.
      if (hasWrappers) {
        // Safety: Remove any button that might have been added to this generic item
        const existingButton = skinItem.querySelector(BUTTON_SELECTOR);
        if (existingButton) {
          existingButton.remove();
        }
        // Also remove direct children that look like buttons (extra safety)
        Array.from(skinItem.children).forEach(child => {
          if (child.classList.contains(BUTTON_CLASS)) {
            child.remove();
          }
        });
        return;
      }

      // Standard Mode (Carousel): Process normally
      ensureFakeButton(skinItem);
    });
  }

  function isVisible(element) {
    if (!element) {
      return false;
    }
    return element.offsetParent !== null;
  }

  function readCurrentSkinName() {
    if (skinMonitorState?.name) {
      return skinMonitorState.name;
    }

    // Read skin name from the same location as skin monitor
    for (const selector of SKIN_SELECTORS) {
      const nodes = document.querySelectorAll(selector);
      if (!nodes.length) {
        continue;
      }

      let candidate = null;

      nodes.forEach((node) => {
        const name = node.textContent.trim();
        if (!name) {
          return;
        }

        if (isVisible(node)) {
          candidate = name;
        } else if (!candidate) {
          candidate = name;
        }
      });

      if (candidate) {
        return candidate;
      }
    }

    return null;
  }

  function getSkinOffset(skinItem) {
    // Check the skin item itself for offset class like "skin-carousel-offset-2"
    let offsetMatch = skinItem.className.match(/skin-carousel-offset-(\d+)/);
    if (offsetMatch) {
      return parseInt(offsetMatch[1]);
    }

    // Check parent elements (the li element might have the class)
    let parent = skinItem.parentElement;
    let depth = 0;
    while (parent && depth < 3) {
      offsetMatch = parent.className.match(/skin-carousel-offset-(\d+)/);
      if (offsetMatch) {
        return parseInt(offsetMatch[1]);
      }
      parent = parent.parentElement;
      depth++;
    }

    // Try to get from Ember view context
    const emberView = skinItem.closest(".ember-view");
    if (emberView) {
      const view =
        emberView.__ember_view__ ||
        emberView._view ||
        (window.Ember &&
          window.Ember.View.views &&
          window.Ember.View.views[emberView.id]);

      if (view) {
        const context = view.context || view._context || view.get?.("context");
        if (context) {
          const item = context.item || context;
          if (item && typeof item.offset === "number") {
            return item.offset;
          }
        }
      }
    }

    return null;
  }

  function getSkinData(skinItem) {
    // Try multiple methods to extract skin data

    // Method 1: Try to get from Ember view context
    const emberView = skinItem.closest(".ember-view");
    if (emberView) {
      // Try different Ember view property access patterns
      const view =
        emberView.__ember_view__ ||
        emberView._view ||
        (window.Ember &&
          window.Ember.View.views &&
          window.Ember.View.views[emberView.id]);

      if (view) {
        const context = view.context || view._context || view.get?.("context");
        if (context) {
          const skin = context.skin || context.item?.skin || context;
          if (skin && (skin.id || skin.skinId)) {
            // Try to get chromas from the skin object directly (like official client does)
            // The official client has chromas in the skin object from Ember context
            if (skin.chromas || skin.childSkins) {
              log.debug(
                `[getSkinData] Found chromas in Ember context: ${(skin.chromas || skin.childSkins)?.length || 0
                } chromas`
              );
            }
            return skin;
          }
        }
      }
    }

    // Method 2: Try to get from data attributes
    const dataId =
      skinItem.getAttribute("data-skin-id") ||
      skinItem.querySelector("[data-skin-id]")?.getAttribute("data-skin-id");
    if (dataId) {
      return { skinId: parseInt(dataId) };
    }

    // Method 3: Extract from background image URL
    const thumbnail = skinItem.querySelector(".skin-selection-thumbnail");
    if (thumbnail) {
      const bgImage =
        thumbnail.style.backgroundImage ||
        window.getComputedStyle(thumbnail).backgroundImage;
      const match = bgImage.match(/champion-splashes\/(\d+)\/(\d+)\.jpg/);
      if (match) {
        return {
          championId: parseInt(match[1]),
          skinId: parseInt(match[2]),
        };
      }
    }

    // Method 4: Try to find skin name from DOM
    const skinNameElement = skinItem.querySelector(
      ".skin-selection-item-information"
    );
    const name = skinNameElement?.textContent?.trim();

    return name ? { name } : null;
  }

  function markSelectedChroma(chromas, currentSkinId) {
    // Mark the chroma that matches Python's selected chroma ID
    // Use Python's state if available, otherwise fall back to current skin ID
    if (!chromas || chromas.length === 0) {
      return chromas;
    }

    // Reset all selections
    chromas.forEach((c) => (c.selected = false));

    // Use Python's selected chroma ID if available and not null
    // Only use currentSkinId as fallback if Python state doesn't exist or selectedChromaId is null
    let selectedChromaId = null;
    if (
      pythonChromaState &&
      pythonChromaState.selectedChromaId !== null &&
      pythonChromaState.selectedChromaId !== undefined
    ) {
      selectedChromaId = pythonChromaState.selectedChromaId;
      log.debug(
        `[getChromaData] Using Python's selected chroma ID: ${selectedChromaId}`
      );
    } else {
      // Python state not available or no chroma selected - use current skin ID (base skin)
      selectedChromaId = currentSkinId;
      log.debug(
        `[getChromaData] Using current skin ID as fallback: ${selectedChromaId}`
      );
    }

    // Find chroma matching the selected chroma ID
    const matchingChroma = chromas.find((c) => c.id === selectedChromaId);
    if (matchingChroma) {
      matchingChroma.selected = true;
      log.debug(
        `[getChromaData] Marked chroma ${matchingChroma.id} as selected (ID: ${selectedChromaId})`
      );
    } else {
      // Default to base skin (first chroma with name "Default")
      const defaultChroma = chromas.find((c) => c.name === "Default");
      if (defaultChroma) {
        defaultChroma.selected = true;
        log.debug(
          `[getChromaData] Marked default chroma ${defaultChroma.id} as selected (no match for ID ${selectedChromaId})`
        );
      } else if (chromas.length > 0) {
        // Fallback to first chroma
        chromas[0].selected = true;
        log.debug(
          `[getChromaData] Marked first chroma ${chromas[0].id} as selected (fallback)`
        );
      }
    }

    return chromas;
  }

  function getChromaData(skinData) {
    if (!skinData) {
      return [];
    }

    // Get current skin ID from state to determine which chroma should be selected
    // Prioritize Python's selected chroma ID if available, otherwise use skinMonitorState
    // This ensures we show the correct selected chroma even if skinMonitorState has the base skin ID
    const currentSkinId =
      pythonChromaState?.selectedChromaId !== null &&
        pythonChromaState?.selectedChromaId !== undefined
        ? pythonChromaState.selectedChromaId
        : skinMonitorState?.skinId || null;

    const baseSkinId = extractSkinIdFromData(skinData);
    const resolvedChampionId =
      getChampionIdFromContext(skinData, baseSkinId, null) ||
      skinData.championId ||
      (Number.isFinite(baseSkinId) ? Math.floor(baseSkinId / 1000) : null);

    // SPECIAL CASE: Check for special skins FIRST (before LCU API data)
    // Elementalist Lux (skin ID 99007) - use local Forms data
    if (baseSkinId === 99007 || (99991 <= baseSkinId && baseSkinId <= 99999)) {
      log.debug(
        `[getChromaData] Elementalist Lux detected (base skin: 99007) - using local Forms data`
      );
      const forms = getElementalistForms();
      const baseFormId = 99007; // Always use base skin ID for Elementalist Lux
      const luxChampionId = 99; // Lux champion ID

      // Base skin (Elementalist Lux base)
      const baseSkinChroma = {
        id: baseFormId,
        name: "Default",
        imagePath: getLocalPreviewPath(
          luxChampionId,
          baseFormId,
          baseFormId,
          true
        ),
        colors: [],
        primaryColor: null,
        selected: false,
        locked: false,
        buttonIconPath: getElementalistButtonIconPath(baseFormId),
      };

      // Forms (fake IDs 99991-99999)
      const formList = forms.map((form) => ({
        id: form.id,
        name: form.name,
        imagePath: getLocalPreviewPath(
          luxChampionId,
          baseFormId,
          form.id,
          false
        ),
        colors: form.colors || [],
        primaryColor: null, // Forms don't have colors
        selected: false,
        locked: false, // Forms are clickable (locking is just visual in the official client)
        buttonIconPath: getElementalistButtonIconPath(form.id),
        form_path: form.form_path,
      }));

      const allChromas = [baseSkinChroma, ...formList];
      return markSelectedChroma(allChromas, currentSkinId);
    }

    // SPECIAL CASE: Sahn Uzal Mordekaiser (skin ID 82054) - use local Forms data
    // FormsWheel: Handle Mordekaiser forms using SUPPORTED_SKINS configuration
    if (baseSkinId === 82054 || baseSkinId === 82998 || baseSkinId === 82999) {
      const skinConfig = getSkinConfig(baseSkinId);
      if (skinConfig && isSupportedSkin(baseSkinId)) {
        log.debug(
          `[getChromaData] Sahn Uzal Mordekaiser detected (base skin: 82054) - using local Forms data`
        );
        const forms = getMordekaiserForms();
        const baseFormId = 82054; // Always use base skin ID
        const mordekaiserChampionId = 82; // Mordekaiser champion ID

        // Base skin (Sahn Uzal Mordekaiser base)
        const baseSkinChroma = {
          id: baseFormId,
          name: "Default",
          imagePath: getLocalPreviewPath(
            mordekaiserChampionId,
            baseFormId,
            baseFormId,
            true
          ),
          colors: [],
          primaryColor: null,
          selected: false,
          locked: false,
          buttonIconPath: `local-asset://${skinConfig.buttonFolder}/1.png`, // Use index-based path
        };

        // Forms (IDs 82998, 82999) - use index-based button paths
        const formList = forms.map((form, index) => {
          const buttonIconPath = `local-asset://${skinConfig.buttonFolder}/${index + 2
            }.png`; // 2.png, 3.png
          return {
            id: form.id,
            name: form.name,
            imagePath: getLocalPreviewPath(
              mordekaiserChampionId,
              baseFormId,
              form.id,
              false
            ),
            colors: form.colors || [],
            primaryColor: null, // Forms don't have colors
            selected: false,
            locked: false, // Forms are clickable
            buttonIconPath: buttonIconPath,
            form_path: form.form_path,
          };
        });

        const allChromas = [baseSkinChroma, ...formList];
        return markSelectedChroma(allChromas, currentSkinId);
      }
    }

    // SPECIAL CASE: Spirit Blossom Morgana (skin ID 25080) - use local Forms data
    // FormsWheel: Handle Morgana forms using SUPPORTED_SKINS configuration
    if (baseSkinId === 25080 || baseSkinId === 25999) {
      const skinConfig = getSkinConfig(baseSkinId);
      if (skinConfig && isSupportedSkin(baseSkinId)) {
        log.debug(
          `[getChromaData] Spirit Blossom Morgana detected (base skin: 25080) - using local Forms data`
        );
        const forms = getMorganaForms();
        const baseFormId = 25080; // Always use base skin ID
        const morganaChampionId = skinConfig.championId; // Use championId from config

        // Base skin (Spirit Blossom Morgana base)
        const baseSkinChroma = {
          id: baseFormId,
          name: "Default",
          imagePath: getLocalPreviewPath(
            morganaChampionId,
            baseFormId,
            baseFormId,
            true
          ),
          colors: [],
          primaryColor: null,
          selected: false,
          locked: false,
          buttonIconPath: `local-asset://${skinConfig.buttonFolder}/1.png`, // Use index-based path
        };

        // Forms (ID 25999) - use index-based button paths
        const formList = forms.map((form, index) => {
          const buttonIconPath = `local-asset://${skinConfig.buttonFolder}/${index + 2
            }.png`; // 2.png
          return {
            id: form.id,
            name: form.name,
            imagePath: getLocalPreviewPath(
              morganaChampionId,
              baseFormId,
              form.id,
              false
            ),
            colors: form.colors || [],
            primaryColor: null, // Forms don't have colors
            selected: false,
            locked: false, // Forms are clickable
            buttonIconPath: buttonIconPath,
            form_path: form.form_path,
          };
        });

        const allChromas = [baseSkinChroma, ...formList];
        return markSelectedChroma(allChromas, currentSkinId);
      }
    }

    // SPECIAL CASE: Radiant Sett (skin ID 875066) - use local Forms data
    // FormsWheel: Handle Sett forms using SUPPORTED_SKINS configuration
    if (baseSkinId === 875066 || baseSkinId === 875998 || baseSkinId === 875999) {
      const skinConfig = getSkinConfig(baseSkinId);
      if (skinConfig && isSupportedSkin(baseSkinId)) {
        log.debug(
          `[getChromaData] Radiant Sett detected (base skin: 875066) - using local Forms data`
        );
        const forms = getSettForms();
        const baseFormId = 875066; // Always use base skin ID
        const settChampionId = 875; // Sett champion ID

        // Base skin (Radiant Sett base)
        const baseSkinChroma = {
          id: baseFormId,
          name: "Default",
          imagePath: getLocalPreviewPath(
            settChampionId,
            baseFormId,
            baseFormId,
            true
          ),
          colors: [],
          primaryColor: null,
          selected: false,
          locked: false,
          buttonIconPath: `local-asset://${skinConfig.buttonFolder}/1.png`, // Use index-based path
        };

        // Forms (IDs 875998, 875999) - use index-based button paths
        const formList = forms.map((form, index) => {
          const buttonIconPath = `local-asset://${skinConfig.buttonFolder}/${index + 2
            }.png`; // 2.png, 3.png
          return {
            id: form.id,
            name: form.name,
            imagePath: getLocalPreviewPath(
              settChampionId,
              baseFormId,
              form.id,
              false
            ),
            colors: form.colors || [],
            primaryColor: null, // Forms don't have colors
            selected: false,
            locked: false, // Forms are clickable
            buttonIconPath: buttonIconPath,
            form_path: form.form_path,
          };
        });

        const allChromas = [baseSkinChroma, ...formList];
        return markSelectedChroma(allChromas, currentSkinId);
      }
    }

    // SPECIAL CASE: KDA Seraphine (skin ID 147001) - use local Forms data
    // FormsWheel: Handle Seraphine forms using SUPPORTED_SKINS configuration
    if (baseSkinId === 147001 || baseSkinId === 147002 || baseSkinId === 147003) {
      const skinConfig = getSkinConfig(baseSkinId);
      if (skinConfig && isSupportedSkin(baseSkinId)) {
        log.debug(
          `[getChromaData] KDA Seraphine detected (base skin: 147001) - using local Forms data`
        );
        const forms = getSeraphineForms();
        const baseFormId = 147001; // Always use base skin ID
        const seraphineChampionId = 147; // Seraphine champion ID

        // Base skin (KDA Seraphine base)
        const baseSkinChroma = {
          id: baseFormId,
          name: "Default",
          imagePath: getLocalPreviewPath(
            seraphineChampionId,
            baseFormId,
            baseFormId,
            true
          ),
          colors: [],
          primaryColor: null,
          selected: false,
          locked: false,
          buttonIconPath: `local-asset://${skinConfig.buttonFolder}/1.png`, // Use index-based path
        };

        // Forms (IDs 147002, 147003) - use index-based button paths
        const formList = forms.map((form, index) => {
          const buttonIconPath = `local-asset://${skinConfig.buttonFolder}/${index + 2
            }.png`; // 2.png, 3.png
          return {
            id: form.id,
            name: form.name,
            imagePath: getLocalPreviewPath(
              seraphineChampionId,
              baseFormId,
              form.id,
              false
            ),
            colors: form.colors || [],
            primaryColor: null, // Forms don't have colors
            selected: false,
            locked: false, // Forms are clickable
            buttonIconPath: buttonIconPath,
            form_path: form.form_path,
          };
        });

        const allChromas = [baseSkinChroma, ...formList];
        return markSelectedChroma(allChromas, currentSkinId);
      }
    }

    // SPECIAL CASE: DJ Sona (skin ID 37006) - use local Forms data
    // FormsWheel: Handle Sona forms using SUPPORTED_SKINS configuration
    if (baseSkinId === 37006 || baseSkinId === 37998 || baseSkinId === 37999) {
      const skinConfig = getSkinConfig(baseSkinId);
      if (skinConfig && isSupportedSkin(baseSkinId)) {
        log.debug(
          `[getChromaData] DJ Sona detected (base skin: 37006) - using local Forms data`
        );
        const forms = getSonaForms();
        const baseFormId = 37006; // Always use base skin ID
        const sonaChampionId = 37; // Sona champion ID

        // Base skin (DJ Sona base)
        const baseSkinChroma = {
          id: baseFormId,
          name: "Default",
          imagePath: getLocalPreviewPath(
            sonaChampionId,
            baseFormId,
            baseFormId,
            true
          ),
          colors: [],
          primaryColor: null,
          selected: false,
          locked: false,
          buttonIconPath: `local-asset://${skinConfig.buttonFolder}/1.png`, // Use index-based path
        };

        // Forms (IDs 37998, 37999) - use index-based button paths
        const formList = forms.map((form, index) => {
          const buttonIconPath = `local-asset://${skinConfig.buttonFolder}/${index + 2
            }.png`; // 2.png, 3.png
          return {
            id: form.id,
            name: form.name,
            imagePath: getLocalPreviewPath(
              sonaChampionId,
              baseFormId,
              form.id,
              false
            ),
            colors: form.colors || [],
            primaryColor: null, // Forms don't have colors
            selected: false,
            locked: false, // Forms are clickable
            buttonIconPath: buttonIconPath,
            form_path: form.form_path,
          };
        });

        const allChromas = [baseSkinChroma, ...formList];
        return markSelectedChroma(allChromas, currentSkinId);
      }
    }

    // SPECIAL CASE: Arcane Fractured Jinx (skin ID 222060) - use local Forms data
    // FormsWheel: Handle Jinx forms using SUPPORTED_SKINS configuration
    if (baseSkinId === 222060 || baseSkinId === 222998 || baseSkinId === 222999) {
      const skinConfig = getSkinConfig(baseSkinId);
      if (skinConfig && isSupportedSkin(baseSkinId)) {
        log.debug(
          `[getChromaData] Arcane Fractured Jinx detected (base skin: 222060) - using local Forms data`
        );
        const forms = getJinxForms();
        const baseFormId = 222060; // Always use base skin ID
        const jinxChampionId = 222; // Jinx champion ID

        // Base skin (Arcane Fractured Jinx base)
        const baseSkinChroma = {
          id: baseFormId,
          name: "Default",
          imagePath: getLocalPreviewPath(
            jinxChampionId,
            baseFormId,
            baseFormId,
            true
          ),
          colors: [],
          primaryColor: null,
          selected: false,
          locked: false,
          buttonIconPath: `local-asset://${skinConfig.buttonFolder}/1.png`, // Use index-based path
        };

        // Forms (IDs 222998, 222999) - use index-based button paths
        const formList = forms.map((form, index) => {
          const buttonIconPath = `local-asset://${skinConfig.buttonFolder}/${index + 2
            }.png`; // 2.png, 3.png
          return {
            id: form.id,
            name: form.name,
            imagePath: getLocalPreviewPath(
              jinxChampionId,
              baseFormId,
              form.id,
              false
            ),
            colors: form.colors || [],
            primaryColor: null, // Forms don't have colors
            selected: false,
            locked: false, // Forms are clickable
            buttonIconPath: buttonIconPath,
            form_path: form.form_path,
          };
        });

        const allChromas = [baseSkinChroma, ...formList];
        return markSelectedChroma(allChromas, currentSkinId);
      }
    }

    // SPECIAL CASE: Uzi Kaisa (skin ID 145070) - use local Forms data
    // FormsWheel: Handle Kaisa forms using SUPPORTED_SKINS configuration
    if (baseSkinId === 145070 || baseSkinId === 145071 || baseSkinId === 145999) {
      const skinConfig = getSkinConfig(baseSkinId);
      if (skinConfig && isSupportedSkin(baseSkinId)) {
        log.debug(
          `[getChromaData] Uzi Kaisa detected (base skin: 145070) - using local Forms data`
        );
        const forms = getKaisaForms();
        const baseFormId = 145070; // Always use base skin ID
        const kaisaChampionId = 145; // Kaisa champion ID

        // Base skin (Uzi Kaisa base)
        const baseSkinChroma = {
          id: baseFormId,
          name: "Default",
          imagePath: getLocalPreviewPath(
            kaisaChampionId,
            baseFormId,
            baseFormId,
            true
          ),
          colors: [],
          primaryColor: null,
          selected: false,
          locked: false,
          buttonIconPath: `local-asset://${skinConfig.buttonFolder}/1.png`, // Use index-based path
        };

        // Forms (IDs 145071, 145999) - use index-based button paths
        const formList = forms.map((form, index) => {
          const buttonIconPath = `local-asset://${skinConfig.buttonFolder}/${index + 2
            }.png`; // 2.png, 3.png
          return {
            id: form.id,
            name: form.name,
            imagePath: getLocalPreviewPath(
              kaisaChampionId,
              baseFormId,
              form.id,
              false
            ),
            colors: form.colors || [],
            primaryColor: null, // Forms don't have colors
            selected: false,
            locked: false, // Forms are clickable
            buttonIconPath: buttonIconPath,
            form_path: form.form_path,
          };
        });

        const allChromas = [baseSkinChroma, ...formList];
        return markSelectedChroma(allChromas, currentSkinId);
      }
    }

    // SPECIAL CASE: Viego (skin ID 234043) - use local Forms data
    // FormsWheel: Handle Viego forms using SUPPORTED_SKINS configuration
    if (baseSkinId === 234043 || baseSkinId === 234994 || baseSkinId === 234995 || 
        baseSkinId === 234996 || baseSkinId === 234997 || baseSkinId === 234998 || baseSkinId === 234999) {
      const skinConfig = getSkinConfig(baseSkinId);
      if (skinConfig && isSupportedSkin(baseSkinId)) {
        log.debug(
          `[getChromaData] Viego detected (base skin: 234043) - using local Forms data`
        );
        const forms = getViegoForms();
        const baseFormId = 234043; // Always use base skin ID
        const viegoChampionId = 234; // Viego champion ID

        // Base skin (Viego base)
        const baseSkinChroma = {
          id: baseFormId,
          name: "Default",
          imagePath: getLocalPreviewPath(
            viegoChampionId,
            baseFormId,
            baseFormId,
            true
          ),
          colors: [],
          primaryColor: null,
          selected: false,
          locked: false,
          buttonIconPath: `local-asset://${skinConfig.buttonFolder}/1.png`, // Use index-based path
        };

        // Forms (IDs 234994-234999) - use index-based button paths
        const formList = forms.map((form, index) => {
          const buttonIconPath = `local-asset://${skinConfig.buttonFolder}/${index + 2
            }.png`; // 2.png, 3.png, 4.png, 5.png, 6.png, 7.png
          return {
            id: form.id,
            name: form.name,
            imagePath: getLocalPreviewPath(
              viegoChampionId,
              baseFormId,
              form.id,
              false
            ),
            colors: form.colors || [],
            primaryColor: null, // Forms don't have colors
            selected: false,
            locked: false, // Forms are clickable
            buttonIconPath: buttonIconPath,
            form_path: form.form_path,
          };
        });

        const allChromas = [baseSkinChroma, ...formList];
        return markSelectedChroma(allChromas, currentSkinId);
      }
    }

    // SPECIAL CASE: Risen Legend Ahri (skin ID 103085) or Immortalized Legend (103086) or Form 2 (103087)
    if (baseSkinId === 103085 || baseSkinId === 103086 || baseSkinId === 103087) {
      log.debug(
        `[getChromaData] Risen Legend Ahri detected (base skin: 103085) - using local HOL chroma data`
      );
      const holChromas = getAhriHolChromas();
      const actualBaseSkinId = 103085; // Always use base skin ID
      const ahriChampionId = 103; // Ahri champion ID

      // Base skin (Risen Legend Ahri)
      const baseSkinChroma = {
        id: actualBaseSkinId,
        name: "Default",
        imagePath: getLocalPreviewPath(
          ahriChampionId,
          actualBaseSkinId,
          actualBaseSkinId,
          true
        ),
        colors: [],
        primaryColor: null,
        selected: false,
        locked: false,
        buttonIconPath: getHolButtonIconPath(
          ahriChampionId,
          actualBaseSkinId,
          actualBaseSkinId
        ),
      };

      // HOL chroma (Immortalized Legend)
      const holChromaList = holChromas.map((chroma) => ({
        id: chroma.id,
        name: chroma.name,
        imagePath: getLocalPreviewPath(
          ahriChampionId,
          actualBaseSkinId,
          chroma.id,
          false
        ),
        colors: chroma.colors || [],
        primaryColor: null,
        selected: false,
        locked: false, // HOL chromas are clickable
        buttonIconPath: getHolButtonIconPath(
          ahriChampionId,
          chroma.id,
          actualBaseSkinId
        ),
      }));

      const allChromas = [baseSkinChroma, ...holChromaList];
      return markSelectedChroma(allChromas, currentSkinId);
    }

    // First, check if chromas are directly in the skinData (like official client)
    // The official client gets chromas from the Ember component context
    if (Array.isArray(skinData.chromas) && skinData.chromas.length > 0) {
      log.debug(
        `[getChromaData] Found ${skinData.chromas.length} chromas directly in skinData (official client method)`
      );
      const baseSkinId = extractSkinIdFromData(skinData);
      const championId = getChampionIdFromContext(skinData, baseSkinId, null);

      // Include the base skin as the first option (default)
      // Construct image path for default chroma: /lol-game-data/assets/v1/champion-chroma-images/{championId}/{skinId}.png
      const defaultImagePath =
        championId && baseSkinId
          ? `/lol-game-data/assets/v1/champion-chroma-images/${championId}/${baseSkinId}.png`
          : null;

      const baseSkinChroma = {
        id: baseSkinId,
        name: "Default",
        imagePath: defaultImagePath,
        colors: [],
        primaryColor: null,
        selected: false, // Will be set by markSelectedChroma
        locked: false,
      };

      const chromaList = skinData.chromas.map((chroma, index) => {
        const chromaId =
          extractSkinIdFromData(chroma) ?? chroma.id ?? chroma.skinId ?? index;
        // Extract colors from chroma data
        const colors = Array.isArray(chroma?.colors) ? chroma.colors : [];
        // Use the second color if available (typically the main chroma color), otherwise first color
        const primaryColor =
          colors.length > 1 ? colors[1] : colors.length > 0 ? colors[0] : null;
        return {
          id: chromaId,
          name:
            chroma.name ||
            chroma.shortName ||
            chroma.chromaName ||
            `Chroma ${index}`,
          imagePath:
            chroma.chromaPreviewPath || chroma.imagePath || chroma.chromaPath,
          colors: colors,
          primaryColor: primaryColor,
          selected: false, // Will be set by markSelectedChroma
          locked: !chroma.ownership?.owned,
          purchaseDisabled: chroma.purchaseDisabled,
        };
      });

      const allChromas = [baseSkinChroma, ...chromaList];
      return markSelectedChroma(allChromas, currentSkinId);
    }

    const childSkins = getChildSkinsFromData(skinData);
    if (childSkins.length > 0) {
      log.debug(
        `[getChromaData] Found ${childSkins.length} child skins in skinData`
      );
      const baseSkinId = extractSkinIdFromData(skinData);
      const championId = getChampionIdFromContext(skinData, baseSkinId, null);
      registerChromaChildren(baseSkinId, childSkins);

      // Include the base skin as the first option (default)
      // Construct image path for default chroma: /lol-game-data/assets/v1/champion-chroma-images/{championId}/{skinId}.png
      const defaultImagePath =
        championId && baseSkinId
          ? `/lol-game-data/assets/v1/champion-chroma-images/${championId}/${baseSkinId}.png`
          : null;

      const baseSkinChroma = {
        id: baseSkinId,
        name: "Default",
        imagePath: defaultImagePath,
        colors: [],
        primaryColor: null,
        selected: false, // Will be set by markSelectedChroma
        locked: false,
      };

      const chromaList = childSkins.map((chroma, index) => {
        const chromaId =
          extractSkinIdFromData(chroma) ?? chroma.id ?? chroma.skinId ?? index;
        // Extract colors from chroma data
        const colors = Array.isArray(chroma?.colors) ? chroma.colors : [];
        // Use the second color if available (typically the main chroma color), otherwise first color
        const primaryColor =
          colors.length > 1 ? colors[1] : colors.length > 0 ? colors[0] : null;
        return {
          id: chromaId,
          name: chroma.name || chroma.shortName || `Chroma ${index}`,
          imagePath: chroma.chromaPreviewPath || chroma.imagePath,
          colors: colors,
          primaryColor: primaryColor,
          selected: false, // Will be set by markSelectedChroma
          locked: !chroma.ownership?.owned,
          purchaseDisabled: chroma.purchaseDisabled,
        };
      });

      const allChromas = [baseSkinChroma, ...chromaList];
      return markSelectedChroma(allChromas, currentSkinId);
    }

    log.debug(
      `[getChromaData] Checking cached chromas for base skin ${baseSkinId}`
    );
    const cachedChromas = getCachedChromasForSkin(baseSkinId);
    if (cachedChromas.length > 0) {
      log.debug(
        `[getChromaData] Found ${cachedChromas.length} cached chromas for skin ${baseSkinId}`
      );
      const championId = getChampionIdFromContext(skinData, baseSkinId, null);

      // Include the base skin as the first option (default)
      // Construct image path for default chroma: /lol-game-data/assets/v1/champion-chroma-images/{championId}/{skinId}.png
      const defaultImagePath =
        championId && baseSkinId
          ? `/lol-game-data/assets/v1/champion-chroma-images/${championId}/${baseSkinId}.png`
          : null;

      const baseSkinChroma = {
        id: baseSkinId,
        name: "Default",
        imagePath: defaultImagePath,
        colors: [],
        primaryColor: null,
        selected: false, // Will be set by markSelectedChroma
        locked: false,
      };
      const allChromas = [
        baseSkinChroma,
        ...cachedChromas.map((chroma, index) => ({
          ...chroma,
          selected: false, // Will be set by markSelectedChroma
        })),
      ];
      return markSelectedChroma(allChromas, currentSkinId);
    }

    // Fallback: construct chroma paths based on skin ID
    // This should rarely be used if champion data is properly fetched
    log.debug(
      `[getChromaData] No chromas found in cache for skin ${baseSkinId}, using fallback`
    );
    const fallbackSkinId = baseSkinId ?? skinData.id;
    const effectiveSkinId = getNumericId(fallbackSkinId);
    const fallbackChampionId =
      skinData.championId ||
      getChampionIdFromContext(skinData, effectiveSkinId);
    const finalChampionId =
      fallbackChampionId ||
      (Number.isFinite(effectiveSkinId)
        ? Math.floor(effectiveSkinId / 1000)
        : null);

    if (!Number.isFinite(effectiveSkinId)) {
      log.debug(`[getChromaData] Invalid skin ID: ${fallbackSkinId}`);
      return [];
    }

    const championForImages = finalChampionId;
    if (!championForImages) {
      log.debug(
        `[getChromaData] Could not determine champion ID for skin ${effectiveSkinId}`
      );
      return [];
    }
    const chromas = [];

    // Create base skin as first option
    chromas.push({
      id: effectiveSkinId,
      name: "Default",
      imagePath: `/lol-game-data/assets/v1/champion-chroma-images/${championForImages}/${effectiveSkinId}000.png`,
      selected: true,
      locked: false,
      colors: [],
      primaryColor: null,
    });

    // Try to find additional chromas (typically numbered 001-012)
    // Create placeholder chromas with default colors if we know the skin has chromas
    const hasChromas =
      skinMonitorState?.hasChromas || skinChromaCache.get(effectiveSkinId);
    const numPlaceholders = hasChromas ? 12 : 3; // Create more placeholders if we know chromas exist

    // Default chroma colors to use as fallback (from official League)
    const defaultColors = [
      "#DF9117", // Orange/Gold
      "#2DA130", // Green
      "#BE1E37", // Red
      "#1E90FF", // Blue
      "#9370DB", // Purple
      "#FF69B4", // Pink
      "#FFD700", // Gold
      "#00CED1", // Cyan
      "#FF6347", // Tomato
      "#32CD32", // Lime
      "#FF1493", // Deep Pink
      "#4169E1", // Royal Blue
    ];

    for (let i = 1; i <= numPlaceholders; i++) {
      const chromaId = effectiveSkinId * 1000 + i;
      const colorIndex = (i - 1) % defaultColors.length;
      chromas.push({
        id: chromaId,
        name: `Chroma ${i}`,
        imagePath: `/lol-game-data/assets/v1/champion-chroma-images/${championForImages}/${chromaId}.png`,
        selected: false,
        locked: true, // Assume locked unless we can verify ownership
        colors: [defaultColors[colorIndex]],
        primaryColor: defaultColors[colorIndex],
      });
    }

    log.debug(
      `[getChromaData] Created ${chromas.length} fallback chromas for skin ${effectiveSkinId}`
    );
    return chromas;
  }

  function createChromaPanel(skinData, chromas, buttonElement) {
    log.info(
      `[FormsWheel] createChromaPanel called with ${chromas.length} chromas`
    );
    log.debug("createChromaPanel details:", {
      skinData,
      chromas,
      buttonElement,
    });

    // Ensure button element exists and is valid before creating panel
    if (!buttonElement) {
      log.warn("[FormsWheel] Cannot create panel: button element not provided");
      return;
    }

    // Verify button is visible
    const buttonVisible =
      buttonElement.offsetParent !== null &&
      buttonElement.style.display !== "none" &&
      buttonElement.style.opacity !== "0";
    if (!buttonVisible) {
      log.warn("[FormsWheel] Cannot create panel: button element not visible");
      return;
    }

    // Remove existing panel if any
    const existingPanel = document.getElementById(PANEL_ID);
    if (existingPanel) {
      existingPanel.remove();
    }

    const panel = document.createElement("div");
    panel.id = PANEL_ID;
    panel.className = PANEL_CLASS;
    panel.style.position = "fixed";
    panel.style.top = "0";
    panel.style.left = "0";
    panel.style.width = "100%";
    panel.style.height = "100%";
    panel.style.zIndex = "10000";
    panel.style.pointerEvents = "none"; // Panel container doesn't capture events, only flyout does
    // Only set default cursor if button isn't present - otherwise allow normal interaction
    if (!buttonElement || !buttonVisible) {
      panel.setAttribute("data-no-button", "true");
      panel.style.cursor = "default";
    }

    // Create flyout frame structure (or use simple div if custom elements don't work)
    let flyoutFrame;
    try {
      flyoutFrame = document.createElement("lol-uikit-flyout-frame");
      flyoutFrame.className = "flyout";
      flyoutFrame.setAttribute("orientation", "top");
      flyoutFrame.setAttribute("animated", "false");
      flyoutFrame.setAttribute("caretoffset", "undefined");
      flyoutFrame.setAttribute("borderless", "undefined");
      flyoutFrame.setAttribute("caretless", "undefined");
      flyoutFrame.setAttribute("show", "true");
    } catch (e) {
      log.debug("Could not create custom element, using div", e);
      flyoutFrame = document.createElement("div");
      flyoutFrame.className = "flyout";
    }

    // Set initial flyout frame styles to match official positioning
    flyoutFrame.style.position = "absolute";
    flyoutFrame.style.overflow = "visible";
    flyoutFrame.style.pointerEvents = "all";
    // Only set default cursor if button isn't present - otherwise allow normal interaction
    if (!buttonElement || !buttonVisible) {
      flyoutFrame.style.pointerEvents = "none";
      flyoutFrame.style.cursor = "default";
    }

    let flyoutContent;
    try {
      flyoutContent = document.createElement("lc-flyout-content");
    } catch (e) {
      log.debug("Could not create lc-flyout-content, using div", e);
      flyoutContent = document.createElement("div");
      flyoutContent.className = "lc-flyout-content";
    }

    const modal = document.createElement("div");
    modal.className = "champ-select-chroma-modal chroma-view ember-view";

    // Add border element (matches official structure)
    const border = document.createElement("div");
    border.className = "border";

    // Chroma information section
    const chromaInfo = document.createElement("div");
    chromaInfo.className = "chroma-information";
    currentChromaInfoElement = chromaInfo;

    // Default background (Summoner's Rift) - official client path
    let bgPath =
      "lol-game-data/assets/content/src/LeagueClient/GameModeAssets/Classic_SRU/img/champ-select-flyout-background.jpg";

    // If we're in ARAM mode, try to use the locally-served ARAM background
    if (isAramMode()) {
      if (aramBackgroundImageUrl) {
        bgPath = aramBackgroundImageUrl;
        log.debug(
          "[FormsWheel] Using cached ARAM background image for chroma panel"
        );
      } else {
        // Request ARAM background from Python; keep SR background as temporary fallback
        requestAramBackgroundImage();
        log.debug(
          "[FormsWheel] ARAM mode detected - requesting ARAM background image"
        );
      }
    }

    chromaInfo.style.backgroundImage = `url('${bgPath}')`;

    const chromaImage = document.createElement("div");
    chromaImage.className = "chroma-information-image";
    // Set initial preview - use selected chroma if available, otherwise first chroma
    // This matches the official client behavior
    if (chromas.length > 0) {
      const selectedChroma = chromas.find((c) => c.selected) || chromas[0];
      updateChromaPreview(selectedChroma, chromaImage);

      // Set selectedChromaData based on the selected chroma when panel is created
      // This ensures the button color is correct even if Python hasn't broadcast state yet
      selectedChromaData = {
        id: selectedChroma.id,
        primaryColor:
          selectedChroma.primaryColor ||
          selectedChroma.colors?.[1] ||
          selectedChroma.colors?.[0] ||
          null,
        colors: selectedChroma.colors || [],
        name: selectedChroma.name,
        buttonIconPath: selectedChroma.buttonIconPath || null, // Include button icon path for Elementalist Lux forms and HOL chromas
      };

      // Note: selectedChromaData will be updated by Python's chroma-state message
      // if Python provides better/more accurate data
    } else {
      // Hide the image element when no chromas are available
      chromaImage.style.display = "none";
    }

    const skinName = document.createElement("div");
    skinName.className = "child-skin-name";
    // Fetch the actual skin name from the DOM (same location as skin monitor)
    const displayName =
      readCurrentSkinName() ||
      skinData.name ||
      skinData.championName ||
      (skinData.championId ? `Champion ${skinData.championId}` : "Champion");
    skinName.textContent = displayName;

    const disabledNotification = document.createElement("div");
    disabledNotification.className = "child-skin-disabled-notification";

    skinName.appendChild(disabledNotification);
    chromaInfo.appendChild(chromaImage);
    chromaInfo.appendChild(skinName);

    // Chroma selection scrollable area
    let scrollable;
    try {
      scrollable = document.createElement("lol-uikit-scrollable");
      scrollable.className = "chroma-selection";
      scrollable.setAttribute("overflow-masks", "enabled");
    } catch (e) {
      log.debug("Could not create scrollable, using div", e);
      scrollable = document.createElement("div");
      scrollable.className = "chroma-selection";
      scrollable.style.overflowY = "auto";
      scrollable.style.maxHeight = "92px";
    }

    // Create ul list for chroma buttons (matching official League structure)
    const chromaList = document.createElement("ul");
    chromaList.style.listStyle = "none";
    chromaList.style.margin = "0";
    chromaList.style.padding = "0";
    chromaList.style.display = "flex";
    chromaList.style.flexDirection = "row";
    chromaList.style.flexWrap = "wrap";
    chromaList.style.alignItems = "center";
    chromaList.style.justifyContent = "center";
    chromaList.style.gap = "0";
    chromaList.style.width = "100%";

    // Track hover state to ensure preview resets to selected when no button is hovered
    let hoveredChromaId = null;
    const resetToSelectedPreview = () => {
      const selectedChroma = chromas.find((c) => c.selected);
      if (selectedChroma && hoveredChromaId === null) {
        updateChromaPreview(selectedChroma, chromaImage);
      }
    };

    // Create chroma buttons as li elements (matching official League structure)
    let buttonCount = 0;
    chromas.forEach((chroma, index) => {
      const listItem = document.createElement("li");
      listItem.style.listStyle = "none";
      listItem.style.margin = "0";
      listItem.style.padding = "0";
      listItem.style.display = "flex";
      listItem.style.alignItems = "center";
      listItem.style.justifyContent = "center";

      const emberView = document.createElement("div");
      emberView.className = "ember-view";

      const chromaButton = document.createElement("div");
      chromaButton.className = `chroma-skin-button ${chroma.locked ? "locked" : ""
        } ${chroma.selected ? "selected" : ""} ${chroma.purchaseDisabled ? "purchase-disabled" : ""
        }`;

      const contents = document.createElement("div");
      contents.className = "contents";

      // FormsWheel: All supported skins use custom assets from button folder
      const baseSkinId = getBaseSkinId(chroma.id) || chroma.id;
      const skinConfig = getSkinConfig(baseSkinId);

      // Check if this is a supported skin (has Forms, uses custom assets)
      if (skinConfig && isSupportedSkin(baseSkinId)) {
        // FormsWheel: Use custom asset buttons from button folder
        // Format: uzal_buttons/1.png, uzal_buttons/2.png, uzal_buttons/3.png, etc.
        const assetFileName = `${index + 1}.png`;
        const iconPath = `${skinConfig.buttonFolder}/${assetFileName}`;

        // Request button icon from Python via bridge
        if (bridge) bridge.send({
          type: "request-local-asset",
          assetPath: iconPath,
          chromaId: chroma.id,
          timestamp: Date.now(),
        });

        // Store pending request so we can apply the URL when Python responds
        pendingLocalAssets.set(chroma.id, { contents, chroma });

        log.debug(
          `[FormsWheel] Requested local button icon: ${iconPath} for chroma ${chroma.id}`
        );

        // Use placeholder until Python serves the image
        contents.style.background = "";
        contents.style.backgroundImage = "";
        contents.style.backgroundColor = "#1e2328"; // Dark placeholder
        contents.style.backgroundSize = "cover";
        contents.style.backgroundPosition = "center";
        contents.style.backgroundRepeat = "no-repeat";
        log.debug(
          `[FormsWheel] Button ${index + 1}: ${chroma.name
          } - using custom asset button from ${skinConfig.buttonFolder
          } (placeholder until Python serves)`
        );
      } else if (
        chroma.buttonIconPath &&
        chroma.buttonIconPath.startsWith("local-asset://")
      ) {
        // Fallback: Other forms with buttonIconPath (Elementalist Lux, etc.)
        const iconPath = chroma.buttonIconPath.replace("local-asset://", "");

        // Request button icon from Python via bridge
        if (bridge) bridge.send({
          type: "request-local-asset",
          assetPath: iconPath,
          chromaId: chroma.id,
          timestamp: Date.now(),
        });

        // Store pending request so we can apply the URL when Python responds
        pendingLocalAssets.set(chroma.id, { contents, chroma });

        log.debug(
          `[FormsWheel] Requested local button icon: ${iconPath} for chroma ${chroma.id}`
        );

        // Use placeholder until Python serves the image
        contents.style.background = "";
        contents.style.backgroundImage = "";
        contents.style.backgroundColor = "#1e2328"; // Dark placeholder
        contents.style.backgroundSize = "cover";
        contents.style.backgroundPosition = "center";
        contents.style.backgroundRepeat = "no-repeat";
        log.debug(
          `[FormsWheel] Button ${index + 1}: ${chroma.name
          } - using local button icon (placeholder until Python serves)`
        );
      } else {
        // Check if this is the base/default skin button
        const isDefaultButton =
          chroma.name === "Default" &&
          !chroma.primaryColor &&
          !chroma.colors?.length;

        if (isDefaultButton) {
          // Base/default button: use the original gradient (beige with red stripe) - matching official League
          contents.style.background =
            "linear-gradient(135deg, #f0e6d2, #f0e6d2 48%, #be1e37 0, #be1e37 52%, #f0e6d2 0, #f0e6d2)";
          contents.style.backgroundSize = "cover";
          contents.style.backgroundPosition = "center";
          contents.style.backgroundRepeat = "no-repeat";
          log.debug(
            `[FormsWheel] Button ${index + 1}: ${chroma.name
            } - using default gradient`
          );
        } else {
          // Chroma buttons: use chroma color if available, otherwise fall back to image
          const primaryColor =
            chroma.primaryColor || chroma.colors?.[1] || chroma.colors?.[0];
          if (primaryColor) {
            // Ensure color has # prefix
            const color = primaryColor.startsWith("#")
              ? primaryColor
              : `#${primaryColor}`;
            // Use solid background color (no gradient to avoid darkening)
            contents.style.backgroundColor = color;
            contents.style.background = color;
            log.debug(
              `[FormsWheel] Button ${index + 1}: ${chroma.name
              } with color ${color}`
            );
          } else if (chroma.imagePath) {
            // Fall back to image if no color available
            contents.style.background = `url('${chroma.imagePath}')`;
            contents.style.backgroundSize = "cover";
            contents.style.backgroundPosition = "center";
            contents.style.backgroundRepeat = "no-repeat";
            log.debug(
              `[FormsWheel] Button ${index + 1}: ${chroma.name} with image ${chroma.imagePath
              }`
            );
          } else {
            // Default fallback color if no color or image is available
            contents.style.background =
              "linear-gradient(135deg, #f0e6d2 0%, #f0e6d2 50%, #f0e6d2 50%, #f0e6d2 100%)";
            contents.style.backgroundSize = "cover";
            contents.style.backgroundPosition = "center";
            contents.style.backgroundRepeat = "no-repeat";
            log.debug(
              `[FormsWheel] Button ${index + 1}: ${chroma.name
              } - no color or image, using default`
            );
          }
        }
      }

      chromaButton.appendChild(contents);
      emberView.appendChild(chromaButton);
      listItem.appendChild(emberView);
      chromaList.appendChild(listItem);
      buttonCount++;

      // Add click handler (allow clicking even if locked - locking is just visual)
      // Add to both button and contents to ensure clicks are captured
      const handleClick = (e) => {
        e.stopPropagation();
        e.preventDefault();
        log.info(
          `[FormsWheel] Chroma button clicked: ${chroma.name} (ID: ${chroma.id}, locked: ${chroma.locked})`
        );
        // Play official chroma click sound (matches Riot's sfx-cs-button-chromas-click.ogg)
        playChromaClickSound();
        selectChroma(chroma, chromas, chromaImage, chromaButton, scrollable);
      };
      chromaButton.addEventListener("click", handleClick);
      contents.addEventListener("click", handleClick);

      // Add hover handlers to update preview (matching official client behavior)
      chromaButton.addEventListener("mouseenter", (e) => {
        e.stopPropagation();
        hoveredChromaId = chroma.id;
        updateChromaPreview(chroma, chromaImage);
      });

      chromaButton.addEventListener("mouseleave", (e) => {
        e.stopPropagation();
        // Clear hover state and reset to selected chroma
        hoveredChromaId = null;
        // Use setTimeout to check if we're entering another button
        setTimeout(() => {
          if (hoveredChromaId === null) {
            resetToSelectedPreview();
          }
        }, 0);
      });
    });

    log.info(`[FormsWheel] Created ${buttonCount} chroma buttons in panel`);
    scrollable.appendChild(chromaList);

    // Update chroma button color after all buttons are created
    updateChromaButtonColor();

    // Reset to selected chroma when mouse leaves the scrollable area
    scrollable.addEventListener("mouseleave", (e) => {
      // Only reset if we're not entering another button
      hoveredChromaId = null;
      setTimeout(() => {
        if (hoveredChromaId === null) {
          resetToSelectedPreview();
        }
      }, 0);
    });

    modal.appendChild(border);
    modal.appendChild(chromaInfo);
    modal.appendChild(scrollable);
    flyoutContent.appendChild(modal);
    flyoutFrame.appendChild(flyoutContent);
    panel.appendChild(flyoutFrame);

    // Position the panel relative to the button
    positionPanel(panel, buttonElement);

    // Add click outside handler to close
    const closeHandler = function closePanelOnOutsideClick(e) {
      if (
        panel &&
        panel.parentNode &&
        !panel.contains(e.target) &&
        !buttonElement.contains(e.target)
      ) {
        panel.remove();
        document.removeEventListener("click", closeHandler);
      }
    };
    // Use setTimeout to avoid immediate closure
    setTimeout(() => {
      document.addEventListener("click", closeHandler);
    }, 100);

    document.body.appendChild(panel);
    log.debug("Panel appended to body", panel);

    // Force a reflow to ensure positioning works
    panel.offsetHeight;

    // Reposition after render
    setTimeout(() => {
      positionPanel(panel, buttonElement);
    }, 0);

    return panel;
  }

  function positionPanel(panel, buttonElement) {
    if (!panel || !buttonElement) {
      log.warn("Cannot position panel: missing elements");
      return;
    }

    // Find the flyout frame element inside the panel
    const flyoutFrame = panel.querySelector(".flyout");
    if (!flyoutFrame) {
      log.warn("Cannot position panel: flyout frame not found");
      return;
    }

    const rect = buttonElement.getBoundingClientRect();
    let flyoutRect = flyoutFrame.getBoundingClientRect();

    // If flyout hasn't been rendered yet, use estimated dimensions
    if (flyoutRect.width === 0) {
      flyoutRect = { width: 305, height: 420 };
    }

    // Calculate position relative to button to match official flyout positioning
    // Official flyout is positioned at top: 178px, left: 486.5px relative to the viewport
    // We need to position it relative to the button's position
    // The flyout should appear above the button, centered horizontally
    const buttonCenterX = rect.left + rect.width / 2;
    const flyoutLeft = buttonCenterX - flyoutRect.width / 2;

    // Position above the button with some spacing
    // Official positioning shows the flyout above the button
    // Adjusted 5px higher than default
    const flyoutTop = rect.top - flyoutRect.height - 15;

    // Set the flyout frame positioning to match official style
    // Official: position: absolute; overflow: visible; top: 178px; left: 486.5px;
    flyoutFrame.style.position = "absolute";
    flyoutFrame.style.overflow = "visible";
    flyoutFrame.style.top = `${Math.max(10, flyoutTop)}px`;
    flyoutFrame.style.left = `${Math.max(
      10,
      Math.min(flyoutLeft, window.innerWidth - flyoutRect.width - 10)
    )}px`;

    // Ensure panel container doesn't interfere with positioning
    panel.style.position = "fixed";
    panel.style.top = "0";
    panel.style.left = "0";
    panel.style.width = "100%";
    panel.style.height = "100%";
    panel.style.pointerEvents = "none";

    // Make flyout frame interactive
    flyoutFrame.style.pointerEvents = "all";

    log.debug("Flyout frame positioned", {
      top: flyoutFrame.style.top,
      left: flyoutFrame.style.left,
      buttonRect: rect,
      flyoutRect: flyoutRect,
    });
  }

  function updateChromaPreview(chroma, chromaImage) {
    // Update preview image using chroma imagePath
    // For special skins (Elementalist Lux, Spirit Blossom Morgana, HOL chromas), use local preview paths
    // Note: Mordekaiser removed - handled by ROSE-FormsWheel
    // For regular chromas, use LCU API paths
    const imagePath = chroma.imagePath;

    if (imagePath) {
      // Check if this is a local preview path (special skins)
      if (imagePath.startsWith("local-preview://")) {
        // Request preview image from Python via bridge
        // Format: local-preview://{champion_id}/{skin_id}/{chroma_id}/{chroma_id}.png
        const pathParts = imagePath.replace("local-preview://", "").split("/");
        if (pathParts.length >= 4) {
          const championId = pathParts[0];
          const skinId = pathParts[1];
          const chromaId = pathParts[2];

          // Request preview from Python
          if (bridge) bridge.send({
            type: "request-local-preview",
            championId: parseInt(championId),
            skinId: parseInt(skinId),
            chromaId: parseInt(chromaId),
            timestamp: Date.now(),
          });

          // Store pending request so we can apply the URL when Python responds
          pendingLocalPreviews.set(parseInt(chromaId), { chromaImage, chroma });

          log.debug(
            `[FormsWheel] Requested local preview for champion ${championId}, skin ${skinId}, chroma ${chromaId}`
          );

          // Hide until Python serves the image
          chromaImage.style.background = "";
          chromaImage.style.backgroundImage = "";
          chromaImage.style.display = "none";
        } else {
          chromaImage.style.display = "none";
        }
      } else {
        // Regular LCU API path
        // Use the chroma preview image (official client behavior)
        // Match official client: background-size: contain (not cover) to avoid zooming
        chromaImage.style.background = "";
        chromaImage.style.backgroundImage = `url('${imagePath}')`;
        chromaImage.style.backgroundSize = "contain"; // Match official client - contain fits entire image
        chromaImage.style.backgroundPosition = "center";
        chromaImage.style.backgroundRepeat = "no-repeat";
        chromaImage.style.display = "";
      }
    } else {
      // Hide if no image path available
      chromaImage.style.display = "none";
    }
  }

  function updateChromaButtonColor() {
    // Update the chroma button's content background to match selected chroma
    // For Elementalist Lux forms and Spirit Blossom Morgana forms: use button icon image
    // Note: Mordekaiser removed - handled by ROSE-FormsWheel
    // If default chroma (no color), keep the button-chroma.png image
    // If chroma has color, use that color as background
    const buttons = document.querySelectorAll(BUTTON_SELECTOR);
    buttons.forEach((button) => {
      const content = button.querySelector(".content");
      if (!content) {
        log.debug(
          `[FormsWheel] Button color update: no .content element found`
        );
        return;
      }

      // Check if this chroma has a button icon path (Elementalist Lux forms, Spirit Blossom Morgana forms, or HOL chromas)
      // Note: Mordekaiser removed - handled by ROSE-FormsWheel
      if (
        selectedChromaData &&
        selectedChromaData.buttonIconPath &&
        selectedChromaData.buttonIconPath.startsWith("local-asset://")
      ) {
        // Elementalist Lux form, Spirit Blossom Morgana form, or HOL chroma - always request the icon to ensure it matches the selected chroma
        // Note: Mordekaiser removed - handled by ROSE-FormsWheel
        // Track the last applied chroma ID on the button to detect when switching between chromas
        const lastAppliedChromaId = content.getAttribute("data-last-chroma-id");
        const chromaIdChanged =
          lastAppliedChromaId !== String(selectedChromaData.id);

        // Check if we already have a pending request for THIS specific chroma ID
        const hasPendingRequestForThisChroma = pendingLocalAssets.has(
          selectedChromaData.id
        );

        // Always request if:
        // 1. Chroma ID changed (switching between forms/chromas)
        // 2. No pending request for this chroma ID (new request needed)
        // This ensures the icon updates immediately when switching between chromas
        if (chromaIdChanged || !hasPendingRequestForThisChroma) {
          const iconPath = selectedChromaData.buttonIconPath.replace(
            "local-asset://",
            ""
          );

          // Request button icon from Python via bridge
          if (bridge) bridge.send({
            type: "request-local-asset",
            assetPath: iconPath,
            chromaId: selectedChromaData.id,
            timestamp: Date.now(),
          });

          // Store pending request so we can apply the URL when Python responds
          pendingLocalAssets.set(selectedChromaData.id, {
            contents: content,
            chroma: selectedChromaData,
          });

          // Mark that we're requesting this chroma ID
          content.setAttribute(
            "data-last-chroma-id",
            String(selectedChromaData.id)
          );

          log.debug(
            `[FormsWheel] Requested button icon for chroma selection button: ${iconPath} for chroma ${selectedChromaData.id} (chromaIdChanged: ${chromaIdChanged})`
          );

          // Only show placeholder if there's no existing icon
          // If we're switching between chromas, keep the old icon visible until the new one loads (prevents flicker)
          const existingBgImage = content.style.backgroundImage;
          const hasExistingIcon =
            existingBgImage &&
            existingBgImage !== "none" &&
            existingBgImage !== "";

          if (!hasExistingIcon) {
            // No existing icon - show placeholder
            content.style.setProperty("background", "", "important");
            content.style.setProperty("background-image", "", "important");
            content.style.setProperty(
              "background-color",
              "#1e2328",
              "important"
            );
            content.style.setProperty(
              "background-size",
              "contain",
              "important"
            );
            content.style.setProperty(
              "background-position",
              "center",
              "important"
            );
            content.style.setProperty(
              "background-repeat",
              "no-repeat",
              "important"
            );
            log.debug(
              `[FormsWheel] Button icon: using placeholder until Python serves ${iconPath}`
            );
          } else {
            // Existing icon present - keep it visible while new one loads (prevents flicker)
            log.debug(
              `[FormsWheel] Button icon: keeping existing icon visible while new icon loads for chroma ${selectedChromaData.id}`
            );
          }
        } else {
          // Icon already loaded and request already pending for this chroma - keep it
          log.debug(
            `[FormsWheel] Button icon already loaded and pending for chroma ${selectedChromaData.id}, keeping existing icon`
          );
        }
        return;
      }

      // Check if this is the default chroma (no color or name is "Default")
      // BUT: For Elementalist Lux, Spirit Blossom Morgana, and HOL chromas, even the "Default" button should show its icon, not the generic default
      // Note: Mordekaiser removed - handled by ROSE-FormsWheel
      const isElementalistLux =
        selectedChromaData &&
        (selectedChromaData.id === 99007 ||
          (selectedChromaData.id >= 99991 && selectedChromaData.id <= 99999));
      const isMorgana =
        selectedChromaData &&
        (selectedChromaData.id === 25080 || selectedChromaData.id === 25999);
      const isKaisa =
        selectedChromaData &&
        (selectedChromaData.id === 145070 || selectedChromaData.id === 145071 || selectedChromaData.id === 145999);
      const isHolChroma =
        selectedChromaData &&
        (selectedChromaData.id === 103085 ||
          selectedChromaData.id === 103086 ||
          selectedChromaData.id === 103087);
      const isDefault =
        !selectedChromaData ||
        (selectedChromaData.name === "Default" &&
          !isElementalistLux &&
          !isMorgana &&
          !isKaisa &&
          !isHolChroma) ||
        (!selectedChromaData.primaryColor &&
          !isElementalistLux &&
          !isMorgana &&
          !isKaisa &&
          !isHolChroma) ||
        selectedChromaData.id === 0;

      if (isDefault) {
        // Default chroma: use the original button-chroma.png image
        // Use setProperty with !important to override CSS rules
        content.style.setProperty(
          "background",
          "url(/fe/lol-champ-select/images/config/button-chroma.png) no-repeat",
          "important"
        );
        content.style.setProperty("background-size", "contain", "important");
        content.style.setProperty(
          "background-color",
          "transparent",
          "important"
        );
        content.style.setProperty(
          "background-image",
          "url(/fe/lol-champ-select/images/config/button-chroma.png)",
          "important"
        );
        log.debug(`[FormsWheel] Button color: default (no color)`);
      } else {
        // Chroma with color: use the chroma color as background
        const color = selectedChromaData.primaryColor.startsWith("#")
          ? selectedChromaData.primaryColor
          : `#${selectedChromaData.primaryColor}`;
        // Use setProperty with !important to override CSS rules
        content.style.setProperty("background", color, "important");
        content.style.setProperty("background-color", color, "important");
        content.style.setProperty("background-image", "none", "important");
        content.style.setProperty("background-size", "cover", "important");
        log.debug(
          `[FormsWheel] Button color updated: ${color} (chroma ID: ${selectedChromaData.id}, name: ${selectedChromaData.name})`
        );
      }
    });
  }

  function selectChroma(
    chroma,
    allChromas,
    chromaImage,
    clickedButton,
    scrollable
  ) {
    log.info(
      `[FormsWheel] selectChroma called for: ${chroma.name} (ID: ${chroma.id})`
    );

    // Update selected state
    allChromas.forEach((c) => {
      c.selected = c.id === chroma.id;
    });

    // Update UI
    scrollable.querySelectorAll(".chroma-skin-button").forEach((btn) => {
      btn.classList.remove("selected");
    });
    clickedButton.classList.add("selected");

    // Update preview image using the shared function
    updateChromaPreview(chroma, chromaImage);

    // Update selectedChromaData immediately with the chroma we just selected
    // This ensures the button color updates right away, even before Python responds
    selectedChromaData = {
      id: chroma.id,
      primaryColor:
        chroma.primaryColor || chroma.colors?.[1] || chroma.colors?.[0] || null,
      colors: chroma.colors || [],
      name: chroma.name,
      buttonIconPath: chroma.buttonIconPath || null, // Include button icon path for Elementalist Lux forms and HOL chromas
    };

    // Update button color immediately
    updateChromaButtonColor();

    // Note: selectedChromaData will be updated again by Python's chroma-state message
    // if Python provides better/more accurate data

    // Send chroma selection to Python thread (like SkinMonitor does)
    const championId = skinMonitorState?.championId || null;
    const baseSkinId = skinMonitorState?.skinId || null;
    log.info(
      `[FormsWheel] Sending chroma selection to Python: ID=${chroma.id}, championId=${championId}, baseSkinId=${baseSkinId}`
    );
    if (bridge) bridge.send({
      type: "chroma-selection",
      skinId: chroma.id,
      chromaId: chroma.id,
      chromaName: chroma.name,
      championId: championId,
      baseSkinId: baseSkinId,
      primaryColor: selectedChromaData.primaryColor,
      timestamp: Date.now(),
    });

    // Try to set the skin via API
    if (window.fetch) {
      fetch("/lol-champ-select/v1/session/my-selection", {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          selectedSkinId: chroma.id,
        }),
      })
        .then(() => {
          log.debug(`Successfully set chroma: ${chroma.id}`);
        })
        .catch((err) => {
          log.warn(`Failed to set chroma: ${chroma.id}`, err);
        });
    } else {
      log.debug(`Selected chroma: ${chroma.id} (API call not available)`);
    }

    // Close the panel after selection (matching official client behavior)
    const panel = document.getElementById(PANEL_ID);
    if (panel) {
      log.info("[FormsWheel] Closing panel after chroma selection");
      panel.remove();
    }
  }

  function toggleChromaPanel(buttonElement, skinItem) {
    log.info("[FormsWheel] toggleChromaPanel called");

    // Check if chroma button exists and is visible before allowing panel to open
    if (!buttonElement) {
      log.warn(
        "[FormsWheel] Cannot open panel: chroma button element not provided"
      );
      return;
    }

    // Verify the button is actually visible and has chromas
    const buttonVisible =
      buttonElement.offsetParent !== null &&
      buttonElement.style.display !== "none" &&
      buttonElement.style.opacity !== "0";
    const hasChromas =
      skinMonitorState?.hasChromas ||
      buttonElement._luLastVisibilityState === true;

    if (!buttonVisible || !hasChromas) {
      log.warn(
        "[FormsWheel] Cannot open panel: chroma button not visible or no chromas"
      );
      return;
    }

    const existingPanel = document.getElementById(PANEL_ID);
    if (existingPanel) {
      log.info("[FormsWheel] Closing existing panel");
      existingPanel.remove();
      return;
    }

    log.info("[FormsWheel] Opening chroma panel...");
    log.debug("Extracting skin data...");
    let skinData = getCachedSkinData(skinItem);

    // If we couldn't extract skin data from DOM, use the skin state data we have
    if (!skinData || !extractSkinIdFromData(skinData)) {
      log.info(
        "[FormsWheel] Could not extract skin data from DOM, using skin state data"
      );
      if (skinMonitorState && skinMonitorState.skinId) {
        skinData = {
          id: skinMonitorState.skinId,
          skinId: skinMonitorState.skinId,
          championId: skinMonitorState.championId,
          name: skinMonitorState.name,
        };
        log.info("[FormsWheel] Using skin state data:", {
          skinId: skinData.skinId,
          championId: skinData.championId,
          name: skinData.name,
        });
      } else {
        log.warn(
          "[FormsWheel] Could not extract skin data from skin item and no skin state available",
          skinItem
        );
        // Try to create panel with minimal data anyway
        const fallbackData = {
          name: "Champion",
          skinId: 0,
          championId: 0,
        };
        const fallbackChromas = [
          {
            id: 0,
            name: "Default",
            imagePath: "",
            selected: true,
            locked: false,
          },
        ];
        createChromaPanel(fallbackData, fallbackChromas, buttonElement);
        return;
      }
    } else {
      log.info("[FormsWheel] Skin data extracted from DOM:", {
        skinId: extractSkinIdFromData(skinData),
        championId: skinData?.championId,
        name: skinData?.name,
      });
    }

    log.info("[FormsWheel] Getting chroma data...");

    // Ensure champion data is fetched before getting chromas
    const championId = getChampionIdFromContext(
      skinData,
      extractSkinIdFromData(skinData),
      skinItem
    );
    log.info(
      `[FormsWheel] Champion ID: ${championId}, Cache has data: ${championId ? championSkinCache.has(championId) : "N/A"
      }`
    );
    if (championId) {
      // Check if fetch is already in progress
      const fetchInProgress = pendingChampionRequests.has(championId);

      if (!championSkinCache.has(championId)) {
        if (fetchInProgress) {
          log.debug(
            `Champion ${championId} data fetch already in progress, waiting...`
          );
          // Wait for existing fetch to complete
          pendingChampionRequests
            .get(championId)
            .then(() => {
              const chromas = getChromaData(skinData);
              log.debug("Chromas found after waiting for fetch:", chromas);
              if (chromas.length === 0) {
                log.warn(
                  "No chromas found after fetch completed, using fallback"
                );
                const defaultChromas = [
                  {
                    id: skinData.skinId || skinData.id || 0,
                    name: "Default",
                    imagePath: "",
                    selected: true,
                    locked: false,
                  },
                ];
                createChromaPanel(skinData, defaultChromas, buttonElement);
                return;
              }
              createChromaPanel(skinData, chromas, buttonElement);
            })
            .catch((err) => {
              log.warn(
                "Failed while waiting for champion data, using available chromas",
                err
              );
              const chromas = getChromaData(skinData);
              if (chromas.length === 0) {
                const defaultChromas = [
                  {
                    id: skinData.skinId || skinData.id || 0,
                    name: "Default",
                    imagePath: "",
                    selected: true,
                    locked: false,
                  },
                ];
                createChromaPanel(skinData, defaultChromas, buttonElement);
              } else {
                createChromaPanel(skinData, chromas, buttonElement);
              }
            });
          return; // Exit early, will create panel in promise callback
        }

        log.debug(`Champion ${championId} data not cached, fetching...`);
        fetchChampionSkinData(championId)
          .then(() => {
            // Retry getting chromas after fetch completes
            const chromas = getChromaData(skinData);
            log.debug("Chromas found after fetch:", chromas);
            if (chromas.length === 0) {
              log.warn(
                "No chromas found for this skin after fetch, creating with default"
              );
              const defaultChromas = [
                {
                  id: skinData.skinId || skinData.id || 0,
                  name: "Default",
                  imagePath: "",
                  selected: true,
                  locked: false,
                },
              ];
              createChromaPanel(skinData, defaultChromas, buttonElement);
              return;
            }
            log.debug("Creating chroma panel with fetched chromas...");
            createChromaPanel(skinData, chromas, buttonElement);
            log.info("Chroma panel opened successfully");
          })
          .catch((err) => {
            log.warn(
              "Failed to fetch champion data, using available chromas",
              err
            );
            const chromas = getChromaData(skinData);
            if (chromas.length === 0) {
              const defaultChromas = [
                {
                  id: skinData.skinId || skinData.id || 0,
                  name: "Default",
                  imagePath: "",
                  selected: true,
                  locked: false,
                },
              ];
              createChromaPanel(skinData, defaultChromas, buttonElement);
            } else {
              createChromaPanel(skinData, chromas, buttonElement);
            }
          });
        return; // Exit early, will create panel in promise callback
      }
    }

    const chromas = getChromaData(skinData);
    log.info(`[FormsWheel] Chromas found: ${chromas.length} total`);
    log.info(
      "[FormsWheel] Chroma details:",
      chromas.map((c) => ({
        id: c.id,
        name: c.name,
        hasColor: !!c.primaryColor,
        color: c.primaryColor,
        hasImage: !!c.imagePath,
        locked: c.locked,
      }))
    );

    if (chromas.length === 0) {
      log.warn(
        "[FormsWheel] No chromas found for this skin, creating with default"
      );
      // Create at least one default chroma
      const defaultChromas = [
        {
          id: skinData.skinId || skinData.id || 0,
          name: "Default",
          imagePath: "",
          selected: true,
          locked: false,
        },
      ];
      createChromaPanel(skinData, defaultChromas, buttonElement);
      return;
    }

    log.info(
      `[FormsWheel] Creating chroma panel with ${chromas.length} chromas...`
    );
    createChromaPanel(skinData, chromas, buttonElement);
    log.info(
      `[FormsWheel] Chroma panel opened successfully with ${chromas.length} chroma buttons`
    );
  }

  function setupObserver() {
    const observer = new MutationObserver(() => {
      scanSkinSelection();
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["class"],
    });

    // Periodic scan as safety net
    const intervalId = setInterval(scanSkinSelection, 500);

    // Return cleanup function
    return () => {
      observer.disconnect();
      clearInterval(intervalId);
    };
  }

  function subscribeToSkinMonitor() {
    if (typeof window === "undefined") {
      return;
    }

    if (window.__roseSkinState) {
      skinMonitorState = window.__roseSkinState;

      // Proactively fetch champion data if initial state has chromas
      if (
        skinMonitorState &&
        skinMonitorState.hasChromas &&
        skinMonitorState.championId &&
        skinMonitorState.skinId
      ) {
        const championId = skinMonitorState.championId;
        if (!championSkinCache.has(championId)) {
          log.info(
            `[FormsWheel] Proactively fetching champion ${championId} data for initial skin ${skinMonitorState.skinId} with chromas`
          );
          fetchChampionSkinData(championId)
            .then(() => {
              log.info(
                `[FormsWheel] Successfully fetched champion ${championId} data (initial)`
              );
            })
            .catch((err) => {
              log.warn(
                `[FormsWheel] Failed to proactively fetch champion ${championId} data (initial)`,
                err
              );
            });
        } else {
          log.info(
            `[FormsWheel] Champion ${championId} data already cached (initial), skipping fetch`
          );
        }
      }
    }

    try {
      scanSkinSelection();
    } catch (e) {
      log.debug("Initial scan after skin state preload failed", e);
    }

    window.addEventListener("lu-skin-monitor-state", (event) => {
      const detail = event?.detail;
      emitBridgeLog("skin_state_update", detail || {});
      const prevState = skinMonitorState;
      skinMonitorState = detail || null;

      // Reset selected chroma data when skin changes (not just chroma selection)
      if (prevState && prevState.skinId !== detail?.skinId) {
        selectedChromaData = null;
        updateChromaButtonColor(); // Reset button to default image
      }

      // Proactively fetch champion data when a skin with chromas is detected
      if (detail && detail.hasChromas && detail.championId && detail.skinId) {
        const championId = detail.championId;
        const skinId = detail.skinId;

        // Only fetch if champion data isn't cached yet, or if skin changed
        const shouldFetch =
          !championSkinCache.has(championId) ||
          (prevState && prevState.skinId !== skinId);

        if (shouldFetch) {
          log.info(
            `[FormsWheel] Proactively fetching champion ${championId} data for skin ${skinId} with chromas`
          );
          fetchChampionSkinData(championId)
            .then(() => {
              log.info(
                `[FormsWheel] Successfully fetched champion ${championId} data`
              );
              // Trigger a rescan to update button visibility if needed
              try {
                scanSkinSelection();
              } catch (e) {
                log.debug("scanSkinSelection failed after champion fetch", e);
              }
            })
            .catch((err) => {
              log.warn(
                `[FormsWheel] Failed to proactively fetch champion ${championId} data`,
                err
              );
            });
        } else {
          log.info(
            `[FormsWheel] Champion ${championId} data already cached, skipping proactive fetch`
          );
        }
      }

      try {
        scanSkinSelection();
      } catch (e) {
        log.debug("scanSkinSelection failed after state update", e);
      }
    });
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
      // Wait for shared bridge API
      bridge = await waitForBridge();

      // Subscribe to bridge message types
      bridge.subscribe("chroma-state", handleChromaStateUpdate);
      bridge.subscribe("local-preview-url", handleLocalPreviewUrl);
      bridge.subscribe("local-asset-url", handleLocalAssetUrl);
      bridge.subscribe("champion-locked", handleChampionLocked);
      bridge.subscribe("phase-change", handlePhaseChangeFromPython);

      // Request hover button assets on every (re)connect
      bridge.onReady(() => {
        if (!hoverButtonNormalUrl) {
          bridge.send({ type: "request-local-asset", assetPath: HOVER_BUTTON_ASSET, timestamp: Date.now() });
        }
        if (!hoverButtonHoverUrl) {
          bridge.send({ type: "request-local-asset", assetPath: HOVER_BUTTON_HOVER_ASSET, timestamp: Date.now() });
        }
      });

      subscribeToSkinMonitor();
      injectCSS();
      scanSkinSelection();
      setupObserver();
      log.info("fake chroma button creation active");
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
