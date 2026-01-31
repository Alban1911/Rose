# Party Mode Implementation Plan

## Overview

Party Mode allows friends to see each other's injected skins in-game by exchanging skin selections before the game starts via peer-to-peer networking.

## Key Constraints

- **No central server** - Must be true P2P
- **Same lobby detection** - Auto-detect friends in League lobby
- **Internet P2P** - Works across different networks (NAT traversal required)

## Architecture

### The Signaling Challenge

Without a server, peers need an alternative way to exchange connection info. The solution:

1. **Party Tokens**: Generate shareable connection tokens containing:
   - External IP:port (discovered via public STUN servers)
   - Summoner ID (for lobby matching)
   - Encryption key (for secure communication)

2. **Same Lobby Verification**: Once connected, verify peers are in the same game by matching summoner IDs from LCU session data.

### Data Flow

```
┌─────────────────┐    Party Token    ┌─────────────────┐
│     User A      │◄────────────────► │     User B      │
│  (Rose Client)  │   (via Discord)   │  (Rose Client)  │
└────────┬────────┘                   └────────┬────────┘
         │                                     │
         │ 1. STUN Discovery                   │ 1. STUN Discovery
         │    (get external IP)                │    (get external IP)
         │                                     │
         │ 2. Generate Token                   │ 2. Generate Token
         │    (share with friend)              │    (share with friend)
         │                                     │
         │ 3. UDP Hole Punching ◄─────────────►│ 3. UDP Hole Punching
         │    (establish P2P)                  │    (establish P2P)
         │                                     │
         │ 4. LCU Lobby Detection              │ 4. LCU Lobby Detection
         │    (verify same lobby)              │    (verify same lobby)
         │                                     │
         │ 5. Skin Exchange ◄─────────────────►│ 5. Skin Exchange
         │    {summoner_id: skin_info}         │    {summoner_id: skin_info}
         │                                     │
         │ 6. Inject All Skins                 │ 6. Inject All Skins
         └─────────────────────────────────────┘
```

## Module Structure

```
party/
├── __init__.py
├── core/
│   ├── __init__.py
│   ├── party_manager.py      # Main orchestrator
│   ├── party_state.py        # Party-specific state
│   └── party_config.py       # Configuration constants
├── network/
│   ├── __init__.py
│   ├── stun_client.py        # STUN client for NAT discovery
│   ├── udp_transport.py      # UDP socket handling + hole punching
│   ├── peer_connection.py    # Individual peer connection management
│   └── connection_pool.py    # Manage multiple peer connections
├── protocol/
│   ├── __init__.py
│   ├── token_codec.py        # Party token encoding/decoding
│   ├── message_types.py      # Protocol message definitions
│   ├── message_handler.py    # Protocol message routing
│   └── crypto.py             # Encryption for P2P messages
├── discovery/
│   ├── __init__.py
│   ├── lobby_matcher.py      # Match peers to lobby members
│   └── skin_collector.py     # Collect skin selections from peers
└── integration/
    ├── __init__.py
    ├── injection_hook.py     # Hook into injection flow
    └── ui_bridge.py          # WebSocket messages for UI
```

## Implementation Details

### 1. STUN Client (`party/network/stun_client.py`)

Uses public STUN servers to discover external IP and port:

```python
STUN_SERVERS = [
    ("stun.l.google.com", 19302),
    ("stun1.l.google.com", 19302),
    ("stun.cloudflare.com", 3478),
]
```

**Key functions:**
- `discover_external_address()` -> `(external_ip, external_port)`
- Uses RFC 5389 STUN protocol over UDP

### 2. Party Token (`party/protocol/token_codec.py`)

Compact, shareable token format:

```python
@dataclass
class PartyToken:
    external_ip: str        # IPv4 address
    external_port: int      # UDP port
    internal_ip: str        # For LAN fallback
    internal_port: int      # Local UDP port
    summoner_id: int        # League summoner ID
    encryption_key: bytes   # 32-byte key for AES
    timestamp: int          # Token creation time

    def encode(self) -> str:
        """Encode to base64 string (compact for sharing)"""
        # Format: ip:port|ip:port|summoner_id|key|timestamp
        # Compressed + base64 = ~60 characters

    @classmethod
    def decode(cls, token_str: str) -> "PartyToken":
        """Decode from base64 string"""
```

Example token: `ROSE:aGVsbG8gd29ybGQgdGhpcyBpcyBhIHRlc3Q=` (~60 chars)

### 3. UDP Transport (`party/network/udp_transport.py`)

Handles UDP socket operations with hole punching:

```python
class UDPTransport:
    def __init__(self, local_port: int = 0):
        self.socket: socket.socket
        self.local_port: int

    async def bind(self) -> int:
        """Bind to local port, return assigned port"""

    async def send(self, data: bytes, addr: tuple[str, int]):
        """Send UDP packet"""

    async def recv(self, timeout: float) -> tuple[bytes, tuple[str, int]]:
        """Receive UDP packet with timeout"""

    async def hole_punch(self, remote_addr: tuple[str, int], attempts: int = 5):
        """
        UDP hole punching sequence:
        1. Send punch packet to remote
        2. Wait for response or timeout
        3. Retry with exponential backoff
        """
```

