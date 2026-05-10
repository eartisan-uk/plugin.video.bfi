# plugin.video.bfi

A Kodi add-on for browsing and playing content from the [BFI Player](https://player.bfi.org.uk) — the British Film Institute's streaming platform, featuring free films and a paid BFI+ subscription library.

## Features

**Free content**
- Popular films and shorts
- Inside Film — talks, Q&As, and documentary content
- Shorts — short film collections
- Collections — themed free collections (e.g. Queer East Festival, Born Digital)

**BFI+ subscription content** (requires a BFI+ account)
- Subscription Exclusives
- Recently Added
- Kermode Introduces
- Popular
- Collections — browse all themed subscription collections (e.g. French New Wave, Brazil on Film)
- Coming Soon

**Account**
- Watchlist — your saved films from the BFI Player website

**General**
- Search the BFI archive with saved search history
- Recently Viewed history for fast replay
- Full Brightcove DASH + Widevine DRM support via `inputstream.adaptive`

## Installation

### Via the BFI Player Repository (recommended)

Installing via the repository means Kodi will notify you of updates automatically.

1. In Kodi, go to **Settings → System → Add-ons** and enable **Unknown sources**
2. Go to **Add-ons → Install from zip file** and enter this URL when prompted:
   ```
   https://raw.githubusercontent.com/eartisan-uk/plugin.video.bfi/main/kodi-repo/repository.eartisan.bfi/repository.eartisan.bfi-1.0.0.zip
   ```
3. Once the repository is installed, go to **Add-ons → Install from repository → BFI Player Repository → Video add-ons → BFI Player** and install

### Manual zip install

If you prefer not to add the repository, download the latest `plugin.video.bfi-x.x.x.zip` from the [`kodi-repo/plugin.video.bfi/`](../kodi-repo/plugin.video.bfi/) folder and install it via **Add-ons → Install from zip file**.

## Requirements

- Kodi 21 (Omega) or later
- `inputstream.adaptive` add-on installed and enabled
- Widevine CDM installed (for DRM-protected streams)
- `script.module.routing`, `script.module.beautifulsoup4`, `script.module.requests`

## BFI+ Login

1. Open Settings → Account
2. Enter your BFI+ email address and password
3. Tap **Sign In**

Once signed in, enable **BFI+** in Settings → Menu to show the Subscription and Watchlist sections in the main menu.

## Icon generation (developers only)

New menu icons can be regenerated after installing Pillow:

```bash
pip install Pillow
cd resources/media
python make_icons.py
```

## Disclaimer

This add-on is not created, maintained, or in any way affiliated with the British Film Institute. It provides an interface to content on the BFI Player website from within Kodi.

## Acknowledgements

This add-on was inspired by [Fraser Chapman's original plugin.video.bfi](https://github.com/FraserChapman/plugin.video.bfi). The codebase has since been substantially rewritten to support Kodi 21, the BFI Player's redesigned website, Brightcove DASH streaming with Widevine DRM, and BFI+ account login — but the original project was the starting point.

## Licence

All code is provided under the [MIT Licence](LICENSE.txt).

`icon.png` and `fanart.jpg` are sourced from public domain / Creative Commons material:

- Icon: [BFI Player Twitter](https://twitter.com/bfiplayer) — Public Domain / Fair use
- Fanart: [Maria Giulia Tolotti — CC BY-SA 3.0](https://commons.wikimedia.org/wiki/File:BFI_Southbank0182.JPG)
