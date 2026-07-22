#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backward-compatible alias for Rose's pseudonymous installation ID."""

from .install_id import get_install_id


def get_machine_id() -> str:
    """Return the pseudonymous installation ID.

    Kept for callers that imported the old function. Rose no longer reads or
    transmits the Windows Machine GUID.
    """
    return get_install_id()


__all__ = ["get_machine_id"]
