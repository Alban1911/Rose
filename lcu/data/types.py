#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Type definitions for LCU API responses
Provides TypedDict definitions for structured data
"""

from typing import TypedDict, List, Optional


class ChromaData(TypedDict, total=False):
    """Chroma data from LCU API"""
    id: int
    name: str
    chromaPath: str
    colors: List[str]
    disabled: bool
    ownership: dict


class SkinData(TypedDict, total=False):
    """Skin data from LCU API"""
    id: int
    skinId: int
    name: str
    skinName: str
    splashPath: Optional[str]
    uncenteredSplashPath: Optional[str]
    tilePath: Optional[str]
    loadScreenPath: Optional[str]
    chromas: List[ChromaData]
    isBase: bool
    ownership: dict
    disabled: bool


class ChampionData(TypedDict, total=False):
    """Champion data from LCU API"""
    id: int
    name: str
    alias: str
    squarePortraitPath: str
    roles: List[str]
    skins: List[SkinData]


class SessionData(TypedDict, total=False):
    """Champion select session data"""
    actions: List[List[dict]]
    myTeam: List[dict]
    theirTeam: List[dict]
    timer: dict
    localPlayerCellId: int
    isSpectating: bool


class LockfileData(TypedDict):
    """Lockfile parsed data"""
    name: str
    pid: int
    port: int
    password: str
    protocol: str
