#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LCU utility functions
"""

from typing import Dict, Any


def map_cells(sess: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    """Map cell IDs to player data"""
    idx: Dict[int, Dict[str, Any]] = {}
    for side in (sess.get("myTeam") or [], sess.get("theirTeam") or []):
        for p in side or []:
            cid = p.get("cellId")
            if cid is not None:
                idx[int(cid)] = p
    return idx


def compute_locked(sess: Dict[str, Any]) -> Dict[int, int]:
    """Compute locked champions by cell ID"""
    locked: Dict[int, int] = {}
    idx = map_cells(sess)
    
    for rnd in (sess.get("actions") or []):
        for a in rnd or []:
            if a.get("type") == "pick" and a.get("completed"):
                cid = a.get("actorCellId")
                ch = int(a.get("championId") or 0)
                if cid is not None:
                    if ch == 0:
                        p = idx.get(int(cid))
                        ch = int((p or {}).get("championId") or 0)
                    if ch > 0:
                        locked[int(cid)] = ch
    
    for cid, p in idx.items():
        ch = int(p.get("championId") or 0)
        if ch <= 0: 
            continue
        intent = int(p.get("championPickIntent") or p.get("pickIntentChampionId") or 0)
        is_intenting = bool(p.get("isPickIntenting") or False)
        if (intent == 0) and (not is_intenting):
            locked[cid] = ch
    
    return locked
