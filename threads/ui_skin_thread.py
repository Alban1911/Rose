#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UI skin detection thread - Windows UI Automation API
"""

import time
import threading
import logging
from typing import Optional, List, Dict, Any
import uiautomation as auto
from database.name_db import NameDB
from state.shared_state import SharedState
from lcu.client import LCU
from utils.normalization import levenshtein_score
from utils.logging import get_logger
from utils.chroma_selector import get_chroma_selector
from config import UI_POLL_INTERVAL, UI_DETECTION_TIMEOUT

# Suppress uiautomation/comtypes debug messages
logging.getLogger('comtypes').setLevel(logging.WARNING)
logging.getLogger('uiautomation').setLevel(logging.WARNING)

log = get_logger()


class UISkinThread(threading.Thread):
    """Thread for monitoring skin names using Windows UI Automation API"""
    
    def __init__(self, state: SharedState, db: NameDB, lcu: Optional[LCU] = None, 
                 skin_scraper=None, injection_manager=None, interval: float = UI_POLL_INTERVAL, 
                 mousehover_debug: bool = False):
        super().__init__(daemon=True)
        self.state = state
        self.db = db
        self.lcu = lcu
        self.skin_scraper = skin_scraper
        self.injection_manager = injection_manager
        self.interval = interval
        self.mousehover_debug = mousehover_debug
        
        # UI detection state
        self.league_window = None
        self.skin_elements = []
        self.skin_name_element = None  # Focus on the specific skin name element
        self.last_detected_skin_name = None
        self.last_detected_skin_id = None
        self.last_detected_skin_key = None
        
        # Chroma panel state
        self.last_chroma_panel_skin_id = None
        self.last_detected_skin_id_for_fade = None
        self.first_skin_detected = False
        self.last_skin_had_chromas = False
        self.last_skin_was_owned = False
        self.chroma_operations_running = False  # Flag to prevent too many chroma threads
        self.last_chroma_operation_time = 0.0  # Track last chroma operation time
        
        # Detection state flags
        self.detection_available = False
        self.last_detection_attempt = 0.0
        
        # Mouse hover debugging
        self.last_mouse_position = None
        self.last_mouse_debug_time = 0.0
        
    def find_league_client(self) -> bool:
        """Find the League of Legends client window."""
        try:
            self.league_window = auto.WindowControl(Name="League of Legends")
            if self.league_window.Exists():
                log.debug("League of Legends client found!")
                return True
            else:
                log.debug("League of Legends client not found")
                return False
        except Exception as e:
            log.debug(f"Error finding League client: {e}")
            return False
    
    
    def _find_skin_name_element(self):
        """Find the specific skin name element at the exact known position - optimized for parallel execution."""
        try:
            log.debug("Getting skin name element at exact position...")
            
            # Get window dimensions and position (non-blocking)
            window_rect = self.league_window.BoundingRectangle
            window_width = window_rect.width()
            window_height = window_rect.height()
            window_left = window_rect.left
            window_top = window_rect.top
            
            # Calculate center position relative to window (this is consistent!)
            center_x = int(window_width * 0.5)  # 50% of window width - CENTER
            center_y = int(window_height * 0.658)  # 65.8% of window height - CENTER
            
            # Convert to screen coordinates
            target_center_x = window_left + center_x
            target_center_y = window_top + center_y
            
            log.debug(f"Looking for TextControl centered at ({target_center_x}, {target_center_y})")
            
            # Search in a horizontal line pattern from the center (most efficient)
            # Y is constant, so we only need small Y range but large X range for text length variation
            # Skin names are positioned to the left of center, so search more left than right
            search_offsets = [
                (0, 0),      # Center
                (-10, 0), (10, 0), (0, -5), (0, 5),    # Small cross
                (-20, 0), (20, 0), (0, -10), (0, 10),  # Medium cross
                (-30, 0), (20, 0),                      # Large horizontal (more left)
                (-40, 0), (20, 0),                      # Extra large horizontal (more left)
                (-50, 0), (20, 0),                      # Maximum horizontal (more left)
                (-60, 0), (20, 0),                      # Extended horizontal (more left)
                (-70, 0), (20, 0),                      # Full range horizontal (more left)
                (-80, 0), (20, 0),                      # Extended left range
                (-90, 0), (20, 0),                      # Maximum left range
                (-100, 0), (20, 0),                     # Full left range
                (-110, 0), (20, 0),                     # Extended left range
                (-120, 0), (20, 0),                     # Maximum left range
            ]
            
            for offset_x, offset_y in search_offsets:
                try:
                    test_x = target_center_x + offset_x
                    test_y = target_center_y + offset_y
                    control = auto.ControlFromPoint(test_x, test_y)
                    
                    if control and control.ControlTypeName == "TextControl" and control.FrameworkId == "Chrome":
                        log.info(f"Found TextControl at center+offset ({test_x}, {test_y}): '{control.Name}'")
                        return control
                    elif control:
                        log.debug(f"At ({test_x}, {test_y}): {control.ControlTypeName} - {control.FrameworkId}")
                except Exception as e:
                    log.debug(f"Error at ({test_x}, {test_y}): {e}")
                    continue
            
            # Fallback: if horizontal pattern fails, try a focused grid (wide left X, narrow right X, narrow Y)
            log.debug(f"Horizontal pattern failed, trying focused grid around center ({target_center_x}, {target_center_y})")
            for offset_x in range(-120, 21, 5):  # -120 to +20 in steps of 5 (wide left, narrow right)
                for offset_y in range(-10, 11, 5):  # -10 to +10 in steps of 5 (narrow Y range)
                    try:
                        test_x = target_center_x + offset_x
                        test_y = target_center_y + offset_y
                        control = auto.ControlFromPoint(test_x, test_y)
                        if control and control.ControlTypeName == "TextControl" and control.FrameworkId == "Chrome":
                            log.info(f"Found TextControl in focused grid at ({test_x}, {test_y}): '{control.Name}'")
                            return control
                    except Exception:
                        continue
            
            log.debug("No TextControl found at skin name position")
            return None
            
        except Exception as e:
            log.debug(f"Error finding skin name element: {e}")
            return None
    
    def _debug_mouse_hover(self):
        """Debug mouse hover - show all UI element information at cursor position"""
        if not self.mousehover_debug:
            return
        
        try:
            import win32gui
            import win32api
            
            # Get current mouse position
            x, y = win32gui.GetCursorPos()
            current_pos = (x, y)
            
            # Only debug if mouse moved or enough time passed
            now = time.time()
            if current_pos == self.last_mouse_position and (now - self.last_mouse_debug_time) < 0.5:
                return
            
            self.last_mouse_position = current_pos
            self.last_mouse_debug_time = now
            
            log.debug(f"[MOUSE] Debugging mouse position: ({x}, {y})")
            
            # Get control at mouse position
            control = auto.ControlFromPoint(x, y)
            
            if control:
                log.info("=" * 80)
                log.info(f"🖱️  MOUSE HOVER DEBUG at ({x}, {y})")
                log.info("=" * 80)
                
                # Basic properties
                log.info(f"Control Type: {control.ControlTypeName}")
                log.info(f"Framework: {control.FrameworkId}")
                log.info(f"Name: '{control.Name}'")
                log.info(f"Automation ID: '{getattr(control, 'AutomationId', 'N/A')}'")
                log.info(f"Class Name: '{getattr(control, 'ClassName', 'N/A')}'")
                log.info(f"Process ID: {getattr(control, 'ProcessId', 'N/A')}")
                log.info(f"Runtime ID: {getattr(control, 'RuntimeId', 'N/A')}")
                
                # Bounding rectangle
                try:
                    rect = control.BoundingRectangle
                    if rect:
                        log.info(f"Bounding Rectangle: ({rect.left}, {rect.top}, {rect.right}, {rect.bottom})")
                        log.info(f"Size: {rect.width()}x{rect.height()}")
                    else:
                        log.info("Bounding Rectangle: Not available")
                except Exception as e:
                    log.info(f"Bounding Rectangle: Error - {e}")
                
                # Parent information
                try:
                    parent = control.GetParentControl()
                    if parent:
                        log.info(f"Parent Type: {parent.ControlTypeName}")
                        log.info(f"Parent Name: '{parent.Name}'")
                        log.info(f"Parent Framework: {parent.FrameworkId}")
                    else:
                        log.info("Parent: None")
                except Exception as e:
                    log.info(f"Parent: Error - {e}")
                
                # Children count
                try:
                    children = control.GetChildren()
                    log.info(f"Children Count: {len(children)}")
                    if len(children) > 0:
                        log.info("Children Types:")
                        for i, child in enumerate(children[:5]):  # Show first 5 children
                            try:
                                log.info(f"  [{i}] {child.ControlTypeName} - '{child.Name}'")
                            except:
                                log.info(f"  [{i}] <error getting child info>")
                        if len(children) > 5:
                            log.info(f"  ... and {len(children) - 5} more children")
                except Exception as e:
                    log.info(f"Children: Error - {e}")
                
                # Additional properties
                try:
                    properties = [
                        'IsEnabled', 'IsOffscreen', 'IsKeyboardFocusable', 'IsPassword',
                        'HasKeyboardFocus', 'IsContentElement', 'IsControlElement'
                    ]
                    log.info("Additional Properties:")
                    for prop in properties:
                        try:
                            value = getattr(control, prop, None)
                            if value is not None:
                                log.info(f"  {prop}: {value}")
                        except:
                            pass
                except Exception as e:
                    log.info(f"Additional Properties: Error - {e}")
                
                log.info("=" * 80)
            else:
                log.info(f"🖱️  MOUSE HOVER DEBUG at ({x}, {y}): No control found")
                
        except Exception as e:
            log.debug(f"Mouse hover debug error: {e}")
    
    def _find_text_control_at_position(self, parent_control, target_x, target_y):
        """Find a TextControl at the specific position within a parent control."""
        try:
            # Get all TextControls within the parent using recursive search
            text_controls = []
            self._collect_text_controls_recursive(parent_control, text_controls, 0)
            
            log.debug(f"Found {len(text_controls)} TextControls within DocumentControl")
            
            # Find the one closest to our target position
            closest_control = None
            closest_distance = float('inf')
            
            for text_control in text_controls:
                try:
                    rect = text_control.BoundingRectangle
                    if not rect:
                        continue
                    
                    # Calculate distance from target position to control center
                    control_x = rect.xcenter()
                    control_y = rect.ycenter()
                    distance = ((control_x - target_x) ** 2 + (control_y - target_y) ** 2) ** 0.5
                    
                    # Check if this control is closer and within reasonable distance
                    if distance < closest_distance and distance < 100:  # Within 100 pixels
                        closest_control = text_control
                        closest_distance = distance
                        
                except Exception:
                    continue
            
            if closest_control:
                log.debug(f"Found closest TextControl at distance {closest_distance:.1f}px: '{closest_control.Name}'")
                return closest_control
            
            log.debug("No TextControl found within 100px of target position")
            return None
            
        except Exception as e:
            log.debug(f"Error finding TextControl at position: {e}")
            return None
    
    def _collect_text_controls_recursive(self, control, text_controls, depth):
        """Recursively collect TextControls from a parent control."""
        if depth > 10:  # Limit depth to prevent infinite recursion
            return
            
        try:
            # Check if this control is a TextControl
            if control.ControlTypeName == "TextControl" and control.FrameworkId == "Chrome":
                text_controls.append(control)
            
            # Get children and recurse
            children = control.GetChildren()
            for child in children:
                self._collect_text_controls_recursive(child, text_controls, depth + 1)
                
        except Exception:
            pass  # Continue with other children
    
    
    def _log_detailed_skin_info(self, control, skin_name):
        """Log basic information about a skin control."""
        try:
            log.info(f"Found skin: '{skin_name}'")
            
        except Exception as e:
            log.error(f"Error logging detailed skin info: {e}")
    
    def find_skin_elements_in_league(self):
        """Find the specific skin name element at exact position and lock onto it for monitoring."""
        import time
        start_time = time.time()
        
        log.debug("Starting direct position-based skin detection...")
        
        if not self.league_window:
            log.debug("No client window reference")
            return []
            
        if not self.league_window.Exists():
            log.debug("League client window doesn't exist")
            return []
        
        log.debug("League client window found and exists")
        
        try:
            # Get the skin name element directly at the exact position
            skin_name_element = self._find_skin_name_element()
            
            if skin_name_element:
                # Store reference to the skin name element
                self.skin_name_element = skin_name_element
                elapsed_time = (time.time() - start_time) * 1000
                log.debug(f"Found skin name element: '{skin_name_element.Name}' in {elapsed_time:.2f}ms")
                return [skin_name_element]  # Return as list for compatibility
            else:
                elapsed_time = (time.time() - start_time) * 1000
                log.debug(f"No skin name element found at position in {elapsed_time:.2f}ms")
                return []
            
        except Exception as e:
            log.debug(f"Error in direct position detection: {e}")
            return []
    
    def _should_run_detection(self) -> bool:
        """Check if UI detection should be running based on conditions"""
        # Must be in ChampSelect
        if self.state.phase != "ChampSelect":
            return False
        
        # Must have locked a champion
        locked_champ = getattr(self.state, "locked_champ_id", None)
        if not locked_champ:
            return False
        
        # Wait after champion lock before starting detection
        locked_timestamp = getattr(self.state, "locked_champ_timestamp", 0.0)
        if locked_timestamp > 0:
            time_since_lock = time.time() - locked_timestamp
            if time_since_lock < 0.1:  # 100ms delay after lock
                return False
        
        # Stop detection if injection has been completed
        if getattr(self.state, 'injection_completed', False):
            return False
        
        # Stop detection if we're within the injection threshold
        if (getattr(self.state, 'loadout_countdown_active', False) and 
            hasattr(self.state, 'current_ticker')):
            
            threshold_ms = int(getattr(self.state, 'skin_write_ms', 300) or 300)
            
            if hasattr(self.state, 'last_remain_ms'):
                remain_ms = getattr(self.state, 'last_remain_ms', 0)
                if remain_ms <= threshold_ms:
                    return False
        
        return True
    
    def _skin_has_displayable_chromas(self, skin_id: int) -> bool:
        """Check if skin has chromas that should show the button"""
        try:
            chroma_selector = get_chroma_selector()
            if chroma_selector:
                return chroma_selector.should_show_chroma_panel(skin_id)
        except Exception:
            pass
        return False
    
    def _queue_chroma_operations(self, skin_id: int, skin_name: str, has_chromas: bool, is_owned: bool):
        """Queue chroma operations to avoid blocking the UI thread"""
        try:
            # Throttle chroma operations to prevent overwhelming the UI
            current_time = time.time()
            if current_time - self.last_chroma_operation_time < 0.1:  # 100ms throttle
                return
            
            # Prevent too many chroma operation threads
            if self.chroma_operations_running:
                return
            
            self.chroma_operations_running = True
            self.last_chroma_operation_time = current_time
            
            # Use a separate thread to handle chroma operations
            def run_chroma_operations():
                try:
                    # Small delay to prevent overwhelming the UI thread
                    time.sleep(0.01)  # 10ms delay
                    self._trigger_chroma_panel(skin_id, skin_name)
                    self._trigger_chroma_fade(skin_id, has_chromas, is_owned)
                except Exception as e:
                    log.debug(f"Error in chroma operations thread: {e}")
                finally:
                    self.chroma_operations_running = False
            
            # Start chroma operations in a separate daemon thread
            chroma_thread = threading.Thread(target=run_chroma_operations, daemon=True, name="ChromaOperations")
            chroma_thread.start()
        except Exception as e:
            log.debug(f"Error queuing chroma operations: {e}")
            self.chroma_operations_running = False
    
    def _trigger_chroma_panel(self, skin_id: int, skin_name: str):
        """Trigger chroma panel display if skin has any chromas (owned or unowned)"""
        try:
            chroma_selector = get_chroma_selector()
            if not chroma_selector:
                return
            
            # Load owned skins on-demand if not already loaded
            if len(self.state.owned_skin_ids) == 0 and self.lcu and self.lcu.ok:
                try:
                    owned_skins = self.lcu.owned_skins()
                    if owned_skins and isinstance(owned_skins, list):
                        self.state.owned_skin_ids = set(owned_skins)
                        log.debug(f"Loaded {len(self.state.owned_skin_ids)} owned skins on-demand")
                except Exception as e:
                    log.debug(f"Failed to load owned skins: {e}")
            
            # Check if user owns the skin
            is_base_skin = (skin_id % 1000) == 0
            is_owned = is_base_skin or (skin_id in self.state.owned_skin_ids)
            log.debug(f"Checking skin_id={skin_id}, is_base={is_base_skin}, owned={is_owned}")
            
            # Button should show for ALL unowned skins (with or without chromas)
            if not is_owned:
                log.debug(f"Showing button - skin NOT owned (chromas: {chroma_selector.should_show_chroma_panel(skin_id)})")
                self.last_chroma_panel_skin_id = skin_id
                
                # Get champion name for direct path to chromas
                champ_id = self.state.locked_champ_id or self.state.hovered_champ_id
                champion_name = None
                if champ_id and self.db:
                    champion_name = self.db.champ_name_by_id.get(champ_id)
                    if not champion_name and hasattr(self.db, 'champ_name_by_id_by_lang'):
                        english_names = self.db.champ_name_by_id_by_lang.get('en_US', {})
                        champion_name = english_names.get(champ_id)
                
                chroma_selector.show_button_for_skin(skin_id, skin_name, champion_name)
            else:
                # Owned skin - only show button if it has chromas
                if chroma_selector.should_show_chroma_panel(skin_id):
                    log.debug(f"Showing button - owned skin with chromas")
                    self.last_chroma_panel_skin_id = skin_id
                    
                    champ_id = self.state.locked_champ_id or self.state.hovered_champ_id
                    champion_name = None
                    if champ_id and self.db:
                        champion_name = self.db.champ_name_by_id.get(champ_id)
                        if not champion_name and hasattr(self.db, 'champ_name_by_id_by_lang'):
                            english_names = self.db.champ_name_by_id_by_lang.get('en_US', {})
                            champion_name = english_names.get(champ_id)
                    
                    chroma_selector.show_button_for_skin(skin_id, skin_name, champion_name)
                else:
                    log.debug(f"Owned skin without chromas - hiding button")
                    chroma_selector.hide()
                    self.last_chroma_panel_skin_id = None
        except Exception as e:
            log.debug(f"Error triggering panel: {e}")
    
    def _trigger_chroma_fade(self, skin_id: int, current_has_chromas: bool, current_is_owned: bool):
        """Trigger chroma button and icon fade animations based on state transitions"""
        try:
            # Check if skin actually changed
            if skin_id == self.last_detected_skin_id_for_fade:
                return  # Same skin, no fade needed
            
            # Update last detected skin
            previous_skin_id = self.last_detected_skin_id_for_fade
            self.last_detected_skin_id_for_fade = skin_id
            
            chroma_selector = get_chroma_selector()
            
            # Check if widgets are initialized
            if chroma_selector and chroma_selector.panel:
                if not chroma_selector.panel.reopen_button:
                    # Widgets not created yet - queue the initial fade if needed
                    if not self.first_skin_detected:
                        log.debug(f"First skin detected but widgets not ready")
                        if not current_is_owned:
                            log.debug(f"First skin NOT owned - queueing UnownedFrame fade")
                            chroma_selector.panel.request_initial_unowned_fade()
                        else:
                            log.debug(f"First skin owned - no UnownedFrame fade needed")
                        self.first_skin_detected = True
                        self.last_skin_had_chromas = current_has_chromas
                        self.last_skin_was_owned = current_is_owned
                    return
                
                button = chroma_selector.panel.reopen_button
                
                if not self.first_skin_detected:
                    # First skin of the session
                    log.debug(f"First skin detected - no button animation")
                    self.first_skin_detected = True
                    self.last_skin_had_chromas = current_has_chromas
                    self.last_skin_was_owned = current_is_owned
                    
                    # For UnownedFrame: only fade in if first skin is NOT owned
                    if not current_is_owned:
                        log.debug(f"UnownedFrame: First skin NOT owned - fade in")
                        button.unowned_frame_fade_owned_to_not_owned_first()
                    else:
                        log.debug(f"UnownedFrame: First skin owned - stay at 0%")
                else:
                    # Determine button animation based on chroma state transition
                    prev_had_chromas = self.last_skin_had_chromas
                    curr_has_chromas = current_has_chromas
                    
                    if prev_had_chromas and curr_has_chromas:
                        # Has → Has: fade out 50ms, wait 100ms, fade in 50ms
                        log.debug(f"Button: Chromas → Chromas: fade out → wait → fade in")
                        button.fade_has_to_has()
                    elif not prev_had_chromas and curr_has_chromas:
                        # None → Has: wait 150ms, fade in 50ms
                        log.debug(f"Button: No chromas → Chromas: wait → fade in")
                        button.fade_none_to_has()
                    elif prev_had_chromas and not curr_has_chromas:
                        # Has → None: fade out 50ms
                        log.debug(f"Button: Chromas → No chromas: fade out")
                        button.fade_has_to_none()
                    else:
                        # None → None: nothing
                        log.debug(f"Button: No chromas → No chromas: no animation")
                    
                    self.last_skin_had_chromas = curr_has_chromas
                    
                    # Determine UnownedFrame animation based on ownership state transition
                    prev_was_owned = self.last_skin_was_owned
                    curr_is_owned = current_is_owned
                    
                    if not prev_was_owned and not curr_is_owned:
                        # Unowned → Unowned: fade out 50ms, wait 100ms, fade in 50ms
                        log.debug(f"UnownedFrame: Unowned → Unowned: fade out → wait → fade in")
                        button.unowned_frame_fade_not_owned_to_not_owned()
                    elif prev_was_owned and not curr_is_owned:
                        # Owned → Unowned: wait 150ms, fade in 50ms
                        log.debug(f"UnownedFrame: Owned → Unowned: wait → fade in (show lock)")
                        button.unowned_frame_fade_owned_to_not_owned()
                    elif not prev_was_owned and curr_is_owned:
                        # Unowned → Owned: fade out 50ms
                        log.debug(f"UnownedFrame: Unowned → Owned: fade out (hide lock)")
                        button.unowned_frame_fade_not_owned_to_owned()
                    else:
                        # Owned → Owned: nothing
                        log.debug(f"UnownedFrame: Owned → Owned: no animation")
                    
                    self.last_skin_was_owned = curr_is_owned
                    
        except Exception as e:
            log.debug(f"Failed to trigger fade: {e}")
    
    def _match_skin_name(self, detected_name: str) -> Optional[tuple]:
        """Match detected skin name against database"""
        champ_id = self.state.hovered_champ_id or self.state.locked_champ_id
        
        if not champ_id:
            return None
        
        # Get champion slug
        champ_slug = self.db.slug_by_id.get(champ_id)
        if not champ_slug:
            return None
        
        # Load champion skins if not already loaded
        if champ_slug not in self.db.champion_skins:
            self.db.load_champion_skins_by_id(champ_id)
        
        # Match against English skin names
        best_match = None
        best_similarity = 0.0
        
        available_skins = self.db.champion_skins.get(champ_slug, {})
        
        for skin_id, skin_name in available_skins.items():
            similarity = levenshtein_score(detected_name, skin_name)
            if similarity > best_similarity and similarity >= 0.3:  # 30% threshold
                best_match = (skin_id, skin_name, similarity)
                best_similarity = similarity
        
        return best_match
    
    def _should_update_hovered_skin(self, detected_skin_name: str) -> bool:
        """Check if we should update the hovered skin based on panel state"""
        # If panel is currently open, don't update
        if getattr(self.state, 'chroma_panel_open', False):
            return False
        
        # Check if we just closed the panel and detected the same base skin
        panel_skin_name = getattr(self.state, 'chroma_panel_skin_name', None)
        if panel_skin_name is not None:
            if detected_skin_name.startswith(panel_skin_name):
                log.debug(f"Skipping update - same base skin as panel (base: '{panel_skin_name}', detected: '{detected_skin_name}')")
                self.state.chroma_panel_skin_name = None
                return False
            else:
                self.state.chroma_panel_skin_name = None
        
        return True
    
    def monitor_skin_changes(self):
        """Monitor the focused skin name element for changes - optimized for parallel execution"""
        if not self.skin_name_element:
            return
        
        try:
            # Quick check if the skin name element still exists (non-blocking)
            if not self.skin_name_element.Exists():
                log.debug("Skin name element no longer exists, need to re-find it")
                self.skin_name_element = None
                return
            
            # Get the current name from the element (non-blocking)
            name = self.skin_name_element.Name
            if not name or not name.strip():
                return
            
            # Check if this is a new skin detection
            if name != self.last_detected_skin_name:
                log.info(f"UI Detection: {name}")
                
                # Special detailed logging for "Darius biosoldat"
                if "Darius biosoldat" in name or "biosoldat" in name.lower():
                    self._log_detailed_skin_info(self.skin_name_element, name)
                
                # Check if we should update (non-blocking)
                if not self._should_update_hovered_skin(name):
                    return
                
                # Match against database (non-blocking)
                match_result = self._match_skin_name(name)
                if match_result:
                    skin_id, skin_name, similarity = match_result
                    
                    # Update state (non-blocking)
                    self.state.last_hovered_skin_name = skin_name
                    self.state.last_hovered_skin_id = skin_id
                    self.state.last_hovered_champ_id = self.state.locked_champ_id
                    self.state.last_hovered_champ_slug = self.db.slug_by_id.get(self.state.locked_champ_id)
                    self.state.hovered_skin_timestamp = time.time()
                    
                    # Check if current skin has chromas (non-blocking)
                    has_chromas = self._skin_has_displayable_chromas(skin_id)
                    
                    # Calculate is_owned (non-blocking)
                    is_base_skin = (skin_id % 1000) == 0
                    is_owned = is_base_skin or (skin_id in self.state.owned_skin_ids)
                    
                    # Queue chroma operations to avoid blocking the UI thread
                    self._queue_chroma_operations(skin_id, skin_name, has_chromas, is_owned)
                    
                    # Log detection (non-blocking)
                    log.info("=" * 80)
                    if is_base_skin:
                        log.info(f"🎨 SKIN DETECTED >>> {skin_name.upper()} <<<")
                        log.info(f"   📋 Champion: {self.state.last_hovered_champ_slug} | SkinID: 0 (Base) | Match: {similarity:.1%}")
                        log.info(f"   🔍 Source: Windows UI API")
                    else:
                        log.info(f"🎨 SKIN DETECTED >>> {skin_name.upper()} <<<")
                        log.info(f"   📋 Champion: {self.state.last_hovered_champ_slug} | SkinID: {skin_id} | Match: {similarity:.1%}")
                        log.info(f"   🔍 Source: Windows UI API")
                    log.info("=" * 80)
                    
                    self.last_detected_skin_name = name
                    self.last_detected_skin_id = skin_id
                    self.last_detected_skin_key = f"{self.state.last_hovered_champ_slug}_{skin_id}"
                    
                    # Update state with English skin name for injection
                    if self.db:
                        english_skin_name = self.db.get_english_skin_name_by_id(skin_id)
                        if english_skin_name:
                            self.state.last_hovered_skin_key = english_skin_name
                            log.debug(f"Updated last_hovered_skin_key to English: '{english_skin_name}'")
                        else:
                            log.warning(f"Could not get English name for skin ID {skin_id}")
                    else:
                        log.warning("No database available to get English skin name")
                
        except Exception as e:
            log.debug(f"Error monitoring skin name element: {e}")
            # If there's an error, reset the element so we can re-find it
            self.skin_name_element = None
    
    def run(self):
        """Main UI detection loop - optimized for parallel execution"""
        log.info("UI Detection: Thread ready")
        
        detection_running = False
        last_check_time = 0
        check_interval = 0.1  # Check every 100ms for responsiveness
        
        while not self.state.stop:
            now = time.time()
            
            # Check if we should be running detection
            should_run = self._should_run_detection()
            
            # Log state changes
            if should_run and not detection_running:
                log.info("UI Detection: Starting - champion locked in ChampSelect")
                detection_running = True
                
                # Find League client (non-blocking)
                if not self.find_league_client():
                    log.warning("UI Detection: League client not found")
                    self.detection_available = False
                    time.sleep(check_interval)  # Short sleep for responsiveness
                    continue
                
                # Find skin elements (non-blocking)
                self.skin_elements = self.find_skin_elements_in_league()
                if not self.skin_elements:
                    log.warning("UI Detection: No skin elements found")
                    self.detection_available = False
                    time.sleep(check_interval)  # Short sleep for responsiveness
                    continue
                
                log.info(f"UI Detection: Found {len(self.skin_elements)} skin elements")
                self.detection_available = True
                
            elif not should_run and detection_running:
                log.info("UI Detection: Stopped - waiting for champion lock")
                detection_running = False
                self.detection_available = False
                self.skin_elements = []
                self.skin_name_element = None  # Reset focused element
                self.last_detected_skin_name = None
                self.last_detected_skin_id = None
                self.last_detected_skin_key = None
            
            if not should_run:
                time.sleep(check_interval)  # Short sleep for responsiveness
                continue
            
            # Check if League client still exists (only check periodically)
            if now - last_check_time > 1.0:  # Check every 1 second instead of every loop
                if not self.league_window or not self.league_window.Exists():
                    log.debug("UI Detection: League client lost, reconnecting...")
                    if not self.find_league_client():
                        time.sleep(check_interval)
                        continue
                    
                    # Re-find skin elements
                    self.skin_elements = self.find_skin_elements_in_league()
                    if not self.skin_elements:
                        log.warning("UI Detection: No skin elements found after reconnection")
                        time.sleep(check_interval)
                        continue
                last_check_time = now
            
            # Mouse hover debugging (always active when enabled)
            if self.mousehover_debug:
                log.debug(f"[MOUSE] Mouse hover debug enabled, detection_available={self.detection_available}")
            self._debug_mouse_hover()
            
            # Monitor for skin changes (non-blocking)
            if self.detection_available:
                if self.skin_name_element:
                    # We have a focused element, monitor it
                    self.monitor_skin_changes()
                else:
                    # Always try to find the skin name element (continuous search)
                    log.debug("Searching for skin name element...")
                    self.skin_name_element = self._find_skin_name_element()
                    if self.skin_name_element:
                        log.debug(f"Found skin name element: '{self.skin_name_element.Name}'")
                    else:
                        log.debug("No skin name element found")
            
            # Use shorter sleep for better responsiveness
            time.sleep(check_interval)