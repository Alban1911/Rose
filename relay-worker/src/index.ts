export { PartyRoom } from './room';

interface Env {
  ROOM: DurableObjectNamespace;
}

// Rose before this version could keep a room awake all day (reconnecting every
// 100s when its pings never got through): it is refused here, before waking the
// room, and Rose 1.4.2+ stops retrying on this status. Older Rose sends no version
const MIN_VERSION = [1, 4, 4];

function supported(version: string | null): boolean {
  if (!version) return false;
  const parts = version.split('.').map((part) => parseInt(part, 10));
  for (let i = 0; i < MIN_VERSION.length; i++) {
    const part = Number.isFinite(parts[i]) ? parts[i] : 0;
    if (part !== MIN_VERSION[i]) return part > MIN_VERSION[i];
  }
  return true;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    // Health check
    if (url.pathname === '/' && request.method === 'GET') {
      return new Response(JSON.stringify({ status: 'ok', service: 'rose-party-relay' }), {
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // WebSocket upgrade at /room?key=<room_id>
    const upgrade = request.headers.get('Upgrade');
    if (upgrade?.toLowerCase() === 'websocket') {
      const roomKey = url.searchParams.get('key');
      if (!roomKey || roomKey.length < 8 || roomKey.length > 64) {
        return new Response('Invalid room key', { status: 400 });
      }
      if (!supported(url.searchParams.get('v'))) {
        return new Response('Update Rose to use party mode', { status: 426 });
      }

      const id = env.ROOM.idFromName(roomKey);
      const stub = env.ROOM.get(id);
      return stub.fetch(request);
    }

    return new Response('Rose Party Relay - WebSocket upgrade required', { status: 426 });
  },
};
