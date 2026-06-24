import psutil
import threading
import pystray
import traceback
import json
import subprocess
import sys
import socket
from PIL import Image, ImageDraw
from datetime import datetime
from pathlib import Path

def get_app_dir():
    if getattr(sys, "frozen", False):
        # When running as .exe
        return Path(sys.executable).parent

    # When running as .py
    return Path(__file__).parent

APP_DIR = get_app_dir()
CONFIG_PATH = APP_DIR / "focus_config.json"
SETTINGS_UI_PATH = Path(__file__).with_name("settings_ui.py")

HOST = "127.0.0.1"
PORT = 51372

BLOCK_ACTIVE = True
stop_event = threading.Event()
LAST_VALID_CONFIG = None
settings_process = None




DAYS = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6
}

def load_config():
    """
    Loads config from focus_config.json.

    If the config is broken after the app already started,
    it keeps using the last valid version.
    """
    global LAST_VALID_CONFIG

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)

        LAST_VALID_CONFIG = config
        return config

    except Exception as e:
        print("Config error:", e)
        traceback.print_exc()

        if LAST_VALID_CONFIG is not None:
            print("Using last valid config.")
            return LAST_VALID_CONFIG

        raise RuntimeError(
            f"Could not load config file: {CONFIG_PATH}"
        )

def get_self_command():
    """
    Returns the command needed to launch this same app.

    In normal Python dev mode:
        python full_focus.py

    In PyInstaller .exe mode:
        FullFocus.exe
    """
    if getattr(sys, "frozen", False):
        return [sys.executable]

    return [sys.executable, str(Path(__file__))]

def open_settings(icon=None, item=None):
    global settings_process

    try:
        # If settings is already open, don't open 10 copies.
        if settings_process is not None and settings_process.poll() is None:
            print("Settings window is already open.")
            return

        cmd = get_self_command() + ["--settings-window"]

        settings_process = subprocess.Popen(
            cmd,
            cwd=str(APP_DIR),
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )

        print("Opened settings.")

    except Exception as e:
        print("Failed to open settings:", e)
        traceback.print_exc()

def normalize(name):
    return name.lower().strip() if name else ""

def parse_time_to_minutes(value):
    """
    Converts '19:30' into minutes after midnight.
    """
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)

def get_rule_days(rule):
    days = rule.get("days", [])

    if not days:
        return set(range(7))

    result = set()

    for day in days:
        day = day.lower()

        if day in DAYS:
            result.add(DAYS[day])

    return result

def is_rule_active(rule, now):
    """
    Returns True if the current time is inside this allowed window.

    Example:
    {
        "days": ["tue"],
        "start": "19:00",
        "end": "00:00"
    }

    means Tuesday from 19:00 until midnight.
    """
    allowed_days = get_rule_days(rule)

    start = parse_time_to_minutes(rule["start"])
    end = parse_time_to_minutes(rule["end"])

    current = now.hour * 60 + now.minute
    today = now.weekday()
    yesterday = (today - 1) % 7

    # Full-day rule
    # Example: 00:00 -> 00:00 means the entire selected day
    if start == end:
        return today in allowed_days

    # Normal same-day rule
    # Example: 09:00 -> 18:00
    if start < end:
        return today in allowed_days and start <= current < end

    # Overnight rule
    # Example: 22:00 -> 02:00
    return (
        today in allowed_days and current >= start
    ) or (
        yesterday in allowed_days and current < end
    )

def is_inside_allowed_window(app_config, now):
    rules = app_config.get("rules", [])

    return any(is_rule_active(rule, now) for rule in rules)


def is_app_blocked_by_config(app_config, now):
    if not app_config.get("enabled", True):
        return False

    mode = app_config.get("mode", "constant").lower()

    if mode == "constant":
        return True

    if mode == "scheduled":
        # Important:
        # scheduled apps are blocked by default.
        # rules are allowed exceptions.
        return not is_inside_allowed_window(app_config, now)

    return False

