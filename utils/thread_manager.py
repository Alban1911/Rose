#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Thread Manager - Modern threading patterns for application threads
Provides controlled startup, shutdown, and lifecycle management
"""

# Standard library imports
import threading
import time
from dataclasses import dataclass
from typing import List, Tuple, Optional, Callable

# Local imports
from config import THREAD_JOIN_TIMEOUT_S
from utils.logging import get_logger, log_success, log_action

log = get_logger()


@dataclass
class ManagedThread:
    """Represents a managed thread with metadata"""
    name: str
    thread: threading.Thread
    stop_method: Optional[Callable] = None  # Optional method to call before stopping


class ThreadManager:
    """
    Manages application threads with controlled lifecycle
    
    Provides:
    - Organized thread registration
    - Graceful shutdown with timeout
    - Thread status monitoring
    - Automatic cleanup on exit
    """
    
    def __init__(self):
        self.threads: List[ManagedThread] = []
        self.lock = threading.Lock()
        
    def register(self, name: str, thread: threading.Thread, 
                 stop_method: Optional[Callable] = None) -> None:
        """
        Register a thread for management
        
        Args:
            name: Human-readable thread name for logging
            thread: The thread instance
            stop_method: Optional method to call for graceful stop (e.g., ws.stop())
        """
        with self.lock:
            managed = ManagedThread(name=name, thread=thread, stop_method=stop_method)
            self.threads.append(managed)
            log.debug(f"Registered thread: {name}")
    
    def start_all(self) -> None:
        """Start all registered threads"""
        with self.lock:
            for managed in self.threads:
                if not managed.thread.is_alive():
                    managed.thread.start()
                    log.debug(f"Started thread: {managed.name}")
    
    def stop_all(self, timeout: float = THREAD_JOIN_TIMEOUT_S) -> Tuple[List[str], float]:
        """
        Stop all threads gracefully with timeout
        
        Args:
            timeout: Maximum time to wait for each thread (seconds)
            
        Returns:
            Tuple of (list of threads still alive, total elapsed time)
        """
        cleanup_start = time.time()
        still_alive = []
        
        log_action(log, "Stopping all managed threads", "🧹")
        
        with self.lock:
            threads_copy = list(self.threads)
        
        # First, call stop methods for threads that have them
        for managed in threads_copy:
            if managed.stop_method and managed.thread.is_alive():
                try:
                    log.debug(f"Calling stop method for {managed.name}")
                    managed.stop_method()
                except Exception as e:
                    log.warning(f"Error calling stop method for {managed.name}: {e}")
        
        # Then wait for all threads to finish
        for managed in threads_copy:
            if managed.thread.is_alive():
                log.debug(f"Waiting for {managed.name} thread...")
                managed.thread.join(timeout=timeout)
                
                if managed.thread.is_alive():
                    log.warning(f"{managed.name} thread did not stop within {timeout}s timeout")
                    still_alive.append(managed.name)
                else:
                    log_success(log, f"{managed.name} thread stopped", "✓")
        
        elapsed = time.time() - cleanup_start
        return still_alive, elapsed
    
    @property
    def alive_threads(self) -> List[str]:
        """Get list of threads that are still alive"""
        with self.lock:
            return [m.name for m in self.threads if m.thread.is_alive()]
    
    def wait_for_all(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for all threads to complete
        
        Args:
            timeout: Maximum time to wait (None = wait forever)
            
        Returns:
            True if all threads completed, False if timeout reached
        """
        start = time.time()
        
        with self.lock:
            threads_copy = list(self.threads)
        
        for managed in threads_copy:
            if timeout is not None:
                remaining = timeout - (time.time() - start)
                if remaining <= 0:
                    return False
                managed.thread.join(timeout=remaining)
            else:
                managed.thread.join()
        
        return all(not m.thread.is_alive() for m in threads_copy)


def create_daemon_thread(target: Callable, name: str = None) -> threading.Thread:
    """
    Factory function to create a daemon thread with consistent settings
    
    Args:
        target: The function to run in the thread
        name: Optional thread name
        
    Returns:
        Configured daemon thread
    """
    thread = threading.Thread(target=target, daemon=True, name=name)
    return thread

