"""League process and direct LCU restart helpers."""

from __future__ import annotations

from typing import Any

try:
    import psutil  # type: ignore
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore

from utils.core.logging import get_logger


log = get_logger("pengu")

LEAGUE_PROCESSES = {
    "LeagueClient.exe",
    "LeagueClientUx.exe",
    "LeagueClientUxRender.exe",
    "League of Legends.exe",
}


def is_league_running() -> bool:
    if psutil is None:
        return False
    try:
        return any(
            (process.info.get("name") or "").casefold()
            in {name.casefold() for name in LEAGUE_PROCESSES}
            for process in psutil.process_iter(["name"])
        )
    except (psutil.Error, OSError) as exc:  # type: ignore[attr-defined]
        log.debug("Could not inspect League processes: %s", exc)
        return False


def restart_client(lcu: Any = None) -> bool:
    """Restart League Client UX through a direct LCU request."""
    if lcu is None or not getattr(lcu, "ok", False):
        try:
            from lcu.core.client import LCU
            lcu = LCU()
        except Exception as exc:
            log.warning("Cannot create an LCU client for restart: %s", exc)
            return False

    if not getattr(lcu, "ok", False):
        log.warning("Cannot restart League Client UX: LCU is unavailable")
        return False

    post = getattr(lcu, "post", None)
    if post is None:
        log.warning("Cannot restart League Client UX: LCU client has no post method")
        return False

    try:
        response = post("/riotclient/kill-and-restart-ux", timeout=5.0)
    except Exception as exc:
        log.warning("Direct LCU restart failed: %s", exc)
        return False

    if response is None:
        return False

    status_code = getattr(response, "status_code", 0)
    succeeded = 200 <= status_code < 300
    if not succeeded:
        log.warning("LCU restart returned HTTP %s", status_code)
    return succeeded