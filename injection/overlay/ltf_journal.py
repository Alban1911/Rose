#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import threading
from pathlib import Path
from typing import Callable, Dict

from utils.core.atomic_file import atomic_write
from utils.core.logging import get_logger

log = get_logger()

_STATE_FILE_LOCK = threading.Lock()


class LtfJournal:
    """The state file of Rose's LTF sessions."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> dict:
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            document = {}
        if not isinstance(document, dict):
            document = {}
        if not any(key in document for key in ("installed", "disabled", "manager", "kept", "switched")):
            document = {"installed": {k: v for k, v in document.items() if isinstance(v, str)}}
        installed = document.get("installed")
        disabled = document.get("disabled")
        manager = document.get("manager")
        kept = document.get("kept")
        switched = document.get("switched")
        return {
            "installed": dict(installed) if isinstance(installed, dict) else {},
            "disabled": [str(mod_id) for mod_id in disabled] if isinstance(disabled, list) else [],
            "manager": manager if isinstance(manager, dict) else None,
            "kept": {
                str(mod_id): record for mod_id, record in kept.items()
                if isinstance(record, dict) and record.get("fingerprint") and record.get("source")
            } if isinstance(kept, dict) else {},
            "switched": {
                str(mod_id): str(name) for mod_id, name in switched.items()
            } if isinstance(switched, dict) else {},
        }

    def update(self, change: Callable[[dict], None]) -> bool:
        """Apply *change* to the state file (read, change, write). False when
        it could not be written: the file then still holds what it held (a
        truncated one would lose the user's mods to turn back on)."""
        with _STATE_FILE_LOCK:
            state = self.read()
            change(state)
            try:
                with atomic_write(self.path) as handle:
                    handle.write(json.dumps(state, ensure_ascii=False, indent=2))
            except OSError as e:
                log.debug(f"[INJECT] Could not write the LTF session state: {e}")
                return False
        return True

    def kept(self) -> Dict[str, dict]:
        """The saved mods left in LTK Manager, turned off: library id -> record."""
        with _STATE_FILE_LOCK:
            return self.read()["kept"]

    def forget_kept(self, mod_ids) -> None:
        """Drop these kept mods from the state file (gone from LTK Manager)."""
        mod_ids = set(mod_ids)

        def drop(state):
            state["kept"] = {k: v for k, v in state["kept"].items() if k not in mod_ids}

        self.update(drop)

    def untrack(self, removed=(), restored=()) -> None:
        """Forget the mods Rose removed and the user's mods it turned back on."""
        removed, restored = set(removed), set(restored)
        if not removed and not restored:
            return

        def drop(state):
            state["installed"] = {k: v for k, v in state["installed"].items() if k not in removed}
            state["disabled"] = [mod_id for mod_id in state["disabled"] if mod_id not in restored]

        self.update(drop)
