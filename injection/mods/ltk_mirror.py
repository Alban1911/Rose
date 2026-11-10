#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Mapping, Optional

from utils.core.atomic_file import atomic_write
from utils.core.junction import safe_remove_entry
from utils.core.logging import get_logger

from ..overlay.ltf_journal import JOURNAL_FILE, LtfJournal
from ..overlay.ltk_data import IndexEntry, read_mod_analysis
from .fantome import read_info
from .manifest import (
    HIDDEN,
    MANIFEST_WRITERS_LOCK,
    MIRRORED,
    SavedMod,
    add_saved_mod,
    listed_now,
    ltk_library_mods,
    manifest_ltk_ids,
)
from .mod_facts import read_mod_facts, stamp_of
from .mod_placement import DESCRIPTION_SIDECAR_SUFFIX, choose_archive_destination, write_image_sidecar
from .storage import ModStorageService

log = get_logger()

CHAMPION_SKIN = "champion-skin"
KEPT_WHEN_MOVED = ("displayName", HIDDEN)


@dataclass
class MirrorReport:
    """What a mirror changed in Rose's lists, by the mods' names, and the
    LTK Manager entries it left as they were (failed): the next sync tries
    them again."""

    listed: List[str] = field(default_factory=list)
    moved: List[str] = field(default_factory=list)
    dropped: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)


def category_of(analysis: Optional[Mapping]) -> Optional[str]:
    """The category Rose lists a mod the user added in LTK Manager in, from
    what LTK Manager's own analysis found in it. None for a champion skin:
    Rose's skins are its own. A HUD is UI, though LTK Manager finds it in a
    map's files too. One not analysed yet goes to others."""
    analysis = analysis or {}
    tags = set(analysis.get("tags") or ())
    if CHAMPION_SKIN in tags:
        return None
    if "ui" in tags:
        return "ui"
    if "map-skin" in tags or analysis.get("maps"):
        return "maps"
    return "others"


def mirror_users_mods(storage: ModStorageService, index: Mapping[str, IndexEntry]) -> MirrorReport:
    """List in Rose each mod the user added in LTK Manager (*index*, its
    library), to be picked for a game as Rose's own category mods are: every
    entry Rose did not add, for its saved mods or in its sessions (their
    journal), but champion skins. A listed one LTK Manager no longer holds,
    or that turns out to be Rose's, leaves Rose's lists; LTK Manager keeps it.
    One LTK Manager's analysis puts in another category now moves there.

    Rose's own entries are read after *index*: one Rose adds meanwhile is in
    the index first, and should it be listed as the user's, the next mirror
    drops it."""
    rose_ids = _journal_ids(storage.mods_root) | manifest_ltk_ids(storage.mods_root)
    analysis = read_mod_analysis()
    wanted = {ltk_id: category_of(analysis.get(ltk_id)) for ltk_id in index if ltk_id not in rose_ids}
    listings = defaultdict(list)
    for mod in ltk_library_mods(storage.mods_root):
        if mod.mirrored:
            listings[mod.ltk_id].append(mod)
    report = MirrorReport()
    for ltk_id in dict.fromkeys([*wanted, *listings]):
        category, mods = wanted.get(ltk_id), listings[ltk_id]
        keep = next((mod for mod in mods if mod.kind == category), mods[0] if mods else None) if category else None
        for mod in mods:
            if mod is keep:
                continue
            if _drop(storage, mod):
                report.dropped.append(mod.display_name or mod.name)
            else:
                report.failed.append(ltk_id)
        if category and (keep is None or keep.kind != category):
            try:
                (report.moved if keep else report.listed).append(_list(storage, index[ltk_id], category, keep))
            except (OSError, ValueError) as e:
                report.failed.append(ltk_id)
                log.warning(f"[MODS] Could not list the LTK Manager mod {ltk_id} in Rose's {category}: {e}")
    if report.listed or report.moved or report.dropped:
        log.info(f"[MODS] Mods added in LTK Manager: {len(report.listed)} now listed in Rose, "
                 f"{len(report.moved)} moved, {len(report.dropped)} no longer")
    return report


def _journal_ids(mods_root: Path) -> set:
    """The entries Rose's sessions installed or kept, from their journal in
    Rose's data folder beside the saved mods."""
    state = LtfJournal(Path(mods_root).parent / "injection" / JOURNAL_FILE).read()
    return set(state["installed"]) | set(state["kept"])


def _drop(storage: ModStorageService, mod: SavedMod) -> bool:
    """Take a mod the user added in LTK Manager out of Rose's lists, while
    its manifest entry is still the one *mod* was read from."""
    with MANIFEST_WRITERS_LOCK:
        return listed_now(storage.mods_root, mod) is not None and storage.delete_category_mod(mod.kind, mod.name)


def _list(storage: ModStorageService, entry: IndexEntry, category: str, source: Optional[SavedMod]) -> str:
    """List the user's LTK Manager mod *entry* in *category*, with its name,
    description, preview image and facts read from its archive (an entry
    without one is listed under its slug), and return its name. *source*,
    its listing in another category, moves there: the name and hide the
    user gave it come along, as they are now, and it leaves once the new
    one is listed. Nothing it wrote stays when a step fails, and *source*
    stays as it is: the next mirror tries again."""
    archive = entry.archive if entry.archive is not None and entry.archive.is_file() else None
    info = read_info(archive) if archive is not None else {}
    fields: dict = {"ltkId": entry.ltk_id, MIRRORED: True}
    display_name = str(info.get("Name") or "").strip()
    if display_name:
        fields["displayName"] = display_name
    facts = None
    if archive is not None:
        try:
            facts = read_mod_facts(archive)
            fields.update(ltkStamp=stamp_of(archive), updatedAt=archive.stat().st_mtime)
        except (OSError, ValueError, zipfile.BadZipFile) as e:
            log.debug(f"[MODS] Could not read the LTK Manager mod {archive.name}: {e}")
    description = str(info.get("Description") or "").strip()
    folder = storage.mods_root / category
    folder.mkdir(parents=True, exist_ok=True)
    with MANIFEST_WRITERS_LOCK:
        source = listed_now(storage.mods_root, source) if source is not None else None
        if source is not None:
            fields.update({key: source.metadata[key] for key in KEPT_WHEN_MOVED if key in source.metadata})
        name, destination = choose_archive_destination(storage.mods_root, folder, entry.slug or entry.ltk_id)
        written = []
        try:
            if archive is not None:
                written.append(write_image_sidecar(archive, beside=destination))
            if description:
                written.append(destination.with_suffix(DESCRIPTION_SIDECAR_SUFFIX))
                with atomic_write(written[-1], "w", encoding="utf-8") as handle:
                    handle.write(description)
            add_saved_mod(storage.mods_root, destination, facts, **fields)
        except Exception:
            for path in filter(None, written):
                safe_remove_entry(path)
            raise
        if source is not None:
            storage.delete_category_mod(source.kind, source.name)
    return fields.get("displayName") or name
