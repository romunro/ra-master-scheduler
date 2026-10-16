import datetime
from pathlib import Path
import tempfile
import unittest
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

from src.constants import CONSTRAINT_TYPES
from src.config import is_configured, load_config, save_config
from src.constraints import (
    load_day_constraints,
    save_day_constraints,
    _empty_day_constraints,
    parse_short_date_input,
    _parse_removal_indices,
)
from src.planner import (
    _last_day_of_month,
    generate_date_list,
    get_japanese_holidays_in_range,
    plan_workdays_multiple_months,
)
from src.past_workdays import find_past_planned_workdays, lock_past_workdays
from src.calendar_renderer import (
    strip_ansi,
    get_day_status,
    render_month_block,
    render_horizontal_calendar,
)
from src.interactive_editor import _jump_month
from src.ical_export import export_schedule_to_ical


class TestConfig(unittest.TestCase):
    def test_is_configured_true(self):
        cfg = {
            "defaults": {
                "start_year": 2026,
                "start_month": 10,
                "duration": 5,
                "workdays": 10,
            }
        }
        self.assertTrue(is_configured(cfg))

    def test_is_configured_false_empty(self):
        self.assertFalse(is_configured({}))
        self.assertFalse(is_configured({"defaults": {}}))
        self.assertFalse(is_configured({"defaults": {"start_year": 2026}}))

    def test_save_and_load_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "config.yaml"
            cfg_data = {
                "defaults": {
                    "start_year": 2027,
                    "start_month": 4,
                    "duration": 3,
                    "workdays": 12,
                    "want_overtime": True,
                }
            }
            save_config(cfg_data, path=cfg_path)
            loaded = load_config(path=cfg_path)
            self.assertEqual(loaded["defaults"]["start_year"], 2027)
            self.assertEqual(loaded["defaults"]["workdays"], 12)
            self.assertTrue(loaded["defaults"]["want_overtime"])


