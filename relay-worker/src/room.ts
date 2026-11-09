import { DurableObject } from 'cloudflare:workers';

interface MemberInfo {
  protocol: 2;
  summoner_id: string;
  summoner_name: string;
  member_key: string;
  skin?: Record<string, unknown> | null;
  joined_at: number;
}

export function readIdentity(headers: Headers) {
  const id = headers.get('X-Rose-Summoner-Id');
  const authorization = headers.get('Authorization') ?? '';
  const encodedName = headers.get('X-Rose-Summoner-Name') ?? '';
  const credential = /^Bearer ([0-9a-f]{64})$/.exec(authorization)?.[1];
  if (!credential || !id || !/^[1-9][0-9]{0,19}$/.test(id)
      || BigInt(id) > 0xffffffffffffffffn || encodedName.length > 1024) return null;
  try {
    const name = decodeURIComponent(encodedName);
    if (name.length > 128 || /[\u0000-\u001f\u007f]/.test(name)) return null;
    return { id, name: name || 'Unknown', credential };
  } catch {
    return null;
  }
}

/** Authenticated, hibernatable room with at most ten simultaneous members. */
export class PartyRoom extends DurableObject {
  private static readonly MAX_MEMBERS = 10;
  private static readonly MAX_IDENTITIES = 128;
  private static readonly MAX_MESSAGE_BYTES = 8 * 1024;
  // Clients ping every 25s. A silent socket can be dropped without a close handshake.
  private static readonly STALE_MS = 90_000;

  constructor(ctx: DurableObjectState, env: Cloudflare.Env) {
    super(ctx, env);
    this.ctx.storage.sql.exec(
      'CREATE TABLE IF NOT EXISTS party_identity (summoner_id TEXT PRIMARY KEY, credential_hash TEXT NOT NULL)',
    );
    this.ctx.setWebSocketAutoResponse(new WebSocketRequestResponsePair('ping', 'pong'));
  }

  async fetch(request: Request): Promise<Response> {
    const identity = readIdentity(request.headers);
    if (!identity) return new Response('Invalid party identity', { status: 400 });

    const proof = new TextEncoder().encode('rose-party-member-v2:' + identity.id + ':' + identity.credential);
    const digest = await crypto.subtle.digest('SHA-256', proof);
    const hash = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
    const sql = this.ctx.storage.sql;
    // Keep registration and replacement synchronous after hashing. A concurrent
    // upgrade must observe the first binding instead of registering over it.
    const binding = sql.exec<{ credential_hash: string }>(
      'SELECT credential_hash FROM party_identity WHERE summoner_id = ?', identity.id,
    ).toArray()[0];
    if (binding && binding.credential_hash !== hash) {
      return new Response('Party identity is registered to another installation', { status: 403 });
    }

    const active = this.openSockets();
    const previous = active.find(({ member }) => member.summoner_id === identity.id);
    if (!previous && active.length >= PartyRoom.MAX_MEMBERS) {
      this.log('full', { open: active.length });
      return new Response('Room is full', { status: 409 });
    }
    if (!binding) {
      const { count } = sql.exec<{ count: number }>('SELECT COUNT(*) AS count FROM party_identity').one();
      if (count >= PartyRoom.MAX_IDENTITIES) {
        return new Response('Room identity limit reached', { status: 507 });
      }
      sql.exec('INSERT INTO party_identity VALUES (?, ?)', identity.id, hash);
    }

    const [client, server] = Object.values(new WebSocketPair());
    this.ctx.acceptWebSocket(server);
    server.serializeAttachment({
      protocol: 2,
      summoner_id: identity.id,
      summoner_name: identity.name,
      member_key: hash,
      joined_at: Date.now(),
    } satisfies MemberInfo);
    if (previous) {
      this.notifyReplaced(previous.socket);
      this.dropSocket(previous.socket, 'replaced');
    }
    this.log('join', { summoner_id: identity.id, replaced: Boolean(previous) });
    this.broadcastMembers();
    return new Response(null, {
      status: 101,
      headers: { 'X-Rose-Party-Protocol': '2' },
      webSocket: client,
    });
  }

