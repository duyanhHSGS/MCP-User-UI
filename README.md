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


## Saved MCP connections

On the **Connection** screen, connect successfully before using **Save endpoint
& tokens**. The button is disabled and gray until an MCP connection succeeds.
Saving is strictly opt-in: connecting alone never writes bearer or OAuth
credentials. Saved connections reconnect with one click; **✕** removes the
endpoint and stored credentials (disconnecting that active endpoint first
so OAuth refresh cannot recreate its tokens). Deleting saved OAuth does
not revoke a grant at the server; revoke that separately at the provider.

The app uses Flet's cross-platform native app storage directories:

| Directory | Data |
| --- | --- |
| `FLET_APP_STORAGE_DATA` | `saved-mcp-connections.json` (URLs, auth type, bearer tokens), and `mcp-oauth-tokens/` (FastMCP OAuth access/refresh tokens and client registration) |
| `FLET_APP_STORAGE_CACHE` | Disposable MCP discovery counts only (`mcp-discovery-counts.json`), without URLs, arguments or credentials |
| `FLET_APP_STORAGE_TEMP` | Short-lived scratch file for disposable discovery counts, immediately removed |

Under `flet run`, directories resolve to
`<project>/.flet/storage/{data,cache,temp}`. Packaged Android, Linux and
other native platforms receive Flet's app-private OS directories. If the
app data environment variable is unavailable, the app does not invent
a fallback storage path for credentials.

**Security:** credential files are **not encrypted**. File writes use
`0600` and OAuth subtree directories use `0700` on POSIX. Anyone with
access to your account/device may still read those secrets. Do not save
credentials on a shared or untrusted machine; stronger protection requires
an OS-backed SecureStorage backend. OAuth credentials may expire or be
revoked, requiring another browser login. OAuth callbacks on physical
Android/iOS devices have not been independently verified.
