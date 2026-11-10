import psutil
import sys
import tkinter as tk
import winreg
from pathlib import Path
from tkinter import ttk, messagebox

from focus_core import (
    clean_process_names,
    get_app_dir,
    is_protected_process,
    parse_rules_text,
    read_config_file,
    rules_to_text,
    write_config_file,
)

APP_DIR = get_app_dir()
CONFIG_PATH = APP_DIR / "focus_config.json"

APP_NAME = "FullFocus"


def load_config():
    return read_config_file(CONFIG_PATH)


def save_config(config):
    write_config_file(CONFIG_PATH, config)


class SettingsApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Full Focus Settings")
        self.root.geometry("820x600")
        self.root.minsize(760, 560)

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

        self.app_listbox = tk.Listbox(left, height=20, width=34)
        self.app_listbox.pack(fill="both", expand=True)
        self.app_listbox.bind("<<ListboxSelect>>", self.on_app_select)

        ttk.Button(left, text="Delete selected app", command=self.delete_selected_app).pack(fill="x", pady=(10, 0))

        # settings for the whole app, not one blocked app
        general = ttk.LabelFrame(left, text="General", padding=8)
        general.pack(fill="x", pady=(10, 0))

        self.startup_var = tk.BooleanVar(value=is_startup_enabled())

        ttk.Checkbutton(
            general,
            text="Launch Full Focus on Windows startup",
            variable=self.startup_var,
            command=self.toggle_startup
        ).pack(anchor="w")

        self.notify_var = tk.BooleanVar(
            value=self.config.get("global", {}).get("notifications", True)
        )

        ttk.Checkbutton(
            general,
            text="Show a notification when an app is blocked",
            variable=self.notify_var,
            command=self.toggle_notifications
        ).pack(anchor="w", pady=(4, 0))

        ttk.Label(right, text="App name / process name").pack(anchor="w")

        name_row = ttk.Frame(right)
        name_row.pack(fill="x", pady=(0, 10))

        self.name_entry = ttk.Entry(name_row)
        self.name_entry.pack(side="left", fill="x", expand=True)

        ttk.Button(
            name_row,
            text="Pick from running apps...",
            command=self.pick_running_app
        ).pack(side="left", padx=(6, 0))

        self.enabled_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(right, text="Enabled", variable=self.enabled_var).pack(anchor="w", pady=(0, 10))

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

        self.rules_text = tk.Text(right, height=7)
        self.rules_text.pack(fill="both", expand=True, pady=(0, 10))

        ttk.Button(right, text="Add / Update app", command=self.save_app).pack(fill="x")

        help_text = (
            "constant = blocked whenever blocker is ON\n"
            "scheduled = blocked by default, allowed only during these windows\n"
            "days: mon, tue, wed, thu, fri, sat, sun"
        )

        ttk.Label(right, text=help_text).pack(anchor="w", pady=(10, 0))

        self.on_mode_change()

    def toggle_startup(self):
        try:
            set_startup_enabled(self.startup_var.get())

            if self.startup_var.get():
                messagebox.showinfo("Startup enabled", "Full Focus will launch when Windows starts.")
            else:
                messagebox.showinfo("Startup disabled", "Full Focus will no longer launch when Windows starts.")

        except Exception as e:
            messagebox.showerror("Startup error", str(e))

    def toggle_notifications(self):
        # the tray app rereads the config every scan, so this applies right away
        self.config.setdefault("global", {})["notifications"] = self.notify_var.get()
        save_config(self.config)

    def pick_running_app(self):
        picker = ProcessPicker(self.root)
        self.root.wait_window(picker)

        if picker.result:
            self.name_entry.delete(0, tk.END)
            self.name_entry.insert(0, picker.result)

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

        # disabled text widgets ignore edits
        self.rules_text.configure(state="normal")
        self.rules_text.delete("1.0", tk.END)
        self.rules_text.insert("1.0", rules_to_text(app.get("rules", [])))

        self.on_mode_change()

    def on_mode_change(self, event=None):
        mode = self.mode_var.get()

        # grey it out so it's obvious the rules don't apply in constant mode
        if mode == "constant":
            self.rules_text.configure(state="disabled", background="#f0f0f0", foreground="#888888")
        else:
            self.rules_text.configure(state="normal", background="white", foreground="black")

    def save_app(self):
        name = self.name_entry.get().strip()

        if not name:
            messagebox.showerror("Error", "App name cannot be empty.")
            return

        if is_protected_process(name):
            messagebox.showerror(
                "Can't block this",
                f"{name} is part of Windows or Full Focus itself. "
                "Closing it could freeze or crash your PC."
            )
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

class ProcessPicker(tk.Toplevel):
    # searchable list of what's running right now, so you don't have to type exe names

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Pick a running app")
        self.geometry("360x440")
        self.transient(parent)

        # keeps clicks on the settings window blocked until this one closes
        self.wait_visibility()
        self.grab_set()

        self.result = None
        self.all_names = clean_process_names(
            proc.info["name"] for proc in psutil.process_iter(["name"])
        )

        frame = ttk.Frame(self, padding=10)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Search").pack(anchor="w")

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self.refresh())

        search = ttk.Entry(frame, textvariable=self.search_var)
        search.pack(fill="x", pady=(0, 8))
        search.focus_set()

        self.listbox = tk.Listbox(frame)
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<Double-Button-1>", lambda event: self.choose())
        self.listbox.bind("<Return>", lambda event: self.choose())

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(8, 0))

        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Use this app", command=self.choose).pack(side="right", padx=(0, 6))

        # enter in the search box picks the first match
        search.bind("<Return>", lambda event: self.choose(first_if_none=True))
        self.bind("<Escape>", lambda event: self.destroy())

        self.refresh()

    def refresh(self):
        query = self.search_var.get().lower().strip()

        self.listbox.delete(0, tk.END)

        for name in self.all_names:
            if query in name.lower():
                self.listbox.insert(tk.END, name)

    def choose(self, first_if_none=False):
        selection = self.listbox.curselection()

        if selection:
            self.result = self.listbox.get(selection[0])
        elif first_if_none and self.listbox.size() > 0:
            self.result = self.listbox.get(0)
        else:
            return

        self.destroy()


def get_startup_command():
    # what goes in the windows Run key
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'

    # dev mode, pythonw so there's no console window
    python = Path(sys.executable).resolve()
    pythonw = python.with_name("pythonw.exe")

    if pythonw.exists():
        python = pythonw

    script = APP_DIR / "full_focus.py"
    return f'"{python}" "{script}"'


def is_startup_enabled():
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ
        ) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return value == get_startup_command()

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
            winreg.SetValueEx(
                key,
                APP_NAME,
                0,
                winreg.REG_SZ,
                get_startup_command()
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