#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Where an injection takes a saved mod from.

The user's saved mods reach an injection as selections (picked in champion
select, restored from the last game), as the steps of the countdown's plan
(injection.core.stage_plan), or as a friend's custom mod matched to one of
theirs (party mode). A saved mod LTK Manager holds goes into the injection's
list of mod names as its LTK reference (injection.mods.ltk_ref): nothing is
linked, and OverlayManager switches its library entry on. A mod still pending
in Rose's storage has its copy linked into the injection's mods folder, as
before. This is where the two are told apart, for all of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from utils.core.junction import is_junction, link_or_extract, safe_remove_entry
from utils.core.paths import get_injection_dir

from ..loadingname.loading_name import LtkSkin
from ..mods.ltk_ref import is_ltk_id, ltk_id_of, ltk_ref
from ..mods.mod_facts import ModFacts
from ..overlay.ltk_library import stored_archive

# What the loading screen name takes a mod LTK Manager holds for when its
# manifest lacks the facts: a skin naming no champion (no name is built) and
# a mod that may carry the text table the name's own would compete with
_UNKNOWN_FACTS = ModFacts(party_hash=None, champion_aliases=(), ships_language_table=True)


def saved_selection(path: Path, ltk_id: object = None, missing: object = False, facts: object = None) -> dict:
    """The keys of a saved mod's selection that tell an injection where to
    take it from: mod_path (Rose's copy, or the path it had once LTK Manager
    holds the mod), mod_folder_name (the LTK reference, or the name the copy
    is linked under: an archive's without its extension), ltk_id, missing,
    and facts (ModFacts.to_manifest(), None when unknown)."""
    path = Path(path)
    ltk_id = ltk_id if is_ltk_id(ltk_id) else None
    if not isinstance(facts, ModFacts):
        facts = ModFacts.from_manifest(facts)
    return {
        "mod_path": str(path),
        "mod_folder_name": ltk_ref(ltk_id) if ltk_id else (path.name if path.is_dir() else path.stem),
        "ltk_id": ltk_id,
        "missing": bool(ltk_id and missing),
        "facts": facts.to_manifest() if facts else None,
    }


@dataclass(frozen=True)
class ModSource:
    """One mod of an injection: a library entry of LTK Manager it switches
    on, or a file Rose links into its mods folder."""

    folder_name: str  # the name Rose's copy is linked under
    source: str  # Rose's copy, or the mod's identity once LTK Manager holds it
    ltk_id: Optional[str] = None
    facts: Optional[ModFacts] = None
    missing: bool = False  # the last sync found LTK Manager's entry gone

    @classmethod
    def of(cls, selection: Mapping, **fields) -> Optional["ModSource"]:
        """The mod a selection (saved_selection's keys) names, None when it
        names none; *fields* are a subclass's own (stage_plan.ModStep)."""
        folder_name, path = selection.get("mod_folder_name"), selection.get("mod_path")
        if not folder_name or not path:
            return None
        ltk_id = selection.get("ltk_id")
        return cls(
            str(folder_name),
            str(path),
            ltk_id if is_ltk_id(ltk_id) else None,
            ModFacts.from_manifest(selection.get("facts")),
            bool(selection.get("missing")),
            **fields,
        )

    def put(self, mods_dir: Path) -> Optional[str]:
        """Make the mod ready for the injection and return its name in the
        injection's list: the LTK reference of an entry LTK Manager holds
        (nothing to put anywhere), else folder_name once Rose's copy is
        linked (or extracted) into *mods_dir*. None when it cannot be
        injected: its entry missing from LTK Manager, or the copy gone.
        Raises OSError when the copy cannot be linked."""
        if self.ltk_id:
            return None if self.missing else ltk_ref(self.ltk_id)
        source = Path(self.source)
        if not source.exists():
            return None
        dest = Path(mods_dir) / self.folder_name
        if dest.exists() or is_junction(dest):
            safe_remove_entry(dest)
        link_or_extract(source, dest, cache_dir=get_injection_dir() / ".extract_cache")
        return self.folder_name if dest.exists() or is_junction(dest) else None


def loading_name_mods(
    mods_dir: Path, skin: str, names: Sequence[str], sources: Iterable[ModSource]
) -> Tuple[Union[Path, LtkSkin], List[Union[Path, ModFacts]]]:
    """What the loading screen name (loading_name.build) reads of an
    injection's skin and of its other mods, by their names in its list: the
    files Rose put into *mods_dir*, and for a mod LTK Manager holds, the facts
    its manifest keeps (*sources*) and, for the skin, LTK Manager's archive."""
    facts = {source.ltk_id: source.facts for source in sources if source.ltk_id}

    def facts_of(ltk_id: str) -> ModFacts:
        return facts.get(ltk_id) or _UNKNOWN_FACTS

    skin_id = ltk_id_of(skin)
    if skin_id:
        skin_source = LtkSkin(facts_of(skin_id).champion_aliases, partial(stored_archive, skin_id))
    else:
        skin_source = Path(mods_dir) / skin
    others = []
    for name in names:
        if name == skin:
            continue
        ltk_id = ltk_id_of(name)
        others.append(facts_of(ltk_id) if ltk_id else Path(mods_dir) / name)
    return skin_source, others
