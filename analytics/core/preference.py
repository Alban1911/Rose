#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The user's analytics choice, kept as [General] analytics_enabled in config.ini."""

from config import get_config_option, set_config_option

_OFF_VALUES = {"0", "false", "no", "off"}


def analytics_opted_in() -> bool:
    """Whether the user lets Rose send analytics; on until they turn it off."""
    value = get_config_option("General", "analytics_enabled")
    return value is None or value.strip().lower() not in _OFF_VALUES


def set_analytics_opted_in(enabled: bool) -> None:
    set_config_option("General", "analytics_enabled", "true" if enabled else "false")
