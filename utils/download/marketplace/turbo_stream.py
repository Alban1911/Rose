#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Minimal decoder for React Router's turbo-stream (the `*.data` route payloads)

RuneForge serves a mod's latest release only through its page data. The format is
a flat JSON array where every value is referenced by its index: objects map
"_<key index>" to a value index, arrays hold value indexes, and negative numbers
are constants. Deferred values arrive as extra lines "P<id>:<json>" whose array
is appended to the same table.
"""

from __future__ import annotations

import json
from typing import Any

_CONSTANTS = {
    -1: None,  # hole
    -2: float("nan"),
    -3: float("-inf"),
    -4: -0.0,
    -5: None,  # null
    -6: float("inf"),
    -7: None,  # undefined
}


def decode(text: str) -> Any:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("Empty turbo-stream payload")

    values = json.loads(lines[0])
    if not isinstance(values, list):
        raise ValueError("Unexpected turbo-stream payload")

    promises: dict[int, Any] = {}
    for line in lines[1:]:
        if line[:1] not in ("P", "E") or ":" not in line:
            continue
        promise_id, payload = line[1:].split(":", 1)
        try:
            chunk = json.loads(payload)
            promise_index = int(promise_id)
        except (ValueError, json.JSONDecodeError):
            continue
        if line[0] == "E":
            promises[promise_index] = ("constant", None)
        elif isinstance(chunk, list):
            promises[promise_index] = ("index", len(values))
            values.extend(chunk)
        else:
            promises[promise_index] = ("constant", _CONSTANTS.get(chunk, chunk))

    memo: dict[int, Any] = {}

    def hydrate(index):
        if not isinstance(index, int) or isinstance(index, bool):
            return None
        if index < 0:
            return _CONSTANTS.get(index)
        if index >= len(values):
            return None
        if index in memo:
            return memo[index]

        value = values[index]
        if isinstance(value, dict):
            result: dict = {}
            memo[index] = result
            for raw_key, value_index in value.items():
                try:
                    key = values[int(raw_key[1:])]
                except (ValueError, IndexError):
                    continue
                if isinstance(key, str):
                    result[key] = hydrate(value_index)
            return result
        if isinstance(value, list):
            if value and isinstance(value[0], str):
                tag = value[0]
                if tag == "P" and len(value) > 1:
                    kind, target = promises.get(value[1], ("constant", None))
                    return hydrate(target) if kind == "index" else target
                if tag == "D" and len(value) > 1:
                    return value[1]  # Date, kept as its timestamp
                return None  # other types (Map, Set, RegExp...) are not needed here
            result_list: list = []
            memo[index] = result_list
            result_list.extend(hydrate(item) for item in value)
            return result_list
        return value

    return hydrate(0)


def find_key(data: Any, key: str) -> Any:
    """Return the first value stored under ``key`` anywhere in decoded data."""
    stack = [data]
    seen = set()
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        if isinstance(node, dict):
            if key in node and node[key] is not None:
                return node[key]
            stack.extend(reversed(list(node.values())))
        elif isinstance(node, list):
            stack.extend(reversed(node))
    return None
