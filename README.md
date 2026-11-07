# MCP User UI
User interface for MCP servers, for USER!!!!

## Set up environment

Run from the project root. Pick your platform:

**Windows (PowerShell)**
```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

**macOS / Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Run

```bash
flet run
```

## Build (pick one)

```bash
flet build windows
flet build macos
flet build linux
flet build apk
flet build aab
flet build ipa
flet build ios-simulator
flet build web
```


## Text size and readability

Open **Settings → Text & readability** to adjust two independent sliders:

- **Interface text size** (100–180%): menus, buttons, forms, labels, and navigation.
- **Answer text size** (100–180%): Markdown answers, lists, headings, and code.

Changes preview immediately, save when you release the slider, and persist locally.
**Reset text sizes** returns both sliders to 100%. The UI scales fonts rather than
stretching the whole window; the desktop navigation rail remains pinned.
