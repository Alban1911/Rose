#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Launcher package
Main entry point for launcher functionality
"""

# Re-export main functions for backward compatibility
from .core.launcher import run_launcher
from .updater import auto_update

# Re-export subpackage classes for convenience
from .update.update_sequence import UpdateSequence
from .update.update_downloader import UpdateDownloader
from .update.update_installer import UpdateInstaller
from .update.github_client import GitHubClient
from .ui.update_dialog import UpdateDialog
from .sequences.hash_check_sequence import HashCheckSequence
from .sequences.skin_sync_sequence import SkinSyncSequence

__all__ = [
    'run_launcher',
    'auto_update',
    'UpdateSequence',
    'UpdateDownloader',
    'UpdateInstaller',
    'GitHubClient',
    'UpdateDialog',
    'HashCheckSequence',
    'SkinSyncSequence',
]
