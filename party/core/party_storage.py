#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Durable, account-scoped settings for Party Mode.

Pairing data lives in Rose's user-data directory so updating or reinstalling
the application doesn't make users exchange invitations again.
"""

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

from utils.core.logging import get_logger
from utils.core.paths import get_state_dir

log = get_logger()

STORAGE_VERSION = 1


class PartyStorage:
    """Small atomic JSON store keyed by League summoner ID."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or (get_state_dir() / "party_mode.json")

    @staticmethod
    def _default_account() -> Dict[str, Any]:
        return {
            "auto_enable": False,
            "own_key": None,
            "active_room_key": None,
            "active_room_host_id": None,
            "active_room_host_key": None,
            "auto_room_key": None,
            "auto_lobby_members": [],
            "auto_room_updated_at": None,
            "trusted_peers": {},
            "ignored_peers": [],
        }

    def load_account(self, summoner_id: int) -> Dict[str, Any]:
        data = self._read()
        account = data.get("accounts", {}).get(str(int(summoner_id)), {})
        result = self._default_account()
        if isinstance(account, dict):
            result.update(account)
        if not isinstance(result.get("trusted_peers"), dict):
            result["trusted_peers"] = {}
        if not isinstance(result.get("ignored_peers"), list):
            result["ignored_peers"] = []
        return deepcopy(result)

    def update_account(self, summoner_id: int, **changes: Any) -> Dict[str, Any]:
        data = self._read()
        accounts = data.setdefault("accounts", {})
        account = self._default_account()
        existing = accounts.get(str(int(summoner_id)))
        if isinstance(existing, dict):
            account.update(existing)
        account.update(changes)
        accounts[str(int(summoner_id))] = account
        self._write(data)
        return deepcopy(account)

    def trust_peer(
        self,
        summoner_id: int,
        peer_id: int,
        summoner_name: str = "Unknown",
    ) -> None:
        account = self.load_account(summoner_id)
        trusted = dict(account["trusted_peers"])
        trusted[str(int(peer_id))] = {
            "summoner_name": str(summoner_name or "Unknown"),
        }
        ignored = [
            value
            for value in account["ignored_peers"]
            if int(value) != int(peer_id)
        ]
        self.update_account(
            summoner_id,
            trusted_peers=trusted,
            ignored_peers=ignored,
        )

    def forget_peer(self, summoner_id: int, peer_id: int) -> None:
        account = self.load_account(summoner_id)
        trusted = dict(account["trusted_peers"])
        trusted.pop(str(int(peer_id)), None)
        ignored = {int(value) for value in account["ignored_peers"]}
        ignored.add(int(peer_id))
        self.update_account(
            summoner_id,
            trusted_peers=trusted,
            ignored_peers=sorted(ignored),
        )

    def _read(self) -> Dict[str, Any]:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError("Party settings root must be an object")
            if not isinstance(data.get("accounts"), dict):
                data["accounts"] = {}
            data["version"] = STORAGE_VERSION
            return data
        except FileNotFoundError:
            return {"version": STORAGE_VERSION, "accounts": {}}
        except Exception as exc:
            log.warning(f"[PARTY] Could not read persistent settings: {exc}")
            return {"version": STORAGE_VERSION, "accounts": {}}

    def _write(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        finally:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass
