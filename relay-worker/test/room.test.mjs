import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, before, test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { Miniflare } from 'miniflare';
import WebSocket from 'ws';

const require = createRequire(import.meta.url);
const root = fileURLToPath(new URL('../', import.meta.url));
const temporary = await mkdtemp(join(tmpdir(), 'rose-relay-test-'));
const bundle = join(temporary, 'bundle');
let worker;

function startWorker() {
  return new Miniflare({
    modules: true,
    scriptPath: join(bundle, 'index.js'),
    modulesRoot: bundle,
    compatibilityDate: '2025-01-01',
    durableObjects: { ROOM: { className: 'PartyRoom', useSQLite: true } },
    durableObjectsPersist: join(temporary, 'rooms'),
  });
}

before(() => {
  execFileSync(process.execPath, [
    require.resolve('wrangler/bin/wrangler.js'), 'deploy', '--dry-run', '--outdir', bundle,
  ], { cwd: root, env: { ...process.env, WRANGLER_SEND_METRICS: 'false' } });
  worker = startWorker();
});

after(async () => {
  try {
    await worker?.dispose();
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
});

const newRoom = () => randomBytes(16).toString('hex');
const credential = (byte) => byte.repeat(64);

async function upgrade(room, id, secret, options = {}) {
  const { path = '/room', protocol = '2', name = 'Lótus 🌹' } = options;
  const url = new URL(path, await worker.ready);
  url.protocol = 'ws:';
  url.search = new URLSearchParams({ key: room, v: '1.5.6', p: protocol });
  const headers = {};
  if (id !== undefined) headers['X-Rose-Summoner-Id'] = id;
  if (secret !== undefined) headers.Authorization = 'Bearer ' + secret;
  headers['X-Rose-Summoner-Name'] = encodeURIComponent(name);
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(url, { headers, handshakeTimeout: 3000 });
    const peer = listen(socket);
    let responseHeaders;
    socket.once('upgrade', (response) => { responseHeaders = response.headers; });
    socket.once('open', () => resolve({ status: 101, headers: responseHeaders, peer }));
    socket.once('unexpected-response', (_request, response) => {
      response.resume();
      response.once('end', () => {
        resolve({ status: response.statusCode, headers: response.headers, peer: null });
        socket.terminate();
      });
      response.once('error', reject);
    });
    socket.on('error', reject);
  });
}

function close(peer) {
  return new Promise((resolve) => {
    peer.socket.once('close', resolve);
    peer.socket.close(1000);
  });
}

function connect(response) {
  assert.equal(response.status, 101);
  assert.equal(response.headers['x-rose-party-protocol'], '2');
  return response.peer;
}

function listen(socket) {
  const messages = [];
  let wake;
  socket.on('message', (data) => {
    const message = data.toString();
    if (message === 'pong') return;
    messages.push(JSON.parse(message));
    wake?.();
  });
  return {
    socket,
    async next(type) {
      while (true) {
        const index = messages.findIndex((message) => message.type === type);
        if (index !== -1) return messages.splice(index, 1)[0];
        await new Promise((resolve, reject) => {
          const timeout = setTimeout(() => reject(new Error('Missing message: ' + type)), 2000);
          wake = () => {
            clearTimeout(timeout);
            wake = undefined;
            resolve();
          };
        });
      }
    },
  };
}

test('legacy and incomplete upgrades do not receive a socket', async () => {
  const room = newRoom();
  const legacy = await upgrade(room, '1', credential('a'), { protocol: '' });
  assert.equal(legacy.status, 426);
  assert.equal(legacy.peer, null);
  const missing = await upgrade(room, '1', undefined);
  assert.equal(missing.status, 400);
  assert.equal(missing.peer, null);
  assert.equal((await upgrade(room, '18446744073709551616', credential('a'))).status, 400);
  assert.equal((await upgrade(room, '1', credential('a'), { path: '/other' })).status, 426);
});

test('an invite cannot replace a connected member, whose identity stays fixed', async () => {
  const room = newRoom();
  const id = '18446744073709551615';
  const owner = connect(await upgrade(room, id, credential('a')));
  const initial = (await owner.next('members')).members;
  assert.equal(initial.length, 1);
  assert.equal(initial[0].summoner_id, id);
  assert.equal(initial[0].summoner_name, 'Lótus 🌹');
  assert.match(initial[0].member_key, /^[0-9a-f]{64}$/);
  assert.notEqual(initial[0].member_key, credential('a'));

  const refused = await upgrade(room, id, credential('b'));
  assert.equal(refused.status, 403);
  assert.equal(refused.peer, null);
  const peer = connect(await upgrade(room, '2', credential('b'), { name: 'Peer' }));
  assert.equal((await owner.next('members')).members.length, 2);

  peer.socket.send(JSON.stringify({ type: 'join', summoner_id: id, summoner_name: 'Other' }));
  peer.socket.send('null');
  peer.socket.send(JSON.stringify({ type: 'skin', summoner_id: id, skin: { skin_id: 23 } }));
  const { members } = await owner.next('members');
  assert.deepEqual(members.find((member) => member.summoner_id === id), initial[0]);
  assert.deepEqual(members.find((member) => member.summoner_id === '2')?.skin, { skin_id: 23 });

  const reconnected = connect(await upgrade(room, id, credential('a')));
  await owner.next('replaced');
  assert.equal((await reconnected.next('members')).members.length, 2);
  await Promise.all([owner, peer, reconnected].map(close));

  // Once the member has left, another installation (a reinstall, another PC) takes the ID
  const reinstalled = connect(await upgrade(room, id, credential('c')));
  const [rejoined] = (await reinstalled.next('members')).members;
  assert.equal(rejoined.summoner_id, id);
  assert.notEqual(rejoined.member_key, initial[0].member_key);
  await close(reinstalled);
});

test('members can distinguish the same claimed ID across different rooms', async () => {
  const first = connect(await upgrade(newRoom(), '9', credential('a')));
  const same = connect(await upgrade(newRoom(), '9', credential('a')));
  const different = connect(await upgrade(newRoom(), '9', credential('b')));
  const [knownKey, sameKey, differentKey] = await Promise.all(
    [first, same, different].map(async (peer) => (await peer.next('members')).members[0].member_key),
  );
  assert.equal(knownKey, sameKey);
  assert.notEqual(knownKey, differentKey);
  await Promise.all([first, same, different].map(close));
});

test('concurrent joins admit one installation, and none is bound after it leaves', async () => {
  const room = newRoom();
  const secrets = [credential('a'), credential('b')];
  const responses = await Promise.all(secrets.map((secret) => upgrade(room, '1', secret)));
  assert.deepEqual(responses.map((response) => response.status).sort(), [101, 403]);
  const winner = responses.findIndex((response) => response.status === 101);
  const first = connect(responses[winner]);
  await first.next('members');
  await close(first);

  await worker.dispose();
  worker = startWorker();
  const other = connect(await upgrade(room, '1', secrets[1 - winner]));
  assert.equal((await other.next('members')).members[0].summoner_id, '1');
  await close(other);
});
