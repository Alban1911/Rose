#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Tuple

LTK_REF_PREFIX = "ltk~"

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
