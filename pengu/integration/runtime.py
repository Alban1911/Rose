"""Pengu runtime asset and configuration management."""

from __future__ import annotations

import configparser
import os
import shutil
import sys
from pathlib import Path
from typing import Iterable

from config import get_config_file_path
from utils.core.logging import get_logger
from utils.core.paths import get_app_dir, get_state_dir, get_user_data_dir


log = get_logger("pengu")
_SESSION_FILE = get_state_dir() / "pengu_session.json"
_LEGACY_PENGU_LOGS = ("rose.log", "rose.log.old", "crash.log", "pengu.log")
_PLUGIN_ENTRYPOINT = "index.js"
_PLUGIN_ENTRYPOINT_DISABLED = "index.js_"
_PLUGIN_ENTRYPOINT_BUNDLED_BACKUP = "index.js.bundled"

_OBSOLETE_LOADER_FILES = (
    "Pengu Loader.exe",
    "Pengu Loader.exe.config",
    "ModernWpf.dll",
    "ModernWpf.Controls.dll",
    "Ookii.Dialogs.Wpf.dll",
    "System.ValueTuple.dll",
)


def _plugin_directory(name: str, directory: Path | None = None) -> Path | None:
    """Resolve a plugin directory while preventing path traversal."""
    if not isinstance(name, str) or not name or name in {".", ".."}:
        return None
    if "/" in name or "\\" in name:
        return None

    plugins_dir = (directory or get_runtime_dir()) / "plugins"
    plugin_dir = plugins_dir / name
    try:
        if plugin_dir.parent.resolve() != plugins_dir.resolve():
            return None
    except OSError:
        return None
    return plugin_dir if plugin_dir.is_dir() else None


def list_plugins(directory: Path | None = None) -> list[dict[str, object]]:
    """Return installed Pengu plugins and their current enabled state."""
    plugins_dir = (directory or get_runtime_dir()) / "plugins"
    if not plugins_dir.is_dir():
        return []

    plugins: list[dict[str, object]] = []
    for plugin_dir in sorted(plugins_dir.iterdir(), key=lambda path: path.name.casefold()):
        if not plugin_dir.is_dir():
            continue
        enabled_path = plugin_dir / _PLUGIN_ENTRYPOINT
        disabled_path = plugin_dir / _PLUGIN_ENTRYPOINT_DISABLED
        bundled_path = plugin_dir / _PLUGIN_ENTRYPOINT_BUNDLED_BACKUP
        if not (enabled_path.exists() or disabled_path.exists() or bundled_path.exists()):
            continue
        plugins.append({
            "name": plugin_dir.name,
            "enabled": enabled_path.exists() and not disabled_path.exists(),
        })
    return plugins


def set_plugin_enabled(name: str, enabled: bool, directory: Path | None = None) -> bool:
    """Enable or disable one plugin using the entrypoint convention."""
    if not isinstance(enabled, bool):
        return False
    plugin_dir = _plugin_directory(name, directory)
    if plugin_dir is None:
        return False

    active_path = plugin_dir / _PLUGIN_ENTRYPOINT
    disabled_path = plugin_dir / _PLUGIN_ENTRYPOINT_DISABLED
    bundled_path = plugin_dir / _PLUGIN_ENTRYPOINT_BUNDLED_BACKUP
    try:
        if enabled:
            if active_path.exists():
                if disabled_path.exists():
                    disabled_path.unlink()
                return True
            if disabled_path.exists():
                disabled_path.replace(active_path)
                return True
            if bundled_path.exists():
                bundled_path.replace(active_path)
                return True
            return False

        if disabled_path.exists():
            if active_path.exists():
                bundled_path.unlink(missing_ok=True)
                active_path.replace(bundled_path)
            return True
        if active_path.exists():
            active_path.replace(disabled_path)
            return True
        return False
    except OSError as exc:
        log.warning("Could not change plugin %s state: %s", name, exc)
        return False


