<div align="center">

# Rose

<img src="./assets/icon.png" alt="Rose" width="112" height="112">

**Every League of Legends skin, right from champion select.**

[![Installer](https://img.shields.io/badge/Installer-Windows-32A832)](https://github.com/Alban1911/Rose/releases/latest) [![Downloads](https://img.shields.io/github/downloads/Alban1911/Rose/total?color=32A832&label=Downloads&cacheSeconds=86400)](https://github.com/Alban1911/Rose/releases/latest) [![Discord](https://img.shields.io/discord/1490473857075642621?color=32A832&logo=discord&logoColor=white&label=Discord)](https://discord.com/invite/roseskins) [![Ko-Fi](https://img.shields.io/badge/KoFi-Donate-C03030?logo=ko-fi&logoColor=white)](https://ko-fi.com/roseapp) [![License](https://img.shields.io/badge/License-MIT-C03030)](LICENSE)

</div>

> [!CAUTION]
> `roseskin.xyz` has nothing to do with Rose, and **its download contains malware**. If you installed anything from it, reinstall Windows. Rose is only distributed through [GitHub Releases](https://github.com/Alban1911/Rose/releases/latest).

Rose is a free, open-source skin changer. It sits in the system tray, adds its menus to the League client, and applies the skin you hover in champion select when the game loads. Only you see the skin (and your friends, with Party Mode), and gameplay doesn't change: Rose gives **no competitive advantage**.

## Features

- **Every skin, chroma and form**, picked straight from champion select
- **Custom mods**: skins, maps, fonts, announcers and more (`.fantome`, `.zip`, `.modpkg`)
- **Party Mode**: friends running Rose see each other's skins in game
- **Random and Historic** skin picks, and the skin's name on the loading screen
- **22 languages**, following your League client
- **Free**: if you paid for Rose, you got scammed 💀

## Install

1. Install **[LTK Manager](https://github.com/LeagueToolkit/ltk-manager/releases)**, which Rose applies skins through. You never have to open it.
2. Download and run the [**latest Rose installer**](https://github.com/Alban1911/Rose/releases/latest).
3. Start Rose, then hover a skin in champion select.

Rose needs Windows 10 or 11 and updates itself.

## FAQ

<details>
<summary><b>How does it work?</b></summary>

<br>

Rose loads its plugins into the League client with [Pengu Loader](https://github.com/PenguLoader/PenguLoader). Just before the champion select countdown ends, it locks in the skin you hover and has LTK Manager patch it into the game. The point where it locks in is the **Injection Threshold** (1 to 2 seconds, in Settings): a change after it is ignored. See [Architecture](CONTRIBUTING.md#architecture) for the full picture.

</details>

<details>
<summary><b>Do I need to open LTK Manager?</b></summary>

<br>

No. Rose starts it in the background and closes it after the game. Leave it closed: if it is already open when a game starts, Rose skips the skin and asks you to close it. Your own LTK Manager mods are paused for the game and turned back on after.

If Rose can't find LTK Manager, click **Set up path** at startup and select `ltk-manager.exe`.

</details>

<details>
<summary><b>Rose doesn't show up in the client, or skins don't load</b></summary>

<br>

Open the **Troubleshooting** panel in Rose's settings, or right-click the tray icon and choose **Diagnose Rose startup**. See [docs/troubleshooting.md](docs/troubleshooting.md) for the diagnostic report and for recovering an interrupted update, and ask on [Discord](https://discord.com/invite/roseskins) if you're stuck.

</details>

<details>
<summary><b>Does Rose collect data?</b></summary>

<br>

Only a random installation ID and the app version, sent to `analytics.rosekeys.site` at startup, every 15 minutes while Rose runs, and when it closes. The ID is not tied to your hardware or account. Builds from source can turn it off with `ANALYTICS_ENABLED = False` in `config.py`.

</details>

## Contributing

Bug reports, translations and pull requests are welcome. [CONTRIBUTING.md](CONTRIBUTING.md) covers how to contribute, then [how Rose works](CONTRIBUTING.md#architecture).

## Credits

[Pengu Loader](https://github.com/PenguLoader/PenguLoader) (vendored and built with Rose, see its [license](https://github.com/PenguLoader/PenguLoader/blob/main/LICENSE)) · [LTK Manager](https://github.com/LeagueToolkit/ltk-manager) · [CommunityDragon](https://github.com/CommunityDragon/Data)

## Legal

Rose is not endorsed by or affiliated with Riot Games. Riot Games and all related properties are trademarks or registered trademarks of Riot Games, Inc. Riot Games does not allow custom skins that reproduce its real skins, which is what Rose does. Use Rose at your own risk: its developers are not responsible for any consequence, including account suspensions or bans.

<div align="center">
<br>

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/roseapp)

**Rose** · *League, unlocked.*

</div>
