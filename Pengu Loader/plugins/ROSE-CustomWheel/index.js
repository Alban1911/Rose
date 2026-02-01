/**
 * @name ROSE-CustomWheel
 * @author Rose Team
 * @description Custom mod wheel for Pengu Loader - displays installed mods for hovered skins
 * @link https://github.com/Alban1911/ROSE-CustomWheel
 */
(function createCustomWheel() {
  const LOG_PREFIX = "[ROSE-CustomWheel]";
  console.log(`${LOG_PREFIX} JS Loaded`);
  const BUTTON_CLASS = "lu-chroma-button";
  const BUTTON_SELECTOR = `.${BUTTON_CLASS}`;
  const PANEL_CLASS = "lu-chroma-panel";
  const PANEL_ID = "rose-custom-wheel-panel-container";
  const REQUEST_TYPE = "request-skin-mods";
  const EVENT_SKIN_STATE = "lu-skin-monitor-state";

  let isOpen = false;
  let panel = null;
  let button = null;
  let championSelectRoot = null;
  let championSelectObserver = null;
  let championLocked = false;
  let currentSkinData = null;
  let selectedModId = null; // Track which mod is currently selected
  let selectedModSkinId = null; // Track which skin the selected mod belongs to
  let activeTab = "skins"; // Current active tab: "skins", "maps", "fonts", "announcers", "others"
  let selectedMapId = null;
  let selectedFontId = null;
  let selectedAnnouncerId = null;
  // Per-category multi-selection (UI / Voiceover / Loading Screen / VFX / SFX / Others).
  // These are first-class categories in the UI; they just share the same list rendering logic.
  let selectedCategoryIds = Object.create(null);
  let lastChampionSelectSession = null; // Track current champ select session
  let isFirstOpenInSession = true; // Track if this is first open in current session
  let lastCategoryModsById = {}; // Cache per category id (ui/voiceover/loading_screen/vfx/sfx/others)
  let emittedHistoricSelectionKeys = new Set(); // Avoid re-emitting historic selections across category responses
  let rightPaneMode = "summary"; // "summary" | "picker"

  const OTHER_CATEGORY_TABS = [
    { id: "ui", label: "UI", prefixes: ["ui/"] },
    { id: "voiceover", label: "Voiceover", prefixes: ["voiceover/", "vo/"] },
    { id: "loading_screen", label: "Loading Screen", prefixes: ["loading_screen/", "loading-screen/", "loading screen/"] },
    { id: "vfx", label: "VFX", prefixes: ["vfx/"] },
    { id: "sfx", label: "SFX", prefixes: ["sfx/"] },
    { id: "others", label: "Others", prefixes: [] }, // fallback bucket
  ];

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

  const SUMMARY_TABS = [
    { id: "skins", label: "Skins" },
    { id: "maps", label: "Maps" },
    { id: "fonts", label: "Fonts" },
    { id: "announcers", label: "Announcers" },
    ...OTHER_CATEGORY_TABS.map((t) => ({ id: t.id, label: t.label })),
  ];

  const SUMMARY_ICONS = {
    skins: '<svg viewBox="0 0 24 24"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
    maps: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>',
    fonts: '<svg viewBox="0 0 24 24"><polyline points="4 7 4 4 20 4 20 7"/><line x1="9" y1="20" x2="15" y2="20"/><line x1="12" y1="4" x2="12" y2="20"/></svg>',
    announcers: '<svg viewBox="0 0 24 24"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>',
    ui: '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>',
    voiceover: '<svg viewBox="0 0 24 24"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>',
    loading_screen: '<svg viewBox="0 0 24 24"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>',
    vfx: '<svg viewBox="0 0 24 24"><path d="M12 3l1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5L12 3z"/><path d="M19 13l.75 2.25L22 16l-2.25.75L19 19l-.75-2.25L16 16l2.25-.75L19 13z"/><path d="M5 17l.75 2.25L8 20l-2.25.75L5 23l-.75-2.25L2 20l2.25-.75L5 17z"/></svg>',
    sfx: '<svg viewBox="0 0 24 24"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>',
    others: '<svg viewBox="0 0 24 24"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>',
  };

  function normalizePathLike(value) {
    return String(value || "").replace(/\\/g, "/").trim().toLowerCase();
  }

  function getSelectedIdsForCategory(categoryId) {
    const key = String(categoryId || "").trim();
    if (!key) return [];
    if (!Array.isArray(selectedCategoryIds[key])) {
      selectedCategoryIds[key] = [];
    }
    return selectedCategoryIds[key];
  }

  function clearAllCategorySelections() {
    for (const t of OTHER_CATEGORY_TABS) {
      selectedCategoryIds[t.id] = [];
    }
  }

  function getSelectedSummaryForTab(tabId) {
    if (tabId === "skins") {
      if (!championLocked) return "Waiting for champ lock…";
      return selectedModId ? String(selectedModId) : "None";
    }
    if (tabId === "maps") return selectedMapId ? String(selectedMapId) : "None";
    if (tabId === "fonts") return selectedFontId ? String(selectedFontId) : "None";
    if (tabId === "announcers") return selectedAnnouncerId ? String(selectedAnnouncerId) : "None";

    // UI / Voiceover / Loading Screen / VFX / SFX / Others are their own categories.
    const selected = getSelectedIdsForCategory(tabId);
    return selected.length ? selected.join(", ") : "None";
  }

  function cleanModName(raw) {
    if (!raw || typeof raw !== "string") return raw;
    let name = raw.replace(/\\/g, "/");
    // Strip directory prefixes (everything before last /)
    const lastSlash = name.lastIndexOf("/");
    if (lastSlash >= 0) name = name.substring(lastSlash + 1);
    // Strip common file extensions
    name = name.replace(/\.(fantome|wad|zip)$/i, "");
    // Replace _ and - with spaces
    name = name.replace(/[_\-]/g, " ");
    // Title-case
    name = name.replace(/\b\w/g, (c) => c.toUpperCase());
    return name.trim() || raw;
  }

  function getTabLabel(tabId) {
    return SUMMARY_TABS.find((t) => t.id === tabId)?.label || String(tabId || "");
  }

  function refreshSummaryValues() {
    if (!panel || !panel._summaryValuesByTab) return;
    for (const tab of SUMMARY_TABS) {
      const el = panel._summaryValuesByTab[tab.id];
      const raw = getSelectedSummaryForTab(tab.id);
      if (el) {
        el.textContent = (raw !== "None" && raw !== "Waiting for champ lock…") ? cleanModName(raw) : raw;
      }
      // Toggle active class on the row
      const row = panel._summaryRowsByTab && panel._summaryRowsByTab[tab.id];
      if (row) {
        if (raw !== "None" && raw !== "Waiting for champ lock…") {
          row.classList.add("active");
        } else {
          row.classList.remove("active");
        }
      }
    }
    // Keep the button badge in sync even when the panel is closed.
    refreshButtonBadgeFromSelections();
  }

  function setRightPaneMode(mode) {
    rightPaneMode = mode;
    if (!panel) return;

    if (panel._summaryView) {
      panel._summaryView.style.display = mode === "summary" ? "flex" : "none";
    }
    if (panel._pickerView) {
      if (mode === "picker") panel._pickerView.classList.add("active");
      else panel._pickerView.classList.remove("active");
    }
    if (panel._backBtn) {
      panel._backBtn.style.display = mode === "picker" ? "inline-block" : "none";
    }
    if (panel._rightTitle) {
      if (mode === "picker") {
        const icon = SUMMARY_ICONS[activeTab] || "";
        panel._rightTitle.innerHTML = `<span class="rose-wheel-title-icon">${icon}</span> Choose \u2022 ${escapeHtml(getTabLabel(activeTab))}`;
      } else {
        panel._rightTitle.textContent = "Custom Mods";
      }
    }
  }

  // Shared bridge API (provided by ROSE-SkinMonitor)
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

  function formatTimestamp(ms) {
    if (!ms) return "";
    try {
      return new Date(ms).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return "";
    }
  }

  const CSS_RULES = `
    .${BUTTON_CLASS} {
      pointer-events: auto;
      -webkit-user-select: none;
      cursor: pointer;
      box-sizing: border-box;
      height: 20px;
      width: 20px;
      position: absolute !important;
      display: block !important;
      z-index: 1;
      margin: 0;
      padding: 0;
    }

    /* Button and Badge Styles */
    lol-uikit-flat-button.rose-custom-wheel-button,
    .rose-custom-wheel-button {
      display: inline-block !important;
      white-space: nowrap !important;
      /* Keep badge stacking self-contained (prevents weird overlap with other UI) */
      isolation: isolate !important;
    }

    .rose-custom-wheel-button .count-badge.social-count-badge,
    lol-uikit-flat-button.rose-custom-wheel-button .count-badge.social-count-badge,
    .rose-custom-wheel-button > .count-badge.social-count-badge,
    lol-uikit-flat-button.rose-custom-wheel-button > .count-badge.social-count-badge {
      position: absolute !important;
      /* Positioning: edit these via CSS variables on the element (DevTools-friendly) */
      top: var(--rose-badge-top, -4px) !important;
      right: var(--rose-badge-right, -17px) !important;
      left: var(--rose-badge-left, auto) !important;
      min-width: 18px !important;
      height: 18px !important;
      padding: 0 5px !important;
      background: #c89b3c !important;
      color: #000 !important;
      border-radius: 3px !important;
      font-size: 11px !important;
      font-weight: 600 !important;
      display: flex !important;
      align-items: center !important;
      justify-content: center !important;
      line-height: 1 !important;
      box-sizing: border-box !important;
      pointer-events: none !important;
      /* Above button contents, but not globally "high" */
      z-index: 1 !important;
      transform: translate(
        var(--rose-badge-translate-x, 60%),
        var(--rose-badge-translate-y, -60%)
      ) !important;
      margin: 0 !important;
      bottom: auto !important;
    }

    .${BUTTON_CLASS}[data-hidden],
    .${BUTTON_CLASS}[data-hidden] * {
      pointer-events: none !important;
      cursor: default !important;
      visibility: hidden !important;
    }

    .${BUTTON_CLASS} .button-image {
      pointer-events: auto;
      -webkit-user-select: none;
      cursor: pointer;
      display: block;
      width: 100%;
      height: 100%;
      background-size: contain;
      background-position: center;
      background-repeat: no-repeat;
      transition: opacity 0.1s ease;
      position: absolute;
      top: 0;
      left: 0;
      min-width: 20px;
      min-height: 20px;
      background-color: transparent !important;
      border: none !important;
    }
    
    .${BUTTON_CLASS} .button-image.default {
      background-color: transparent;
      border: none;
      border-radius: 2px;
    }

    .${BUTTON_CLASS} .button-image.default { opacity: 1; }
    .${BUTTON_CLASS} .button-image.pressed { opacity: 0; background-color: transparent !important; border: none !important; }
    .${BUTTON_CLASS}.pressed .button-image.default { opacity: 0; }
    .${BUTTON_CLASS}.pressed .button-image.pressed { opacity: 1; }

    .chroma.icon { display: none !important; }

    /* Main Panel Container */
    .${PANEL_CLASS} {
      position: fixed;
      z-index: 10000;
      pointer-events: all;
      -webkit-user-select: none;
      font-family: "Spiegel", "LoL Body", Arial, sans-serif;
    }

    .${PANEL_CLASS}[data-no-button] {
      pointer-events: none;
      cursor: default !important;
    }

    /* Modal Content */
    .${PANEL_CLASS} .chroma-modal {
      background: #010a13;
      border-radius: 2px;
      box-shadow: 0 0 20px rgba(0, 0, 0, 0.8);
      display: flex;
      flex-direction: column;
      /* Stable size (clamped to viewport) */
      width: 980px;
      max-width: calc(100vw - 80px);
      min-width: 720px;
      position: relative;
      z-index: 0;
      padding: 16px;
      box-sizing: border-box;
      overflow: hidden;
      color: #f0e6d2;
      height: 520px !important;
      min-height: 420px !important;
      max-height: calc(100vh - 120px) !important;
    }
    
    .${PANEL_CLASS} .chroma-modal.chroma-view {
      /* Height handled in base class to ensure consistency */
      overflow: hidden;
    }

    /* Flyout Reset */
    .${PANEL_CLASS} .flyout {
      position: absolute;
      overflow: visible;
      pointer-events: all;
      -webkit-user-select: none;
      width: auto !important;
      filter: drop-shadow(0 0 10px rgba(0,0,0,0.5));
    }
    
    .${PANEL_CLASS} .flyout .caret,
    .${PANEL_CLASS} .flyout [class*="caret"],
    .${PANEL_CLASS} lol-uikit-flyout-frame .caret,
    .${PANEL_CLASS} lol-uikit-flyout-frame [class*="caret"],
    .${PANEL_CLASS} .flyout .caret::before,
    .${PANEL_CLASS} .flyout .caret::after,
    .${PANEL_CLASS} .flyout [class*="caret"]::before,
    .${PANEL_CLASS} .flyout [class*="caret"]::after,
    .${PANEL_CLASS} lol-uikit-flyout-frame .caret::before,
    .${PANEL_CLASS} lol-uikit-flyout-frame .caret::after,
    .${PANEL_CLASS} lol-uikit-flyout-frame [class*="caret"]::before,
    .${PANEL_CLASS} lol-uikit-flyout-frame [class*="caret"]::after,
    .${PANEL_CLASS} .flyout::part(caret),
    .${PANEL_CLASS} lol-uikit-flyout-frame::part(caret),
    .${PANEL_CLASS} lol-uikit-flyout-frame::before,
    .${PANEL_CLASS} lol-uikit-flyout-frame::after,
    .${PANEL_CLASS} .flyout::before,
    .${PANEL_CLASS} .flyout::after {
      display: none !important;
      visibility: hidden !important;
      content: none !important;
    }

    /* Tab Navigation */
    /* ===== Unified Summary rows (category + status + change in one row) ===== */

    .${PANEL_CLASS} .rose-wheel-right-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding-bottom: 10px;
      border-bottom: 1px solid #3c3c41;
      margin-bottom: 10px;
      flex-shrink: 0;
    }

    .${PANEL_CLASS} .rose-wheel-right-title {
      font-weight: 700;
      color: #f0e6d2;
      font-size: 13px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .${PANEL_CLASS} .rose-wheel-right-title .rose-wheel-title-icon {
      width: 18px;
      height: 18px;
      flex-shrink: 0;
    }

    .${PANEL_CLASS} .rose-wheel-right-title .rose-wheel-title-icon svg {
      width: 18px;
      height: 18px;
      fill: none;
      stroke: #c8aa6e;
      stroke-width: 2;
      stroke-linecap: round;
      stroke-linejoin: round;
    }

    .${PANEL_CLASS} .rose-wheel-summary {
      flex: 1;
      min-height: 0;
      display: flex;
      flex-direction: column;
      justify-content: flex-start;
      gap: 6px;
      padding: 6px 2px;
      overflow-y: auto;
    }

    .${PANEL_CLASS} .rose-wheel-summary::-webkit-scrollbar { width: 6px; }
    .${PANEL_CLASS} .rose-wheel-summary::-webkit-scrollbar-track { background: rgba(0,0,0,0.3); }
    .${PANEL_CLASS} .rose-wheel-summary::-webkit-scrollbar-thumb { background: #5b5a56; border-radius: 3px; }

    .${PANEL_CLASS} .rose-wheel-summary-row {
      display: grid;
      grid-template-columns: 1fr auto;
      align-items: center;
      gap: 12px;
      padding: 8px;
      border: 1px solid #3c3c41;
      border-left: 3px solid transparent;
      background: linear-gradient(to right, rgba(30, 35, 40, 0.8), rgba(30, 35, 40, 0.5));
      transition: border-left-color 0.2s ease;
    }

    .${PANEL_CLASS} .rose-wheel-summary-row.active {
      border-left: 3px solid #c8aa6e;
    }

    .${PANEL_CLASS} .rose-wheel-summary-row:hover .rose-wheel-summary-icon {
      color: #c8aa6e;
    }

    .${PANEL_CLASS} .rose-wheel-summary-icon {
      width: 18px;
      height: 18px;
      flex-shrink: 0;
      color: #5b5a56;
      transition: color 0.2s ease;
    }

    .${PANEL_CLASS} .rose-wheel-summary-icon svg {
      width: 18px;
      height: 18px;
      fill: none;
      stroke: currentColor;
      stroke-width: 2;
      stroke-linecap: round;
      stroke-linejoin: round;
    }

    .${PANEL_CLASS} .rose-wheel-summary-left {
      flex: 1;
      min-width: 0;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }

    .${PANEL_CLASS} .rose-wheel-summary-label {
      color: #a09b8c;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    .${PANEL_CLASS} .rose-wheel-summary-value {
      color: #f0e6d2;
      font-size: 13px;
      font-weight: 700;
      word-break: break-word;
    }

    .${PANEL_CLASS} .rose-wheel-picker {
      flex: 1;
      min-height: 0;
      display: none;
    }

    .${PANEL_CLASS} .rose-wheel-picker.active {
      display: flex;
      flex-direction: column;
      min-height: 0;
    }

    /* (Tab buttons removed from Summary UI; navigation is via per-row Change buttons) */

    .${PANEL_CLASS} .tab-content {
      display: none;
      width: 100%;
      background: transparent;
    }

    .${PANEL_CLASS} .tab-content.active {
      display: flex;
      flex-direction: column;
      height: 100%;
    }

    /* Mod List Content */
    .${PANEL_CLASS} .mod-selection {
      pointer-events: all;
      flex: 1;
      min-height: 0;
      overflow-y: auto;
      overflow-x: hidden;
      padding-right: 4px;
      margin-top: 4px;
    }

    /* Scrollbar */
    .${PANEL_CLASS} .mod-selection::-webkit-scrollbar {
      width: 6px;
    }
    .${PANEL_CLASS} .mod-selection::-webkit-scrollbar-track {
      background: rgba(0,0,0,0.3);
    }
    .${PANEL_CLASS} .mod-selection::-webkit-scrollbar-thumb {
      background: #5b5a56;
      border-radius: 3px;
    }

    .${PANEL_CLASS} .mod-selection ul {
      list-style: none;
      margin: 0;
      padding: 0;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }

    /* List Items */
    .${PANEL_CLASS} .mod-selection li {
      background: linear-gradient(to right, rgba(30, 35, 40, 0.9), rgba(30, 35, 40, 0.6));
      border: 1px solid #3c3c41;
      border-left: 3px solid transparent;
      padding: 10px;
      transition: all 0.2s ease;
      display: flex;
      flex-direction: column;
      gap: 4px;
      border-radius: 0;
    }

    .${PANEL_CLASS} .mod-selection li:hover {
      background: linear-gradient(to right, rgba(40, 45, 50, 0.9), rgba(40, 45, 50, 0.7));
      border-color: #5c5c61;
      border-left-color: #c8aa6e;
      transform: translateX(2px);
    }

    .${PANEL_CLASS} .mod-selection li.selected-row {
      border-left-color: #c8aa6e;
      background: linear-gradient(to right, rgba(200, 170, 110, 0.12), rgba(30, 35, 40, 0.6));
    }

    .${PANEL_CLASS} .mod-selection li .mod-name.none-label {
      font-style: italic;
      color: #8b8b8b;
    }

    .${PANEL_CLASS} .mod-name-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      width: 100%;
    }
    
    .${PANEL_CLASS} .mod-name {
      color: #f0e6d2;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.5px;
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .${PANEL_CLASS} .mod-description {
      color: #a09b8c;
      font-size: 11px;
      font-weight: 400;
      line-height: 1.4;
      word-wrap: break-word;
    }

    .${PANEL_CLASS} .mod-meta, 
    .${PANEL_CLASS} .mod-injection-note {
      color: #7a7a7d;
      font-size: 10px;
      font-style: italic;
    }

    .${PANEL_CLASS} .mod-loading {
      color: #a09b8c;
      font-size: 12px;
      text-align: center;
      padding: 20px;
      font-style: italic;
    }

    /* Action Buttons */
    .${PANEL_CLASS} .mod-select-button {
      background: transparent;
      border: 1px solid #c8aa6e;
      color: #c8aa6e;
      padding: 4px 10px;
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      cursor: pointer;
      transition: all 0.2s;
      flex-shrink: 0;
      border-radius: 0;
    }

    .${PANEL_CLASS} .mod-select-button:hover {
      background: rgba(200, 170, 110, 0.1);
      box-shadow: 0 0 8px rgba(200, 170, 110, 0.2);
    }

    .${PANEL_CLASS} .mod-select-button.selected {
      background: #c8aa6e;
      color: #010a13;
      box-shadow: 0 0 10px rgba(200, 170, 110, 0.4);
      border-color: #c8aa6e;
    }
  `;

  function injectCSS() {
    const styleId = "rose-custom-wheel-css";
    if (document.getElementById(styleId)) {
      return;
    }

    const styleTag = document.createElement("style");
    styleTag.id = styleId;
    styleTag.textContent = CSS_RULES;
    document.head.appendChild(styleTag);
  }

  function createButton() {
    if (button) {
      return button;
    }

    try {
      button = document.createElement("lol-uikit-flat-button");
    } catch (e) {
      button = document.createElement("div");
    }
    button.className = "lol-uikit-flat-button idle rose-custom-wheel-button";
    button.textContent = "Custom mods";

    // Ensure button has relative positioning for badge (only if not already positioned)
    const computedStyle = window.getComputedStyle(button);
    if (computedStyle.position === "static" || computedStyle.position === "") {
      button.style.position = "relative";
    }

    // Create count badge
    const countBadge = document.createElement("div");
    countBadge.className = "count-badge social-count-badge";
    countBadge.textContent = "0";
    countBadge.style.display = "none"; // Hidden by default
    // Defaults (can be overridden live in DevTools on the element via CSS variables)
    countBadge.style.setProperty("--rose-badge-top", "-4px");
    countBadge.style.setProperty("--rose-badge-right", "-17px");
    countBadge.style.setProperty("--rose-badge-left", "auto");
    countBadge.style.setProperty("--rose-badge-translate-x", "60%");
    countBadge.style.setProperty("--rose-badge-translate-y", "-60%");
    button.appendChild(countBadge);
    button._countBadge = countBadge; // Store reference

    button.addEventListener("click", (event) => {
      event.stopPropagation();
      event.preventDefault();
      isOpen ? closePanel() : openPanel();
    });

    return button;
  }

  function createPanel() {
    if (panel) {
      return panel;
    }

    // Remove existing panel if any
    const existingPanel = document.getElementById(PANEL_ID);
    if (existingPanel) {
      existingPanel.remove();
    }

    panel = document.createElement("div");
    panel.id = PANEL_ID;
    panel.className = PANEL_CLASS;
    panel.style.position = "fixed";
    panel.style.top = "0";
    panel.style.left = "0";
    panel.style.width = "100%";
    panel.style.height = "100%";
    panel.style.zIndex = "10000";
    panel.style.pointerEvents = "none";
    panel.style.display = "none"; // Hidden by default

    // Create flyout frame structure
    let flyoutFrame;
    try {
      flyoutFrame = document.createElement("lol-uikit-flyout-frame");
      flyoutFrame.className = "flyout";
      flyoutFrame.setAttribute("orientation", "top");
      flyoutFrame.setAttribute("animated", "false");
      flyoutFrame.setAttribute("caretless", "true");
      flyoutFrame.setAttribute("show", "true");
    } catch (e) {
      flyoutFrame = document.createElement("div");
      flyoutFrame.className = "flyout";
    }

    flyoutFrame.style.position = "absolute";
    flyoutFrame.style.overflow = "visible";
    flyoutFrame.style.pointerEvents = "all";

    let flyoutContent;
    try {
      flyoutContent = document.createElement("lc-flyout-content");
    } catch (e) {
      flyoutContent = document.createElement("div");
      flyoutContent.className = "lc-flyout-content";
    }

    const modal = document.createElement("div");
    modal.className = "champ-select-chroma-modal chroma-modal chroma-view ember-view";

    // Header Decoration removed as per user request

    const isOtherCategoryTab = (tabName) => OTHER_CATEGORY_TABS.some((t) => t.id === tabName);

    const switchTab = (tabName) => {
      activeTab = tabName;
      // Update tab content
      const allContents = [
        panel._modsContent,
        panel._mapsContent,
        panel._fontsContent,
        panel._announcersContent,
        ...OTHER_CATEGORY_TABS.map((t) => panel[`_${t.id}Content`]).filter(Boolean),
      ];
      allContents.forEach((content) => {
        if (content && content.dataset && content.dataset.tab === tabName) {
          content.classList.add("active");
        } else if (content) {
          content.classList.remove("active");
        }
      });
      // Request data for the active tab (always request fresh data)
      if (tabName === "skins") {
        requestModsForCurrentSkin();
      } else if (tabName === "maps") {
        requestMaps();
      } else if (tabName === "fonts") {
        requestFonts();
      } else if (tabName === "announcers") {
        requestAnnouncers();
      } else if (isOtherCategoryTab(tabName)) {
        if (lastCategoryModsById[tabName]) {
          updateOtherCategoryEntries(tabName, lastCategoryModsById[tabName]);
        } else {
          requestCategoryMods(tabName);
        }
      }

      // Update header title for picker context
      if (panel && panel._rightTitle) {
        if (rightPaneMode === "picker") {
          const icon = SUMMARY_ICONS[activeTab] || "";
          panel._rightTitle.innerHTML = `<span class="rose-wheel-title-icon">${icon}</span> Choose \u2022 ${escapeHtml(getTabLabel(activeTab))}`;
        } else {
          panel._rightTitle.textContent = "Custom Mods";
        }
      }
    };

    // Scrollable area for mod list
    let scrollable;
    try {
      scrollable = document.createElement("lol-uikit-scrollable");
      scrollable.className = "mod-selection";
      scrollable.setAttribute("overflow-masks", "enabled");
    } catch (e) {
      scrollable = document.createElement("div");
      scrollable.className = "mod-selection";
      scrollable.style.overflowY = "auto";
    }

    // Create tab content containers
    const modsContent = document.createElement("div");
    modsContent.className = "tab-content active";
    modsContent.dataset.tab = "skins";

    const mapsContent = document.createElement("div");
    mapsContent.className = "tab-content";
    mapsContent.dataset.tab = "maps";

    const fontsContent = document.createElement("div");
    fontsContent.className = "tab-content";
    fontsContent.dataset.tab = "fonts";

    const announcersContent = document.createElement("div");
    announcersContent.className = "tab-content";
    announcersContent.dataset.tab = "announcers";

    const otherContents = OTHER_CATEGORY_TABS.map((t) => {
      const content = document.createElement("div");
      content.className = "tab-content";
      content.dataset.tab = t.id;
      return content;
    });

    // Create ul lists for each tab
    const modList = document.createElement("ul");
    modList.style.listStyle = "none";
    modList.style.margin = "0";
    modList.style.padding = "0";
    modList.style.display = "flex";
    modList.style.flexDirection = "column";
    modList.style.width = "100%";
    modList.style.gap = "4px";

    const mapsList = document.createElement("ul");
    mapsList.style.listStyle = "none";
    mapsList.style.margin = "0";
    mapsList.style.padding = "0";
    mapsList.style.display = "flex";
    mapsList.style.flexDirection = "column";
    mapsList.style.width = "100%";
    mapsList.style.gap = "4px";

    const fontsList = document.createElement("ul");
    fontsList.style.listStyle = "none";
    fontsList.style.margin = "0";
    fontsList.style.padding = "0";
    fontsList.style.display = "flex";
    fontsList.style.flexDirection = "column";
    fontsList.style.width = "100%";
    fontsList.style.gap = "4px";

    const announcersList = document.createElement("ul");
    announcersList.style.listStyle = "none";
    announcersList.style.margin = "0";
    announcersList.style.padding = "0";
    announcersList.style.display = "flex";
    announcersList.style.flexDirection = "column";
    announcersList.style.width = "100%";
    announcersList.style.gap = "4px";

    const createSimpleList = () => {
      const ul = document.createElement("ul");
      ul.style.listStyle = "none";
      ul.style.margin = "0";
      ul.style.padding = "0";
      ul.style.display = "flex";
      ul.style.flexDirection = "column";
      ul.style.width = "100%";
      ul.style.gap = "4px";
      return ul;
    };

    const otherLists = OTHER_CATEGORY_TABS.reduce((acc, t) => {
      acc[t.id] = createSimpleList();
      return acc;
    }, {});

    // Loading elements for each tab
    const modsLoading = document.createElement("div");
    modsLoading.className = "mod-loading";
    modsLoading.textContent = "Waiting for mods…";
    modsLoading.style.display = "none";

    const mapsLoading = document.createElement("div");
    mapsLoading.className = "mod-loading";
    mapsLoading.textContent = "Loading maps…";
    mapsLoading.style.display = "none";

    const fontsLoading = document.createElement("div");
    fontsLoading.className = "mod-loading";
    fontsLoading.textContent = "Loading fonts…";
    fontsLoading.style.display = "none";

    const announcersLoading = document.createElement("div");
    announcersLoading.className = "mod-loading";
    announcersLoading.textContent = "Loading announcers…";
    announcersLoading.style.display = "none";

    const otherLoadingEls = OTHER_CATEGORY_TABS.reduce((acc, t) => {
      const el = document.createElement("div");
      el.className = "mod-loading";
      el.textContent = `Loading ${t.label.toLowerCase()}…`;
      el.style.display = "none";
      acc[t.id] = el;
      return acc;
    }, {});

    // Assemble mods content
    modsContent.appendChild(modsLoading);
    modsContent.appendChild(modList);

    // Assemble other tabs content
    mapsContent.appendChild(mapsLoading);
    mapsContent.appendChild(mapsList);

    fontsContent.appendChild(fontsLoading);
    fontsContent.appendChild(fontsList);

    announcersContent.appendChild(announcersLoading);
    announcersContent.appendChild(announcersList);

    otherContents.forEach((content) => {
      const tabId = content.dataset.tab;
      content.appendChild(otherLoadingEls[tabId]);
      content.appendChild(otherLists[tabId]);
    });

    // Add tab content to scrollable (tabs stay fixed outside)
    scrollable.appendChild(modsContent);
    scrollable.appendChild(mapsContent);
    scrollable.appendChild(fontsContent);
    scrollable.appendChild(announcersContent);
    otherContents.forEach((content) => scrollable.appendChild(content));

    // Header + Summary + Picker (Summary rows contain the category buttons on the left)
    const rightHeader = document.createElement("div");
    rightHeader.className = "rose-wheel-right-header";

    const rightTitle = document.createElement("div");
    rightTitle.className = "rose-wheel-right-title";
    rightTitle.textContent = "Custom Mods";

    const headerButtons = document.createElement("div");
    headerButtons.style.display = "flex";
    headerButtons.style.gap = "8px";

    const backBtn = document.createElement("button");
    backBtn.className = "mod-select-button";
    backBtn.textContent = "Back";
    backBtn.style.display = "none";

    headerButtons.appendChild(backBtn);

    rightHeader.appendChild(rightTitle);
    rightHeader.appendChild(headerButtons);

    // Summary view (all categories)
    const summaryView = document.createElement("div");
    summaryView.className = "rose-wheel-summary";

    panel._summaryValuesByTab = {};
    panel._summaryRowsByTab = {};

    SUMMARY_TABS.forEach((tab) => {
      const row = document.createElement("div");
      row.className = "rose-wheel-summary-row";

      // Left cell: value
      const left = document.createElement("div");
      left.className = "rose-wheel-summary-left";

      const label = document.createElement("div");
      label.className = "rose-wheel-summary-label";
      label.style.display = "flex";
      label.style.alignItems = "center";
      label.style.gap = "6px";

      const iconSpan = document.createElement("span");
      iconSpan.className = "rose-wheel-summary-icon";
      iconSpan.innerHTML = SUMMARY_ICONS[tab.id] || "";
      label.appendChild(iconSpan);

      const labelText = document.createElement("span");
      labelText.textContent = tab.label;
      label.appendChild(labelText);

      const value = document.createElement("div");
      value.className = "rose-wheel-summary-value";
      value.textContent = getSelectedSummaryForTab(tab.id);
      panel._summaryValuesByTab[tab.id] = value;

      left.appendChild(label);
      left.appendChild(value);

      const changeBtn = document.createElement("button");
      changeBtn.className = "mod-select-button";
      changeBtn.textContent = "Change";
      changeBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        switchTab(tab.id);
        setRightPaneMode("picker");
        refreshSummaryValues();
      });

      row.appendChild(left);
      row.appendChild(changeBtn);
      panel._summaryRowsByTab[tab.id] = row;
      summaryView.appendChild(row);
    });

    // Picker view (reuses existing scrollable with tab contents)
    const pickerView = document.createElement("div");
    pickerView.className = "rose-wheel-picker";
    pickerView.appendChild(scrollable);

    backBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      setRightPaneMode("summary");
      refreshSummaryValues();
    });

    panel._summaryView = summaryView;
    panel._pickerView = pickerView;
    panel._backBtn = backBtn;
    panel._rightTitle = rightTitle;

    modal.appendChild(rightHeader);
    modal.appendChild(summaryView);
    modal.appendChild(pickerView);
    flyoutContent.appendChild(modal);
    flyoutFrame.appendChild(flyoutContent);
    panel.appendChild(flyoutFrame);

    // Remove arrow/caret at the bottom
    setTimeout(() => {
      const carets = flyoutFrame.querySelectorAll('.caret, [class*="caret"]');
      carets.forEach(caret => {
        if (caret && caret.parentNode) {
          caret.style.display = 'none';
          caret.style.visibility = 'hidden';
        }
      });
      // Also try to remove via shadow DOM if it's a custom element
      if (flyoutFrame.shadowRoot) {
        const shadowCarets = flyoutFrame.shadowRoot.querySelectorAll('.caret, [class*="caret"]');
        shadowCarets.forEach(caret => {
          if (caret) {
            caret.style.display = 'none';
            caret.style.visibility = 'hidden';
          }
        });
      }
    }, 100);

    // Store references
    panel._modList = modList;
    panel._mapsList = mapsList;
    panel._fontsList = fontsList;
    panel._announcersList = announcersList;
    OTHER_CATEGORY_TABS.forEach((t) => {
      panel[`_${t.id}List`] = otherLists[t.id];
      panel[`_${t.id}Loading`] = otherLoadingEls[t.id];
      panel[`_${t.id}Content`] = otherContents.find((c) => c.dataset.tab === t.id);
    });
    panel._modsLoading = modsLoading;
    panel._mapsLoading = mapsLoading;
    panel._fontsLoading = fontsLoading;
    panel._announcersLoading = announcersLoading;
    panel._modsContent = modsContent;
    panel._mapsContent = mapsContent;
    panel._fontsContent = fontsContent;
    panel._announcersContent = announcersContent;
    panel._loadingEl = modsLoading; // Keep for backward compatibility

    // Width is now stable (CSS-controlled); no dynamic calculation needed.
    panel._calculateWidth = null;

    // Start in summary mode by default
    setRightPaneMode("summary");
    refreshSummaryValues();

    return panel;
  }

  function positionPanel(panelElement, buttonElement) {
    if (!panelElement || !buttonElement) {
      return;
    }

    const flyoutFrame = panelElement.querySelector(".flyout");
    if (!flyoutFrame) {
      return;
    }

    const rect = buttonElement.getBoundingClientRect();
    let flyoutRect = flyoutFrame.getBoundingClientRect();

    if (flyoutRect.width === 0) {
      // Try to get width from the modal element
      const modal = flyoutFrame.querySelector(".chroma-modal");
      if (modal) {
        const modalRect = modal.getBoundingClientRect();
        if (modalRect.width > 0) {
          flyoutRect = { width: modalRect.width, height: flyoutRect.height || 400 };
        } else {
          // Fallback: use button width + estimated padding
          flyoutRect = { width: rect.width + 32, height: 400 };
        }
      } else {
        // Fallback: use button width + estimated padding
        flyoutRect = { width: rect.width + 32, height: 400 };
      }
    }

    // Center panel in the middle of the screen
    const centerX = (window.innerWidth - flyoutRect.width) / 2;
    const centerY = (window.innerHeight - flyoutRect.height) / 2;

    flyoutFrame.style.position = "fixed";
    flyoutFrame.style.overflow = "visible";
    flyoutFrame.style.top = `${centerY}px`;
    flyoutFrame.style.left = `${centerX}px`;
    flyoutFrame.style.right = ""; // Clear right when using left
    flyoutFrame.style.transform = ""; // Remove transform to avoid blur

    panelElement.style.position = "fixed";
    panelElement.style.top = "0";
    panelElement.style.left = "0";
    panelElement.style.width = "100%";
    panelElement.style.height = "100%";
    panelElement.style.pointerEvents = "none";
    flyoutFrame.style.pointerEvents = "all";
  }

  function updateNoneRow(listEl, isNoneActive) {
    const noneLi = listEl?.querySelector('[data-mod-id="__none__"], [data-map-id="__none__"], [data-font-id="__none__"], [data-announcer-id="__none__"], [data-other-id="__none__"]');
    if (!noneLi) return;
    const noneBtn = noneLi.querySelector(".mod-select-button");
    if (isNoneActive) {
      noneLi.classList.add("selected-row");
      if (noneBtn) { noneBtn.textContent = "Selected"; noneBtn.classList.add("selected"); }
    } else {
      noneLi.classList.remove("selected-row");
      if (noneBtn) { noneBtn.textContent = "Select"; noneBtn.classList.remove("selected"); }
    }
  }

  function handleModSelect(modId, buttonElement, modData) {
    const parentLi = buttonElement.closest("li");
    // Toggle selection
    if (selectedModId === modId) {
      // Deselect
      selectedModId = null;
      selectedModSkinId = null;
      buttonElement.textContent = "Select";
      buttonElement.classList.remove("selected");
      if (parentLi) parentLi.classList.remove("selected-row");

      // Emit deselection to Python backend (modId: null means deselect)
      const state = window.__roseSkinState || {};
      const championId = Number(state.championId);
      const skinId = Number(state.skinId);

      if (championId && skinId) {
        if (bridge) bridge.send({
          type: "select-skin-mod",
          championId,
          skinId,
          modId: null, // null means deselect
          modData: null,
        });
      }
    } else {
      // Deselect previous button if any
      if (selectedModId) {
        const prevLi = panel?._modList?.querySelector(
          `[data-mod-id="${selectedModId}"]`
        );
        if (prevLi) {
          const previousButton = prevLi.querySelector(".mod-select-button");
          if (previousButton) {
            previousButton.textContent = "Select";
            previousButton.classList.remove("selected");
          }
          prevLi.classList.remove("selected-row");
        }
      }

      // Select new mod
      selectedModId = modId;
      // Store the mod's own target skinId (from the backend entry), not the currently hovered skin.
      const modTargetSkinId = modData?.skinId ? Number(modData.skinId) : null;
      const state = window.__roseSkinState || {};
      selectedModSkinId = modTargetSkinId || Number(state.skinId);

      buttonElement.textContent = "Selected";
      buttonElement.classList.add("selected");
      if (parentLi) parentLi.classList.add("selected-row");

      // Emit selection to Python backend using the mod's target skinId
      const championId = Number(state.championId);
      const emitSkinId = selectedModSkinId;

      if (championId && emitSkinId) {
        const payload = {
          type: "select-skin-mod",
          championId,
          skinId: emitSkinId,
          modId,
          modData,
        };
        console.log(`[ROSE-CustomWheel] Sending mod selection:`, payload);
        if (bridge) bridge.send(payload);
      } else {
        console.warn(`[ROSE-CustomWheel] Cannot send mod selection - missing championId or skinId:`, { championId, skinId: emitSkinId });
      }
    }

    updateNoneRow(panel?._modList, !selectedModId);
    refreshSummaryValues();
    refreshButtonBadgeFromSelections();
  }

  function updateModEntries(mods) {
    if (!panel || !panel._modList || !panel._loadingEl) {
      return;
    }

    const modList = panel._modList;
    const loadingEl = panel._loadingEl;

    // Store current selectedModId before clearing the list
    const previousSelectedModId = selectedModId;

    modList.innerHTML = "";

    // Don't reset selection - restore it if it still exists in the mod list

    if (!mods || mods.length === 0) {
      loadingEl.textContent = "No skins found";
      loadingEl.style.display = "block";
      return;
    }

    loadingEl.style.display = "none";

    // "None" deselect option
    {
      const noneItem = document.createElement("li");
      noneItem.setAttribute("data-mod-id", "__none__");
      const noneRow = document.createElement("div");
      noneRow.className = "mod-name-row";
      const noneName = document.createElement("div");
      noneName.className = "mod-name none-label";
      noneName.textContent = "None";
      noneRow.appendChild(noneName);
      const noneBtn = document.createElement("button");
      noneBtn.className = "mod-select-button";
      const nothingSelected = !selectedModId;
      noneBtn.textContent = nothingSelected ? "Selected" : "Select";
      if (nothingSelected) {
        noneBtn.classList.add("selected");
        noneItem.classList.add("selected-row");
      }
      noneBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (selectedModId) {
          // Deselect current via handler-like logic
          const prevLi = modList.querySelector(`[data-mod-id="${selectedModId}"]`);
          if (prevLi) {
            const prevBtn = prevLi.querySelector(".mod-select-button");
            if (prevBtn) { prevBtn.textContent = "Select"; prevBtn.classList.remove("selected"); }
            prevLi.classList.remove("selected-row");
          }
          const state = window.__roseSkinState || {};
          const championId = Number(state.championId);
          const skinId = Number(state.skinId);
          selectedModId = null;
          selectedModSkinId = null;
          if (championId && skinId) {
            if (bridge) bridge.send({ type: "select-skin-mod", championId, skinId, modId: null, modData: null });
          }
        }
        // Mark None as selected
        noneBtn.textContent = "Selected";
        noneBtn.classList.add("selected");
        noneItem.classList.add("selected-row");
        refreshSummaryValues();
        refreshButtonBadgeFromSelections();
      });
      noneRow.appendChild(noneBtn);
      noneItem.appendChild(noneRow);
      modList.appendChild(noneItem);
    }

    mods.forEach((mod) => {
      const listItem = document.createElement("li");
      // Use relativePath as the unique identifier, fallback to modName
      const modId = mod.relativePath || mod.modName || `mod-${Date.now()}-${Math.random()}`;

      // Create a row container for name and button
      const modNameRow = document.createElement("div");
      modNameRow.className = "mod-name-row";

      const modName = document.createElement("div");
      modName.className = "mod-name";
      modName.textContent = cleanModName(mod.modName) || "Unnamed mod";
      modNameRow.appendChild(modName);

      // Select button
      const selectButton = document.createElement("button");
      selectButton.className = "mod-select-button";
      // A mod is selected purely by ID — selection persists across skin navigation.
      const isSelected = (selectedModId === modId || previousSelectedModId === modId);

      // Restore selection state if this was previously selected
      if (previousSelectedModId === modId && selectedModId !== modId) {
        selectedModId = modId;
      }

      selectButton.textContent = isSelected ? "Selected" : "Select";
      if (isSelected) {
        selectButton.classList.add("selected");
        listItem.classList.add("selected-row");
      }
      selectButton.addEventListener("click", (e) => {
        e.stopPropagation();
        handleModSelect(modId, selectButton, mod);
      });

      modNameRow.appendChild(selectButton);
      listItem.appendChild(modNameRow);

      // Store mod ID on list item for easy reference
      listItem.setAttribute("data-mod-id", modId);

      if (mod.description) {
        const modDesc = document.createElement("div");
        modDesc.className = "mod-description";
        modDesc.textContent = mod.description;
        listItem.appendChild(modDesc);
      }

      modList.appendChild(listItem);
    });
  }

  function updateMapsEntries(mapsList) {
    if (!panel || !panel._mapsList || !panel._mapsLoading) {
      return;
    }

    const mapsListEl = panel._mapsList;
    const loadingEl = panel._mapsLoading;

    mapsListEl.innerHTML = "";

    if (!mapsList || mapsList.length === 0) {
      loadingEl.textContent = "No maps found";
      loadingEl.style.display = "block";
      return;
    }

    loadingEl.style.display = "none";

    // "None" deselect option
    {
      const noneItem = document.createElement("li");
      noneItem.setAttribute("data-map-id", "__none__");
      const noneRow = document.createElement("div");
      noneRow.className = "mod-name-row";
      const noneName = document.createElement("div");
      noneName.className = "mod-name none-label";
      noneName.textContent = "None";
      noneRow.appendChild(noneName);
      const noneBtn = document.createElement("button");
      noneBtn.className = "mod-select-button";
      const nothingSelected = !selectedMapId;
      noneBtn.textContent = nothingSelected ? "Selected" : "Select";
      if (nothingSelected) { noneBtn.classList.add("selected"); noneItem.classList.add("selected-row"); }
      noneBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (selectedMapId) {
          const prevLi = mapsListEl.querySelector(`[data-map-id="${selectedMapId}"]`);
          if (prevLi) {
            const prevBtn = prevLi.querySelector(".mod-select-button");
            if (prevBtn) { prevBtn.textContent = "Select"; prevBtn.classList.remove("selected"); }
            prevLi.classList.remove("selected-row");
          }
          selectedMapId = null;
          if (bridge) bridge.send({ type: "select-map", mapId: null });
        }
        noneBtn.textContent = "Selected"; noneBtn.classList.add("selected"); noneItem.classList.add("selected-row");
        refreshSummaryValues(); refreshButtonBadgeFromSelections();
      });
      noneRow.appendChild(noneBtn);
      noneItem.appendChild(noneRow);
      mapsListEl.appendChild(noneItem);
    }

    mapsList.forEach((map) => {
      const listItem = document.createElement("li");
      const mapId = map.id || map.name || `map-${Date.now()}-${Math.random()}`;

      // Create a row container for name and button
      const mapNameRow = document.createElement("div");
      mapNameRow.className = "mod-name-row";

      const mapName = document.createElement("div");
      mapName.className = "mod-name";
      mapName.textContent = cleanModName(map.name) || "Unnamed map";
      mapNameRow.appendChild(mapName);

      const selectButton = document.createElement("button");
      selectButton.className = "mod-select-button";
      listItem.setAttribute("data-map-id", mapId);

      if (selectedMapId === mapId) {
        selectButton.textContent = "Selected";
        selectButton.classList.add("selected");
        listItem.classList.add("selected-row");
      } else {
        selectButton.textContent = "Select";
      }

      selectButton.addEventListener("click", (e) => {
        e.stopPropagation();
        handleMapSelect(mapId, selectButton, map);
      });

      mapNameRow.appendChild(selectButton);
      listItem.appendChild(mapNameRow);

      if (map.description) {
        const mapDesc = document.createElement("div");
        mapDesc.className = "mod-description";
        mapDesc.textContent = map.description;
        listItem.appendChild(mapDesc);
      }

      mapsListEl.appendChild(listItem);
    });
  }

  function updateFontsEntries(fontsList) {
    if (!panel || !panel._fontsList || !panel._fontsLoading) {
      return;
    }

    const fontsListEl = panel._fontsList;
    const loadingEl = panel._fontsLoading;

    fontsListEl.innerHTML = "";

    if (!fontsList || fontsList.length === 0) {
      loadingEl.textContent = "No fonts found";
      loadingEl.style.display = "block";
      return;
    }

    loadingEl.style.display = "none";

    // "None" deselect option
    {
      const noneItem = document.createElement("li");
      noneItem.setAttribute("data-font-id", "__none__");
      const noneRow = document.createElement("div");
      noneRow.className = "mod-name-row";
      const noneName = document.createElement("div");
      noneName.className = "mod-name none-label";
      noneName.textContent = "None";
      noneRow.appendChild(noneName);
      const noneBtn = document.createElement("button");
      noneBtn.className = "mod-select-button";
      const nothingSelected = !selectedFontId;
      noneBtn.textContent = nothingSelected ? "Selected" : "Select";
      if (nothingSelected) { noneBtn.classList.add("selected"); noneItem.classList.add("selected-row"); }
      noneBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (selectedFontId) {
          const prevLi = fontsListEl.querySelector(`[data-font-id="${selectedFontId}"]`);
          if (prevLi) {
            const prevBtn = prevLi.querySelector(".mod-select-button");
            if (prevBtn) { prevBtn.textContent = "Select"; prevBtn.classList.remove("selected"); }
            prevLi.classList.remove("selected-row");
          }
          selectedFontId = null;
          if (bridge) bridge.send({ type: "select-font", fontId: null });
        }
        noneBtn.textContent = "Selected"; noneBtn.classList.add("selected"); noneItem.classList.add("selected-row");
        refreshSummaryValues(); refreshButtonBadgeFromSelections();
      });
      noneRow.appendChild(noneBtn);
      noneItem.appendChild(noneRow);
      fontsListEl.appendChild(noneItem);
    }

    fontsList.forEach((font) => {
      const listItem = document.createElement("li");
      const fontId = font.id || font.name || `font-${Date.now()}-${Math.random()}`;

      // Create a row container for name and button
      const fontNameRow = document.createElement("div");
      fontNameRow.className = "mod-name-row";

      const fontName = document.createElement("div");
      fontName.className = "mod-name";
      fontName.textContent = cleanModName(font.name) || "Unnamed font";
      fontNameRow.appendChild(fontName);

      const selectButton = document.createElement("button");
      selectButton.className = "mod-select-button";
      listItem.setAttribute("data-font-id", fontId);

      if (selectedFontId === fontId) {
        selectButton.textContent = "Selected";
        selectButton.classList.add("selected");
        listItem.classList.add("selected-row");
      } else {
        selectButton.textContent = "Select";
      }

      selectButton.addEventListener("click", (e) => {
        e.stopPropagation();
        handleFontSelect(fontId, selectButton, font);
      });

      fontNameRow.appendChild(selectButton);
      listItem.appendChild(fontNameRow);

      if (font.description) {
        const fontDesc = document.createElement("div");
        fontDesc.className = "mod-description";
        fontDesc.textContent = font.description;
        listItem.appendChild(fontDesc);
      }

      fontsListEl.appendChild(listItem);
    });
  }

  function updateAnnouncersEntries(announcersList) {
    if (!panel || !panel._announcersList || !panel._announcersLoading) {
      return;
    }

    const announcersListEl = panel._announcersList;
    const loadingEl = panel._announcersLoading;

    announcersListEl.innerHTML = "";

    if (!announcersList || announcersList.length === 0) {
      loadingEl.textContent = "No announcers found";
      loadingEl.style.display = "block";
      return;
    }

    loadingEl.style.display = "none";

    // "None" deselect option
    {
      const noneItem = document.createElement("li");
      noneItem.setAttribute("data-announcer-id", "__none__");
      const noneRow = document.createElement("div");
      noneRow.className = "mod-name-row";
      const noneName = document.createElement("div");
      noneName.className = "mod-name none-label";
      noneName.textContent = "None";
      noneRow.appendChild(noneName);
      const noneBtn = document.createElement("button");
      noneBtn.className = "mod-select-button";
      const nothingSelected = !selectedAnnouncerId;
      noneBtn.textContent = nothingSelected ? "Selected" : "Select";
      if (nothingSelected) { noneBtn.classList.add("selected"); noneItem.classList.add("selected-row"); }
      noneBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (selectedAnnouncerId) {
          const prevLi = announcersListEl.querySelector(`[data-announcer-id="${selectedAnnouncerId}"]`);
          if (prevLi) {
            const prevBtn = prevLi.querySelector(".mod-select-button");
            if (prevBtn) { prevBtn.textContent = "Select"; prevBtn.classList.remove("selected"); }
            prevLi.classList.remove("selected-row");
          }
          selectedAnnouncerId = null;
          if (bridge) bridge.send({ type: "select-announcer", announcerId: null });
        }
        noneBtn.textContent = "Selected"; noneBtn.classList.add("selected"); noneItem.classList.add("selected-row");
        refreshSummaryValues(); refreshButtonBadgeFromSelections();
      });
      noneRow.appendChild(noneBtn);
      noneItem.appendChild(noneRow);
      announcersListEl.appendChild(noneItem);
    }

    announcersList.forEach((announcer) => {
      const listItem = document.createElement("li");
      const announcerId = announcer.id || announcer.name || `announcer-${Date.now()}-${Math.random()}`;

      // Create a row container for name and button
      const announcerNameRow = document.createElement("div");
      announcerNameRow.className = "mod-name-row";

      const announcerName = document.createElement("div");
      announcerName.className = "mod-name";
      announcerName.textContent = cleanModName(announcer.name) || "Unnamed announcer";
      announcerNameRow.appendChild(announcerName);

      const selectButton = document.createElement("button");
      selectButton.className = "mod-select-button";
      listItem.setAttribute("data-announcer-id", announcerId);

      if (selectedAnnouncerId === announcerId) {
        selectButton.textContent = "Selected";
        selectButton.classList.add("selected");
        listItem.classList.add("selected-row");
      } else {
        selectButton.textContent = "Select";
      }

      selectButton.addEventListener("click", (e) => {
        e.stopPropagation();
        handleAnnouncerSelect(announcerId, selectButton, announcer);
      });

      announcerNameRow.appendChild(selectButton);
      listItem.appendChild(announcerNameRow);

      if (announcer.description) {
        const announcerDesc = document.createElement("div");
        announcerDesc.className = "mod-description";
        announcerDesc.textContent = announcer.description;
        listItem.appendChild(announcerDesc);
      }

      announcersListEl.appendChild(listItem);
    });
  }

  function updateOtherCategoryEntries(categoryId, items) {
    if (!panel) {
      return;
    }
    const listEl = panel[`_${categoryId}List`];
    const loadingEl = panel[`_${categoryId}Loading`];
    if (!listEl || !loadingEl) {
      return;
    }

    listEl.innerHTML = "";
    const selectedIds = getSelectedIdsForCategory(categoryId);

    if (!items || items.length === 0) {
      const label = OTHER_CATEGORY_TABS.find((t) => t.id === categoryId)?.label || "mods";
      loadingEl.textContent = `No ${label.toLowerCase()} found`;
      loadingEl.style.display = "block";
      return;
    }

    loadingEl.style.display = "none";

    // "None" deselect option (clears all selections for this category)
    {
      const noneItem = document.createElement("li");
      noneItem.setAttribute("data-other-id", "__none__");
      const noneRow = document.createElement("div");
      noneRow.className = "mod-name-row";
      const noneName = document.createElement("div");
      noneName.className = "mod-name none-label";
      noneName.textContent = "None";
      noneRow.appendChild(noneName);
      const noneBtn = document.createElement("button");
      noneBtn.className = "mod-select-button";
      const nothingSelected = selectedIds.length === 0;
      noneBtn.textContent = nothingSelected ? "Selected" : "Select";
      if (nothingSelected) { noneBtn.classList.add("selected"); noneItem.classList.add("selected-row"); }
      noneBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        // Deselect all items in this category
        const allSelectedLis = listEl.querySelectorAll("li.selected-row");
        allSelectedLis.forEach((li) => {
          if (li === noneItem) return;
          const btn = li.querySelector(".mod-select-button");
          if (btn) { btn.textContent = "Select"; btn.classList.remove("selected"); }
          li.classList.remove("selected-row");
        });
        // Emit deselect for each selected id
        const ids = getSelectedIdsForCategory(categoryId);
        for (const id of [...ids]) {
          if (bridge) bridge.send({ type: "select-other", category: categoryId, otherId: id, otherData: null, action: "deselect" });
        }
        ids.length = 0; // clear all
        noneBtn.textContent = "Selected"; noneBtn.classList.add("selected"); noneItem.classList.add("selected-row");
        refreshSummaryValues(); refreshButtonBadgeFromSelections();
      });
      noneRow.appendChild(noneBtn);
      noneItem.appendChild(noneRow);
      listEl.appendChild(noneItem);
    }

    items.forEach((other) => {
      const listItem = document.createElement("li");
      const otherId = other.id || other.name || `other-${Date.now()}-${Math.random()}`;

      const otherNameRow = document.createElement("div");
      otherNameRow.className = "mod-name-row";

      const otherName = document.createElement("div");
      otherName.className = "mod-name";
      otherName.textContent = cleanModName(other.name || other.modName) || "Unnamed mod";
      otherNameRow.appendChild(otherName);

      const selectButton = document.createElement("button");
      selectButton.className = "mod-select-button";
      listItem.setAttribute("data-other-id", otherId);

      if (selectedIds.includes(otherId)) {
        selectButton.textContent = "Selected";
        selectButton.classList.add("selected");
        listItem.classList.add("selected-row");
      } else {
        selectButton.textContent = "Select";
      }

      selectButton.addEventListener("click", (e) => {
        e.stopPropagation();
        handleCategoryModSelect(categoryId, otherId, selectButton, other);
      });

      otherNameRow.appendChild(selectButton);
      listItem.appendChild(otherNameRow);

      if (other.description) {
        const otherDesc = document.createElement("div");
        otherDesc.className = "mod-description";
        otherDesc.textContent = other.description;
        listItem.appendChild(otherDesc);
      }

      listEl.appendChild(listItem);
    });
  }

  function handleMapSelect(mapId, buttonElement, mapData) {
    const parentLi = buttonElement.closest("li");
    if (selectedMapId === mapId) {
      selectedMapId = null;
      buttonElement.textContent = "Select";
      buttonElement.classList.remove("selected");
      if (parentLi) parentLi.classList.remove("selected-row");
      if (bridge) bridge.send({ type: "select-map", mapId: null });
    } else {
      if (selectedMapId) {
        const prevLi = panel?._mapsList?.querySelector(
          `[data-map-id="${selectedMapId}"]`
        );
        if (prevLi) {
          const previousButton = prevLi.querySelector(".mod-select-button");
          if (previousButton) {
            previousButton.textContent = "Select";
            previousButton.classList.remove("selected");
          }
          prevLi.classList.remove("selected-row");
        }
      }
      selectedMapId = mapId;
      buttonElement.textContent = "Selected";
      buttonElement.classList.add("selected");
      if (parentLi) parentLi.classList.add("selected-row");
      if (bridge) bridge.send({ type: "select-map", mapId, mapData });
    }

    updateNoneRow(panel?._mapsList, !selectedMapId);
    refreshSummaryValues();
    refreshButtonBadgeFromSelections();
  }

  function handleFontSelect(fontId, buttonElement, fontData) {
    const parentLi = buttonElement.closest("li");
    if (selectedFontId === fontId) {
      selectedFontId = null;
      buttonElement.textContent = "Select";
      buttonElement.classList.remove("selected");
      if (parentLi) parentLi.classList.remove("selected-row");
      if (bridge) bridge.send({ type: "select-font", fontId: null });
    } else {
      if (selectedFontId) {
        const prevLi = panel?._fontsList?.querySelector(
          `[data-font-id="${selectedFontId}"]`
        );
        if (prevLi) {
          const previousButton = prevLi.querySelector(".mod-select-button");
          if (previousButton) {
            previousButton.textContent = "Select";
            previousButton.classList.remove("selected");
          }
          prevLi.classList.remove("selected-row");
        }
      }
      selectedFontId = fontId;
      buttonElement.textContent = "Selected";
      buttonElement.classList.add("selected");
      if (parentLi) parentLi.classList.add("selected-row");
      if (bridge) bridge.send({ type: "select-font", fontId, fontData });
    }

    updateNoneRow(panel?._fontsList, !selectedFontId);
    refreshSummaryValues();
    refreshButtonBadgeFromSelections();
  }

  function handleAnnouncerSelect(announcerId, buttonElement, announcerData) {
    const parentLi = buttonElement.closest("li");
    if (selectedAnnouncerId === announcerId) {
      selectedAnnouncerId = null;
      buttonElement.textContent = "Select";
      buttonElement.classList.remove("selected");
      if (parentLi) parentLi.classList.remove("selected-row");
      if (bridge) bridge.send({ type: "select-announcer", announcerId: null });
    } else {
      if (selectedAnnouncerId) {
        const prevLi = panel?._announcersList?.querySelector(
          `[data-announcer-id="${selectedAnnouncerId}"]`
        );
        if (prevLi) {
          const previousButton = prevLi.querySelector(".mod-select-button");
          if (previousButton) {
            previousButton.textContent = "Select";
            previousButton.classList.remove("selected");
          }
          prevLi.classList.remove("selected-row");
        }
      }
      selectedAnnouncerId = announcerId;
      buttonElement.textContent = "Selected";
      buttonElement.classList.add("selected");
      if (parentLi) parentLi.classList.add("selected-row");
      if (bridge) bridge.send({ type: "select-announcer", announcerId, announcerData });
    }

    updateNoneRow(panel?._announcersList, !selectedAnnouncerId);
    refreshSummaryValues();
    refreshButtonBadgeFromSelections();
  }

  function handleCategoryModSelect(categoryId, otherId, buttonElement, otherData) {
    const parentLi = buttonElement.closest("li");
    const selectedIds = getSelectedIdsForCategory(categoryId);
    const index = selectedIds.indexOf(otherId);
    if (index !== -1) {
      // Deselect
      selectedIds.splice(index, 1);
      buttonElement.textContent = "Select";
      buttonElement.classList.remove("selected");
      if (parentLi) parentLi.classList.remove("selected-row");
      if (bridge) bridge.send({ type: "select-other", category: categoryId, otherId, otherData, action: "deselect" });
    } else {
      // Select (add to array)
      selectedIds.push(otherId);
      buttonElement.textContent = "Selected";
      buttonElement.classList.add("selected");
      if (parentLi) parentLi.classList.add("selected-row");
      if (bridge) bridge.send({ type: "select-other", category: categoryId, otherId, otherData, action: "select" });
    }

    const listEl = panel?.[`_${categoryId}List`];
    updateNoneRow(listEl, selectedIds.length === 0);
    refreshSummaryValues();
    refreshButtonBadgeFromSelections();
  }

  function findButtonContainer() {
    // Find the bottom-right-buttons container to position the button above it
    return document.querySelector(".bottom-right-buttons");
  }

  function attachToChampionSelect() {
    // Attach as soon as champ select UI exists (even before a champion is locked)
    if (!championSelectRoot) {
      return;
    }

    createButton();
    createPanel();

    const targetContainer = findButtonContainer();
    if (!targetContainer) {
      // Retry after a short delay if container not found (DOM might not be ready)
      setTimeout(() => {
        if (championSelectRoot) {
          const retryContainer = findButtonContainer();
          if (retryContainer) {
            attachToChampionSelect();
          }
        }
      }, 100);
      return;
    }

    // Remove button from old parent if it exists
    if (button.parentNode) {
      button.parentNode.removeChild(button);
    }

    // Ensure container has relative positioning for absolute child
    const containerStyles = window.getComputedStyle(targetContainer);
    if (containerStyles.position === "static") {
      targetContainer.style.position = "relative";
    }

    // Position button absolutely above the container buttons
    button.style.position = "absolute";
    button.style.right = "0"; // Align with right edge of container
    button.style.bottom = "100%"; // Position above container
    button.style.marginBottom = "10px"; // 10px spacing above buttons
    button.style.left = "";
    button.style.top = "";
    button.style.width = "auto";
    button.style.height = "auto";
    button.style.padding = "";
    button.style.display = "block";
    button.style.visibility = "visible";
    button.style.opacity = "1";
    button.style.zIndex = "";
    button.style.transform = "";

    // Ensure badge positioning works - button needs to be relative for badge absolute positioning
    // But we need absolute for button positioning, so we'll use a wrapper or ensure badge uses button as reference
    // Actually, absolute children can still position relative to absolute parents, so this should work

    // Append to container (same structure as QUIT button)
    targetContainer.appendChild(button);

    // Store reference to container for repositioning
    button._container = targetContainer;

    // Force badge positioning after button is attached
    if (button._countBadge) {
      const badge = button._countBadge;
      badge.style.position = "absolute";
      badge.style.top = "0";
      badge.style.left = "0";
      badge.style.transform = "translate(-170%, -70%)";
      badge.style.zIndex = "10";
    }

    if (panel.parentNode !== document.body) {
      document.body.appendChild(panel);
    }
  }

  function detachFromChampionSelect() {
    if (button && button.parentNode) {
      button.parentNode.removeChild(button);
    }
    closePanel(); // Ensure panel is closed when detaching
  }

  function refreshUIVisibility() {
    // Show the button whenever we're in champ select; only the Skins tab content
    // is gated by champion lock/skin hover state.
    if (championSelectRoot) {
      attachToChampionSelect();
      return;
    }
    closePanel();
    detachFromChampionSelect();
  }

  function updateChampionSelectTarget() {
    const target = document.querySelector(".champion-select");
    if (target === championSelectRoot) {
      // Even if target is the same, check if button needs to be attached
      if (target && (!button || !button.parentNode)) {
        refreshUIVisibility();
      }
      return;
    }
    // New champion select detected - reset session tracking
    if (target && target !== championSelectRoot) {
      lastChampionSelectSession = target;
      isFirstOpenInSession = true;
    }
    championSelectRoot = target;
    refreshUIVisibility();
  }

  function observeChampionSelect() {
    if (championSelectObserver || !document.body) {
      return;
    }
    championSelectObserver = new MutationObserver(() => {
      updateChampionSelectTarget();
    });
    championSelectObserver.observe(document.body, {
      childList: true,
      subtree: true,
    });
  }

  function openPanel() {
    if (!championSelectRoot) {
      return;
    }

    attachToChampionSelect();

    if (!panel || !button) {
      return;
    }

    // Create panel if it doesn't exist
    if (!panel.parentNode) {
      document.body.appendChild(panel);
    }

    // Show panel
    panel.style.display = "block";
    panel.style.pointerEvents = "none"; // Will be set to "all" by flyout frame

    // Only switch to Skins tab on first open in this champ select session
    // Otherwise, keep the last selected tab
    if (isFirstOpenInSession) {
      activeTab = "skins";
      isFirstOpenInSession = false;
    }

    // Always start in summary view when opening the panel
    setRightPaneMode("summary");
    refreshSummaryValues();

    // Update tab content based on activeTab (generic)
    panel.querySelectorAll(".tab-content").forEach((content) => {
      if (content && content.dataset && content.dataset.tab === activeTab) {
        content.classList.add("active");
      } else if (content) {
        content.classList.remove("active");
      }
    });

    // Request data for the active tab
    if (activeTab === "skins") {
      requestModsForCurrentSkin();
    } else if (activeTab === "maps") {
      requestMaps();
    } else if (activeTab === "fonts") {
      requestFonts();
    } else if (activeTab === "announcers") {
      requestAnnouncers();
    } else if (OTHER_CATEGORY_TABS.some((t) => t.id === activeTab)) {
      if (lastCategoryModsById[activeTab]) {
        updateOtherCategoryEntries(activeTab, lastCategoryModsById[activeTab]);
      } else {
        requestCategoryMods(activeTab);
      }
    }

    // Initial positioning (will be repositioned after width is calculated)
    positionPanel(panel, button);

    // Force a reflow
    panel.offsetHeight;

    // Reposition after render
    setTimeout(() => {
      positionPanel(panel, button);
    }, 0);

    isOpen = true;

    // Update button pressed state
    if (button) {
      button.classList.add("pressed");
    }

    // Request data for all tabs when panel opens (in background, but don't switch to them)
    requestModsForCurrentSkin();
    requestMaps();
    requestFonts();
    requestAnnouncers();
    for (const t of OTHER_CATEGORY_TABS) {
      requestCategoryMods(t.id);
    }

    // Add click outside handler
    const closeHandler = (e) => {
      if (
        panel &&
        panel.parentNode &&
        !panel.contains(e.target) &&
        !button.contains(e.target)
      ) {
        closePanel();
        document.removeEventListener("click", closeHandler);
      }
    };
    setTimeout(() => {
      document.addEventListener("click", closeHandler);
    }, 100);
  }

  function closePanel() {
    if (!panel) {
      isOpen = false;
      // Update button pressed state
      if (button) {
        button.classList.remove("pressed");
      }
      return;
    }
    // Hide panel but keep it in DOM for reuse
    if (panel.parentNode) {
      panel.style.display = "none";
      panel.style.pointerEvents = "none";
    }
    isOpen = false;

    // Update button pressed state
    if (button) {
      button.classList.remove("pressed");
    }

    // Keep selections when closing; users use the panel for quick checking/changing.
  }

  function requestModsForCurrentSkin() {
    const state = window.__roseSkinState || {};
    const championId = Number(state.championId);
    const skinId = Number(state.skinId);

    // Skins are only meaningful once a champion is locked in champ select.
    if (!championLocked) {
      // Badge reflects selected mods across categories; don't zero it here.
      if (panel && panel._modsLoading) {
        panel._modsLoading.textContent = "Waiting for champ lock…";
        panel._modsLoading.style.display = "block";
      }
      return;
    }

    // Clear selection when navigating to a skin that differs from the mod's target.
    if (selectedModId && selectedModSkinId != null && Number(selectedModSkinId) !== skinId) {
      selectedModId = null;
      selectedModSkinId = null;
      // Notify backend so it clears selected_custom_mod and the popup
      if (bridge) bridge.send({ type: "select-skin-mod", championId, skinId, modId: null });
    }

    if (!championId || !skinId) {
      // Badge reflects selected mods across categories; don't zero it here.
      if (panel && panel._modsLoading) {
        panel._modsLoading.textContent = "Hover a skin…";
        panel._modsLoading.style.display = "block";
      }
      return;
    }

    if (bridge) bridge.send({ type: REQUEST_TYPE, championId, skinId });

    if (panel && panel._modsLoading) {
      panel._modsLoading.textContent = "Checking for mods…";
      panel._modsLoading.style.display = "block";
    }
  }

  // Request maps - global (not skin-specific)
  // Backend should look in: %LOCALAPPDATA%\Rose\mods\maps
  function requestMaps() {
    if (bridge) bridge.send({ type: "request-maps" });
    if (panel && panel._mapsLoading) {
      panel._mapsLoading.textContent = "Loading maps…";
      panel._mapsLoading.style.display = "block";
    }
  }

  // Request fonts - global (not skin-specific)
  // Backend should look in: %LOCALAPPDATA%\Rose\mods\fonts
  function requestFonts() {
    if (bridge) bridge.send({ type: "request-fonts" });
    if (panel && panel._fontsLoading) {
      panel._fontsLoading.textContent = "Loading fonts…";
      panel._fontsLoading.style.display = "block";
    }
  }

  // Request announcers - global (not skin-specific)
  // Backend should look in: %LOCALAPPDATA%\Rose\mods\announcers
  function requestAnnouncers() {
    if (bridge) bridge.send({ type: "request-announcers" });
    if (panel && panel._announcersLoading) {
      panel._announcersLoading.textContent = "Loading announcers…";
      panel._announcersLoading.style.display = "block";
    }
  }

  // Request category mods - global (not skin-specific)
  // Backend should look in: %LOCALAPPDATA%\Rose\mods\<category>
  function requestCategoryMods(categoryId) {
    if (!categoryId) return;
    if (bridge) bridge.send({ type: "request-category-mods", category: categoryId });
    if (!panel) return;

    const loadingEl = panel[`_${categoryId}Loading`] || panel._othersLoading;
    if (loadingEl) {
      const label = OTHER_CATEGORY_TABS.find((t) => t.id === categoryId)?.label || "mods";
      loadingEl.textContent = `Loading ${label.toLowerCase()}…`;
      loadingEl.style.display = "block";
    }
  }

  // Legacy alias (kept for compatibility)
  function requestOthers() {
    requestCategoryMods(activeTab || "others");
  }

  function handleSkinState(event) {
    // Always request mods to update badge, even if panel is not open
    requestModsForCurrentSkin();

    if (!isOpen) {
      return;
    }
  }

  function updateButtonBadge(count) {
    if (!button || !button._countBadge) {
      return;
    }
    const badge = button._countBadge;
    // Ensure badge positioning is always correct
    badge.style.position = "absolute";
    badge.style.top = "0";
    badge.style.left = "0";
    badge.style.transform = "translate(-170%, -70%)";
    badge.style.zIndex = "10";

    if (count > 0) {
      badge.textContent = String(count);
      badge.style.display = "flex"; // Explicitly set to flex to match CSS
    } else {
      badge.textContent = "0"; // Reset text content
      badge.style.display = "none";
    }
  }

  // Badge should reflect how many mods are currently selected (across all categories),
  // not how many mods are available for the hovered skin.
  function getSelectedModsCount() {
    let count = 0;
    // Skins are only meaningful after champ lock.
    if (championLocked && selectedModId) count += 1;
    if (selectedMapId) count += 1;
    if (selectedFontId) count += 1;
    if (selectedAnnouncerId) count += 1;
    // Sum the unique selections per category (UI / VO / Loading Screen / VFX / SFX / Others).
    for (const t of OTHER_CATEGORY_TABS) {
      const ids = getSelectedIdsForCategory(t.id);
      if (Array.isArray(ids) && ids.length) {
        count += new Set(ids).size;
      }
    }
    return count;
  }

  function refreshButtonBadgeFromSelections() {
    updateButtonBadge(getSelectedModsCount());
  }

  function handleModsResponse(event) {
    const detail = event?.detail;
    if (!detail || detail.type !== "skin-mods-response") {
      return;
    }

    const championId = Number(detail?.championId);
    const skinId = Number(detail?.skinId);
    if (!championId || !skinId) {
      // Badge reflects selected mods across categories; don't zero it due to missing hover state.
      refreshButtonBadgeFromSelections();
      return;
    }

    // Store current skin data for selection restoration
    currentSkinData = { championId, skinId };

    // Use the LIVE skin state for clearing / auto-select checks.
    // The response's skinId can be stale if the user navigated away while
    // the request was in flight.
    const liveSkinId = Number((window.__roseSkinState || {}).skinId) || skinId;

    // Clear selection when the currently hovered skin differs from the mod's target skin.
    if (selectedModId && selectedModSkinId != null && Number(selectedModSkinId) !== liveSkinId) {
      selectedModId = null;
      selectedModSkinId = null;
      // Notify backend so it clears selected_custom_mod and the popup
      if (bridge) bridge.send({ type: "select-skin-mod", championId, skinId: liveSkinId, modId: null });
    }

    const mods = Array.isArray(detail.mods) ? detail.mods : [];

    // Auto-select the historic mod when the user is hovering the skin it targets.
    const historicMod = detail.historicMod;
    let didAutoSelect = false;
    if (historicMod && !selectedModId) {
      // Find the mod that matches the historic path
      const historicModEntry = mods.find(mod => {
        const modPath = mod.relativePath || "";
        // Normalize paths for comparison
        return modPath.replace(/\\/g, "/") === historicMod.replace(/\\/g, "/");
      });

      if (historicModEntry) {
        const modTargetSkinId = historicModEntry.skinId ? Number(historicModEntry.skinId) : null;
        // Only auto-select if the user is CURRENTLY on the mod's target skin
        if (modTargetSkinId && modTargetSkinId === liveSkinId) {
          const modId = historicModEntry.relativePath || historicModEntry.modName || `mod-${Date.now()}-${Math.random()}`;
          selectedModId = modId;
          selectedModSkinId = modTargetSkinId;
          didAutoSelect = true;
        }
      }
    }

    // Emit to backend immediately when historic auto-select fires, regardless
    // of whether the panel is open.  The backend needs this to broadcast the
    // custom-mod state so the mod-name popup appears.
    if (didAutoSelect) {
      const autoMod = mods.find(mod => {
        const modPath = mod.relativePath || mod.modName || "";
        return modPath === selectedModId || mod.relativePath === selectedModId;
      });
      if (autoMod) {
        const emitSkinId = autoMod.skinId ? Number(autoMod.skinId) : skinId;
        if (bridge) bridge.send({ type: "select-skin-mod", championId, skinId: emitSkinId, modId: selectedModId, modData: autoMod });
      }
    }

    // Keep Summary accurate even if the panel hasn't been opened yet
    refreshSummaryValues();
    refreshButtonBadgeFromSelections();

    if (!isOpen) {
      return;
    }

    updateModEntries(mods);

    // If the panel is open and the historic mod was auto-selected, mark its button
    if (didAutoSelect && selectedModId) {
      const button = panel?._modList?.querySelector(
        `[data-mod-id="${selectedModId}"] .mod-select-button`
      );
      if (button) {
        button.textContent = "Selected";
        button.classList.add("selected");
      }
    }
  }

  function handleMapsResponse(event) {
    const detail = event?.detail;
    if (!detail || detail.type !== "maps-response") {
      return;
    }

    const mapsList = Array.isArray(detail.maps) ? detail.maps : [];

    // Check for historic mod and auto-select it
    const historicMod = detail.historicMod;
    if (historicMod && !selectedMapId) {
      // Find the mod that matches the historic path
      // historicMod is the relative path (e.g., "maps/default-summoner-rift_1.0.1")
      // map.id is also the relative path
      const historicMap = mapsList.find(map => {
        const mapId = map.id || "";
        // Normalize paths for comparison
        return mapId.replace(/\\/g, "/") === historicMod.replace(/\\/g, "/");
      });

      if (historicMap) {
        // Use the same ID format as updateMapsEntries uses
        const mapId = historicMap.id || historicMap.name || `map-${Date.now()}-${Math.random()}`;
        selectedMapId = mapId;
      }
    }

    refreshSummaryValues();
    refreshButtonBadgeFromSelections();

    if (isOpen && rightPaneMode === "picker" && activeTab === "maps") {
      updateMapsEntries(mapsList);
    }

    // After UI is updated, emit selection to backend if historic mod was found
    if (historicMod && selectedMapId) {
      const historicMap = mapsList.find(map => {
        const mapId = map.id || map.name || `map-${Date.now()}-${Math.random()}`;
        return mapId === selectedMapId;
      });
      if (historicMap) {
        // Find the button and update it, then emit
        const button = panel?._mapsList?.querySelector(
          `[data-map-id="${selectedMapId}"] .mod-select-button`
        );
        if (button) {
          button.textContent = "Selected";
          button.classList.add("selected");
        }
        if (bridge) bridge.send({ type: "select-map", mapId: selectedMapId, mapData: historicMap });
      }
    }
  }

  function handleFontsResponse(event) {
    const detail = event?.detail;
    if (!detail || detail.type !== "fonts-response") {
      return;
    }

    const fontsList = Array.isArray(detail.fonts) ? detail.fonts : [];

    // Check for historic mod and auto-select it
    const historicMod = detail.historicMod;
    if (historicMod && !selectedFontId) {
      // Find the mod that matches the historic path
      const historicFont = fontsList.find(font => {
        const fontId = font.id || "";
        // Normalize paths for comparison
        return fontId.replace(/\\/g, "/") === historicMod.replace(/\\/g, "/");
      });

      if (historicFont) {
        const fontId = historicFont.id || historicFont.name || `font-${Date.now()}-${Math.random()}`;
        selectedFontId = fontId;
      }
    }

    refreshSummaryValues();
    refreshButtonBadgeFromSelections();

    if (isOpen && rightPaneMode === "picker" && activeTab === "fonts") {
      updateFontsEntries(fontsList);
    }

    // After UI is updated, emit selection to backend if historic mod was found
    if (historicMod && selectedFontId) {
      const historicFont = fontsList.find(font => {
        const fontId = font.id || font.name || `font-${Date.now()}-${Math.random()}`;
        return fontId === selectedFontId;
      });
      if (historicFont) {
        // Find the button and update it, then emit
        const button = panel?._fontsList?.querySelector(
          `[data-font-id="${selectedFontId}"] .mod-select-button`
        );
        if (button) {
          button.textContent = "Selected";
          button.classList.add("selected");
        }
        if (bridge) bridge.send({ type: "select-font", fontId: selectedFontId, fontData: historicFont });
      }
    }
  }

  function handleAnnouncersResponse(event) {
    const detail = event?.detail;
    if (!detail || detail.type !== "announcers-response") {
      return;
    }

    const announcersList = Array.isArray(detail.announcers) ? detail.announcers : [];

    // Check for historic mod and auto-select it
    const historicMod = detail.historicMod;
    if (historicMod && !selectedAnnouncerId) {
      // Find the mod that matches the historic path
      const historicAnnouncer = announcersList.find(announcer => {
        const announcerId = announcer.id || "";
        // Normalize paths for comparison
        return announcerId.replace(/\\/g, "/") === historicMod.replace(/\\/g, "/");
      });

      if (historicAnnouncer) {
        const announcerId = historicAnnouncer.id || historicAnnouncer.name || `announcer-${Date.now()}-${Math.random()}`;
        selectedAnnouncerId = announcerId;
      }
    }

    refreshSummaryValues();
    refreshButtonBadgeFromSelections();

    if (isOpen && rightPaneMode === "picker" && activeTab === "announcers") {
      updateAnnouncersEntries(announcersList);
    }

    // After UI is updated, emit selection to backend if historic mod was found
    if (historicMod && selectedAnnouncerId) {
      const historicAnnouncer = announcersList.find(announcer => {
        const announcerId = announcer.id || announcer.name || `announcer-${Date.now()}-${Math.random()}`;
        return announcerId === selectedAnnouncerId;
      });
      if (historicAnnouncer) {
        // Find the button and update it, then emit
        const button = panel?._announcersList?.querySelector(
          `[data-announcer-id="${selectedAnnouncerId}"] .mod-select-button`
        );
        if (button) {
          button.textContent = "Selected";
          button.classList.add("selected");
        }
        if (bridge) bridge.send({ type: "select-announcer", announcerId: selectedAnnouncerId, announcerData: historicAnnouncer });
      }
    }
  }

  function handleOthersResponse(event) {
    const detail = event?.detail;
    if (!detail || detail.type !== "others-response") {
      return;
    }

    const othersList = Array.isArray(detail.others) ? detail.others : [];
    lastCategoryModsById["others"] = othersList;

    // Check for historic mod(s) and auto-select them
    // historicMod can be a string (legacy) or an array (new format)
    const historicMod = detail.historicMod;
    const historicMods = Array.isArray(historicMod) ? historicMod : (historicMod ? [historicMod] : []);
    
    const selectedIds = getSelectedIdsForCategory("others");
    if (historicMods.length > 0 && selectedIds.length === 0) {
      // Find all mods that match the historic paths
      const historicOthers = [];
      for (const historicPath of historicMods) {
        const historicOther = othersList.find(other => {
          const otherId = other.id || "";
          // Normalize paths for comparison
          return otherId.replace(/\\/g, "/") === String(historicPath).replace(/\\/g, "/");
        });
        if (historicOther) {
          historicOthers.push(historicOther);
        }
      }

      // Add all historic mods to selected list
      for (const historicOther of historicOthers) {
        const otherId = historicOther.id || historicOther.name || `other-${Date.now()}-${Math.random()}`;
        if (!selectedIds.includes(otherId)) {
          selectedIds.push(otherId);
        }
      }
    }

    refreshSummaryValues();
    refreshButtonBadgeFromSelections();

    if (!isOpen || rightPaneMode !== "picker" || !OTHER_CATEGORY_TABS.some((t) => t.id === activeTab)) {
      return;
    }

    updateOtherCategoryEntries("others", othersList);

    // After UI is updated, emit selection to backend for all historic mods found
    if (historicMods.length > 0 && selectedIds.length > 0) {
      for (const historicPath of historicMods) {
        const historicOther = othersList.find(other => {
          const otherId = other.id || "";
          return otherId.replace(/\\/g, "/") === String(historicPath).replace(/\\/g, "/");
        });
        if (historicOther) {
          const otherId = historicOther.id || historicOther.name || `other-${Date.now()}-${Math.random()}`;
          // Find the button and update it, then emit
          const button = OTHER_CATEGORY_TABS.map((t) => panel?.[`_${t.id}List`])
            .filter(Boolean)
            .map((listEl) =>
              listEl.querySelector(`[data-other-id="${otherId}"] .mod-select-button`)
            )
            .find(Boolean);
          if (button) {
            button.textContent = "Selected";
            button.classList.add("selected");
          }
          if (bridge) bridge.send({ type: "select-other", category: "others", otherId, otherData: historicOther, action: "select" });
        }
      }
    }
  }

  function handleCategoryModsResponse(event) {
    const detail = event?.detail;
    if (!detail || detail.type !== "category-mods-response") {
      return;
    }

    const category = String(detail.category || "").trim();
    if (!OTHER_CATEGORY_TABS.some((t) => t.id === category)) {
      return;
    }

    const modsList = Array.isArray(detail.mods) ? detail.mods : [];
    lastCategoryModsById[category] = modsList;

    // Apply historic selections for this specific category.
    const historicMod = detail.historicMod;
    const historicMods = Array.isArray(historicMod) ? historicMod : (historicMod ? [historicMod] : []);
    if (historicMods.length > 0) {
      for (const historicPath of historicMods) {
        const match = modsList.find((m) => {
          const id = (m?.id || "").replace(/\\/g, "/");
          return id === String(historicPath).replace(/\\/g, "/");
        });
        if (!match) continue;
        const otherId = match.id || match.name || `other-${Date.now()}-${Math.random()}`;
        const selectedIds = getSelectedIdsForCategory(category);
        if (!selectedIds.includes(otherId)) {
          selectedIds.push(otherId);
        }
        const key = `${category}:${otherId}`;
        if (!emittedHistoricSelectionKeys.has(key)) {
          emittedHistoricSelectionKeys.add(key);
          if (bridge) bridge.send({ type: "select-other", category, otherId, otherData: match, action: "select" });
        }
      }
    }

    refreshSummaryValues();
    refreshButtonBadgeFromSelections();

    if (!isOpen || rightPaneMode !== "picker" || activeTab !== category) {
      return;
    }

    updateOtherCategoryEntries(category, modsList);

    // Update visible button states for already-selected items
    const listEl = panel?.[`_${category}List`];
    if (listEl) {
      for (const otherId of getSelectedIdsForCategory(category)) {
        const btn = listEl.querySelector(`[data-other-id="${otherId}"] .mod-select-button`);
        if (btn) {
          btn.textContent = "Selected";
          btn.classList.add("selected");
        }
      }
    }
  }

  function handleChampionLocked(event) {
    const locked = Boolean(event?.detail?.locked);
    if (locked === championLocked) {
      // Even if state is the same, ensure button is attached if it should be
      if (locked && championSelectRoot && (!button || !button.parentNode)) {
        refreshUIVisibility();
      }
      return;
    }

    // If a new champion is being locked, only clear SKIN-specific selections.
    // Global selections (maps/fonts/announcers/UI/VO/VFX/...) should persist across champ locks.
    if (locked && !championLocked) {
      selectedModId = null;
      selectedModSkinId = null;
      // New champ select session - reset to first open
      lastChampionSelectSession = championSelectRoot;
      isFirstOpenInSession = true;
    }

    championLocked = locked;
    refreshUIVisibility();
    refreshSummaryValues();
    refreshButtonBadgeFromSelections();

    // Additional retry after lock state changes to ensure button appears
    if (locked) {
      setTimeout(() => {
        if (championLocked && championSelectRoot && (!button || !button.parentNode)) {
          refreshUIVisibility();
        }
      }, 200);
    }
  }

  function whenReady(cb) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", cb, { once: true });
      return;
    }
    cb();
  }

  whenReady(async () => {
    try {
      bridge = await waitForBridge();
      console.log(`${LOG_PREFIX} Bridge connected`);
    } catch (e) {
      console.error(`${LOG_PREFIX} Failed to connect to bridge:`, e);
    }

    injectCSS();
    createButton();
    createPanel();
    updateChampionSelectTarget();
    observeChampionSelect();

    // Keep the skin-state window event (published by SkinMonitor via CustomEvent)
    window.addEventListener(EVENT_SKIN_STATE, handleSkinState, {
      passive: true,
    });

    // Subscribe to bridge messages instead of window CustomEvents
    if (bridge) {
      bridge.subscribe("skin-mods-response", (data) => handleModsResponse({ detail: data }));
      bridge.subscribe("maps-response", (data) => handleMapsResponse({ detail: data }));
      bridge.subscribe("fonts-response", (data) => handleFontsResponse({ detail: data }));
      bridge.subscribe("announcers-response", (data) => handleAnnouncersResponse({ detail: data }));
      bridge.subscribe("category-mods-response", (data) => handleCategoryModsResponse({ detail: data }));
      bridge.subscribe("others-response", (data) => handleOthersResponse({ detail: data }));
      bridge.subscribe("champion-locked", (data) => handleChampionLocked({ detail: data }));
      bridge.subscribe("custom-mod-state", (data) => {
        if (!data.active && selectedModId) {
          selectedModId = null;
          selectedModSkinId = null;
          if (panel && panel._modList) {
            panel._modList.querySelectorAll("li.selected-row").forEach((li) => {
              li.classList.remove("selected-row");
              const btn = li.querySelector(".mod-select-button");
              if (btn) { btn.textContent = "Select"; btn.classList.remove("selected"); }
            });
            updateNoneRow(panel._modList, true);
          }
          refreshSummaryValues();
          refreshButtonBadgeFromSelections();
        }
      });

      // Request initial data on every (re)connect
      bridge.onReady(() => {
        requestMaps();
        requestFonts();
        requestAnnouncers();
        for (const t of OTHER_CATEGORY_TABS) {
          requestCategoryMods(t.id);
        }
      });
    }

    // Reposition button when skin changes
    const repositionButton = () => {
      // Button is now part of container flow, so no manual repositioning needed
      // Just check if button needs to be reattached
      if (button && !button.parentNode && championSelectRoot) {
        attachToChampionSelect();
      }
      // Reposition panel if it's open
      if (isOpen && panel && button) {
        positionPanel(panel, button);
      }
    };

    window.addEventListener("resize", repositionButton);
    window.addEventListener("scroll", repositionButton);

    // Periodic check to ensure button is attached on first champion select
    // This handles cases where events fire before DOM is ready
    let attachmentCheckInterval = setInterval(() => {
      if (championSelectRoot) {
        if (!button || !button.parentNode) {
          refreshUIVisibility();
        } else {
          // Button is attached, stop checking
          clearInterval(attachmentCheckInterval);
        }
      }
    }, 500);

    // Stop checking after 10 seconds to avoid infinite checking
    setTimeout(() => {
      clearInterval(attachmentCheckInterval);
    }, 10000);
  });
})();
