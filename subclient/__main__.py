"""python -m subclient: this worktree's own League client window and Rose.

Start your League client as usual first. Each worktree keeps its state in
.rose-dev/ at its root: Rose's data folder, the browser profile, and the
lockfile through which its Rose reaches the sub-client.
"""

import argparse
import asyncio
import configparser
import logging
import os
import secrets
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import List, Optional

from aiohttp import web

from .server import LcuEndpoint, SubclientServer

log = logging.getLogger("subclient")

REPO = Path(__file__).resolve().parent.parent
_ROSE_START_TIMEOUT_S = 120.0
_ENDPOINT_CACHE_S = 2.0
_LINKED_READ_ONLY_LIBRARIES = ("skins", "classic")
_COPIED_LIBRARIES = ("resources",)


class RealClient:
    """The developer's League client, found the way Rose finds it."""

    def __init__(self, lockfile: Optional[str]):
        self._lockfile = lockfile
        self._cached: Optional[LcuEndpoint] = None
        self._checked = -_ENDPOINT_CACHE_S
        self._lock = asyncio.Lock()

    async def endpoint(self) -> Optional[LcuEndpoint]:
        async with self._lock:
            if time.monotonic() - self._checked >= _ENDPOINT_CACHE_S:
                self._cached = await asyncio.to_thread(self._discover)
                self._checked = time.monotonic()
            return self._cached

    def _discover(self) -> Optional[LcuEndpoint]:
        from lcu.core.lockfile import find_lockfile, find_process_credentials, parse_lockfile
        path = find_lockfile(self._lockfile)
        data = (parse_lockfile(path) if path else None) or find_process_credentials()
        return LcuEndpoint(data.pid, data.port, data.password) if data else None


def find_league_dir(explicit: Optional[str], lockfile: Optional[str]) -> Optional[Path]:
    if explicit:
        return Path(explicit)
    from lcu.core.lockfile import find_lockfile
    path = find_lockfile(lockfile)
    return Path(path).parent if path else None


def _link_or_copy(source: str, target: str) -> None:
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def seed_data(data_dir: Path) -> None:
    """Give a new profile the skin library of the developer's own Rose."""
    from utils.core.paths import get_user_data_dir
    source = get_user_data_dir()
    for name in _LINKED_READ_ONLY_LIBRARIES + _COPIED_LIBRARIES:
        if (source / name).is_dir() and not (data_dir / name).exists():
            log.info("Seeding %s from %s", name, source / name)
            copy = _link_or_copy if name in _LINKED_READ_ONLY_LIBRARIES else shutil.copy2
            shutil.copytree(source / name, data_dir / name, copy_function=copy)


def disable_analytics(data_dir: Path) -> None:
    from config import read_config_file, write_config_file
    path = data_dir / "config.ini"
    config = configparser.ConfigParser(interpolation=None)
    read_config_file(config, path)
    if not config.has_section("General"):
        config.add_section("General")
    config.set("General", "analytics_enabled", "false")
    write_config_file(config, path)


