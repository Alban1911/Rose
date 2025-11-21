#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Core launcher package
Contains the main launcher entry point
"""

from .launcher import run_launcher
from ..updater import auto_update

__all__ = ['run_launcher', 'auto_update']

