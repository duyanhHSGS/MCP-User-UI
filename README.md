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
