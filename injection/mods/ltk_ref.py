#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A saved mod LTK Manager holds, named where a mod's folder name goes.

The injection passes its mods around as names in the injection's mods folder
(mk_run_overlay, stage_mods, prepare_plan, the selections' mod_folder_name).
A mod the user added lives in LTK Manager's library only, with no file there:
it travels in those same lists as a reference to its library entry, and the
code that turns a name into a path asks ltk_id_of first.

The token holds no ':': on Windows, Path(x) / "ltk:..." reads it as a drive
and drops x.
"""

from __future__ import annotations

import re
from typing import Optional

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
