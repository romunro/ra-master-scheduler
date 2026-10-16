import datetime
from pathlib import Path
import sys
import warnings

# Ensure root directory is on sys.path
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Filter harmless Google API Python version deprecation warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="google.api_core")

from src.constants import (
    CONFIG_PATH,
    CONSTRAINTS_PATH,
    CONSTRAINT_TYPES,
    COLOR_BOLD,
    COLOR_RESET,
)
from src.config import (
    load_config,
    save_config,
    is_configured,
    prompt_initial_setup,
    prompt_edit_settings,
)
from src.constraints import (
    _empty_day_constraints,
    _parse_yaml_constraint_date,
    _normalise_constraint_mapping,
    _serialise_constraint_mapping,
    load_day_constraints,
    save_day_constraints,
    parse_short_date_input,
    safe_parse_short_date_input,
    _check_year_month,
    _check_valid_date,
    _parse_removal_indices,
    prompt_remove_custom_entries,
)
from src.planner import (
    _last_day_of_month,
    get_japanese_holidays_in_range,
    generate_date_list,
    plan_workdays_multiple_months,
)
from src.calendar_renderer import (
    render_horizontal_calendar,
    display_overview,
    display_detailed_table,
    get_day_status,
)
from src.past_workdays import (
    find_past_planned_workdays,
    lock_past_workdays,
)
from src.gcalendar import (
    _get_google_calendar_service,
    fetch_google_calendar_constraints,
    check_google_calendar_background,
    prompt_google_calendar_setup,
    sync_schedule_to_google_calendar,
)
from src.ical_export import (
    export_schedule_to_ical,
    prompt_for_export,
    _ical_escape,
    _ical_fold,
)
from src.interactive_editor import (
    interactive_calendar_editor,
)


def _dates_within_range(dates, start_date, end_date, label):
    """Return in-range dates and report entries that cannot affect this schedule."""
    dates = set(dates)
    outside = dates - {d for d in dates if start_date <= d <= end_date}
    if outside:
        formatted = ", ".join(str(d) for d in sorted(outside))
        print(f"[!] {label} outside planning range ignored: {formatted}")
    return {d for d in dates if start_date <= d <= end_date}


def display_schedule(
    schedule,
    start_year,
    start_month,
    end_year,
    end_month,
    disabled_days=None,
    forced_days=None,
    paid_disabled_days=None,
    unpaid_disabled_days=None,
    include_table=False,
):
    """Display the overview and optionally the detailed table."""
    display_overview(
        schedule,
        start_year,
        start_month,
        end_year,
        end_month,
        disabled_days=disabled_days,
        forced_days=forced_days,
        paid_disabled_days=paid_disabled_days,
        unpaid_disabled_days=unpaid_disabled_days,
    )
    if include_table:
        display_detailed_table(
            schedule,
            start_year,
            start_month,
            end_year,
            end_month,
            disabled_days=disabled_days,
            forced_days=forced_days,
            paid_disabled_days=paid_disabled_days,
            unpaid_disabled_days=unpaid_disabled_days,
        )


