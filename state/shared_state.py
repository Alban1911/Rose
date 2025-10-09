#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shared state for the application
"""

import threading
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SharedState:
    """Shared state between threads"""
    phase: Optional[str] = None
    hovered_champ_id: Optional[int] = None
    locked_champ_id: Optional[int] = None
    locked_champ_timestamp: float = 0.0  # Time when champion was locked (for OCR delay)
    last_hovered_skin_key: Optional[str] = None
    last_hovered_skin_id: Optional[int] = None
    last_hovered_skin_slug: Optional[str] = None
    selected_skin_id: Optional[int] = None  # Skin ID selected in LCU (owned skin)
    owned_skin_ids: set = field(default_factory=set)  # All owned skin IDs from LCU inventory
    processed_action_ids: set = field(default_factory=set)
    stop: bool = False
    players_visible: int = 0
    locks_by_cell: dict[int, int] = field(default_factory=dict)
    all_locked_announced: bool = False
    local_cell_id: Optional[int] = None
    
    # Loadout timer
    loadout_countdown_active: bool = False
    loadout_t0: float = 0.0
    loadout_left0_ms: int = 0
    last_remain_ms: int = 0  # Remaining time in milliseconds
    last_hover_written: bool = False
    timer_lock: threading.Lock = field(default_factory=threading.Lock)
    ticker_seq: int = 0
    current_ticker: int = 0
    
    # OCR last raw text (exact string to write)
    ocr_last_text: Optional[str] = None
    
    # Skin write config
    skin_write_ms: int = 2000
    injection_completed: bool = False  # Flag to prevent OCR restart after injection
    inject_batch: Optional[str] = None
    
    # Chroma selection
    selected_chroma_id: Optional[int] = None  # Selected chroma ID (None = base skin)
    pending_chroma_selection: bool = False  # Flag to indicate chroma wheel is open