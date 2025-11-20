#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
User Interface Manager - Parent class for all UI components
Manages ChromaUI and UnownedFrame as separate components
"""

# Standard library imports
import threading

# Local imports
from ui.chroma_ui import ChromaUI
from utils.logging import get_logger

from .historic_mode_handler import HistoricModeHandler
from .randomization_handler import RandomizationHandler
from .skin_display_handler import SkinDisplayHandler
from .ui_lifecycle_manager import UILifecycleManager

log = get_logger()


class UserInterface:
    """Parent class managing all UI components"""
    
    def __init__(self, state, skin_scraper):
        self.state = state
        self.skin_scraper = skin_scraper
        self.lock = threading.Lock()
        
        # Current skin tracking
        self.current_skin_id = None
        self.current_skin_name = None
        self.current_champion_name = None
        self.current_champion_id = None
        
        # Initialize handlers
        self.lifecycle_manager = UILifecycleManager(state, skin_scraper)
        self.historic_handler = HistoricModeHandler(state)
        self.randomization_handler = RandomizationHandler(state, skin_scraper)
        self.skin_display_handler = None  # Will be initialized when chroma_ui is created
    
    # Legacy methods - no-op for compatibility
    def create_click_catchers(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def _try_show_click_blocker(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def _show_click_blocker_on_main_thread(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def _hide_click_blocker_with_delay(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def create_click_catchers_for_finalization(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def show_skin(self, skin_id: int, skin_name: str, champion_name: str = None, champion_id: int = None):
        """Show UI for a specific skin - manages both ChromaUI and UnownedFrame"""
        if not self.is_ui_initialized():
            log.debug("[UI] Cannot show skin - UI not initialized")
            return
        
        with self.lock:
            # Prevent duplicate processing of the same skin
            if (self.current_skin_id == skin_id and 
                self.current_skin_name == skin_name and 
                self.current_champion_name == champion_name):
                log.debug(f"[UI] Skipping duplicate skin: {skin_name} (ID: {skin_id})")
                return
            
            # Update current skin tracking
            self.current_skin_id = skin_id
            self.current_skin_name = skin_name
            self.current_champion_name = champion_name
            self.current_champion_id = champion_id
            
            # Show skin using display handler
            # Ensure display handler has chroma_ui reference
            if not self.skin_display_handler and self.lifecycle_manager.chroma_ui:
                from .skin_display_handler import SkinDisplayHandler
                self.skin_display_handler = SkinDisplayHandler(
                    self.state, self.skin_scraper, self.lifecycle_manager.chroma_ui
                )
            
            if self.skin_display_handler:
                # Update chroma_ui reference if it changed
                if self.skin_display_handler.chroma_ui != self.lifecycle_manager.chroma_ui:
                    self.skin_display_handler.chroma_ui = self.lifecycle_manager.chroma_ui
                
                new_base_skin_id, prev_base_skin_id = self.skin_display_handler.show_skin(
                    skin_id, skin_name, champion_name, champion_id,
                    self.current_skin_id, self.current_skin_name, self.current_champion_name
                )
            else:
                new_base_skin_id = None
                prev_base_skin_id = None
            
            # Cancel randomization if skin changed and random mode is active
            if self.state.random_mode_active and not self.randomization_handler.randomization_in_progress:
                self.randomization_handler.cancel()
            
            # Always reset randomization flags if skin changed
            self.randomization_handler.reset_on_skin_change()
            
            # Broadcast dice button state to JavaScript
            self.randomization_handler.update_dice_button(self.current_skin_id)
            
            # Historic mode activation: check on first skin detection if champion is locked with default skin
            self.historic_handler.check_and_activate(skin_id)
            
            # Historic mode deactivation: if skin changes from default to non-default, deactivate historic mode
            if new_base_skin_id is not None:
                self.historic_handler.check_and_deactivate(skin_id, new_base_skin_id)
    
    def hide_all(self):
        """Hide all UI components"""
        with self.lock:
            if not self.is_ui_initialized():
                log.debug("[UI] Cannot hide - UI not initialized")
                return
            log.info("[UI] Hiding all UI components")
            if self.skin_display_handler:
                self.skin_display_handler._hide_chroma_ui()
    
    def _schedule_hide_all_on_main_thread(self):
        """Schedule hide_all() to run on the main thread"""
        try:
            # Use threading.Timer to schedule on main thread
            timer = threading.Timer(0.0, self.hide_all)
            timer.daemon = True
            timer.start()
            log.debug("[UI] hide_all() scheduled on main thread")
        except Exception as e:
            log.warning(f"[UI] Failed to schedule hide_all on main thread: {e}")
    
    def check_resolution_and_update(self):
        """Check for resolution changes and update UI components accordingly"""
        try:
            # Check ChromaUI for resolution changes (it handles its own resolution checking)
            if self.lifecycle_manager.chroma_ui:
                # ChromaUI components handle their own resolution checking
                pass
        except Exception as e:
            log.error(f"[UI] Error checking resolution changes: {e}")
            import traceback
            log.error(traceback.format_exc())
    
    def is_ui_initialized(self):
        """Check if UI components are initialized"""
        return self.lifecycle_manager.is_ui_initialized()
    
    def request_ui_initialization(self):
        """Request UI initialization (called from any thread)"""
        self.lifecycle_manager.request_ui_initialization()
    
    def process_pending_operations(self):
        """Process pending UI operations (must be called from main thread)"""
        # Update skin_scraper in lifecycle manager if it changed
        if self.skin_scraper is not None and self.lifecycle_manager.skin_scraper != self.skin_scraper:
            self.lifecycle_manager.skin_scraper = self.skin_scraper
        
        initialized = self.lifecycle_manager.process_pending_operations()
        # Update skin display handler reference after initialization
        if initialized and self.lifecycle_manager.chroma_ui and not self.skin_display_handler:
            from .skin_display_handler import SkinDisplayHandler
            self.skin_display_handler = SkinDisplayHandler(
                self.state, self.skin_scraper, self.lifecycle_manager.chroma_ui
            )
            # Update chroma_ui reference in display handler if it was already created
            if self.skin_display_handler:
                self.skin_display_handler.chroma_ui = self.lifecycle_manager.chroma_ui
    
    def request_ui_destruction(self):
        """Request UI destruction (called from any thread)"""
        self.lifecycle_manager.request_ui_destruction()
    
    def has_pending_operations(self):
        """Check if there are pending UI operations"""
        return self.lifecycle_manager.has_pending_operations()
    
    def destroy_ui(self):
        """Destroy UI components (must be called from main thread)"""
        self.lifecycle_manager.destroy_ui()
        # Clear skin display handler reference
        self.skin_display_handler = None
    
    def _handle_dice_click_disabled(self):
        """Handle dice button click in disabled state - start randomization"""
        if self.randomization_handler.handle_dice_click_disabled(self.current_skin_id):
            return
        
        # Need to force base skin first
        lcu = self.skin_scraper.lcu if self.skin_scraper and hasattr(self.skin_scraper, 'lcu') else None
        if lcu:
            self.randomization_handler.force_base_skin_and_randomize(lcu)
    
    def _handle_dice_click_enabled(self):
        """Handle dice button click in enabled state - cancel randomization"""
        self.randomization_handler.handle_dice_click_enabled()
    
    def reset_skin_state(self):
        """Reset all skin-related state for new ChampSelect"""
        with self.lock:
            # Reset current skin tracking
            self.current_skin_id = None
            self.current_skin_name = None
            self.current_champion_name = None
            self.current_champion_id = None
            
            # Reset UI detection state
            self.last_skin_name = None
            self.last_skin_id = None
            
            # Reset randomization state
            self.randomization_handler.randomization_started = False
            
            # Force UI recreation for new ChampSelect
            self.lifecycle_manager.reset_skin_state()
            
            log.debug("[UI] Skin state reset for new ChampSelect")
    
    # Legacy methods - no-op for compatibility
    def _show_unowned_frame(self, skin_id: int, skin_name: str, champion_name: str = None, is_same_base_chroma: bool = False):
        """Legacy method - no-op for compatibility."""
        pass
    
    def _hide_unowned_frame(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def _on_click_catcher_hide_clicked(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def _on_click_catcher_clicked(self, instance_name: str):
        """Legacy method - no-op for compatibility."""
        pass
    
    def _create_show_instances_for_panel(self, panel_name: str):
        """Legacy method - no-op for compatibility."""
        pass
    
    def _destroy_all_show_instances(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def _hide_all_ui_elements(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def _show_all_ui_elements(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def show_click_catcher_hide(self, x, y, width=50, height=50):
        """Legacy method - no-op for compatibility."""
        pass
    
    def hide_click_catcher_hide(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def show_click_catcher(self, instance_name: str):
        """Legacy method - no-op for compatibility."""
        pass
    
    def hide_click_catcher(self, instance_name: str):
        """Legacy method - no-op for compatibility."""
        pass
    
    def show_all_click_catchers(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def hide_all_click_catchers(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def _show_click_catchers(self):
        """Legacy method - no-op for compatibility."""
        pass
    
    def cleanup(self):
        """Clean up all UI components"""
        with self.lock:
            if self.lifecycle_manager.chroma_ui:
                self.lifecycle_manager.chroma_ui.cleanup()
            log.info("[UI] All UI components cleaned up")
    
    # Backward compatibility properties
    @property
    def chroma_ui(self):
        """Get chroma_ui instance (for backward compatibility)"""
        return self.lifecycle_manager.chroma_ui
    
    @property
    def _force_reinitialize(self) -> bool:
        """Get force reinitialize flag (for backward compatibility)"""
        return self.lifecycle_manager.force_reinitialize
    
    @_force_reinitialize.setter
    def _force_reinitialize(self, value: bool):
        """Set force reinitialize flag (for backward compatibility)"""
        self.lifecycle_manager.force_reinitialize = value
    
    @property
    def _pending_ui_initialization(self) -> bool:
        """Get pending UI initialization flag (for backward compatibility)"""
        return self.lifecycle_manager._pending_ui_initialization
    
    @_pending_ui_initialization.setter
    def _pending_ui_initialization(self, value: bool):
        """Set pending UI initialization flag (for backward compatibility)"""
        self.lifecycle_manager._pending_ui_initialization = value


# Global UI instance
_user_interface = None


def get_user_interface(state=None, skin_scraper=None) -> UserInterface:
    """Get or create global user interface instance"""
    global _user_interface
    if _user_interface is None:
        _user_interface = UserInterface(state, skin_scraper)
    else:
        # Update the existing instance with new parameters if they were provided
        if state is not None and _user_interface.state != state:
            _user_interface.state = state
        if skin_scraper is not None and _user_interface.skin_scraper != skin_scraper:
            _user_interface.skin_scraper = skin_scraper
            # Also update lifecycle manager's skin_scraper
            if _user_interface.lifecycle_manager:
                _user_interface.lifecycle_manager.skin_scraper = skin_scraper
    return _user_interface
