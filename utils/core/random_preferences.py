"""Persist the Classic per-champion random-skin toggle separately."""

from __future__ import annotations

import json

from utils.core.paths import get_user_data_dir


def _preferences_path():
    return get_user_data_dir() / "classic_random_skin_champions.json"


def load_random_champions() -> set[int]:
    try:
        data = json.loads(_preferences_path().read_text(encoding="utf-8"))
        values = data.get("champions", []) if isinstance(data, dict) else []
        return {int(value) for value in values if int(value) > 0}
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return set()


def is_random_enabled_for_champion(champion_id: int) -> bool:
    try:
        return int(champion_id) in load_random_champions()
    except (TypeError, ValueError):
        return False


def set_random_enabled_for_champion(champion_id: int, enabled: bool) -> None:
    try:
        champion_id = int(champion_id)
        if champion_id <= 0:
            return
        champions = load_random_champions()
        if enabled:
            champions.add(champion_id)
        else:
            champions.discard(champion_id)
        path = _preferences_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"champions": sorted(champions)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except (OSError, TypeError, ValueError):
        pass
