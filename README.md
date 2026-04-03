# 🌹 Rose - Effortless Skin Changer for LoL

<div align="center">

  <img src="./assets/icon.png" alt="Rose Icon" width="128" height="128">

[![Installer](https://img.shields.io/badge/Installer-Windows-32A832)](https://github.com/Alban1911/Rose/releases/latest) [![Ko-Fi](https://img.shields.io/badge/KoFi-Donate-C03030?logo=ko-fi&logoColor=white)](https://ko-fi.com/roseapp) [![Discord](https://img.shields.io/discord/1465467335946272780?color=32A832&logo=discord&logoColor=white&label=Discord)](https://discord.com/invite/roseapp) [![License](https://img.shields.io/badge/License-Open%20Source-C03030)](LICENSE) [![Downloads](https://img.shields.io/github/downloads/Alban1911/Rose/total?color=32A832&label=Downloads)](https://github.com/Alban1911/Rose/releases/latest)


</div>

---

## Overview

Rose is an open-source automatic skin changer for League of Legends that enables seamless access to all skins in the game. The application runs silently in the system tray and automatically detects skin selections during champion select, injecting the chosen skin when the game loads.

**Rose is built on Pengu Loader**, a plugin system that injects JavaScript plugins into the League Client, enabling enhanced UI interactions and quick skin detection.

## Architecture

Rose consists of three main components:

### Python Backend

- **LCU API Integration**: Communicates with the League Client via the League Client Update (LCU) API
- **Skin Injection**: Handles skin injection compatible with Riot Vanguard
- **WebSocket Bridge**: Operates a WebSocket server for real-time communication with frontend plugins
- **Skin Management**: Downloads and manages encrypted skin files from the [RoseSkin repository](https://github.com/Alban1911/RoseSkin) — files are decrypted at runtime and wiped after use
- **Party Mode**: Enables skin sharing between friends in the same lobby via a Cloudflare WebSocket relay
- **Game Monitoring**: Tracks game state, champion select phases, and loadout countdowns
- **Analytics**: Sends periodic pings to track unique users (configurable, runs in background thread)

### Cloudflare Workers

- **rose-party-relay**: Durable Object-backed WebSocket relay that manages party rooms (max 10 members per room) for real-time skin selection broadcasting between friends
- **rose-skin-key**: Serves the skin decryption key at runtime

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

## How It Works

1. **League Client Integration**: Rose activates **Pengu Loader** on startup, which injects the JavaScript plugins into the League Client
2. **Skin Detection**: When you hover over a skin in champion select, `ROSE-SkinMonitor` detects the selection and sends it to the Python backend
3. **Game Opening Delay**: To make sure the injection has time to occur we suspend League of Legend's game process as long as the overlay is not ran
4. **Game Injection**: Rose decrypts and injects the selected skin when the game starts
5. **Seamless Experience**: The skin loads as if you owned it, with full chroma support and no gameplay impact (**Rose will never provide any competitive advantage to its users**)

## Features

- **Smart Injection**: Never injects skins you already own
- **Multi-Language Support**: Works with any client language
- **Open Source**: Fully open source and extensible
- **Free**: If you bought this software, you got scammed 💀

## Requirements

- **Windows 10/11**
- **League of Legends** installed
- **Injection DLL** - You must provide your own signed DLL (see below)

### DLL Requirement

Due to DMCA restrictions, Rose cannot distribute the injection DLL file. You must obtain this file yourself from an authorized source and sign it with your own code signing certificate.

On first launch, Rose will prompt you to provide this file and open the folder where it should be placed.

## Installation

1. Download the latest installer from [Releases](https://github.com/Alban1911/Rose/releases/latest)
2. Run the installer as Administrator
3. Launch Rose from the Start Menu or desktop shortcut

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