def get_bundled_dir() -> Path | None:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(meipass) / "Pengu Loader"
        if candidate.is_dir():
            return candidate

    if getattr(sys, "frozen", False):
        candidate = get_app_dir() / "_internal" / "Pengu Loader"
        if candidate.is_dir():
            return candidate
        candidate = get_app_dir() / "Pengu Loader"
        if candidate.is_dir():
            return candidate

    candidate = Path(__file__).resolve().parents[2] / "Pengu Loader"
    return candidate if candidate.is_dir() else None


def _runtime_dir() -> Path:
    if not getattr(sys, "frozen", False):
        bundled = get_bundled_dir()
        if bundled is not None:
            return bundled
    return get_user_data_dir() / "Pengu Loader"


def _remove_legacy_logs(directory: Path) -> None:
    for filename in _LEGACY_PENGU_LOGS:
        try:
            (directory / filename).unlink(missing_ok=True)
        except OSError as exc:
            log.debug("Could not remove legacy Pengu log %s: %s", directory / filename, exc)


def _snapshot_plugin_state(directory: Path) -> tuple[set[str], set[str]]:
    enabled: set[str] = set()
    disabled: set[str] = set()
    plugins_dir = directory / "plugins"
    if not plugins_dir.is_dir():
        return enabled, disabled

    for plugin_dir in plugins_dir.iterdir():
        if not plugin_dir.is_dir():
            continue
        enabled_path = plugin_dir / _PLUGIN_ENTRYPOINT
        disabled_path = plugin_dir / _PLUGIN_ENTRYPOINT_DISABLED
        if disabled_path.exists():
            disabled.add(plugin_dir.name)
        elif enabled_path.exists():
            enabled.add(plugin_dir.name)
    return enabled, disabled


def _sanitize_disabled_plugin(directory: Path) -> None:
    plugins_dir = directory / "plugins"
    if not plugins_dir.is_dir():
        return

    for plugin_dir in plugins_dir.iterdir():
        if not plugin_dir.is_dir():
            continue
        enabled = plugin_dir / _PLUGIN_ENTRYPOINT
        disabled = plugin_dir / _PLUGIN_ENTRYPOINT_DISABLED
        if not disabled.exists() or not enabled.exists():
            continue
        backup = plugin_dir / _PLUGIN_ENTRYPOINT_BUNDLED_BACKUP
        try:
            backup.unlink(missing_ok=True)
            enabled.replace(backup)
        except OSError:
            try:
                enabled.unlink()
            except OSError as exc:
                log.debug("Could not preserve disabled plugin %s: %s", plugin_dir, exc)


def _restore_plugin_state(
    directory: Path,
    enabled_plugins: Iterable[str],
    disabled_plugins: Iterable[str],
) -> None:
    plugins_dir = directory / "plugins"
    if not plugins_dir.is_dir():
        return

    for plugin_name in enabled_plugins:
        plugin_dir = plugins_dir / plugin_name
        enabled = plugin_dir / _PLUGIN_ENTRYPOINT
        disabled = plugin_dir / _PLUGIN_ENTRYPOINT_DISABLED
        if enabled.exists() and disabled.exists():
            try:
                disabled.unlink()
            except OSError as exc:
                log.debug("Could not restore enabled plugin %s: %s", plugin_name, exc)

    _sanitize_disabled_plugin(directory)

    for plugin_name in disabled_plugins:
        plugin_dir = plugins_dir / plugin_name
        if (plugin_dir / _PLUGIN_ENTRYPOINT_DISABLED).exists():
            continue
        backup = plugin_dir / _PLUGIN_ENTRYPOINT_BUNDLED_BACKUP
        if backup.exists():
            try:
                backup.replace(plugin_dir / _PLUGIN_ENTRYPOINT_DISABLED)
            except OSError as exc:
                log.debug("Could not restore disabled plugin %s: %s", plugin_name, exc)


def _remove_obsolete_loader_files(directory: Path) -> None:
    if not getattr(sys, "frozen", False):
        return
    for filename in _OBSOLETE_LOADER_FILES:
        path = directory / filename
        try:
            if path.exists():
                path.unlink()
                log.info("Removed obsolete Pengu loader file: %s", path)
        except OSError as exc:
            log.warning("Could not remove obsolete Pengu loader file %s: %s", path, exc)


