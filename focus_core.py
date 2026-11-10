# core logic, no windows stuff here so it can be tested anywhere

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

DAYS = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}

DAY_NAMES = {number: name for name, number in DAYS.items()}

DEFAULT_CONFIG = {
    "global": {
        "check_interval_seconds": 3,
        "notifications": True
    },
    "apps": []
}

# windows needs these to run, killing them can crash or freeze the pc
PROTECTED_PROCESSES = {
    "system",
    "system idle process",
    "registry",
    "memory compression",
    "smss.exe",
    "csrss.exe",
    "wininit.exe",
    "winlogon.exe",
    "services.exe",
    "lsass.exe",
    "svchost.exe",
    "dwm.exe",
    "explorer.exe",
    "fontdrvhost.exe",
    "conhost.exe",
    "sihost.exe",
    "taskhostw.exe",
    "ctfmon.exe",
    "runtimebroker.exe",
    "searchhost.exe",
    "startmenuexperiencehost.exe",
    "shellexperiencehost.exe",
    "textinputhost.exe",
    "securityhealthservice.exe",
    "msmpeng.exe",
    "fullfocus.exe",
}


def get_app_dir():
    # folder next to the .exe, or next to the script in dev mode
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    return Path(__file__).resolve().parent


def get_resource_path(filename):
    # pyinstaller unpacks bundled files into _MEIPASS
    bundle_dir = getattr(sys, "_MEIPASS", None)

    if bundle_dir is not None:
        bundled = Path(bundle_dir) / filename

        if bundled.exists():
            return bundled

    return get_app_dir() / filename


def default_config():
    # fresh copy so nobody edits the default by accident
    return json.loads(json.dumps(DEFAULT_CONFIG))


def read_config_file(path):
    # creates the config on first run
    path = Path(path)

    if not path.exists():
        config = default_config()
        write_config_file(path, config)
        return config

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_config_file(path, config):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)


def normalize(name):
    return name.lower().strip() if name else ""


def validate_time(value):
    # "HH:MM", 00:00 to 23:59
    try:
        hour, minute = value.split(":")
        hour = int(hour)
        minute = int(minute)

        return 0 <= hour <= 23 and 0 <= minute <= 59

    except Exception:
        return False


def parse_time_to_minutes(value):
    # "19:30" -> 1170
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def parse_rules_text(text):
    # one rule per line, e.g. "tue 19:00 00:00" or "mon,tue 18:00 22:00"
    rules = []

    for line in text.strip().splitlines():
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
            if day not in DAYS:
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
    # back to the text format for the settings window
    lines = []

    for rule in rules:
        days = ",".join(rule.get("days", []))
        start = rule.get("start", "00:00")
        end = rule.get("end", "00:00")

        lines.append(f"{days} {start} {end}")

    return "\n".join(lines)


def get_rule_days(rule):
    # no days listed = every day
    days = rule.get("days", [])

    if not days:
        return set(range(7))

    return {DAYS[day.lower()] for day in days if day.lower() in DAYS}


def is_rule_active(rule, now):
    # is now inside this allowed window?
    allowed_days = get_rule_days(rule)

    start = parse_time_to_minutes(rule["start"])
    end = parse_time_to_minutes(rule["end"])

    current = now.hour * 60 + now.minute
    today = now.weekday()
    yesterday = (today - 1) % 7

    # same start and end = whole day
    if start == end:
        return today in allowed_days

    # normal, like 09:00 -> 18:00
    if start < end:
        return today in allowed_days and start <= current < end

    # overnight, like 22:00 -> 02:00
    # either late on an allowed day, or early the morning after one
    return (
        today in allowed_days and current >= start
    ) or (
        yesterday in allowed_days and current < end
    )


def is_inside_allowed_window(app_config, now):
    return any(is_rule_active(rule, now) for rule in app_config.get("rules", []))


def is_app_blocked_by_config(app_config, now):
    if not app_config.get("enabled", True):
        return False

    mode = app_config.get("mode", "constant").lower()

    if mode == "constant":
        return True

    if mode == "scheduled":
        # blocked by default, rules are the exceptions
        return not is_inside_allowed_window(app_config, now)

    return False


def build_app_lookup(config):
    # process name -> app config
    apps = {}

    for app in config.get("apps", []):
        name = normalize(app.get("name"))

        if name:
            apps[name] = app

    return apps


def should_kill_app(process_name, app_lookup, now=None):
    # build app_lookup once per scan, not per process
    process_name = normalize(process_name)

    if not process_name:
        return False

    app_config = app_lookup.get(process_name)

    if app_config is None:
        return False

    if now is None:
        now = datetime.now()

    return is_app_blocked_by_config(app_config, now)


def is_protected_process(name):
    return normalize(name) in PROTECTED_PROCESSES


def clean_process_names(names):
    # for the "pick from running apps" list: no duplicates, no system stuff, sorted
    seen = {}

    for name in names:
        key = normalize(name)

        if key and key not in seen and key not in PROTECTED_PROCESSES:
            seen[key] = name

    return sorted(seen.values(), key=str.lower)


def next_allowed_start(app_config, now):
    # when does the app get unblocked next? None if never (constant mode, no rules)
    if app_config.get("mode", "constant").lower() != "scheduled":
        return None

    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    best = None

    for rule in app_config.get("rules", []):
        allowed_days = get_rule_days(rule)
        start = parse_time_to_minutes(rule["start"])

        # 8 days so the same weekday next week is covered too
        for offset in range(8):
            day = today + timedelta(days=offset)

            if day.weekday() not in allowed_days:
                continue

            candidate = day + timedelta(minutes=start)

            if candidate > now and (best is None or candidate < best):
                best = candidate

    return best


def describe_block(app_name, app_config, now):
    # text for the "app was blocked" notification
    unblock_at = next_allowed_start(app_config, now)

    if unblock_at is None:
        return f"{app_name} is blocked"

    time_text = unblock_at.strftime("%H:%M")
    days_away = (unblock_at.date() - now.date()).days

    if days_away == 0:
        return f"{app_name} is blocked until {time_text}"

    if days_away == 1:
        return f"{app_name} is blocked until tomorrow {time_text}"

    return f"{app_name} is blocked until {DAY_NAMES[unblock_at.weekday()]} {time_text}"


class Cooldown:
    # stops the same app from spamming notifications if it keeps relaunching

    def __init__(self, seconds):
        self.seconds = seconds
        self.last_seen = {}

    def ready(self, key, now):
        last = self.last_seen.get(key)

        if last is not None and (now - last).total_seconds() < self.seconds:
            return False

        self.last_seen[key] = now
        return True