def find_browser(explicit: Optional[str]) -> Optional[str]:
    if explicit:
        return explicit
    roots = [os.environ.get(k) for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
    for relative in (r"Google\Chrome\Application\chrome.exe", r"Microsoft\Edge\Application\msedge.exe"):
        for root in filter(None, roots):
            candidate = Path(root) / relative
            if candidate.is_file():
                return str(candidate)
    return None


def browser_command(browser: str, profile: Path, url: str, headless: bool, devtools_port: Optional[int]) -> List[str]:
    command = [browser, f"--user-data-dir={profile}", f"--app={url}", "--window-size=1280,720",
               "--no-first-run", "--no-default-browser-check"]
    if headless:
        command.append("--headless=new")
    if devtools_port:
        command.append(f"--remote-debugging-port={devtools_port}")
    return command


def rose_environment(data_dir: Path, lockfile: Path) -> dict:
    env = dict(os.environ)
    env.update({"ROSE_SUBCLIENT": "1", "ROSE_DATA_DIR": str(data_dir), "LCU_LOCKFILE": str(lockfile)})
    return env


def start_rose(data_dir: Path, lockfile: Path, bridge_port_file: Path, console_log) -> subprocess.Popen:
    bridge_port_file.unlink(missing_ok=True)
    return subprocess.Popen(
        [sys.executable, str(REPO / "main.py"), "--dev"],
        cwd=str(REPO), env=rose_environment(data_dir, lockfile),
        stdout=console_log, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


async def _wait_for_bridge(port_file: Path, rose: subprocess.Popen) -> bool:
    deadline = time.monotonic() + _ROSE_START_TIMEOUT_S
    while time.monotonic() < deadline:
        if port_file.is_file():
            return True
        if rose.poll() is not None:
            return False
        await asyncio.sleep(0.25)
    return False


async def run(args: argparse.Namespace) -> int:
    profile = Path(args.profile).resolve() if args.profile else REPO / ".rose-dev"
    data_dir = profile / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    client = RealClient(args.lockfile)
    real = await client.endpoint()
    if real is None:
        log.error("No League client found. Start League, then run this again.")
        return 1
    league_dir = find_league_dir(args.league_dir, args.lockfile)
    if league_dir is None or not (league_dir / "Plugins").is_dir():
        log.error("Could not find the League install folder: pass --league-dir")
        return 1

    if not args.no_seed:
        seed_data(data_dir)
    disable_analytics(data_dir)

    token = secrets.token_urlsafe(24)
    title = f"Rose sub-client - {REPO.name}"
    bridge_port_file = data_dir / "state" / "bridge_port.txt"
    lockfile = profile / "lockfile"
    server = SubclientServer(endpoint=client.endpoint, league_dir=league_dir,
                             plugins_dir=REPO / "Pengu Loader" / "plugins",
                             bridge_port_file=bridge_port_file, token=token, title=title)
    runner = web.AppRunner(server.make_app(), access_log=None)
    rose = browser = None
    rose_log = None
    await runner.setup()
    try:
        site = web.TCPSite(runner, "127.0.0.1", args.port)
        await site.start()
        port = runner.addresses[0][1]
        lockfile.write_text(f"RoseSubclient:{real.pid}:{port}:{token}:http", encoding="utf-8")
        url = f"http://127.0.0.1:{port}/bootstrap.html?key={token}"
        log.info("Sub-client for %s on http://127.0.0.1:%s", REPO.name, port)

        if not args.no_rose:
            rose_log = open(profile / "rose-console.log", "w", encoding="utf-8")
            rose = start_rose(data_dir, lockfile, bridge_port_file, rose_log)
            log.info("Started Rose (PID %s), data in %s", rose.pid, data_dir)
            if not await _wait_for_bridge(bridge_port_file, rose):
                log.error("Rose did not start its bridge; see %s and %s", profile / "rose-console.log", data_dir / "logs")
                return 1

        if args.no_browser:
            log.info("Open %s", url)
        else:
            path = find_browser(args.browser)
            if path:
                browser = subprocess.Popen(browser_command(path, profile / "browser", url, args.headless, args.devtools_port))
            else:
                log.warning("No Chrome or Edge found, opening the default browser (shares its profile)")
                webbrowser.open(url)
        log.info("Running. Ctrl+C stops the sub-client%s.", " and its Rose" if rose else "")

        while rose is None or rose.poll() is None:
            await asyncio.sleep(0.5)
        log.info("Rose exited with code %s", rose.returncode)
        return rose.returncode or 0
    finally:
        for process in (browser, rose):
            if process and process.poll() is None:
                process.terminate()
        if rose_log:
            rose_log.close()
        lockfile.unlink(missing_ok=True)
        await runner.cleanup()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m subclient", description=__doc__.splitlines()[0])
    parser.add_argument("--profile", help="state folder (default: .rose-dev in this worktree)")
    parser.add_argument("--lockfile", help="the real client's lockfile, if Rose can't find it")
    parser.add_argument("--league-dir", help="the League install folder, if not next to the lockfile")
    parser.add_argument("--port", type=int, default=0, help="sub-client port (default: any free one)")
    parser.add_argument("--no-rose", action="store_true", help="don't start Rose")
    parser.add_argument("--no-browser", action="store_true", help="print the URL instead of opening a window")
    parser.add_argument("--no-seed", action="store_true", help="don't copy your Rose's skin library into a new profile")
    parser.add_argument("--browser", help="Chrome or Edge executable to use")
    parser.add_argument("--headless", action="store_true", help="run the window headless (for agents)")
    parser.add_argument("--devtools-port", type=int, help="expose Chrome DevTools on this port (for agents)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="[subclient] %(message)s")
    if os.environ.get("ROSE_SUBCLIENT"):
        log.error("Run this from a normal shell, not from inside a sub-client's Rose")
        return 1
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
