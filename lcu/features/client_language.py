"""Change the League product locale through Riot Client, then relaunch League.

API reference: https://github.com/KebsCS/lcu-and-riotclient-api/tree/main/riotclient
The UX-only restart does not reload the League backend's locale.
"""

import re
import threading
import time
from pathlib import Path

import requests

from .language_cache import LanguageCache


class LanguageChangeError(Exception):
    """A user-facing failure that never includes local API credentials."""


LANGUAGE_NAMES = {
    "ar_AE": "العربية", "cs_CZ": "Čeština", "de_DE": "Deutsch",
    "el_GR": "Ελληνικά", "en_AU": "English (Australia)",
    "en_GB": "English (UK)", "en_PH": "English (Philippines)",
    "en_SG": "English (Singapore)", "en_US": "English (US)",
    "es_AR": "Español (Argentina)", "es_ES": "Español (España)",
    "es_MX": "Español (México)", "fr_FR": "Français", "hu_HU": "Magyar",
    "id_ID": "Bahasa Indonesia", "it_IT": "Italiano", "ja_JP": "日本語",
    "ko_KR": "한국어", "pl_PL": "Polski", "pt_BR": "Português (Brasil)",
    "ro_RO": "Română", "ru_RU": "Русский", "th_TH": "ไทย", "tr_TR": "Türkçe",
    "vi_VN": "Tiếng Việt", "zh_MY": "中文 (马来西亚)", "zh_TW": "繁體中文",
}


