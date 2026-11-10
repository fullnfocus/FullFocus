from datetime import datetime

import pytest

from focus_core import (
    Cooldown,
    build_app_lookup,
    clean_process_names,
    describe_block,
    is_protected_process,
    next_allowed_start,
    is_app_blocked_by_config,
    is_rule_active,
    parse_rules_text,
    read_config_file,
    rules_to_text,
    should_kill_app,
    validate_time,
)

# nov 2026: mon 9, tue 10, wed 11 ... sun 15
MON, TUE, WED, SUN = 9, 10, 11, 15


def at(day, hhmm):
    hour, minute = map(int, hhmm.split(":"))
    return datetime(2026, 11, day, hour, minute)


def rule(days, start, end):
    return {"days": days, "start": start, "end": end}


# is_rule_active

class TestSameDayRule:
    r = rule(["tue"], "09:00", "18:00")

    def test_inside(self):
        assert is_rule_active(self.r, at(TUE, "12:00"))

    def test_start_is_inclusive(self):
        assert is_rule_active(self.r, at(TUE, "09:00"))

    def test_end_is_exclusive(self):
        assert not is_rule_active(self.r, at(TUE, "18:00"))

    def test_wrong_day(self):
        assert not is_rule_active(self.r, at(WED, "12:00"))


class TestOvernightRule:
    r = rule(["tue"], "22:00", "02:00")

    def test_late_on_allowed_day(self):
        assert is_rule_active(self.r, at(TUE, "23:30"))

    def test_spills_into_next_morning(self):
        assert is_rule_active(self.r, at(WED, "01:59"))

    def test_ends_at_end_time(self):
        assert not is_rule_active(self.r, at(WED, "02:00"))

    def test_does_not_spill_into_the_morning_of_the_allowed_day(self):
        # tue 01:00 is still monday night
        assert not is_rule_active(self.r, at(TUE, "01:00"))

    def test_sunday_wraps_to_monday(self):
        sunday_night = rule(["sun"], "23:00", "01:00")
        assert is_rule_active(sunday_night, at(MON, "00:30"))


class TestSpecialRules:
    def test_same_start_and_end_means_whole_day(self):
        r = rule(["tue"], "00:00", "00:00")
        assert is_rule_active(r, at(TUE, "00:00"))
        assert is_rule_active(r, at(TUE, "23:59"))
        assert not is_rule_active(r, at(WED, "00:00"))

    def test_until_midnight(self):
        r = rule(["tue"], "19:00", "00:00")
        assert is_rule_active(r, at(TUE, "23:59"))
        assert not is_rule_active(r, at(WED, "00:00"))

    def test_no_days_means_every_day(self):
        r = {"start": "10:00", "end": "11:00"}
        assert is_rule_active(r, at(SUN, "10:30"))

    def test_day_names_are_case_insensitive(self):
        assert is_rule_active(rule(["TUE"], "09:00", "18:00"), at(TUE, "12:00"))


# blocking decisions

class TestBlocking:
    def test_constant_mode_always_blocks(self):
        app = {"name": "steam.exe", "mode": "constant"}
        assert is_app_blocked_by_config(app, at(TUE, "12:00"))

    def test_missing_mode_defaults_to_constant(self):
        assert is_app_blocked_by_config({"name": "steam.exe"}, at(TUE, "12:00"))

    def test_disabled_app_is_never_blocked(self):
        app = {"name": "steam.exe", "mode": "constant", "enabled": False}
        assert not is_app_blocked_by_config(app, at(TUE, "12:00"))

    def test_scheduled_app_allowed_inside_window(self):
        app = {"mode": "scheduled", "rules": [rule(["tue"], "19:00", "23:00")]}
        assert not is_app_blocked_by_config(app, at(TUE, "20:00"))

    def test_scheduled_app_blocked_outside_window(self):
        app = {"mode": "scheduled", "rules": [rule(["tue"], "19:00", "23:00")]}
        assert is_app_blocked_by_config(app, at(TUE, "18:59"))

    def test_scheduled_app_without_rules_is_always_blocked(self):
        assert is_app_blocked_by_config({"mode": "scheduled"}, at(TUE, "12:00"))

    def test_any_matching_rule_allows(self):
        app = {"mode": "scheduled", "rules": [
            rule(["mon"], "09:00", "10:00"),
            rule(["tue"], "09:00", "10:00"),
        ]}
        assert not is_app_blocked_by_config(app, at(TUE, "09:30"))


class TestShouldKillApp:
    config = {"apps": [
        {"name": "Steam.exe", "mode": "constant"},
        {"name": "game.exe", "mode": "constant", "enabled": False},
    ]}

    def test_process_names_match_case_insensitively(self):
        lookup = build_app_lookup(self.config)
        assert should_kill_app("STEAM.EXE", lookup, at(TUE, "12:00"))

    def test_unlisted_process_is_left_alone(self):
        lookup = build_app_lookup(self.config)
        assert not should_kill_app("explorer.exe", lookup, at(TUE, "12:00"))

    def test_disabled_entry_is_left_alone(self):
        lookup = build_app_lookup(self.config)
        assert not should_kill_app("game.exe", lookup, at(TUE, "12:00"))

    @pytest.mark.parametrize("name", [None, "", "   "])
    def test_empty_names_are_ignored(self, name):
        lookup = build_app_lookup(self.config)
        assert not should_kill_app(name, lookup, at(TUE, "12:00"))


