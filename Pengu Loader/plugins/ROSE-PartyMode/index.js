/**
 * @name Rose-PartyMode
 * @author Rose Team
 * @description Party Mode - See your friends' skins in game via P2P
 * @link https://github.com/Alban1911/Rose
 */
(function initPartyMode() {
  const LOG_PREFIX = "[Rose-PartyMode]";
  let BRIDGE_PORT = 50000;
  let BRIDGE_URL = `ws://127.0.0.1:${BRIDGE_PORT}`;
  const BRIDGE_PORT_STORAGE_KEY = "rose_bridge_port";
  const DISCOVERY_START_PORT = 50000;
  const DISCOVERY_END_PORT = 50010;

  const PANEL_ID = "rose-party-panel";
  const BUTTON_ID = "rose-party-button";
  const LOBBY_BUTTON_ID = "rose-party-lobby-button";

  let bridgeSocket = null;
  let bridgeReady = false;
  let bridgeQueue = [];
  let partyPanel = null;
  let lobbyButton = null;
  let isVisible = false;
  let currentUIMode = null; // 'lobby' or 'champselect'

  // Party state
  let partyState = {
    enabled: false,
    my_token: null,
    my_summoner_id: null,
    my_summoner_name: "Unknown",
    peers: [],
  };

  /**
   * Escape HTML special characters to prevent XSS
   */
  function escapeHtml(str) {
    if (typeof str !== "string") return str;
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // Load bridge port with file-based discovery and localStorage caching
  async function loadBridgePort() {
    try {
      const cachedPort = localStorage.getItem(BRIDGE_PORT_STORAGE_KEY);
      if (cachedPort) {
        const port = parseInt(cachedPort, 10);
        if (!isNaN(port) && port > 0) {
          try {
            const response = await fetch(
              `http://127.0.0.1:${port}/bridge-port`,
              { signal: AbortSignal.timeout(50) }
            );
            if (response.ok) {
              const portText = await response.text();
              const fetchedPort = parseInt(portText.trim(), 10);
              if (!isNaN(fetchedPort) && fetchedPort > 0) {
                BRIDGE_PORT = fetchedPort;
                BRIDGE_URL = `ws://127.0.0.1:${BRIDGE_PORT}`;
                console.log(
                  `${LOG_PREFIX} Loaded bridge port from cache: ${BRIDGE_PORT}`
                );
                return true;
              }
            }
          } catch (e) {
            localStorage.removeItem(BRIDGE_PORT_STORAGE_KEY);
          }
        }
      }

      // Try default port 50000
      try {
        const response = await fetch(`http://127.0.0.1:50000/bridge-port`, {
          signal: AbortSignal.timeout(50),
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
        // Continue to discovery
      }

      // Parallel port discovery
      const portPromises = [];
      for (let port = DISCOVERY_START_PORT; port <= DISCOVERY_END_PORT; port++) {
        portPromises.push(
          fetch(`http://127.0.0.1:${port}/bridge-port`, {
            signal: AbortSignal.timeout(100),
          })
            .then((response) => {
              if (response.ok) {
                return response.text().then((portText) => {
                  const fetchedPort = parseInt(portText.trim(), 10);
                  if (!isNaN(fetchedPort) && fetchedPort > 0) {
                    return { port: fetchedPort };
                  }
                  return null;
                });
              }
              return null;
            })
            .catch(() => null)
        );
      }

      const results = await Promise.allSettled(portPromises);
      for (const result of results) {
        if (result.status === "fulfilled" && result.value) {
          BRIDGE_PORT = result.value.port;
          BRIDGE_URL = `ws://127.0.0.1:${BRIDGE_PORT}`;
          localStorage.setItem(BRIDGE_PORT_STORAGE_KEY, String(BRIDGE_PORT));
          console.log(`${LOG_PREFIX} Loaded bridge port: ${BRIDGE_PORT}`);
          return true;
        }
      }

      console.warn(
        `${LOG_PREFIX} Failed to load bridge port, using default (50000)`
      );
      return false;
    } catch (e) {
      console.warn(`${LOG_PREFIX} Error loading bridge port:`, e);
      return false;
    }
  }

  function getCSSRules() {
    return `
    @font-face {
      font-family: "Beaufort for LOL";
      src: url("http://127.0.0.1:${BRIDGE_PORT}/asset/BeaufortforLOL-Regular.ttf") format("truetype");
      font-weight: normal;
      font-style: normal;
      font-display: swap;
    }

    /* Party Button */
    /* Party Panel */
    /* ===== Panel: Riot dialog-frame style ===== */
    #${PANEL_ID} {
      position: fixed;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      width: 380px;
      background-color: #010a13;
      border: 2px solid #463714;
      box-shadow: 0 0 0 1px rgba(1,10,19,.8), 0 8px 30px rgba(0,0,0,.7), inset 0 1px 0 rgba(255,255,255,.03);
      z-index: 9998;
      display: none;
      flex-direction: column;
      cursor: default;
      -webkit-font-smoothing: antialiased;
      font-kerning: normal;
    }

    #${PANEL_ID}.visible {
      display: flex;
    }

    /* Title bar — matches .lol-friend-finder-modal .title */
    .party-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 15px 18px 10px;
    }

    .party-header h3 {
      margin: 0;
      color: #f0e6d2;
      font-family: var(--font-display), "Beaufort for LOL", Arial, sans-serif;
      font-size: 18px;
      font-weight: 700;
      letter-spacing: .05em;
      line-height: 22px;
      text-transform: uppercase;
    }

    .party-status {
      font-family: var(--font-body), Arial, sans-serif;
      font-size: 12px;
      font-weight: 400;
      letter-spacing: .025em;
    }

    .party-status.offline { color: #5b5a56; }
    .party-status.online  { color: #0acbe6; }

    /* Body — matches .lol-friend-finder-modal .modal-body */
    .party-content {
      display: flex;
      flex-direction: column;
      flex: 1;
      padding: 0 18px;
      overflow: hidden;
    }

    /* Description text */
    .party-description {
      color: #a09b8c;
      font-family: var(--font-body), Arial, sans-serif;
      font-size: 12px;
      line-height: 16px;
      margin-bottom: 15px;
    }

    /* Section headers — matches .lol-friend-finder-modal .header */
    .party-section {
      margin-bottom: 15px;
    }

    .party-section:last-child {
      margin-bottom: 0;
    }

    .party-section-title {
      color: #a09b8c;
      font-family: var(--font-display), "Beaufort for LOL", Arial, sans-serif;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: .05em;
      text-transform: uppercase;
      margin-bottom: 10px;
    }

    /* Inputs — matches lol-uikit-flat-input */
    .token-container,
    .add-peer-container {
      display: flex;
      gap: 8px;
      align-items: stretch;
    }

    .token-input,
    .add-peer-input {
      flex: 1;
      background: rgba(0,0,0,.7);
      border: thin solid #3c3c41;
      padding: 7px 10px;
      color: #f0e6d2;
      font-family: var(--font-body), Arial, sans-serif;
      font-size: 12px;
      line-height: 18px;
      outline: none;
    }

    .token-input {
      font-family: monospace;
      font-size: 11px;
      color: #a09b8c;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .token-input:focus,
    .add-peer-input:focus {
      border-color: #c89b3c;
    }

    .add-peer-input::placeholder {
      color: #5b5a56;
    }

    /* Buttons — matches lol-uikit-flat-button-secondary */
    .copy-btn, .add-btn {
      background: transparent;
      border: thin solid #5b5a56;
      padding: 7px 16px;
      color: #cdbe91;
      cursor: pointer;
      font-family: var(--font-body), Arial, sans-serif;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: .075em;
      text-transform: uppercase;
      white-space: nowrap;
      transition: color .3s, border-color .3s;
    }

    .copy-btn:hover, .add-btn:hover {
      border-color: #c8aa6e;
      color: #f0e6d2;
    }

    .copy-btn:active, .add-btn:active {
      color: #463714;
      border-color: #463714;
    }

    .copy-btn.copied {
      border-color: #0acbe6;
      color: #0acbe6;
    }

    .add-btn:disabled, .add-peer-input:disabled {
      opacity: 0.5;
      cursor: default;
      pointer-events: none;
    }

    /* Toggle button — matches lol-uikit-flat-button (primary) */
    .party-toggle-btn {
      width: 100%;
      padding: 10px;
      cursor: pointer;
      font-family: var(--font-body), Arial, sans-serif;
      font-size: 14px;
      font-weight: 700;
      letter-spacing: .1em;
      text-transform: uppercase;
      border: thin solid #c8aa6e;
      transition: background .3s, color .3s, border-color .3s;
    }

    .party-toggle-btn.enable {
      background: linear-gradient(to bottom, #1e2328, #1e2328);
      border-color: #c8aa6e;
      color: #cdbe91;
    }

    .party-toggle-btn.enable:hover {
      background: linear-gradient(to bottom, #1e2328, #1e2328);
      border-color: #c8aa6e;
      color: #f0e6d2;
    }

    .party-toggle-btn.disable {
      background: transparent;
      border-color: #5b5a56;
      color: #a09b8c;
    }

    .party-toggle-btn.disable:hover {
      border-color: #ff4646;
      color: #ff4646;
    }

    .party-toggle-btn:disabled {
      opacity: 0.5;
      cursor: default;
    }

    /* Peers list — matches requested-players / recent-summoners */
    .peers-list {
      max-height: 200px;
      overflow-y: auto;
      scrollbar-width: thin;
      scrollbar-color: #463714 transparent;
    }

    .peers-list::-webkit-scrollbar { width: 6px; }
    .peers-list::-webkit-scrollbar-track { background: transparent; }
    .peers-list::-webkit-scrollbar-thumb { background: #463714; border-radius: 3px; }

    .peer-item {
      display: flex;
      align-items: center;
      padding: 6px 0;
      border-bottom: thin solid rgba(60,60,65,.5);
    }

    .peer-item:last-child {
      border-bottom: none;
    }

    .peer-info {
      flex: 1;
      min-width: 0;
    }

    .peer-name {
      color: #a09b8c;
      font-family: var(--font-body), Arial, sans-serif;
      font-size: 12px;
      line-height: 16px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .peer-item:hover .peer-name {
      color: #f0e6d2;
    }

    .peer-status {
      font-family: var(--font-body), Arial, sans-serif;
      font-size: 10px;
      color: #5b5a56;
      line-height: 14px;
    }

    .peer-status.in-lobby { color: #0acbe6; }

    .peer-skin {
      font-size: 10px;
      color: #c89b3c;
      line-height: 14px;
    }

    .peer-remove {
      background: none;
      border: none;
      color: #5b5a56;
      cursor: pointer;
      padding: 4px 8px;
      font-size: 14px;
      transition: color .2s;
    }

    .peer-remove:hover { color: #ff4646; }

    .no-peers {
      color: #5b5a56;
      font-family: var(--font-body), Arial, sans-serif;
      font-size: 12px;
      text-align: center;
      padding: 20px;
    }

    /* Close button — matches lol-uikit-dialog-frame close button */
    .party-close-btn {
      position: absolute;
      top: -14px;
      right: -14px;
      width: 28px;
      height: 28px;
      border-radius: 50%;
      background: #1e2328;
      border: 2px solid #463714;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: border-color .2s;
      z-index: 1;
      padding: 0;
    }

    .party-close-btn:hover {
      border-color: #c8aa6e;
    }

    .party-close-btn:active {
      border-color: #785a28;
    }

    .party-close-btn::before,
    .party-close-btn::after {
      content: "";
      position: absolute;
      width: 12px;
      height: 2px;
      background: #a09b8c;
      transition: background .2s;
    }

    .party-close-btn::before { transform: rotate(45deg); }
    .party-close-btn::after  { transform: rotate(-45deg); }

    .party-close-btn:hover::before,
    .party-close-btn:hover::after {
      background: #f0e6d2;
    }

    /* Loading state */
    .loading {
      opacity: 0.6;
      pointer-events: none;
    }

    .spinner {
      display: inline-block;
      width: 12px;
      height: 12px;
      border: 2px solid rgba(200, 170, 110, 0.3);
      border-top-color: #c8aa6e;
      border-radius: 50%;
      animation: rose-party-spin 0.8s linear infinite;
    }

    @keyframes rose-party-spin {
      to { transform: rotate(360deg); }
    }

    /* Messages */
    .error-msg {
      color: #ff4646;
      font-size: 11px;
      margin-top: 8px;
    }

    .success-msg {
      color: #0acbe6;
      font-size: 11px;
      margin-top: 8px;
    }

    /* Lobby action bar button - matches native social bar buttons */
    #${LOBBY_BUTTON_ID} {
      position: relative;
      cursor: pointer;
    }

    #${LOBBY_BUTTON_ID} .party-mode-icon {
      background-color: #c8aa6e;
      cursor: pointer;
      display: block;
      height: inherit;
      width: inherit;
      -webkit-mask: url("data:image/svg+xml,%3Csvg viewBox='0 0 24 24' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 3c1.66 0 3 1.34 3 3s-1.34 3-3 3-3-1.34-3-3 1.34-3 3-3zm0 14.2c-2.5 0-4.71-1.28-6-3.22.03-1.99 4-3.08 6-3.08 1.99 0 5.97 1.09 6 3.08-1.29 1.94-3.5 3.22-6 3.22z'/%3E%3C/svg%3E") no-repeat center;
      -webkit-mask-size: 18px;
    }

    #${LOBBY_BUTTON_ID}:hover .party-mode-icon {
      background-color: #f0e6d2;
    }

    #${LOBBY_BUTTON_ID}:active .party-mode-icon {
      background-color: #463714;
    }

    #${LOBBY_BUTTON_ID}.active .party-mode-icon {
      background-color: #0acbe6;
    }

    #${LOBBY_BUTTON_ID}.connected .party-mode-icon {
      background-color: #4ade80;
    }


    `;
  }

  function injectStyles() {
    const styleId = "rose-party-mode-styles";
    if (document.getElementById(styleId)) return;

    const style = document.createElement("style");
    style.id = styleId;
    style.textContent = getCSSRules();
    document.head.appendChild(style);
  }

  // Attach a native Riot tooltip to an element
  function attachTooltip(el, text) {
    let wrapper = null;
    el.addEventListener("mouseenter", () => {
      // Wrapper div to control positioning (native tooltip may override its own styles)
      wrapper = document.createElement("div");
      wrapper.style.cssText = "position:fixed;pointer-events:none;z-index:10000;visibility:hidden";
      const tip = document.createElement("lol-uikit-tooltip");
      tip.setAttribute("data-tooltip-position", "bottom");
      const content = document.createElement("lol-uikit-content-block");
      content.setAttribute("type", "tooltip-system");
      const p = document.createElement("p");
      p.textContent = text;
      content.appendChild(p);
      tip.appendChild(content);
      wrapper.appendChild(tip);
      document.body.appendChild(wrapper);
      // Wait for render then position the wrapper
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          if (!wrapper || !wrapper.isConnected) return;
          const btnRect = el.getBoundingClientRect();
          const wrapRect = wrapper.getBoundingClientRect();
          const centerX = btnRect.left + btnRect.width / 2;
          wrapper.style.left = `${centerX - wrapRect.width / 2}px`;
          wrapper.style.top = `${btnRect.bottom}px`;
          wrapper.style.visibility = "visible";
        });
      });
    });
    el.addEventListener("mouseleave", () => {
      if (wrapper) {
        wrapper.remove();
        wrapper = null;
      }
    });
  }

  // Create button in social actions bar
  function createLobbyButton() {
    const existing = document.getElementById(LOBBY_BUTTON_ID);
    if (existing) {
      lobbyButton = existing;
      updateLobbyButtonState();
      return;
    }

    // Find the social actions bar buttons container
    const buttonsContainer = document.querySelector(".lol-social-actions-bar .buttons");
    if (!buttonsContainer) {
      console.log(`${LOG_PREFIX} Social actions bar not found, retrying...`);
      return false;
    }

    // Find the friend-finder-button to insert before it
    const friendFinderBtn = buttonsContainer.querySelector(".friend-finder-button");
    const friendFinderParent = friendFinderBtn ? friendFinderBtn.closest(".action-bar-button") : null;

    const button = document.createElement("span");
    button.id = LOBBY_BUTTON_ID;
    button.className = "action-bar-button";
    button.innerHTML = `
      <span class="party-mode-icon"></span>
    `;

    button.addEventListener("click", (e) => {
      e.stopPropagation();
      togglePanel();
    });
    attachTooltip(button, "Party Mode");

    // Insert before the add friend button, or append to the end
    if (friendFinderParent) {
      buttonsContainer.insertBefore(button, friendFinderParent);
    } else {
      // Try to insert after the SOCIAL header
      const socialHeader = buttonsContainer.querySelector(".friend-header");
      if (socialHeader && socialHeader.nextSibling) {
        buttonsContainer.insertBefore(button, socialHeader.nextSibling);
      } else {
        buttonsContainer.appendChild(button);
      }
    }

    lobbyButton = button;
    updateLobbyButtonState();
    return true;
  }

  function updateLobbyButtonState() {
    if (!lobbyButton) return;

    const connectedPeers = (partyState.peers || []).filter((p) => p.connected);
    if (partyState.enabled) {
      lobbyButton.classList.add("active");
    } else {
      lobbyButton.classList.remove("active");
    }
    if (partyState.enabled && connectedPeers.length > 0) {
      lobbyButton.classList.add("connected");
    } else {
      lobbyButton.classList.remove("connected");
    }
  }

  function createPartyPanel() {
    // Remove any existing panel (may be detached/stale)
    const existing = document.getElementById(PANEL_ID);
    if (existing) {
      if (existing.isConnected && partyPanel === existing) return; // Already good
      existing.remove();
    }

    // Find a persistent container to attach the panel to
    const container = document.querySelector(".lol-social-actions-bar") || document.body;

    const panel = document.createElement("div");
    panel.id = PANEL_ID;
    panel.innerHTML = `
      <div class="party-header">
        <h3>Party Mode</h3>
        <span class="party-status offline">Offline</span>
      </div>
      <div class="party-content">
        <div class="party-description">Share your skins with friends in the same lobby. Enable party mode and exchange tokens to connect.</div>

        <div class="party-section" id="party-toggle-section">
          <button class="party-toggle-btn enable" id="party-toggle-btn">
            Enable Party Mode
          </button>
        </div>

        <div class="party-section" id="party-token-section" style="display: none;">
          <div class="party-section-title">Your Party Token</div>
          <div class="token-container">
            <input type="text" class="token-input" id="party-token-display" readonly placeholder="Generating...">
            <button class="copy-btn" id="copy-token-btn">Copy</button>
          </div>
        </div>

        <div class="party-section" id="party-add-section" style="display: none;">
          <div class="party-section-title">Add Friend</div>
          <div class="add-peer-container">
            <input type="text" class="add-peer-input" id="add-peer-input" placeholder="Paste friend's token here...">
            <button class="add-btn" id="add-peer-btn">Add</button>
          </div>
          <div id="add-peer-message"></div>
        </div>

        <div class="party-section" id="party-peers-section" style="display: none;">
          <div class="party-section-title">Connected Friends (<span id="peer-count">0</span>)</div>
          <div class="peers-list" id="peers-list">
            <div class="no-peers">No friends connected yet</div>
          </div>
        </div>
      </div>
      <button class="party-close-btn" id="party-close-btn"></button>
    `;

    try {
      container.appendChild(panel);
      partyPanel = panel;
      // Use querySelector on panel directly instead of document to avoid ID conflicts
      panel.querySelector("#party-toggle-btn").addEventListener("click", handleToggleParty);
      panel.querySelector("#copy-token-btn").addEventListener("click", handleCopyToken);
      panel.querySelector("#add-peer-btn").addEventListener("click", handleAddPeer);
      panel.querySelector("#add-peer-input").addEventListener("keypress", (e) => {
        if (e.key === "Enter") handleAddPeer();
      });
      panel.querySelector("#party-close-btn").addEventListener("click", () => {
        isVisible = false;
        partyPanel.classList.remove("visible");
      });
    } catch (e) {
      console.error(`${LOG_PREFIX} Failed to create panel:`, e);
      partyPanel = null;
    }
  }

  function togglePanel() {
    // Recreate panel if it was removed from DOM
    if (!partyPanel || !partyPanel.isConnected) {
      partyPanel = null;
      isVisible = false;
      createPartyPanel();
    }
    if (!partyPanel) return;
    isVisible = !isVisible;
    partyPanel.classList.toggle("visible", isVisible);
    updatePanelState();
  }

  function updateButtonState() {
    updateLobbyButtonState();
  }

  function updatePanelState() {
    if (!partyPanel) return;

    const statusEl = partyPanel.querySelector(".party-status");
    const toggleBtn = document.getElementById("party-toggle-btn");
    const tokenSection = document.getElementById("party-token-section");
    const addSection = document.getElementById("party-add-section");
    const peersSection = document.getElementById("party-peers-section");
    const tokenDisplay = document.getElementById("party-token-display");
    const peerCountEl = document.getElementById("peer-count");
    const peersList = document.getElementById("peers-list");

    if (partyState.enabled) {
      statusEl.className = "party-status online";
      statusEl.textContent = "Online";

      toggleBtn.className = "party-toggle-btn disable";
      toggleBtn.textContent = "Disable Party Mode";

      tokenSection.style.display = "block";
      addSection.style.display = "block";
      peersSection.style.display = "block";

      if (partyState.my_token) {
        tokenDisplay.value = partyState.my_token;
      }

      // Update peers list (show all peers, including those still connecting)
      const allPeers = partyState.peers || [];
      const connectedPeers = allPeers.filter((p) => p.connected);
      peerCountEl.textContent = connectedPeers.length;

      if (allPeers.length === 0) {
        peersList.innerHTML = '<div class="no-peers">No friends connected yet</div>';
      } else {
        peersList.innerHTML = allPeers
          .map((peer) => {
            const cs = (peer.connection_state || "disconnected").toLowerCase();
            const isWaiting = cs === "connecting" || cs === "handshaking";
            const statusText = isWaiting
              ? "Waiting for your friend"
              : cs === "connected"
                ? (peer.in_lobby ? "In lobby" : "Connected")
                : cs === "handshaking"
                  ? "Handshaking"
                  : cs === "connecting"
                    ? "Connecting"
                    : "Disconnected";
            const displayName = isWaiting ? "Friend" : escapeHtml(peer.summoner_name);
            const lobbyStatus = peer.in_lobby ? "in-lobby" : "";
            const skinInfo = peer.skin_selection
              ? `Skin: ${peer.skin_selection.skin_id}`
              : "";

            return `
            <div class="peer-item" data-summoner-id="${peer.summoner_id}">
              <div class="peer-info">
                <span class="peer-name">${displayName}</span>
                ${isWaiting ? '<span class="peer-status waiting"><span class="spinner"></span> ' : `<span class="peer-status ${lobbyStatus}">`}
                ${escapeHtml(statusText)}</span>
                ${skinInfo ? `<span class="peer-skin">${skinInfo}</span>` : ""}
              </div>
              <button class="peer-remove" title="Remove" onclick="window.rosePartyRemovePeer(${peer.summoner_id})">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
                </svg>
              </button>
            </div>
          `;
          })
          .join("");
      }
    } else {
      statusEl.className = "party-status offline";
      statusEl.textContent = "Offline";

      toggleBtn.className = "party-toggle-btn enable";
      toggleBtn.textContent = "Enable Party Mode";

      tokenSection.style.display = "none";
      addSection.style.display = "none";
      peersSection.style.display = "none";
    }

    updateButtonState();
  }

  async function handleToggleParty() {
    const toggleBtn = document.getElementById("party-toggle-btn");

    if (partyState.enabled) {
      // Disable
      toggleBtn.disabled = true;
      toggleBtn.innerHTML = '<span class="spinner"></span> Disabling...';
      sendBridgeMessage({ type: "party-disable" });
    } else {
      // Enable
      toggleBtn.disabled = true;
      toggleBtn.innerHTML = '<span class="spinner"></span> Enabling...';
      sendBridgeMessage({ type: "party-enable" });
    }
  }

  function handleCopyToken() {
    const tokenDisplay = document.getElementById("party-token-display");
    const copyBtn = document.getElementById("copy-token-btn");

    if (!tokenDisplay.value) return;

    navigator.clipboard.writeText(tokenDisplay.value).then(() => {
      copyBtn.textContent = "Copied!";
      copyBtn.classList.add("copied");
      setTimeout(() => {
        copyBtn.textContent = "Copy";
        copyBtn.classList.remove("copied");
      }, 2000);
    });
  }

  function handleAddPeer() {
    const input = document.getElementById("add-peer-input");
    const addBtn = document.getElementById("add-peer-btn");
    const messageEl = document.getElementById("add-peer-message");
    // Strip and remove all whitespace (spaces, newlines, tabs) so pasted tokens work
    const token = input.value.replace(/\s+/g, "").trim();

    if (!token) {
      messageEl.innerHTML =
        '<div class="error-msg">Please enter a token</div>';
      return;
    }

    // Lock the entire panel during connection
    input.disabled = true;
    addBtn.disabled = true;
    addBtn.innerHTML = '<span class="spinner"></span>';
    const toggleBtn = document.getElementById("party-toggle-btn");
    if (toggleBtn) toggleBtn.disabled = true;
    const closeBtn = partyPanel ? partyPanel.querySelector("#party-close-btn") : null;
    if (closeBtn) closeBtn.style.display = "none";
    messageEl.innerHTML =
      '<div class="success-msg"><span class="spinner"></span> Connecting to your friend...</div>';
    sendBridgeMessage({ type: "party-add-peer", token: token });
    input.value = "";
  }

  // Global function for remove button onclick
  window.rosePartyRemovePeer = function (summonerId) {
    sendBridgeMessage({ type: "party-remove-peer", summoner_id: summonerId });
  };

  function handleBridgeMessage(data) {
    console.log(`${LOG_PREFIX} Received:`, data.type);

    switch (data.type) {
      case "party-state":
        partyState = {
          enabled: data.enabled || false,
          my_token: data.my_token || null,
          my_summoner_id: data.my_summoner_id || null,
          my_summoner_name: data.my_summoner_name || "Unknown",
          peers: data.peers || [],
        };
        updateButtonState();
        updatePanelState();
        break;

      case "party-enabled":
        const toggleBtn = document.getElementById("party-toggle-btn");
        toggleBtn.disabled = false;

        if (data.success) {
          partyState.enabled = true;
          partyState.my_token = data.token;
          console.log(`${LOG_PREFIX} Party mode enabled`);
        } else {
          const messageEl = document.getElementById("add-peer-message");
          if (messageEl) {
            messageEl.innerHTML = `<div class="error-msg">${escapeHtml(data.error || "Failed to enable")}</div>`;
          }
          console.error(`${LOG_PREFIX} Failed to enable:`, data.error);
        }
        updateButtonState();
        updatePanelState();
        break;

      case "party-disabled":
        const toggleBtnDisable = document.getElementById("party-toggle-btn");
        if (toggleBtnDisable) toggleBtnDisable.disabled = false;

        partyState.enabled = false;
        partyState.my_token = null;
        partyState.peers = [];
        console.log(`${LOG_PREFIX} Party mode disabled`);
        updateButtonState();
        updatePanelState();
        break;

      case "party-peer-added": {
        const addInput = document.getElementById("add-peer-input");
        const addBtn = document.getElementById("add-peer-btn");
        const addMessageEl = document.getElementById("add-peer-message");

        // Unlock the panel
        if (addInput) addInput.disabled = false;
        if (addBtn) {
          addBtn.disabled = false;
          addBtn.textContent = "Add";
        }
        const unlockToggleBtn = document.getElementById("party-toggle-btn");
        if (unlockToggleBtn) unlockToggleBtn.disabled = false;
        const unlockCloseBtn = partyPanel ? partyPanel.querySelector("#party-close-btn") : null;
        if (unlockCloseBtn) unlockCloseBtn.style.display = "";

        if (data.success) {
          if (addMessageEl) {
            addMessageEl.innerHTML =
              '<div class="success-msg">Friend connected!</div>';
            setTimeout(() => {
              addMessageEl.innerHTML = "";
            }, 3000);
          }
        } else {
          if (addMessageEl) {
            addMessageEl.innerHTML = `<div class="error-msg">${escapeHtml(data.error || "Failed to connect")}</div>`;
          }
        }
        // Request updated state
        sendBridgeMessage({ type: "party-get-state" });
        break;
      }

      case "party-peer-removed":
        // Request updated state
        sendBridgeMessage({ type: "party-get-state" });
        break;

      case "phase-change":
        // Pause the 500ms DOM monitor during in-game to avoid stealing
        // CPU from the League game process.  Resume in every other phase
        // so the party button reattaches if the client re-renders.
        if (data.phase === "InProgress") {
          stopGamePhaseMonitor();
        } else {
          startGamePhaseMonitor();
        }
        break;
    }
  }

  function connectBridge() {
    if (bridgeSocket && bridgeSocket.readyState === WebSocket.OPEN) {
      return;
    }

    console.log(`${LOG_PREFIX} Connecting to bridge at ${BRIDGE_URL}`);
    bridgeSocket = new WebSocket(BRIDGE_URL);

    bridgeSocket.onopen = () => {
      console.log(`${LOG_PREFIX} Bridge connected`);
      bridgeReady = true;

      // Flush queued messages
      while (bridgeQueue.length > 0) {
        const msg = bridgeQueue.shift();
        bridgeSocket.send(JSON.stringify(msg));
      }

      // Request current party state
      sendBridgeMessage({ type: "party-get-state" });
    };

    bridgeSocket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleBridgeMessage(data);
      } catch (e) {
        console.error(`${LOG_PREFIX} Error parsing message:`, e);
      }
    };

    bridgeSocket.onclose = () => {
      console.log(`${LOG_PREFIX} Bridge disconnected, reconnecting...`);
      bridgeReady = false;
      setTimeout(connectBridge, 1000);
    };

    bridgeSocket.onerror = (error) => {
      console.error(`${LOG_PREFIX} Bridge error:`, error);
    };
  }

  function sendBridgeMessage(msg) {
    if (bridgeReady && bridgeSocket && bridgeSocket.readyState === WebSocket.OPEN) {
      bridgeSocket.send(JSON.stringify(msg));
    } else {
      bridgeQueue.push(msg);
    }
  }

  // Check if we're in lobby (pre-game party lobby)
  function isInLobby() {
    return !!(
      document.querySelector(".v2-banner-component.local-player") ||
      document.querySelector(".lobby-player.local-player") ||
      document.querySelector("lol-regalia-parties-v2-element") ||
      document.querySelector(".parties-game-info-panel") ||
      document.querySelector(".lobby-members-container") ||
      document.querySelector(".ready-check-swap-button") ||
      document.querySelector(".lobby-header-custom-map-name")
    );
  }

  // Check if we're in champion select
  function isInChampSelect() {
    return !!(
      document.querySelector(".champion-grid") ||
      document.querySelector(".summoner-array") ||
      document.querySelector(".skin-selector-dropdown") ||
      document.querySelector(".champion-select-container")
    );
  }

  // Check if we should show party UI (lobby OR champ select)
  function shouldShowPartyUI() {
    return isInLobby() || isInChampSelect();
  }

  // Remove all party UI elements

  // Monitor for lobby/champ select.
  // Pauses during InProgress phase to avoid stealing CPU from the game.
  // See GitHub issue #22.
  let gamePhaseMonitorId = null;

  function startGamePhaseMonitor() {
    if (gamePhaseMonitorId) return;
    gamePhaseMonitorId = setInterval(() => {
      const inChampSelect = isInChampSelect();
      const inLobby = isInLobby();

      // Always keep the party button in the social actions bar
      // (it's always present, not just in lobby)
      if (!lobbyButton || !lobbyButton.isConnected) {
        lobbyButton = null;
        createLobbyButton();
      }

      // Ensure panel exists
      if (!partyPanel || !partyPanel.isConnected) {
        partyPanel = null;
        isVisible = false;
        createPartyPanel();
      }

      // Track UI mode changes
      if (inChampSelect && currentUIMode !== "champselect") {
        console.log(`${LOG_PREFIX} Entered champion select`);
        currentUIMode = "champselect";
      } else if (inLobby && currentUIMode !== "lobby") {
        console.log(`${LOG_PREFIX} Entered lobby`);
        currentUIMode = "lobby";
      } else if (!inChampSelect && !inLobby && currentUIMode !== "default") {
        currentUIMode = "default";
      }
    }, 500);
  }

  function stopGamePhaseMonitor() {
    if (!gamePhaseMonitorId) return;
    clearInterval(gamePhaseMonitorId);
    gamePhaseMonitorId = null;
  }

  // Initialize
  async function init() {
    console.log(`${LOG_PREFIX} Initializing...`);

    await loadBridgePort();
    injectStyles();
    connectBridge();

    // Always create social bar button and panel
    createLobbyButton();
    createPartyPanel();

    // Set initial UI mode
    if (isInChampSelect()) {
      currentUIMode = "champselect";
    } else if (isInLobby()) {
      currentUIMode = "lobby";
    } else {
      currentUIMode = "default";
    }

    startGamePhaseMonitor();

    console.log(`${LOG_PREFIX} Initialized`);
  }

  // Start when DOM is ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
