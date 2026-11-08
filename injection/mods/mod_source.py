#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Where an injection takes a mod from.

The user's saved mods reach an injection as selections (picked in champion
select, restored from the last game), as the steps of the countdown's plan
(injection.core.stage_plan), or as a friend's custom mod matched to one of
theirs (party mode). Each carries its source, built once from its manifest
entry (SavedMod.source):

- LtkEntry, a saved mod LTK Manager holds: it goes into the injection's list
  of mod names as its LTK reference (injection.mods.ltk_ref), nothing is
  linked, and OverlayManager switches its library entry on;
- RoseFile, a file Rose links into the injection's mods folder: a saved mod
  still pending in Rose's storage, as before, or a friend's skin.

put() readies either for an injection and take_back() undoes it, so the code
that prepares an injection never tells the two apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from utils.core.junction import is_junction, link_or_extract, safe_remove_entry
from utils.core.paths import get_injection_dir

from .ltk_ref import ltk_ref
from .mod_facts import ModFacts


@dataclass(frozen=True)
class RoseFile:
    """A mod file (an archive, or a folder) Rose links into an injection's
    mods folder."""

    path: Path
    name: str  # what it is linked as: its name in the injection's list of mods

    @classmethod
    def at(cls, path: Path) -> "RoseFile":
        """The mod at *path*, linked under its own name: a folder's, an
        archive's without its extension."""
        path = Path(path)
        return cls(path, path.name if path.is_dir() else path.stem)

    @property
    def available(self) -> bool:
        """Whether its file is still there."""
        return self.path.exists()

    def put(self, mods_dir: Path) -> Optional[str]:
        """Link (or extract) the file into *mods_dir* and return its name
        there; None when the file is gone or nothing landed. Raises OSError
        when it cannot be linked."""
        if not self.path.exists():
            return None
        dest = Path(mods_dir) / self.name
        if dest.exists() or is_junction(dest):
            safe_remove_entry(dest)
        link_or_extract(self.path, dest, cache_dir=get_injection_dir() / ".extract_cache")
        return self.name if dest.exists() or is_junction(dest) else None

    def take_back(self, mods_dir: Path) -> None:
        """Undo put: remove the link from *mods_dir* (only it: the other mods stay)."""
        dest = Path(mods_dir) / self.name
        if dest.exists() or is_junction(dest):
            safe_remove_entry(dest)

    def plugin_fields(self) -> dict:
        """Where the plugins' listings say the saved mod is: still Rose's."""
        return {"ltkId": None, "missing": False, "pending": True}


@dataclass(frozen=True)
class LtkEntry:
    """A saved mod LTK Manager's library holds, with the facts its manifest
    keeps (None when it lacks them): nothing is linked for an injection."""

    ltk_id: str
    facts: Optional[ModFacts] = None
    missing: bool = False  # the last sync found the entry gone from LTK Manager

    @property
    def name(self) -> str:
        """Its name in the injection's list of mods: its LTK reference."""
        return ltk_ref(self.ltk_id)

    @property
    def available(self) -> bool:
        """Whether the last sync still found its entry in LTK Manager."""
        return not self.missing

    def put(self, mods_dir: Path) -> Optional[str]:
        """Its LTK reference, the session switches the entry on (None when
        the entry is missing): nothing goes into *mods_dir*."""
        return None if self.missing else self.name

    def take_back(self, mods_dir: Path) -> None:
        """Nothing to undo: put linked nothing."""

    def plugin_fields(self) -> dict:
        """Where the plugins' listings say the saved mod is: LTK Manager's,
        missing when the last sync found its entry gone."""
        return {"ltkId": self.ltk_id, "missing": self.missing, "pending": False}


ModSource = Union[RoseFile, LtkEntry]