### 4. Peer Connection (`party/network/peer_connection.py`)

Manages individual peer connection lifecycle:

```python
class PeerConnection:
    def __init__(self, token: PartyToken, transport: UDPTransport):
        self.token: PartyToken
        self.state: ConnectionState  # CONNECTING, CONNECTED, DISCONNECTED
        self.summoner_id: int
        self.skin_selection: dict    # {champion_id: skin_data}

    async def connect(self) -> bool:
        """Establish connection via hole punching"""

    async def send_message(self, msg: Message):
        """Send encrypted message to peer"""

    async def recv_message(self) -> Message:
        """Receive and decrypt message from peer"""
```

### 5. Protocol Messages (`party/protocol/message_types.py`)

```python
@dataclass
class Message:
    type: MessageType
    payload: dict
    timestamp: float

class MessageType(Enum):
    PING = "ping"
    PONG = "pong"
    SKIN_UPDATE = "skin_update"       # Single skin selection update
    SKIN_SYNC = "skin_sync"           # Full skin state sync
    LOBBY_INFO = "lobby_info"         # Lobby state sharing
    READY = "ready"                   # Ready for injection
```

**Skin Update Payload:**
```python
{
    "summoner_id": 12345,
    "champion_id": 84,          # Akali
    "skin_id": 84015,           # K/DA ALL OUT Akali
    "chroma_id": None,          # Optional chroma
    "custom_mod": None,         # Optional custom mod path
}
```

### 6. Lobby Matcher (`party/discovery/lobby_matcher.py`)

Matches connected peers to lobby/champion select members:

```python
class LobbyMatcher:
    def __init__(self, lcu: LCU, state: SharedState):
        self.lcu = lcu
        self.state = state

    def get_lobby_summoner_ids(self) -> set[int]:
        """Get summoner IDs from current lobby/champ select"""
        # Use /lol-lobby/v2/lobby for lobby phase
        # Use /lol-champ-select/v1/session myTeam for champ select

    def match_peers_to_lobby(self, peers: list[PeerConnection]) -> dict[int, PeerConnection]:
        """Match connected peers to lobby members by summoner ID"""
        lobby_ids = self.get_lobby_summoner_ids()
        return {
            peer.summoner_id: peer
            for peer in peers
            if peer.summoner_id in lobby_ids
        }
```

### 7. Party Manager (`party/core/party_manager.py`)

Main orchestrator:

```python
class PartyManager:
    def __init__(self, lcu: LCU, state: SharedState, injection_manager):
        self.lcu = lcu
        self.state = state
        self.injection_manager = injection_manager
        self.transport: UDPTransport
        self.peers: dict[int, PeerConnection]  # summoner_id -> connection
        self.my_token: PartyToken
        self.enabled: bool = False

    async def enable(self) -> str:
        """
        Enable party mode:
        1. Bind UDP socket
        2. Discover external address via STUN
        3. Generate and return party token
        """

    async def add_peer(self, token_str: str) -> bool:
        """
        Add peer from token:
        1. Decode token
        2. Attempt connection via hole punching
        3. Add to peer pool if successful
        """

    async def broadcast_skin_update(self, champion_id: int, skin_data: dict):
        """Broadcast skin selection to all connected peers in lobby"""

    def get_party_skins(self) -> dict[int, dict]:
        """Get all peer skin selections for injection"""
        # Returns: {champion_id: skin_data} for all peers in current lobby
```

### 8. Injection Hook (`party/integration/injection_hook.py`)

Hooks into existing injection flow:

```python
class PartyInjectionHook:
    def __init__(self, party_manager: PartyManager, injection_manager):
        self.party_manager = party_manager
        self.injection_manager = injection_manager

    def collect_party_skins(self) -> list[dict]:
        """
        Collect all skins to inject (own + peers):
        1. Get own skin selection from state
        2. Get peer skin selections from party_manager
        3. Deduplicate (own selection takes priority)
        4. Return list of skins to inject
        """

    def prepare_party_injection(self):
        """
        Prepare all party skins for injection:
        1. For each peer skin, resolve to ZIP file
        2. Extract all mods to injection directory
        3. Create overlay with all mods
        """
```

### 9. UI Bridge (`party/integration/ui_bridge.py`)

WebSocket messages for JavaScript UI:

**Python -> JavaScript:**
```python
{
    "type": "party-state",
    "enabled": True,
    "my_token": "ROSE:abc123...",
    "peers": [
        {
            "summoner_id": 12345,
            "summoner_name": "Player1",
            "connected": True,
            "in_lobby": True,
            "skin_selection": {"champion_id": 84, "skin_id": 84015}
        }
    ]
}
```

