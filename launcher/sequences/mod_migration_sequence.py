
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from utils.core.logging import get_logger, get_named_logger
from utils.system.win32_base import user32

if TYPE_CHECKING:
    from injection.mods.migration import MigrationReport, Step
    from injection.mods.storage import ModStorageService
    from injection.overlay.ltk_library import LtkLibrary

log = get_logger()
updater_log = get_named_logger("updater", prefix="log_updater")

MB_OK = 0x00000000
MB_YESNO = 0x00000004
MB_ICONQUESTION = 0x00000020
MB_ICONWARNING = 0x00000030
MB_TOPMOST = 0x00040000
IDYES = 6

TITLE = "Rose - your mods"
BACKUP_QUESTION = (
    "Rose now keeps the mods you added in LTK Manager's library, without a copy of its own, "
    "and moves your mods there now.\n\n"
    "Do you want a backup of your mods on your desktop first? ({size}, {free} free)\n\n"
    "Yes: copy them to a \"Rose mods backup\" folder on your desktop, then move them.\n"
    "No: move them without a backup."
)
STEP_TEXT_BY_STEP_VALUE = {
    "convert": "Packing your mods ({index}/{total}): {name}",
    "connect": "Opening LTK Manager to move your mods…",
    "backup": "Backing up your mods to your desktop…",
    "move": "Moving your mods into LTK Manager ({index}/{total}): {name}",
}


class _DialogUi:
    """The migration's MigrationUi in the launcher's UpdateDialog."""

    def __init__(self, dialog) -> None:
        self._dialog = dialog
        self._detail: Optional[str] = None

    def progress(self, step: Step, index: int = 0, total: int = 0, name: str = "",
                 done_bytes: int = 0, total_bytes: int = 0) -> None:
        detail = STEP_TEXT_BY_STEP_VALUE[step.value].format(index=index, total=total, name=name)
        if detail != self._detail:
            self._detail = detail
            self._dialog.set_detail(detail)
        if total_bytes:
            self._dialog.update_transfer_progress(done_bytes, total_bytes)
        else:
            self._dialog.clear_transfer_text()
        self._dialog.pump_messages()

    def ask_backup(self, size: int, free: int) -> bool:
        from injection.mods.migration import size_text

        self._detail = "Back up your mods?"
        self._dialog.set_detail(self._detail)
        self._dialog.clear_transfer_text()
        self._dialog.pump_messages()
        answer = user32.MessageBoxW(
            self._dialog.hwnd or None,
            BACKUP_QUESTION.format(size=size_text(size), free=size_text(free)),
            TITLE,
            MB_YESNO | MB_ICONQUESTION | MB_TOPMOST,
        )
        accepted = answer == IDYES
        updater_log.info(f"Mods backup prompt answered: {'yes' if accepted else 'no'} "
                         f"({size_text(size)}, {size_text(free)} free).")
        return accepted

    def notify(self, message: str) -> None:
        updater_log.warning(f"Mods migration notice shown to user: {message}")
        user32.MessageBoxW(self._dialog.hwnd or None, message, TITLE, MB_OK | MB_ICONWARNING | MB_TOPMOST)


class ModMigrationSequence:
    """Moves the saved mods Rose still holds into LTK Manager's library.

    Rose starts whatever happens: a mod not moved stays in Rose, pending,
    works as before, and is moved at a later start. *storage* and *library*
    are Rose's own by default."""

    def __init__(self, storage: Optional[ModStorageService] = None,
                 library: Optional[LtkLibrary] = None) -> None:
        self._storage = storage
        self._library = library

    def perform(self, dialog) -> Optional[MigrationReport]:
        """Run the migration in *dialog*; its MigrationReport, or None when
        it failed."""
        try:
            from injection.mods.migration import migrate_saved_mods
            from injection.mods.storage import ModStorageService
            from injection.overlay.ltf_session import LtfHost
            from injection.overlay.ltk_library import LtkLibrary
            from utils.core.paths import get_injection_dir, get_tools_dir

            storage = self._storage or ModStorageService()
            library = self._library or LtkLibrary(LtfHost(get_tools_dir(), get_injection_dir()))
            report = migrate_saved_mods(storage, library, _DialogUi(dialog))
        except Exception as exc:
            log.error(f"[MIGRATE] Could not move the saved mods into LTK Manager: {exc}", exc_info=True)
            return None
        finally:
            dialog.clear_transfer_text()
            dialog.pump_messages()
        updater_log.info(f"Mods migration: {len(report.moved)} moved, {len(report.failed)} left in Rose"
                         f"{f', skipped ({report.skipped_reason})' if report.skipped_reason else ''}.")
        return report
