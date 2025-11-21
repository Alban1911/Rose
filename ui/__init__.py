#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UI Package - Main entry point for UI components

This package is organized into subpackages:
- core: Main UI orchestration and lifecycle management
- chroma: Chroma selection and display functionality
- handlers: Feature-specific handlers (historic mode, randomization, skin display)
"""

# Public API exports
from ui.core.user_interface import UserInterface, get_user_interface
from ui.chroma.selector import ChromaSelector, get_chroma_selector, init_chroma_selector

__all__ = [
    'UserInterface',
    'get_user_interface',
    'ChromaSelector',
    'get_chroma_selector',
    'init_chroma_selector',
]