def _prompt_add_custom_days(range_start, range_end, paid_disabled_days, unpaid_disabled_days, forced_days, sy, sm, ey, em, want_overtime, workdays):
    """Prompt for entering dates as text (YYYY-M-D,D,M-D)."""
    print("\nEnter dates as YYYY-M-D,D,M-D (press Enter to skip a category).")
    new_paid = safe_parse_short_date_input("Additional paid disabled days (leave):\n> ")
    new_unpaid = safe_parse_short_date_input("Additional unpaid disabled days (off):\n> ")
    new_forced = safe_parse_short_date_input("Additional forced work days:\n> ")

    new_paid = _dates_within_range(new_paid, range_start, range_end, "Paid disabled days")
    new_unpaid = _dates_within_range(new_unpaid, range_start, range_end, "Unpaid disabled days")
    new_forced = _dates_within_range(new_forced, range_start, range_end, "Forced work days")

    if not (new_paid or new_unpaid or new_forced):
        print("No new dates provided.")
        return paid_disabled_days, unpaid_disabled_days, forced_days, None

    proposed_paid = paid_disabled_days | new_paid
    proposed_unpaid = unpaid_disabled_days | new_unpaid
    proposed_forced = forced_days | new_forced
    proposed_disabled = proposed_paid | proposed_unpaid

    conflicts = proposed_disabled & proposed_forced
    if conflicts:
        formatted = ", ".join(str(d) for d in sorted(conflicts))
        print(f"[!] Dates cannot be both disabled and forced; additions cancelled: {formatted}")
        return paid_disabled_days, unpaid_disabled_days, forced_days, None

    proposed_schedule = plan_workdays_multiple_months(
        sy, sm, ey, em,
        disabled_days=proposed_disabled,
        forced_days=proposed_forced,
        want_overtime=want_overtime,
        workdays=workdays,
        paid_disabled_days=proposed_paid,
        unpaid_disabled_days=proposed_unpaid,
    )
    if not proposed_schedule:
        print("[!] No valid schedule possible with these additions; changes cancelled.")
        return paid_disabled_days, unpaid_disabled_days, forced_days, None

    accepted_additions = {
        "paid_disabled_days": proposed_paid - paid_disabled_days,
        "unpaid_disabled_days": proposed_unpaid - unpaid_disabled_days,
        "forced_days": proposed_forced - forced_days,
    }
    proposed_constraints = {
        "paid_disabled_days": proposed_paid,
        "unpaid_disabled_days": proposed_unpaid,
        "forced_days": proposed_forced,
    }
    try:
        save_day_constraints(proposed_constraints, accepted_additions)
        print(f"[+] Saved constraints to {CONSTRAINTS_PATH}.")
        return proposed_paid, proposed_unpaid, proposed_forced, proposed_schedule
    except (OSError, ValueError) as error:
        print(f"[!] Could not save constraints: {error}")
        return paid_disabled_days, unpaid_disabled_days, forced_days, None


