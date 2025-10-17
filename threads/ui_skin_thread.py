#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UI skin detection thread - Windows UI Automation API
"""

import time
import threading
from typing import Optional, List, Dict, Any
import uiautomation as auto
from database.name_db import NameDB
from state.shared_state import SharedState
from lcu.client import LCU
from utils.normalization import levenshtein_score
from utils.logging import get_logger
from utils.chroma_selector import get_chroma_selector
from config import UI_POLL_INTERVAL, UI_DETECTION_TIMEOUT

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
    
    def _find_control_by_automation_id(self, control, target_id, depth=0):
        """Recursively find a control by AutomationId."""
        if depth > 15:  # Prevent infinite recursion
            return None
            
        try:
            # Check if this control matches
            if control.AutomationId == target_id:
                return control
            
            # Search children
            children = control.GetChildren()
            for child in children:
                result = self._find_control_by_automation_id(child, target_id, depth + 1)
                if result:
                    return result
                    
        except Exception:
            pass
            
        return None
    
    def _get_text_controls_in_container(self, container):
        """Get all TextControls within a container."""
        text_controls = []
        
        try:
            self._collect_text_controls(container, text_controls, 0)
        except Exception:
            pass
            
        return text_controls
    
    def _collect_text_controls(self, control, text_controls, depth):
        """Recursively collect TextControls."""
        if depth > 10:  # Limit depth
            return
            
        try:
            if (control.ControlTypeName == "TextControl" and 
                control.FrameworkId == "Chrome" and 
                control.Name and 
                len(control.Name.strip()) > 3 and
                control.IsEnabled and 
                not control.IsOffscreen):
                text_controls.append(control)
            
            # Search children
            children = control.GetChildren()
            for child in children:
                self._collect_text_controls(child, text_controls, depth + 1)
                
        except Exception:
            pass
    
    def _find_skins_optimized(self):
        """ULTRA-FAST skin detection using specific AutomationId pattern."""
        import time
        start_time = time.time()
        skin_elements = []
        
        try:
            log.debug("Targeting ember10101 AutomationId pattern...")
            
            # Method 1: Direct search for the specific ember10101 container
            try:
                # Find the GroupControl with AutomationId 'ember10101' directly using recursive search
                ember_container = self._find_control_by_automation_id(self.league_window, "ember10101")
                
                if ember_container:
                    log.debug("Found ember10101 container!")
                    
                    # Get all TextControls within this container
                    skin_controls = self._get_text_controls_in_container(ember_container)
                    
                    log.debug(f"Found {len(skin_controls)} TextControls in ember10101")
                    
                    # These are all skins!
                    for control in skin_controls:
                        skin_elements.append(control)
                        log.debug(f"Skin: '{control.Name}'")
                
                else:
                    log.debug("ember10101 container not found, trying broader search...")
                    # Fallback to broader ember search
                    return self._find_skins_by_ember_pattern()
                
            except Exception as e:
                log.debug(f"Direct ember10101 search failed: {e}")
                # Fallback to broader search
                return self._find_skins_by_ember_pattern()
            
            elapsed_time = (time.time() - start_time) * 1000  # Convert to milliseconds
            log.debug(f"Found {len(skin_elements)} skins in {elapsed_time:.2f}ms!")
            
        except Exception as e:
            log.debug(f"Ultra-fast search failed: {e}")
            
        return skin_elements
    
    def _find_skins_by_ember_pattern(self):
        """Fallback: Search for any ember AutomationId pattern."""
        skin_elements = []
        
        try:
            log.debug("Searching for ember AutomationId patterns...")
            
            # Find all TextControls that are children of GroupControls with ember AutomationIds
            all_text_controls = self.league_window.FindAllChildren(
                lambda c: (c.ControlTypeName == "TextControl" and 
                         c.FrameworkId == "Chrome" and 
                         c.Name and 
                         len(c.Name.strip()) > 3 and
                         c.IsEnabled and 
                         not c.IsOffscreen)
            )
            
            log.debug(f"Found {len(all_text_controls)} TextControls")
            
            # Filter for skins by checking parent AutomationId
            for control in all_text_controls:
                try:
                    parent = control.GetParentControl()
                    if parent and parent.ControlTypeName == "GroupControl":
                        grandparent = parent.GetParentControl()
                        if (grandparent and 
                            grandparent.ControlTypeName == "GroupControl" and 
                            grandparent.AutomationId and 
                            "ember" in grandparent.AutomationId):
                            
                            # This is likely a skin!
                            skin_elements.append(control)
                            log.debug(f"Skin: '{control.Name}' (Parent: {grandparent.AutomationId})")
                except:
                    pass
            
        except Exception as e:
            log.debug(f"Ember pattern search failed: {e}")
            
        return skin_elements
    
    def find_skin_elements_in_league(self):
        """Find all skin text elements within the League client using learned patterns."""
        import time
        start_time = time.time()
        
        log.debug("Starting automatic skin detection...")
        
        if not self.league_window:
            log.debug("No client window reference")
            return []
            
        if not self.league_window.Exists():
            log.debug("League client window doesn't exist")
            return []
        
        log.debug("League client window found and exists")
        
        skin_elements = []
        
        try:
            # Use optimized search based on learned path
            log.debug("Using optimized skin detection based on learned UI hierarchy...")
            skin_elements = self._find_skins_optimized()
            
            elapsed_time = (time.time() - start_time) * 1000  # Convert to milliseconds
            log.debug(f"Search complete. Found {len(skin_elements)} skin elements in {elapsed_time:.2f}ms")
            return skin_elements
            
        except Exception as e:
            log.debug(f"Error searching for skin elements: {e}")
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
        """Monitor skin elements for name changes"""
        if not self.skin_elements:
            return
        
        current_skins = set()
        
        # Check each skin element
        for element in self.skin_elements:
            try:
                if element.Exists():
                    name = element.Name
                    if name and name.strip():
                        current_skins.add(name)
                        
                        # Check if this is a new skin detection
                        if name != self.last_detected_skin_name:
                            log.info(f"UI Detection: {name}")
                            
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
                log.debug(f"Error checking skin element: {e}")
                continue
    
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
            if self.detection_available and self.skin_elements:
                self.monitor_skin_changes()
            
            time.sleep(self.interval)
