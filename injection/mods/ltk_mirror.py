#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Mapping, Optional

from utils.core.atomic_file import atomic_write
from utils.core.logging import get_logger

from ..overlay.ltf_journal import JOURNAL_FILE, LtfJournal
from ..overlay.ltk_data import IndexEntry, read_mod_analysis
from .fantome import read_info
from .manifest import (
    ARCHIVE_SUFFIX,
    UnreadableManifest,
    add_mirrored_mod,
    ltk_library_mods,
    manifest_ltk_ids,
)
from .mod_facts import read_mod_facts, stamp_of
from .storage import ModStorageService

log = get_logger()

CHAMPION_SKIN = "champion-skin"


@dataclass
class MirrorReport:
    """What a mirror changed in Rose's lists, by the mods' names."""

    listed: List[str] = field(default_factory=list)
    dropped: List[str] = field(default_factory=list)


def category_of(analysis: Optional[Mapping]) -> Optional[str]:
    """The category Rose lists a mod the user added in LTK Manager in, from
    what LTK Manager's own analysis found in it. None for a champion skin:
    Rose's skins are its own. One not analysed yet goes to others."""
    analysis = analysis or {}
    tags = set(analysis.get("tags") or ())
    if CHAMPION_SKIN in tags:
        return None
    if "map-skin" in tags or analysis.get("maps"):
        return "maps"
    if "ui" in tags:
        return "ui"
    return "others"


def mirror_users_mods(storage: ModStorageService, index: Mapping[str, IndexEntry]) -> MirrorReport:
    """List in Rose each mod the user added in LTK Manager (*index*, its
    library), to be picked for a game as Rose's own category mods are: every
    entry Rose did not add, for its saved mods or in its sessions (their
    journal), but champion skins. A listed one LTK Manager no longer holds,
    or that turns out to be Rose's, leaves Rose's lists; LTK Manager keeps it.

    Rose's own entries are read after *index*: one Rose adds meanwhile is in
    the index first, and should it be listed as the user's, the next mirror
    drops it."""
    rose_ids = _journal_ids(storage.mods_root) | manifest_ltk_ids(storage.mods_root)
    analysis = read_mod_analysis()
    wanted = {ltk_id: category_of(analysis.get(ltk_id)) for ltk_id in index if ltk_id not in rose_ids}
    report = MirrorReport()
    listed = set()
    for mod in ltk_library_mods(storage.mods_root):
        if not mod.mirrored:
            continue
        if wanted.get(mod.ltk_id) and mod.ltk_id not in listed:
            listed.add(mod.ltk_id)
        elif storage.delete_category_mod(mod.kind, mod.name):
            report.dropped.append(mod.display_name or mod.name)
    for ltk_id, category in wanted.items():
        if category and ltk_id not in listed:
            try:
                report.listed.append(_list(storage, index[ltk_id], category))
            except UnreadableManifest as e:
                log.warning(f"[MODS] Could not list the LTK Manager mod {ltk_id} in Rose: {e}")
    if report.listed or report.dropped:
        log.info(f"[MODS] Mods added in LTK Manager: {len(report.listed)} now listed in Rose, "
                 f"{len(report.dropped)} no longer")
    return report


def _journal_ids(mods_root: Path) -> set:
    """The entries Rose's sessions installed or kept, from their journal in
    Rose's data folder beside the saved mods."""
    state = LtfJournal(Path(mods_root).parent / "injection" / JOURNAL_FILE).read()
    return set(state["installed"]) | set(state["kept"])


def _list(storage: ModStorageService, entry: IndexEntry, category: str) -> str:
    """List the user's LTK Manager mod *entry* in *category*, with its name,
    description, preview image and facts read from its archive (an entry
    without one is listed under its slug), and return its name."""
    archive = entry.archive if entry.archive is not None and entry.archive.is_file() else None
    fields: dict = {}
    info = read_info(archive) if archive is not None else {}
    display_name = str(info.get("Name") or "").strip()
    if display_name:
        fields["displayName"] = display_name
    if archive is not None:
        try:
            fields.update(read_mod_facts(archive).to_manifest(), ltkStamp=stamp_of(archive),
                          updatedAt=archive.stat().st_mtime)
        except (OSError, ValueError, zipfile.BadZipFile) as e:
            log.debug(f"[MODS] Could not read the LTK Manager mod {archive.name}: {e}")
    name = add_mirrored_mod(storage.mods_root, category, entry.ltk_id, entry.slug or entry.ltk_id, fields)
    beside = storage.mods_root / category / f"{name}{ARCHIVE_SUFFIX}"
    if archive is not None:
        storage._write_image_sidecar(archive, beside=beside)
    description = str(info.get("Description") or "").strip()
    if description:
        with atomic_write(beside.with_suffix(storage.DESCRIPTION_SIDECAR_SUFFIX), "w", encoding="utf-8") as handle:
            handle.write(description)
    return display_name or name
