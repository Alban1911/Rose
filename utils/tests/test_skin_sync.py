import hashlib
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.download import github_rate_limit, skin_sync
from utils.download.repo_downloader import RepoDownloader
from utils.download.skin_sync import MANIFEST_URL, RAW_BASE, TREE_API_URL, SkinSync, blob_sha

COMMIT = "c0ffee" * 6 + "abcd"


def git_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


class FakeResponse:
    def __init__(self, status=200, body=b"", headers=None):
        self.status_code = status
        self.content = body
        self.headers = headers or {}

    @property
    def text(self):
        return self.content.decode("utf-8")

    def json(self):
        return json.loads(self.content)

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i:i + chunk_size]

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeGitHub:
    """raw.githubusercontent.com for LeagueSkins: the manifest branch and the files by commit or main"""

    def __init__(self, files):
        self.files = dict(files)  # repo path -> content
        self.etag = '"manifest-1"'
        self.calls = []
        self.manifest_status = 200
        self.throttle_after = None  # answer 429 after this many file downloads
        self.served = 0
        self.wrong_content = set()
        self.commit_gone = False
        self.lock = threading.Lock()

    def manifest(self):
        files = [[path, git_sha(data), len(data)] for path, data in sorted(self.files.items())]
        return json.dumps({"version": 1, "commit": COMMIT, "files": files}).encode()

    def get(self, url, headers=None, stream=False, timeout=None):
        self.calls.append(url)
        headers = headers or {}
        if url == MANIFEST_URL:
            if self.manifest_status != 200:
                return FakeResponse(self.manifest_status)
            if headers.get("If-None-Match") == self.etag:
                return FakeResponse(304)
            return FakeResponse(200, self.manifest(), {"ETag": self.etag})
        prefix_commit, prefix_main = f"{RAW_BASE}/{COMMIT}/", f"{RAW_BASE}/main/"
        if url.startswith(prefix_commit) and self.commit_gone:
            return FakeResponse(404)
        for prefix in (prefix_commit, prefix_main):
            if url.startswith(prefix):
                from urllib.parse import unquote
                path = unquote(url[len(prefix):])
                with self.lock:  # the sync downloads from several threads
                    if self.throttle_after is not None and self.served >= self.throttle_after:
                        return FakeResponse(429)
                    if path not in self.files:
                        return FakeResponse(404)
                    self.served += 1
                data = self.files[path]
                if path in self.wrong_content:
                    data = b"tampered " + data
                return FakeResponse(200, data)
        return FakeResponse(404)

    def downloads(self):
        return [url for url in self.calls if url != MANIFEST_URL]


class SkinSyncTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        self.skins = self.root / "skins"
        self.skins.mkdir()
        self.github = FakeGitHub({
            "skins/1/1001/1001.fantome": b"skin 1001",
            "skins/1/1001/1001.png": b"preview",
            "skins/1/1001/1002/1002.fantome": b"chroma 1002",
            "classic/1/1001/1001.fantome": b"classic 1001",
            "resources/en/skin_ids.json": b"{}",
        })
        self.downloader = RepoDownloader(target_dir=self.skins)
        patcher = patch.object(SkinSync, "_session", lambda sync: self.github)
        patcher.start()
        self.addCleanup(patcher.stop)
        no_wait = patch.object(skin_sync.time, "sleep")
        no_wait.start()
        self.addCleanup(no_wait.stop)

    def synchronizer(self):
        return SkinSync(
            self.downloader._resolve_local_path,
            [self.skins, self.downloader.classic_dir, self.downloader.resources_dir],
            self.skins,
            workers=2,
        )

    def sync(self):
        return self.synchronizer().run()

    def local(self, path):
        return self.downloader._resolve_local_path(path)

    def test_a_missing_library_is_downloaded_and_checked(self):
        result = self.sync()

        self.assertTrue(result.complete)
        self.assertEqual(result.downloaded, 5)
        for path, data in self.github.files.items():
            self.assertEqual(self.local(path).read_bytes(), data, path)
        self.assertTrue(all(f"/{COMMIT}/" in url for url in self.github.downloads()))  # pinned to the commit
        self.assertEqual(self.local("classic/1/1001/1001.fantome").parent.parent.parent, self.root / "classic")

    def test_an_unchanged_library_downloads_nothing(self):
        self.sync()
        self.github.calls.clear()

        result = self.sync()

        self.assertTrue(result.complete)
        self.assertEqual(self.github.downloads(), [])
        self.assertEqual(self.github.calls, [MANIFEST_URL])  # one request, answered 304

    def test_only_the_files_that_changed_are_downloaded(self):
        self.sync()
        self.github.files["skins/1/1001/1001.fantome"] = b"skin 1001, 16.22"
        self.github.files["skins/2/2001/2001.fantome"] = b"new skin"
        self.github.etag = '"manifest-2"'
        self.github.calls.clear()

        result = self.sync()

        self.assertEqual(result.downloaded, 2)
        self.assertEqual(len(self.github.downloads()), 2)
        self.assertEqual(self.local("skins/1/1001/1001.fantome").read_bytes(), b"skin 1001, 16.22")

    def test_a_library_from_an_older_rose_is_checked_once_not_downloaded(self):
        for path, data in self.github.files.items():
            self.local(path).parent.mkdir(parents=True, exist_ok=True)
            self.local(path).write_bytes(data)

        result = self.sync()

        self.assertTrue(result.complete)
        self.assertEqual(self.github.downloads(), [])

    def test_a_file_whose_content_does_not_match_is_not_kept(self):
        self.github.wrong_content.add("skins/1/1001/1001.fantome")
        target = self.local("skins/1/1001/1001.fantome")
        target.parent.mkdir(parents=True)
        target.write_bytes(b"what was there")

        result = self.sync()

        self.assertFalse(result.complete)
        self.assertEqual(result.failed, 1)
        self.assertEqual(target.read_bytes(), b"what was there")

    def test_a_throttled_sync_keeps_what_landed_and_resumes(self):
        self.github.throttle_after = 2
        first = self.sync()
        self.assertFalse(first.complete)
        self.assertTrue(first.throttled)
        self.assertEqual(first.downloaded, 2)

        self.github.throttle_after = None
        self.github.calls.clear()
        second = self.sync()

        self.assertTrue(second.complete)
        self.assertEqual(second.downloaded, 3)  # the two that landed are not fetched again
        self.assertEqual(len(self.github.downloads()), 3)

    def test_only_unmodified_files_owned_by_the_library_are_removed(self):
        self.sync()
        untracked = self.local("skins/9/9001/9001.fantome")
        untracked.parent.mkdir(parents=True)
        untracked.write_bytes(b"local only")
        modified = "skins/1/1001/1001.png"
        self.local(modified).write_bytes(b"local preview")
        retired = "skins/1/1001/1002/1002.fantome"
        del self.github.files[modified]
        del self.github.files[retired]
        self.github.etag = '"manifest-2"'

        result = self.sync()

        self.assertTrue(result.complete)
        self.assertEqual(result.removed, 1)
        self.assertEqual(untracked.read_bytes(), b"local only")
        self.assertEqual(self.local(modified).read_bytes(), b"local preview")
        self.assertFalse(self.local(retired).exists())
        self.assertFalse(self.local(retired).parent.exists())
        self.assertTrue((self.skins / skin_sync.STATE_FILE).exists())  # Rose's own files stay

    def test_an_incomplete_sync_preserves_files_until_a_complete_retry(self):
        self.sync()
        retired = "skins/1/1001/1002/1002.fantome"
        new = "skins/2/2001/2001.fantome"
        del self.github.files[retired]
        self.github.files[new] = b"new skin"
        self.github.wrong_content.add(new)
        self.github.etag = '"manifest-2"'

        failed = self.sync()

        self.assertFalse(failed.complete)
        self.assertEqual(failed.removed, 0)
        self.assertEqual(self.local(retired).read_bytes(), b"chroma 1002")
        self.github.wrong_content.clear()

        retried = self.sync()

        self.assertTrue(retried.complete)
        self.assertEqual(retried.removed, 1)
        self.assertFalse(self.local(retired).exists())
        self.assertEqual(self.local(new).read_bytes(), b"new skin")

    def test_an_interrupted_manifest_fetch_cannot_reuse_the_wrong_listing(self):
        self.sync()
        synchronizer = self.synchronizer()
        original = self.github.files.copy()
        retired = "skins/1/1001/1002/1002.fantome"
        del self.github.files[retired]
        self.github.etag = '"manifest-2"'
        # The process can exit after writing the manifest but before saving state.
        synchronizer.fetch_manifest(synchronizer._load_state())
        self.github.files = original
        self.github.etag = '"manifest-1"'
        self.github.calls.clear()

        result = self.sync()

        self.assertTrue(result.complete)
        self.assertEqual(result.removed, 0)
        self.assertTrue(self.local(retired).exists())
        self.assertEqual(self.github.calls, [MANIFEST_URL, MANIFEST_URL])

    def test_an_unresolvable_destination_prevents_cleanup(self):
        self.sync()
        retired = "skins/1/1001/1002/1002.fantome"
        new = "skins/2/2001/2001.fantome"
        del self.github.files[retired]
        self.github.files[new] = b"new skin"
        self.github.etag = '"manifest-2"'
        synchronizer = self.synchronizer()
        synchronizer.resolve = lambda path: None if path == new else self.local(path)

        result = synchronizer.run()

        self.assertFalse(result.complete)
        self.assertEqual(result.pending, [new])
        self.assertTrue(self.local(retired).is_file())

    def test_temp_files_left_by_a_killed_sync_are_swept(self):
        self.sync()
        partial = self.local("skins/1/1001/.1001.fantome.abc123.tmp")
        state_temp = self.skins / ".skin_sync_state.json.x1y2z3.tmp"
        partial.write_bytes(b"half a skin")
        state_temp.write_bytes(b"{")
        self.github.etag = '"manifest-2"'

        self.sync()

        self.assertFalse(partial.exists())
        self.assertFalse(state_temp.exists())
        self.assertTrue((self.skins / skin_sync.STATE_FILE).exists())
        self.assertTrue((self.skins / skin_sync.MANIFEST_COPY).exists())
        self.assertEqual(self.local("skins/1/1001/1001.fantome").read_bytes(), b"skin 1001")

    def test_a_rewritten_commit_falls_back_to_main(self):
        self.github.commit_gone = True

        result = self.sync()

        self.assertTrue(result.complete)
        self.assertTrue(any(f"{RAW_BASE}/main/" in url for url in self.github.downloads()))

    def test_without_a_manifest_the_tree_api_lists_the_library(self):
        self.github.manifest_status = 404
        tree = {"truncated": False, "tree": [
            {"type": "blob", "path": path, "sha": git_sha(data), "size": len(data)}
            for path, data in self.github.files.items()
        ] + [{"type": "blob", "path": "README.md", "sha": "x", "size": 1}]}
        with patch.object(skin_sync.github_rate_limit, "api_get", return_value=FakeResponse(200, json.dumps(tree).encode())) as api:
            result = self.sync()

        api.assert_called_once()
        self.assertEqual(api.call_args.args[0], TREE_API_URL)
        self.assertTrue(result.complete)
        self.assertTrue(all(f"{RAW_BASE}/main/" in url for url in self.github.downloads()))

    def test_no_listing_leaves_the_library_as_it_is(self):
        self.github.manifest_status = 503
        kept = self.local("skins/1/1001/1001.fantome")
        kept.parent.mkdir(parents=True)
        kept.write_bytes(b"skin")
        with patch.object(skin_sync.github_rate_limit, "api_get", return_value=None):
            self.assertIsNone(self.sync())
            self.assertFalse(self.downloader.download_incremental_updates())

        self.assertTrue(kept.exists())

    def test_a_listing_without_skins_never_empties_the_library(self):
        self.github.files = {"resources/en/skin_ids.json": b"{}"}
        kept = self.local("skins/1/1001/1001.fantome")
        kept.parent.mkdir(parents=True)
        kept.write_bytes(b"skin")
        with patch.object(skin_sync.github_rate_limit, "api_get", return_value=None):
            self.assertIsNone(self.sync())

        self.assertTrue(kept.exists())

    def test_blob_sha_is_gits(self):
        path = self.root / "file"
        path.write_bytes(b"hello\n")
        self.assertEqual(blob_sha(path), "ce013625030ba8dba906f756967f9e9ca394464a")  # git hash-object


class RateLimitTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        state = Path(temp_dir.name) / "github_api_limit.json"
        patcher = patch.object(github_rate_limit, "_state_file", return_value=state)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_rate_limit_refusal_blocks_calls_until_its_reset(self):
        reset = int(time.time()) + 600
        github_rate_limit.note_response(FakeResponse(403, headers={
            "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset),
        }))

        self.assertFalse(github_rate_limit.api_allowed())
        self.assertAlmostEqual(github_rate_limit.blocked_until(), reset, delta=1)
        with patch("requests.get") as get:
            self.assertIsNone(github_rate_limit.api_get("https://api.github.com/x"))
        get.assert_not_called()

    def test_other_refusals_block_nothing(self):
        github_rate_limit.note_response(FakeResponse(403, headers={"X-RateLimit-Remaining": "42"}))
        github_rate_limit.note_response(FakeResponse(404))

        self.assertTrue(github_rate_limit.api_allowed())

    def test_a_429_without_a_time_waits_the_default(self):
        github_rate_limit.note_response(FakeResponse(429))

        self.assertAlmostEqual(
            github_rate_limit.blocked_until() - time.time(), github_rate_limit.DEFAULT_BACKOFF_S, delta=5,
        )


class HashUpdaterTests(unittest.TestCase):
    def setUp(self):
        from utils.download import hash_updater
        self.hash_updater = hash_updater
        self.state = {}
        for target, kwargs in (
            ("load_state", {"side_effect": lambda: dict(self.state)}),
            ("save_state", {"side_effect": lambda state: self.state.update(state)}),
        ):
            patcher = patch.object(hash_updater, target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.remote = {name: f'"{name}-1"' for name in hash_updater.HASH_FILES}
        patcher = patch.object(hash_updater, "remote_etags", side_effect=lambda session: self.remote)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_unchanged_files_need_no_download(self):
        self.state = {"etags": dict(self.remote)}
        self.assertFalse(self.hash_updater.check_for_updates())

    def test_a_changed_file_is_an_update(self):
        self.state = {"etags": dict(self.remote)}
        self.remote["hashes.game.txt.3"] = '"changed"'
        self.assertTrue(self.hash_updater.check_for_updates())

    def test_a_state_from_an_older_rose_is_taken_as_current(self):
        self.state = {"files": {"hashes.game.txt.0": {"sha": "abc"}}}

        self.assertFalse(self.hash_updater.check_for_updates(target_exists=True))
        self.assertEqual(self.state["etags"], self.remote)

    def test_no_state_downloads_them(self):
        self.assertTrue(self.hash_updater.check_for_updates(target_exists=True))

    def test_an_unreadable_check_changes_nothing(self):
        self.remote = None
        self.assertFalse(self.hash_updater.check_for_updates())


class ReleaseCheckTests(unittest.TestCase):
    def setUp(self):
        from launcher.update import github_client
        self.github_client = github_client

    def test_the_latest_release_comes_from_the_redirect(self):
        def head(url, **kwargs):
            self.assertEqual(url, "https://github.com/Alban1911/Rose/releases/download/1.5.2/update_package_1.5.2.zip")
            return FakeResponse(200, headers={"Content-Length": "35066861"})

        redirect = FakeResponse(302, headers={"Location": "https://github.com/Alban1911/Rose/releases/tag/1.5.2"})
        with patch("requests.get", return_value=redirect), patch("requests.head", side_effect=head), \
                patch.object(self.github_client.github_rate_limit, "api_get") as api:
            release = self.github_client.GitHubClient().get_latest_release()

        api.assert_not_called()
        client = self.github_client.GitHubClient()
        self.assertEqual(client.get_release_version(release), "1.5.2")
        self.assertEqual(client.get_zip_asset(release)["size"], 35066861)

    def test_the_api_is_the_fallback(self):
        api_release = {"tag_name": "1.5.2", "assets": []}
        with patch("requests.get", return_value=FakeResponse(200)), \
                patch.object(self.github_client.github_rate_limit, "api_get",
                             return_value=FakeResponse(200, json.dumps(api_release).encode())):
            self.assertEqual(self.github_client.GitHubClient().get_latest_release(), api_release)


if __name__ == "__main__":
    unittest.main()