**JavaScript -> Python:**
```python
{"type": "party-enable"}           # Enable party mode
{"type": "party-disable"}          # Disable party mode
{"type": "party-add-peer", "token": "ROSE:..."}  # Add peer
{"type": "party-remove-peer", "summoner_id": 12345}  # Remove peer
```

## Integration Points

### 1. State Updates (`state/core/shared_state.py`)

Add party-related state:

```python
@dataclass
class SharedState:
    # ... existing fields ...

    # Party mode
    party_mode_enabled: bool = False
    party_token: Optional[str] = None
    party_peers: dict = field(default_factory=dict)  # summoner_id -> peer_info
    party_skins: dict = field(default_factory=dict)  # champion_id -> skin_data
```

### 2. Injection Trigger Modification

In `threads/handlers/injection_trigger.py`, add party skin collection:

```python
def trigger_injection(self, name: str, ticker_id: int, cname: str = ""):
    # ... existing code ...

    # Collect party skins if party mode enabled
    if self.state.party_mode_enabled and self.party_manager:
        party_skins = self.party_manager.get_party_skins()
        # Add party skins to injection list
```

### 3. Message Handler Updates

In `pengu/communication/message_handler.py`, add party message handling:

```python
async def _handle_message(self, data: dict):
    msg_type = data.get("type")

    if msg_type == "party-enable":
        await self._handle_party_enable()
    elif msg_type == "party-disable":
        await self._handle_party_disable()
    elif msg_type == "party-add-peer":
        await self._handle_party_add_peer(data.get("token"))
    # ... etc
```

### 4. Broadcaster Updates

In `pengu/communication/broadcaster.py`, add party state broadcasting:

```python
def broadcast_party_state(self):
    """Broadcast party state to JavaScript UI"""
    if not self.state.party_mode_enabled:
        return

    message = {
        "type": "party-state",
        "enabled": True,
        "my_token": self.state.party_token,
        "peers": self._format_peers_for_ui()
    }
    self._broadcast(json.dumps(message))
```

## Implementation Order

### Phase 1: Core P2P Infrastructure
1. `party/network/stun_client.py` - STUN discovery
2. `party/network/udp_transport.py` - UDP socket handling
3. `party/protocol/token_codec.py` - Token encoding/decoding
4. `party/protocol/crypto.py` - Message encryption
5. `party/network/peer_connection.py` - Peer connection management

### Phase 2: Protocol & Discovery
6. `party/protocol/message_types.py` - Message definitions
7. `party/protocol/message_handler.py` - Message routing
8. `party/discovery/lobby_matcher.py` - Lobby matching
9. `party/discovery/skin_collector.py` - Skin collection

### Phase 3: Integration
10. `party/core/party_state.py` - Party state management
11. `party/core/party_manager.py` - Main orchestrator
12. `party/integration/ui_bridge.py` - UI communication
13. Update `state/core/shared_state.py`
14. Update `pengu/communication/message_handler.py`
15. Update `pengu/communication/broadcaster.py`

### Phase 4: Injection Integration
16. `party/integration/injection_hook.py` - Injection flow hook
17. Update `threads/handlers/injection_trigger.py`

### Phase 5: JavaScript UI (Pengu Loader Plugin)
18. Create `Pengu Loader/plugins/ROSE-PartyMode/index.js`
19. Party enable/disable button
20. Token display/copy functionality
21. Peer token input
22. Peer list display with skin previews

## NAT Traversal Strategy

### UDP Hole Punching Process

1. **Both peers get external address via STUN**
2. **Exchange addresses via party tokens**
3. **Simultaneous punch attempt:**
   - Both peers send UDP packets to each other's external address
   - NAT sees outgoing packet, creates mapping
   - Incoming packet from peer matches mapping, gets through

### Fallback Mechanisms

1. **LAN Detection**: If peers have same external IP, try internal addresses
2. **Symmetric NAT Workaround**: If hole punching fails, try port prediction
3. **Relay Option (Future)**: Could add optional relay server for difficult NATs

## Security Considerations

1. **Token Encryption**: Tokens contain encrypted connection info
2. **Message Encryption**: All P2P messages use AES-256-GCM
3. **Summoner ID Verification**: Verify peer summoner ID matches LCU lobby data
4. **Token Expiration**: Tokens expire after 1 hour
5. **Rate Limiting**: Limit connection attempts to prevent abuse

## Potential Challenges & Mitigations

| Challenge | Mitigation |
|-----------|------------|
| Symmetric NAT (hardest to traverse) | Port prediction + eventual relay fallback |
| Firewall blocking UDP | Document firewall requirements + LAN fallback |
| Token sharing friction | Make tokens short, copyable, with QR code option |
| Timing (skins ready before game) | Start exchange in lobby, not just champ select |
| Multiple peers (party of 5) | Connection pool handles multiple peers efficiently |

## Testing Strategy

1. **Unit Tests**: Protocol encoding, STUN client, encryption
2. **Integration Tests**: Full connection flow on localhost
3. **LAN Tests**: Two machines on same network
4. **Internet Tests**: Two machines on different networks
5. **NAT Type Testing**: Test with different NAT configurations
