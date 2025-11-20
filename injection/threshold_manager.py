#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Threshold Manager
Handles injection threshold configuration and management
"""

from config import get_config_float

from utils.logging import get_logger

log = get_logger()


class ThresholdManager:
    """Manages injection threshold configuration"""
    
    def __init__(self, shared_state=None):
        """Initialize threshold manager
        
        Args:
            shared_state: Optional shared state for propagating threshold changes
        """
        self.shared_state = shared_state
        self.injection_threshold = get_config_float("General", "injection_threshold", 0.5)
        self._last_threshold_value = self.injection_threshold
    
    def refresh(self) -> float:
        """Reload injection threshold from config so tray changes apply immediately."""
        try:
            new_value = get_config_float("General", "injection_threshold", 0.5)
        except Exception as exc:  # noqa: BLE001
            log.debug(f"[INJECT] Failed to refresh injection threshold: {exc}")
            return self.injection_threshold

        # Allow 0 as a special case for no cooldown, but guard against negatives.
        new_value = max(0.0, float(new_value))

        if abs(new_value - self._last_threshold_value) < 1e-6:
            return self.injection_threshold

        self.injection_threshold = new_value
        self._last_threshold_value = new_value

        if self.shared_state is not None:
            try:
                self.shared_state.skin_write_ms = max(0, int(new_value * 1000))
            except Exception as exc:  # noqa: BLE001
                log.debug(f"[INJECT] Failed to propagate skin_write_ms update: {exc}")

        log.info(f"[INJECT] Injection threshold reloaded: {new_value:.2f}s")
        return self.injection_threshold