  async webSocketMessage(ws: WebSocket, message: string | ArrayBuffer) {
    const member = this.member(ws);
    if (!member || typeof message !== 'string' || message === 'pong') return;
    if (message.length > PartyRoom.MAX_MESSAGE_BYTES
        || new TextEncoder().encode(message).byteLength > PartyRoom.MAX_MESSAGE_BYTES) return;

    let msg: { type?: unknown; skin?: unknown } | null;
    try {
      msg = JSON.parse(message);
    } catch {
      return;
    }

    if (!msg || typeof msg !== 'object') return;
    switch (msg.type) {
      case 'skin': {
        const skin = msg.skin;
        if (skin !== null && (!skin || typeof skin !== 'object' || Array.isArray(skin))) return;
        member.skin = skin as MemberInfo['skin'];
        try {
          ws.serializeAttachment(member);
        } catch {
          return; // The parsed object can exceed the attachment's storage limit.
        }
        this.broadcastMembers();
        break;
      }
      case 'leave': {
        ws.serializeAttachment(null);
        ws.close(1000, 'client left');
        this.broadcastMembers();
        break;
      }
    }
  }

  async webSocketClose(ws: WebSocket, code: number, reason: string, wasClean: boolean) {
    const info = this.member(ws);
    this.log('client_close', { summoner_id: info?.summoner_id, code, reason, wasClean });
    // A connection lost without a close frame (1006) has no peer to answer.
    if (wasClean) {
      try {
        ws.close(1000, 'closed');
      } catch {}
    }
    this.broadcastMembers();
  }

  async webSocketError(ws: WebSocket, error: unknown) {
    const info = this.member(ws);
    this.log('error', { summoner_id: info?.summoner_id, error: String(error) });
    this.dropSocket(ws, 'error');
    this.broadcastMembers();
  }

  // Mark a socket inactive instead of waiting for its peer to acknowledge a
  // close frame. The runtime eventually reaps idle connections.
  private dropSocket(ws: WebSocket, reason: string) {
    this.log('drop', { summoner_id: this.member(ws)?.summoner_id, reason });
    try {
      ws.serializeAttachment(null);
    } catch {}
  }

  private notifyReplaced(ws: WebSocket) {
    try {
      ws.send(JSON.stringify({ type: 'replaced' }));
    } catch {}
  }

  private member(ws: WebSocket): MemberInfo | null {
    const info = ws.deserializeAttachment();
    return info?.protocol === 2 ? info : null;
  }

  private openSockets(): { socket: WebSocket; member: MemberInfo }[] {
    const now = Date.now();
    const open: { socket: WebSocket; member: MemberInfo }[] = [];
    for (const socket of this.ctx.getWebSockets()) {
      if (socket.readyState !== WebSocket.READY_STATE_OPEN) continue;
      const member = this.member(socket);
      if (!member) continue;
      const lastSeen = this.ctx.getWebSocketAutoResponseTimestamp(socket)?.getTime() ?? member.joined_at;
      if (now - lastSeen > PartyRoom.STALE_MS) {
        this.dropSocket(socket, 'stale');
        continue;
      }
      open.push({ socket, member });
    }
    return open;
  }

  private log(event: string, fields: Record<string, unknown>) {
    console.log(JSON.stringify({ event, room: this.ctx.id.toString().slice(0, 12), ...fields }));
  }

  private broadcastMembers() {
    const sockets = this.openSockets();
    const members = sockets.map(({ member: { protocol, joined_at, ...member } }) => member);
    const payload = JSON.stringify({ type: 'members', members });
    for (const { socket } of sockets) {
      try {
        socket.send(payload);
      } catch {}
    }
  }
}