def main():
    """Main application loop with clean overview and intuitive menu options."""
    config = load_config()

    # First-run setup if no settings found
    if not is_configured(config):
        config = prompt_initial_setup(config)

    defaults = config.get("defaults", {})
    sy = defaults.get("start_year", datetime.date.today().year)
    sm = defaults.get("start_month", datetime.date.today().month)
    duration = defaults.get("duration", 5)
    workdays = defaults.get("workdays", 10)
    want_overtime = defaults.get("want_overtime", False)

    # Compute date range
    end_month_index = sy * 12 + (sm - 1) + duration - 1
    ey, em_zero_based = divmod(end_month_index, 12)
    em = em_zero_based + 1
    range_start = datetime.date(sy, sm, 1)
    range_end = _last_day_of_month(ey, em)

    # Load constraints
    try:
        stored_constraints, constraint_history = load_day_constraints()
    except ValueError as error:
        print(f"[!] Invalid constraints file: {error}")
        stored_constraints = _empty_day_constraints()
        constraint_history = []

    paid_disabled_days = set(stored_constraints["paid_disabled_days"])
    unpaid_disabled_days = set(stored_constraints["unpaid_disabled_days"])
    forced_days = set(stored_constraints["forced_days"])

    # Solve initial schedule
    current_schedule = plan_workdays_multiple_months(
        sy, sm, ey, em,
        disabled_days=paid_disabled_days | unpaid_disabled_days,
        forced_days=forced_days,
        want_overtime=want_overtime,
        workdays=workdays,
        paid_disabled_days=paid_disabled_days,
        unpaid_disabled_days=unpaid_disabled_days,
    )
    if not current_schedule:
        print("[!] Warning: Could not find feasible schedule with current constraints.")
        current_schedule = {}

    # Google Calendar background sync check
    cal_status = ""
    cal_id = config.get("calendar", {}).get("write_calendar_id")
    key_path = config.get("calendar", {}).get("service_account_key_path", "service_account.json")
    if cal_id and Path(key_path).exists():
        has_changes, new_c, cal_status, new_sched = check_google_calendar_background(
            config, range_start, range_end, stored_constraints,
            sy=sy, sm=sm, ey=ey, em=em,
            want_overtime=want_overtime,
            workdays=workdays,
            current_schedule=current_schedule,
        )
        if has_changes and new_c:
            paid_disabled_days, unpaid_disabled_days, forced_days = new_c
            if new_sched is not None:
                current_schedule = new_sched

    # Main Interactive Loop
    while True:
        # Display Overview Dashboard
        display_overview(
            current_schedule,
            sy, sm, ey, em,
            disabled_days=paid_disabled_days | unpaid_disabled_days,
            forced_days=forced_days,
            paid_disabled_days=paid_disabled_days,
            unpaid_disabled_days=unpaid_disabled_days,
            target_workdays=workdays,
            want_overtime=want_overtime,
            google_calendar_status=cal_status,
        )

        # Check for past unforced workdays
        today = datetime.date.today()
        past_unlocked = find_past_planned_workdays(
            current_schedule, forced_days, paid_disabled_days=paid_disabled_days, today=today
        )
        lock_past_label = f"Lock past workdays ({len(past_unlocked)} day(s) passed before {today})"

        # Main Menu Options
        print("What would you like to do?")
        print(f"  {COLOR_BOLD}[1]{COLOR_RESET} Interactive Calendar (Navigate days with arrow keys & toggle)")
        print(f"  {COLOR_BOLD}[2]{COLOR_RESET} {lock_past_label}")
        print(f"  {COLOR_BOLD}[3]{COLOR_RESET} Google Calendar (Sync schedule to cloud / Check updates)")
        print(f"  {COLOR_BOLD}[4]{COLOR_RESET} Add custom days via text input (Forced / Paid / Unpaid)")
        print(f"  {COLOR_BOLD}[5]{COLOR_RESET} Manage / Remove custom day constraints")
        print(f"  {COLOR_BOLD}[6]{COLOR_RESET} View detailed day-by-day table")
        print(f"  {COLOR_BOLD}[7]{COLOR_RESET} Export schedule to iCal (.ical file)")
        print(f"  {COLOR_BOLD}[8]{COLOR_RESET} Edit planning settings (Dates, duration, workdays, overtime)")
        print(f"  {COLOR_BOLD}[9]{COLOR_RESET} Re-solve schedule")
        print(f"  {COLOR_BOLD}[0]{COLOR_RESET} Exit")

        choice = input("\nSelect an option [0-9]: ").strip()

        if choice == "1":
            # Interactive curses calendar editor
            new_sched, new_f, new_p, new_u, changed = interactive_calendar_editor(
                current_schedule,
                sy, sm, ey, em,
                forced_days=forced_days,
                paid_disabled_days=paid_disabled_days,
                unpaid_disabled_days=unpaid_disabled_days,
                disabled_days=paid_disabled_days | unpaid_disabled_days,
                want_overtime=want_overtime,
                workdays=workdays,
            )
            if changed:
                forced_days = new_f
                paid_disabled_days = new_p
                unpaid_disabled_days = new_u
                current_schedule = new_sched
                print("\n[+] Updated schedule from interactive editor!")

        elif choice == "2":
            # Lock past workdays
            new_forced, changed = lock_past_workdays(
                current_schedule,
                forced_days,
                paid_disabled_days,
                unpaid_disabled_days,
                today=today,
            )
            if changed:
                forced_days = new_forced
                new_sched = plan_workdays_multiple_months(
                    sy, sm, ey, em,
                    disabled_days=paid_disabled_days | unpaid_disabled_days,
                    forced_days=forced_days,
                    want_overtime=want_overtime,
                    workdays=workdays,
                    paid_disabled_days=paid_disabled_days,
                    unpaid_disabled_days=unpaid_disabled_days,
                )
                if new_sched:
                    current_schedule = new_sched

        elif choice == "3":
            # Google Calendar
            print("\n--- Google Calendar Operations ---")
            print("  [1] Sync / Push schedule to Google Calendar")
            print("  [2] Pull / Check latest constraints from Google Calendar")
            print("  [3] Configure / Change Google Calendar ID")
            print("  [0] Back to main menu")
            gchoice = input("Select an option [0-3]: ").strip()
            if gchoice == "1":
                sync_schedule_to_google_calendar(
                    current_schedule,
                    config,
                    paid_disabled_days,
                    unpaid_disabled_days,
                    forced_days,
                )
            elif gchoice == "2":
                has_changes, new_c, cal_status, new_sched = check_google_calendar_background(
                    config, range_start, range_end, {
                        "paid_disabled_days": paid_disabled_days,
                        "unpaid_disabled_days": unpaid_disabled_days,
                        "forced_days": forced_days,
                    },
                    sy=sy, sm=sm, ey=ey, em=em,
                    want_overtime=want_overtime,
                    workdays=workdays,
                    current_schedule=current_schedule,
                )
                if has_changes and new_c:
                    paid_disabled_days, unpaid_disabled_days, forced_days = new_c
                    if new_sched is not None:
                        current_schedule = new_sched
            elif gchoice == "3":
                new_id = prompt_google_calendar_setup(config)
                if new_id:
                    config.setdefault("calendar", {})["write_calendar_id"] = new_id
                    save_config(config)

        elif choice == "4":
            # Add custom days via text input
            new_p, new_u, new_f, new_s = _prompt_add_custom_days(
                range_start, range_end,
                paid_disabled_days, unpaid_disabled_days, forced_days,
                sy, sm, ey, em, want_overtime, workdays
            )
            if new_s:
                paid_disabled_days = new_p
                unpaid_disabled_days = new_u
                forced_days = new_f
                current_schedule = new_s

        elif choice == "5":
            # Remove custom constraints
            new_p, new_u, new_f, changed = prompt_remove_custom_entries(
                paid_disabled_days, unpaid_disabled_days, forced_days
            )
            if changed:
                paid_disabled_days = new_p
                unpaid_disabled_days = new_u
                forced_days = new_f
                new_sched = plan_workdays_multiple_months(
                    sy, sm, ey, em,
                    disabled_days=paid_disabled_days | unpaid_disabled_days,
                    forced_days=forced_days,
                    want_overtime=want_overtime,
                    workdays=workdays,
                    paid_disabled_days=paid_disabled_days,
                    unpaid_disabled_days=unpaid_disabled_days,
                )
                if new_sched:
                    current_schedule = new_sched

        elif choice == "6":
            # View detailed day-by-day table
            display_detailed_table(
                current_schedule,
                sy, sm, ey, em,
                disabled_days=paid_disabled_days | unpaid_disabled_days,
                forced_days=forced_days,
                paid_disabled_days=paid_disabled_days,
                unpaid_disabled_days=unpaid_disabled_days,
            )
            input("Press Enter to return to main menu...")

        elif choice == "7":
            # Export to iCal
            prompt_for_export(
                current_schedule,
                paid_disabled_days,
                unpaid_disabled_days,
                forced_days,
            )

        elif choice == "8":
            # Edit planning settings
            config = prompt_edit_settings(config)
            defaults = config.get("defaults", {})
            sy = defaults.get("start_year", sy)
            sm = defaults.get("start_month", sm)
            duration = defaults.get("duration", duration)
            workdays = defaults.get("workdays", workdays)
            want_overtime = defaults.get("want_overtime", want_overtime)

            end_month_index = sy * 12 + (sm - 1) + duration - 1
            ey, em_zero_based = divmod(end_month_index, 12)
            em = em_zero_based + 1
            range_start = datetime.date(sy, sm, 1)
            range_end = _last_day_of_month(ey, em)

            new_sched = plan_workdays_multiple_months(
                sy, sm, ey, em,
                disabled_days=paid_disabled_days | unpaid_disabled_days,
                forced_days=forced_days,
                want_overtime=want_overtime,
                workdays=workdays,
                paid_disabled_days=paid_disabled_days,
                unpaid_disabled_days=unpaid_disabled_days,
            )
            if new_sched:
                current_schedule = new_sched

        elif choice == "9":
            # Re-solve schedule
            print("\nRe-solving schedule...")
            new_sched = plan_workdays_multiple_months(
                sy, sm, ey, em,
                disabled_days=paid_disabled_days | unpaid_disabled_days,
                forced_days=forced_days,
                want_overtime=want_overtime,
                workdays=workdays,
                paid_disabled_days=paid_disabled_days,
                unpaid_disabled_days=unpaid_disabled_days,
            )
            if new_sched:
                current_schedule = new_sched
                print("[+] Schedule re-solved successfully!")
            else:
                print("[!] Solver failed to find a valid schedule.")

        elif choice in ("0", "q", "exit"):
            print("\nGoodbye!")
            break
        else:
            print("[!] Invalid option. Please enter a number 0-9.")


if __name__ == "__main__":
    main()