# rule parsing

class TestParseRules:
    def test_parses_multiple_lines_and_days(self):
        rules = parse_rules_text("tue 19:00 00:00\n\nmon,WED 18:00 22:00\n")
        assert rules == [
            rule(["tue"], "19:00", "00:00"),
            rule(["mon", "wed"], "18:00", "22:00"),
        ]

    def test_round_trip(self):
        text = "tue 19:00 00:00\nmon,wed 18:00 22:00"
        assert rules_to_text(parse_rules_text(text)) == text

    @pytest.mark.parametrize("bad", [
        "tue 19:00",              # missing end time
        "funday 19:00 20:00",     # unknown day
        "tue 25:00 20:00",        # invalid hour
        "tue 19:60 20:00",        # invalid minute
        "tue seven 20:00",        # not a time
    ])
    def test_rejects_invalid_lines(self, bad):
        with pytest.raises(ValueError):
            parse_rules_text(bad)

    @pytest.mark.parametrize("value, ok", [
        ("00:00", True), ("23:59", True), ("9:05", True),
        ("24:00", False), ("12:60", False), ("-1:00", False), ("noon", False),
    ])
    def test_validate_time(self, value, ok):
        assert validate_time(value) is ok


# config file

def test_missing_config_is_created_with_defaults(tmp_path):
    path = tmp_path / "focus_config.json"

    config = read_config_file(path)

    assert path.exists()
    assert config == {"global": {"check_interval_seconds": 3, "notifications": True}, "apps": []}


# notifications

class TestDescribeBlock:
    app = {"mode": "scheduled", "rules": [
        rule(["tue"], "19:00", "23:00"),
        rule(["wed"], "00:00", "07:00"),
    ]}

    def test_later_today(self):
        assert describe_block("x.exe", self.app, at(TUE, "18:00")) == "x.exe is blocked until 19:00"

    def test_tomorrow(self):
        assert describe_block("x.exe", self.app, at(TUE, "23:30")) == "x.exe is blocked until tomorrow 00:00"

    def test_later_this_week(self):
        assert describe_block("x.exe", self.app, at(WED, "08:00")) == "x.exe is blocked until tue 19:00"

    def test_constant_mode_has_no_end(self):
        assert describe_block("x.exe", {"mode": "constant"}, at(TUE, "12:00")) == "x.exe is blocked"

    def test_scheduled_without_rules_has_no_end(self):
        assert next_allowed_start({"mode": "scheduled"}, at(TUE, "12:00")) is None

    def test_picks_the_earliest_rule(self):
        app = {"mode": "scheduled", "rules": [
            rule(["fri"], "18:00", "20:00"),
            rule(["wed"], "18:00", "20:00"),
        ]}
        assert next_allowed_start(app, at(TUE, "12:00")) == at(WED, "18:00")

    def test_same_weekday_next_week(self):
        app = {"mode": "scheduled", "rules": [rule(["tue"], "09:00", "10:00")]}
        assert next_allowed_start(app, at(TUE, "12:00")) == datetime(2026, 11, 17, 9, 0)

    def test_whole_day_rule_starts_at_midnight(self):
        app = {"mode": "scheduled", "rules": [rule(["sun"], "00:00", "00:00")]}
        assert next_allowed_start(app, at(TUE, "12:00")) == at(SUN, "00:00")

    def test_result_actually_unblocks_the_app(self):
        # whatever time we promise, the app really has to be allowed then
        unblock = next_allowed_start(self.app, at(WED, "08:00"))
        assert not is_app_blocked_by_config(self.app, unblock)


class TestCooldown:
    def test_first_time_is_ready(self):
        assert Cooldown(60).ready("steam.exe", at(TUE, "12:00"))

    def test_blocks_repeats_inside_the_window(self):
        cooldown = Cooldown(60)
        cooldown.ready("steam.exe", datetime(2026, 11, 10, 12, 0, 0))
        assert not cooldown.ready("steam.exe", datetime(2026, 11, 10, 12, 0, 59))

    def test_ready_again_after_the_window(self):
        cooldown = Cooldown(60)
        cooldown.ready("steam.exe", datetime(2026, 11, 10, 12, 0, 0))
        assert cooldown.ready("steam.exe", datetime(2026, 11, 10, 12, 1, 0))

    def test_apps_are_tracked_separately(self):
        cooldown = Cooldown(60)
        cooldown.ready("steam.exe", at(TUE, "12:00"))
        assert cooldown.ready("discord.exe", at(TUE, "12:00"))


# process picker and safety

def test_clean_process_names():
    names = ["svchost.exe", "Discord.exe", "discord.exe", "steam.exe", "", None, "Explorer.EXE", "chrome.exe"]
    assert clean_process_names(names) == ["chrome.exe", "Discord.exe", "steam.exe"]


@pytest.mark.parametrize("name, protected", [
    ("explorer.exe", True),
    ("SVCHOST.EXE", True),
    ("FullFocus.exe", True),
    ("steam.exe", False),
])
def test_is_protected_process(name, protected):
    assert is_protected_process(name) is protected
