#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Utils Package - Utility functions and helpers

This package is organized into subpackages:
- core: Core utilities (logging, paths, validation, etc.)
- system: System/OS-specific utilities (Windows, admin, window management)
- download: Download and network utilities (skin downloaders, hash management)
- integration: UI/System integration (tray, Pengu Loader)
- threading: Threading utilities
"""

# Import paths first (doesn't depend on config)
from utils.core.paths import (
    get_user_data_dir, get_appdata_dir, get_skins_dir,
    get_state_dir, get_injection_dir, get_app_dir, get_asset_path
)

# Lazy imports for modules that depend on config (to avoid circular imports)
# These will be imported on first access via __getattr__
def __getattr__(name):
    """Lazy import for modules that may have circular dependencies"""
    if name in {
        'get_logger', 'setup_logging', 'log_section', 'log_success',
        'log_status', 'get_log_mode', 'log_event', 'log_action'
    }:
        from utils.core.logging import (
            get_logger, setup_logging, log_section, log_success,
            log_status, get_log_mode, log_event, log_action
        )
        return locals()[name]
    
    if name in {
        'get_champion_id_from_skin_id', 'is_default_skin', 'is_owned',
        'is_chroma_id', 'get_base_skin_id_for_chroma', 'is_base_skin',
        'is_base_skin_owned', 'find_free_port'
    }:
        from utils.core.utilities import (
            get_champion_id_from_skin_id, is_default_skin, is_owned,
            is_chroma_id, get_base_skin_id_for_chroma, is_base_skin,
            is_base_skin_owned, find_free_port
        )
        return locals()[name]
    
    if name in {
        'validate_skin_id', 'validate_skin_name', 'validate_champion_id',
        'validate_positive_number', 'require_non_empty_list', 'validated_method'
    }:
        from utils.core.validation import (
            validate_skin_id, validate_skin_name, validate_champion_id,
            validate_positive_number, require_non_empty_list, validated_method
        )
        return locals()[name]
    
    if name in {'levenshtein_distance', 'levenshtein_score'}:
        from utils.core.normalization import levenshtein_distance, levenshtein_score
        return locals()[name]
    
    if name in {
        'load_historic_map', 'get_historic_skin_for_champion', 'write_historic_entry'
    }:
        from utils.core.historic import (
            load_historic_map, get_historic_skin_for_champion, write_historic_entry
        )
        return locals()[name]
    
    raise AttributeError(f"module 'utils' has no attribute '{name}'")

__all__ = [
    # Paths (eagerly imported)
    'get_user_data_dir', 'get_appdata_dir', 'get_skins_dir',
    'get_state_dir', 'get_injection_dir', 'get_app_dir', 'get_asset_path',
    # Logging (lazy)
    'get_logger', 'setup_logging', 'log_section', 'log_success',
    'log_status', 'get_log_mode', 'log_event', 'log_action',
    # Utilities (lazy)
    'get_champion_id_from_skin_id', 'is_default_skin', 'is_owned',
    'is_chroma_id', 'get_base_skin_id_for_chroma', 'is_base_skin',
    'is_base_skin_owned', 'find_free_port',
    # Validation (lazy)
    'validate_skin_id', 'validate_skin_name', 'validate_champion_id',
    'validate_positive_number', 'require_non_empty_list', 'validated_method',
    # Normalization (lazy)
    'levenshtein_distance', 'levenshtein_score',
    # Historic (lazy)
    'load_historic_map', 'get_historic_skin_for_champion', 'write_historic_entry',
]
