import json
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .wad import WadArchive

RUNNER = "rcp-fe-plugin-runner"

_LOADING = (
    "<div id='index_loading_div_20210908' style='position: fixed;display: flex;align-items: center;"
    "justify-content: center;flex-direction: column;pointer-events: all;top: 0;left: 0;width: 100%;"
    "height: 100%;direction: ltr;'>    <img src='/lol-game-data/assets/ASSETS/SplashScreens/lol_icon.png'>  </div>"
)

# Pengu's rcp hooks (window.rcp) run plugin callbacks around each Riot
# plugin's init, which ROSE-UI uses to reach the champ select API.
_SHIM = """
window.riotInvoke = () => Promise.resolve();
(() => {
  const pre = new Map(), post = new Map(), waiting = new Map(), apis = new Map();
  const add = (map, name, value) => { if (!map.has(name)) map.set(name, []); map.get(name).push(value); };
  const full = (name) => (name.startsWith("rcp-") ? name : `rcp-${name}`);
  window.rcp = {
    preInit(name, callback) { add(pre, full(name), callback); },
    postInit(name, callback) { add(post, full(name), callback); },
    whenReady(name) {
      name = full(name);
      return apis.has(name) ? Promise.resolve(apis.get(name)) : new Promise((resolve) => add(waiting, name, resolve));
    },
    get(name) { return apis.get(full(name)); },
  };
  const announce = "riotPlugin.announce:";
  const dispatch = document.dispatchEvent.bind(document);
  document.dispatchEvent = (event) => {
    if (event.type.startsWith(announce) && typeof event.registrationHandler === "function") {
      const name = event.type.slice(announce.length);
      const register = event.registrationHandler;
      event.registrationHandler = (init) => register(async (provider, ...rest) => {
        for (const callback of pre.get(name) || []) await callback(provider);
        const api = await init(provider, ...rest);
        apis.set(name, api);
        for (const callback of post.get(name) || []) await callback(api);
        for (const resolve of waiting.get(name) || []) resolve(api);
        return api;
      });
    }
    return dispatch(event);
  };
})();
"""


def frontend_plugins(plugins: Iterable[dict]) -> List[dict]:
    """The frontend plugins of /plugin-manager/v2/plugins, in the order the client mounts them."""
    return [p for p in plugins if p.get("supertype") == "frontend"]


def build_graph(frontend: List[dict], manifest: dict) -> dict:
    """The plugin runner's /graph.json: what to initialize, in which order."""
    names = [p["fullName"] for p in frontend]
    implementations = {
        contract["fullName"]: p["fullName"]
        for p in frontend
        for contract in p.get("implementedContracts", [])
        if contract.get("fullName") != p["fullName"]
    }
    return {
        "dependencies": {p["fullName"]: [d["fullName"] for d in p.get("dependencies", [])] for p in frontend},
        "sequence": [n for n in names if n != RUNNER],
        "lazy": [p["name"] for p in manifest.get("plugins", []) if p.get("lazy") and p.get("name") in names],
        "shims": {},
        "implementations": implementations,
    }


class FrontendAssets:
    """Files under /fe/<short name>/, read from each plugin's mounted WADs."""

    def __init__(self, league_dir: Path, frontend: List[dict], locale: str = ""):
        self._full_names = {p["shortName"]: p["fullName"] for p in frontend}
        self._wads: Dict[str, List[WadArchive]] = {
            p["fullName"]: [
                WadArchive(league_dir / Path(bundle.replace("\\", "/")))
                for bundle in p.get("mountedAssetBundles", {}).values()
            ]
            for p in frontend
        }
        self._folders = ["global/default"]
        if locale:
            self._folders += [f"global/{locale.lower()}", locale.lower()]

    def _locate(self, short_name: str, relative: str):
        full = self._full_names.get(short_name)
        if full is None or not relative or ".." in relative.split("/"):
            return None
        for wad in self._wads.get(full, []):
            if not wad.path.is_file():
                continue
            for folder in self._folders:
                path = f"plugins/{full}/{folder}/{relative}"
                if wad.contains(path):
                    return wad, path
        return None

    def has(self, short_name: str, relative: str) -> bool:
        return self._locate(short_name, relative) is not None

    def read(self, short_name: str, relative: str) -> Optional[bytes]:
        found = self._locate(short_name, relative)
        return found[0].read(found[1]) if found else None


def rose_plugin_names(plugins_dir: Path) -> List[str]:
    """The Pengu plugins Pengu would load: folders with an index.js (index.js_ is disabled)."""
    if not plugins_dir.is_dir():
        return []
    return sorted(d.name for d in plugins_dir.iterdir() if (d / "index.js").is_file())


def _script_json(value) -> str:
    return json.dumps(value).replace("</", "<\\/")


def build_bootstrap(frontend: List[dict], assets: FrontendAssets, *, title: str,
                    websocket_url: str, rose_plugins: List[str], config: dict) -> str:
    """The client's bootstrap page, with Pengu's stand-in and this worktree's plugins."""
    stamp = int(time.time() * 1000)
    head = [
        "<!doctype html><html><head>",
        "  <meta charset='utf-8'>",
        "  <meta name='viewport' content='width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=0' />",
        f"  <title>{_html(title)}</title>",
        "  <link rel='riot:plugins:dependency-graph' href='/graph.json' />",
        f"  <link rel='riot:plugins:websocket' href='{_html(websocket_url)}' />",
        "  <link rel='stylesheet' href='/fe/lol-uikit/main.css'>",
        "  <script>window.getPluginAnnounceEventName = (pluginName) => `riotPlugin.announce:${pluginName}`;</script>",
        f"  <script>window.__roseSubclient = {_script_json(config)};{_SHIM}</script>",
    ]
    runner_short = None
    for plugin in frontend:
        short = plugin["shortName"]
        if plugin["fullName"] == RUNNER:
            runner_short = short
            continue
        if assets.has(short, f"rcp-fe-{short}.css"):
            head.append(f"  <link href='/fe/{short}/rcp-fe-{short}.css' rel='stylesheet' data-plugin-name='{short}'>")
        head.append(f"  <script src='/fe/{short}/rcp-fe-{short}.js?t={stamp}'></script>")
    # Pengu imports each plugin as a module once the page is up
    for name in rose_plugins:
        head.append(f"  <script type='module' src='/rose-plugins/{_html(name)}/index.js'></script>")
    runner = runner_short or "plugin-runner"
    body = (
        "</head><body data-env='public' data-loading-div-id='index_loading_div_20210908'>"
        f"{_LOADING}<script src='/fe/{runner}/rcp-fe-{runner}.js?t={stamp}'></script></body></html>"
    )
    return "\n".join(head) + "\n" + body


def _html(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("'", "&#39;").replace('"', "&quot;")
            .replace("<", "&lt;").replace(">", "&gt;"))
