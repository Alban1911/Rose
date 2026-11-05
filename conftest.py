"""Test-wide safety: never touch a real League game from the test suite."""
import pytest


@pytest.fixture(autouse=True)
def _no_real_game_hold(monkeypatch):
    # The patcher's game hold suspends the real "League of Legends.exe" when
    # one runs: tests drive it explicitly instead
    monkeypatch.setattr("injection.overlay.overlay_manager.HOLD_WATCH", False)
