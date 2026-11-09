"""Launcher auto-update logic for Rose.

Downloads the latest release ZIP from GitHub and prepares it beside the
installation for a helper to apply once Rose exits.
"""

from __future__ import annotations

from typing import Callable, Optional

from .update.update_sequence import UpdateSequence

# Backward compatibility - maintain the auto_update function signature
def auto_update(
    status_callback: Callable[[str], None],
    progress_callback: Callable[[int], None],
    bytes_callback: Optional[Callable[[int, Optional[int]], None]] = None,
    confirm_callback: Optional[Callable[[str, str], bool]] = None,
) -> bool:
    """Download and install the latest release if a new version is available.

    Returns True when the update helper is ready, False otherwise.
    """
    sequence = UpdateSequence()
    return sequence.perform_update(
        status_callback,
        progress_callback,
        bytes_callback,
        confirm_callback=confirm_callback,
    )
