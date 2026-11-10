# Full Focus

[![tests](https://github.com/fullnfocus/FullFocus/actions/workflows/tests.yml/badge.svg)](https://github.com/fullnfocus/FullFocus/actions/workflows/tests.yml)

A lightweight Windows tray app that keeps distracting apps closed either all the time, or outside the time windows you allow.

I built it for myself because "just don't open Steam during the week" never worked, so I made my computer enforce it.

<!-- TODO: replace with a short screen recording, e.g. docs/demo.gif
     (open a blocked app -> it closes within a few seconds) -->
![Demo](docs/demo.gif)

## Features

- **Two blocking modes**
  - `constant`: blocked whenever Full Focus is on
  - `scheduled`: blocked by default, allowed only inside the windows you define
- **Flexible time windows**: per weekday, including overnight windows (`fri 22:00 → 02:00` keeps working past midnight into Saturday)
- **Notifications**: tells you when it closes something and when the app is allowed again ("discord.exe is blocked until 18:00")
- **Runs quietly in the system tray**: toggle blocking, open settings, open the log, or quit from the tray menu
- **Settings window**: add/edit apps and rules without touching JSON, or pick apps straight from a list of running processes
- **Safe by default**: refuses to block Windows system processes (like `explorer.exe`) or itself
- **Log file**: everything it closes, plus any errors, goes to `focus.log` next to the app
- **Launch on Windows startup** (optional, one checkbox)
- **Single instance**: launching it again opens the settings of the copy already running instead of starting a second blocker
- **Resilient config**: if `focus_config.json` gets corrupted while running, it keeps using the last valid version

## Install

1. Download `FullFocus.exe` from the [latest release](https://github.com/fullnfocus/FullFocus/releases/latest).
2. Put it in its own folder (it creates `focus_config.json` next to itself on first run) and run it.
3. Right-click the tray icon → **Settings** to add apps.

## Configuring apps

In the settings window, click **Pick from running apps...** (or type the process name from Task Manager → Details, e.g. `steam.exe`), pick a mode, and for scheduled apps type one allowed window per line:

```
day[,day...] start end
```

```
mon,tue,wed,thu,fri 18:00 23:00    weekday evenings
sat 10:00 02:00                    Saturday 10:00 until Sunday 02:00
sun 00:00 00:00                    all of Sunday (same start and end = whole day)
```

The settings are stored in `focus_config.json`; see [`focus_config.example.json`](focus_config.example.json) for the format.

## How it works

```
 ┌──────────── tray app (main thread) ────────────┐
 │ pystray icon: Settings / Toggle blocking / Quit │
 └─────────────────────────────────────────────────┘
        │ starts                         │ starts
        ▼                                ▼
 monitor thread                   command server thread
 every N seconds:                 listens on 127.0.0.1:51372
  1. reload config                 "SHOW_SETTINGS" → open settings
  2. list running processes        (sent by a second launch of the app)
  3. close the ones focus_core
     says are blocked right now
```

- **`focus_core.py`**: all decision logic (rule parsing, schedule evaluation, config handling). Pure Python with no Windows dependencies, so it is fully unit-tested.
- **`full_focus.py`**: the background app: tray icon, process monitor (`psutil`), single-instance IPC over a local socket.
- **`settings_ui.py`**: Tkinter settings window and the Windows startup registry entry.

Processes are scanned every `check_interval_seconds` (default 3), so a blocked app may stay open for up to a few seconds before it is closed.

## Run from source

Requires Python 3.11+ on Windows.

```bash
pip install -r requirements.txt
python full_focus.py
```

Build the single-file executable:

```bash
pip install pyinstaller
pyinstaller FullFocus.spec      # output: dist/FullFocus.exe
```

## Tests

```bash
pip install pytest
pytest
```

The tests cover the scheduling edge cases: overnight windows, the Sunday→Monday wrap, whole-day rules, inclusive start / exclusive end, disabled apps, and rule parsing. They run on every push via GitHub Actions on Python 3.11–3.13.

## Limitations and ideas

- Blocking is by process name, so a renamed `.exe` is not caught.
- It's a self-control tool, not a security tool: you can always quit it from the tray. A **strict mode** that can't be switched off mid-session is the next planned feature.
- Usage statistics (how often each app was blocked) would make it easier to see whether it's helping.
