import json
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lcu.features import language_cache
from lcu.features.language_cache import LanguageCache


class LanguageCacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.installation = self.root / "League"
        self.write("LeagueClient.exe", b"client-build-1")
        self.write("Game/content-metadata.json", b'{"version":"build-1"}')
        self.write("Game/code-metadata.json", b'{"version":"build-1"}')
        self.assets = {
            "Plugins/rcp-be-lol-game-data/pt_BR-assets.wad": b"client Portuguese",
            "Game/DATA/FINAL/Champions/Ahri.pt_BR.wad.client": b"voice Portuguese",
            "Game/DATA/FINAL/UI.pt_BR.wad.client": b"text Portuguese",
            "locales/pt-BR.pak": b"browser Portuguese",
        }
        for name, content in self.assets.items():
            self.write(name, content)
        self.write("Game/DATA/FINAL/UI.wad.client", b"shared assets")
        self.write("Plugins/rcp-be-lol-game-data/en_US-assets.wad", b"English")
        self.write("Config/pt_BR.yaml", b"settings must not be cached")
        self.cache = self.create_cache()

    def write(self, name, content):
        path = self.installation / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def create_cache(self, patchline="live", installation=None):
        return LanguageCache(installation or self.installation, patchline, root=self.root / "cache")

    def manifest(self):
        return self.cache.directory / "pt_BR.json"

    def test_roundtrip_survives_new_service_and_restores_client_and_game(self):
        self.assertEqual(self.cache.save("pt_BR"), len(self.assets))
        for name in self.assets:
            (self.installation / name).unlink()
        self.assertEqual(self.create_cache().restore("pt_BR"), len(self.assets))
        for name, content in self.assets.items():
            self.assertEqual((self.installation / name).read_bytes(), content)
        manifest = json.loads(self.manifest().read_text())
        self.assertEqual({item["path"] for item in manifest["files"]}, set(self.assets))

    def test_cache_miss_does_not_modify_installation(self):
        self.assertEqual(self.cache.restore("pt_BR"), 0)
        self.assertEqual(self.cache.restore("ja_JP"), 0)
        self.assertFalse(self.cache.directory.exists())

    def test_version_change_and_patchline_never_reuse_old_files(self):
        self.cache.save("pt_BR")
        self.assertEqual(self.create_cache("pbe").restore("pt_BR"), 0)
        for name in ("Game/content-metadata.json", "Game/code-metadata.json", "LeagueClient.exe"):
            with self.subTest(name=name):
                original = (self.installation / name).read_bytes()
                self.write(name, b"new build")
                self.assertEqual(self.cache.restore("pt_BR"), 0)
                self.assertEqual(self.create_cache().restore("pt_BR"), 0)
                self.write(name, original)

    def test_another_installation_has_separate_cache(self):
        import shutil
        self.cache.save("pt_BR")
        other = self.root / "OtherLeague"
        shutil.copytree(self.installation, other)
        self.assertEqual(self.create_cache(installation=other).restore("pt_BR"), 0)

    def test_corrupt_or_missing_blob_rejects_entire_entry_before_writing(self):
        self.cache.save("pt_BR")
        manifest = json.loads(self.manifest().read_text())
        blob = self.cache.directory / "blobs" / manifest["files"][-1]["sha256"]
        for name in self.assets:
            (self.installation / name).unlink()
        blob.write_bytes(b"broken")
        self.assertEqual(self.cache.restore("pt_BR"), 0)
        self.assertFalse(any((self.installation / name).exists() for name in self.assets))
        blob.unlink()
        self.assertEqual(self.cache.restore("pt_BR"), 0)

    def test_bad_manifests_and_paths_are_misses(self):
        self.cache.save("pt_BR")
        manifest = json.loads(self.manifest().read_text())
        for name in ("../outside.pt_BR.wad", "C:/outside.pt_BR.wad", "Game/../../outside.pt_BR.wad",
                     "Config/pt_BR.wad", "Game/pt_BR.exe", "Game/UI.en_US.wad.client", "Game\\..\\pt_BR.wad"):
            with self.subTest(name=name):
                manifest["files"][0]["path"] = name
                self.manifest().write_text(json.dumps(manifest))
                self.assertEqual(self.cache.restore("pt_BR"), 0)
        for content in ("{", "null", "[]", '{"files":null}'):
            self.manifest().write_text(content)
            self.assertEqual(self.cache.restore("pt_BR"), 0)

    def test_failed_copy_preserves_previous_manifest_and_installed_file(self):
        self.cache.save("pt_BR")
        previous = self.manifest().read_bytes()
        name = next(iter(self.assets))
        self.write(name, b"updated Portuguese")
        with patch("lcu.features.language_cache.shutil.copy2", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.cache.save("pt_BR")
            self.assertEqual(self.manifest().read_bytes(), previous)
            with self.assertRaises(OSError):
                self.cache.restore("pt_BR")
        self.assertEqual((self.installation / name).read_bytes(), b"updated Portuguese")
        self.assertFalse(list(self.root.rglob(".rose-language-*")))

    def test_unchanged_files_do_not_get_copied_again(self):
        self.cache.save("pt_BR")
        with patch("lcu.features.language_cache.shutil.copy2") as copy:
            self.assertEqual(self.cache.save("pt_BR"), len(self.assets))
            self.assertEqual(self.cache.restore("pt_BR"), len(self.assets))
        copy.assert_not_called()

    def test_scan_failure_does_not_publish_incomplete_manifest(self):
        self.cache.save("pt_BR")
        previous = self.manifest().read_bytes()
        def unreadable(*args, **kwargs):
            kwargs["onerror"](PermissionError("unreadable folder"))
        with patch("lcu.features.language_cache.os.walk", side_effect=unreadable):
            with self.assertRaises(PermissionError):
                self.cache.save("pt_BR")
        self.assertEqual(self.manifest().read_bytes(), previous)

    def test_malformed_manifest_types_and_duplicate_targets_are_misses(self):
        self.cache.save("pt_BR")
        original = json.loads(self.manifest().read_text())
        for name in self.assets:
            (self.installation / name).unlink()
        variants = []
        for key, value in (("path", None), ("path", []), ("sha256", 3),
                           ("size", True), ("size", -1), ("size", "17")):
            candidate = json.loads(json.dumps(original))
            candidate["files"][0][key] = value
            variants.append(candidate)
        for item in (None, [], "not an asset", 17):
            candidate = dict(original, files=[item])
            variants.append(candidate)
        duplicate = dict(original["files"][0])
        duplicate["path"] = duplicate["path"].upper()
        variants.append(dict(original, files=original["files"] + [duplicate]))
        variants.append(dict(original, schema=True))
        for candidate in variants:
            with self.subTest(candidate=candidate):
                self.manifest().write_text(json.dumps(candidate))
                self.assertEqual(self.cache.restore("pt_BR"), 0)
                self.assertFalse(any((self.installation / name).exists() for name in self.assets))

    def test_windows_aliases_and_noncanonical_paths_are_rejected(self):
        for relative in ("Game/./pt_BR.wad", "Game//pt_BR.wad", "Game/../pt_BR.wad",
                         "Game/.. /pt_BR.wad", "Game/pt_BR./UI.wad", "Game/pt_BR /UI.wad",
                         "Game/pt_BR/NUL.wad", "Game/pt_BR/COM1.wad", "Game/pt_BR/UI:stream.wad",
                         "Game/pt_BR/UI?.wad", "Game/pt_BR/\x00.wad", "Game/pt_BR/UI.wad/"):
            with self.subTest(relative=relative):
                self.assertFalse(LanguageCache._asset(relative, "pt_BR"))

    def test_oversized_and_deeply_nested_manifests_are_misses(self):
        self.cache.save("pt_BR")
        with patch.object(language_cache, "_MAX_MANIFEST_BYTES", 4):
            self.assertEqual(self.cache.restore("pt_BR"), 0)
        self.manifest().write_text("[" * 2000 + "]" * 2000)
        self.assertEqual(self.cache.restore("pt_BR"), 0)

    def test_reparse_points_in_cache_and_installation_are_rejected(self):
        self.cache.save("pt_BR")
        original_is_link = language_cache._is_link
        for linked in (self.cache.directory, self.cache.directory / "blobs",
                       self.installation / "Plugins", self.manifest()):
            with self.subTest(linked=linked):
                with patch.object(language_cache, "_is_link", side_effect=lambda path: (
                    path == linked or original_is_link(path)
                )):
                    self.assertEqual(self.cache.restore("pt_BR"), 0)
        with patch.object(language_cache, "_is_link", side_effect=lambda path: (
            path == self.cache.directory or original_is_link(path)
        )):
            with self.assertRaises(ValueError):
                self.cache.save("pt_BR")

    def test_symlink_asset_is_not_followed(self):
        target = self.installation / next(iter(self.assets))
        outside = self.root / "outside.pt_BR.wad"
        outside.write_bytes(b"outside")
        target.unlink()
        try:
            target.symlink_to(outside)
        except OSError as exc:
            self.skipTest(f"Creating symbolic links is unavailable: {exc}")
        with self.assertRaises(ValueError):
            self.cache.save("pt_BR")
        self.assertFalse(self.manifest().exists())
        self.assertEqual(outside.read_bytes(), b"outside")

    def test_blob_changed_during_copy_does_not_replace_installed_file(self):
        self.cache.save("pt_BR")
        target = self.installation / next(iter(self.assets))
        target.write_bytes(b"installed file")
        original_copy = shutil.copy2

        def changed_blob(source, destination):
            source.write_bytes(b"changed after preflight")
            return original_copy(source, destination)

        with patch.object(language_cache.shutil, "copy2", side_effect=changed_blob):
            with self.assertRaises(OSError):
                self.cache.restore("pt_BR")
        self.assertEqual(target.read_bytes(), b"installed file")
        self.assertFalse(list(self.root.rglob(".rose-language-*")))

    def test_build_changed_during_validation_prevents_any_restore(self):
        self.cache.save("pt_BR")
        for name in self.assets:
            (self.installation / name).unlink()
        original_digest = language_cache._digest

        def updating_build(path):
            if path.parent.name == "blobs":
                self.write("LeagueClient.exe", b"patched during validation")
            return original_digest(path)

        with patch.object(language_cache, "_digest", side_effect=updating_build):
            self.assertEqual(self.cache.restore("pt_BR"), 0)
        self.assertFalse(any((self.installation / name).exists() for name in self.assets))

    def test_manifest_publication_failure_keeps_previous_entry(self):
        self.cache.save("pt_BR")
        previous = self.manifest().read_bytes()
        original_replace = language_cache.os.replace

        def disk_full(source, destination):
            if destination == self.manifest():
                raise OSError("disk full")
            return original_replace(source, destination)

        with patch.object(language_cache.os, "replace", side_effect=disk_full):
            with self.assertRaises(OSError):
                self.cache.save("pt_BR")
        self.assertEqual(self.manifest().read_bytes(), previous)
        self.assertFalse(list(self.root.rglob(".manifest-*")))

    def test_invalid_locale_cannot_create_cache_paths(self):
        for locale in ("../bad", "pt-BR", None):
            with self.assertRaises(ValueError):
                self.cache.save(locale)
            with self.assertRaises(ValueError):
                self.cache.restore(locale)


if __name__ == "__main__":
    unittest.main()
