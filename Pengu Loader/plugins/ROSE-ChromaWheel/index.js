/**
 * @name Rose-ChromaWheel
 * @author Rose Team
 * @description Chroma wheel for Pengu Loader
 * @link https://github.com/Alban1911/Rose-ChromaWheel
 */
(function createFakeChromaButton() {
  const LOG_PREFIX = "[LU-ChromaButton]";
  console.log(`${LOG_PREFIX} JS Loaded`);
  const BUTTON_CLASS = "lu-chroma-button";
  const BUTTON_SELECTOR = `.${BUTTON_CLASS}`;
  const PANEL_CLASS = "lu-chroma-panel";
  const PANEL_ID = "lu-chroma-panel-container";
  const SKIN_SELECTORS = [
    ".skin-name-text", // Classic Champ Select
    ".skin-name", // Swiftplay lobby
  ];
  const SPECIAL_BASE_SKIN_IDS = new Set([99007]); // 82054, 145070, 103085, 25080 removed - handled by ROSE-FormsWheel
  const SPECIAL_CHROMA_SKIN_IDS = new Set([100001, 88888]); // 145071, 103086, 103087 removed - handled by ROSE-FormsWheel
  // HOL skins handled by ROSE-FormsWheel (should not show ChromaWheel buttons)
  const HOL_SKIN_IDS = new Set([145070, 145071, 103085, 103086, 103087]);
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

  // Shared bridge API (provided by ROSE-Bridge plugin)
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
          console.debug(
            "[ChromaWheel] Failed to play chroma click sound:",
            err
          );
        }
      });
    } catch (err) {
      if (window?.console) {
        console.debug(
          "[ChromaWheel] Error initializing chroma click sound:",
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
      height: 25px;
      left: 50%;
      position: absolute;
      transform: translateX(-50%) translateY(50%);
      width: 25px;
      z-index: 10;
    }

    .${BUTTON_CLASS}[data-hidden],
    .${BUTTON_CLASS}[data-hidden] * {
      pointer-events: none !important;
      cursor: default !important;
      visibility: hidden !important;
    }

    .${BUTTON_CLASS} .outer-mask {
      pointer-events: auto;
      -webkit-user-select: none;
      list-style-type: none;
      cursor: pointer;
      border-radius: 50%;
      box-shadow: 0 0 4px 1px rgba(1,10,19,.25);
      box-sizing: border-box;
      height: 100%;
      overflow: hidden;
      position: relative;
    }

    .${BUTTON_CLASS} .frame-color {
      --champion-preview-hover-animation-percentage: 0%;
      --column-height: 95px;
      --font-display: "LoL Display","Times New Roman",Times,Baskerville,Georgia,serif;
      --font-body: "LoL Body",Arial,"Helvetica Neue",Helvetica,sans-serif;
      pointer-events: auto;
      -webkit-user-select: none;
      list-style-type: none;
      cursor: default;
      background-image: linear-gradient(0deg,#695625 0,#a9852d 23%,#b88d35 93%,#c8aa6e);
      box-sizing: border-box;
      height: 100%;
      overflow: hidden;
      width: 100%;
      padding: 2px;
    }

    .${BUTTON_CLASS} .content {
      pointer-events: auto;
      -webkit-user-select: none;
      list-style-type: none;
      cursor: pointer;
      display: block;
      background: url(/fe/lol-champ-select/images/config/button-chroma.png) no-repeat;
      background-size: contain;
      border: 2px solid #010a13;
      border-radius: 50%;
      height: 16px;
      margin: 1px;
      width: 16px;
    }

    .${BUTTON_CLASS} .inner-mask {
      -webkit-user-select: none;
      list-style-type: none;
      cursor: default;
      border-radius: 50%;
      box-sizing: border-box;
      overflow: hidden;
      pointer-events: none;
      position: absolute;
      box-shadow: inset 0 0 4px 4px rgba(0,0,0,.75);
      width: calc(100% - 4px);
      height: calc(100% - 4px);
      left: 2px;
      top: 2px;
    }

    /* Ensure thumbnail-wrapper has relative positioning for absolute button */
    .thumbnail-wrapper.active-skin {
      position: relative;
    }

    .thumbnail-wrapper .${BUTTON_CLASS} {
      direction: ltr;
      background: transparent;
      cursor: pointer;
      height: 28px;
      width: 28px;
      /* Keep the same positioning as base button for consistency */
      bottom: 1px;
      left: 50%;
      position: absolute;
      transform: translateX(-50%) translateY(50%);
      z-index: 10;
    }

    /* Show outer-mask in Swiftplay so .content is visible */
    .thumbnail-wrapper .${BUTTON_CLASS} .outer-mask {
      display: block;
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
      if (bridge) {
        bridge.send({
          type: "chroma-log",
          source: "LU-ChromaWheel",
          event,
          data,
          timestamp: Date.now(),
        });
      }
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
      `[ChromaWheel] Received local preview URL: ${url} for chroma ${chromaId}`
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
      log.debug(`[ChromaWheel] Applied local preview URL to chroma image`);
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
      `[ChromaWheel] Received local asset URL: ${url} for chroma ${chromaId}`
    );

    // Special handling: ARAM background image for the panel
    if (assetPath === ARAM_BACKGROUND_ASSET_PATH && url) {
      aramBackgroundImageUrl = url;
      aramBackgroundRequestPending = false;

      if (currentChromaInfoElement) {
        currentChromaInfoElement.style.backgroundImage = `url('${url}')`;
        log.debug(
          "[ChromaWheel] Applied ARAM background image to chroma panel"
        );
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
        `[ChromaWheel] Applied local asset URL to button icon for chroma ${chromaId}`
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
      `[ChromaWheel] Received chroma state from Python: selectedChromaId=${data.selectedChromaId}, chromaColor=${data.chromaColor}`
    );

    // Note: isMordekaiser and isMorgana are global functions defined elsewhere
    // HOL chromas (Kai'Sa and Ahri) are now handled by ROSE-FormsWheel

    // Helper to get buttonIconPath for Elementalist Lux forms
    const getButtonIconPathForElementalist = (chromaId) => {
      if (chromaId === 99007 || (chromaId >= 99991 && chromaId <= 99999)) {
        return getElementalistButtonIconPath(chromaId);
      }
      return null;
    };

    // Helper to get buttonIconPath for Sahn Uzal Mordekaiser forms
    // Note: Mordekaiser handling removed - now handled by ROSE-FormsWheel plugin
    const getButtonIconPathForMordekaiser = (chromaId) => {
      // This function is kept for compatibility but should not be used
      // Mordekaiser is now handled by ROSE-FormsWheel
      return null;
    };

    // Helper to get buttonIconPath for Spirit Blossom Morgana forms
    // Note: Morgana handling removed - now handled by ROSE-FormsWheel plugin
    const getButtonIconPathForMorgana = (chromaId) => {
      // This function is kept for compatibility but should not be used
      // Morgana is now handled by ROSE-FormsWheel
      return null;
    };

    // Helper to get buttonIconPath for HOL chromas - removed, handled by ROSE-FormsWheel

    // Update selectedChromaData based on Python state
    if (data.selectedChromaId && data.chromaColor) {
      // Python provided the color directly
      const buttonIconPath =
        getButtonIconPathForElementalist(data.selectedChromaId) ||
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
          `[ChromaWheel] Found base skin ID ${baseSkinId} for chroma ${data.currentSkinId} from chromaParentMap`
        );
      }

      // Also check if selectedChromaId itself is in the map (in case currentSkinId wasn't set correctly)
      if (!baseSkinId && chromaParentMap.has(data.selectedChromaId)) {
        baseSkinId = chromaParentMap.get(data.selectedChromaId);
        log.debug(
          `[ChromaWheel] Found base skin ID ${baseSkinId} for selected chroma ${data.selectedChromaId} from chromaParentMap`
        );
      }

      // Check if this is Elementalist Lux - if so, use local data
      if (
        data.selectedChromaId === 99007 ||
        (data.selectedChromaId >= 99991 && data.selectedChromaId <= 99999)
      ) {
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
          `[ChromaWheel] Elementalist Lux form detected: ${data.selectedChromaId}, buttonIconPath: ${selectedChromaData.buttonIconPath}`
        );
        // Note: Mordekaiser (82054) and Spirit Blossom Morgana (25080) handling removed - now handled by ROSE-FormsWheel plugin
        // HOL chromas (Kai'Sa and Ahri) are now handled by ROSE-FormsWheel - skip here
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
            `[ChromaWheel] Looking for chroma ${data.selectedChromaId
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
            `[ChromaWheel] Found chroma color from cache: ${foundChroma.primaryColor}`
          );
        } else {
          // Chroma selected but no color available - try to keep existing selectedChromaData if it matches
          if (
            selectedChromaData &&
            selectedChromaData.id === data.selectedChromaId
          ) {
            log.debug(
              `[ChromaWheel] Keeping existing selectedChromaData for chroma ${data.selectedChromaId}`
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
              `[ChromaWheel] Could not find chroma color for ${data.selectedChromaId}, using default`
            );
          }
        }
      }
    } else {
      // Default/base chroma selected
      // Check if currentSkinId is Elementalist Lux base
      let buttonIconPath = null;
      if (
        data.currentSkinId === 99007 ||
        (data.currentSkinId >= 99991 && data.currentSkinId <= 99999)
      ) {
        buttonIconPath = getElementalistButtonIconPath(data.currentSkinId);
      }
      // Note: Mordekaiser (82054), Spirit Blossom Morgana (25080), and HOL chromas (Kai'Sa and Ahri) are now handled by ROSE-FormsWheel - skip here

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
        // Leaving champ select / finalization – clear flag
        isAramFromPython = false;
      }
    } catch (e) {
      // Fail silently – fallback to Ember-based detection
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

    log.debug("[ChromaWheel] Requesting ARAM background image from Python", {
      assetPath: ARAM_BACKGROUND_ASSET_PATH,
    });

    if (bridge) {
      bridge.send(payload);
    } else {
      aramBackgroundRequestPending = false;
      log.debug("[ChromaWheel] Bridge not available for ARAM background request");
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
    error: (msg, extra) => {
      console.error(`${LOG_PREFIX} ${msg}`, extra ?? "");
      emitBridgeLog("error", { message: msg, data: extra });
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

  // HOL chroma functions removed - now handled by ROSE-FormsWheel

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
  // Path: assets/morgana_buttons/{form_id}.png
  function getMorganaButtonIconPath(formId) {
    // Request icon path from Python via bridge
    // Python will return the local file path or serve it via HTTP
    // For now, construct the expected path structure
    const path = `local-asset://morgana_buttons/${formId}.png`;
    return path;
  }

  // getHolButtonIconPath removed - now handled by ROSE-FormsWheel

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
    const styleId = "lu-chroma-button-css";
    if (document.getElementById(styleId)) {
      return;
    }

    const styleTag = document.createElement("style");
    styleTag.id = styleId;
    styleTag.textContent = CSS_RULES;
    document.head.appendChild(styleTag);
    log.debug("injected CSS rules");
  }

  function createFakeButton() {
    const button = document.createElement("div");
    button.className = BUTTON_CLASS;

    const outerMask = document.createElement("div");
    outerMask.className = "outer-mask interactive";

    const frameColor = document.createElement("div");
    frameColor.className = "frame-color";
    frameColor.style.padding = "2px";

    const content = document.createElement("div");
    content.className = "content";
    content.style.background = "";

    const innerMask = document.createElement("div");
    innerMask.className = "inner-mask inner-shadow";
    innerMask.style.width = "calc(100% - 4px)";
    innerMask.style.height = "calc(100% - 4px)";
    innerMask.style.left = "2px";
    innerMask.style.top = "2px";

    frameColor.appendChild(content);
    frameColor.appendChild(innerMask);
    outerMask.appendChild(frameColor);
    button.appendChild(outerMask);

    // Add click handler to open chroma panel
    const handleClick = (e) => {
      e.stopPropagation();
      e.preventDefault();
      log.info("[ChromaWheel] Chroma button clicked!");
      const skinItem = button.closest(
        ".skin-selection-item, .thumbnail-wrapper"
      );
      if (skinItem) {
        // Check if this skin has offset 2 (normal champ select) or is active-skin (Swiftplay)
        const offset = getSkinOffset(skinItem);
        const isSwiftplayActive =
          skinItem.classList.contains("thumbnail-wrapper") &&
          skinItem.classList.contains("active-skin");
        log.info(
          `[ChromaWheel] Skin offset: ${offset}, isSwiftplayActive: ${isSwiftplayActive}`
        );

        if (offset === 2 || isSwiftplayActive) {
          log.info(
            `[ChromaWheel] Found valid skin item (offset=${offset}, swiftplay=${isSwiftplayActive}), opening panel`
          );
          toggleChromaPanel(button, skinItem);
        } else {
          log.info(
            `[ChromaWheel] Skin offset is ${offset}, not 2, and not Swiftplay active. Panel will not open.`
          );
        }
      } else {
        log.warn("[ChromaWheel] Could not find skin item for chroma button");
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
          "[ChromaWheel] Button hidden, closing panel and marking as non-interactive"
        );
        existingPanel.setAttribute("data-no-button", "true");
        existingPanel.style.pointerEvents = "none";
        existingPanel.style.cursor = "default";
        // Remove the panel after a short delay to allow any animations
        setTimeout(() => {
          if (existingPanel.parentNode) {
            existingPanel.remove();
          }
        }, 100);
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
      // Fallback: if we can't determine offset but this skin matches the current skin state, consider it current
      // This helps when offset detection fails but we know this is the selected skin
      if (skinMonitorState?.skinId) {
        const skinData = getCachedSkinData(skinItem);
        const skinId = getSkinIdFromContext(skinData, skinItem);
        if (Number.isFinite(skinId) && skinId === skinMonitorState.skinId) {
          log.debug(
            `[ChromaWheel] Using fallback: skin ${skinId} matches current skin state (offset detection returned ${offset})`
          );
          return true;
        }
      }
    }

    // Thumbnail wrappers (e.g., Swiftplay lobby) typically flag selection via attributes/classes
    if (skinItem.classList.contains("thumbnail-wrapper")) {
      // Check for active-skin class (Swiftplay mode)
      if (skinItem.classList.contains("active-skin")) {
        return true;
      }
      // Check for selected class or aria-selected attribute
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
      `[ChromaWheel] Champion lock state updated: ${championLocked} (was: ${wasLocked})`
    );

    // If champion was unlocked, remove all buttons
    if (!championLocked && wasLocked) {
      log.debug(
        "[ChromaWheel] Champion unlocked - removing all chroma buttons"
      );
      const allButtons = document.querySelectorAll(BUTTON_SELECTOR);
      allButtons.forEach((button) => button.remove());
    } else if (championLocked && !wasLocked) {
      // Champion just locked - scan for buttons
      log.debug("[ChromaWheel] Champion locked - scanning for chroma buttons");
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

    // Don't create button if champion is not locked (except in Swiftplay mode)
    const isSwiftplay =
      skinItem.classList.contains("thumbnail-wrapper") &&
      skinItem.classList.contains("active-skin");
    if (!championLocked && !isSwiftplay) {
      // Remove existing button if champion is not locked (and not Swiftplay)
      const existingButton = skinItem.querySelector(BUTTON_SELECTOR);
      if (existingButton) {
        existingButton.remove();
      }
      return;
    }

    const isCurrent = isCurrentSkinItem(skinItem);
    const currentSkinId = skinMonitorState?.skinId ?? null;

    // Skip HOL skins - they are handled by ROSE-FormsWheel
    if (currentSkinId && HOL_SKIN_IDS.has(currentSkinId)) {
      // Remove existing button if it exists (shouldn't be there, but clean up just in case)
      const existingButton = skinItem.querySelector(BUTTON_SELECTOR);
      if (existingButton) {
        existingButton.remove();
      }
      return;
    }

    const hasChromas = Boolean(
      skinMonitorState?.hasChromas || isSpecialBaseSkin(currentSkinId)
      // Note: Mordekaiser (82054), Spirit Blossom Morgana (25080), and HOL skins removed - handled by ROSE-FormsWheel
    );

    // Check if button already exists
    let existingButton = skinItem.querySelector(BUTTON_SELECTOR);

    // Debug logging for troubleshooting - only log when state changes
    if (isCurrent) {
      const lastLogState = ensureFakeButton._lastLogState;
      const currentLogState = {
        skinId: currentSkinId,
        hasChromas,
        championLocked,
        existingButton: !!existingButton,
      };
      if (
        !lastLogState ||
        lastLogState.skinId !== currentLogState.skinId ||
        lastLogState.hasChromas !== currentLogState.hasChromas ||
        lastLogState.championLocked !== currentLogState.championLocked ||
        lastLogState.existingButton !== currentLogState.existingButton
      ) {
        emitBridgeLog("current_skin_item_found", currentLogState);
        ensureFakeButton._lastLogState = currentLogState;
      }
    }

    if (!isCurrent) {
      if (existingButton) {
        existingButton.remove();
      }
      return;
    }

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
        // (as a sibling to .related, not inside .shared-skin-chroma-modal)
        if (
          skinItem.classList.contains("thumbnail-wrapper") &&
          skinItem.classList.contains("active-skin")
        ) {
          // Always place directly on thumbnail-wrapper for Swiftplay (same as the working case)
          skinItem.appendChild(fakeButton);
          existingButton = fakeButton;
          log.debug(
            `[ChromaWheel] Placed button on Swiftplay thumbnail-wrapper for skin ${currentSkinId}`
          );
        } else {
          // Normal champ select: append directly to skin item
          skinItem.appendChild(fakeButton);
          existingButton = fakeButton;
        }
        log.info(
          `[ChromaWheel] Created chroma button for skin ${currentSkinId} (hasChromas: ${hasChromas})`
        );
        emitBridgeLog("button_created", {
          skinId: currentSkinId,
          hasChromas,
          isSupported: true,
          championLocked: championLocked,
        });
      } else {
        // Only log button exists message when state changes (reduce spam)
        const lastButtonExistsState = ensureFakeButton._lastButtonExistsState;
        if (
          !lastButtonExistsState ||
          lastButtonExistsState.skinId !== currentSkinId ||
          lastButtonExistsState.hasChromas !== hasChromas
        ) {
          log.debug(
            `[ChromaWheel] Button already exists for skin ${currentSkinId}, updating visibility`
          );
          ensureFakeButton._lastButtonExistsState = {
            skinId: currentSkinId,
            hasChromas,
          };
        }
      }

      updateButtonVisibility(existingButton, hasChromas);
    } catch (e) {
      log.warn("Failed to create chroma button", e);
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

    // Debug: Check for current skin item - only log when state changes
    let currentItemFound = false;
    skinItems.forEach((skinItem) => {
      const offset = getSkinOffset(skinItem);
      if (offset === 2) {
        currentItemFound = true;
        // Only log when state changes (skinId or hasChromas)
        const lastFoundState = scanSkinSelection._lastFoundState;
        const currentFoundState = {
          skinId: skinMonitorState?.skinId,
          hasChromas: skinMonitorState?.hasChromas,
          championLocked: championLocked,
        };
        if (
          !lastFoundState ||
          lastFoundState.skinId !== currentFoundState.skinId ||
          lastFoundState.hasChromas !== currentFoundState.hasChromas ||
          lastFoundState.championLocked !== currentFoundState.championLocked
        ) {
          log.debug(
            `[ChromaWheel] Found current skin item with offset 2, hasChromas: ${skinMonitorState?.hasChromas}, championLocked: ${championLocked}`
          );
          scanSkinSelection._lastFoundState = currentFoundState;
        }
      }
      ensureFakeButton(skinItem);
    });

    // Only warn once per state change, with debouncing
    if (!currentItemFound && skinItems.length > 0) {
      const warningKey = `${skinItems.length}-${skinMonitorState?.skinId}`;
      const lastWarning = scanSkinSelection._lastWarning;
      if (lastWarning !== warningKey) {
        log.warn(
          `[ChromaWheel] Warning: No skin item with offset 2 found, but ${skinItems.length} items exist`
        );
        scanSkinSelection._lastWarning = warningKey;
      }
    } else if (currentItemFound) {
      // Reset warning state when item is found
      scanSkinSelection._lastWarning = null;
    }

    thumbnailWrappers.forEach((thumbnailWrapper) => {
      ensureFakeButton(thumbnailWrapper);
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

    // NOTE: Sahn Uzal Mordekaiser (82054) and Spirit Blossom Morgana (25080) removed - now handled by ROSE-FormsWheel plugin
    // Previously these special cases handled Mordekaiser and Morgana forms, but they're now excluded from this plugin

    // SPECIAL CASE: Risen Legend Kai'Sa and Ahri HoL skins are now handled by ROSE-FormsWheel
    // (removed - handled by ROSE-FormsWheel)

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
      `[ChromaWheel] createChromaPanel called with ${chromas.length} chromas`
    );
    log.debug("createChromaPanel details:", {
      skinData,
      chromas,
      buttonElement,
    });

    // Ensure button element exists and is valid before creating panel
    if (!buttonElement) {
      log.warn(
        "[ChromaWheel] Cannot create panel: button element not provided"
      );
      return;
    }

    // Verify button is visible
    const buttonVisible =
      buttonElement.offsetParent !== null &&
      buttonElement.style.display !== "none" &&
      buttonElement.style.opacity !== "0";
    if (!buttonVisible) {
      log.warn("[ChromaWheel] Cannot create panel: button element not visible");
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
          "[ChromaWheel] Using cached ARAM background image for chroma panel"
        );
      } else {
        // Request ARAM background from Python; keep SR background as temporary fallback
        requestAramBackgroundImage();
        log.debug(
          "[ChromaWheel] ARAM mode detected - requesting ARAM background image"
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
    // Prioritize the matched name from Python (skinMonitorState.name) over DOM reading
    // This ensures we use the matched name (e.g., "Talon à l'épée tenace (saphir)") 
    // instead of the input or base skin name
    const displayName =
      skinMonitorState?.name ||
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

      // Check if this is Elementalist Lux form or Sahn Uzal Mordekaiser form (has buttonIconPath)
      if (
        chroma.buttonIconPath &&
        chroma.buttonIconPath.startsWith("local-asset://")
      ) {
        // Elementalist Lux form or Sahn Uzal Mordekaiser form - use local button icon
        // Format: local-asset://elementalist_buttons/{form_id}.png or local-asset://mordekaiser_buttons/{form_id}.png
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
          `[ChromaWheel] Requested local button icon: ${iconPath} for chroma ${chroma.id}`
        );

        // Use placeholder until Python serves the image
        contents.style.background = "";
        contents.style.backgroundImage = "";
        contents.style.backgroundColor = "#1e2328"; // Dark placeholder
        contents.style.backgroundSize = "cover";
        contents.style.backgroundPosition = "center";
        contents.style.backgroundRepeat = "no-repeat";
        log.debug(
          `[ChromaWheel] Button ${index + 1}: ${chroma.name
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
            `[ChromaWheel] Button ${index + 1}: ${chroma.name
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
              `[ChromaWheel] Button ${index + 1}: ${chroma.name
              } with color ${color}`
            );
          } else if (chroma.imagePath) {
            // Fall back to image if no color available
            contents.style.background = `url('${chroma.imagePath}')`;
            contents.style.backgroundSize = "cover";
            contents.style.backgroundPosition = "center";
            contents.style.backgroundRepeat = "no-repeat";
            log.debug(
              `[ChromaWheel] Button ${index + 1}: ${chroma.name} with image ${chroma.imagePath
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
              `[ChromaWheel] Button ${index + 1}: ${chroma.name
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
          `[ChromaWheel] Chroma button clicked: ${chroma.name} (ID: ${chroma.id}, locked: ${chroma.locked})`
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

    log.info(`[ChromaWheel] Created ${buttonCount} chroma buttons in panel`);
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
            `[ChromaWheel] Requested local preview for champion ${championId}, skin ${skinId}, chroma ${chromaId}`
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
    // This works for both normal champ select and Swiftplay mode
    const buttons = document.querySelectorAll(BUTTON_SELECTOR);
    log.debug(
      `[ChromaWheel] updateChromaButtonColor: Found ${buttons.length} button(s) to update`
    );
    buttons.forEach((button) => {
      const content = button.querySelector(".content");
      if (!content) {
        log.debug(
          `[ChromaWheel] Button color update: no .content element found`
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
            `[ChromaWheel] Requested button icon for chroma selection button: ${iconPath} for chroma ${selectedChromaData.id} (chromaIdChanged: ${chromaIdChanged})`
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
              `[ChromaWheel] Button icon: using placeholder until Python serves ${iconPath}`
            );
          } else {
            // Existing icon present - keep it visible while new one loads (prevents flicker)
            log.debug(
              `[ChromaWheel] Button icon: keeping existing icon visible while new icon loads for chroma ${selectedChromaData.id}`
            );
          }
        } else {
          // Icon already loaded and request already pending for this chroma - keep it
          log.debug(
            `[ChromaWheel] Button icon already loaded and pending for chroma ${selectedChromaData.id}, keeping existing icon`
          );
        }
        return;
      }

      // Check if this is the default chroma (no color or name is "Default")
      // BUT: For Elementalist Lux, even the "Default" button should show its icon, not the generic default
      // Note: Mordekaiser (82054), Spirit Blossom Morgana (25080), and HOL chromas are now handled by ROSE-FormsWheel
      const isElementalistLux =
        selectedChromaData &&
        (selectedChromaData.id === 99007 ||
          (selectedChromaData.id >= 99991 && selectedChromaData.id <= 99999));
      // HOL chromas are now handled by ROSE-FormsWheel
      const isDefault =
        !selectedChromaData ||
        (selectedChromaData.name === "Default" && !isElementalistLux) ||
        (!selectedChromaData.primaryColor && !isElementalistLux) ||
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
        log.debug(`[ChromaWheel] Button color: default (no color)`);
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
          `[ChromaWheel] Button color updated: ${color} (chroma ID: ${selectedChromaData.id}, name: ${selectedChromaData.name})`
        );
      }
    });

    // Also update the actual .chroma.icon element in Swiftplay mode (the real chroma button)
    const chromaIcons = document.querySelectorAll(".chroma.icon");
    if (chromaIcons.length > 0) {
      chromaIcons.forEach((chromaIcon) => {
        // Check if this is in an active Swiftplay skin
        const isActiveSwiftplay = chromaIcon.closest(
          ".thumbnail-wrapper.active-skin"
        );
        if (isActiveSwiftplay) {
          const isDefault =
            !selectedChromaData ||
            selectedChromaData.name === "Default" ||
            !selectedChromaData.primaryColor ||
            selectedChromaData.id === 0;

          if (isDefault) {
            // Default chroma: remove selected class and reset background
            chromaIcon.classList.remove("selected");
            chromaIcon.style.setProperty(
              "background",
              "url(/fe/lol-static-assets/images/skin-viewer/icon-chroma-default.png) 0 0 no-repeat",
              "important"
            );
            chromaIcon.style.setProperty(
              "background-size",
              "contain",
              "important"
            );
            chromaIcon.style.setProperty("border", "none", "important");
            chromaIcon.style.setProperty("border-radius", "", "important");
            chromaIcon.style.setProperty("box-shadow", "", "important");
            chromaIcon.style.setProperty("height", "", "important");
            chromaIcon.style.setProperty("width", "", "important");
            log.debug(`[ChromaWheel] Swiftplay .chroma.icon: reset to default`);
          } else {
            // Chroma with color: update with linear gradient and selected styling
            const color = selectedChromaData.primaryColor.startsWith("#")
              ? selectedChromaData.primaryColor
              : `#${selectedChromaData.primaryColor}`;

            // Create linear gradient (135deg, color 0%, color 50%, color 50%, color 100%)
            const gradient = `linear-gradient(135deg, ${color} 0%, ${color} 50%, ${color} 50%, ${color} 100%)`;

            chromaIcon.classList.add("selected");
            chromaIcon.style.setProperty("background", gradient, "important");
            chromaIcon.style.setProperty(
              "border",
              "2px solid #c89b3c",
              "important"
            );
            chromaIcon.style.setProperty("border-radius", "100%", "important");
            chromaIcon.style.setProperty(
              "box-shadow",
              "inset 0 0 4px 4px rgba(0,0,0,.75), inset 0 0 2px 2px rgba(1,10,19,.75)",
              "important"
            );
            chromaIcon.style.setProperty("height", "23px", "important");
            chromaIcon.style.setProperty("width", "23px", "important");

            log.debug(
              `[ChromaWheel] Swiftplay .chroma.icon updated: ${color} (chroma ID: ${selectedChromaData.id})`
            );
          }
        }
      });
    }

    // Log summary - this function updates all buttons (normal champ select and Swiftplay)
    if (buttons.length > 0) {
      const firstButton = buttons[0];
      const isSwiftplay = firstButton.closest(".thumbnail-wrapper.active-skin");
      log.debug(
        `[ChromaWheel] Updated ${buttons.length} button(s) ${isSwiftplay ? "(Swiftplay mode)" : "(normal champ select)"
        }`
      );
    }
  }

  function selectChroma(
    chroma,
    allChromas,
    chromaImage,
    clickedButton,
    scrollable
  ) {
    log.info(
      `[ChromaWheel] selectChroma called for: ${chroma.name} (ID: ${chroma.id})`
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
      `[ChromaWheel] Sending chroma selection to Python: ID=${chroma.id}, championId=${championId}, baseSkinId=${baseSkinId}`
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
      log.info("[ChromaWheel] Closing panel after chroma selection");
      panel.remove();
    }
  }

  function toggleChromaPanel(buttonElement, skinItem) {
    log.info("[ChromaWheel] toggleChromaPanel called");

    // Don't open panel for HOL skins - they are handled by ROSE-FormsWheel
    const currentSkinId = skinMonitorState?.skinId ?? null;
    if (currentSkinId && HOL_SKIN_IDS.has(currentSkinId)) {
      log.debug(`[ChromaWheel] Skipping panel for HOL skin ${currentSkinId} (handled by FormsWheel)`);
      return;
    }

    // Check if chroma button exists and is visible before allowing panel to open
    if (!buttonElement) {
      log.warn(
        "[ChromaWheel] Cannot open panel: chroma button element not provided"
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
        "[ChromaWheel] Cannot open panel: chroma button not visible or no chromas"
      );
      return;
    }

    const existingPanel = document.getElementById(PANEL_ID);
    if (existingPanel) {
      log.info("[ChromaWheel] Closing existing panel");
      existingPanel.remove();
      return;
    }

    log.info("[ChromaWheel] Opening chroma panel...");
    log.debug("Extracting skin data...");
    let skinData = getCachedSkinData(skinItem);

    // If we couldn't extract skin data from DOM, use the skin state data we have
    if (!skinData || !extractSkinIdFromData(skinData)) {
      log.info(
        "[ChromaWheel] Could not extract skin data from DOM, using skin state data"
      );
      if (skinMonitorState && skinMonitorState.skinId) {
        skinData = {
          id: skinMonitorState.skinId,
          skinId: skinMonitorState.skinId,
          championId: skinMonitorState.championId,
          name: skinMonitorState.name,
        };
        log.info("[ChromaWheel] Using skin state data:", {
          skinId: skinData.skinId,
          championId: skinData.championId,
          name: skinData.name,
        });
      } else {
        log.warn(
          "[ChromaWheel] Could not extract skin data from skin item and no skin state available",
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
      log.info("[ChromaWheel] Skin data extracted from DOM:", {
        skinId: extractSkinIdFromData(skinData),
        championId: skinData?.championId,
        name: skinData?.name,
      });
    }

    log.info("[ChromaWheel] Getting chroma data...");

    // Ensure champion data is fetched before getting chromas
    const championId = getChampionIdFromContext(
      skinData,
      extractSkinIdFromData(skinData),
      skinItem
    );
    log.info(
      `[ChromaWheel] Champion ID: ${championId}, Cache has data: ${championId ? championSkinCache.has(championId) : "N/A"
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
    log.info(`[ChromaWheel] Chromas found: ${chromas.length} total`);
    log.info(
      "[ChromaWheel] Chroma details:",
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
        "[ChromaWheel] No chromas found for this skin, creating with default"
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
      `[ChromaWheel] Creating chroma panel with ${chromas.length} chromas...`
    );
    createChromaPanel(skinData, chromas, buttonElement);
    log.info(
      `[ChromaWheel] Chroma panel opened successfully with ${chromas.length} chroma buttons`
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
            `[ChromaWheel] Proactively fetching champion ${championId} data for initial skin ${skinMonitorState.skinId} with chromas`
          );
          fetchChampionSkinData(championId)
            .then(() => {
              log.info(
                `[ChromaWheel] Successfully fetched champion ${championId} data (initial)`
              );
            })
            .catch((err) => {
              log.warn(
                `[ChromaWheel] Failed to proactively fetch champion ${championId} data (initial)`,
                err
              );
            });
        } else {
          log.info(
            `[ChromaWheel] Champion ${championId} data already cached (initial), skipping fetch`
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
            `[ChromaWheel] Proactively fetching champion ${championId} data for skin ${skinId} with chromas`
          );
          fetchChampionSkinData(championId)
            .then(() => {
              log.info(
                `[ChromaWheel] Successfully fetched champion ${championId} data`
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
                `[ChromaWheel] Failed to proactively fetch champion ${championId} data`,
                err
              );
            });
        } else {
          log.info(
            `[ChromaWheel] Champion ${championId} data already cached, skipping proactive fetch`
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
      // Wait for the shared bridge API
      bridge = await waitForBridge();

      // Subscribe to bridge message types
      bridge.subscribe("chroma-state", handleChromaStateUpdate);
      bridge.subscribe("local-preview-url", handleLocalPreviewUrl);
      bridge.subscribe("local-asset-url", handleLocalAssetUrl);
      bridge.subscribe("champion-locked", handleChampionLocked);
      bridge.subscribe("phase-change", handlePhaseChangeFromPython);

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
  } else if (document.readyState === "loading") {
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
