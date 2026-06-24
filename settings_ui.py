import json
from pathlib import Path
import tkinter as tk
import sys
import winreg
from pathlib import Path
from tkinter import ttk, messagebox

def get_app_dir():
    if getattr(sys, "frozen", False):
        # Running as PyInstaller .exe
        return Path(sys.executable).resolve().parent

    # Running as normal .py file
    return Path(__file__).resolve().parent


APP_DIR = get_app_dir()
CONFIG_PATH = APP_DIR / "focus_config.json"

VALID_DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
APP_NAME = "FullFocus"


def load_config():
    if not CONFIG_PATH.exists():
        return {
            "global": {
                "check_interval_seconds": 3
            },
            "apps": []
        }

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)


def validate_time(value):
    try:
        hour, minute = value.split(":")
        hour = int(hour)
        minute = int(minute)

        return 0 <= hour <= 23 and 0 <= minute <= 59

    except Exception:
        return False


def parse_rules_text(text):
    """
    Expected format, one rule per line:

    tue 19:00 00:00
    wed 00:00 07:00
    mon,tue,wed 18:00 22:00
    """
    rules = []

    lines = text.strip().splitlines()

    for line in lines:
        line = line.strip()

        if not line:
            continue

        parts = line.split()

        if len(parts) != 3:
            raise ValueError(
                f"Invalid rule: {line}\n\n"
                "Use format: tue 19:00 00:00"
            )

        days_part, start, end = parts

        days = [day.strip().lower() for day in days_part.split(",")]

        for day in days:
            if day not in VALID_DAYS:
                raise ValueError(f"Invalid day: {day}")

        if not validate_time(start):
            raise ValueError(f"Invalid start time: {start}")

        if not validate_time(end):
            raise ValueError(f"Invalid end time: {end}")

        rules.append({
            "days": days,
            "start": start,
            "end": end
        })

    return rules


def rules_to_text(rules):
    lines = []

    for rule in rules:
        days = ",".join(rule.get("days", []))
        start = rule.get("start", "00:00")
        end = rule.get("end", "00:00")

        lines.append(f"{days} {start} {end}")

    return "\n".join(lines)


class SettingsApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Full Focus Settings")
        self.root.geometry("700x450")

        self.config = load_config()

        self.create_widgets()
        self.refresh_app_list()

    def create_widgets(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill="both", expand=True)

        left = ttk.Frame(main)
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))

        right = ttk.Frame(main)
        right.pack(side="right", fill="both", expand=True)

        ttk.Label(left, text="Apps").pack(anchor="w")

        self.app_listbox = tk.Listbox(left, height=20)
        self.app_listbox.pack(fill="both", expand=True)
        self.app_listbox.bind("<<ListboxSelect>>", self.on_app_select)

        ttk.Button(left, text="Delete selected app", command=self.delete_selected_app).pack(fill="x", pady=(10, 0))

        ttk.Label(right, text="App name / process name").pack(anchor="w")
        self.name_entry = ttk.Entry(right)
        self.name_entry.pack(fill="x", pady=(0, 10))

        self.enabled_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(right, text="Enabled", variable=self.enabled_var).pack(anchor="w", pady=(0, 10))

        self.startup_var = tk.BooleanVar(value=is_startup_enabled())

        ttk.Checkbutton(
            right,
            text="Launch Full Focus on Windows startup",
            variable=self.startup_var,
            command=self.toggle_startup
        ).pack(anchor="w", pady=(0, 10))

        ttk.Label(right, text="Mode").pack(anchor="w")
        self.mode_var = tk.StringVar(value="constant")
        self.mode_box = ttk.Combobox(
            right,
            textvariable=self.mode_var,
            values=["constant", "scheduled"],
            state="readonly"
        )
        self.mode_box.pack(fill="x", pady=(0, 10))
        self.mode_box.bind("<<ComboboxSelected>>", self.on_mode_change)

        ttk.Label(
            right,
            text="Allowed windows for scheduled apps\nFormat: day start end\nExample: tue 19:00 00:00"
        ).pack(anchor="w")

        self.rules_text = tk.Text(right, height=8)
        self.rules_text.pack(fill="both", expand=True, pady=(0, 10))

        ttk.Button(right, text="Add / Update app", command=self.save_app).pack(fill="x")

        help_text = (
            "constant = blocked whenever blocker is ON\n"
            "scheduled = blocked by default, allowed only during these windows\n"
            "days: mon, tue, wed, thu, fri, sat, sun"
        )

        ttk.Label(right, text=help_text).pack(anchor="w", pady=(10, 0))

    def toggle_startup(self):
        try:
            set_startup_enabled(self.startup_var.get())

            if self.startup_var.get():
                messagebox.showinfo("Startup enabled", "Full Focus will launch when Windows starts.")
            else:
                messagebox.showinfo("Startup disabled", "Full Focus will no longer launch when Windows starts.")

        except Exception as e:
            messagebox.showerror("Startup error", str(e))

    def refresh_app_list(self):
        self.app_listbox.delete(0, tk.END)

        for app in self.config.get("apps", []):
            name = app.get("name", "unknown")
            mode = app.get("mode", "constant")
            enabled = app.get("enabled", True)

            status = "ON" if enabled else "OFF"

            self.app_listbox.insert(tk.END, f"{name} | {mode} | {status}")

    def get_selected_app_index(self):
        selection = self.app_listbox.curselection()

        if not selection:
            return None

        return selection[0]

    def on_app_select(self, event=None):
        index = self.get_selected_app_index()

        if index is None:
            return

        app = self.config["apps"][index]

        self.name_entry.delete(0, tk.END)
        self.name_entry.insert(0, app.get("name", ""))

        self.enabled_var.set(app.get("enabled", True))
        self.mode_var.set(app.get("mode", "constant"))

        self.rules_text.delete("1.0", tk.END)
        self.rules_text.insert("1.0", rules_to_text(app.get("rules", [])))

        self.on_mode_change()

    def on_mode_change(self, event=None):
        mode = self.mode_var.get()

        if mode == "constant":
            self.rules_text.configure(state="disabled")
        else:
            self.rules_text.configure(state="normal")

    def save_app(self):
        name = self.name_entry.get().strip()

        if not name:
            messagebox.showerror("Error", "App name cannot be empty.")
            return

        if not name.lower().endswith(".exe"):
            messagebox.showwarning(
                "Warning",
                "Usually Windows process names end with .exe, for example steam.exe."
            )

        mode = self.mode_var.get()
        enabled = self.enabled_var.get()

        app_data = {
            "name": name,
            "enabled": enabled,
            "mode": mode
        }

        if mode == "scheduled":
            try:
                rules = parse_rules_text(self.rules_text.get("1.0", tk.END))
            except ValueError as e:
                messagebox.showerror("Invalid rules", str(e))
                return

            app_data["rules"] = rules

        apps = self.config.setdefault("apps", [])

        existing_index = None

        for i, app in enumerate(apps):
            if app.get("name", "").lower() == name.lower():
                existing_index = i
                break

        if existing_index is None:
            apps.append(app_data)
        else:
            apps[existing_index] = app_data

        save_config(self.config)
        self.refresh_app_list()

        messagebox.showinfo("Saved", "App saved successfully.")

    def delete_selected_app(self):
        index = self.get_selected_app_index()

        if index is None:
            messagebox.showerror("Error", "Select an app first.")
            return

        app = self.config["apps"][index]
        name = app.get("name", "this app")

        confirmed = messagebox.askyesno(
            "Confirm delete",
            f"Delete {name} from config?"
        )

        if not confirmed:
            return

        del self.config["apps"][index]

        save_config(self.config)
        self.refresh_app_list()

        self.name_entry.delete(0, tk.END)
        self.rules_text.configure(state="normal")
        self.rules_text.delete("1.0", tk.END)

        messagebox.showinfo("Deleted", "App deleted successfully.")

def get_exe_path_for_startup():
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve())

    # Dev mode fallback.
    # Autostart is mainly meant for packaged .exe mode.
    return str(Path(sys.executable).resolve())


def is_startup_enabled():
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ
        ) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return value == f'"{get_exe_path_for_startup()}"'

    except FileNotFoundError:
        return False


def set_startup_enabled(enabled):
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0,
        winreg.KEY_SET_VALUE
    ) as key:
        if enabled:
            exe_path = get_exe_path_for_startup()
            winreg.SetValueEx(
                key,
                APP_NAME,
                0,
                winreg.REG_SZ,
                f'"{exe_path}"'
            )
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    root = tk.Tk()
    app = SettingsApp(root)

    def on_close():
        root.quit()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    root.mainloop()