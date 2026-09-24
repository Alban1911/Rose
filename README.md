# 🌹 Rose - Effortless Skin Changer for LoL

<div align="center">

  <img src="./assets/icon.png" alt="Rose Icon" width="128" height="128">

[![Installer](https://img.shields.io/badge/Installer-Windows-32A832)](https://github.com/Alban1911/Rose/releases/latest) [![Ko-Fi](https://img.shields.io/badge/KoFi-Donate-C03030?logo=ko-fi&logoColor=white)](https://ko-fi.com/roseapp) [![Discord](https://img.shields.io/discord/1490473857075642621?color=32A832&logo=discord&logoColor=white&label=Discord)](https://discord.com/invite/roseskins) [![License](https://img.shields.io/badge/License-MIT-C03030)](LICENSE) [![Downloads](https://img.shields.io/github/downloads/Alban1911/Rose/total?color=32A832&label=Downloads&cacheSeconds=86400)](https://github.com/Alban1911/Rose/releases/latest)


</div>

---

## Overview

Rose is an open-source automatic skin changer for League of Legends that enables seamless access to all skins in the game. The application runs silently in the system tray and automatically detects skin selections during champion select, injecting the chosen skin when the game loads.

Built on the [Pengu Loader](https://github.com/PenguLoader/PenguLoader) framework, Rose integrates JavaScript extensions into the League Client to enable modular UI interactions. It strictly modifies local rendering variables to display custom models and textures. It is designed purely as an exploration of client-side asset management, providing no manipulation of network data, memory states, or gameplay mechanics, thereby **offering zero competitive advantage**.

## Architecture

Rose consists of three main components:

### Python Backend

- **LCU API Integration**: Communicates with the League Client via the League Client Update (LCU) API
- **Skin Injection**: Handles skin injection compatible with Riot Vanguard
- **WebSocket Bridge**: Operates a WebSocket server for real-time communication with frontend plugins
- **Skin Management**: Downloads and manages skin files from the [LeagueSkins repository](https://github.com/Alban1911/LeagueSkins)
- **Party Mode**: Enables skin sharing between friends in the same lobby via a Cloudflare WebSocket relay
- **Game Monitoring**: Tracks game state, champion select phases, and loadout countdowns
- **Auto-Updater**: Checks GitHub for new releases and prompts users to install updates
- **Analytics**: Sends a startup ping, a 15-minute presence heartbeat, and a best-effort close ping (configurable, runs in a background thread)

### Analytics and privacy

Rose sends a pseudonymous, randomly generated installation ID and the app version
to `https://analytics.rosekeys.site/` when analytics are enabled. The ID is not derived
from the Windows Machine GUID. Analytics can be disabled with
`ANALYTICS_ENABLED = False` in `config.py`.

The analytics API and dashboard are maintained separately from this public
client repository. Only aggregate usage metrics are exposed through the
dashboard; raw activity and server credentials remain private.

### Cloudflare Workers

- **rose-party-relay**: Durable Object-backed WebSocket relay that manages party rooms (max 10 members per room) for real-time skin selection broadcasting between friends
### Pengu Loader Plugins

Rose includes a suite of JavaScript plugins that extend the League Client UI:

- **ROSE-UI**: Unlocks locked skin previews in champion select, enabling hover interactions on all skins
- **ROSE-SkinMonitor**: Monitors currently selected skin's name and sends it to the Python backend via WebSocket
- **ROSE-CustomWheel**: Displays custom mod metadata for hovered skins and exposes quick access to the mods folder
- **ROSE-ChromaWheel**: Enhanced chroma selection interface for choosing any chroma variant
- **ROSE-FormsWheel**: Custom form selection interface for skins with multiple forms (Elementalist Lux, Sahn Uzal Mordekaiser, Spirit Blossom Morgana, Radiant Sett)
- **ROSE-SettingsPanel**: Settings panel accessible from the League of Legends Client
- **ROSE-RandomSkin**: Random skin selection feature
- **ROSE-HistoricMode**: Access to the last used skin for every champion
- **ROSE-PartyMode**: Party mode UI — displays a panel in lobby and champion select to enable skin sharing, view connected peers, and see friends' skin selections in real time
- **ROSE-Jade**: Client customization — regalia borders, backgrounds, banners, icons, titles, and win/loss stats

## How It Works

1. **League Client Integration**: Rose activates **[Pengu Loader](https://github.com/PenguLoader/PenguLoader)** on startup, which injects the JavaScript plugins into the League Client
2. **Skin Detection**: When you hover over a skin in champion select, `ROSE-SkinMonitor` detects the selection and sends it to the Python backend
3. **Game Opening Delay**: To make sure the injection has time to occur we suspend League of Legend's game process as long as the overlay is not ran
4. **Game Injection**: Rose injects the selected skin when the game starts
5. **Seamless Experience**: The skin loads as if you owned it, with full chroma support and no gameplay impact (Rose will **never** provide any competitive advantage to its users)

## Features

- **Smart Injection**: Never injects skins you already own
- **Multi-Language Support**: Works with any client language
- **Open Source**: Fully open source and extensible
- **Free**: If you bought this software, you got scammed 💀

## Requirements

- **Windows 10/11**
- **League of Legends** installed
- **LTK patcher** - two files from [LTK Manager](https://github.com/LeagueToolkit/ltk-manager) that you add yourself (see below)

### LTK patcher

Rose injects skins with the patcher from LTK Manager: `ltk_patcher_host.exe` waits for the game to start and loads `ltk_patcher_dll.dll` into it, which makes the game read the skin files. League Toolkit updates both files when a League patch changes the game.

**Rose does not ship these files.** The LTK license does not allow redistributing them with League Toolkit's code signature, so every user gets their own copy from the official LTK Manager. Please do not ask for them or share them in the Discord.

**Setup (one time)**

1. Download the latest `LTK.Manager_x.y.z_x64-setup.exe` from **https://github.com/LeagueToolkit/ltk-manager/releases/latest** (under *Assets*) and install it. When the installer offers to run LTK Manager, let it: on first launch it looks for your League folder (pick it yourself if it can't find it). You don't need to use LTK Manager for anything else.
2. Open LTK Manager's install folder. By default it is `C:\Users\<your Windows user>\AppData\Local\LTK Manager` (if you picked another folder in the installer, use that one). `AppData` is hidden, so the easiest way is: press `Win` + `R`, paste `%LOCALAPPDATA%\LTK Manager` and press Enter; pasting it into File Explorer's address bar works too.
3. Copy `ltk_patcher_host.exe` and `ltk_patcher_dll.dll` from there.
4. Paste them into Rose's tools folder, `C:\Program Files\Rose\_internal\injection\tools` (Windows asks for administrator permission). The **Open tools folder** button in Rose's "Missing Patcher" window opens it for you.
5. Start Rose again.

**After a League patch**

The patcher DLL has an end-of-life date built in and stops injecting into game builds released after it. When that happens Rose shows **"Rose - Patcher Outdated"** before starting. Open LTK Manager and let it update (it only checks for updates while it is open, and installs them when you close it), then repeat steps 2–5 to replace both files.

| Rose window | Meaning | Fix |
|---|---|---|
| Rose - Missing Patcher | one or both files are not in the tools folder | steps 1–5 |
| Rose - Patcher Outdated | the DLL reached its end-of-life date | update LTK Manager, then steps 2–5 |
| Rose - Broken Patcher | `ltk_patcher_dll.dll` is not a valid LTK patcher DLL | copy both files again from LTK Manager |

## Installation

1. Download the latest installer from [Releases](https://github.com/Alban1911/Rose/releases/latest)
2. Run the installer as Administrator
3. Launch Rose from the Start Menu or desktop shortcut
4. On first launch Rose asks for the LTK patcher: follow [LTK patcher setup](#ltk-patcher)

## Building from source

Rose builds the Pengu Loader executable from the vendored source in
`vendor/PenguLoader-1.1.6/` as part of the normal Rose build. You do not need
to download or commit a prebuilt `Pengu Loader.exe`.

### Prerequisites

- Windows 10/11
- Python 3.11 or newer
- Visual Studio Build Tools with the .NET desktop build tools, WPF support,
  and the .NET Framework 4.7.2 targeting pack
- Inno Setup 6 if you also want to create the installer

Clone the repository and enter its directory:

```powershell
git clone https://github.com/Alban1911/Rose.git
cd Rose
```

Install the Python dependencies first:

```powershell
python -m pip install -r requirements.txt
```

Build the loader by itself, if needed:

```powershell
python scripts/build_pengu_loader.py
```

Build Rose and automatically rebuild the loader:

```powershell
python scripts/build_pyinstaller.py
```

The packaged application is written to `dist/Rose/`. To build both Rose and
the Windows installer in one step:

```powershell
python scripts/build_all.py
```

The installer is written to `installer/Rose_Setup.exe`. Use
`scripts/build_pyinstaller.py` or `scripts/build_all.py` instead of invoking
`pyinstaller Rose.spec` directly, because the Rose build scripts compile
Pengu Loader first.

## Credits

Rose uses the [official Pengu Loader](https://github.com/PenguLoader/PenguLoader)
project. Its source is vendored and built as part of Rose, with Rose-specific
lifecycle integration added around the loader. Please see the
[official Pengu Loader license](https://github.com/PenguLoader/PenguLoader/blob/main/LICENSE)
and credit the Pengu Loader contributors.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and project structure.

## Legal Disclaimer

This project is not endorsed by or affiliated with Riot Games. Riot Games and all related properties are trademarks or registered trademarks of Riot Games, Inc.

Custom skins are allowed under Riot's terms of service and are not detected. Do not discuss or advertise skin tools in game. Users proceed at their own risk.

## Support

If you enjoy Rose and want to support its development:

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/roseapp)

Your support helps keep the project alive and motivates continued development!

---

**Rose** - _League, unlocked._
