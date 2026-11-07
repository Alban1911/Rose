import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location('rose_find_iscc_test', Path(__file__).resolve().parents[1] / 'scripts/create_installer.py')
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class _Key:
    def __init__(self, values=None, children=()):
        self.values = values or {}
        self.children = list(children)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_winreg(uninstall_entries):
    """A winreg whose HKLM Uninstall key lists *uninstall_entries* (name -> values, or None for an
    entry this account may not open)."""
    module = types.SimpleNamespace(
        HKEY_LOCAL_MACHINE='HKLM', HKEY_CURRENT_USER='HKCU',
        KEY_READ=1, KEY_WOW64_64KEY=2, KEY_WOW64_32KEY=4,
    )
    root = _Key(children=list(uninstall_entries))

    def open_key(parent, name, reserved=0, access=0):
        if parent == 'HKLM' and access & module.KEY_WOW64_64KEY:
            return root
        if parent is root:
            values = uninstall_entries[name]
            if values is None:
                raise PermissionError(5, 'Access is denied')
            return _Key(values)
        raise FileNotFoundError(name)

    def query_value(key, name):
        if name not in key.values:
            raise FileNotFoundError(name)
        return key.values[name], 1

    module.OpenKey = open_key
    module.QueryInfoKey = lambda key: (len(key.children), 0, 0)
    module.EnumKey = lambda key, index: key.children[index]
    module.QueryValueEx = query_value
    return module


class FindIsccRegistryTests(unittest.TestCase):
    def test_an_uninstall_entry_that_cannot_be_opened_is_skipped(self):
        """One entry with a restrictive ACL raised out of find_iscc, and the installer build failed."""
        with tempfile.TemporaryDirectory() as temporary:
            inno = Path(temporary) / 'Apps' / 'Inno Setup 6'
            inno.mkdir(parents=True)
            entries = {
                'Locked{0000}': None,
                'Inno Setup 6_is1': {'DisplayName': 'Inno Setup version 6.4.0', 'InstallLocation': str(inno)},
            }
            with patch.dict(sys.modules, {'winreg': fake_winreg(entries)}):
                directories = builder._registered_inno_directories()
        self.assertEqual(directories, [inno])


if __name__ == '__main__':
    unittest.main()
