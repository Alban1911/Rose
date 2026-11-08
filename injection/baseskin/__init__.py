#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Make a custom skin match the base skin's identity before it is used.

See steps.py for the four things checked, and package.py for how a mod is
read and written. Ported from RoseBin, which applies the same steps to the skins
Rose ships.
"""

from .package import FixResult, fix_mod

__all__ = ["FixResult", "fix_mod"]
