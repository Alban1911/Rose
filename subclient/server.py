import asyncio
import base64
import hmac
import json
import logging
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional, Tuple

import aiohttp
from aiohttp import web

from . import frontend

log = logging.getLogger("subclient")

COOKIE = "rose_subclient"
_READ_METHODS = frozenset({"GET", "HEAD"})
_QUIET_WRITES = ("/telemetry/", "/tracing/")
# WAMP 1 messages a viewer may send: PREFIX, SUBSCRIBE, UNSUBSCRIBE
_WAMP_ALLOWED = frozenset({1, 5, 6})
_WAMP_CALL, _WAMP_CALLERROR = 2, 4
_READ_ONLY = "Blocked by the Rose sub-client (read-only)"
_REQUEST_HEADERS = ("Accept", "Accept-Language", "If-None-Match", "If-Modified-Since", "Range")
_RESPONSE_HEADERS = ("Content-Type", "Content-Length", "Content-Encoding", "Content-Range", "Accept-Ranges",
                     "Cache-Control", "ETag", "Last-Modified")
# Windows can map .js to text/plain, and browsers refuse module scripts served so
_CONTENT_TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
                  ".json": "application/json", ".html": "text/html", ".svg": "image/svg+xml"}


@dataclass(frozen=True)
class LcuEndpoint:
    """Where the real client's LCU API listens."""
    pid: int
    port: int
    password: str

    @property
    def base(self) -> str:
        return f"https://127.0.0.1:{self.port}"

    @property
    def ws_url(self) -> str:
        return f"wss://127.0.0.1:{self.port}/"

    @property
    def authorization(self) -> str:
        return "Basic " + base64.b64encode(f"riot:{self.password}".encode("utf-8")).decode("ascii")


def is_read_request(method: str) -> bool:
    return method.upper() in _READ_METHODS


def screen_wamp(message: str) -> Tuple[bool, Optional[str]]:
    """For a WAMP message from the UI or Rose: (send it to the real client?, reply instead)."""
    try:
        data = json.loads(message)
    except ValueError:
        return False, None
    if not isinstance(data, list) or not data:
        return False, None
    if data[0] in _WAMP_ALLOWED:
        return True, None
    if data[0] == _WAMP_CALL and len(data) >= 2:
        return False, json.dumps([_WAMP_CALLERROR, data[1], "rose-subclient:read-only", _READ_ONLY])
    return False, None


def content_type(name: str) -> str:
    suffix = Path(name).suffix.lower()
    return _CONTENT_TYPES.get(suffix) or mimetypes.guess_type(name)[0] or "application/octet-stream"


