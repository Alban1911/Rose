/**
 * ROSE Skin Unlocker - Pengu Plugin
 * Makes locked skins appear as unlocked in the champion select skin carousel
 */

const SKIN_CAROUSEL_ENDPOINT = '/lol-champ-select/v1/skin-carousel-skins';

/**
 * Modifies a skin object to appear as owned/unlocked
 */
function unlockSkin(skin) {
    if (!skin) return skin;

    skin.unlocked = true;
    skin.ownership = {
        owned: true,
        rental: { rented: false },
        loyaltyReward: false
    };

    if (Array.isArray(skin.childSkins)) {
        skin.childSkins.forEach(chroma => {
            chroma.unlocked = true;
            chroma.ownership = {
                owned: true,
                rental: { rented: false },
                loyaltyReward: false
            };
        });
    }

    return skin;
}

/**
 * Process the skin carousel response
 */
function processCarouselSkins(skins) {
    if (!Array.isArray(skins)) return skins;
    return skins.map(unlockSkin);
}

/**
 * Hook into fetch API (primary method used by League Client)
 */
function hookFetch() {
    const originalFetch = window.fetch;

    window.fetch = async function(input, init) {
        const url = typeof input === 'string' ? input : input.url;
        const response = await originalFetch.call(this, input, init);

        if (url?.includes(SKIN_CAROUSEL_ENDPOINT)) {
            try {
                const data = await response.json();
                const modifiedData = processCarouselSkins(data);

                return new Response(JSON.stringify(modifiedData), {
                    status: response.status,
                    statusText: response.statusText,
                    headers: response.headers
                });
            } catch (e) {
                return response;
            }
        }

        return response;
    };
}

/**
 * Hook WebSocket for real-time updates
 */
function hookWebSocket() {
    const OriginalWebSocket = window.WebSocket;

    window.WebSocket = function(url, protocols) {
        const ws = new OriginalWebSocket(url, protocols);

        const originalAddEventListener = ws.addEventListener.bind(ws);
        ws.addEventListener = function(type, listener, options) {
            if (type === 'message') {
                const wrappedListener = function(event) {
                    const modifiedEvent = processWebSocketMessage(event);
                    return listener.call(this, modifiedEvent);
                };
                return originalAddEventListener(type, wrappedListener, options);
            }
            return originalAddEventListener(type, listener, options);
        };

        // Also handle onmessage property
        let _onmessage = null;
        Object.defineProperty(ws, 'onmessage', {
            get: () => _onmessage,
            set: (handler) => {
                _onmessage = handler;
                if (handler) {
                    originalAddEventListener('message', function(event) {
                        const modifiedEvent = processWebSocketMessage(event);
                        handler.call(this, modifiedEvent);
                    });
                }
            }
        });

        return ws;
    };

    // Preserve prototype chain
    window.WebSocket.prototype = OriginalWebSocket.prototype;
    window.WebSocket.CONNECTING = OriginalWebSocket.CONNECTING;
    window.WebSocket.OPEN = OriginalWebSocket.OPEN;
    window.WebSocket.CLOSING = OriginalWebSocket.CLOSING;
    window.WebSocket.CLOSED = OriginalWebSocket.CLOSED;
}

/**
 * Process WebSocket message and modify if needed
 */
function processWebSocketMessage(event) {
    try {
        const data = JSON.parse(event.data);

        // LCU WebSocket format: [opcode, event, {uri, data}]
        if (data[2]?.uri?.includes(SKIN_CAROUSEL_ENDPOINT) && data[2]?.data) {
            data[2].data = processCarouselSkins(data[2].data);
            return new MessageEvent('message', {
                data: JSON.stringify(data),
                origin: event.origin,
                lastEventId: event.lastEventId,
                source: event.source,
                ports: event.ports
            });
        }
    } catch (e) {}

    return event;
}

/**
 * Plugin entry point
 */
export function init(context) {
    hookFetch();
    hookWebSocket();
}