class ClientLanguageService:
    """One serialized operation per backend, with status retained across UX reloads."""

    def __init__(self, lcu, stopped=lambda: False):
        self.lcu = lcu
        self.stopped = stopped
        self._operation = threading.Lock()
        self._status_lock = threading.Lock()
        self._status = {"busy": False, "stage": "idle", "message": ""}

    @property
    def status(self):
        with self._status_lock:
            return dict(self._status)

    @staticmethod
    def _report(report, status):
        try:
            report(dict(status))
        except Exception:
            # A UX restart disconnects the status consumer. Keep the operation
            # and retained status alive without logging authenticated details.
            pass

    def _update(self, report, **status):
        with self._status_lock:
            self._status = status
        self._report(report, status)

    @staticmethod
    def _request(session, base, method, path, **kwargs):
        try:
            response = session.request(method, base + path, timeout=5, allow_redirects=False, **kwargs)
        except requests.RequestException:
            raise LanguageChangeError("Could not contact the client. Please try again.") from None
        if not 200 <= response.status_code < 300:
            raise LanguageChangeError(f"The client rejected the operation (HTTP {response.status_code}).")
        return response

    def _league(self, path):
        self.lcu.refresh_if_needed()
        if not self.lcu.ok or not self.lcu.base:
            raise LanguageChangeError("Open League of Legends and sign in first.")
        response = self._request(self.lcu.s, self.lcu.base, "GET", path)
        try:
            return response.json()
        except ValueError:
            raise LanguageChangeError("The client returned an unexpected response.") from None

    def _connect_riot(self):
        args = self._league("/riotclient/command-line-args")
        if not isinstance(args, list):
            raise LanguageChangeError("Riot Client connection details are unavailable.")
        flags = {}
        for arg in args:
            if isinstance(arg, str) and arg.startswith("--") and "=" in arg:
                key, value = arg.split("=", 1)
                flags[key] = value.strip('"')
        port = flags.get("--riotclient-app-port", "")
        token = flags.get("--riotclient-auth-token", "")
        if not re.fullmatch(r"[0-9]{1,5}", port) or not 0 < int(port) < 65536 or not token:
            raise LanguageChangeError("Riot Client is unavailable. Open League through Riot Client.")
        region = self._league("/riotclient/region-locale")
        if not isinstance(region, dict) or not isinstance(region.get("region"), str) or not region["region"]:
            raise LanguageChangeError("Could not identify the running League installation.")
        patchline = "pbe" if region["region"].upper() == "PBE" else "live"
        session = requests.Session()
        session.trust_env = False
        session.verify = False  # Riot's self-signed certificate; loopback only.
        session.auth = ("riot", token)
        return session, f"https://127.0.0.1:{port}", patchline

    def _options(self, session, base, patchline):
        suffix = f"/products/league_of_legends/patchlines/{patchline}"
        try:
            current = self._request(session, base, "GET", "/riotclient/product-locales" + suffix).json()
            available = self._request(
                session, base, "GET", "/rnet-product-registry/v4/available-product-locales" + suffix
            ).json()
        except ValueError:
            raise LanguageChangeError("The client returned an unexpected language list.") from None
        if (not isinstance(current, str) or not re.fullmatch(r"[a-z]{2}_[A-Z]{2}", current)
                or not isinstance(available, list)):
            raise LanguageChangeError("This client version does not expose a supported language list.")
        locales = sorted({x for x in available if isinstance(x, str) and re.fullmatch(r"[a-z]{2}_[A-Z]{2}", x)})
        if not locales:
            raise LanguageChangeError("No languages are available for this installation.")
        return {"currentLocale": current, "languages": [
            {"locale": x, "name": LANGUAGE_NAMES.get(x, x)} for x in locales
        ]}

    def options(self):
        session, base, patchline = self._connect_riot()
        with session:
            return self._options(session, base, patchline)

    def _require_idle(self):
        if self.stopped():
            raise LanguageChangeError("Rose is shutting down. No restart will be requested.")
        # Read directly; never rely on a stale shared-state/cached phase for a restart.
        if self._league("/lol-gameflow/v1/gameflow-phase") not in ("None", "Lobby"):
            raise LanguageChangeError("Leave the queue, champion select or game before changing language.")

    def _wait(self, predicate, timeout):
        deadline = time.monotonic() + timeout
        while not self.stopped() and time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.5)
        return False

    def _language_cache(self, patchline):
        # Use the connected client's lockfile, not a guessed live/PBE path.
        connection = getattr(self.lcu, "_connection", None)
        lockfile = getattr(connection, "lf_path", None)
        if not isinstance(lockfile, (str, Path)):
            return None
        return LanguageCache(Path(lockfile).parent, patchline)

    def change(self, locale, report=lambda status: None):
        if not self._operation.acquire(blocking=False):
            self._report(report, self.status)
            return
        saved = False
        cache_note = ""
        try:
            self._update(report, busy=True, stage="checking", message="Checking language…")
            if not isinstance(locale, str) or not re.fullmatch(r"[a-z]{2}_[A-Z]{2}", locale):
                raise LanguageChangeError("Select a valid language.")
            self._require_idle()
            session, base, patchline = self._connect_riot()
            with session:
                options = self._options(session, base, patchline)
                if locale not in {item["locale"] for item in options["languages"]}:
                    raise LanguageChangeError("This language is not available for your installation.")
                actual = self._league("/riotclient/region-locale")
                try:
                    cache = self._language_cache(patchline)
                except (OSError, ValueError):
                    cache = None
                if cache is None:
                    cache_note = " Local language cache is unavailable; Riot may download files."
                elif isinstance(actual, dict) and actual.get("locale"):
                    self._update(report, busy=True, stage="caching", message="Saving current language files locally…")
                    try:
                        if not cache.save(actual["locale"]):
                            cache_note = " No language files could be cached for this build."
                    except (OSError, ValueError):
                        cache_note = " Could not save the local language cache; check disk space and permissions."
                if options["currentLocale"] == locale and isinstance(actual, dict) and actual.get("locale") == locale:
                    self._update(report, busy=False, stage="complete", message="This language is already active." + cache_note)
                    return
                suffix = f"/products/league_of_legends/patchlines/{patchline}"
                locale_path = "/riotclient/product-locales" + suffix
                reused = 0
                if cache is not None:
                    self._require_idle()
                    self._update(report, busy=True, stage="restoring", message="Checking local language cache…")
                    try:
                        # Locale-specific filenames do not replace the active
                        # language. Seed them BEFORE PUT, which can start patching.
                        reused = cache.restore(locale)
                    except (OSError, ValueError):
                        cache_note = " Could not restore all cached files; Riot may download missing files."
                self._require_idle()
                self._request(session, base, "PUT", locale_path, json=locale)
                saved = True
                if self._request(session, base, "GET", locale_path).json() != locale:
                    raise LanguageChangeError("The client did not confirm the requested language.")
                # Recheck immediately before closing: the player may have joined a queue.
                self._require_idle()
                old_base, old_session = self.lcu.base, self.lcu.s
                self._update(report, busy=True, stage="restarting", message=(
                    "Restarting League with cached language files. Riot will verify them…" if reused else
                    "Restarting League. Language files may need to download…"
                ))
                launcher = "/product-launcher/v1" + suffix
                self._request(session, base, "DELETE", launcher)

                def closed():
                    try:
                        old_session.get(old_base + "/riotclient/region-locale", timeout=1, allow_redirects=False)
                        return False
                    except (requests.Timeout, requests.exceptions.SSLError):
                        # A slow or TLS-rejecting process may still be running.
                        return False
                    except requests.ConnectionError:
                        return True
                    except requests.RequestException:
                        return False

                if not self._wait(closed, 30):
                    raise LanguageChangeError("League did not close in time. Restart it through Riot Client.")
                if self.stopped():
                    raise LanguageChangeError("Rose is shutting down. Reopen League through Riot Client.")
                self._request(session, base, "POST", launcher)

                def applied():
                    try:
                        data = self._league("/riotclient/region-locale")
                        return isinstance(data, dict) and data.get("locale") == locale
                    except LanguageChangeError:
                        return False

                if not self._wait(applied, 120):
                    raise LanguageChangeError("The new language is not confirmed yet. Check downloads in Riot Client and reopen League if needed.")
                if cache is not None:
                    self._update(report, busy=True, stage="caching", message="Caching language files for the next switch…")
                    try:
                        # Re-resolve build identity in case Riot updated during restart.
                        current_cache = self._language_cache(patchline)
                        if current_cache is None or not current_cache.save(locale):
                            cache_note = " No language files could be cached for this build."
                    except (OSError, ValueError):
                        cache_note = " Could not save the local language cache; check disk space and permissions."
                self._update(report, busy=False, stage="complete", message=(
                    "Language changed successfully." + (" Local cache reused." if reused else "") + cache_note
                ), locale=locale)
        except (LanguageChangeError, ValueError) as exc:
            message = str(exc) if isinstance(exc, LanguageChangeError) else "The client returned an unexpected response."
            if saved:
                message = "The language preference was saved. " + message
            self._update(report, busy=False, stage="error", message=message)
        except Exception:
            # Do not expose exceptions containing authenticated request details.
            self._update(report, busy=False, stage="error", message=(
                "The language preference was saved. Reopen League through Riot Client." if saved
                else "Could not change the language. Please try again."
            ))
        finally:
            self._operation.release()