class SubclientServer:
    def __init__(self, *, endpoint: Callable[[], Awaitable[Optional[LcuEndpoint]]], league_dir: Path,
                 plugins_dir: Path, bridge_port_file: Path, token: str, title: str):
        self._endpoint = endpoint
        self._league_dir = Path(league_dir)
        self._plugins_dir = Path(plugins_dir).resolve()
        self._bridge_port_file = Path(bridge_port_file)
        self._token = token
        self._title = title
        self._session: Optional[aiohttp.ClientSession] = None
        self._frontend = []
        self._graph = {}
        self._assets: Optional[frontend.FrontendAssets] = None

    def make_app(self) -> web.Application:
        app = web.Application(middlewares=[self._authorize])
        app.on_startup.append(self._start)
        app.on_cleanup.append(self._stop)
        app.router.add_get("/bootstrap.html", self._bootstrap)
        app.router.add_get("/index.html", self._bootstrap)
        app.router.add_get("/graph.json", self._dependency_graph)
        app.router.add_get("/fe/{short}/{relative:.+}", self._frontend_file)
        app.router.add_get("/rose-plugins/{relative:.+}", self._rose_plugin_file)
        app.router.add_route("*", "/{tail:.*}", self._proxy)
        return app

    async def _start(self, _app):
        # The LCU uses a self-signed certificate on 127.0.0.1.
        self._session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False), auto_decompress=False)
        plugins = await self._lcu_json("/plugin-manager/v2/plugins")
        manifest = await self._lcu_json("/plugin-manager/v3/plugins-manifest")
        try:
            locale = (await self._lcu_json("/riotclient/region-locale")).get("locale", "")
        except (aiohttp.ClientError, ValueError):
            locale = ""
        self._frontend = frontend.frontend_plugins(plugins)
        if not self._frontend:
            raise RuntimeError("The League client reported no frontend plugins")
        self._graph = frontend.build_graph(self._frontend, manifest)
        self._assets = frontend.FrontendAssets(self._league_dir, self._frontend, locale)

    async def _stop(self, _app):
        if self._session:
            await self._session.close()

    async def _lcu_json(self, path: str):
        endpoint = await self._endpoint()
        if endpoint is None:
            raise RuntimeError("The League client is not running")
        async with self._session.get(endpoint.base + path, headers={"Authorization": endpoint.authorization}) as r:
            r.raise_for_status()
            return json.loads(await r.read())

    def _is_authorized(self, request: web.Request) -> bool:
        cookie = request.cookies.get(COOKIE, "")
        if cookie and hmac.compare_digest(cookie, self._token):
            return True
        expected = "Basic " + base64.b64encode(f"riot:{self._token}".encode("utf-8")).decode("ascii")
        return hmac.compare_digest(request.headers.get("Authorization", ""), expected)

    @web.middleware
    async def _authorize(self, request: web.Request, handler):
        key = request.query.get("key")
        if key is not None and request.path in ("/bootstrap.html", "/index.html"):
            if not hmac.compare_digest(key, self._token):
                return web.Response(status=401, text="Wrong sub-client key")
            response = web.Response(status=302, headers={"Location": "/bootstrap.html"})
            response.set_cookie(COOKIE, self._token, httponly=True, samesite="Strict", path="/")
            return response
        if not self._is_authorized(request):
            return web.Response(status=401, text="Open the sub-client from the URL python -m subclient printed")
        return await handler(request)

    def _bridge_port(self) -> Optional[int]:
        try:
            port = int(self._bridge_port_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None
        return port if 0 < port < 65536 else None

    async def _bootstrap(self, request: web.Request) -> web.Response:
        html = frontend.build_bootstrap(
            self._frontend,
            self._assets,
            title=self._title,
            websocket_url=f"ws://{request.host}/",
            rose_plugins=frontend.rose_plugin_names(self._plugins_dir),
            config={"bridgePort": self._bridge_port()},
        )
        return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-store"})

    async def _dependency_graph(self, _request: web.Request) -> web.Response:
        return web.json_response(self._graph)

    async def _frontend_file(self, request: web.Request) -> web.Response:
        relative = request.match_info["relative"]
        data = await asyncio.to_thread(self._assets.read, request.match_info["short"], relative)
        if data is None:
            return web.Response(status=404)
        return web.Response(body=data, headers={"Content-Type": content_type(relative)})

    async def _rose_plugin_file(self, request: web.Request) -> web.StreamResponse:
        path = (self._plugins_dir / request.match_info["relative"]).resolve()
        if not path.is_relative_to(self._plugins_dir) or not path.is_file():
            return web.Response(status=404)
        return web.FileResponse(path, headers={"Content-Type": content_type(path.name), "Cache-Control": "no-cache"})

    async def _proxy(self, request: web.Request) -> web.StreamResponse:
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return await self._websocket(request)
        if not is_read_request(request.method):
            if request.path.startswith(_QUIET_WRITES):
                return web.Response(status=204)
            log.info("Refused %s %s (read-only)", request.method, request.path)
            return web.json_response({"errorCode": "RPC_ERROR", "httpStatus": 403, "message": _READ_ONLY}, status=403)
        endpoint = await self._endpoint()
        if endpoint is None:
            return web.json_response({"errorCode": "RPC_ERROR", "httpStatus": 503,
                                      "message": "The League client is not running"}, status=503)
        headers = {name: request.headers[name] for name in _REQUEST_HEADERS if name in request.headers}
        headers["Authorization"] = endpoint.authorization
        try:
            async with self._session.request(request.method, endpoint.base + request.rel_url.raw_path_qs,
                                             headers=headers, allow_redirects=False) as upstream:
                response = web.StreamResponse(status=upstream.status, headers={
                    name: upstream.headers[name] for name in _RESPONSE_HEADERS if name in upstream.headers})
                await response.prepare(request)
                if request.method != "HEAD":
                    async for chunk in upstream.content.iter_chunked(64 * 1024):
                        await response.write(chunk)
                await response.write_eof()
                return response
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.debug("LCU request %s failed: %s", request.path, e)
            return web.json_response({"errorCode": "RPC_ERROR", "httpStatus": 502,
                                      "message": f"The League client did not answer: {e}"}, status=502)

    async def _websocket(self, request: web.Request) -> web.StreamResponse:
        endpoint = await self._endpoint()
        if endpoint is None:
            return web.Response(status=503, text="The League client is not running")
        client = web.WebSocketResponse(protocols=("wamp",), max_msg_size=0)
        await client.prepare(request)
        connector = aiohttp.TCPConnector(ssl=False, force_close=True)
        async with aiohttp.ClientSession(connector=connector) as session:
            try:
                upstream = await session.ws_connect(
                    endpoint.ws_url,
                    headers={"Authorization": endpoint.authorization},
                    origin=endpoint.base, protocols=("wamp",), max_msg_size=0)
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                log.debug("LCU WebSocket failed: %s", e)
                await client.close(code=1011, message=b"The League client did not answer")
                return client
            async with upstream:
                relay = asyncio.create_task(self._relay_events(upstream, client))
                try:
                    async for message in client:
                        if message.type != aiohttp.WSMsgType.TEXT:
                            continue
                        forward, reply = screen_wamp(message.data)
                        if forward:
                            await upstream.send_str(message.data)
                        elif reply:
                            await client.send_str(reply)
                finally:
                    relay.cancel()
        return client

    @staticmethod
    async def _relay_events(upstream, client: web.WebSocketResponse) -> None:
        async for message in upstream:
            if message.type == aiohttp.WSMsgType.TEXT:
                await client.send_str(message.data)
            elif message.type == aiohttp.WSMsgType.BINARY:
                await client.send_bytes(message.data)
        await client.close()