def build_app_lookup(config):
    apps = {}

    for app in config.get("apps", []):
        name = normalize(app.get("name"))

        if name:
            apps[name] = app

    return apps

def should_kill_app(process_name, config):
    process_name = normalize(process_name)

    if not process_name:
        return False

    app_lookup = build_app_lookup(config)
    app_config = app_lookup.get(process_name)

    if app_config is None:
        return False

    now = datetime.now()

    return is_app_blocked_by_config(app_config, now)

def monitor():
    while not stop_event.is_set():
        try:
            config = load_config()
            interval = config.get("global", {}).get("check_interval_seconds", 3)

            if BLOCK_ACTIVE:
                for proc in psutil.process_iter(["name"]):
                    try:
                        process_name = proc.info["name"]

                        if should_kill_app(process_name, config):
                            print(f"Killing blocked app: {process_name}")
                            proc.kill()

                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

            stop_event.wait(interval)

        except Exception as e:
            print("Monitor error:", e)
            traceback.print_exc()
            stop_event.wait(3)


def toggle_blocking(icon, item):
    global BLOCK_ACTIVE
    BLOCK_ACTIVE = not BLOCK_ACTIVE
    icon.title = f"Full Focus - {'ON' if BLOCK_ACTIVE else 'OFF'}"

def quit_app(icon, item):
    stop_event.set()
    icon.stop()



def create_tray_icon():
    ICON_PATH = APP_DIR / "icon.ico"
    img = Image.open(ICON_PATH)

    menu = pystray.Menu(
        pystray.MenuItem("Settings", open_settings),
        pystray.MenuItem(
            "Toggle blocking",
            toggle_blocking,
            checked=lambda item: BLOCK_ACTIVE
        ),
        pystray.MenuItem("Quit", quit_app)
    )

    icon = pystray.Icon(
        "blocker",
        img,
        "Full Focus - ON",
        menu
    )

    icon.run()

def send_command_to_running_instance(command):
    """
    Tries to contact an already-running Full Focus instance.

    Returns True if another instance received the command.
    Returns False if no instance is running.
    """
    try:
        with socket.create_connection((HOST, PORT), timeout=0.5) as sock:
            sock.sendall(command.encode("utf-8"))
        return True

    except OSError:
        return False


def command_server():
    """
    Runs inside the main background app.
    Listens for commands from future launches.
    """
    try:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen(5)
        server.settimeout(1)

        print(f"Command server listening on {HOST}:{PORT}")

        while not stop_event.is_set():
            try:
                conn, addr = server.accept()

                with conn:
                    command = conn.recv(1024).decode("utf-8").strip()

                    if command == "SHOW_SETTINGS":
                        print("Received SHOW_SETTINGS command.")
                        open_settings()

            except socket.timeout:
                continue

            except Exception as e:
                print("Command server connection error:", e)
                traceback.print_exc()

    except Exception as e:
        print("Command server error:", e)
        traceback.print_exc()

    finally:
        try:
            server.close()
        except Exception:
            pass

def run_settings_window():
    from settings_ui import SettingsApp
    import tkinter as tk

    root = tk.Tk()
    app = SettingsApp(root)

    def on_close():
        root.quit()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()

if __name__ == "__main__":
    # Special mode: open only the settings window.
    if "--settings-window" in sys.argv:
        run_settings_window()
        sys.exit(0)

    # Normal launch.
    # If app is already running, tell it to show settings and exit.
    if send_command_to_running_instance("SHOW_SETTINGS"):
        print("Full Focus is already running. Opening settings window.")
        sys.exit(0)

    # No running instance found, so this is the main background app.
    command_thread = threading.Thread(target=command_server, daemon=True)
    command_thread.start()

    monitor_thread = threading.Thread(target=monitor, daemon=True)
    monitor_thread.start()

    create_tray_icon()
