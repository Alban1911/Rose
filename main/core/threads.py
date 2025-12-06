#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Thread initialization and management
"""

from threads import PhaseThread, WSEventThread, LCUMonitorThread
from pengu import PenguSkinMonitorThread
from analytics import AnalyticsThread
from utils.threading.thread_manager import ThreadManager
from utils.core.logging import get_logger
from config import PHASE_POLL_INTERVAL_DEFAULT, WS_PING_TIMEOUT_DEFAULT

log = get_logger()


def initialize_threads(lcu, state, args, injection_manager, skin_scraper, app_status, on_lcu_disconnected):
    """
    Initialize and start all application threads
    
    Returns:
        Tuple of (thread_manager, t_phase, t_ui, t_ws, t_lcu_monitor)
    """
    # Initialize thread manager for organized thread lifecycle
    thread_manager = ThreadManager()
    
    # Create and register threads
    t_phase = PhaseThread(lcu, state, interval=1.0/max(PHASE_POLL_INTERVAL_DEFAULT, args.phase_hz), 
                         log_transitions=False, injection_manager=injection_manager, skin_scraper=skin_scraper, db=None)
    thread_manager.register("Phase", t_phase)
    
    t_ui = PenguSkinMonitorThread(state, lcu, skin_scraper=skin_scraper, injection_manager=injection_manager)
    state.ui_skin_thread = t_ui  # Store reference for access during champion exchange
    thread_manager.register("Pengu Skin Monitor", t_ui, stop_method=t_ui.stop)
    
    t_ws = WSEventThread(lcu, state, ping_interval=args.ws_ping, 
                        ping_timeout=WS_PING_TIMEOUT_DEFAULT, timer_hz=args.timer_hz, 
                        fallback_ms=args.fallback_loadout_ms, injection_manager=injection_manager, 
                        skin_scraper=skin_scraper, app_status=app_status)
    thread_manager.register("WebSocket", t_ws, stop_method=t_ws.stop)
    
    # Language callback to update shared state
    def on_language_detected(language: str):
        """Callback when language is detected from LCU"""
        if language:
            # Extract language code from locale (e.g., 'en_US' -> 'en')
            language_code = language.split('_')[0] if '_' in language else language
            state.current_language = language_code
            log.info(f"[Main] Language detected and set: {language_code} (from {language})")
        else:
            log.warning("[Main] Language detection returned None")
    
    t_lcu_monitor = LCUMonitorThread(lcu, state, on_language_detected, t_ws, 
                                      db=None, skin_scraper=skin_scraper, injection_manager=injection_manager,
                                      disconnect_callback=on_lcu_disconnected)
    thread_manager.register("LCU Monitor", t_lcu_monitor)
    
    # Initialize analytics thread
    t_analytics = AnalyticsThread(state)
    thread_manager.register("Analytics", t_analytics, stop_method=t_analytics.stop)
    
    # Start all threads
    thread_manager.start_all()
    
    log.info("System ready")
    
    # Wait for PenguSkinMonitor thread to be ready (servers started)
    if t_ui and hasattr(t_ui, 'ready_event'):
        t_ui.ready_event.wait(timeout=5.0)  # Wait up to 5 seconds for servers to start
    
    # Mark app as fully ready after all threads and servers are initialized
    app_status.mark_download_process_complete()
    
    return thread_manager, t_phase, t_ui, t_ws, t_lcu_monitor

