#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Core injection package
Contains the main injection manager and injector
"""

from .manager import InjectionManager
from .injector import SkinInjector

__all__ = ['InjectionManager', 'SkinInjector']

