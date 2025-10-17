import uiautomation as auto
import time
import sys
import signal
from datetime import datetime
from typing import Optional, Dict, Any

class LeagueSkinDetector:
    def __init__(self):
        self.league_process = None
        self.client_window = None
        self.running = True
        
        # Set up signal handler for Ctrl+C
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle Ctrl+C gracefully."""
        print("\n[STOPPED] Received Ctrl+C, stopping...")
        self.running = False
        sys.exit(0)
        
    def find_league_client(self) -> bool:
        """Find the League of Legends client window."""
        try:
            # Look for League of Legends client window by name
            self.client_window = auto.WindowControl(Name="League of Legends")
            if self.client_window.Exists():
                print("+ League of Legends client found!")
                return True
            else:
                print("- League of Legends client not found. Make sure the client is running.")
                return False
        except Exception as e:
            print(f"- Error finding League client: {e}")
            return False
    
    def get_control_under_cursor(self) ->auto.Control Optional[]:
        """Get the UI control currently under the mouse cursor."""
        try:
            control = auto.ControlFromCursor()
            return control
        except Exception as e:
            print(f"- Error getting control under cursor: {e}")
            return None
    
    def extract_skin_info(self, control: auto.Control) -> Dict[str, Any]:
        """Extract skin information from a UI control."""
        skin_info = {
            'name': None,
            'value': None,
            'text': None,
            'control_type': None,
            'automation_id': None,
            'class_name': None
        }
        
        try:
            # Get basic control information
            skin_info['name'] = control.Name
            skin_info['control_type'] = str(control.ControlTypeName)
            skin_info['automation_id'] = control.AutomationId
            skin_info['class_name'] = control.ClassName
            
            # Try to get value pattern
            try:
                value_pattern = control.GetValuePattern()
                if value_pattern:
                    skin_info['value'] = value_pattern.Value
            except:
                pass
            
            # Try to get text pattern
            try:
                text_pattern = control.GetTextPattern()
                if text_pattern:
                    skin_info['text'] = text_pattern.GetText()
            except:
                pass
            
            # Try to get legacy accessible pattern
            try:
                legacy_pattern = control.GetLegacyIAccessiblePattern()
                if legacy_pattern:
                    skin_info['name'] = skin_info['name'] or legacy_pattern.Name
                    skin_info['value'] = skin_info['value'] or legacy_pattern.Value
            except:
                pass
                
        except Exception as e:
            print(f"- Error extracting skin info: {e}")
        
        return skin_info
    
    def find_skin_in_parent_hierarchy(self, control: auto.Control, max_depth: int = 5) -> Optional[str]:
        """Search up the parent hierarchy for skin-related information."""
        current_control = control
        depth = 0
        
        while current_control and depth < max_depth:
            skin_info = self.extract_skin_info(current_control)
            
            # Look for skin-related keywords in the control's properties
            skin_keywords = ['skin', 'champion', 'champ', 'name', 'title']
            
            for key, value in skin_info.items():
                if value and isinstance(value, str):
                    value_lower = value.lower()
                    if any(keyword in value_lower for keyword in skin_keywords):
                        if len(value.strip()) > 2:  # Filter out very short strings
                            return value
            
            # Move to parent control
            try:
                current_control = current_control.GetParentControl()
                depth += 1
            except:
                break
        
        return None
    
    def find_skin_elements_in_league(self):
        """Automatically find all skin text elements within the League client using learned patterns."""
        import time
        start_time = time.time()
        
        print("\n[INFO] Starting automatic skin detection...")
        
        if not self.client_window:
            print("[ERROR] No client window reference")
            return []
            
        if not self.client_window.Exists():
            print("[ERROR] League client window doesn't exist")
            return []
        
        print("[INFO] League client window found and exists")
        print(f"[INFO] League client bounds: {self.client_window.BoundingRectangle}")
        
        skin_elements = []
        
        try:
            # Get League client bounds
            league_rect = self.client_window.BoundingRectangle
            print(f"[INFO] Searching within bounds: {league_rect}")
            
            # Use optimized search based on learned path
            print("[INFO] Using optimized skin detection based on learned UI hierarchy...")
            skin_elements = self._find_skins_optimized(league_rect)
            
            elapsed_time = (time.time() - start_time) * 1000  # Convert to milliseconds
            print(f"[INFO] Search complete. Found {len(skin_elements)} skin elements in {elapsed_time:.2f}ms")
            return skin_elements
            
        except Exception as e:
            print(f"[ERROR] Error searching for skin elements: {e}")
            return []
    
    def _find_skins_optimized(self, league_rect):
        """ULTRA-FAST skin detection using specific AutomationId pattern."""
        import time
        start_time = time.time()
        skin_elements = []
        
        try:
            print("[ULTRA-FAST] Targeting ember10101 AutomationId pattern...")
            
            # Method 1: Direct search for the specific ember10101 container
            try:
                # Find the GroupControl with AutomationId 'ember10101' directly using recursive search
                ember_container = self._find_control_by_automation_id(self.client_window, "ember10101")
                
                if ember_container:
                    print(f"[ULTRA-FAST] Found ember10101 container!")
                    
                    # Get all TextControls within this container
                    skin_controls = self._get_text_controls_in_container(ember_container)
                    
                    print(f"[ULTRA-FAST] Found {len(skin_controls)} TextControls in ember10101")
                    
                    # These are all skins!
                    for control in skin_controls:
                        skin_elements.append(control)
                        print(f"[FOUND] Skin: '{control.Name}'")
                
                else:
                    print("[ULTRA-FAST] ember10101 container not found, trying broader search...")
                    # Fallback to broader ember search
                    return self._find_skins_by_ember_pattern(league_rect)
                
            except Exception as e:
                print(f"[ULTRA-FAST] Direct ember10101 search failed: {e}")
                # Fallback to broader search
                return self._find_skins_by_ember_pattern(league_rect)
            
            elapsed_time = (time.time() - start_time) * 1000  # Convert to milliseconds
            print(f"[ULTRA-FAST] Found {len(skin_elements)} skins in {elapsed_time:.2f}ms!")
            
        except Exception as e:
            print(f"[ERROR] Ultra-fast search failed: {e}")
            
        return skin_elements
    
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
    
    def _find_skins_by_ember_pattern(self, league_rect):
        """Fallback: Search for any ember AutomationId pattern."""
        skin_elements = []
        
        try:
            print("[EMBER-PATTERN] Searching for ember AutomationId patterns...")
            
            # Find all TextControls that are children of GroupControls with ember AutomationIds
            all_text_controls = self.client_window.FindAllChildren(
                lambda c: (c.ControlTypeName == "TextControl" and 
                         c.FrameworkId == "Chrome" and 
                         c.Name and 
                         len(c.Name.strip()) > 3 and
                         c.IsEnabled and 
                         not c.IsOffscreen)
            )
            
            print(f"[EMBER-PATTERN] Found {len(all_text_controls)} TextControls")
            
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
                            print(f"[FOUND] Skin: '{control.Name}' (Parent: {grandparent.AutomationId})")
                except:
                    pass
            
        except Exception as e:
            print(f"[EMBER-PATTERN] Search failed: {e}")
            # Final fallback to path navigation
            return self._find_skins_by_path(league_rect)
            
        return skin_elements
    
    def _find_skins_by_path(self, league_rect):
        """Fallback: Navigate through UI path."""
        skin_elements = []
        
        try:
            print("[FALLBACK] Using UI path navigation...")
            
            # Follow the exact known path: PaneControl -> PaneControl -> DocumentControl -> GroupControls -> TextControls
            children = self.client_window.GetChildren()
            if not children:
                return skin_elements
            pane1 = children[0]
            
            pane1_children = pane1.GetChildren()
            if not pane1_children:
                return skin_elements
            pane2 = pane1_children[0]
            
            pane2_children = pane2.GetChildren()
            doc_control = None
            for child in pane2_children:
                if child.ControlTypeName == "DocumentControl" and child.FrameworkId == "Chrome":
                    doc_control = child
                    break
            
            if not doc_control:
                return skin_elements
            
            self._navigate_to_skins(doc_control, skin_elements, 0)
            
        except Exception as e:
            print(f"[ERROR] Path navigation failed: {e}")
            
        return skin_elements
    
    def _navigate_to_skins(self, control, skin_elements, depth):
        """Navigate through GroupControls to find skin TextControls - no search, just navigation."""
        if depth > 12:  # Limit depth based on known path
            return
            
        try:
            children = control.GetChildren()
            
            for child in children:
                if child.ControlTypeName == "TextControl" and child.FrameworkId == "Chrome":
                    # Quick check if it's a skin
                    name = child.Name
                    if (name and len(name.strip()) > 3 and 
                        child.IsEnabled and not child.IsOffscreen and
                        not name.lower().strip() in ["lol", "tft", "position", "assignée", "préparez", "équipement",
                                                   "bannissements", "équipe", "trier", "nom", "aléatoire", "quitter",
                                                   "voir", "compétences", "connexion", "cliquer", "entrée", "n'oubliez",
                                                   "jamais", "mot", "passe", "aider", "sélection", "champions", "renvoyé",
                                                   "salon", "groupe", "difficile", "mode", "aveugle", "5c5", "6", "1"]):
                        skin_elements.append(child)
                        print(f"[FOUND] Skin: '{child.Name}'")
                
                elif child.ControlTypeName == "GroupControl" and child.FrameworkId == "Chrome":
                    # Continue navigating
                    self._navigate_to_skins(child, skin_elements, depth + 1)
                    
                elif child.ControlTypeName == "ListControl" and child.FrameworkId == "Chrome":
                    # Navigate ListControls
                    self._navigate_list_controls(child, skin_elements, depth + 1)
                    
        except Exception:
            pass  # Continue navigating other branches
    
    def _navigate_list_controls(self, list_control, skin_elements, depth):
        """Navigate ListControls for skin TextControls."""
        try:
            children = list_control.GetChildren()
            for child in children:
                if child.ControlTypeName == "ListItemControl" and child.FrameworkId == "Chrome":
                    # Navigate within each ListItemControl
                    self._navigate_to_skins(child, skin_elements, depth + 1)
        except Exception:
            pass
    
    def _log_skin_details(self, control, depth):
        """Log detailed information about a skin control for pattern analysis."""
        try:
            indent = "  " * depth
            print(f"{indent}[SKIN_DETAILS] ========================================")
            print(f"{indent}[SKIN_DETAILS] Name: '{control.Name}'")
            print(f"{indent}[SKIN_DETAILS] ControlType: {control.ControlTypeName}")
            print(f"{indent}[SKIN_DETAILS] FrameworkId: {control.FrameworkId}")
            print(f"{indent}[SKIN_DETAILS] ClassName: '{control.ClassName}'")
            print(f"{indent}[SKIN_DETAILS] AutomationId: '{control.AutomationId}'")
            print(f"{indent}[SKIN_DETAILS] BoundingRectangle: {control.BoundingRectangle}")
            print(f"{indent}[SKIN_DETAILS] IsEnabled: {control.IsEnabled}")
            print(f"{indent}[SKIN_DETAILS] IsOffscreen: {control.IsOffscreen}")
            print(f"{indent}[SKIN_DETAILS] IsKeyboardFocusable: {control.IsKeyboardFocusable}")
            print(f"{indent}[SKIN_DETAILS] IsContentElement: {control.IsContentElement}")
            print(f"{indent}[SKIN_DETAILS] IsControlElement: {control.IsControlElement}")
            
            # Get parent information
            try:
                parent = control.GetParentControl()
                if parent:
                    print(f"{indent}[SKIN_DETAILS] Parent: {parent.ControlTypeName} - '{parent.Name}' ({parent.FrameworkId})")
                    print(f"{indent}[SKIN_DETAILS] Parent ClassName: '{parent.ClassName}'")
                    print(f"{indent}[SKIN_DETAILS] Parent AutomationId: '{parent.AutomationId}'")
                    
                    # Get grandparent
                    grandparent = parent.GetParentControl()
                    if grandparent:
                        print(f"{indent}[SKIN_DETAILS] Grandparent: {grandparent.ControlTypeName} - '{grandparent.Name}' ({grandparent.FrameworkId})")
                        print(f"{indent}[SKIN_DETAILS] Grandparent ClassName: '{grandparent.ClassName}'")
                        print(f"{indent}[SKIN_DETAILS] Grandparent AutomationId: '{grandparent.AutomationId}'")
            except Exception as e:
                print(f"{indent}[SKIN_DETAILS] Parent info error: {e}")
            
            # Get LegacyIAccessible pattern
            try:
                legacy = control.GetLegacyIAccessiblePattern()
                if legacy:
                    print(f"{indent}[SKIN_DETAILS] LegacyIAccessible Role: {legacy.Role}")
                    print(f"{indent}[SKIN_DETAILS] LegacyIAccessible State: {legacy.State}")
                    print(f"{indent}[SKIN_DETAILS] LegacyIAccessible Name: '{legacy.Name}'")
                    print(f"{indent}[SKIN_DETAILS] LegacyIAccessible Description: '{legacy.Description}'")
            except Exception as e:
                print(f"{indent}[SKIN_DETAILS] LegacyIAccessible error: {e}")
            
            # Get siblings count
            try:
                parent = control.GetParentControl()
                if parent:
                    siblings = parent.GetChildren()
                    print(f"{indent}[SKIN_DETAILS] Siblings count: {len(siblings)}")
                    for i, sibling in enumerate(siblings):
                        if sibling == control:
                            print(f"{indent}[SKIN_DETAILS] This is sibling #{i+1}")
                            break
            except Exception as e:
                print(f"{indent}[SKIN_DETAILS] Siblings info error: {e}")
            
            print(f"{indent}[SKIN_DETAILS] ========================================")
            
        except Exception as e:
            print(f"{indent}[SKIN_DETAILS] Error logging details: {e}")
    
    def _find_skins_fallback(self, league_rect):
        """Fallback method if direct search fails."""
        skin_elements = []
        
        try:
            # Simple recursive search with minimal logging
            self._search_all_controls(self.client_window, skin_elements, league_rect, 0)
        except Exception as e:
            print(f"[ERROR] Fallback search failed: {e}")
            
        return skin_elements
    
    def _search_all_controls(self, control, skin_elements, league_rect, depth):
        """Simple recursive search - no logging spam."""
        if depth > 20:  # Limit depth
            return
            
        try:
            children = control.GetChildren()
            for child in children:
                if (child.ControlTypeName == "TextControl" and 
                    child.FrameworkId == "Chrome" and 
                    child.Name and 
                    len(child.Name.strip()) > 3):
                    
                    if self._is_skin_text_control(child, league_rect):
                        skin_elements.append(child)
                        print(f"[FOUND] Skin: '{child.Name}'")
                
                # Continue searching
                self._search_all_controls(child, skin_elements, league_rect, depth + 1)
                
        except Exception:
            pass  # Continue searching other branches
    
    def _search_group_controls_for_skins(self, control, skin_elements, league_rect, depth):
        """Search through GroupControls to find skin TextControls."""
        if depth > 15:  # Prevent infinite recursion
            return
            
        try:
            children = control.GetChildren()
            
            for child in children:
                if child.ControlTypeName == "TextControl" and child.FrameworkId == "Chrome":
                    # Check if this is a skin
                    if self._is_skin_text_control(child, league_rect):
                        skin_elements.append(child)
                        print(f"[FOUND] Skin: '{child.Name}' at ({child.BoundingRectangle.xcenter()}, {child.BoundingRectangle.ycenter()})")
                
                elif child.ControlTypeName == "GroupControl" and child.FrameworkId == "Chrome":
                    # Recursively search GroupControls
                    self._search_group_controls_for_skins(child, skin_elements, league_rect, depth + 1)
                    
                elif child.ControlTypeName == "ListControl" and child.FrameworkId == "Chrome":
                    # Search ListControls for skin items
                    self._search_list_controls_for_skins(child, skin_elements, league_rect, depth + 1)
                    
        except Exception as e:
            pass  # Continue searching other branches
    
    def _search_list_controls_for_skins(self, list_control, skin_elements, league_rect, depth):
        """Search ListControls for skin TextControls."""
        try:
            children = list_control.GetChildren()
            print(f"[OPTIMIZED] Searching ListControl with {len(children)} items...")
            
            for child in children:
                if child.ControlTypeName == "ListItemControl" and child.FrameworkId == "Chrome":
                    # Search within each ListItemControl
                    self._search_group_controls_for_skins(child, skin_elements, league_rect, depth + 1)
                    
        except Exception as e:
            pass  # Continue searching other branches
    
    def _search_children_for_skin_patterns(self, control, skin_elements, league_rect, depth=0, path=""):
        """Search for skin elements using learned patterns from the data analysis."""
        if depth > 25:  # Go much deeper to find skin names
            return
            
        try:
            # Build current path
            current_path = f"{path}/{control.ControlTypeName}"
            if control.Name:
                current_path += f"('{control.Name}')"
            
            # Log what we're checking (only for TextControls and important containers)
            if (control.ControlTypeName == "TextControl" or 
                control.ControlTypeName == "ListControl" or 
                control.ControlTypeName == "ListItemControl" or
                depth <= 3):
                indent = "  " * depth
                print(f"{indent}[DEBUG] Checking: {control.ControlTypeName} - '{control.Name}' ({control.FrameworkId})")
                if control.ControlTypeName == "TextControl" and control.Name and len(control.Name) > 3:
                    print(f"{indent}[PATH] {current_path}")
            
            # Special handling for DocumentControl (Chrome content)
            if (control.ControlTypeName == "DocumentControl" and 
                control.FrameworkId == "Chrome"):
                print(f"[FOCUS] Found Chrome DocumentControl - searching deeper for skin elements...")
                children = control.GetChildren()
                print(f"[FOCUS] DocumentControl has {len(children)} children")
                # Focus search on this container's children
                for child in children:
                    self._search_children_for_skin_patterns(child, skin_elements, league_rect, depth + 1, current_path)
                return
            
            # Check if this is the skin list container (ListControl with multiple children)
            if (control.ControlTypeName == "ListControl" and 
                control.FrameworkId == "Chrome"):
                children = control.GetChildren()
                # Check if this ListControl contains skin-like elements
                skin_count = 0
                for child in children:
                    if (child.ControlTypeName == "ListItemControl" and 
                        child.FrameworkId == "Chrome"):
                        skin_count += 1
                
                if skin_count >= 3:  # Likely a skin list if it has 3+ list items
                    print(f"[FOUND] Skin list container at ({control.BoundingRectangle.xcenter()}, {control.BoundingRectangle.ycenter()}) with {len(children)} children ({skin_count} list items)")
                    print(f"[DEEP] Searching DEEPLY into each list item...")
                    # Focus search on this container's children - GO DEEP!
                    for i, child in enumerate(children):
                        print(f"[DEEP] Searching list item {i+1}/{len(children)}...")
                        self._search_children_for_skin_patterns(child, skin_elements, league_rect, depth + 1, current_path)
                    return
            
            # Check if this control matches our skin pattern
            if self._is_skin_text_control(control, league_rect):
                skin_elements.append(control)
                print(f"[FOUND] Skin element: '{control.Name}' at ({control.BoundingRectangle.xcenter()}, {control.BoundingRectangle.ycenter()})")
                print(f"[SKIN_PATH] {current_path}")
            
            # Recursively search children
            children = control.GetChildren()
            # Only log children count for important containers
            if (control.ControlTypeName == "ListControl" or 
                control.ControlTypeName == "ListItemControl" or
                depth <= 3):
                print(f"{indent}[DEBUG] Has {len(children)} children")
            for child in children:
                self._search_children_for_skin_patterns(child, skin_elements, league_rect, depth + 1, current_path)
        except Exception as e:
            # Only log errors for important searches
            if (control.ControlTypeName == "ListControl" or 
                control.ControlTypeName == "ListItemControl" or
                depth <= 3):
                print(f"[DEBUG] Error in search: {e}")
    
    def _is_skin_text_control(self, control, league_rect):
        """Ultra-fast skin detection - minimal checks only."""
        try:
            name = control.Name
            if not name or len(name.strip()) < 3:
                return False
            
            # Quick UI text filter
            name_lower = name.lower().strip()
            if name_lower in ["lol", "tft", "position", "assignée", "préparez", "équipement", 
                             "bannissements", "équipe", "trier", "nom", "aléatoire", "quitter",
                             "voir", "compétences", "connexion", "cliquer", "entrée", "n'oubliez",
                             "jamais", "mot", "passe", "aider", "sélection", "champions", "renvoyé",
                             "salon", "groupe", "difficile", "mode", "aveugle", "5c5", "6", "1"]:
                return False
            
            # Must be Chrome framework
            if control.FrameworkId != "Chrome":
                return False
            
            # Must be enabled and visible
            if not control.IsEnabled or control.IsOffscreen:
                return False
            
            # Check if it looks like a skin name (contains spaces, dashes, or special chars)
            if (" " in name or "-" in name or "'" in name or 
                any(char in name for char in ["é", "è", "à", "ç"])):
                return True
            
            # Single word but longer than 4 characters
            if len(name.strip()) > 4:
                return True
            
            return False
            
        except Exception:
            return False
    
    def _search_children_for_text_controls(self, control, skin_elements, league_rect, depth=0):
        """Recursively search for TextControl elements within League bounds."""
        if depth > 10:  # Prevent infinite recursion
            return
            
        try:
            if control.ControlTypeName == "TextControl":
                # Check if this control is within the League client bounds
                control_rect = control.BoundingRectangle
                if (control_rect.left >= league_rect.left and 
                    control_rect.top >= league_rect.top and 
                    control_rect.right <= league_rect.right and 
                    control_rect.bottom <= league_rect.bottom):
                    skin_elements.append(control)
            
            # Recursively search children
            children = control.GetChildren()
            for child in children:
                self._search_children_for_text_controls(child, skin_elements, league_rect, depth + 1)
        except:
            pass
    
    def monitor_skin_elements(self, duration: int = 30):
        """Monitor skin elements automatically without requiring mouse hover."""
        if not self.find_league_client():
            return
        
        print(f"\n[INFO] Starting automatic skin monitoring for {duration} seconds...")
        print("Searching for skin elements in League client...")
        
        # Find all skin elements
        skin_elements = self.find_skin_elements_in_league()
        
        if not skin_elements:
            print("[WARNING] No skin elements found. Try navigating to champion select or collection screen.")
            return
        
        print(f"[INFO] Monitoring {len(skin_elements)} skin elements...")
        print("Press Ctrl+C to stop early.\n")
        
        start_time = time.time()
        last_detected_skins = set()
        
        try:
            while time.time() - start_time < duration and self.running:
                timestamp = datetime.now().strftime("%H:%M:%S")
                current_skins = set()
                
                # Check each skin element
                for element in skin_elements:
                    try:
                        if element.Exists():
                            name = element.Name
                            if name and name.strip():
                                current_skins.add(name)
                                
                                # Check if this is a new skin detection
                                if name not in last_detected_skins:
                                    print(f"[{timestamp}] Skin: {name}")
                    except:
                        continue
                
                # Update the set of detected skins
                last_detected_skins = current_skins
                
                time.sleep(0.5)  # Check every 500ms
                
                # Check if we should stop
                if not self.running:
                    break
                
        except KeyboardInterrupt:
            print("\n[STOPPED] Monitoring stopped by user.")
    
    def monitor_hovered_skin(self, duration: int = 30):
        """Monitor for hovered skin information for a specified duration."""
        if not self.find_league_client():
            return
        
        print(f"\n[INFO] Monitoring for hovered skin information for {duration} seconds...")
        print("Hover over skins in the League client to detect them.")
        print("Press Ctrl+C to stop early.\n")
        
        start_time = time.time()
        last_detected_skin = None
        last_control_info = None
        
        try:
            while time.time() - start_time < duration and self.running:
                control = self.get_control_under_cursor()
                
                if control:
                    # Create a unique identifier for this control
                    current_control_info = f"{control.Name} ({control.ControlTypeName})"
                    
                    # Only show control info if it changed
                    if current_control_info != last_control_info:
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        in_league = self.is_control_in_league_client(control)
                        
                        print(f"[{timestamp}] ===== CONTROL DETECTED =====")
                        print(f"Control: {current_control_info}")
                        print(f"In League: {in_league}")
                        
                        # Get ALL possible information about the control
                        try:
                            print(f"Name: '{control.Name}'")
                            print(f"Control Type: {control.ControlTypeName}")
                            print(f"Automation ID: '{control.AutomationId}'")
                            print(f"Class Name: '{control.ClassName}'")
                            print(f"Framework ID: '{control.FrameworkId}'")
                            print(f"Localized Control Type: '{control.LocalizedControlType}'")
                            print(f"Bounding Rectangle: {control.BoundingRectangle}")
                            print(f"  - Left: {control.BoundingRectangle.left}")
                            print(f"  - Top: {control.BoundingRectangle.top}")
                            print(f"  - Right: {control.BoundingRectangle.right}")
                            print(f"  - Bottom: {control.BoundingRectangle.bottom}")
                            print(f"  - Width: {control.BoundingRectangle.width()}")
                            print(f"  - Height: {control.BoundingRectangle.height()}")
                            print(f"  - Center X: {control.BoundingRectangle.xcenter()}")
                            print(f"  - Center Y: {control.BoundingRectangle.ycenter()}")
                            
                            # Try to get clickable point
                            try:
                                clickable_point = control.GetClickablePoint()
                                print(f"Clickable Point: {clickable_point}")
                            except:
                                print("Clickable Point: Not available")
                            
                            # Try to get position
                            try:
                                position = control.GetPosition()
                                print(f"Position: {position}")
                            except:
                                print("Position: Not available")
                            
                            # Check if it's enabled, visible, etc.
                            print(f"Is Enabled: {control.IsEnabled}")
                            print(f"Is Offscreen: {control.IsOffscreen}")
                            print(f"Has Keyboard Focus: {control.IsKeyboardFocusable}")
                            print(f"Is Content Element: {control.IsContentElement}")
                            print(f"Is Control Element: {control.IsControlElement}")
                            
                            # Try different patterns
                            patterns_available = []
                            pattern_methods = [
                                'GetValuePattern', 'GetTextPattern', 'GetLegacyIAccessiblePattern',
                                'GetInvokePattern', 'GetSelectionPattern', 'GetTogglePattern',
                                'GetExpandCollapsePattern', 'GetScrollPattern', 'GetWindowPattern'
                            ]
                            
                            for pattern_method in pattern_methods:
                                try:
                                    pattern = getattr(control, pattern_method)()
                                    if pattern:
                                        patterns_available.append(pattern_method.replace('Get', '').replace('Pattern', ''))
                                except:
                                    pass
                            
                            print(f"Available Patterns: {', '.join(patterns_available) if patterns_available else 'None'}")
                            
                            # Try to get value, text, and other content
                            try:
                                value_pattern = control.GetValuePattern()
                                if value_pattern:
                                    print(f"Value: '{value_pattern.Value}'")
                            except:
                                print("Value: Not available")
                            
                            try:
                                text_pattern = control.GetTextPattern()
                                if text_pattern:
                                    print(f"Text: '{text_pattern.GetText()}'")
                            except:
                                print("Text: Not available")
                            
                            try:
                                legacy_pattern = control.GetLegacyIAccessiblePattern()
                                if legacy_pattern:
                                    print(f"Legacy Name: '{legacy_pattern.Name}'")
                                    print(f"Legacy Value: '{legacy_pattern.Value}'")
                                    print(f"Legacy Description: '{legacy_pattern.Description}'")
                                    print(f"Legacy Role: '{legacy_pattern.Role}'")
                                    print(f"Legacy State: '{legacy_pattern.State}'")
                            except:
                                print("Legacy IAccessible: Not available")
                            
                            # Get parent information
                            try:
                                parent = control.GetParentControl()
                                if parent:
                                    print(f"Parent: '{parent.Name}' ({parent.ControlTypeName})")
                                else:
                                    print("Parent: None")
                            except:
                                print("Parent: Error getting parent")
                            
                            # Get children count
                            try:
                                children = control.GetChildren()
                                print(f"Children Count: {len(children)}")
                                if len(children) > 0:
                                    print("Children:")
                                    for i, child in enumerate(children[:5]):  # Show first 5 children
                                        try:
                                            print(f"  {i+1}. '{child.Name}' ({child.ControlTypeName})")
                                        except:
                                            print(f"  {i+1}. [Error reading child]")
                                    if len(children) > 5:
                                        print(f"  ... and {len(children) - 5} more children")
                            except:
                                print("Children: Error getting children")
                            
                        except Exception as e:
                            print(f"Error getting detailed info: {e}")
                        
                        print("=" * 50)
                        last_control_info = current_control_info
                    
                    # Always check for skin detection (even on same control)
                    in_league = self.is_control_in_league_client(control)
                    if in_league:
                        skin_name = self.find_skin_in_parent_hierarchy(control)
                        if skin_name and skin_name != last_detected_skin:
                            timestamp = datetime.now().strftime("%H:%M:%S")
                            print(f"[{timestamp}] [DETECTED] Skin: {skin_name}")
                            last_detected_skin = skin_name
                            print("=" * 30)
                
                time.sleep(0.1)  # Small delay to prevent excessive CPU usage
                
                # Check if we should stop
                if not self.running:
                    break
                
        except KeyboardInterrupt:
            print("\n[STOPPED] Monitoring stopped by user.")
    
    def is_control_in_league_client(self, control: auto.Control) -> bool:
        """Check if the control belongs to the League of Legends client."""
        try:
            # Method 1: Check if control is within League window bounds
            if self.client_window and self.client_window.Exists():
                league_rect = self.client_window.BoundingRectangle
                control_rect = control.BoundingRectangle
                
                # Check if control is within League window bounds
                if (control_rect.left >= league_rect.left and 
                    control_rect.top >= league_rect.top and 
                    control_rect.right <= league_rect.right and 
                    control_rect.bottom <= league_rect.bottom):
                    return True
            
            # Method 2: Walk up the parent hierarchy
            current = control
            for _ in range(15):
                try:
                    if current.Name == "League of Legends" or current.ClassName == "RCLIENT":
                        return True
                    
                    if hasattr(current, 'GetTopLevelControl'):
                        top_level = current.GetTopLevelControl()
                        if top_level and (top_level.Name == "League of Legends" or top_level.ClassName == "RCLIENT"):
                            return True
                    
                    current = current.GetParentControl()
                    if not current:
                        break
                except:
                    break
            
            return False
        except:
            return False
    
    def get_detailed_control_info(self, control: auto.Control):
        """Get detailed information about a control for debugging."""
        print("[DEBUG] Detailed Control Information:")
        print(f"   Name: {control.Name}")
        print(f"   Control Type: {control.ControlTypeName}")
        print(f"   Automation ID: {control.AutomationId}")
        print(f"   Class Name: {control.ClassName}")
        print(f"   Bounding Rectangle: {control.BoundingRectangle}")
        
        # Try different patterns
        patterns = ['ValuePattern', 'TextPattern', 'LegacyIAccessiblePattern', 'InvokePattern']
        for pattern_name in patterns:
            try:
                pattern = getattr(control, f'Get{pattern_name}')()
                if pattern:
                    print(f"   {pattern_name}: Available")
            except:
                pass

def main():
    print("League of Legends Skin Detector")
    print("=" * 40)
    
    detector = LeagueSkinDetector()
    
    if not detector.find_league_client():
        print("\nPlease make sure League of Legends client is running and try again.")
        return
    
    print("\nChoose detection mode:")
    print("1. Automatic skin detection (finds all skins automatically)")
    print("2. Hover-based detection (detect skins by hovering)")
    
    try:
        choice = input("\nEnter your choice (1-2): ").strip()
    except (EOFError, KeyboardInterrupt):
        # If no input available (like in non-interactive environment), default to hover-based
        choice = "2"
        print("2")  # Echo the choice
    
    if choice == "1":
        print("\nStarting automatic skin detection...")
        print("The script will find and monitor all skin elements automatically.")
        print("Press Ctrl+C to stop.\n")
        try:
            detector.monitor_skin_elements(999999)  # Very long duration, effectively infinite
        except KeyboardInterrupt:
            print("\n[STOPPED] Skin detection stopped by user.")
        except Exception as e:
            print(f"- Error: {e}")
    elif choice == "2":
        print("\nStarting hover-based skin detection...")
        print("Hover over skins in the League client to detect them.")
        print("Press Ctrl+C to stop.\n")
        try:
            detector.monitor_hovered_skin(999999)  # Very long duration, effectively infinite
        except KeyboardInterrupt:
            print("\n[STOPPED] Skin detection stopped by user.")
        except Exception as e:
            print(f"- Error: {e}")
    else:
        print("Invalid choice. Using hover-based detection by default.")
        try:
            detector.monitor_hovered_skin(999999)
        except KeyboardInterrupt:
            print("\n[STOPPED] Skin detection stopped by user.")
        except Exception as e:
            print(f"- Error: {e}")

if __name__ == "__main__":
    main()
