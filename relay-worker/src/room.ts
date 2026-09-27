import { DurableObject } from 'cloudflare:workers';

/**
 * Rose Party Room - Durable Object
 *
 * Shared room where party members broadcast their skin selections.
 * All messages are JSON, broadcast to everyone else in the room.
 * Max 10 members per room.
 */

interface MemberInfo {
  summoner_id: number;
  summoner_name: string;
  skin?: SkinInfo;
  joined_at?: number;
}

interface SkinInfo {
  champion_id: number;
  skin_id: number;
  chroma_id?: number;
  skin_name?: string;
  champion_name?: string;
}

export class PartyRoom extends DurableObject {
  private static MAX_MEMBERS = 10;
  // Clients ping every 25s; a socket silent for longer is gone (PC asleep,
  // network lost...) even though no close frame arrived
  private static STALE_MS = 90_000;

  constructor(ctx: DurableObjectState, env: any) {
    super(ctx, env);
    this.ctx.setWebSocketAutoResponse(
      new WebSocketRequestResponsePair('ping', 'pong'),
    );
  }

  async fetch(request: Request): Promise<Response> {
    const active = this.openSockets();

    if (active.length >= PartyRoom.MAX_MEMBERS) {
      return new Response('Room is full', { status: 409 });
    }

    const pair = new WebSocketPair();
    const [client, server] = Object.values(pair);

    this.ctx.acceptWebSocket(server);

    // Send current member list to the new joiner
    const members = this.getMembers();
    server.send(JSON.stringify({ type: 'members', members }));

    return new Response(null, { status: 101, webSocket: client });
  }

  async webSocketMessage(ws: WebSocket, message: string | ArrayBuffer) {
    if (typeof message !== 'string') return;
    if (message === 'pong') return;

    let msg: any;
    try {
      msg = JSON.parse(message);
    } catch {
      return;
    }

    switch (msg.type) {
      case 'join': {
        // Member announces themselves
        const info: MemberInfo = {
          summoner_id: msg.summoner_id,
          summoner_name: msg.summoner_name || 'Unknown',
          joined_at: Date.now(),
        };
        ws.serializeAttachment(info);
        // A rejoin replaces the member's previous connection, which dropped
        // without a close frame
        for (const other of this.ctx.getWebSockets()) {
          if (other === ws) continue;
          const otherInfo = other.deserializeAttachment() as MemberInfo | null;
          if (otherInfo?.summoner_id === info.summoner_id) {
            this.closeSocket(other, 'replaced');
          }
        }
        this.broadcastMembers();
        break;
      }
      case 'skin': {
        // Member updated their skin selection
        const existing = ws.deserializeAttachment() as MemberInfo | null;
        if (existing) {
          existing.skin = msg.skin || null;
          ws.serializeAttachment(existing);
          this.broadcastMembers();
        }
        break;
      }
      case 'leave': {
        ws.close(1000, 'client left');
        break;
      }
    }
  }

  async webSocketClose(ws: WebSocket) {
    // Clear the member info so getMembers() won't include them, and answer
    // the close frame so the client isn't left waiting
    this.closeSocket(ws, 'closed');
    this.broadcastMembers();
  }

  async webSocketError(ws: WebSocket) {
    ws.serializeAttachment(null);
    this.broadcastMembers();
  }

  private closeSocket(ws: WebSocket, reason: string) {
    try {
      ws.serializeAttachment(null);
    } catch {}
    try {
      ws.close(1000, reason);
    } catch {}
  }

  // Open sockets, closing the ones that stopped pinging
  private openSockets(): WebSocket[] {
    const now = Date.now();
    const open: WebSocket[] = [];
    for (const ws of this.ctx.getWebSockets()) {
      if (ws.readyState !== WebSocket.READY_STATE_OPEN) continue;
      const info = ws.deserializeAttachment() as MemberInfo | null;
      const lastSeen =
        this.ctx.getWebSocketAutoResponseTimestamp(ws)?.getTime() ?? info?.joined_at ?? now;
      if (now - lastSeen > PartyRoom.STALE_MS) {
        this.closeSocket(ws, 'stale');
        continue;
      }
      open.push(ws);
    }
    return open;
  }

  private getMembers(): MemberInfo[] {
    const members: MemberInfo[] = [];
    for (const ws of this.openSockets()) {
      try {
        const info = ws.deserializeAttachment() as MemberInfo | null;
        if (info?.summoner_id) {
          const { joined_at, ...member } = info;
          members.push(member);
        }
      } catch {}
    }
    return members;
  }

  private broadcastMembers() {
    const members = this.getMembers();
    const payload = JSON.stringify({ type: 'members', members });
    for (const ws of this.openSockets()) {
      try {
        ws.send(payload);
      } catch {}
    }
  }
}
