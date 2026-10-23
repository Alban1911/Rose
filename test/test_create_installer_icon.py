import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


SPEC = importlib.util.spec_from_file_location('rose_installer_icon_test', Path(__file__).resolve().parents[1] / 'scripts/create_installer.py')
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class InstallerIconTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / 'home'
        compiler = self.home / 'AppData/Local/Programs/Inno Setup 6/ISCC.exe'
        compiler.parent.mkdir(parents=True)
        compiler.touch()
        (self.root / 'assets').mkdir()
        (self.root / 'dist/Rose').mkdir(parents=True)
        (self.root / 'installer.iss').write_text('stub')
        self.icon = self.root / 'assets/icon.ico'
        self.png = self.root / 'assets/tray_ready.png'
        self.png.write_bytes(b'png input')

    def build(self, image, pil_available=True):
        def compile_installer(*args, **kwargs):
            (self.root / 'installer/Rose_Setup_1.exe').write_bytes(b'fake installer')
            return SimpleNamespace(returncode=0)

        with patch.object(builder, 'ROOT', self.root), patch.object(Path, 'home', return_value=self.home), \
                patch.object(builder, 'PIL_AVAILABLE', pil_available), \
                patch.object(builder, 'Image', image, create=True), \
                patch.object(builder.subprocess, 'run', side_effect=compile_installer) as compiler, \
                contextlib.redirect_stdout(io.StringIO()):
            result = builder.create_installer()
        return result, compiler

    def test_existing_icon_bytes_are_preserved_and_copied_without_conversion(self):
        self.icon.write_bytes(b'original tracked ico')
        image = Mock()
        image.open.return_value.__enter__ = Mock(return_value=SimpleNamespace(
            save=lambda path, **kwargs: path.write_bytes(b'regenerated icon')))
        image.open.return_value.__exit__ = Mock(return_value=False)
        result, compiler = self.build(image)
        self.assertTrue(result)
        image.open.assert_not_called()
        self.assertEqual(self.icon.read_bytes(), b'original tracked ico')
        self.assertEqual((self.root / 'dist/Rose/icon.ico').read_bytes(), b'original tracked ico')
        compiler.assert_called_once()

    def test_missing_icon_is_generated_from_png_and_copied(self):
        image = Mock()
        image.open.return_value.__enter__ = Mock(return_value=SimpleNamespace(
            save=lambda path, **kwargs: path.write_bytes(b'generated ico')))
        image.open.return_value.__exit__ = Mock(return_value=False)
        result, compiler = self.build(image)
        self.assertTrue(result)
        self.assertEqual(self.icon.read_bytes(), b'generated ico')
        self.assertEqual((self.root / 'dist/Rose/icon.ico').read_bytes(), b'generated ico')
        compiler.assert_called_once()

    def test_conversion_failure_without_an_icon_does_not_compile(self):
        image = Mock()
        image.open.side_effect = OSError('bad PNG')
        result, compiler = self.build(image)
        self.assertFalse(result)
        compiler.assert_not_called()

    def test_existing_icon_works_without_pillow(self):
        self.icon.write_bytes(b'original ico')
        self.assertTrue(self.build(Mock(), pil_available=False)[0])
