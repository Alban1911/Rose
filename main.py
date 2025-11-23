#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Main entry point for Rose (delegates to main package)
"""

import sys
from pathlib import Path

# Ensure the project root is in sys.path for proper package resolution
# This fixes import issues when running from different directories
# Only needed in development mode (PyInstaller handles paths automatically)
if not getattr(sys, 'frozen', False):
    _project_root = Path(__file__).parent.absolute()
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

# Import from the modularized main package
from main import main

if __name__ == "__main__":
        main()
