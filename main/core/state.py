#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Application state management
"""


class AppState:
    """Application state to replace global variables"""
    def __init__(self):
        self.shutting_down = False
        self.lock_file = None
        self.lock_file_path = None


# Global app state instance
_app_state = AppState()


def get_app_state() -> AppState:
    """Get the global application state instance"""
    return _app_state