def _copy_tree(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    enabled, disabled = _snapshot_plugin_state(destination)
    destination_datastore = destination / "datastore"
    source_datastore = source / "datastore"
    destination_config = destination / "config"
    source_config = source / "config"

    shutil.copytree(
        source,
        destination,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(
            "datastore",
            "config",
            *_OBSOLETE_LOADER_FILES,
        ),
    )

    if not destination_datastore.exists() and source_datastore.exists():
        shutil.copy2(source_datastore, destination_datastore)
    if not destination_config.exists() and source_config.exists():
        shutil.copy2(source_config, destination_config)

    _restore_plugin_state(destination, enabled, disabled)


def prepare_runtime() -> Path:
    bundled = get_bundled_dir()
    directory = _runtime_dir()

    if getattr(sys, "frozen", False):
        if bundled is None:
            raise FileNotFoundError("Bundled Pengu runtime directory is missing")
        _copy_tree(bundled, directory)

    directory.mkdir(parents=True, exist_ok=True)
    (directory / "plugins").mkdir(parents=True, exist_ok=True)
    (directory / "datastore").touch(exist_ok=True)
    (directory / "config").touch(exist_ok=True)
    _remove_obsolete_loader_files(directory)
    _remove_legacy_logs(directory)

    core_path = directory / "core.dll"
    if not core_path.is_file():
        raise FileNotFoundError(f"Pengu core.dll is missing: {core_path}")
    return directory


def get_runtime_dir() -> Path:
    return prepare_runtime()


def get_core_path(directory: Path | None = None) -> Path:
    return (directory or get_runtime_dir()) / "core.dll"


def _write_key_value_file(path: Path, key: str, value: str) -> bytes:
    original = path.read_bytes() if path.exists() else b""
    text = original.decode("utf-8", errors="replace")
    lines = text.splitlines()
    output: list[str] = []
    found = False

    for line in lines:
        if "=" in line:
            current_key = line.split("=", 1)[0].strip()
            if current_key.lower() == key.lower():
                output.append(f"{current_key}={value}")
                found = True
                continue
        output.append(line)

    if not found:
        output.append(f"{key}={value}")

    data = ("\n".join(output).rstrip("\n") + "\n").encode("utf-8")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)
    return original


def read_pengu_config(directory: Path | None = None) -> dict[str, str]:
    path = (directory or get_runtime_dir()) / "config"
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            values[key] = value.strip()
    return values


def write_pengu_option(key: str, value: str, directory: Path | None = None) -> bytes:
    if not key or "=" in key or "\n" in key or "\r" in key:
        raise ValueError("Pengu config key is invalid")
    if "\n" in value or "\r" in value:
        raise ValueError("Pengu config value is invalid")
    return _write_key_value_file(
        (directory or get_runtime_dir()) / "config",
        key,
        value,
    )


def write_pengu_config(league_path: str, directory: Path | None = None) -> bytes:
    if not league_path or not league_path.strip():
        raise ValueError("League path is empty")
    path = (directory or get_runtime_dir()) / "config"
    return _write_key_value_file(path, "LeaguePath", league_path.strip())


def _write_rose_config(active: bool, directory: Path) -> bytes:
    path = get_config_file_path()
    original = path.read_bytes() if path.exists() else b""
    config = configparser.ConfigParser()
    config.optionxform = str
    if path.exists():
        config.read(path, encoding="utf-8")
    if not config.has_section("General"):
        config.add_section("General")
    config.set("General", "disabled", "0" if active else "1")
    config.set("General", "loaderpath", str(directory) if active else "")

    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        config.write(handle)
    temporary.replace(path)
    return original


def write_rose_config(active: bool, directory: Path) -> bytes:
    return _write_rose_config(active, directory)


def snapshot_rose_config() -> bytes:
    path = get_config_file_path()
    return path.read_bytes() if path.exists() else b""


def restore_rose_config(original: bytes) -> None:
    path = get_config_file_path()
    if original:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(original)
        temporary.replace(path)
    else:
        path.unlink(missing_ok=True)


def remove_legacy_logs(directory: Path) -> None:
    _remove_legacy_logs(directory)


PENGU_DIR = _runtime_dir()
PENGU_CORE = PENGU_DIR / "core.dll"