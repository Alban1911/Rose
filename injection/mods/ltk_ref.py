#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A saved mod LTK Manager holds, named where a mod's folder name goes.

The injection passes its mods around as names in the injection's mods folder
(mk_run_overlay, stage_mods, prepare_plan). A mod the user added lives in LTK
Manager's library only, with no file there: it travels in those same lists as
a reference to its library entry (its source's name: injection.mods.mod_source),
and the code that turns a name into a path asks ltk_id_of first.

The token holds no ':': on Windows, Path(x) / "ltk:..." reads it as a drive
and drops x.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Tuple

LTK_REF_PREFIX = "ltk~"

# LTK Manager names its library entries by UUID; requiring that form also
# keeps a token from ever holding a path separator
_LTK_ID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def is_ltk_id(value: object) -> bool:
    """Whether *value* is an LTK Manager library id (a UUID)."""
    return isinstance(value, str) and _LTK_ID.fullmatch(value) is not None


def ltk_ref(ltk_id: str) -> str:
    """The name of the library entry *ltk_id* in a list of mod names.

    Raises ValueError for anything but a library id: a token ltk_id_of does
    not recognise would be taken for a file name further on.
    """
    if not is_ltk_id(ltk_id):
        raise ValueError(f"Not an LTK Manager library id: {ltk_id!r}")
    return f"{LTK_REF_PREFIX}{ltk_id}"


def ltk_id_of(name: object) -> Optional[str]:
    """The library id a mod name refers to, or None for a file's name."""
    if not isinstance(name, str) or not name.startswith(LTK_REF_PREFIX):
        return None
    ltk_id = name[len(LTK_REF_PREFIX):]
    return ltk_id if is_ltk_id(ltk_id) else None


def split_mod_names(names: Iterable[str]) -> Tuple[List[str], List[str]]:
    """An injection's mod names as (the files in its mods folder, the library
    ids of the saved mods LTK Manager holds), each in their order."""
    files: List[str] = []
    ltk_ids: List[str] = []
    for name in names:
        ltk_id = ltk_id_of(name)
        if ltk_id is None:
            files.append(name)
        elif ltk_id not in ltk_ids:
            ltk_ids.append(ltk_id)
    return files, ltk_ids
