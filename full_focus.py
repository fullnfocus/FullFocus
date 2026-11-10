import logging
import os
import psutil
import threading
import pystray
import subprocess
import sys
import socket
from logging.handlers import RotatingFileHandler
from PIL import Image
from datetime import datetime
from pathlib import Path

from focus_core import (
    Cooldown,
    build_app_lookup,
    describe_block,
    get_app_dir,
    get_resource_path,
    normalize,
    read_config_file,
    should_kill_app,
)

APP_DIR = get_app_dir()
CONFIG_PATH = APP_DIR / "focus_config.json"
LOG_PATH = APP_DIR / "focus.log"

HOST = "127.0.0.1"
PORT = 51372

BLOCK_ACTIVE = True
stop_event = threading.Event()
LAST_VALID_CONFIG = None
settings_process = None
tray_icon = None

# one notification per app per minute is plenty
notify_cooldown = Cooldown(seconds=60)

log = logging.getLogger("fullfocus")


def setup_logging():
    # the .exe has no console, so everything goes to focus.log next to it
    # max 1 MB per file, keeps 2 old ones around
    handler = RotatingFileHandler(
        LOG_PATH,
        maxBytes=1_000_000,
        backupCount=2,
        encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))

    log.setLevel(logging.INFO)
    log.addHandler(handler)


def load_config():
    # if the file breaks while running, keep using the last good config
    global LAST_VALID_CONFIG

    try:
        config = read_config_file(CONFIG_PATH)
        LAST_VALID_CONFIG = config
        return config

    except Exception:
        log.exception("couldn't read %s", CONFIG_PATH)

        if LAST_VALID_CONFIG is not None:
            log.warning("using the last valid config instead")
            return LAST_VALID_CONFIG

        raise RuntimeError(
            f"Could not load config file: {CONFIG_PATH}"
        )

def get_self_command():
    # how to relaunch ourselves: the .exe, or python + this script
    if getattr(sys, "frozen", False):
        return [sys.executable]

    return [sys.executable, str(Path(__file__))]

def open_settings(icon=None, item=None):
    global settings_process

    try:
        # don't open 10 copies of settings
        if settings_process is not None and settings_process.poll() is None:
            return

        cmd = get_self_command() + ["--settings-window"]

        settings_process = subprocess.Popen(
            cmd,
            cwd=str(APP_DIR),
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )

    except Exception:
        log.exception("couldn't open settings")

def open_log(icon=None, item=None):
    try:
        if not LOG_PATH.exists():
            LOG_PATH.touch()

        os.startfile(LOG_PATH)

    except Exception:
        log.exception("couldn't open the log file")

def notify_blocked(app_name, app_config, now):
    if tray_icon is None or not notify_cooldown.ready(normalize(app_name), now):
        return

    try:
        tray_icon.notify(describe_block(app_name, app_config, now), "Full Focus")

    except Exception:
        # notifications are a nice-to-have, never let them break blocking
        log.exception("couldn't show a notification")

def monitor():
    my_pid = os.getpid()

    while not stop_event.is_set():
        try:
            config = load_config()
            settings = config.get("global", {})
            interval = settings.get("check_interval_seconds", 3)
            notifications_on = settings.get("notifications", True)

            if BLOCK_ACTIVE:
                # once per scan, not per process
                app_lookup = build_app_lookup(config)
                now = datetime.now()

                for proc in psutil.process_iter(["name"]):
                    try:
                        process_name = proc.info["name"]

                        # never kill ourselves, even if someone adds us to the list
                        if proc.pid == my_pid:
                            continue

                        if should_kill_app(process_name, app_lookup, now):
                            proc.kill()
                            log.info("closed %s (pid %s)", process_name, proc.pid)

                            if notifications_on:
                                app_config = app_lookup[normalize(process_name)]
                                notify_blocked(process_name, app_config, now)

                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

            stop_event.wait(interval)

        except Exception:
            log.exception("monitor loop crashed, retrying in 3s")
            stop_event.wait(3)


def toggle_blocking(icon, item):
    global BLOCK_ACTIVE
    BLOCK_ACTIVE = not BLOCK_ACTIVE
    icon.title = f"Full Focus - {'ON' if BLOCK_ACTIVE else 'OFF'}"
    log.info("blocking turned %s", "on" if BLOCK_ACTIVE else "off")

def quit_app(icon, item):
    log.info("quit from the tray menu")
    stop_event.set()
    icon.stop()



def create_tray_icon():
    global tray_icon

    img = Image.open(get_resource_path("icon.ico"))

    menu = pystray.Menu(
        pystray.MenuItem("Settings", open_settings),
        pystray.MenuItem(
            "Toggle blocking",
            toggle_blocking,
            checked=lambda item: BLOCK_ACTIVE
        ),
        pystray.MenuItem("Open log", open_log),
        pystray.MenuItem("Quit", quit_app)
    )

    tray_icon = pystray.Icon(
        "blocker",
        img,
        "Full Focus - ON",
        menu
    )

    tray_icon.run()

def send_command_to_running_instance(command):
    # returns False if nothing is running yet
    try:
        with socket.create_connection((HOST, PORT), timeout=0.5) as sock:
            sock.sendall(command.encode("utf-8"))
        return True

    except OSError:
        return False


def command_server():
    # listens for messages from later launches of the app
    server = None

    try:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen(5)
        server.settimeout(1)

        while not stop_event.is_set():
            try:
                conn, addr = server.accept()

                with conn:
                    command = conn.recv(1024).decode("utf-8").strip()

                    if command == "SHOW_SETTINGS":
                        open_settings()

            except socket.timeout:
                continue

            except Exception:
                log.exception("command server connection error")

    except Exception:
        log.exception("command server stopped")

    finally:
        if server is not None:
            server.close()

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
    # settings window only
    if "--settings-window" in sys.argv:
        run_settings_window()
        sys.exit(0)

    # already running? just ask it to open settings
    if send_command_to_running_instance("SHOW_SETTINGS"):
        sys.exit(0)

    # first instance, start the blocker
    setup_logging()
    log.info("full focus started")

    command_thread = threading.Thread(target=command_server, daemon=True)
    command_thread.start()

    monitor_thread = threading.Thread(target=monitor, daemon=True)
    monitor_thread.start()

    create_tray_icon()
