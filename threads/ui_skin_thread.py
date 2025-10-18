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
                 skin_scraper=None, injection_manager=None, interval: float = UI_POLL_INTERVAL):
        super().__init__(daemon=True)
        self.state = state
        self.db = db
        self.lcu = lcu
        self.skin_scraper = skin_scraper
        self.injection_manager = injection_manager
        self.interval = interval
        
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
        
        # Detection state flags
        self.detection_available = False
        self.last_detection_attempt = 0.0
        
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
        """Find the specific skin name element at the exact known position."""
        try:
            log.debug("Getting skin name element at exact position...")
            
            # Get window dimensions and position
            window_rect = self.league_window.BoundingRectangle
            window_width = window_rect.width()
            window_height = window_rect.height()
            window_left = window_rect.left
            window_top = window_rect.top
            
            # Calculate exact position relative to window
            relative_x = int(window_width * 0.5)  # 50% of window width
            relative_y = int(window_height * 0.658)  # 65.8% of window height
            
            # Convert to screen coordinates
            target_x = window_left + relative_x
            target_y = window_top + relative_y
            
            log.debug(f"Looking for TextControl at position ({target_x}, {target_y})")
            
            # Use uiautomation's FromPoint method to get control at exact position
            try:
                control = auto.ControlFromPoint(target_x, target_y)
                log.debug(f"Control at position: {control.ControlTypeName if control else 'None'} - {control.FrameworkId if control else 'None'}")
                
                if control and control.ControlTypeName == "TextControl" and control.FrameworkId == "Chrome":
                    log.debug(f"Found TextControl at position: '{control.Name}'")
                    return control
                elif control and control.ControlTypeName == "DocumentControl" and control.FrameworkId == "Chrome":
                    # The skin name is inside the document, try to get it directly
                    log.debug(f"Found DocumentControl at position, trying direct TextControl access...")
                    
                    # Try to get TextControl directly at the same position within the document
                    try:
                        text_control = auto.ControlFromPoint(target_x, target_y)
                        if text_control and text_control.ControlTypeName == "TextControl" and text_control.FrameworkId == "Chrome":
                            log.debug(f"Found TextControl directly: '{text_control.Name}'")
                            return text_control
                    except Exception as e:
                        log.debug(f"Direct TextControl access failed: {e}")
                    
                    # Fallback: search for TextControl within the document
                    text_control = self._find_text_control_at_position(control, target_x, target_y)
                    if text_control:
                        log.debug(f"Found TextControl within DocumentControl: '{text_control.Name}'")
                        return text_control
                else:
                    log.debug(f"Control at position is not a Chrome TextControl: {control.ControlTypeName if control else 'None'}")
            except Exception as e:
                log.debug(f"Error getting control from point: {e}")
            
            # Fallback: try a small area around the target position
            tolerance = 20
            for offset_x in range(-tolerance, tolerance + 1, 5):
                for offset_y in range(-tolerance, tolerance + 1, 5):
                    try:
                        test_x = target_x + offset_x
                        test_y = target_y + offset_y
                        control = auto.ControlFromPoint(test_x, test_y)
                        if control and control.ControlTypeName == "TextControl" and control.FrameworkId == "Chrome":
                            log.debug(f"Found TextControl at offset position ({test_x}, {test_y}): '{control.Name}'")
                            return control
                    except Exception:
                        continue
            
            log.debug("No TextControl found at skin name position")
            return None
            
        except Exception as e:
            log.debug(f"Error finding skin name element: {e}")
            return None
    
    def _find_text_control_at_position(self, parent_control, target_x, target_y):
        """Find a TextControl at the specific position within a parent control."""
        try:
            # Get all TextControls within the parent using recursive search
            text_controls = []
            self._collect_text_controls_recursive(parent_control, text_controls, 0)
            
            log.debug(f"Found {len(text_controls)} TextControls within DocumentControl")
            
            # Log all TextControls found for debugging
            for i, text_control in enumerate(text_controls):
                try:
                    rect = text_control.BoundingRectangle
                    if rect:
                        control_x = rect.xcenter()
                        control_y = rect.ycenter()
                        distance = ((control_x - target_x) ** 2 + (control_y - target_y) ** 2) ** 0.5
                        log.debug(f"TextControl {i+1}: '{text_control.Name}' at ({control_x}, {control_y}) - distance: {distance:.1f}px")
                except Exception as e:
                    log.debug(f"TextControl {i+1}: Error getting position - {e}")
            
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
        """Log detailed information about a skin control for debugging."""
        try:
            log.info("=" * 120)
            log.info(f"🔍 ULTRA-DETAILED SKIN INFO FOR: '{skin_name}'")
            log.info("=" * 120)
            
            # Basic control information
            log.info(f"📋 CONTROL DETAILS:")
            log.info(f"   Name: '{control.Name}'")
            log.info(f"   Control Type: {control.ControlTypeName}")
            log.info(f"   Framework ID: '{control.FrameworkId}'")
            log.info(f"   Class Name: '{control.ClassName}'")
            log.info(f"   Automation ID: '{control.AutomationId}'")
            log.info(f"   Localized Control Type: '{control.LocalizedControlType}'")
            log.info(f"   Help Text: '{getattr(control, 'HelpText', 'N/A')}'")
            log.info(f"   Item Type: '{getattr(control, 'ItemType', 'N/A')}'")
            log.info(f"   Item Status: '{getattr(control, 'ItemStatus', 'N/A')}'")
            
            # Bounding rectangle details
            rect = control.BoundingRectangle
            log.info(f"📐 BOUNDING RECTANGLE:")
            log.info(f"   Left: {rect.left}")
            log.info(f"   Top: {rect.top}")
            log.info(f"   Right: {rect.right}")
            log.info(f"   Bottom: {rect.bottom}")
            log.info(f"   Width: {rect.width()}")
            log.info(f"   Height: {rect.height()}")
            log.info(f"   Center X: {rect.xcenter()}")
            log.info(f"   Center Y: {rect.ycenter()}")
            
            # State information
            log.info(f"🔧 CONTROL STATE:")
            log.info(f"   Is Enabled: {control.IsEnabled}")
            log.info(f"   Is Offscreen: {control.IsOffscreen}")
            log.info(f"   Is Keyboard Focusable: {control.IsKeyboardFocusable}")
            log.info(f"   Is Content Element: {control.IsContentElement}")
            log.info(f"   Is Control Element: {control.IsControlElement}")
            log.info(f"   Is Password: {getattr(control, 'IsPassword', 'N/A')}")
            log.info(f"   Is Required For Form: {getattr(control, 'IsRequiredForForm', 'N/A')}")
            
            # Clickable point and position
            try:
                clickable_point = control.GetClickablePoint()
                log.info(f"🖱️ CLICKABLE POINT: {clickable_point}")
            except Exception as e:
                log.info(f"🖱️ CLICKABLE POINT: Error - {e}")
            
            try:
                position = control.GetPosition()
                log.info(f"📍 POSITION: {position}")
            except Exception as e:
                log.info(f"📍 POSITION: Error - {e}")
            
            # All possible patterns
            all_patterns = [
                'GetValuePattern', 'GetTextPattern', 'GetLegacyIAccessiblePattern',
                'GetInvokePattern', 'GetSelectionPattern', 'GetTogglePattern',
                'GetExpandCollapsePattern', 'GetScrollPattern', 'GetWindowPattern',
                'GetRangeValuePattern', 'GetSelectionItemPattern', 'GetTablePattern',
                'GetTableItemPattern', 'GetGridPattern', 'GetGridItemPattern',
                'GetMultipleViewPattern', 'GetTransformPattern', 'GetItemContainerPattern',
                'GetVirtualizedItemPattern', 'GetSynchronizedInputPattern', 'GetDockPattern',
                'GetAnnotationPattern', 'GetDragPattern', 'GetDropTargetPattern',
                'GetObjectModelPattern', 'GetSpreadsheetPattern', 'GetSpreadsheetItemPattern',
                'GetStylesPattern', 'GetTextChildPattern', 'GetTextEditPattern',
                'GetTextRangePattern', 'GetTextRange2Pattern', 'GetCustomNavigationPattern'
            ]
            
            patterns_available = []
            patterns_detailed = {}
            
            for pattern_method in all_patterns:
                try:
                    pattern = getattr(control, pattern_method)()
                    if pattern:
                        pattern_name = pattern_method.replace('Get', '').replace('Pattern', '')
                        patterns_available.append(pattern_name)
                        patterns_detailed[pattern_name] = pattern
                except:
                    pass
            
            log.info(f"🎭 AVAILABLE PATTERNS: {', '.join(patterns_available) if patterns_available else 'None'}")
            
            # Detailed pattern information
            for pattern_name, pattern in patterns_detailed.items():
                log.info(f"🎭 {pattern_name.upper()} PATTERN DETAILS:")
                try:
                    if hasattr(pattern, 'Value'):
                        log.info(f"   Value: '{pattern.Value}'")
                    if hasattr(pattern, 'GetText'):
                        log.info(f"   Text: '{pattern.GetText()}'")
                    if hasattr(pattern, 'Name'):
                        log.info(f"   Name: '{pattern.Name}'")
                    if hasattr(pattern, 'Description'):
                        log.info(f"   Description: '{pattern.Description}'")
                    if hasattr(pattern, 'Role'):
                        log.info(f"   Role: '{pattern.Role}'")
                    if hasattr(pattern, 'State'):
                        log.info(f"   State: '{pattern.State}'")
                    if hasattr(pattern, 'Value'):
                        log.info(f"   Value: '{pattern.Value}'")
                    if hasattr(pattern, 'IsReadOnly'):
                        log.info(f"   IsReadOnly: '{pattern.IsReadOnly}'")
                    if hasattr(pattern, 'IsRequired'):
                        log.info(f"   IsRequired: '{pattern.IsRequired}'")
                    if hasattr(pattern, 'IsSelected'):
                        log.info(f"   IsSelected: '{pattern.IsSelected}'")
                    if hasattr(pattern, 'ToggleState'):
                        log.info(f"   ToggleState: '{pattern.ToggleState}'")
                    if hasattr(pattern, 'ExpandCollapseState'):
                        log.info(f"   ExpandCollapseState: '{pattern.ExpandCollapseState}'")
                    if hasattr(pattern, 'CanScroll'):
                        log.info(f"   CanScroll: '{pattern.CanScroll}'")
                    if hasattr(pattern, 'CanScrollHorizontally'):
                        log.info(f"   CanScrollHorizontally: '{pattern.CanScrollHorizontally}'")
                    if hasattr(pattern, 'CanScrollVertically'):
                        log.info(f"   CanScrollVertically: '{pattern.CanScrollVertically}'")
                    if hasattr(pattern, 'HorizontalScrollPercent'):
                        log.info(f"   HorizontalScrollPercent: '{pattern.HorizontalScrollPercent}'")
                    if hasattr(pattern, 'VerticalScrollPercent'):
                        log.info(f"   VerticalScrollPercent: '{pattern.VerticalScrollPercent}'")
                    if hasattr(pattern, 'HorizontalViewSize'):
                        log.info(f"   HorizontalViewSize: '{pattern.HorizontalViewSize}'")
                    if hasattr(pattern, 'VerticalViewSize'):
                        log.info(f"   VerticalViewSize: '{pattern.VerticalViewSize}'")
                    if hasattr(pattern, 'CanMaximize'):
                        log.info(f"   CanMaximize: '{pattern.CanMaximize}'")
                    if hasattr(pattern, 'CanMinimize'):
                        log.info(f"   CanMinimize: '{pattern.CanMinimize}'")
                    if hasattr(pattern, 'IsModal'):
                        log.info(f"   IsModal: '{pattern.IsModal}'")
                    if hasattr(pattern, 'IsTopmost'):
                        log.info(f"   IsTopmost: '{pattern.IsTopmost}'")
                    if hasattr(pattern, 'WindowVisualState'):
                        log.info(f"   WindowVisualState: '{pattern.WindowVisualState}'")
                    if hasattr(pattern, 'WindowInteractionState'):
                        log.info(f"   WindowInteractionState: '{pattern.WindowInteractionState}'")
                except Exception as e:
                    log.info(f"   Error getting {pattern_name} details: {e}")
            
            # Complete parent hierarchy with ALL details
            log.info(f"👨‍👩‍👧‍👦 COMPLETE PARENT HIERARCHY:")
            current = control
            depth = 0
            while current and depth < 15:
                try:
                    parent = current.GetParentControl()
                    if parent:
                        log.info(f"   Level {depth + 1}: '{parent.Name}' ({parent.ControlTypeName}) - {parent.FrameworkId}")
                        log.info(f"      Class: '{parent.ClassName}' | AutomationId: '{parent.AutomationId}'")
                        log.info(f"      LocalizedControlType: '{parent.LocalizedControlType}'")
                        log.info(f"      IsEnabled: {parent.IsEnabled} | IsOffscreen: {parent.IsOffscreen}")
                        log.info(f"      BoundingRect: {parent.BoundingRectangle}")
                        
                        # Get parent's patterns
                        parent_patterns = []
                        for pattern_method in ['GetValuePattern', 'GetTextPattern', 'GetLegacyIAccessiblePattern']:
                            try:
                                pattern = getattr(parent, pattern_method)()
                                if pattern:
                                    parent_patterns.append(pattern_method.replace('Get', '').replace('Pattern', ''))
                            except:
                                pass
                        log.info(f"      Available Patterns: {', '.join(parent_patterns) if parent_patterns else 'None'}")
                        
                        current = parent
                        depth += 1
                    else:
                        break
                except Exception as e:
                    log.info(f"   Error at level {depth + 1}: {e}")
                    break
            
            # Complete siblings information
            try:
                parent = control.GetParentControl()
                if parent:
                    siblings = parent.GetChildren()
                    log.info(f"👥 COMPLETE SIBLINGS INFO:")
                    log.info(f"   Total Siblings: {len(siblings)}")
                    for i, sibling in enumerate(siblings):
                        try:
                            is_current = " ← THIS ONE" if sibling == control else ""
                            log.info(f"   Sibling {i+1}: '{sibling.Name}' ({sibling.ControlTypeName}) - {sibling.FrameworkId}{is_current}")
                            log.info(f"      AutomationId: '{sibling.AutomationId}' | Class: '{sibling.ClassName}'")
                            log.info(f"      BoundingRect: {sibling.BoundingRectangle}")
                            log.info(f"      IsEnabled: {sibling.IsEnabled} | IsOffscreen: {sibling.IsOffscreen}")
                        except Exception as e:
                            log.info(f"   Sibling {i+1}: [Error reading sibling - {e}]")
            except Exception as e:
                log.info(f"👥 SIBLINGS: Error getting siblings - {e}")
            
            # Complete children information
            try:
                children = control.GetChildren()
                log.info(f"👶 COMPLETE CHILDREN INFO:")
                log.info(f"   Total Children: {len(children)}")
                for i, child in enumerate(children):
                    try:
                        log.info(f"   Child {i+1}: '{child.Name}' ({child.ControlTypeName}) - {child.FrameworkId}")
                        log.info(f"      AutomationId: '{child.AutomationId}' | Class: '{child.ClassName}'")
                        log.info(f"      BoundingRect: {child.BoundingRectangle}")
                        log.info(f"      IsEnabled: {child.IsEnabled} | IsOffscreen: {child.IsOffscreen}")
                    except Exception as e:
                        log.info(f"   Child {i+1}: [Error reading child - {e}]")
            except Exception as e:
                log.info(f"👶 CHILDREN: Error getting children - {e}")
            
            # Additional control properties
            log.info(f"🔍 ADDITIONAL CONTROL PROPERTIES:")
            try:
                log.info(f"   ProcessId: {getattr(control, 'ProcessId', 'N/A')}")
                log.info(f"   RuntimeId: {getattr(control, 'RuntimeId', 'N/A')}")
                log.info(f"   NativeWindowHandle: {getattr(control, 'NativeWindowHandle', 'N/A')}")
                log.info(f"   ProviderDescription: {getattr(control, 'ProviderDescription', 'N/A')}")
            except Exception as e:
                log.info(f"   Error getting additional properties: {e}")
            
            log.info("=" * 120)
            log.info(f"🔍 END ULTRA-DETAILED INFO FOR: '{skin_name}'")
            log.info("=" * 120)
            
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
            if time_since_lock < 0.2:  # 200ms delay after lock
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
        """Monitor the focused skin name element for changes"""
        if not self.skin_name_element:
            return
        
        try:
            # Check if the skin name element still exists
            if not self.skin_name_element.Exists():
                log.debug("Skin name element no longer exists, need to re-find it")
                self.skin_name_element = None
                return
            
            # Get the current name from the element
            name = self.skin_name_element.Name
            if not name or not name.strip():
                return
            
            # Check if this is a new skin detection
            if name != self.last_detected_skin_name:
                log.info(f"UI Detection: {name}")
                
                # Special detailed logging for "Darius biosoldat"
                if "Darius biosoldat" in name or "biosoldat" in name.lower():
                    self._log_detailed_skin_info(self.skin_name_element, name)
                
                # Check if we should update
                if not self._should_update_hovered_skin(name):
                    return
                
                # Match against database
                match_result = self._match_skin_name(name)
                if match_result:
                    skin_id, skin_name, similarity = match_result
                    
                    # Update state
                    self.state.last_hovered_skin_name = skin_name
                    self.state.last_hovered_skin_id = skin_id
                    self.state.last_hovered_champ_id = self.state.locked_champ_id
                    self.state.last_hovered_champ_slug = self.db.slug_by_id.get(self.state.locked_champ_id)
                    self.state.hovered_skin_timestamp = time.time()
                    
                    # Check if current skin has chromas
                    has_chromas = self._skin_has_displayable_chromas(skin_id)
                    
                    # Show chroma panel if skin has chromas
                    self._trigger_chroma_panel(skin_id, skin_name)
                    
                    # Calculate is_owned
                    is_base_skin = (skin_id % 1000) == 0
                    is_owned = is_base_skin or (skin_id in self.state.owned_skin_ids)
                    
                    # Trigger fade animation
                    self._trigger_chroma_fade(skin_id, has_chromas, is_owned)
                    
                    # Log detection
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
                
        except Exception as e:
            log.debug(f"Error monitoring skin name element: {e}")
            # If there's an error, reset the element so we can re-find it
            self.skin_name_element = None
    
    def run(self):
        """Main UI detection loop"""
        log.info("UI Detection: Thread ready")
        
        detection_running = False
        
        while not self.state.stop:
            now = time.time()
            
            # Check if we should be running detection
            should_run = self._should_run_detection()
            
            # Log state changes
            if should_run and not detection_running:
                log.info("UI Detection: Starting - champion locked in ChampSelect")
                detection_running = True
                
                # Find League client
                if not self.find_league_client():
                    log.warning("UI Detection: League client not found")
                    self.detection_available = False
                    time.sleep(1.0)
                    continue
                
                # Find skin elements
                self.skin_elements = self.find_skin_elements_in_league()
                if not self.skin_elements:
                    log.warning("UI Detection: No skin elements found")
                    self.detection_available = False
                    time.sleep(1.0)
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
                time.sleep(self.interval)
                continue
            
            # Check if League client still exists
            if not self.league_window or not self.league_window.Exists():
                log.debug("UI Detection: League client lost, reconnecting...")
                if not self.find_league_client():
                    time.sleep(1.0)
                    continue
                
                # Re-find skin elements
                self.skin_elements = self.find_skin_elements_in_league()
                if not self.skin_elements:
                    log.warning("UI Detection: No skin elements found after reconnection")
                    time.sleep(1.0)
                    continue
            
            # Monitor for skin changes
            if self.detection_available:
                if self.skin_name_element:
                    # We have a focused element, monitor it
                    self.monitor_skin_changes()
                elif self.skin_elements:
                    # Fallback: try to find the skin name element from existing elements
                    log.debug("No focused skin name element, attempting to find one...")
                    self.skin_name_element = self._find_skin_name_element()
                    if self.skin_name_element:
                        log.debug(f"Found skin name element: '{self.skin_name_element.Name}'")
                    else:
                        log.debug("Still no skin name element found")
            
            time.sleep(self.interval)