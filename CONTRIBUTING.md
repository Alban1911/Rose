# Contributing to Rose

Thanks for helping out. Bug reports, translations and pull requests are all welcome, and [Discord](https://discord.com/invite/roseskins) is the place for questions. Read [ARCHITECTURE.md](ARCHITECTURE.md) first for how the pieces fit together.

## Reporting bugs

Use the [**Bug report**](https://github.com/Alban1911/Rose/issues/new/choose) form. It asks for your Rose version, League patch, region and game mode, the message in Rose's **Troubleshooting** panel, and the latest log from **Open Logs Folder**. Remove party tokens, account names and personal paths before posting. Ideas go in the **Feature request** form.

## Development setup

You need Windows 10 or 11, Python 3.11 or newer (CI uses 3.12), and [LTK Manager](https://github.com/LeagueToolkit/ltk-manager/releases) installed.

```powershell
git clone https://github.com/Alban1911/Rose.git
cd Rose
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Rose needs two native pieces before it can run from source. Building them needs [Visual Studio Build Tools](#build-tools).

```powershell
python scripts/build_pengu_loader.py   # Pengu Loader.exe, from vendor/PenguLoader-1.1.6/
python scripts/build_ltf.py            # ltk_launcher.exe + LeagueToolFlop.dll, into injection/tools/
```

Then run Rose from an **elevated** terminal:

```powershell
python main.py --dev --verbose
```

`--dev` skips the launcher (update check, skin sync, mod migration) and writes no log files unless you add `--logs`. `--debug` logs even more.

**Party Mode** needs a relay URL. Either set `ROSE_RELAY_URL`, or create the gitignored `party/network/relay_config.py`:

```python
RELAY_URL = "wss://<relay-host>"
```

To work on the relay itself, run it locally and point Rose at it with `ROSE_RELAY_URL=ws://127.0.0.1:8787` (see [Party relay](#party-relay)).

## Building

`scripts/build_pyinstaller.py` is the build entry point: it builds Pengu Loader and the LTF bridge, then packages Rose with PyInstaller. Don't run `pyinstaller Rose.spec` directly. The build refuses to start without `party/network/relay_config.py`, so Party Mode never ships without a relay.

| Command | Output |
| --- | --- |
| `python scripts/build_pyinstaller.py` | `dist/Rose/` (add `--skip-pengu-loader` to reuse the current loader build) |
| `python scripts/build_all.py` | The above, plus `installer/Rose_Setup_<version>.exe` |
| `python scripts/create_update_package.py` | `installer/update_package_<version>.zip`, the package the auto-updater downloads |

### Build tools

- **Visual Studio Build Tools** with:
  - .NET desktop build tools, WPF, and the .NET Framework 4.7.2 targeting pack (Pengu Loader)
  - MSVC C++ build tools with C++20 (the LTF bridge, from `native/ltf/`)
- **Inno Setup 6**, only for the installer

## Tests and checks

CI runs all of these on every pull request and every push to `main`. Run the ones for what you touched before opening a pull request.

```powershell
# Python unit tests: test/ and every package's tests/ folder (Windows only)
$suites = @('test') + (Get-ChildItem -Directory | ForEach-Object { Join-Path $_.Name 'tests' } | Where-Object { Test-Path $_ })
foreach ($suite in $suites) { python -m unittest discover -s $suite -t . }

# Python lint: syntax errors and undefined names only
python -m pip install ruff
python -m ruff check . --select E9,F63,F7,F82

# Plugins: syntax check, then the JS regression tests (Node.js 22+)
git ls-files 'Pengu Loader/plugins/*.js' | ForEach-Object { node --check $_ }
node --test "test/*.test.cjs"

# Party relay
cd relay-worker; npm ci; npm run typecheck; npm test; cd ..
```

- Python tests need Windows: several modules call `ctypes.windll` when imported.
- A plugin with a syntax error doesn't fail loudly; it just never loads in the client. Always run `node --check`.
- Put Python tests in the `tests/` folder (with an `__init__.py`) of the package they cover. CI picks up a new package's `tests/` folder by itself.
- `scripts/test_startup_diagnostics.ps1` and `scripts/test_update_prompt.ps1` are manual checks for the diagnostics collector and the update prompt.

CI also lints the workflows in `.github/` (actionlint, zizmor) and reviews dependency changes.

## Pull requests

- Branch off `main`: `fix/chroma-crash`, `feat/skin-preview`, `docs/readme`.
- Write commits as `type(scope): summary`, like the history: `fix(party): ...`, `feat(mods): ...`.
- Keep one change per pull request, and make sure CI passes.
- Skin package bugs (a broken model, missing sounds) belong in [LeagueSkins](https://github.com/Alban1911/LeagueSkins), not here.

## Writing plugins

Plugins live in `Pengu Loader/plugins/ROSE-<Name>/index.js`. `ROSE-SkinMonitor` hosts the WebSocket connection to Rose and exposes it as `window.__roseBridge` once it knows the port. Wait for that object to appear, then use:

| Method | Use |
| --- | --- |
| `send(payload)` | Send a message to Rose |
| `subscribe(type, cb)` / `unsubscribe(type, cb)` | Receive Rose's messages of a type |
| `onReady(cb)` | Run once the bridge is connected |
| `onDisconnect(cb)` | Run when an open connection to Rose closes (not on each failed reconnect), so a plugin waiting for an answer can give up |

Messages from the plugins are routed in `pengu/communication/message_handler.py`.

## Translations

Rose's menus are translated in `Pengu Loader/plugins/ROSE-I18n/locales/`, one `<language>.json` per language, keyed by the English text. A missing text falls back to English. Both the plugins and the Python side (`utils/core/i18n.py`) read these files. To add a language, copy an existing file and translate the values.

## Party relay

The relay is a Cloudflare Worker in `relay-worker/` (TypeScript). The tests build the Worker and exercise WebSocket upgrades against a local Durable Object with SQLite storage.

```powershell
cd relay-worker
npm ci
npm run dev    # local relay on ws://127.0.0.1:8787
```

Relay deployments outside loopback use WSS. Protocol changes must ship together with a matching Rose release: the relay answers HTTP 426 to clients it no longer supports, and clients wait for the relay's protocol acknowledgement before exchanging party state. Existing invite tokens keep their room keys.
