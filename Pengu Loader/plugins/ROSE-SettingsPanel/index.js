/**
 * @name Rose-SettingsPanel
 * @author Rose Team
 * @description Settings panel for Rose
 * @link https://github.com/FlorentTariolle/ROSE-SettingsPanel
 */
(function initSettingsPanel() {
  const LOG_PREFIX = "[Rose-SettingsPanel]";
  let BRIDGE_PORT = 50000; // Default, will be updated from /bridge-port endpoint
  let BRIDGE_URL = `ws://127.0.0.1:${BRIDGE_PORT}`;
  const BRIDGE_PORT_STORAGE_KEY = "rose_bridge_port";
  const DISCOVERY_START_PORT = 50000;
  const DISCOVERY_END_PORT = 50010;
  const DISCORD_INVITE_URL = "https://discord.gg/PHVUppft";
  const KOFI_URL = "https://ko-fi.com/roseapp";
  const GITHUB_URL = "https://github.com/Alban1911/Rose";

  const PANEL_ID = "rose-settings-panel";
  const FLYOUT_ID = "rose-settings-flyout";

  /**
   * Escape HTML special characters to prevent XSS (CWE-79)
   * @param {string} str - String to escape
   * @returns {string} Escaped string safe for innerHTML
   */
  function escapeHtml(str) {
    if (typeof str !== 'string') return str;
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  let bridgeSocket = null;
  let bridgeReady = false;
  let bridgeQueue = [];
  let settingsPanel = null;
  let currentSettings = {
    threshold: 0.5,
    monitorAutoResumeTimeout: 60,
    autostart: false,
    gamePath: "",
    gamePathValid: false,
  };
  let pathValidationTimeout = null;

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
                BRIDGE_URL = `ws://127.0.0.1:${BRIDGE_PORT}`;
                console.log(`${LOG_PREFIX} Loaded bridge port from cache: ${BRIDGE_PORT}`);
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
            BRIDGE_URL = `ws://127.0.0.1:${BRIDGE_PORT}`;
            localStorage.setItem(BRIDGE_PORT_STORAGE_KEY, String(BRIDGE_PORT));
            console.log(`${LOG_PREFIX} Loaded bridge port: ${BRIDGE_PORT}`);
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
            BRIDGE_URL = `ws://127.0.0.1:${BRIDGE_PORT}`;
            localStorage.setItem(BRIDGE_PORT_STORAGE_KEY, String(BRIDGE_PORT));
            console.log(`${LOG_PREFIX} Loaded bridge port: ${BRIDGE_PORT}`);
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
          BRIDGE_URL = `ws://127.0.0.1:${BRIDGE_PORT}`;
          localStorage.setItem(BRIDGE_PORT_STORAGE_KEY, String(BRIDGE_PORT));
          console.log(`${LOG_PREFIX} Loaded bridge port: ${BRIDGE_PORT}`);
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
          BRIDGE_URL = `ws://127.0.0.1:${BRIDGE_PORT}`;
          localStorage.setItem(BRIDGE_PORT_STORAGE_KEY, String(BRIDGE_PORT));
          console.log(`${LOG_PREFIX} Loaded bridge port (legacy): ${BRIDGE_PORT}`);
          return true;
        }
      }

      console.warn(`${LOG_PREFIX} Failed to load bridge port, using default (50000)`);
      return false;
    } catch (e) {
      console.warn(`${LOG_PREFIX} Error loading bridge port:`, e);
      return false;
    }
  }

  function getCSSRules() {
    return `
    @keyframes roseWarningPulse {
      0%   { filter: drop-shadow(0 0 0 rgba(255, 70, 70, 0.00)) drop-shadow(0 0 0 rgba(255, 70, 70, 0.00)); opacity: 0.95; }
      50%  { filter: drop-shadow(0 0 6px rgba(255, 70, 70, 0.90)) drop-shadow(0 0 12px rgba(255, 70, 70, 0.45)); opacity: 1.00; }
      100% { filter: drop-shadow(0 0 0 rgba(255, 70, 70, 0.00)) drop-shadow(0 0 0 rgba(255, 70, 70, 0.00)); opacity: 0.95; }
    }

    .rose-warning-glow {
      animation: roseWarningPulse 1.35s ease-in-out infinite;
      will-change: filter, opacity;
    }

    @font-face {
      font-family: "Beaufort for LOL";
      src: url("http://127.0.0.1:${BRIDGE_PORT}/asset/BeaufortforLOL-Regular.ttf") format("truetype");
      font-weight: normal;
      font-style: normal;
      font-display: swap;
    }
    
    @font-face {
      font-family: "Beaufort for LOL";
      src: url("http://127.0.0.1:${BRIDGE_PORT}/asset/BeaufortforLOL-Bold.ttf") format("truetype");
      font-weight: bold;
      font-style: normal;
      font-display: swap;
    }

    /* Diagnostics / Troubleshooting dialog scrollbar (avoid native Windows scrollbar look) */
    #rose-diagnostics-body {
      scrollbar-width: thin;
      scrollbar-color: #463714 rgba(0, 0, 0, 0.25);
    }

    #rose-diagnostics-body::-webkit-scrollbar {
      width: 10px;
    }

    #rose-diagnostics-body::-webkit-scrollbar:horizontal {
      display: none !important;
      height: 0 !important;
    }

    #rose-diagnostics-body::-webkit-scrollbar-track {
      background: rgba(0, 0, 0, 0.25);
      border-left: 1px solid rgba(70, 55, 20, 0.55);
    }

    #rose-diagnostics-body::-webkit-scrollbar-thumb {
      background: linear-gradient(to bottom, rgba(200, 155, 60, 0.22), rgba(70, 55, 20, 0.85));
      border: 1px solid rgba(70, 55, 20, 0.95);
      border-radius: 10px;
      min-height: 28px;
    }

    #rose-diagnostics-body::-webkit-scrollbar-thumb:hover {
      background: linear-gradient(to bottom, rgba(200, 155, 60, 0.32), rgba(70, 55, 20, 0.95));
    }

    #rose-diagnostics-body::-webkit-scrollbar-corner {
      background: transparent;
    }
    
    #${PANEL_ID} {
      position: fixed;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      z-index: 10000;
      pointer-events: none;
    }
    
    #${PANEL_ID} .flyout-container {
      pointer-events: all;
    }
    
    lol-uikit-flyout-frame#${FLYOUT_ID},
    #${FLYOUT_ID} {
      min-width: 360px !important;
      max-width: 400px !important;
      background: transparent !important;
      background-color: transparent !important;
      background-image: none !important;
      border-radius: 0 !important;
      padding: 0 !important;
      color: #cdbe91;
      font-family: "Beaufort for LOL", serif;
      display: flex !important;
      flex-direction: column !important;
      align-items: center !important;
      box-shadow: none !important;
      border: none !important;
      margin: 0 !important;
      overflow: visible !important;
      transform-origin: top center !important;
    }
    
    lol-uikit-flyout-frame#${FLYOUT_ID}::before,
    lol-uikit-flyout-frame#${FLYOUT_ID}::after,
    #${FLYOUT_ID}::before,
    #${FLYOUT_ID}::after {
      display: none !important;
      background: none !important;
      background-color: transparent !important;
      background-image: none !important;
      content: none !important;
    }
    
    lol-uikit-flyout-frame#${FLYOUT_ID} lc-flyout-content,
    lol-uikit-flyout-frame#${FLYOUT_ID} .lc-flyout-content,
    #${FLYOUT_ID} lc-flyout-content,
    #${FLYOUT_ID} .lc-flyout-content {
      background: #010a13 !important;
      background-color: #010a13 !important;
      background-image: none !important;
      border-radius: 0 !important;
      padding: 20px !important;
      width: 100% !important;
      box-sizing: border-box !important;
      border: none !important;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5) !important;
      margin: 0 !important;
    }
    
    #${FLYOUT_ID} .settings-title {
      font-size: 18px;
      font-weight: bold !important;
      margin-bottom: 12px;
      color: #c8aa6e;
      text-align: center;
      width: 100%;
    }
    
    #${FLYOUT_ID} .settings-section {
      margin-bottom: 12px;
      width: 100%;
    }
    
    #${FLYOUT_ID} .settings-label {
      display: block;
      margin-bottom: 8px;
      font-size: 14px;
      color: #cdbe91;
    }
    
    #${FLYOUT_ID} .settings-value {
      display: inline-block;
      margin-left: 10px;
      font-size: 14px;
      color: #c8aa6e;
      min-width: 50px;
    }

    #${FLYOUT_ID} .rose-tooltip-wrapper {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      position: relative;
      margin-right: 8px;
      top: 3px;
    }

    #${FLYOUT_ID} .rose-tooltip-icon {
      width: 14px;
      height: 14px;
      background-image: url("http://127.0.0.1:${BRIDGE_PORT}/asset/tooltip.png");
      background-size: contain;
      background-repeat: no-repeat;
      background-position: center;
      opacity: 0.85;
      cursor: help;
      border: none;
      padding: 0;
      margin: 0;
      outline: none;
      background-color: transparent;
    }

    #${FLYOUT_ID} .rose-tooltip-icon:hover {
      opacity: 1;
    }

    #${FLYOUT_ID} .rose-tooltip-icon:focus-visible {
      outline: 1px solid #c8aa6e;
      outline-offset: 2px;
      border-radius: 3px;
    }

    /* Tooltip bubble is rendered globally (outside flyout) */
    #rose-global-tooltip {
      position: fixed;
      left: 0;
      top: 0;
      width: 340px;
      max-width: 340px;
      box-sizing: border-box;
      padding: 10px 12px;
      background: #0b1a2a;
      border: 1px solid #5c5b56;
      color: #cdbe91;
      font-size: 12px;
      line-height: 1.35;
      white-space: pre-line;
      text-align: justify;
      text-justify: inter-word;
      box-shadow: 0 10px 28px rgba(0, 0, 0, 0.65);
      opacity: 0;
      visibility: hidden;
      transform: translateY(2px);
      transition: opacity 0.12s ease, transform 0.12s ease;
      z-index: 100050;
      pointer-events: none;
      font-family: "Beaufort for LOL", serif;
    }

    #rose-global-tooltip[data-show="true"] {
      opacity: 1;
      visibility: visible;
      transform: translateY(0px);
    }

    #rose-global-tooltip::after {
      content: "";
      position: absolute;
      left: var(--rose-tooltip-arrow-x, 50%);
      transform: translateX(-50%);
      width: 0;
      height: 0;
      border-left: 7px solid transparent;
      border-right: 7px solid transparent;
    }

    #rose-global-tooltip::before {
      content: "";
      position: absolute;
      left: var(--rose-tooltip-arrow-x, 50%);
      transform: translateX(-50%);
      width: 0;
      height: 0;
      border-left: 8px solid transparent;
      border-right: 8px solid transparent;
      z-index: -1;
    }

    /* Tooltip ABOVE the icon (arrow on bottom) */
    #rose-global-tooltip[data-placement="top"]::after {
      top: 100%;
      border-top: 7px solid #0b1a2a;
    }

    #rose-global-tooltip[data-placement="top"]::before {
      top: 100%;
      border-top: 8px solid #5c5b56;
      margin-top: 1px;
    }

    /* Tooltip BELOW the icon (arrow on top) */
    #rose-global-tooltip[data-placement="bottom"]::after {
      top: -7px;
      border-bottom: 7px solid #0b1a2a;
    }

    #rose-global-tooltip[data-placement="bottom"]::before {
      top: -8px;
      border-bottom: 8px solid #5c5b56;
      margin-top: -1px;
    }
    
    #${FLYOUT_ID} .settings-slider {
      width: 100%;
      height: 6px;
      background: #3c3c41;
      border-radius: 3px;
      outline: none;
      -webkit-appearance: none;
      margin: 6px 0;
    }
    
    #${FLYOUT_ID} .settings-slider::-webkit-slider-thumb {
      -webkit-appearance: none;
      appearance: none;
      width: 16px;
      height: 16px;
      background: #c8aa6e;
      border-radius: 50%;
      cursor: pointer;
    }
    
    #${FLYOUT_ID} .settings-slider::-moz-range-thumb {
      width: 16px;
      height: 16px;
      background: #c8aa6e;
      border-radius: 50%;
      cursor: pointer;
      border: none;
    }
    
    #${FLYOUT_ID} .settings-checkbox {
      width: 18px;
      height: 18px;
      margin-right: 8px;
      cursor: pointer;
    }
    
    #${FLYOUT_ID} .settings-input {
      width: 100%;
      padding: 8px;
      background: #3c3c41;
      border: 1px solid #5c5b56;
      border-radius: 4px;
      color: #cdbe91;
      font-size: 14px;
      font-family: "Beaufort for LOL", serif;
      box-sizing: border-box;
    }
    
    #${FLYOUT_ID} .settings-input::placeholder {
      font-family: "Beaufort for LOL", serif;
      color: #7d7d7d;
      opacity: 1;
    }
    
    #${FLYOUT_ID} .settings-input::-webkit-input-placeholder {
      font-family: "Beaufort for LOL", serif;
      color: #7d7d7d;
    }
    
    #${FLYOUT_ID} .settings-input::-moz-placeholder {
      font-family: "Beaufort for LOL", serif;
      color: #7d7d7d;
      opacity: 1;
    }
    
    #${FLYOUT_ID} .settings-input:-ms-input-placeholder {
      font-family: "Beaufort for LOL", serif;
      color: #7d7d7d;
    }
    
    #${FLYOUT_ID} .settings-input:focus {
      outline: none;
      border-color: #c8aa6e;
    }
    
    #${FLYOUT_ID} .settings-status {
      display: inline-block;
      margin-left: 8px;
      font-size: 16px;
    }
    
    #${FLYOUT_ID} .settings-button {
      width: 100%;
      padding: 10px;
      background: #0a1428;
      border: 1px solid #c8aa6e;
      border-radius: 4px;
      color: #c8aa6e;
      font-size: 14px;
      font-weight: bold;
      cursor: pointer;
      margin-top: 8px;
      transition: background 0.2s;
    }
    
    #${FLYOUT_ID} .settings-button:hover {
      background: #1a2332;
    }
    
    #${FLYOUT_ID} .settings-links {
      display: flex;
      justify-content: space-between;
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid #3c3c41;
      width: 100%;
    }
    
    #${FLYOUT_ID} form {
      width: 100%;
      display: flex;
      flex-direction: column;
      align-items: center;
    }
    
    #${FLYOUT_ID} .settings-link {
      color: #c8aa6e;
      text-decoration: none;
      font-size: 14px;
      transition: color 0.2s;
    }
    
    #${FLYOUT_ID} .settings-link:hover {
      color: #f0e6d2;
    }
    
    #${FLYOUT_ID} .settings-checkbox-wrapper {
      display: flex;
      align-items: center;
      margin-top: 8px;
    }
    
    /* Style for the "Add custom mods" dropdown button - match League UI button styling */
    #add-custom-mods-dropdown {
      background: #1E2328 !important;
      background-color: #1E2328 !important;
      color: #c8aa6e !important;
      font-family: "Beaufort for LOL", serif !important;
      pointer-events: all !important;
      position: relative !important;
      display: flex !important;
      align-items: center !important;
      justify-content: center !important;
      box-sizing: border-box !important;
      min-width: 90px !important;
      height: 100% !important;
      min-height: 32px !important;
      cursor: pointer !important;
      -webkit-user-select: none !important;
      text-align: center !important;
      margin-top: 8px !important;
      transition: background 0.2s !important;
      z-index: 10003 !important;
    }
    
    /* Ensure dropdown menu appears above other elements */
    #add-custom-mods-dropdown[class*="active"],
    #add-custom-mods-dropdown.active {
      z-index: 10003 !important;
    }
    
    /* Dropdown menu options container */
    #add-custom-mods-dropdown ~ *,
    #add-custom-mods-dropdown .lol-uikit-dropdown-menu,
    #add-custom-mods-dropdown [role="listbox"] {
      z-index: 10003 !important;
    }
    
    /* Remove any blue colors or unwanted backgrounds from child elements, but keep dropdown background */
    #add-custom-mods-dropdown > * {
      background: transparent !important;
      background-color: transparent !important;
    }
    
    /* Ensure dropdown itself and pseudo-elements maintain background */
    #add-custom-mods-dropdown,
    #add-custom-mods-dropdown::before,
    #add-custom-mods-dropdown::after {
      background: #1E2328 !important;
      background-color: #1E2328 !important;
      background-image: none !important;
      opacity: 1 !important;
    }
    
    /* Hover effect - no transparency */
    #add-custom-mods-dropdown:hover,
    #add-custom-mods-dropdown:hover::before,
    #add-custom-mods-dropdown:hover::after {
      background: #1E2328 !important;
      background-color: #1E2328 !important;
      opacity: 1 !important;
    }
    
    /* Remove focus/active blue colors and shining effects */
    #add-custom-mods-dropdown:focus,
    #add-custom-mods-dropdown:active,
    #add-custom-mods-dropdown:focus-visible,
    #add-custom-mods-dropdown:focus-within {
      background: #1E2328 !important;
      background-color: #1E2328 !important;
      outline: none !important;
      box-shadow: none !important;
      border: none !important;
    }
    
    /* Remove any glow or shine effects */
    #add-custom-mods-dropdown:focus::before,
    #add-custom-mods-dropdown:focus::after,
    #add-custom-mods-dropdown:active::before,
    #add-custom-mods-dropdown:active::after {
      display: none !important;
      box-shadow: none !important;
    }
    
    /* Remove all glow effects including filters, transforms, and shadows */
    #add-custom-mods-dropdown:focus,
    #add-custom-mods-dropdown:active,
    #add-custom-mods-dropdown:focus-visible,
    #add-custom-mods-dropdown:focus-within,
    #add-custom-mods-dropdown:focus *,
    #add-custom-mods-dropdown:active * {
      filter: none !important;
      -webkit-filter: none !important;
      transform: none !important;
      -webkit-transform: none !important;
      box-shadow: none !important;
      text-shadow: none !important;
      outline: none !important;
      border-color: transparent !important;
    }
    
    /* Blur focus after click */
    #add-custom-mods-dropdown {
      outline: none !important;
    }
    
    /* Don't center dropdown menu options */
    #add-custom-mods-dropdown .framed-dropdown-type {
      text-align: left !important;
    }
    
    /* Hide placeholder option from dropdown menu (but keep it for header display) */
    #add-custom-mods-dropdown[class*="active"] .placeholder-option,
    #add-custom-mods-dropdown.active .placeholder-option {
      display: none !important;
    }
    
    /* Force placeholder to always be selected for display */
    #add-custom-mods-dropdown .placeholder-option {
      display: block !important;
    }
    
    /* Ensure placeholder text is always shown in header */
    #add-custom-mods-dropdown:not([class*="active"]) .placeholder-option {
      display: block !important;
    }
    
    /* Hide checkmark icons in dropdown */
    #add-custom-mods-dropdown lol-uikit-dropdown-option::after,
    #add-custom-mods-dropdown lol-uikit-dropdown-option::before,
    #add-custom-mods-dropdown .framed-dropdown-type::after,
    #add-custom-mods-dropdown .framed-dropdown-type::before,
    #add-custom-mods-dropdown lol-uikit-dropdown-option [class*="check"],
    #add-custom-mods-dropdown lol-uikit-dropdown-option [class*="icon"],
    #add-custom-mods-dropdown lol-uikit-dropdown-option [class*="selected"] {
      display: none !important;
      visibility: hidden !important;
      opacity: 0 !important;
    }
    
    /* Override :host .ui-dropdown color to match button contrast */
    #add-custom-mods-dropdown .ui-dropdown {
      color: #CDBE91 !important;
      font-size: 12px !important;
      font-weight: normal !important;
      line-height: 16px !important;
      letter-spacing: 0.025em !important;
      -webkit-font-smoothing: subpixel-antialiased !important;
    }
    
    /* Target shadow DOM content via part or direct selector */
    #add-custom-mods-dropdown::part(content),
    #add-custom-mods-dropdown .ui-dropdown-current-content,
    #add-custom-mods-dropdown .ui-dropdown-current-content.shadow {
      color: #CDBE91 !important;
    }
    
    
    /* Add Custom Mods Dialog Styles */
    #add-custom-mods-dialog,
    #champion-selection-dialog,
    #skin-selection-dialog {
      position: fixed;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      z-index: 10001;
      background: rgba(0, 0, 0, 0.5);
      display: flex;
      align-items: center;
      justify-content: center;
    }

    #add-custom-mods-dialog .backdrop,
    #champion-selection-dialog .backdrop,
    #skin-selection-dialog .backdrop {
      position: fixed;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      z-index: 10001;
      background: rgba(0, 0, 0, 0.5);
      pointer-events: all;
    }

    
    #add-custom-mods-flyout,
    #champion-selection-flyout,
    #skin-selection-flyout {
      min-width: 600px !important;
      max-width: 800px !important;
      background: transparent !important;
      background-color: transparent !important;
      background-image: none !important;
      border-radius: 0 !important;
      padding: 0 !important;
      color: #cdbe91;
      font-family: "Beaufort for LOL", serif;
      display: flex !important;
      flex-direction: column !important;
      align-items: center !important;
      box-shadow: none !important;
      border: none !important;
      margin: 0 !important;
      overflow: visible !important;
      overflow-x: hidden !important;
      overflow-y: hidden !important;
    }

    #skin-selection-flyout {
      min-width: 700px !important;
    }

    #champion-selection-flyout::-webkit-scrollbar,
    #skin-selection-flyout::-webkit-scrollbar,
    #champion-selection-dialog::-webkit-scrollbar,
    #skin-selection-dialog::-webkit-scrollbar {
      display: none !important;
      width: 0 !important;
      height: 0 !important;
    }
    
    #champion-selection-flyout *::-webkit-scrollbar,
    #skin-selection-flyout *::-webkit-scrollbar {
      display: none !important;
      width: 0 !important;
      height: 0 !important;
    }
    
    #add-custom-mods-flyout lc-flyout-content,
    #add-custom-mods-flyout .lc-flyout-content,
    #champion-selection-flyout lc-flyout-content,
    #champion-selection-flyout .lc-flyout-content,
    #skin-selection-flyout lc-flyout-content,
    #skin-selection-flyout .lc-flyout-content {
      overflow-x: hidden !important;
    }
    
    #add-custom-mods-flyout lc-flyout-content,
    #add-custom-mods-flyout .lc-flyout-content,
    #champion-selection-flyout lc-flyout-content,
    #champion-selection-flyout .lc-flyout-content,
    #skin-selection-flyout lc-flyout-content,
    #skin-selection-flyout .lc-flyout-content {
      background: #010a13 !important;
      background-color: #010a13 !important;
      background-image: none !important;
      border-radius: 0 !important;
      padding: 20px !important;
      width: 100% !important;
      box-sizing: border-box !important;
      border: 1px solid #c8aa6e !important;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5) !important;
      margin: 0 !important;
      overflow-x: hidden !important;
    }
    
    #champion-selection-dialog,
    #skin-selection-dialog {
      overflow-x: hidden !important;
      overflow-y: hidden !important;
    }
    
    #champion-selection-flyout::-webkit-scrollbar,
    #skin-selection-flyout::-webkit-scrollbar,
    #champion-selection-flyout::-webkit-scrollbar:horizontal,
    #skin-selection-flyout::-webkit-scrollbar:horizontal,
    #champion-selection-dialog::-webkit-scrollbar,
    #skin-selection-dialog::-webkit-scrollbar {
      display: none !important;
      width: 0 !important;
      height: 0 !important;
    }
    
    #add-custom-mods-flyout::before,
    #add-custom-mods-flyout::after {
      display: none !important;
      content: none !important;
    }

    #add-custom-mods-flyout *::before,
    #add-custom-mods-flyout *::after {
      display: none !important;
      content: none !important;
      background: none !important;
      background-image: none !important;
    }
    
    #add-custom-mods-flyout .settings-title,
    #champion-selection-flyout .settings-title,
    #skin-selection-flyout .settings-title {
      font-size: 18px;
      font-weight: bold !important;
      margin-bottom: 12px;
      color: #c8aa6e;
      text-align: center;
      width: 100%;
      position: relative;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    
    .dialog-header {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 100%;
      margin-bottom: 16px;
      position: relative;
    }

    .back-button {
      position: absolute;
      left: 0;
      background: transparent;
      border: none;
      color: #a09b8c;
      width: 32px;
      height: 32px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 0;
      transition: color 0.2s ease;
      flex-shrink: 0;
    }
    .back-button svg {
      width: 20px;
      height: 20px;
      fill: none;
      stroke: currentColor;
      stroke-width: 2;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    .back-button:hover {
      color: #c8aa6e;
    }
    .back-button:active {
      color: #f0e6d2;
    }
    
    .dialog-title-wrapper {
      flex: 1;
      text-align: center;
      font-size: 18px;
      font-weight: bold;
      color: #c8aa6e;
      font-family: "Beaufort for LOL", serif;
    }
    
    #champion-selection-flyout .champion-search-input,
    #champion-selection-flyout lol-uikit-flat-input.champion-search-input {
      width: 100%;
      margin-bottom: 12px;
    }
    
    #champion-selection-flyout .champion-search-input input,
    #champion-selection-flyout lol-uikit-flat-input.champion-search-input input {
      width: 100%;
      box-sizing: border-box;
    }
    
    #champions-grid-wrapper,
    #skins-list {
      scrollbar-width: none;
    }
    #champions-grid-wrapper::-webkit-scrollbar,
    #skins-list::-webkit-scrollbar {
      display: none;
      width: 0;
      height: 0;
    }

    #champions-grid-wrapper {
      max-height: 45vh;
      margin-top: 12px;
    }
    
    #champions-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(90px, 1fr));
      gap: 8px;
      padding-right: 8px;
    }

    .champion-card {
      display: flex;
      flex-direction: column;
      align-items: center;
      cursor: pointer;
      padding: 6px;
      border: 1px solid transparent;
      border-radius: 4px;
      transition: border-color 0.2s, background 0.2s;
      background: transparent;
    }
    .champion-card:hover {
      border-color: #c8aa6e;
      background: rgba(200, 170, 110, 0.08);
    }
    .champion-card img {
      width: 60px;
      height: 60px;
      border-radius: 50%;
      border: 2px solid #5b5a56;
      object-fit: cover;
      transition: border-color 0.2s;
    }
    .champion-card:hover img {
      border-color: #c8aa6e;
    }
    .champion-card .champion-name {
      margin-top: 6px;
      font-size: 11px;
      color: #a09b8c;
      text-align: center;
      font-family: "Beaufort for LOL", serif;
      line-height: 1.2;
      max-width: 80px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .champion-card:hover .champion-name {
      color: #cdbe91;
    }

    #skins-list {
      max-height: 60vh;
    }

    #skins-list .skins-list-container {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
      gap: 10px;
      padding-right: 8px;
    }

    .skin-card {
      display: flex;
      flex-direction: column;
      cursor: pointer;
      border: 1px solid #5b5a56;
      border-radius: 4px;
      overflow: hidden;
      transition: border-color 0.2s, box-shadow 0.2s;
      background: #1e2328;
    }
    .skin-card:hover {
      border-color: #c8aa6e;
      box-shadow: 0 0 8px rgba(200, 170, 110, 0.3);
    }
    .skin-card img {
      width: 100%;
      aspect-ratio: 308 / 560;
      object-fit: cover;
      display: block;
      background: #0a0a0d;
    }
    .skin-card .skin-name {
      padding: 8px;
      font-size: 12px;
      color: #a09b8c;
      text-align: center;
      font-family: "Beaufort for LOL", serif;
      line-height: 1.3;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .skin-card:hover .skin-name {
      color: #cdbe91;
    }
  `;
  }

  function log(level, message, data = null) {
    const consoleMethod =
      level === "error"
        ? console.error
        : level === "warn"
          ? console.warn
          : console.log;
    consoleMethod(`${LOG_PREFIX} ${message}`, data || "");
  }

  function setupBridgeSocket() {
    if (bridgeSocket && bridgeSocket.readyState === WebSocket.OPEN) {
      return;
    }

    try {
      bridgeSocket = new WebSocket(BRIDGE_URL);

      bridgeSocket.onopen = () => {
        log("info", "WebSocket bridge connected");
        bridgeReady = true;
        flushBridgeQueue();
        // Keep badges in sync even if Settings flyout isn't opened yet.
        requestSettings();
        requestDiagnostics();
        startBadgeObserver();

        // Poll diagnostics so warnings appear without opening the panel.
        if (!_diagnosticsPollId) {
          _diagnosticsPollId = setInterval(() => {
            try {
              if (!bridgeReady) return;
              if (typeof document !== "undefined" && document.hidden) return;
              requestDiagnostics();
            } catch (e) {}
          }, 15000);
        }
      };

      bridgeSocket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          handleBridgeMessage(payload);
        } catch (e) {
          log("error", "Failed to parse bridge message", { error: e.message });
        }
      };

      bridgeSocket.onerror = (error) => {
        log("warn", "WebSocket bridge error", {
          error: error.message || "Unknown error",
        });
      };

      bridgeSocket.onclose = () => {
        log("info", "WebSocket bridge closed, reconnecting...");
        bridgeReady = false;
        bridgeSocket = null;
        if (_diagnosticsPollId) {
          clearInterval(_diagnosticsPollId);
          _diagnosticsPollId = null;
        }
        scheduleBridgeRetry();
      };
    } catch (e) {
      log("error", "Failed to setup WebSocket bridge", { error: e.message });
      scheduleBridgeRetry();
    }
  }

  function scheduleBridgeRetry() {
    setTimeout(() => {
      if (!bridgeReady) {
        setupBridgeSocket();
      }
    }, 3000);
  }

  function flushBridgeQueue() {
    if (
      bridgeQueue.length > 0 &&
      bridgeReady &&
      bridgeSocket &&
      bridgeSocket.readyState === WebSocket.OPEN
    ) {
      bridgeQueue.forEach((message) => {
        bridgeSocket.send(message);
      });
      bridgeQueue = [];
    }
  }

  function sendToBridge(payload) {
    const message = JSON.stringify(payload);
    if (
      bridgeReady &&
      bridgeSocket &&
      bridgeSocket.readyState === WebSocket.OPEN
    ) {
      bridgeSocket.send(message);
    } else {
      bridgeQueue.push(message);
      setupBridgeSocket();
    }
  }

  function handleBridgeMessage(payload) {
    if (payload.type === "settings-data") {
      handleSettingsData(payload);
    } else if (payload.type === "settings-saved") {
      handleSettingsSaved(payload);
    } else if (payload.type === "diagnostics-data") {
      handleDiagnosticsData(payload);
    } else if (payload.type === "diagnostics-cleared-category") {
      // Refresh the view after backend clears matching entries.
      requestDiagnostics();
    } else if (payload.type === "path-validation-result") {
      handlePathValidationResult(payload);
    } else if (payload.type === "champions-list-response") {
      handleChampionsListResponse(payload);
    } else if (payload.type === "champion-skins-response") {
      handleChampionSkinsResponse(payload);
    } else if (payload.type === "folder-opened-response") {
      handleFolderOpenedResponse(payload);
    }
  }

  function handleSettingsData(payload) {
    currentSettings = {
      threshold: payload.threshold || 0.5,
      monitorAutoResumeTimeout: payload.monitorAutoResumeTimeout || 60,
      autostart: payload.autostart || false,
      gamePath: payload.gamePath || "",
      gamePathValid: payload.gamePathValid || false,
    };
    updateSettingsForm();
    // Badge count should reflect what's actually in diagnostics (and not change while dragging sliders).
    const localCount = Array.isArray(diagnosticsState.errors) ? diagnosticsState.errors.length : 0;
    if (localCount > 0) {
      updateErrorBadges(true, localCount);
    } else {
      updateErrorBadges(!!payload.hasErrors, payload.errorsCount || 0);
    }
    // If backend reports errors but we don't have the list yet, fetch it once so we can
    // show per-category guidance and clear it after Save (not while dragging).
    if (payload.hasErrors && (!Array.isArray(diagnosticsState.errors) || diagnosticsState.errors.length === 0)) {
      requestDiagnostics();
    }
    log("info", "Settings data received", currentSettings);
  }

  let diagnosticsDialog = null;
  let diagnosticsState = { errors: [], path: "", settingsSnapshot: null };
  let errorBadgeState = { hasErrors: false, count: 0 };
  let _badgeObserverStarted = false;
  let _pendingSave = null;
  let _diagnosticsPollId = null;
  let _flyoutRepositionTimer = null;

  function _clamp(n, min, max) {
    return Math.max(min, Math.min(max, n));
  }

  function _diagnosticsCategory(e) {
    const raw = String(e?.text || e?.msg || "").trim();
    const code = String(e?.code || "").trim();

    if (code === "BASE_SKIN_FORCE_SLOW" || code === "BASE_SKIN_VERIFY_FAILED") return "injection_threshold";
    if (code === "AUTO_RESUME_TRIGGERED" || code === "MONITOR_AUTO_RESUME_TIMEOUT") return "monitor_timeout";

    if (/Injection\s*Threshold/i.test(raw)) return "injection_threshold";
    if (/Auto-Resume Timeout/i.test(raw) || /Monitor Auto-Resume Timeout/i.test(raw)) return "monitor_timeout";

    return "other";
  }

  function _getRecommendedForCategory(category, errors) {
    const snap = diagnosticsState?.settingsSnapshot || null;
    const snapThreshold =
      typeof snap?.threshold === "number" && Number.isFinite(snap.threshold) ? snap.threshold : null;
    const snapTimeout =
      typeof snap?.monitorAutoResumeTimeout === "number" && Number.isFinite(snap.monitorAutoResumeTimeout)
        ? snap.monitorAutoResumeTimeout
        : null;

    if (category === "injection_threshold") {
      // Prefer explicit recommendation if present.
      const recs = (errors || [])
        .map((e) => e?.recommendedThresholdS)
        .filter((v) => typeof v === "number" && Number.isFinite(v));
      if (recs.length) return _clamp(Math.max(...recs), 0.3, 2.0);
      // Otherwise: stable heuristic based on the settings at the time diagnostics were fetched.
      if (typeof snapThreshold === "number") return _clamp(snapThreshold + 0.25, 0.3, 2.0);
      return null;
    }

    if (category === "monitor_timeout") {
      // Prefer explicit recommendation if present (support multiple field names defensively).
      const recs = (errors || [])
        .map((e) => e?.recommendedMonitorTimeoutS ?? e?.recommendedTimeoutS ?? e?.recommendedAutoResumeTimeoutS)
        .filter((v) => typeof v === "number" && Number.isFinite(v));
      if (recs.length) return _clamp(Math.max(...recs), 20, 180);
      if (typeof snapTimeout === "number") return _clamp(Math.max(snapTimeout + 30, 90), 20, 180);
      return null;
    }

    return null;
  }

  function getEffectiveDiagnosticsErrors() {
    const errors = Array.isArray(diagnosticsState.errors) ? diagnosticsState.errors : [];
    if (errors.length === 0) return [];

    // Group by category so we can drop the whole category once resolved.
    const byCat = new Map();
    for (const e of errors) {
      const cat = _diagnosticsCategory(e);
      if (!byCat.has(cat)) byCat.set(cat, []);
      byCat.get(cat).push(e);
    }

    const curThreshold = typeof currentSettings?.threshold === "number" ? currentSettings.threshold : null;
    const curTimeout =
      typeof currentSettings?.monitorAutoResumeTimeout === "number" ? currentSettings.monitorAutoResumeTimeout : null;

    const resolved = new Set();
    for (const [cat, list] of byCat.entries()) {
      const rec = _getRecommendedForCategory(cat, list);
      if (rec == null) continue;

      if (cat === "injection_threshold" && typeof curThreshold === "number" && curThreshold >= (rec - 1e-6)) {
        resolved.add(cat);
      } else if (cat === "monitor_timeout" && typeof curTimeout === "number" && curTimeout >= (rec - 1e-6)) {
        resolved.add(cat);
      }
    }

    if (resolved.size === 0) return errors;
    return errors.filter((e) => !resolved.has(_diagnosticsCategory(e)));
  }

  function getResolvedDiagnosticsCategories() {
    const all = Array.isArray(diagnosticsState?.errors) ? diagnosticsState.errors : [];
    if (all.length === 0) return [];
    const allCats = new Set(all.map(_diagnosticsCategory));
    const remainingCats = new Set(getEffectiveDiagnosticsErrors().map(_diagnosticsCategory));

    const resolved = [];
    for (const cat of allCats) {
      if (cat === "other") continue;
      if (!remainingCats.has(cat)) resolved.push(cat);
    }
    return resolved;
  }

  function handleDiagnosticsData(payload) {
    // Snapshot the settings at the time we fetched diagnostics so "recommended" targets stay stable
    // while the user is dragging sliders.
    const snapshot =
      currentSettings && typeof currentSettings === "object"
        ? {
            threshold: currentSettings.threshold,
            monitorAutoResumeTimeout: currentSettings.monitorAutoResumeTimeout,
          }
        : null;
    diagnosticsState = {
      errors: Array.isArray(payload.errors) ? payload.errors : [],
      path: payload.path || "",
      settingsSnapshot: snapshot,
    };
    updateErrorBadges(diagnosticsState.errors.length > 0, diagnosticsState.errors.length);
    renderDiagnosticsDialog();
  }

  function getResolvedCategoriesForSavedValues(values) {
    // Only consider a category "fixed" if:
    // - the saved value meets/exceeds the recommended target, AND
    // - the user actually increased it compared to the snapshot from when diagnostics were fetched.
    const eps = 1e-6;
    const all = Array.isArray(diagnosticsState?.errors) ? diagnosticsState.errors : [];
    if (!all.length || !values) return [];

    const snap = diagnosticsState?.settingsSnapshot || null;
    const snapThreshold = typeof snap?.threshold === "number" ? snap.threshold : null;
    const snapTimeout = typeof snap?.monitorAutoResumeTimeout === "number" ? snap.monitorAutoResumeTimeout : null;

    const byCat = new Map();
    for (const e of all) {
      const cat = _diagnosticsCategory(e);
      if (!byCat.has(cat)) byCat.set(cat, []);
      byCat.get(cat).push(e);
    }

    const resolved = [];
    for (const [cat, list] of byCat.entries()) {
      if (cat === "other") continue;
      const rec = _getRecommendedForCategory(cat, list);
      if (rec == null) continue;

      if (cat === "injection_threshold") {
        const saved = typeof values.threshold === "number" ? values.threshold : null;
        const increased = typeof snapThreshold === "number" ? saved != null && saved > (snapThreshold + eps) : true;
        if (saved != null && saved >= (rec - eps) && increased) resolved.push(cat);
      } else if (cat === "monitor_timeout") {
        const saved = typeof values.monitorAutoResumeTimeout === "number" ? values.monitorAutoResumeTimeout : null;
        const increased = typeof snapTimeout === "number" ? saved != null && saved > (snapTimeout + eps) : true;
        if (saved != null && saved >= (rec - eps) && increased) resolved.push(cat);
      }
    }

    return resolved;
  }

  function updateErrorBadges(hasErrors, count) {
    errorBadgeState = { hasErrors: !!hasErrors, count: Number(count) || 0 };
    applyErrorBadges();
  }

  function startBadgeObserver() {
    if (_badgeObserverStarted) return;
    _badgeObserverStarted = true;

    // Re-apply badges when the Golden Rose nav item is injected by ROSE-UI (or recreated by Ember).
    const tryApply = () => {
      try {
        applyErrorBadges();
      } catch (e) {}
    };

    try {
      const obs = new MutationObserver(() => {
        // Only bother if we actually have errors to show (keeps it cheap)
        if (!errorBadgeState.hasErrors) return;
        tryApply();
      });
      obs.observe(document.body, { childList: true, subtree: true });

      // Also retry a few times after startup (covers cases where body observer misses early churn)
      let attempts = 0;
      const id = setInterval(() => {
        attempts += 1;
        tryApply();
        if (attempts >= 20) clearInterval(id); // ~10s max
      }, 500);
    } catch (e) {
      // Fallback: periodic best-effort if MutationObserver fails
      let attempts = 0;
      const id = setInterval(() => {
        attempts += 1;
        tryApply();
        if (attempts >= 20) clearInterval(id);
      }, 500);
    }
  }

  function applyErrorBadges() {
    // Sidebar "Golden Rose" nav icon badge
    const navItem = document.querySelector(
      "lol-uikit-navigation-item.menu_item_Golden.Rose"
    );
    if (navItem) {
      const host =
        navItem.querySelector(".menu-item-icon-wrapper") ||
        navItem.querySelector(".menu-item-icon") ||
        navItem;

      host.style.position = host.style.position || "relative";
      // Use warning image overlay (assets/red-warning.png) on the top-right of the Rose icon.
      let badge = host.querySelector("#rose-errors-badge");
      if (errorBadgeState.hasErrors) {
        if (!badge) {
          badge = document.createElement("div");
          badge.id = "rose-errors-badge";
          badge.classList.add("rose-warning-glow");
          // Position + size for the warning overlay
          badge.style.position = "absolute";
          badge.style.top = "-10px";
          badge.style.right = "-10px";
          badge.style.width = "14px";
          badge.style.height = "14px";
          badge.style.backgroundImage = `url(http://127.0.0.1:${BRIDGE_PORT}/asset/red-warning.png)`;
          badge.style.backgroundSize = "contain";
          badge.style.backgroundRepeat = "no-repeat";
          badge.style.backgroundPosition = "center";
          badge.style.pointerEvents = "none";
          host.appendChild(badge);
        }
        // Keep text empty; this overlay is purely visual.
      } else if (badge) {
        badge.remove();
      }
    }

    // Troubleshooting button warning overlay (only when settings flyout is open)
    const tb = document.getElementById("troubleshoot-button");
    if (tb) {
      tb.style.position = tb.style.position || "relative";
      let warn = tb.querySelector("#rose-troubleshoot-warning");
      if (errorBadgeState.hasErrors) {
        if (!warn) {
          warn = document.createElement("div");
          warn.id = "rose-troubleshoot-warning";
          warn.classList.add("rose-warning-glow");

          warn.style.position = "absolute";
          warn.style.top = "-15px";
          warn.style.right = "-9px";
          warn.style.width = "14px";
          warn.style.height = "14px";
          warn.style.backgroundImage = `url(http://127.0.0.1:${BRIDGE_PORT}/asset/red-warning.png)`;
          warn.style.backgroundSize = "contain";
          warn.style.backgroundRepeat = "no-repeat";
          warn.style.backgroundPosition = "center";
          warn.style.pointerEvents = "none";

          tb.appendChild(warn);
        }
      } else if (warn) {
        warn.remove();
      }
    }
  }

  function handlePathValidationResult(payload) {
    const pathInput = document.getElementById("game-path-input");
    const pathStatus = document.getElementById("path-status");

    if (!pathInput || !pathStatus) {
      return;
    }

    // Only update if this validation is for the current path value
    const currentPath = pathInput.value.trim();
    if (payload.gamePath === currentPath) {
      const isValid = payload.valid === true;
      pathStatus.textContent = isValid ? "✅" : "❌";

      // Update current settings if this is the saved path
      if (currentPath === currentSettings.gamePath) {
        currentSettings.gamePathValid = isValid;
      }
    }
  }

  function handleSettingsSaved(payload) {
    if (payload.success) {
      log("info", "Settings saved successfully", payload);
      // Show success message to user
      const saveButton = document.getElementById("save-button");
      if (saveButton) {
        const originalText = saveButton.textContent;
        saveButton.textContent = "Saved!";
        setTimeout(() => {
          saveButton.textContent = originalText;
        }, 2000);
      }

      // After a successful save: if the user actually increased a value enough to satisfy the
      // recommendation, clear all diagnostics entries from that category so they stay gone.
      try {
        if (_pendingSave) {
          const cats = getResolvedCategoriesForSavedValues(_pendingSave);
          if (cats.length > 0) {
            sendToBridge({ type: "diagnostics-clear-category", categories: cats });
          }
        }
      } catch (e) {}
      _pendingSave = null;

      // Refresh settings + diagnostics + badges after save
      requestSettings();
      requestDiagnostics();
    } else {
      log("error", "Settings save failed", payload);
      // Show error message to user
      const saveButton = document.getElementById("save-button");
      if (saveButton) {
        const originalText = saveButton.textContent;
        saveButton.textContent = payload.error || "Error saving settings";
        saveButton.style.background = "#8b0000";
        setTimeout(() => {
          saveButton.textContent = originalText;
          saveButton.style.background = "";
        }, 3000);
      }
    }
  }

  function validateGamePath(path) {
    if (!path || !path.trim()) {
      return false;
    }
    // Basic validation - check if path contains "League of Legends"
    // Full validation is done on Python side
    return path.trim().length > 0;
  }

  function createSettingsFlyout(navItem) {
    // Remove existing panel if any
    const existingPanel = document.getElementById(PANEL_ID);
    if (existingPanel) {
      existingPanel.remove();
    }

    // Create panel container (fixed positioning for viewport-relative coordinates)
    const panel = document.createElement("div");
    panel.id = PANEL_ID;
    panel.style.position = "fixed";
    panel.style.top = "0";
    panel.style.left = "0";
    panel.style.width = "100%";
    panel.style.height = "100%";
    panel.style.zIndex = "10000";
    panel.style.pointerEvents = "none";
    document.body.appendChild(panel);

    // Create backdrop for click-outside-to-close
    const backdrop = document.createElement("div");
    backdrop.style.position = "fixed";
    backdrop.style.top = "0";
    backdrop.style.left = "0";
    backdrop.style.width = "100%";
    backdrop.style.height = "100%";
    backdrop.style.zIndex = "9999";
    backdrop.style.background = "transparent";
    backdrop.style.pointerEvents = "all";
    backdrop.addEventListener("click", (e) => {
      // Only close if clicking directly on backdrop, not on flyout
      if (e.target === backdrop) {
        closeSettingsPanel();
      }
    });
    panel.appendChild(backdrop);

    // Get the actual icon element position (not the parent container)
    const iconElement =
      navItem.querySelector(".menu-item-icon") ||
      navItem.querySelector(".menu-item-icon-wrapper") ||
      navItem;
    const iconRect = iconElement.getBoundingClientRect();

    // Create flyout frame
    let flyoutFrame;
    try {
      flyoutFrame = document.createElement("lol-uikit-flyout-frame");
      flyoutFrame.id = FLYOUT_ID;
      flyoutFrame.className = "flyout";
      flyoutFrame.setAttribute("orientation", "bottom");
      flyoutFrame.setAttribute("animated", "true");
      flyoutFrame.setAttribute("show", "true");
    } catch (e) {
      log("debug", "Could not create custom element, using div", e);
      flyoutFrame = document.createElement("div");
      flyoutFrame.id = FLYOUT_ID;
      flyoutFrame.className = "flyout";
    }

    // Use absolute positioning within the fixed panel container
    flyoutFrame.style.position = "absolute";
    flyoutFrame.style.overflow = "visible";
    // Position below the icon, centered horizontally on the icon
    flyoutFrame.style.top = `${iconRect.bottom + 45}px`;
    flyoutFrame.style.left = `${iconRect.left + iconRect.width / 2}px`;
    flyoutFrame.style.transform = "translateX(-50%)"; // Center the panel on the icon
    flyoutFrame.style.zIndex = "10001";
    flyoutFrame.style.pointerEvents = "all";
    flyoutFrame.style.setProperty("background", "transparent", "important");
    flyoutFrame.style.setProperty(
      "background-color",
      "transparent",
      "important"
    );
    flyoutFrame.style.setProperty("background-image", "none", "important");
    flyoutFrame.style.setProperty("border", "none", "important");
    flyoutFrame.style.setProperty("box-shadow", "none", "important");
    flyoutFrame.style.setProperty("margin", "0", "important");
    flyoutFrame.style.setProperty("padding", "0", "important");
    flyoutFrame.style.setProperty("overflow", "visible", "important");

    // Force remove any default classes that might add background
    if (flyoutFrame.classList) {
      flyoutFrame.classList.forEach((cls) => {
        if (cls.includes("background") || cls.includes("bg-")) {
          flyoutFrame.classList.remove(cls);
        }
      });
    }

    // Prevent click from closing
    flyoutFrame.addEventListener("click", (e) => {
      e.stopPropagation();
    });

    // Create flyout content
    let flyoutContent;
    try {
      flyoutContent = document.createElement("lc-flyout-content");
    } catch (e) {
      log("debug", "Could not create lc-flyout-content, using div", e);
      flyoutContent = document.createElement("div");
      flyoutContent.className = "lc-flyout-content";
    }

    // Create settings form
    const form = document.createElement("div");
    form.style.width = "100%";
    form.style.display = "flex";
    form.style.flexDirection = "column";
    form.style.alignItems = "center";

    function getOrCreateGlobalTooltip() {
      let el = document.getElementById("rose-global-tooltip");
      if (el) return el;

      el = document.createElement("div");
      el.id = "rose-global-tooltip";
      el.setAttribute("role", "tooltip");
      el.setAttribute("data-show", "false");
      document.body.appendChild(el);
      return el;
    }

    function hideGlobalTooltip() {
      const el = document.getElementById("rose-global-tooltip");
      if (!el) return;
      el.setAttribute("data-show", "false");
    }

    function showGlobalTooltipFor(anchorEl, text) {
      const tooltip = getOrCreateGlobalTooltip();
      tooltip.textContent = text;
      tooltip.setAttribute("data-show", "true");

      // Measure after setting text
      const margin = 10;
      const rect = anchorEl.getBoundingClientRect();
      const tRect = tooltip.getBoundingClientRect();

      // Prefer above, fallback below if not enough room
      const preferredTop = rect.top - tRect.height - margin;
      const belowTop = rect.bottom + margin;
      const useTop = preferredTop >= 8;
      const top = useTop ? preferredTop : belowTop;
      tooltip.setAttribute("data-placement", useTop ? "top" : "bottom");

      // Center horizontally on icon, clamp to viewport
      let left = rect.left + rect.width / 2 - tRect.width / 2;
      const maxLeft = window.innerWidth - tRect.width - 8;
      left = Math.max(8, Math.min(maxLeft, left));

      tooltip.style.left = `${Math.round(left)}px`;
      tooltip.style.top = `${Math.round(top)}px`;

      // Nudge the arrow towards the anchor if clamped
      const anchorCenterX = rect.left + rect.width / 2;
      const arrowX = Math.max(12, Math.min(tRect.width - 12, anchorCenterX - left));
      tooltip.style.setProperty("--rose-tooltip-arrow-x", `${Math.round(arrowX)}px`);
    }

    function createTooltipButton(tooltipText, ariaLabel) {
      const wrapper = document.createElement("span");
      wrapper.className = "rose-tooltip-wrapper";

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "rose-tooltip-icon";
      btn.setAttribute("aria-label", ariaLabel || "Info");

      // prevent accidental focus/drag interactions with nearby controls
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
      });

      const show = () => showGlobalTooltipFor(btn, tooltipText);
      const hide = () => hideGlobalTooltip();

      btn.addEventListener("mouseenter", show);
      btn.addEventListener("mouseleave", hide);
      btn.addEventListener("focus", show);
      btn.addEventListener("blur", hide);

      // Keep tooltip in correct position while resizing/scrolling
      const reposition = () => {
        const tt = document.getElementById("rose-global-tooltip");
        if (!tt || tt.getAttribute("data-show") !== "true") return;
        showGlobalTooltipFor(btn, tooltipText);
      };
      window.addEventListener("resize", reposition);
      window.addEventListener("scroll", reposition, true);

      wrapper.appendChild(btn);
      return wrapper;
    }

    // Title
    const title = document.createElement("div");
    title.className = "settings-title";
    title.textContent = "Settings";
    form.appendChild(title);

    // Injection threshold section
    const thresholdSection = document.createElement("div");
    thresholdSection.className = "settings-section";

    const thresholdLabel = document.createElement("label");
    thresholdLabel.className = "settings-label";
    const thresholdLabelText = document.createElement("span");
    thresholdLabelText.textContent = "Injection Threshold (seconds):";
    thresholdLabel.appendChild(
      createTooltipButton(
        "Injection threshold is the time window during which the app considers your last hovered skin as the one to inject.\n\nFor example, if your injection threshold is set to 1 second, whichever skin you were hovering 1 second before champ select ends will be the one injected.\n\nIf your PC or connection is on the slower side, you may need to fine-tune this value.",
        "Injection threshold info"
      )
    );
    thresholdLabel.appendChild(thresholdLabelText);
    thresholdSection.appendChild(thresholdLabel);

    const thresholdValue = document.createElement("span");
    thresholdValue.className = "settings-value";
    thresholdValue.id = "threshold-value";
    thresholdValue.textContent = "0.50 s";
    thresholdLabel.appendChild(thresholdValue);

    // Create slider container with League of Legends style
    const thresholdSliderContainer = document.createElement("div");
    thresholdSliderContainer.className = "lol-settings-slider-component";
    thresholdSliderContainer.style.display = "flex";
    thresholdSliderContainer.style.alignItems = "center";
    thresholdSliderContainer.style.width = "100%";
    thresholdSliderContainer.style.marginTop = "10px";

    const thresholdSliderWrapper = document.createElement("div");
    thresholdSliderWrapper.className = "lol-settings-slider";
    thresholdSliderWrapper.style.width = "400px";
    thresholdSliderWrapper.style.height = "30px";
    thresholdSliderWrapper.style.position = "relative";

    const thresholdSlider = document.createElement("input");
    thresholdSlider.type = "range";
    thresholdSlider.id = "threshold-slider";
    // Minimum Injection Threshold: 300ms (0.30s)
    thresholdSlider.min = "30";
    thresholdSlider.max = "200";
    thresholdSlider.value = "50";
    thresholdSlider.style.width = "100%";
    thresholdSlider.style.height = "100%";
    thresholdSlider.style.opacity = "0";
    thresholdSlider.style.cursor = "pointer";
    thresholdSlider.style.position = "absolute";
    thresholdSlider.style.zIndex = "2";

    const thresholdSliderUI = document.createElement("div");
    thresholdSliderUI.className = "lol-uikit-slider-wrapper horizontal";
    thresholdSliderUI.style.position = "relative";
    thresholdSliderUI.style.height = "30px";
    thresholdSliderUI.style.width = "100%";

    const thresholdSliderBase = document.createElement("div");
    thresholdSliderBase.className = "lol-uikit-slider-base";
    thresholdSliderBase.style.height = "30px";
    thresholdSliderBase.style.width = "100%";
    thresholdSliderBase.style.position = "absolute";

    const thresholdTrack = document.createElement("div");
    thresholdTrack.className = "lol-uikit-slider-base-track";
    thresholdTrack.style.position = "absolute";
    thresholdTrack.style.top = "14px";
    thresholdTrack.style.left = "0";
    thresholdTrack.style.width = "calc(100% - 2.5px)";
    thresholdTrack.style.height = "2px";
    thresholdTrack.style.background = "#1e2328";

    // Calculate initial position for threshold slider (value 50, min 30, max 200)
    const thresholdInitialValue = 50;
    const thresholdMin = 30;
    const thresholdMax = 200;
    const thresholdPercentage = ((thresholdInitialValue - thresholdMin) / (thresholdMax - thresholdMin)) * 100;
    const thresholdSliderWidth = 400;
    const thresholdButtonWidth = 30;
    const thresholdMaxPosition = thresholdSliderWidth - thresholdButtonWidth; // 370px max
    const thresholdInitialPosition = (thresholdPercentage / 100) * thresholdMaxPosition;

    const thresholdFill = document.createElement("div");
    thresholdFill.className = "lol-uikit-slider-fill";
    thresholdFill.style.width = `${thresholdInitialPosition}px`;
    thresholdFill.style.height = "2px";
    thresholdFill.style.background = "linear-gradient(to left, #695625, #463714)";
    thresholdFill.style.position = "absolute";
    thresholdFill.style.top = "13px";
    thresholdFill.style.border = "thin solid #010a13";
    thresholdFill.style.transition = "width 0.1s ease-out, background 0.2s ease";

    const thresholdButton = document.createElement("div");
    thresholdButton.className = "lol-uikit-slider-button";
    thresholdButton.style.left = `${thresholdInitialPosition}px`;
    thresholdButton.style.width = "30px";
    thresholdButton.style.height = "30px";
    thresholdButton.style.background = "url('/fe/lol-uikit/images/slider-btn.png') no-repeat top left";
    thresholdButton.style.backgroundSize = "100%";
    thresholdButton.style.position = "absolute";
    thresholdButton.style.top = "0px";
    thresholdButton.style.cursor = "pointer";
    thresholdButton.style.transition = "left 0.1s ease-out, background-position 0.2s ease";

    thresholdSliderBase.appendChild(thresholdTrack);
    thresholdSliderBase.appendChild(thresholdFill);
    thresholdSliderBase.appendChild(thresholdButton);
    thresholdSliderUI.appendChild(thresholdSliderBase);
    thresholdSliderWrapper.appendChild(thresholdSlider);
    thresholdSliderWrapper.appendChild(thresholdSliderUI);
    thresholdSliderContainer.appendChild(thresholdSliderWrapper);
    thresholdSection.appendChild(thresholdSliderContainer);
    form.appendChild(thresholdSection);

    // Monitor auto-resume timeout section
    const timeoutSection = document.createElement("div");
    timeoutSection.className = "settings-section";

    const timeoutLabel = document.createElement("label");
    timeoutLabel.className = "settings-label";
    const timeoutLabelText = document.createElement("span");
    timeoutLabelText.textContent = "Monitor Auto-Resume Timeout (seconds):";
    timeoutLabel.appendChild(
      createTooltipButton(
        "Auto-resume is a safety feature.\n\nIf the injection process takes longer than the value you set, the app will automatically cancel the injection and let the game start normally.\n\nThis prevents the injection from looping and blocking the game from launching.\n\nIf you use a lot of custom mods, you may need to adjust this value.",
        "Auto-resume info"
      )
    );
    timeoutLabel.appendChild(timeoutLabelText);
    timeoutSection.appendChild(timeoutLabel);

    const timeoutValue = document.createElement("span");
    timeoutValue.className = "settings-value";
    timeoutValue.id = "timeout-value";
    timeoutValue.textContent = "60 s";
    timeoutLabel.appendChild(timeoutValue);

    // Create slider container with League of Legends style
    const timeoutSliderContainer = document.createElement("div");
    timeoutSliderContainer.className = "lol-settings-slider-component";
    timeoutSliderContainer.style.display = "flex";
    timeoutSliderContainer.style.alignItems = "center";
    timeoutSliderContainer.style.width = "100%";
    timeoutSliderContainer.style.marginTop = "10px";

    const timeoutSliderWrapper = document.createElement("div");
    timeoutSliderWrapper.className = "lol-settings-slider";
    timeoutSliderWrapper.style.width = "400px";
    timeoutSliderWrapper.style.height = "30px";
    timeoutSliderWrapper.style.position = "relative";

    const timeoutSlider = document.createElement("input");
    timeoutSlider.type = "range";
    timeoutSlider.id = "timeout-slider";
    // Minimum Auto-Resume Timeout: 20s
    timeoutSlider.min = "20";
    timeoutSlider.max = "180";
    timeoutSlider.value = "60";
    timeoutSlider.style.width = "100%";
    timeoutSlider.style.height = "100%";
    timeoutSlider.style.opacity = "0";
    timeoutSlider.style.cursor = "pointer";
    timeoutSlider.style.position = "absolute";
    timeoutSlider.style.zIndex = "2";

    const timeoutSliderUI = document.createElement("div");
    timeoutSliderUI.className = "lol-uikit-slider-wrapper horizontal";
    timeoutSliderUI.style.position = "relative";
    timeoutSliderUI.style.height = "30px";
    timeoutSliderUI.style.width = "100%";

    const timeoutSliderBase = document.createElement("div");
    timeoutSliderBase.className = "lol-uikit-slider-base";
    timeoutSliderBase.style.height = "30px";
    timeoutSliderBase.style.width = "100%";
    timeoutSliderBase.style.position = "absolute";

    const timeoutTrack = document.createElement("div");
    timeoutTrack.className = "lol-uikit-slider-base-track";
    timeoutTrack.style.position = "absolute";
    timeoutTrack.style.top = "14px";
    timeoutTrack.style.left = "0";
    timeoutTrack.style.width = "calc(100% - 2.5px)";
    timeoutTrack.style.height = "2px";
    timeoutTrack.style.background = "#1e2328";

    const timeoutFill = document.createElement("div");
    timeoutFill.className = "lol-uikit-slider-fill";
    timeoutFill.style.width = "0px"; // Initial position for min value
    timeoutFill.style.height = "2px";
    timeoutFill.style.background = "linear-gradient(to left, #695625, #463714)";
    timeoutFill.style.position = "absolute";
    timeoutFill.style.top = "13px";
    timeoutFill.style.border = "thin solid #010a13";
    timeoutFill.style.transition = "width 0.1s ease-out, background 0.2s ease";

    const timeoutButton = document.createElement("div");
    timeoutButton.className = "lol-uikit-slider-button";
    timeoutButton.style.left = "0px"; // Initial position
    timeoutButton.style.width = "30px";
    timeoutButton.style.height = "30px";
    timeoutButton.style.background = "url('/fe/lol-uikit/images/slider-btn.png') no-repeat top left";
    timeoutButton.style.backgroundSize = "100%";
    timeoutButton.style.position = "absolute";
    timeoutButton.style.top = "0px";
    timeoutButton.style.cursor = "pointer";
    timeoutButton.style.transition = "left 0.1s ease-out, background-position 0.2s ease";

    timeoutSliderBase.appendChild(timeoutTrack);
    timeoutSliderBase.appendChild(timeoutFill);
    timeoutSliderBase.appendChild(timeoutButton);
    timeoutSliderUI.appendChild(timeoutSliderBase);
    timeoutSliderWrapper.appendChild(timeoutSlider);
    timeoutSliderWrapper.appendChild(timeoutSliderUI);
    timeoutSliderContainer.appendChild(timeoutSliderWrapper);
    timeoutSection.appendChild(timeoutSliderContainer);
    form.appendChild(timeoutSection);

    // Autostart section
    const autostartSection = document.createElement("div");
    autostartSection.className = "settings-section";

    const autostartLabel = document.createElement("label");
    autostartLabel.className = "settings-label";
    autostartLabel.textContent = "Start automatically with Windows:";
    autostartSection.appendChild(autostartLabel);

    const autostartWrapper = document.createElement("div");
    autostartWrapper.className = "settings-checkbox-wrapper";

    const autostartCheckbox = document.createElement("input");
    autostartCheckbox.type = "checkbox";
    autostartCheckbox.className = "settings-checkbox";
    autostartCheckbox.id = "autostart-checkbox";
    autostartWrapper.appendChild(autostartCheckbox);

    const autostartText = document.createElement("span");
    autostartText.textContent = "Enable auto-start";
    autostartWrapper.appendChild(autostartText);
    autostartSection.appendChild(autostartWrapper);
    form.appendChild(autostartSection);

    // Game path section
    const pathSection = document.createElement("div");
    pathSection.className = "settings-section";

    const pathLabel = document.createElement("label");
    pathLabel.className = "settings-label";
    pathLabel.textContent = "League of Legends Game Path:";
    pathSection.appendChild(pathLabel);

    const pathInputWrapper = document.createElement("div");
    pathInputWrapper.style.display = "flex";
    pathInputWrapper.style.alignItems = "center";

    const pathInput = document.createElement("input");
    pathInput.type = "text";
    pathInput.className = "settings-input";
    pathInput.id = "game-path-input";
    pathInput.placeholder = "C:\\Riot Games\\League of Legends\\Game";
    pathInput.addEventListener("input", () => {
      updatePathStatus();
    });
    pathInputWrapper.appendChild(pathInput);

    const pathStatus = document.createElement("span");
    pathStatus.className = "settings-status";
    pathStatus.id = "path-status";
    pathStatus.textContent = "";
    pathInputWrapper.appendChild(pathStatus);
    pathSection.appendChild(pathInputWrapper);
    form.appendChild(pathSection);

    // Add custom mods dropdown
    const modsDropdownContainer = document.createElement("div");
    modsDropdownContainer.style.marginTop = "8px";
    modsDropdownContainer.style.width = "100%";

    const modsDropdown = document.createElement("lol-uikit-framed-dropdown");
    modsDropdown.id = "add-custom-mods-dropdown";
    modsDropdown.className = "lol-publishing-locale-preference-dropdown";
    modsDropdown.setAttribute("tabindex", "0");
    modsDropdown.style.width = "100%";

    // Add placeholder option for header display (hidden in dropdown menu)
    const placeholderOption = document.createElement("lol-uikit-dropdown-option");
    placeholderOption.setAttribute("slot", "lol-uikit-dropdown-option");
    placeholderOption.setAttribute("value", "");
    placeholderOption.className = "framed-dropdown-type placeholder-option";
    placeholderOption.textContent = "Add custom mods";
    placeholderOption.style.color = "#7d7d7d";
    placeholderOption.style.opacity = "0.7";
    placeholderOption.style.pointerEvents = "none";
    placeholderOption.style.cursor = "default";
    placeholderOption.setAttribute("selected", ""); // Show in header
    // Prevent any click events on the placeholder
    placeholderOption.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation();
      return false;
    }, true); // Use capture phase to catch early
    modsDropdown.appendChild(placeholderOption);

    const categories = [
      { id: "skins", name: "Skins" },
      { id: "maps", name: "Maps" },
      { id: "fonts", name: "Fonts" },
      { id: "announcers", name: "Announcers" },
      { id: "ui", name: "UI" },
      { id: "voiceover", name: "Voiceover" },
      { id: "loading_screen", name: "Loading Screen" },
      { id: "vfx", name: "VFX" },
      { id: "sfx", name: "SFX" },
      { id: "others", name: "Others" },
    ];

    categories.forEach((category) => {
      const option = document.createElement("lol-uikit-dropdown-option");
      option.setAttribute("slot", "lol-uikit-dropdown-option");
      option.setAttribute("value", category.id);
      option.className = "framed-dropdown-type";
      option.textContent = category.name;
      modsDropdown.appendChild(option);
    });

    // Function to aggressively remove focus and glow effects
    const removeFocusAndGlow = () => {
      // Blur the dropdown element
      if (document.activeElement === modsDropdown || modsDropdown.contains(document.activeElement)) {
        modsDropdown.blur();
      }

      // Blur any focused elements within the dropdown
      const focusedElement = modsDropdown.querySelector(':focus');
      if (focusedElement) {
        focusedElement.blur();
      }

      // Remove focus-related attributes and classes
      modsDropdown.removeAttribute('tabindex');
      modsDropdown.setAttribute('tabindex', '0');

      // Blur elements in shadow DOM if accessible
      const shadowRoot = modsDropdown.shadowRoot;
      if (shadowRoot) {
        const shadowFocused = shadowRoot.activeElement;
        if (shadowFocused) {
          shadowFocused.blur();
        }
        // Remove focus from all focusable elements in shadow DOM
        shadowRoot.querySelectorAll('*').forEach(el => {
          if (el === shadowRoot.activeElement || el.matches(':focus')) {
            el.blur();
          }
        });
      }

      // Force focus to body or another element to ensure dropdown loses focus
      if (document.body) {
        document.body.focus();
      }
      // Remove focus completely
      if (document.activeElement && document.activeElement !== document.body) {
        document.activeElement.blur();
      }
    };

    // Function to reset dropdown to placeholder and close it
    const resetDropdown = () => {
      // Remove active class to close dropdown
      modsDropdown.classList.remove("active");
      // Remove selected from all category options
      modsDropdown.querySelectorAll('lol-uikit-dropdown-option[value!=""]').forEach(opt => {
        opt.removeAttribute("selected");
      });
      // Reset to placeholder option for header display
      const placeholder = modsDropdown.querySelector('.placeholder-option');
      if (placeholder) {
        placeholder.setAttribute("selected", "");
        // Force the dropdown to use placeholder value
        if (modsDropdown.setAttribute) {
          modsDropdown.setAttribute("value", "");
        }
      }

      // Aggressively remove focus and glow effects
      removeFocusAndGlow();

      // Force reset again after a short delay to catch any framework updates
      setTimeout(() => {
        const placeholder = modsDropdown.querySelector('.placeholder-option');
        if (placeholder && !placeholder.hasAttribute('selected')) {
          placeholder.setAttribute("selected", "");
        }
        modsDropdown.querySelectorAll('lol-uikit-dropdown-option[value!=""]').forEach(opt => {
          opt.removeAttribute("selected");
        });
        // Remove focus again after framework updates
        removeFocusAndGlow();
      }, 10);
    };

    // Handle dropdown selection change - prevent showing selected value
    modsDropdown.addEventListener("change", (e) => {
      const selectedValue = e.target.value || e.detail?.value;
      if (selectedValue) {
        handleCategorySelection(selectedValue);
        // Immediately reset to placeholder before UI updates
        resetDropdown();
      }
    });

    // Handle click on options - prevent showing selected value
    modsDropdown.querySelectorAll('lol-uikit-dropdown-option').forEach((option) => {
      option.addEventListener("click", (e) => {
        e.stopPropagation();
        const categoryId = option.getAttribute("value");
        // Ignore placeholder option (empty value)
        if (categoryId) {
          // Prevent the option from being selected
          option.removeAttribute("selected");
          handleCategorySelection(categoryId);
          // Immediately reset to placeholder
          resetDropdown();
          // Remove focus immediately and after delays
          setTimeout(() => removeFocusAndGlow(), 0);
          setTimeout(() => removeFocusAndGlow(), 50);
          setTimeout(() => removeFocusAndGlow(), 100);
          setTimeout(() => removeFocusAndGlow(), 200);
        }
      }, true); // Use capture phase to intercept early
    });

    // Watch for any selected attribute changes and reset to placeholder
    const observer = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
        if (mutation.type === 'attributes' && mutation.attributeName === 'selected') {
          const target = mutation.target;
          // If a category option (not placeholder) gets selected, reset it
          if (target.getAttribute('value') && target.getAttribute('value') !== '') {
            const placeholder = modsDropdown.querySelector('.placeholder-option');
            if (placeholder && !placeholder.hasAttribute('selected')) {
              // Remove selected from category option
              target.removeAttribute('selected');
              // Set placeholder as selected
              placeholder.setAttribute('selected', '');
            }
          }
        }
      });
    });

    // Observe all dropdown options for selected attribute changes
    modsDropdown.querySelectorAll('lol-uikit-dropdown-option').forEach((option) => {
      observer.observe(option, { attributes: true, attributeFilter: ['selected'] });
    });

    modsDropdownContainer.appendChild(modsDropdown);
    form.appendChild(modsDropdownContainer);

    // Inject shadow DOM styles to override :host .ui-dropdown color
    let retryCount = 0;
    const MAX_RETRIES = 20;
    const injectShadowStyles = () => {
      const root = modsDropdown.shadowRoot;
      if (!root) {
        // Shadow root might not be ready yet, try again (up to MAX_RETRIES times)
        if (retryCount < MAX_RETRIES) {
          retryCount++;
          setTimeout(injectShadowStyles, 50);
        }
        return;
      }

      // Check if style already injected
      if (root.querySelector('style[data-rose-dropdown-color]')) {
        return;
      }

      const rootStyle = document.createElement("style");
      rootStyle.setAttribute("data-rose-dropdown-color", "true");
      rootStyle.textContent = `
        :host .ui-dropdown {
          color: #CDBE91 !important;
          font-size: 12px !important;
          font-weight: normal !important;
          line-height: 16px !important;
          letter-spacing: 0.025em !important;
          -webkit-font-smoothing: subpixel-antialiased !important;
        }
        
        /* Remove all glow effects when not focused */
        :host:not(:focus):not(:focus-within) .ui-dropdown,
        :host:not(:focus):not(:focus-within) * {
          filter: none !important;
          -webkit-filter: none !important;
          box-shadow: none !important;
          text-shadow: none !important;
          outline: none !important;
        }
      `;
      root.appendChild(rootStyle);
    };

    // Try to inject styles immediately and retry if shadow root isn't ready
    injectShadowStyles();

    // Remove focus/shine effect after clicking - use the comprehensive function
    modsDropdown.addEventListener("click", (e) => {
      // Only remove focus if clicking outside of options (on the button itself)
      if (!e.target.closest('lol-uikit-dropdown-option')) {
        setTimeout(() => removeFocusAndGlow(), 100);
      }
    });

    // Remove focus when mouse leaves the dropdown area
    modsDropdown.addEventListener("mouseleave", () => {
      // Only remove focus if dropdown is not active/open
      if (!modsDropdown.classList.contains('active')) {
        removeFocusAndGlow();
      }
    });

    // Also blur when dropdown closes
    modsDropdown.addEventListener("change", () => {
      setTimeout(() => removeFocusAndGlow(), 50);
      setTimeout(() => removeFocusAndGlow(), 150);
    });

    // Watch for when dropdown closes (active class removed) and remove focus
    const activeObserver = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
        if (mutation.type === 'attributes' && mutation.attributeName === 'class') {
          // If active class was removed, ensure focus is removed
          if (!modsDropdown.classList.contains('active')) {
            removeFocusAndGlow();
            // Also remove focus after a delay to catch any late updates
            setTimeout(() => removeFocusAndGlow(), 50);
            setTimeout(() => removeFocusAndGlow(), 150);
          }
        }
      });
    });
    activeObserver.observe(modsDropdown, { attributes: true, attributeFilter: ['class'] });

    // Open logs folder button
    const logsButton = document.createElement("lol-uikit-flat-button-secondary");
    logsButton.id = "logs-folder-button";
    logsButton.textContent = "Open Logs Folder";
    logsButton.style.marginTop = "8px";
    logsButton.style.width = "100%";
    logsButton.addEventListener("click", () => {
      openLogsFolder();
    });
    form.appendChild(logsButton);

    // Troubleshooting button (opens a small dialog with compact errors)
    const troubleshootButton = document.createElement("lol-uikit-flat-button-secondary");
    troubleshootButton.id = "troubleshoot-button";
    troubleshootButton.textContent = "Troubleshooting";
    troubleshootButton.style.marginTop = "8px";
    troubleshootButton.style.width = "100%";
    troubleshootButton.addEventListener("click", () => {
      openDiagnosticsDialog();
    });
    form.appendChild(troubleshootButton);

    // Open Pengu Loader UI button
    const penguUIButton = document.createElement("lol-uikit-flat-button-secondary");
    penguUIButton.id = "pengu-ui-button";
    penguUIButton.textContent = "Open Pengu Loader UI";
    penguUIButton.style.marginTop = "8px";
    penguUIButton.style.width = "100%";
    penguUIButton.addEventListener("click", () => {
      openPenguLoaderUI();
    });
    form.appendChild(penguUIButton);

    // Save button (moved to last position)
    const saveButton = document.createElement("lol-uikit-flat-button-secondary");
    saveButton.id = "save-button";
    saveButton.textContent = "Save";
    saveButton.style.marginTop = "8px";
    saveButton.style.width = "21%";
    saveButton.addEventListener("click", () => {
      saveSettings();
    });
    form.appendChild(saveButton);

    // Links section
    const linksSection = document.createElement("div");
    linksSection.className = "settings-links";

    const discordLink = document.createElement("a");
    discordLink.className = "settings-link";
    discordLink.href = DISCORD_INVITE_URL;
    discordLink.target = "_blank";
    discordLink.textContent = "Discord";
    linksSection.appendChild(discordLink);

    const kofiLink = document.createElement("a");
    kofiLink.className = "settings-link";
    kofiLink.href = KOFI_URL;
    kofiLink.target = "_blank";
    kofiLink.textContent = "Ko-Fi";
    linksSection.appendChild(kofiLink);

    const githubLink = document.createElement("a");
    githubLink.className = "settings-link";
    githubLink.href = GITHUB_URL;
    githubLink.target = "_blank";
    githubLink.textContent = "GitHub";
    linksSection.appendChild(githubLink);

    form.appendChild(linksSection);

    flyoutContent.appendChild(form);
    flyoutFrame.appendChild(flyoutContent);
    panel.appendChild(flyoutFrame);

    // Setup slider interactions after form is added to DOM
    setTimeout(() => {
      setupSliderInteractions("threshold", thresholdSlider, thresholdButton, thresholdFill, thresholdValue, thresholdMin, thresholdMax, (value) => {
        return parseFloat(value) / 100;
      }, (value) => {
        return `${value.toFixed(2)} s`;
      });

      // Use the slider element's min/max so UI stays correct when limits change
      setupSliderInteractions(
        "timeout",
        timeoutSlider,
        timeoutButton,
        timeoutFill,
        timeoutValue,
        parseInt(timeoutSlider.min || "20", 10),
        parseInt(timeoutSlider.max || "180", 10),
        (value) => {
          return parseInt(value);
      }, (value) => {
        return `${value} s`;
      });
    }, 100);

    settingsPanel = panel;

    // Recalculate position after adding to DOM to ensure accurate positioning
    _flyoutRepositionTimer = setTimeout(() => {
      // If panel was closed before this runs, do nothing.
      if (!settingsPanel || !document.getElementById(PANEL_ID)) return;
      const liveFlyout = document.getElementById(FLYOUT_ID);
      if (!liveFlyout) return;
      const updatedIconElement =
        navItem.querySelector(".menu-item-icon") ||
        navItem.querySelector(".menu-item-icon-wrapper") ||
        navItem;
      const updatedIconRect = updatedIconElement.getBoundingClientRect();
      liveFlyout.style.top = `${updatedIconRect.bottom + 45}px`;
      liveFlyout.style.left = `${updatedIconRect.left + updatedIconRect.width / 2
        }px`;
      liveFlyout.style.transform = "translateX(-50%)"; // Center the panel on the icon
    }, 0);

    // Request current settings
    requestSettings();
  }

  function setupSliderInteractions(sliderId, slider, button, fill, valueDisplay, min, max, valueConverter, displayFormatter) {
    if (!slider || !button || !fill || !valueDisplay) return;

    let isHovered = false;
    let isDragging = false;

    const updateSlider = (rawValue) => {
      const value = Math.max(min, Math.min(max, rawValue));
      const percentage = ((value - min) / (max - min)) * 100;
      const sliderWidth = 400;
      const buttonWidth = 30;
      const maxPosition = sliderWidth - buttonWidth; // 370px max to keep button within bounds
      const buttonPosition = (percentage / 100) * maxPosition;

      if (isDragging) {
        button.style.transition = 'none';
        fill.style.transition = 'none';
      } else {
        button.style.transition = 'left 0.1s ease-out';
        fill.style.transition = 'width 0.1s ease-out, background 0.2s ease';
      }

      button.style.left = `${buttonPosition}px`;
      fill.style.width = `${buttonPosition}px`;

      const convertedValue = valueConverter(value);
      valueDisplay.textContent = displayFormatter(convertedValue);
      slider.value = value;

      // Maintain hover effects after slider update
      if (!isDragging) {
        updateHoverEffects();
      }
    };

    const updateHoverEffects = () => {
      if (isHovered || isDragging) {
        fill.style.background = isDragging
          ? 'linear-gradient(to right, #695625, #463714)'
          : 'linear-gradient(to right, #785a28 0%, #c89b3c 56%, #c8aa6e 100%)';
        button.style.backgroundPosition = isDragging ? '0 -60px' : '0 -30px';
      } else {
        fill.style.background = 'linear-gradient(to left, #695625, #463714)';
        button.style.backgroundPosition = '0 0';
      }
    };

    slider.addEventListener('input', (e) => {
      updateSlider(parseInt(e.target.value));
    });

    // Use the slider container for hover detection to be more precise
    const sliderContainer = slider.closest('.lol-settings-slider');
    if (sliderContainer) {
      sliderContainer.addEventListener('mouseenter', () => {
        isHovered = true;
        updateHoverEffects();
      });

      sliderContainer.addEventListener('mouseleave', () => {
        isHovered = false;
        updateHoverEffects();
      });

      // Also handle mouseover on child elements to ensure hover state is maintained
      const handleMouseOver = () => {
        if (!isHovered) {
          isHovered = true;
          updateHoverEffects();
        }
      };

      const handleMouseOut = (e) => {
        // Check if we're actually leaving the container
        const relatedTarget = e.relatedTarget;
        if (!relatedTarget || !sliderContainer.contains(relatedTarget)) {
          isHovered = false;
          updateHoverEffects();
        }
      };

      // Add listeners to all interactive child elements
      const buttonElement = sliderContainer.querySelector('.lol-uikit-slider-button');
      const trackElement = sliderContainer.querySelector('.lol-uikit-slider-base-track');

      if (buttonElement) {
        buttonElement.addEventListener('mouseover', handleMouseOver);
        buttonElement.addEventListener('mouseout', handleMouseOut);
      }

      if (trackElement) {
        trackElement.addEventListener('mouseover', handleMouseOver);
        trackElement.addEventListener('mouseout', handleMouseOut);
      }
    }

    const handleMouseMove = (e) => {
      if (!isDragging) return;

      const sliderRect = slider.getBoundingClientRect();
      const x = Math.max(0, Math.min(sliderRect.width, e.clientX - sliderRect.left));
      const percentage = x / sliderRect.width;
      const value = Math.round(percentage * (max - min) + min);

      updateSlider(value);
    };

    const cleanupDragging = () => {
      if (!isDragging) return;

      isDragging = false;
      updateHoverEffects();

      button.style.transition = 'left 0.1s ease-out';
      fill.style.transition = 'width 0.1s ease-out, background 0.2s ease';

      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', cleanupDragging);
      document.removeEventListener('mouseleave', cleanupDragging);
    };

    button.addEventListener('mousedown', (e) => {
      isDragging = true;
      updateHoverEffects();
      e.preventDefault();

      button.style.transition = 'none';
      fill.style.transition = 'none';

      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', cleanupDragging);
      document.addEventListener('mouseleave', cleanupDragging);
    });

    const track = slider.closest('.lol-settings-slider')?.querySelector('.lol-uikit-slider-base-track');
    if (track) {
      track.addEventListener('click', (e) => {
        const sliderRect = slider.getBoundingClientRect();
        const x = Math.max(0, Math.min(sliderRect.width, e.clientX - sliderRect.left));
        const percentage = x / sliderRect.width;
        const value = Math.round(percentage * (max - min) + min);

        updateSlider(value);
      });
    }

    // Initialize position
    updateSlider(parseInt(slider.value));
  }

  function updateSettingsForm() {
    const thresholdSlider = document.getElementById("threshold-slider");
    const thresholdValue = document.getElementById("threshold-value");
    const thresholdButton = thresholdSlider?.closest('.lol-settings-slider')?.querySelector('.lol-uikit-slider-button');
    const thresholdFill = thresholdSlider?.closest('.lol-settings-slider')?.querySelector('.lol-uikit-slider-fill');
    const timeoutSlider = document.getElementById("timeout-slider");
    const timeoutValue = document.getElementById("timeout-value");
    const timeoutButton = timeoutSlider?.closest('.lol-settings-slider')?.querySelector('.lol-uikit-slider-button');
    const timeoutFill = timeoutSlider?.closest('.lol-settings-slider')?.querySelector('.lol-uikit-slider-fill');
    const autostartCheckbox = document.getElementById("autostart-checkbox");
    const pathInput = document.getElementById("game-path-input");

    if (thresholdSlider && thresholdValue && thresholdButton && thresholdFill) {
      const sliderValue = Math.round(currentSettings.threshold * 100);
      thresholdSlider.value = sliderValue;
      thresholdValue.textContent = `${currentSettings.threshold.toFixed(2)} s`;
      const min = parseInt(thresholdSlider.min || "30", 10);
      const max = parseInt(thresholdSlider.max || "200", 10);
      const percentage = ((sliderValue - min) / (max - min)) * 100;
      const maxPosition = 400 - 30; // 370px max
      const buttonPosition = (percentage / 100) * maxPosition;
      thresholdButton.style.left = `${buttonPosition}px`;
      thresholdFill.style.width = `${buttonPosition}px`;
    }

    if (timeoutSlider && timeoutValue && timeoutButton && timeoutFill) {
      timeoutSlider.value = currentSettings.monitorAutoResumeTimeout;
      timeoutValue.textContent = `${currentSettings.monitorAutoResumeTimeout} s`;
      const min = parseInt(timeoutSlider.min || "20", 10);
      const max = parseInt(timeoutSlider.max || "180", 10);
      const percentage = ((currentSettings.monitorAutoResumeTimeout - min) / (max - min)) * 100;
      const maxPosition = 400 - 30; // 370px max
      const buttonPosition = (percentage / 100) * maxPosition;
      timeoutButton.style.left = `${buttonPosition}px`;
      timeoutFill.style.width = `${buttonPosition}px`;
    }

    if (autostartCheckbox) {
      autostartCheckbox.checked = currentSettings.autostart;
    }

    if (pathInput) {
      pathInput.value = currentSettings.gamePath || "";
      // Update status based on validation result from settings data
      const pathStatus = document.getElementById("path-status");
      if (pathStatus) {
        const path = pathInput.value.trim();
        if (path.length === 0) {
          pathStatus.textContent = "";
        } else if (currentSettings.gamePathValid) {
          pathStatus.textContent = "✅";
        } else {
          // Request validation for the loaded path
          requestPathValidation(path);
        }
      }
    }
  }

  function updatePathStatus() {
    const pathInput = document.getElementById("game-path-input");
    const pathStatus = document.getElementById("path-status");

    if (!pathInput || !pathStatus) {
      return;
    }

    const path = pathInput.value.trim();
    if (path.length === 0) {
      pathStatus.textContent = "";
      return;
    }

    // Show loading indicator while validating
    pathStatus.textContent = "⏳";

    // Clear any existing timeout
    if (pathValidationTimeout) {
      clearTimeout(pathValidationTimeout);
    }

    // Debounce validation request (wait 500ms after user stops typing)
    pathValidationTimeout = setTimeout(() => {
      requestPathValidation(path);
    }, 500);
  }

  function requestPathValidation(path) {
    if (!path || !path.trim()) {
      return;
    }

    sendToBridge({
      type: "path-validate",
      gamePath: path.trim(),
    });
  }

  function requestSettings() {
    sendToBridge({
      type: "settings-request",
    });
  }

  function saveSettings() {
    const thresholdSlider = document.getElementById("threshold-slider");
    const timeoutSlider = document.getElementById("timeout-slider");
    const autostartCheckbox = document.getElementById("autostart-checkbox");
    const pathInput = document.getElementById("game-path-input");

    const threshold = thresholdSlider
      ? parseFloat(thresholdSlider.value) / 100
      : 0.5;
    const monitorAutoResumeTimeout = timeoutSlider
      ? parseInt(timeoutSlider.value)
      : 60;
    const autostart = autostartCheckbox ? autostartCheckbox.checked : false;
    const gamePath = pathInput ? pathInput.value.trim() : "";

    // Clamp threshold between 0.30 and 2.0
    const clampedThreshold = Math.max(0.3, Math.min(2.0, threshold));
    // Clamp timeout between 20 and 180
    const clampedTimeout = Math.max(20, Math.min(180, monitorAutoResumeTimeout));

    // Track what we're trying to save; we only clear warnings after the save succeeds.
    _pendingSave = { threshold: clampedThreshold, monitorAutoResumeTimeout: clampedTimeout };

    sendToBridge({
      type: "settings-save",
      threshold: clampedThreshold,
      monitorAutoResumeTimeout: clampedTimeout,
      autostart: autostart,
      gamePath: gamePath,
    });

    log("info", "Settings save requested", {
      threshold: clampedThreshold,
      monitorAutoResumeTimeout: clampedTimeout,
      autostart,
      gamePath,
    });
  }

  function openAddCustomModsDialog() {
    createCategorySelectionDialog();
    log("info", "Add custom mods dialog opened");
  }

  function createCategorySelectionDialog() {
    // Remove existing dialog if any
    const existingDialog = document.getElementById("add-custom-mods-dialog");
    if (existingDialog) {
      existingDialog.remove();
    }

    // Create dialog container
    const dialog = document.createElement("div");
    dialog.id = "add-custom-mods-dialog";
    dialog.style.position = "fixed";
    dialog.style.top = "0";
    dialog.style.left = "0";
    dialog.style.width = "100%";
    dialog.style.height = "100%";
    dialog.style.zIndex = "10001";
    dialog.style.pointerEvents = "none";
    document.body.appendChild(dialog);

    // Create backdrop
    const backdrop = document.createElement("div");
    backdrop.className = "backdrop";
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) {
        closeCategoryDialog();
      }
    });
    dialog.appendChild(backdrop);

    // Create flyout frame
    let flyoutFrame;
    try {
      flyoutFrame = document.createElement("lol-uikit-flyout-frame");
      flyoutFrame.id = "add-custom-mods-flyout";
      flyoutFrame.className = "flyout";
      flyoutFrame.setAttribute("orientation", "center");
      flyoutFrame.setAttribute("animated", "true");
      flyoutFrame.setAttribute("show", "true");
    } catch (e) {
      log("debug", "Could not create custom element, using div", e);
      flyoutFrame = document.createElement("div");
      flyoutFrame.id = "add-custom-mods-flyout";
      flyoutFrame.className = "flyout";
    }

    flyoutFrame.style.position = "absolute";
    flyoutFrame.style.top = "50%";
    flyoutFrame.style.left = "50%";
    flyoutFrame.style.transform = "translate(-50%, -50%)";
    flyoutFrame.style.zIndex = "10002";
    flyoutFrame.style.pointerEvents = "all";

    // Create flyout content
    let flyoutContent;
    try {
      flyoutContent = document.createElement("lc-flyout-content");
    } catch (e) {
      log("debug", "Could not create lc-flyout-content, using div", e);
      flyoutContent = document.createElement("div");
      flyoutContent.className = "lc-flyout-content";
    }

    // Title
    const title = document.createElement("div");
    title.className = "settings-title";
    title.textContent = "Add Custom Mods";
    flyoutContent.appendChild(title);

    // Category buttons container
    const categoriesContainer = document.createElement("div");
    categoriesContainer.style.display = "flex";
    categoriesContainer.style.flexDirection = "column";
    categoriesContainer.style.gap = "10px";

    const categories = [
      { id: "skins", name: "Skins" },
      { id: "maps", name: "Maps" },
      { id: "fonts", name: "Fonts" },
      { id: "announcers", name: "Announcers" },
      { id: "ui", name: "UI" },
      { id: "voiceover", name: "Voiceover" },
      { id: "loading_screen", name: "Loading Screen" },
      { id: "vfx", name: "VFX" },
      { id: "sfx", name: "SFX" },
      { id: "others", name: "Others" },
    ];

    categories.forEach((category) => {
      const categoryButton = document.createElement("lol-uikit-flat-button-secondary");
      categoryButton.textContent = category.name;
      categoryButton.style.width = "100%";
      categoryButton.style.padding = "12px";
      categoryButton.addEventListener("click", () => {
        handleCategorySelection(category.id);
      });
      categoriesContainer.appendChild(categoryButton);
    });

    flyoutContent.appendChild(categoriesContainer);
    flyoutFrame.appendChild(flyoutContent);
    dialog.appendChild(flyoutFrame);

    // Prevent click from closing
    flyoutFrame.addEventListener("click", (e) => {
      e.stopPropagation();
    });
  }

  function closeCategoryDialog() {
    const dialog = document.getElementById("add-custom-mods-dialog");
    if (dialog) {
      dialog.remove();
    }
  }

  function handleCategorySelection(category) {
    closeCategoryDialog();

    if (category === "skins") {
      // Open champion selection for skins
      openChampionSelection();
    } else {
      // Directly open folder for other categories
      sendToBridge({
        type: "add-custom-mods-category-selected",
        category: category,
      });
      log("info", `Category selected: ${category}`);
    }
  }

  function openChampionSelection() {
    // Remove existing dialog if any
    const existingDialog = document.getElementById("champion-selection-dialog");
    if (existingDialog) {
      existingDialog.remove();
    }

    // Dialog is the backdrop itself — no extra wrapper
    const dialog = document.createElement("div");
    dialog.id = "champion-selection-dialog";
    dialog.addEventListener("click", (e) => {
      if (e.target === dialog) {
        closeChampionSelection();
      }
    });
    document.body.appendChild(dialog);

    // Create flyout frame
    const flyoutFrame = document.createElement("div");
    flyoutFrame.id = "champion-selection-flyout";
    flyoutFrame.className = "flyout";
    flyoutFrame.style.maxHeight = "75vh";
    flyoutFrame.style.width = "700px";
    flyoutFrame.style.overflowY = "hidden";
    flyoutFrame.style.overflowX = "hidden";
    flyoutFrame.addEventListener("click", (e) => e.stopPropagation());

    // Create flyout content
    const flyoutContent = document.createElement("div");
    flyoutContent.className = "lc-flyout-content";

    // Header with back button and title
    const header = document.createElement("div");
    header.className = "dialog-header";

    // Back button
    const backButton = document.createElement("button");
    backButton.className = "back-button";
    backButton.innerHTML = '<svg viewBox="0 0 24 24"><polyline points="15 18 9 12 15 6"></polyline></svg>';
    backButton.setAttribute("aria-label", "Go back");
    backButton.addEventListener("click", () => {
      closeChampionSelection();
    });
    header.appendChild(backButton);

    // Title text
    const titleWrapper = document.createElement("div");
    titleWrapper.className = "dialog-title-wrapper";
    titleWrapper.textContent = "Select Champion";
    header.appendChild(titleWrapper);

    flyoutContent.appendChild(header);

    // Search input using League UI component
    const searchContainer = document.createElement("div");
    searchContainer.className = "settings-section";

    let flatInput;
    try {
      flatInput = document.createElement("lol-uikit-flat-input");
    } catch (e) {
      flatInput = document.createElement("div");
      flatInput.className = "lol-uikit-flat-input";
    }
    flatInput.className = "champion-search-input";
    flyoutContent.style.width = "700px";

    const searchInput = document.createElement("input");
    searchInput.type = "search";
    searchInput.name = "champion_search";
    searchInput.id = "champion-search-input";
    searchInput.placeholder = "Search champions...";
    searchInput.autocomplete = "off";
    searchInput.autocorrect = "off";
    searchInput.autocapitalize = "off";
    searchInput.spellcheck = "false";

    flatInput.appendChild(searchInput);
    searchContainer.appendChild(flatInput);
    flyoutContent.appendChild(searchContainer);

    // Loading indicator
    const loadingIndicator = document.createElement("div");
    loadingIndicator.id = "champion-loading";
    loadingIndicator.textContent = "Loading champions...";
    loadingIndicator.style.color = "#cdbe91";
    loadingIndicator.style.textAlign = "center";
    loadingIndicator.style.padding = "20px";
    loadingIndicator.style.fontFamily = '"Beaufort for LOL", serif';
    flyoutContent.appendChild(loadingIndicator);

    // Champions grid wrapper
    const championsGridWrapper = document.createElement("div");
    championsGridWrapper.id = "champions-grid-wrapper";
    championsGridWrapper.style.overflowY = "auto";
    championsGridWrapper.style.overflowX = "hidden";
    championsGridWrapper.style.maxHeight = "45vh";
    championsGridWrapper.style.marginTop = "12px";

    // Champions grid container
    const championsGrid = document.createElement("div");
    championsGrid.id = "champions-grid";
    championsGridWrapper.appendChild(championsGrid);
    flyoutContent.appendChild(championsGridWrapper);

    flyoutFrame.appendChild(flyoutContent);
    dialog.appendChild(flyoutFrame);

    // Request champions list
    sendToBridge({
      type: "add-custom-mods-champion-selected",
      action: "list",
    });

    // Search functionality
    searchInput.addEventListener("input", (e) => {
      const searchTerm = e.target.value.toLowerCase().trim();
      const allChampions = window.__roseAllChampions || [];
      const filtered = allChampions.filter((champ) =>
        champ.name.toLowerCase().includes(searchTerm)
      );
      renderChampionsGrid(filtered);
    });

    // Store render function for bridge response
    window.__roseChampionRenderer = renderChampionsGrid;
  }

  function closeChampionSelection() {
    const dialog = document.getElementById("champion-selection-dialog");
    if (dialog) {
      dialog.remove();
    }
    delete window.__roseChampionRenderer;
    delete window.__roseAllChampions;
  }

  function renderChampionsGrid(champions) {
    const championsGrid = document.getElementById("champions-grid");
    if (!championsGrid) return;

    championsGrid.innerHTML = "";

    if (champions.length === 0) {
      championsGrid.innerHTML = `<div style="grid-column: 1 / -1; color: #cdbe91; text-align: center; padding: 20px; font-family: 'Beaufort for LOL', serif;">No champions found matching your search.</div>`;
      return;
    }

    champions.forEach((champion) => {
      const card = document.createElement("div");
      card.className = "champion-card";

      const img = document.createElement("img");
      img.src = `/lol-game-data/assets/v1/champion-icons/${champion.id}.png`;
      img.alt = champion.name;
      img.loading = "lazy";
      img.onerror = function () { this.style.display = "none"; };
      card.appendChild(img);

      const name = document.createElement("div");
      name.className = "champion-name";
      name.textContent = champion.name;
      card.appendChild(name);

      card.addEventListener("click", () => handleChampionSelection(champion.id));
      championsGrid.appendChild(card);
    });
  }

  function handleChampionSelection(championId) {
    closeChampionSelection();
    openSkinSelection(championId);
  }

  function openSkinSelection(championId) {
    // Remove existing dialog if any
    const existingDialog = document.getElementById("skin-selection-dialog");
    if (existingDialog) {
      existingDialog.remove();
    }

    // Dialog is the backdrop itself
    const dialog = document.createElement("div");
    dialog.id = "skin-selection-dialog";
    dialog.addEventListener("click", (e) => {
      if (e.target === dialog) {
        closeSkinSelection();
      }
    });
    document.body.appendChild(dialog);

    // Create flyout frame
    const flyoutFrame = document.createElement("div");
    flyoutFrame.id = "skin-selection-flyout";
    flyoutFrame.className = "flyout";
    flyoutFrame.style.maxHeight = "75vh";
    flyoutFrame.style.width = "700px";
    flyoutFrame.style.overflowY = "hidden";
    flyoutFrame.style.overflowX = "hidden";
    flyoutFrame.addEventListener("click", (e) => e.stopPropagation());

    // Create flyout content
    const flyoutContent = document.createElement("div");
    flyoutContent.className = "lc-flyout-content";

    // Header with back button and title
    const header = document.createElement("div");
    header.className = "dialog-header";
    header.id = "skin-selection-header";

    // Back button
    const backButton = document.createElement("button");
    backButton.className = "back-button";
    backButton.innerHTML = '<svg viewBox="0 0 24 24"><polyline points="15 18 9 12 15 6"></polyline></svg>';
    backButton.setAttribute("aria-label", "Go back");
    backButton.addEventListener("click", (e) => {
      e.stopPropagation();
      closeSkinSelection();
      openChampionSelection();
    });
    header.appendChild(backButton);

    // Title text
    const titleWrapper = document.createElement("div");
    titleWrapper.className = "dialog-title-wrapper";
    titleWrapper.textContent = "Select Skin";
    header.appendChild(titleWrapper);

    flyoutContent.appendChild(header);

    // Loading indicator
    const loadingIndicator = document.createElement("div");
    loadingIndicator.id = "skin-loading";
    loadingIndicator.textContent = "Loading skins...";
    loadingIndicator.style.color = "#cdbe91";
    loadingIndicator.style.textAlign = "center";
    loadingIndicator.style.padding = "20px";
    loadingIndicator.style.fontFamily = '"Beaufort for LOL", serif';
    flyoutContent.appendChild(loadingIndicator);

    // Skins list container
    const skinsList = document.createElement("div");
    skinsList.style.overflowY = "auto";
    skinsList.style.overflowX = "hidden";
    skinsList.id = "skins-list";

    // Create inner container for flex layout
    const skinsListContainer = document.createElement("div");
    skinsListContainer.className = "skins-list-container";
    skinsList.appendChild(skinsListContainer);

    flyoutContent.appendChild(skinsList);

    flyoutFrame.appendChild(flyoutContent);
    dialog.appendChild(flyoutFrame);

    // Request skins for champion
    sendToBridge({
      type: "add-custom-mods-skin-selected",
      action: "list",
      championId: championId,
    });

    // Store champion ID for later use
    window.__roseSelectedChampionId = championId;
  }

  function closeSkinSelection() {
    const dialog = document.getElementById("skin-selection-dialog");
    if (dialog) {
      dialog.remove();
    }
    delete window.__roseSelectedChampionId;
  }

  function handleSkinSelection(championId, skinId) {
    closeSkinSelection();

    sendToBridge({
      type: "add-custom-mods-skin-selected",
      action: "create",
      championId: championId,
      skinId: skinId,
    });
    log("info", `Skin selected: champion=${championId}, skin=${skinId}`);
  }

  function handleChampionsListResponse(payload) {
    const loadingIndicator = document.getElementById("champion-loading");
    if (loadingIndicator) {
      loadingIndicator.style.display = "none";
    }

    const championsGrid = document.getElementById("champions-grid");
    if (!championsGrid) return;

    if (payload.error) {
      championsGrid.innerHTML = `<div style="color: #ff6b6b; text-align: center; padding: 20px; font-family: 'Beaufort for LOL', serif;">${escapeHtml(payload.error)}</div>`;
      return;
    }

    const champions = payload.champions || [];
    if (champions.length === 0) {
      championsGrid.innerHTML = `<div style="color: #cdbe91; text-align: center; padding: 20px; font-family: 'Beaufort for LOL', serif;">No champions found. Please ensure League of Legends client is running.</div>`;
      return;
    }

    // Store champions for search functionality
    window.__roseAllChampions = champions;

    // Render champions
    if (window.__roseChampionRenderer) {
      window.__roseChampionRenderer(champions);
    } else {
      // Fallback: render directly
      renderChampionsGrid(champions);
    }
  }

  function handleChampionSkinsResponse(payload) {
    const loadingIndicator = document.getElementById("skin-loading");
    if (loadingIndicator) {
      loadingIndicator.style.display = "none";
    }

    const skinsList = document.getElementById("skins-list");
    if (!skinsList) return;

    if (payload.error) {
      let skinsListContainer = skinsList.querySelector(".skins-list-container");
      if (!skinsListContainer) {
        skinsListContainer = document.createElement("div");
        skinsListContainer.className = "skins-list-container";
        skinsList.innerHTML = "";
        skinsList.appendChild(skinsListContainer);
      } else {
        skinsListContainer.innerHTML = "";
      }
      skinsListContainer.innerHTML = `<div style="color: #ff6b6b; text-align: center; padding: 20px; font-family: 'Beaufort for LOL', serif;">${escapeHtml(payload.error)}</div>`;
      return;
    }

    const skins = payload.skins || [];
    const championId = payload.championId;

    // Update title with champion name if available
    const header = document.getElementById("skin-selection-header");
    if (header && payload.championName) {
      const titleWrapper = header.querySelector(".dialog-title-wrapper");
      if (titleWrapper) {
        titleWrapper.textContent = `Select Skin - ${payload.championName}`;
      }
    }

    // Get or create the container inside the scrollable
    let skinsListContainer = skinsList.querySelector(".skins-list-container");
    if (!skinsListContainer) {
      skinsListContainer = document.createElement("div");
      skinsListContainer.className = "skins-list-container";
      skinsList.innerHTML = "";
      skinsList.appendChild(skinsListContainer);
    } else {
      skinsListContainer.innerHTML = "";
    }

    if (skins.length === 0) {
      skinsListContainer.innerHTML = `<div style="color: #cdbe91; text-align: center; padding: 20px; font-family: 'Beaufort for LOL', serif;">No skins found for this champion.</div>`;
      return;
    }

    skins.forEach((skin) => {
      const card = document.createElement("div");
      card.className = "skin-card";

      const img = document.createElement("img");
      const skinId = skin.skinId || skin.id;
      img.src = skin.tilePath || `/lol-game-data/assets/v1/champion-tiles/${skinId}.jpg`;
      img.alt = skin.name || `Skin ${skinId}`;
      img.loading = "lazy";
      img.onerror = function () { this.style.display = "none"; };
      card.appendChild(img);

      const nameEl = document.createElement("div");
      nameEl.className = "skin-name";
      nameEl.textContent = skin.name || `Skin ${skinId}`;
      card.appendChild(nameEl);

      card.addEventListener("click", () => handleSkinSelection(championId, skinId));
      skinsListContainer.appendChild(card);
    });
  }

  function handleFolderOpenedResponse(payload) {
    if (payload.error) {
      log("error", `Failed to open folder: ${escapeHtml(payload.error)}`);
      // Could show an error message to user here
    } else {
      log("info", `Folder opened: ${payload.path}`);
    }
  }

  function openLogsFolder() {
    sendToBridge({
      type: "open-logs-folder",
    });
    log("info", "Open logs folder requested");
  }

  function requestDiagnostics() {
    sendToBridge({ type: "diagnostics-request" });
  }

  function openDiagnosticsDialog() {
    // If already open, close it
    const existing = document.getElementById("rose-diagnostics-dialog");
    if (existing) {
      existing.remove();
      diagnosticsDialog = null;
      return;
    }

    const dialog = document.createElement("div");
    dialog.id = "rose-diagnostics-dialog";
    dialog.style.position = "fixed";
    dialog.style.top = "0";
    dialog.style.left = "0";
    dialog.style.width = "100%";
    dialog.style.height = "100%";
    dialog.style.zIndex = "10002";
    dialog.style.pointerEvents = "none";
    document.body.appendChild(dialog);

    const backdrop = document.createElement("div");
    backdrop.style.position = "absolute";
    backdrop.style.top = "0";
    backdrop.style.left = "0";
    backdrop.style.width = "100%";
    backdrop.style.height = "100%";
    backdrop.style.background = "rgba(0, 0, 0, 0.6)";
    backdrop.style.pointerEvents = "auto";
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) {
        dialog.remove();
        diagnosticsDialog = null;
      }
    });
    dialog.appendChild(backdrop);

    const panel = document.createElement("div");
    panel.style.position = "absolute";
    // Center relative to the Settings flyout (not the whole client window)
    // Fallback to viewport center if the flyout can't be found.
    let centerX = window.innerWidth / 2;
    let centerY = window.innerHeight / 2;
    try {
      const settingsFlyout = document.getElementById(FLYOUT_ID);
      if (settingsFlyout) {
        const r = settingsFlyout.getBoundingClientRect();
        centerX = r.left + r.width / 2;
        centerY = r.top + r.height / 2;
      }
    } catch (e) {}

    panel.style.left = `${centerX}px`;
    panel.style.top = `${centerY}px`;
    panel.style.transform = "translate(-50%, -50%)";
    panel.style.width = "520px";
    panel.style.maxWidth = "92vw";
    panel.style.background = "#0b0f14";
    panel.style.border = "1px solid #463714";
    panel.style.boxShadow = "0 10px 30px rgba(0,0,0,0.6)";
    panel.style.padding = "14px";
    panel.style.pointerEvents = "auto";
    panel.style.position = "absolute";

    const title = document.createElement("div");
    title.textContent = "Troubleshooting";
    title.style.color = "#cdbe91";
    title.style.fontFamily = "'Beaufort for LOL', serif";
    title.style.fontSize = "16px";
    title.style.marginBottom = "10px";
    panel.appendChild(title);

    // Top-right close button
    const closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.setAttribute("aria-label", "Close");
    closeBtn.textContent = "×";
    closeBtn.style.position = "absolute";
    closeBtn.style.top = "6px";
    closeBtn.style.right = "8px";
    closeBtn.style.width = "26px";
    closeBtn.style.height = "26px";
    closeBtn.style.lineHeight = "24px";
    closeBtn.style.padding = "0";
    closeBtn.style.border = "none";
    closeBtn.style.background = "#0b0f14";
    closeBtn.style.color = "#cdbe91";
    closeBtn.style.cursor = "pointer";
    closeBtn.style.borderRadius = "4px";
    closeBtn.style.fontFamily = "'Beaufort for LOL', serif";
    closeBtn.style.fontSize = "18px";
    closeBtn.addEventListener("click", () => {
      dialog.remove();
      diagnosticsDialog = null;
    });
    panel.appendChild(closeBtn);

    const body = document.createElement("div");
    body.id = "rose-diagnostics-body";
    body.style.color = "#cdbe91";
    body.style.fontFamily = "'Beaufort for LOL', serif";
    body.style.fontSize = "12px";
    body.style.whiteSpace = "normal";
    body.style.border = "1px solid #010a13";
    body.style.background = "#070a0e";
    body.style.padding = "10px";
    body.style.maxHeight = "220px";
    body.style.overflow = "auto";
    body.style.lineHeight = "1.35";
    body.textContent = "Loading…";
    panel.appendChild(body);

    const foot = document.createElement("div");
    foot.id = "rose-diagnostics-foot";
    foot.style.marginTop = "8px";
    foot.style.color = "#7e6f4e";
    foot.style.fontFamily = "'Beaufort for LOL', serif";
    foot.style.fontSize = "11px";
    panel.appendChild(foot);

    backdrop.appendChild(panel);
    diagnosticsDialog = dialog;

    // After layout, clamp the panel inside the viewport (avoids off-screen when flyout is near an edge).
    try {
      requestAnimationFrame(() => {
        try {
          const pr = panel.getBoundingClientRect();
          const margin = 12;
          let dx = 0;
          let dy = 0;
          if (pr.left < margin) dx = margin - pr.left;
          if (pr.right > window.innerWidth - margin) dx = (window.innerWidth - margin) - pr.right;
          if (pr.top < margin) dy = margin - pr.top;
          if (pr.bottom > window.innerHeight - margin) dy = (window.innerHeight - margin) - pr.bottom;
          if (dx || dy) {
            const curLeft = parseFloat(panel.style.left) || centerX;
            const curTop = parseFloat(panel.style.top) || centerY;
            panel.style.left = `${curLeft + dx}px`;
            panel.style.top = `${curTop + dy}px`;
          }
        } catch (e) {}
      });
    } catch (e) {}

    requestDiagnostics();
    renderDiagnosticsDialog();
  }

  function renderDiagnosticsDialog() {
    if (!diagnosticsDialog) return;
    const body = document.getElementById("rose-diagnostics-body");
    const foot = document.getElementById("rose-diagnostics-foot");
    if (!body || !foot) return;

    const errors = Array.isArray(diagnosticsState.errors) ? diagnosticsState.errors : [];
    if (errors.length === 0) {
      body.innerHTML = `
        <div style="opacity:0.85; margin-bottom:8px;">No recent errors.</div>
        <div style="opacity:0.75;">If something feels off, open the logs folder and share the latest log in a discord ticket.</div>
      `.trim();
    } else {
      const clamp = (n, min, max) => Math.max(min, Math.min(max, n));
      const fmtS = (n, digits = 2) => (typeof n === "number" && Number.isFinite(n) ? `${n.toFixed(digits)} s` : "");
      const curThreshold = typeof currentSettings?.threshold === "number" ? currentSettings.threshold : null;
      const curMonitorTimeout =
        typeof currentSettings?.monitorAutoResumeTimeout === "number"
          ? currentSettings.monitorAutoResumeTimeout
          : null;

      const escapeHtml = (value) =>
        String(value ?? "")
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;")
          .replace(/'/g, "&#39;");

      const describe = (e) => {
        const raw = String(e?.text || "").trim();
        const code = String(e?.code || "").trim();

        const isInjectionThreshold =
          code === "BASE_SKIN_FORCE_SLOW" ||
          code === "BASE_SKIN_VERIFY_FAILED" ||
          /Injection\s*Threshold/i.test(raw);
        const isMonitorTimeout =
          code === "AUTO_RESUME_TRIGGERED" ||
          code === "MONITOR_AUTO_RESUME_TIMEOUT" ||
          /Auto-Resume Timeout/i.test(raw) ||
          /Monitor Auto-Resume Timeout/i.test(raw);

        if (isInjectionThreshold) {
          const thresholdAtMax =
            typeof curThreshold === "number" && Number.isFinite(curThreshold) && curThreshold >= (2.0 - 1e-6);
          return {
            title:
              code === "BASE_SKIN_VERIFY_FAILED"
                ? "Base skin verification failed (selected skin may not apply)"
                : "Base skin forcing took too long (skin may not appear)",
            details: [
              code === "BASE_SKIN_VERIFY_FAILED"
                ? `What it means: the client didn't apply/reflect the base skin change in time.`
                : `What it means: forcing the base skin took too long, so the selected skin may not show.`,
              thresholdAtMax
                ? `Fix: you're already at the maximum Injection Threshold. This usually means the injection is extremely slow. Try lighter mods, close heavy apps, move League/mods to an SSD, and consider adding antivirus exclusions for the League and Rose folders. Then retry.`
                : `Fix: increase "Injection Threshold (seconds)" and click Save. If the warning is still there, increase it again and Save again. Once the warning is gone, retry your skin selection.`,
            ],
          };
        }

        if (isMonitorTimeout) {
          const timeoutAtMax =
            typeof curMonitorTimeout === "number" &&
            Number.isFinite(curMonitorTimeout) &&
            curMonitorTimeout >= (180 - 1e-6);
          return {
            title: "Injection exceeded the timeout (process was stopped)",
            details: [
              `What it means: injection took longer than the allowed time, so ROSE stopped the process.`,
              timeoutAtMax
                ? `Fix: you're already at the maximum Monitor Auto-Resume Timeout. This usually means the injection is extremely slow. Try lighter mods, close heavy apps, move League/mods to an SSD, and consider adding antivirus exclusions for the League and Rose folders. Then retry.`
                : `Fix: increase "Monitor Auto-Resume Timeout (seconds)" and click Save. If the warning is still there, increase it again and Save again. Once the warning is gone, try again.`,
            ],
          };
        }

        // Fallback: show raw error text as-is.
        return {
          title: raw || "(unknown error)",
          details: [],
        };
      };

      const headerHtml = `
        <div style="display:flex; flex-direction:column; gap:4px; margin-bottom:10px;">
          <div style="font-weight:700;">Errors (most recent first)</div>
          <div style="opacity:0.75;">Tip: after changing a setting, click <span style="font-weight:700;">Save</span>, then retry.</div>
        </div>
      `.trim();

      const itemsHtml = errors
        .map((e, idx) => {
          const ts = String(e?.ts || "").trim();
          const desc = describe(e);
          const title = escapeHtml(desc.title);
          const tsHtml = ts ? `<span style="opacity:0.75;">${escapeHtml(ts)}</span>` : "";

          const detailsHtml = (desc.details || [])
            .map((d) => `<li style="margin:2px 0;">${escapeHtml(d)}</li>`)
            .join("");

          return `
            <div style="border:1px solid rgba(70,55,20,0.55); background: rgba(1,10,19,0.35); padding:8px; margin-bottom:8px;">
              <div style="display:flex; gap:8px; align-items:baseline; margin-bottom:6px;">
                <span style="font-weight:800; color:#c89b3c;">${idx + 1}.</span>
                ${tsHtml}
                <span style="font-weight:700;">${title}</span>
              </div>
              ${
                detailsHtml
                  ? `<ul style="margin:0; padding-left:18px;">${detailsHtml}</ul>`
                  : `<div style="opacity:0.8;">${escapeHtml(String(e?.text || "").trim() || "No additional details.")}</div>`
              }
            </div>
          `.trim();
        })
        .join("");

      body.innerHTML = `${headerHtml}${itemsHtml}`;
    }
  }

  function openPenguLoaderUI() {
    sendToBridge({
      type: "open-pengu-loader-ui",
    });
    log("info", "Open Pengu Loader UI requested");
  }

  function closeSettingsPanel() {
    if (!settingsPanel) return;

    // Disable selected nav item
    const navItem = document.querySelector(".menu_item_Golden");
    if (navItem) {
      navItem.removeAttribute("active")
    }

    // Restore last active item
    const lastActiveNavItem = document.querySelector(".main-nav-bar > * > lol-uikit-navigation-item[roseLastActive]");
    if (lastActiveNavItem) {
      lastActiveNavItem.removeAttribute("roseLastActive")
      lastActiveNavItem.setAttribute("active", true);
    }

    // Cancel any pending reposition timer to avoid a "one-frame" flicker after closing.
    try {
      if (_flyoutRepositionTimer) {
        clearTimeout(_flyoutRepositionTimer);
        _flyoutRepositionTimer = null;
      }
    } catch (e) {}

    // If troubleshooting dialog is open, close it too (it is a separate fixed overlay).
    try {
      const diag = document.getElementById("rose-diagnostics-dialog");
      if (diag) diag.remove();
      diagnosticsDialog = null;
    } catch (e) {}

    const cleanup = () => {
      try {
        if (settingsPanel) settingsPanel.remove();
      } catch (e) {}
      settingsPanel = null;
    };

    // Prefer the built-in flyout animation when available.
    let flyout = null;
    try {
      flyout = document.getElementById(FLYOUT_ID);
    } catch (e) {
      flyout = null;
    }

    if (flyout) {
      // Disable interactions immediately while closing.
      try {
        flyout.style.pointerEvents = "none";
      } catch (e) {}

      // Smooth close (avoid scale/pop + avoid one-frame re-appearance).
      try {
        const baseTransform = flyout.style.transform || "translateX(-50%)";
        flyout.style.willChange = "opacity, transform";
        flyout.style.transition =
          "opacity 180ms cubic-bezier(0.22, 1, 0.36, 1), transform 180ms cubic-bezier(0.22, 1, 0.36, 1)";

        // Apply end-state on next frame so the transition reliably runs.
        requestAnimationFrame(() => {
          try {
            flyout.style.opacity = "0";
            flyout.style.transform = `${baseTransform} translateY(-6px)`;
          } catch (e) {}
        });

        // Cleanup after the transition.
        setTimeout(cleanup, 220);
        return;
      } catch (e) {
        // If something goes wrong, fall back to immediate cleanup.
        cleanup();
        return;
      }
    }

    cleanup();
  }

  // Listen for open settings event from ROSE-UI
  window.addEventListener("rose-open-settings", (e) => {
    const navItem =
      e.detail?.navItem ||
      document.querySelector(
        "lol-uikit-navigation-item.menu_item_Golden.Rose"
      );
    if (navItem) {
      // Toggle: if panel is already open, close it
      if (settingsPanel && document.getElementById(PANEL_ID)) {
        closeSettingsPanel();
      } else {
        createSettingsFlyout(navItem);
      }
    } else {
      log(
        "warn",
        "Could not find Golden Rose nav item to position settings panel"
      );
    }
  });

  // Inject CSS
  function injectCSS() {
    // Remove existing CSS if it exists (to update with correct port)
    const existingStyle = document.getElementById("rose-settings-panel-css");
    if (existingStyle) {
      existingStyle.remove();
    }

    const style = document.createElement("style");
    style.id = "rose-settings-panel-css";
    style.textContent = getCSSRules();
    document.head.appendChild(style);
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
          log("error", `Init failed: Maximum retry count (${MAX_RETRIES}) reached. Document still not ready.`);
          _initializing = false;
          _retryCount = 0; // Reset for next attempt
          return;
        }
        _retryCount++;
        // Still not ready, schedule another retry
        requestAnimationFrame(() => {
          init().catch(err => {
            log("error", "Init failed:", err);
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
          log("error", `Init failed: Maximum retry count (${MAX_RETRIES}) reached. Document still not ready.`);
          _initializing = false;
          _retryCount = 0; // Reset for next attempt
          return;
        }
        _retryCount++;
        // Use synchronous wrapper to prevent multiple concurrent schedules
        requestAnimationFrame(() => {
          init().catch(err => {
            log("error", "Init failed:", err);
            _initializing = false;
          });
        });
        return;
      }
    }
    try {
      // Load bridge port before initializing
      await loadBridgePort();

      // Inject CSS after port is loaded (so it has the correct port number)
      injectCSS();
      setupBridgeSocket();
      log("info", "Settings panel plugin initialized");
      _initialized = true;
      _retryCount = 0; // Reset retry counter on success
    } catch (err) {
      log("error", "Init failed:", err);
      throw err; // Re-throw to propagate error to .catch() handlers
    } finally {
      _initializing = false;
    }
  }

  if (typeof document === "undefined") {
    log("warn", "document unavailable; aborting");
    return;
  }

  if (document.readyState === "loading") {
    document.addEventListener(
      "DOMContentLoaded",
      () => {
        init().catch((err) => {
          log("error", "Init failed:", err);
        });
      },
      { once: true }
    );
  } else {
    init().catch((err) => {
      log("error", "Init failed:", err);
    });
  }
})();