class TestConstraints(unittest.TestCase):
    def test_load_save_day_constraints(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            c_path = Path(tmpdir) / "constraints.yaml"
            constraints = {
                "paid_disabled_days": {datetime.date(2026, 11, 2)},
                "unpaid_disabled_days": {datetime.date(2026, 11, 3)},
                "forced_days": {datetime.date(2026, 11, 4)},
            }
            additions = {
                "paid_disabled_days": {datetime.date(2026, 11, 2)},
                "unpaid_disabled_days": {datetime.date(2026, 11, 3)},
                "forced_days": {datetime.date(2026, 11, 4)},
            }
            save_day_constraints(constraints, additions=additions, path=c_path)

            loaded, history = load_day_constraints(path=c_path)
            self.assertIn(datetime.date(2026, 11, 2), loaded["paid_disabled_days"])
            self.assertIn(datetime.date(2026, 11, 3), loaded["unpaid_disabled_days"])
            self.assertIn(datetime.date(2026, 11, 4), loaded["forced_days"])
            self.assertEqual(len(history), 1)

    def test_parse_short_date_input(self):
        parsed = parse_short_date_input("2026-10-1,2,11-5")
        self.assertIn(datetime.date(2026, 10, 1), parsed)
        self.assertIn(datetime.date(2026, 10, 2), parsed)
        self.assertIn(datetime.date(2026, 11, 5), parsed)

    def test_parse_removal_indices(self):
        entries = [
            (datetime.date(2026, 10, 1), "forced_days", "forced"),
            (datetime.date(2026, 10, 2), "forced_days", "forced"),
        ]
        indices = _parse_removal_indices("1, 2", 2, entries)
        self.assertEqual(indices, {1, 2})
        indices_all = _parse_removal_indices("all", 2, entries)
        self.assertEqual(indices_all, {1, 2})


class TestPlanner(unittest.TestCase):
    def test_last_day_of_month(self):
        self.assertEqual(_last_day_of_month(2026, 10), datetime.date(2026, 10, 31))
        self.assertEqual(_last_day_of_month(2026, 2), datetime.date(2026, 2, 28))
        self.assertEqual(_last_day_of_month(2024, 2), datetime.date(2024, 2, 29))  # leap year
        self.assertEqual(_last_day_of_month(2026, 12), datetime.date(2026, 12, 31))

    def test_generate_date_list(self):
        dates = generate_date_list(2026, 10, 2026, 10)
        self.assertEqual(len(dates), 31)
        self.assertEqual(dates[0], datetime.date(2026, 10, 1))
        self.assertEqual(dates[-1], datetime.date(2026, 10, 31))

    def test_plan_workdays_solver(self):
        sched = plan_workdays_multiple_months(
            2026, 10, 2026, 10,
            workdays=10,
        )
        worked_days = [d for d, hrs in sched.items() if hrs > 0]
        self.assertEqual(len(worked_days), 10)
        for d in worked_days:
            self.assertGreaterEqual(sched[d], 7.75)

    def test_paid_leave_counts_days_and_hours(self):
        paid_day = datetime.date(2026, 10, 15)
        sched = plan_workdays_multiple_months(
            2026, 10, 2026, 10,
            paid_disabled_days={paid_day},
            workdays=10,
        )
        # Paid leave day must have exactly 7.75 hours
        self.assertEqual(sched.get(paid_day), 7.75)
        # Total days with hours > 0 must be 10 (9 workdays + 1 paid leave day)
        worked_days = [d for d, hrs in sched.items() if hrs > 0]
        self.assertEqual(len(worked_days), 10)
        self.assertIn(paid_day, worked_days)
        # Total monthly hours must be 10 * 7.75 = 77.5
        self.assertAlmostEqual(sum(sched.values()), 77.5)


class TestPastWorkdays(unittest.TestCase):
    def test_find_and_lock_past_workdays(self):
        today = datetime.date(2026, 10, 15)
        # Schedule has workdays on 2026-10-01, 2026-10-02, 2026-10-16
        sched = {
            datetime.date(2026, 10, 1): 6.5,
            datetime.date(2026, 10, 2): 6.5,
            datetime.date(2026, 10, 16): 6.5,
        }
        # 2026-10-01 is already forced
        forced = {datetime.date(2026, 10, 1)}

        to_lock = find_past_planned_workdays(sched, forced, today=today)
        # Only 2026-10-02 should be found (10-01 already forced, 10-16 in future)
        self.assertEqual(to_lock, [datetime.date(2026, 10, 2)])

        with tempfile.TemporaryDirectory() as tmpdir:
            c_path = Path(tmpdir) / "constraints.yaml"
            save_day_constraints(
                {"paid_disabled_days": set(), "unpaid_disabled_days": set(), "forced_days": forced},
                path=c_path
            )
            new_forced, changed = lock_past_workdays(
                sched,
                forced,
                paid_disabled_days=set(),
                unpaid_disabled_days=set(),
                today=today,
                constraints_path=c_path,
                confirm=False,
            )
            self.assertTrue(changed)
            self.assertIn(datetime.date(2026, 10, 2), new_forced)
            self.assertIn(datetime.date(2026, 10, 1), new_forced)


class TestCalendarRenderer(unittest.TestCase):
    def test_strip_ansi(self):
        colored = "\033[92m 1\033[0m"
        self.assertEqual(strip_ansi(colored), " 1")

    def test_render_month_block_dimensions(self):
        block = render_month_block(
            2026, 10,
            schedule={},
            forced_days=set(),
            paid_disabled_days=set(),
            unpaid_disabled_days=set(),
            disabled_days=set(),
            holiday_set=set(),
        )
        # Must be exactly 9 lines
        self.assertEqual(len(block), 9)
        # Every line must have visual width of 20 chars
        for idx, line in enumerate(block):
            visual_w = len(strip_ansi(line))
            self.assertEqual(visual_w, 20, f"Line {idx} visual width is {visual_w}, expected 20: {strip_ansi(line)!r}")

    def test_horizontal_calendar_responsive_wrapping(self):
        # 3 months: Oct, Nov, Dec 2026
        # Narrow width (50): can only fit 2 months per row (23*2 - 3 = 43 <= 50)
        lines_narrow = render_horizontal_calendar(
            {}, 2026, 10, 2026, 12, terminal_width=50
        )
        # 2 rows of months + 2 blank lines = 9*2 + 2 = 20 lines
        self.assertEqual(len(lines_narrow), 20)

        # Wide width (100): can fit all 3 months in 1 row (23*3 - 3 = 66 <= 100)
        lines_wide = render_horizontal_calendar(
            {}, 2026, 10, 2026, 12, terminal_width=100
        )
        # 1 row of months + 1 blank line = 10 lines
        self.assertEqual(len(lines_wide), 10)


class TestInteractiveEditorUtils(unittest.TestCase):
    def test_jump_month(self):
        min_d = datetime.date(2026, 10, 1)
        max_d = datetime.date(2027, 2, 28)

        # Jump forward 1 month from Oct 15 -> Nov 15
        d = datetime.date(2026, 10, 15)
        d_next = _jump_month(d, 1, min_d, max_d)
        self.assertEqual(d_next, datetime.date(2026, 11, 15))

        # Jump backward 1 month from Nov 15 -> Oct 15
        d_prev = _jump_month(d_next, -1, min_d, max_d)
        self.assertEqual(d_prev, datetime.date(2026, 10, 15))

        # Clamping at min_d
        d_clamped = _jump_month(d, -5, min_d, max_d)
        self.assertEqual(d_clamped, min_d)

    def test_interactive_editor_non_tty(self):
        from unittest.mock import patch
        from src.interactive_editor import interactive_calendar_editor
        with patch("sys.stdin.isatty", return_value=False):
            res = interactive_calendar_editor(
                {}, 2026, 11, 2027, 3,
                forced_days={datetime.date(2026, 11, 2)},
                paid_disabled_days=set(),
                unpaid_disabled_days=set()
            )
            self.assertEqual(res[4], False)
            self.assertEqual(res[1], {datetime.date(2026, 11, 2)})


class TestIcalExport(unittest.TestCase):
    def test_export_schedule(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "test_schedule.ics"
            sched = {
                datetime.date(2026, 10, 1): 7.75,
                datetime.date(2026, 10, 2): 0.0,
            }
            exported = export_schedule_to_ical(sched, out_path)
            self.assertTrue(exported.exists())
            content = exported.read_text(encoding="utf-8")
            self.assertIn("BEGIN:VCALENDAR", content)
            self.assertIn("20261001T090000", content)
            self.assertIn("20261001T174500", content)
            self.assertIn("BEGIN:VALARM", content)
            self.assertIn("TRIGGER:-PT10H", content)


class TestGoogleCalendarComparison(unittest.TestCase):
    def test_display_affected_month_comparison_output(self):
        import io
        from unittest.mock import patch
        from src.gcalendar import _display_affected_month_comparison

        before_sched = {datetime.date(2026, 11, 2): 7.75}
        after_sched = {}
        before_c = {"paid_disabled_days": set(), "unpaid_disabled_days": set(), "forced_days": set()}
        after_c = {"paid_disabled_days": set(), "unpaid_disabled_days": {datetime.date(2026, 11, 2)}, "forced_days": set()}

        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _display_affected_month_comparison(
                2026, 11,
                before_schedule=before_sched,
                after_schedule=after_sched,
                before_constraints=before_c,
                after_constraints=after_c,
                holiday_set=set(),
                target_workdays=1,
                before_feasible=True,
                after_feasible=False,
                changes_in_month=[datetime.date(2026, 11, 2)],
                terminal_width=80,
            )
        output = buf.getvalue()
        self.assertIn("Affected Month: November 2026", output)
        self.assertIn("BEFORE (Current)", output)
        self.assertIn("AFTER (Google Cal)", output)
        self.assertIn("Feasible", output)
        self.assertIn("INFEASIBLE", output)

    def test_check_google_calendar_background_with_changes(self):
        import io
        from unittest.mock import patch
        from src.gcalendar import check_google_calendar_background

        config = {
            "calendar": {
                "write_calendar_id": "test_cal_id@group.calendar.google.com",
                "service_account_key_path": "tests/fake_key.json",
            }
        }
        with tempfile.NamedTemporaryFile(suffix=".json") as f:
            config["calendar"]["service_account_key_path"] = f.name
            with patch("src.gcalendar.fetch_google_calendar_constraints") as mock_fetch:
                # 2026-11-02 changed to unpaid disabled day
                mock_fetch.return_value = (set(), {datetime.date(2026, 11, 2)}, set())
                stored_c = {"paid_disabled_days": set(), "unpaid_disabled_days": set(), "forced_days": set()}

                # 1. Simulate user declining to apply ('n')
                buf = io.StringIO()
                with patch("sys.stdout", buf), patch("builtins.input", return_value="n"):
                    has_changes, new_c, cal_status, new_sched = check_google_calendar_background(
                        config,
                        datetime.date(2026, 11, 1),
                        datetime.date(2026, 11, 30),
                        stored_c,
                        sy=2026, sm=11, ey=2026, em=11,
                        want_overtime=False,
                        workdays=10,
                    )
                self.assertFalse(has_changes)
                self.assertIsNone(new_c)
                self.assertEqual(cal_status, "Changes ignored")
                output = buf.getvalue()
                self.assertIn("Google Calendar: 1 new constraint(s) detected:", output)
                self.assertIn("Affected Month: November 2026", output)
                self.assertIn("BEFORE (Current)", output)
                self.assertIn("AFTER (Google Cal)", output)

                # 2. Simulate user accepting to apply ('y')
                with tempfile.TemporaryDirectory() as c_tmp:
                    c_file = Path(c_tmp) / "constraints.yaml"
                    save_day_constraints(stored_c, path=c_file)
                    with patch("src.gcalendar.save_day_constraints") as mock_save, patch("builtins.input", return_value="y"):
                        has_changes_y, new_c_y, cal_status_y, new_sched_y = check_google_calendar_background(
                            config,
                            datetime.date(2026, 11, 1),
                            datetime.date(2026, 11, 30),
                            stored_c,
                            sy=2026, sm=11, ey=2026, em=11,
                            want_overtime=False,
                            workdays=10,
                        )
                        self.assertTrue(has_changes_y)
                        self.assertIsNotNone(new_c_y)
                        self.assertIn(datetime.date(2026, 11, 2), new_c_y[1])
                        self.assertEqual(cal_status_y, "Synced (applied)")


if __name__ == "__main__":
    unittest.main()
