#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shared state for the application
"""

# Standard library imports
import threading
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SharedState:
    """Shared state between threads"""
    phase: Optional[str] = None
    hovered_champ_id: Optional[int] = None
    locked_champ_id: Optional[int] = None
    locked_champ_timestamp: float = 0.0  # Time when champion was locked
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
    
    
    # Skin write config
    skin_write_ms: int = 2000
    injection_completed: bool = False  # Flag to prevent UI detection restart after injection
    inject_batch: Optional[str] = None
    
    # Chroma selection
    selected_chroma_id: Optional[int] = None  # Selected chroma ID (None = base skin)
    selected_form_path: Optional[str] = None  # Selected Form file path for Elementalist Lux
    pending_chroma_selection: bool = False  # Flag to indicate chroma panel is open
    
    # UI state management
    reset_skin_notification: bool = False  # Flag to reset skin notification debouncing
    chroma_panel_open: bool = False
    
    # Language detection
    current_language: Optional[str] = None  # Current client language (e.g., 'en', 'fr', 'de')
    
    # Game mode detection
    current_game_mode: Optional[str] = None  # Current game mode (ARAM, CLASSIC, SWIFT_PLAY, etc.)
    current_map_id: Optional[int] = None  # Current map ID (12 = ARAM, 11 = SR)
    current_queue_id: Optional[int] = None  # Current queue ID (2400 = ARAM, etc.)
    chroma_panel_skin_name: Optional[str] = None  # Base skin name when panel was opened (to avoid re-detecting same skin)
    is_swiftplay_mode: bool = False  # Flag to indicate if we're in Swiftplay mode
    
    # Swiftplay skin tracking - maps champion ID to last detected skin ID
    swiftplay_skin_tracking: dict = field(default_factory=dict)  # {champion_id: skin_id}
    swiftplay_extracted_mods: list = field(default_factory=list)  # List of extracted mod folder names for Swiftplay injection
    
    # UI Detection
    ui_last_text: Optional[str] = None  # Last detected skin name from UI
    ui_skin_id: Optional[int] = None  # Last detected skin ID from UI
    
    # Random skin selection
    random_skin_name: Optional[str] = None  # Selected random skin for injection
    random_skin_id: Optional[int] = None  # Selected random skin/chroma ID for injection
    random_mode_active: bool = False  # Tracks if randomization is active