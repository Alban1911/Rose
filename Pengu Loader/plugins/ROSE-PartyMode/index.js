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
  let partyButton = null;
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
    #${BUTTON_ID} {
      position: fixed;
      bottom: 120px;
      right: 20px;
      width: 48px;
      height: 48px;
      border-radius: 50%;
      background: linear-gradient(180deg, #1e2328 0%, #0a0c0e 100%);
      border: 2px solid #463714;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 9999;
      transition: all 0.2s ease;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.5);
    }

    #${BUTTON_ID}:hover {
      border-color: #c89b3c;
      transform: scale(1.05);
    }

    #${BUTTON_ID}.active {
      border-color: #0acbe6;
      box-shadow: 0 0 12px rgba(10, 203, 230, 0.5);
    }

    #${BUTTON_ID} svg {
      width: 24px;
      height: 24px;
      fill: #a09b8c;
      transition: fill 0.2s ease;
    }

    #${BUTTON_ID}:hover svg,
    #${BUTTON_ID}.active svg {
      fill: #f0e6d2;
    }

    #${BUTTON_ID} .peer-count {
      position: absolute;
      top: -4px;
      right: -4px;
      min-width: 18px;
      height: 18px;
      background: #0acbe6;
      border-radius: 9px;
      font-size: 11px;
      font-weight: bold;
      color: #010a13;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 0 4px;
    }

    /* Party Panel */
    #${PANEL_ID} {
      position: fixed;
      bottom: 180px;
      right: 20px;
      width: 340px;
      background: linear-gradient(180deg, #1e2328 0%, #0a0c0e 100%);
      border: 1px solid #463714;
      border-radius: 4px;
      z-index: 9998;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.6);
      font-family: "Beaufort for LOL", Arial, sans-serif;
      display: none;
    }

    #${PANEL_ID}.visible {
      display: block;
    }

    .party-header {
      padding: 12px 16px;
      border-bottom: 1px solid #463714;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }

    .party-header h3 {
      margin: 0;
      color: #c8aa6e;
      font-size: 14px;
      font-weight: normal;
      letter-spacing: 1px;
      text-transform: uppercase;
    }

    .party-status {
      font-size: 11px;
      padding: 3px 8px;
      border-radius: 3px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    .party-status.offline {
      background: rgba(255, 70, 70, 0.2);
      color: #ff4646;
      border: 1px solid rgba(255, 70, 70, 0.3);
    }

    .party-status.online {
      background: rgba(10, 203, 230, 0.2);
      color: #0acbe6;
      border: 1px solid rgba(10, 203, 230, 0.3);
    }

    .party-content {
      padding: 16px;
    }

    .party-section {
      margin-bottom: 16px;
    }

    .party-section:last-child {
      margin-bottom: 0;
    }

    .party-section-title {
      color: #a09b8c;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 1px;
      margin-bottom: 8px;
    }

    /* Token display */
    .token-container {
      display: flex;
      gap: 8px;
    }

    .token-input {
      flex: 1;
      background: rgba(0, 0, 0, 0.3);
      border: 1px solid #3c3c41;
      border-radius: 3px;
      padding: 8px 10px;
      color: #a09b8c;
      font-family: monospace;
      font-size: 11px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .token-input:focus {
      outline: none;
      border-color: #c89b3c;
    }

    .copy-btn, .add-btn {
      background: linear-gradient(180deg, #1e2328 0%, #0a0c0e 100%);
      border: 1px solid #463714;
      border-radius: 3px;
      padding: 8px 12px;
      color: #c8aa6e;
      cursor: pointer;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      transition: all 0.2s ease;
    }

    .copy-btn:hover, .add-btn:hover {
      border-color: #c89b3c;
      background: linear-gradient(180deg, #2a2f35 0%, #12161a 100%);
    }

    .copy-btn.copied {
      border-color: #0acbe6;
      color: #0acbe6;
    }

    /* Enable/Disable button */
    .party-toggle-btn {
      width: 100%;
      padding: 12px;
      border-radius: 3px;
      cursor: pointer;
      font-size: 13px;
      font-weight: bold;
      text-transform: uppercase;
      letter-spacing: 1px;
      transition: all 0.2s ease;
      font-family: "Beaufort for LOL", Arial, sans-serif;
    }

    .party-toggle-btn.enable {
      background: linear-gradient(180deg, #0acbe6 0%, #005a82 100%);
      border: 1px solid #0acbe6;
      color: #010a13;
    }

    .party-toggle-btn.enable:hover {
      background: linear-gradient(180deg, #1ad5f0 0%, #007aa8 100%);
    }

    .party-toggle-btn.disable {
      background: linear-gradient(180deg, #3c3c41 0%, #1e2328 100%);
      border: 1px solid #5b5a56;
      color: #a09b8c;
    }

    .party-toggle-btn.disable:hover {
      border-color: #ff4646;
      color: #ff4646;
    }

    .party-toggle-btn:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }

    /* Peers list */
    .peers-list {
      max-height: 200px;
      overflow-y: auto;
      scrollbar-width: thin;
      scrollbar-color: #463714 rgba(0, 0, 0, 0.25);
    }

    .peers-list::-webkit-scrollbar {
      width: 6px;
    }

    .peers-list::-webkit-scrollbar-track {
      background: rgba(0, 0, 0, 0.25);
    }

    .peers-list::-webkit-scrollbar-thumb {
      background: #463714;
      border-radius: 3px;
    }

    .peer-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 10px 12px;
      background: rgba(0, 0, 0, 0.2);
      border-radius: 3px;
      margin-bottom: 6px;
    }

    .peer-item:last-child {
      margin-bottom: 0;
    }

    .peer-info {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }

    .peer-name {
      color: #f0e6d2;
      font-size: 13px;
    }

    .peer-status {
      font-size: 10px;
      color: #5b5a56;
    }

    .peer-status.in-lobby {
      color: #0acbe6;
    }

    .peer-skin {
      font-size: 10px;
      color: #c89b3c;
    }

    .peer-remove {
      background: none;
      border: none;
      color: #5b5a56;
      cursor: pointer;
      padding: 4px;
      transition: color 0.2s ease;
    }

    .peer-remove:hover {
      color: #ff4646;
    }

    .no-peers {
      color: #5b5a56;
      font-size: 12px;
      text-align: center;
      padding: 20px;
    }

    /* Add peer section */
    .add-peer-container {
      display: flex;
      gap: 8px;
    }

    .add-peer-input {
      flex: 1;
      background: rgba(0, 0, 0, 0.3);
      border: 1px solid #3c3c41;
      border-radius: 3px;
      padding: 8px 10px;
      color: #f0e6d2;
      font-family: monospace;
      font-size: 11px;
    }

    .add-peer-input:focus {
      outline: none;
      border-color: #c89b3c;
    }

    .add-peer-input::placeholder {
      color: #5b5a56;
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
      animation: spin 0.8s linear infinite;
    }

    @keyframes spin {
      to { transform: rotate(360deg); }
    }

    /* Error message */
    .error-msg {
      color: #ff4646;
      font-size: 11px;
      margin-top: 8px;
      padding: 8px;
      background: rgba(255, 70, 70, 0.1);
      border-radius: 3px;
    }

    /* Success message */
    .success-msg {
      color: #0acbe6;
      font-size: 11px;
      margin-top: 8px;
      padding: 8px;
      background: rgba(10, 203, 230, 0.1);
      border-radius: 3px;
    }

    /* Lobby action bar button */
    #${LOBBY_BUTTON_ID} {
      position: relative;
      cursor: pointer;
      width: 24px;
      height: 24px;
      display: flex;
      align-items: center;
      justify-content: center;
    }

    #${LOBBY_BUTTON_ID} .party-mode-icon {
      width: 20px;
      height: 20px;
      background-image: url('data:image/svg+xml,<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path fill="%23a09b8c" d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 3c1.66 0 3 1.34 3 3s-1.34 3-3 3-3-1.34-3-3 1.34-3 3-3zm0 14.2c-2.5 0-4.71-1.28-6-3.22.03-1.99 4-3.08 6-3.08 1.99 0 5.97 1.09 6 3.08-1.29 1.94-3.5 3.22-6 3.22z"/></svg>');
      background-size: contain;
      background-repeat: no-repeat;
      background-position: center;
      transition: filter 0.2s ease;
    }

    #${LOBBY_BUTTON_ID}:hover .party-mode-icon {
      filter: brightness(1.3);
    }

    #${LOBBY_BUTTON_ID}.active .party-mode-icon {
      background-image: url('data:image/svg+xml,<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path fill="%230acbe6" d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 3c1.66 0 3 1.34 3 3s-1.34 3-3 3-3-1.34-3-3 1.34-3 3-3zm0 14.2c-2.5 0-4.71-1.28-6-3.22.03-1.99 4-3.08 6-3.08 1.99 0 5.97 1.09 6 3.08-1.29 1.94-3.5 3.22-6 3.22z"/></svg>');
    }

    #${LOBBY_BUTTON_ID} .lobby-peer-count {
      position: absolute;
      top: -4px;
      right: -6px;
      min-width: 14px;
      height: 14px;
      background: #0acbe6;
      border-radius: 7px;
      font-size: 9px;
      font-weight: bold;
      color: #010a13;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 0 3px;
    }

    /* Panel positioning for lobby mode */
    #${PANEL_ID}.lobby-mode {
      position: fixed;
      bottom: auto;
      right: auto;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
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

  // Create floating button for champion select
  function createPartyButton() {
    if (document.getElementById(BUTTON_ID)) return;

    const button = document.createElement("div");
    button.id = BUTTON_ID;
    button.title = "Party Mode - Share skins with friends";
    button.innerHTML = `
      <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
        <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 3c1.66 0 3 1.34 3 3s-1.34 3-3 3-3-1.34-3-3 1.34-3 3-3zm0 14.2c-2.5 0-4.71-1.28-6-3.22.03-1.99 4-3.08 6-3.08 1.99 0 5.97 1.09 6 3.08-1.29 1.94-3.5 3.22-6 3.22z"/>
      </svg>
      <span class="peer-count" style="display: none;">0</span>
    `;

    button.addEventListener("click", togglePanel);
    document.body.appendChild(button);
    partyButton = button;
    updateButtonState();
  }

  // Create button in social actions bar for lobby
  function createLobbyButton() {
    if (document.getElementById(LOBBY_BUTTON_ID)) return;

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
    button.title = "Party Mode - Share skins with friends";
    button.innerHTML = `
      <span class="party-mode-icon"></span>
      <span class="lobby-peer-count" style="display: none;">0</span>
    `;

    button.addEventListener("click", togglePanel);

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

    const connectedPeers = partyState.peers.filter((p) => p.connected).length;
    const peerCount = lobbyButton.querySelector(".lobby-peer-count");

    if (partyState.enabled) {
      lobbyButton.classList.add("active");
      if (connectedPeers > 0) {
        peerCount.textContent = connectedPeers;
        peerCount.style.display = "flex";
      } else {
        peerCount.style.display = "none";
      }
    } else {
      lobbyButton.classList.remove("active");
      peerCount.style.display = "none";
    }
  }

  function createPartyPanel() {
    if (document.getElementById(PANEL_ID)) return;

    const panel = document.createElement("div");
    panel.id = PANEL_ID;
    panel.innerHTML = `
      <div class="party-header">
        <h3>Party Mode</h3>
        <span class="party-status offline">Offline</span>
      </div>
      <div class="party-content">
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
    `;

    document.body.appendChild(panel);
    partyPanel = panel;

    // Event listeners
    document
      .getElementById("party-toggle-btn")
      .addEventListener("click", handleToggleParty);
    document
      .getElementById("copy-token-btn")
      .addEventListener("click", handleCopyToken);
    document
      .getElementById("add-peer-btn")
      .addEventListener("click", handleAddPeer);
    document
      .getElementById("add-peer-input")
      .addEventListener("keypress", (e) => {
        if (e.key === "Enter") handleAddPeer();
      });
  }

  function togglePanel() {
    if (!partyPanel) return;
    isVisible = !isVisible;
    partyPanel.classList.toggle("visible", isVisible);
  }

  function updateButtonState() {
    // Update floating button (champ select)
    if (partyButton) {
      const connectedPeers = partyState.peers.filter((p) => p.connected).length;
      const peerCount = partyButton.querySelector(".peer-count");

      if (partyState.enabled) {
        partyButton.classList.add("active");
        if (connectedPeers > 0) {
          peerCount.textContent = connectedPeers;
          peerCount.style.display = "flex";
        } else {
          peerCount.style.display = "none";
        }
      } else {
        partyButton.classList.remove("active");
        peerCount.style.display = "none";
      }
    }

    // Update lobby button
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
    const messageEl = document.getElementById("add-peer-message");
    // Strip and remove all whitespace (spaces, newlines, tabs) so pasted tokens work
    const token = input.value.replace(/\s+/g, "").trim();

    if (!token) {
      messageEl.innerHTML =
        '<div class="error-msg">Please enter a token</div>';
      return;
    }

    messageEl.innerHTML =
      '<div class="success-msg"><span class="spinner"></span> Waiting for your friend...</div>';
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
        updatePanelState();
        break;

      case "party-disabled":
        const toggleBtnDisable = document.getElementById("party-toggle-btn");
        toggleBtnDisable.disabled = false;

        partyState.enabled = false;
        partyState.my_token = null;
        partyState.peers = [];
        console.log(`${LOG_PREFIX} Party mode disabled`);
        updatePanelState();
        break;

      case "party-peer-added":
        const addMessageEl = document.getElementById("add-peer-message");
        if (data.success) {
          addMessageEl.innerHTML =
            '<div class="success-msg">Friend connected!</div>';
          setTimeout(() => {
            addMessageEl.innerHTML = "";
          }, 3000);
        } else {
          addMessageEl.innerHTML = `<div class="error-msg">${escapeHtml(data.error || "Failed to connect")}</div>`;
        }
        // Request updated state
        sendBridgeMessage({ type: "party-get-state" });
        break;

      case "party-peer-removed":
        // Request updated state
        sendBridgeMessage({ type: "party-get-state" });
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
  function removePartyUI() {
    if (partyPanel) {
      partyPanel.classList.remove("visible");
      partyPanel.remove();
      partyPanel = null;
      isVisible = false;
    }
    if (partyButton) {
      partyButton.remove();
      partyButton = null;
    }
    if (lobbyButton) {
      lobbyButton.remove();
      lobbyButton = null;
    }
    currentUIMode = null;
  }

  // Monitor for lobby/champ select
  function startGamePhaseMonitor() {
    let wasInGamePhase = false;
    let lobbyButtonRetryCount = 0;

    setInterval(() => {
      const inChampSelect = isInChampSelect();
      const inLobby = isInLobby();
      const inGamePhase = inChampSelect || inLobby;

      if (inGamePhase && !wasInGamePhase) {
        // Entering a game phase
        if (inChampSelect) {
          console.log(`${LOG_PREFIX} Entered champion select`);
          currentUIMode = "champselect";
          createPartyButton();
          createPartyPanel();
          if (partyPanel) {
            partyPanel.classList.remove("lobby-mode");
          }
        } else if (inLobby) {
          console.log(`${LOG_PREFIX} Entered lobby`);
          currentUIMode = "lobby";
          lobbyButtonRetryCount = 0;
          const success = createLobbyButton();
          createPartyPanel();
          if (partyPanel) {
            partyPanel.classList.add("lobby-mode");
          }
          if (!success) {
            lobbyButtonRetryCount = 1;
          }
        }
      } else if (inGamePhase && wasInGamePhase) {
        // Still in game phase - check if phase changed (lobby <-> champ select)
        if (inChampSelect && currentUIMode === "lobby") {
          console.log(`${LOG_PREFIX} Transitioned from lobby to champion select`);
          removePartyUI();
          currentUIMode = "champselect";
          createPartyButton();
          createPartyPanel();
          if (partyPanel) {
            partyPanel.classList.remove("lobby-mode");
          }
        } else if (inLobby && currentUIMode === "champselect") {
          console.log(`${LOG_PREFIX} Transitioned from champion select to lobby`);
          removePartyUI();
          currentUIMode = "lobby";
          lobbyButtonRetryCount = 0;
          createLobbyButton();
          createPartyPanel();
          if (partyPanel) {
            partyPanel.classList.add("lobby-mode");
          }
        } else if (inLobby && currentUIMode === "lobby" && !lobbyButton && lobbyButtonRetryCount < 10) {
          // Retry creating lobby button if it failed (social bar might not be ready)
          const success = createLobbyButton();
          if (success) {
            lobbyButtonRetryCount = 0;
          } else {
            lobbyButtonRetryCount++;
          }
        }
      } else if (!inGamePhase && wasInGamePhase) {
        console.log(`${LOG_PREFIX} Left game phase`);
        removePartyUI();
      }

      wasInGamePhase = inGamePhase;
    }, 500);
  }

  // Initialize
  async function init() {
    console.log(`${LOG_PREFIX} Initializing...`);

    await loadBridgePort();
    injectStyles();
    connectBridge();
    startGamePhaseMonitor();

    // Also create button immediately if already in lobby/champ select
    if (isInChampSelect()) {
      currentUIMode = "champselect";
      createPartyButton();
      createPartyPanel();
    } else if (isInLobby()) {
      currentUIMode = "lobby";
      createLobbyButton();
      createPartyPanel();
      if (partyPanel) {
        partyPanel.classList.add("lobby-mode");
      }
    }

    console.log(`${LOG_PREFIX} Initialized`);
  }

  // Start when DOM is ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
