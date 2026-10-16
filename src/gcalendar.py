import calendar
import datetime
from pathlib import Path
import shutil
import warnings

# Filter harmless Google API Python version deprecation warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="google.api_core")

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    service_account = None
    build = None
    HttpError = Exception

from src.config import save_config
from src.constraints import save_day_constraints
from src.constants import (
    COLOR_BOLD,
    COLOR_GREEN,
    COLOR_LIGHT_RED,
    COLOR_MAGENTA,
    COLOR_RESET,
    COLOR_YELLOW,
    DEFAULT_ALERT_MINUTES,
    DEFAULT_WORK_START_TIME,
    DEFAULT_WORK_END_TIME,
    DEFAULT_TIMEZONE,
)
from src.calendar_renderer import render_month_block, strip_ansi
from src.planner import plan_workdays_multiple_months, get_japanese_holidays_in_range


def _get_google_calendar_service(key_path):
    """Authenticate and build the Google Calendar service client."""
    if service_account is None or build is None:
        print("[!] Google API client library is not installed.")
        return None
    try:
        creds = service_account.Credentials.from_service_account_file(
            key_path,
            scopes=["https://www.googleapis.com/auth/calendar"]
        )
        return build("calendar", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        print(f"[!] Failed to authenticate with Google Calendar: {e}")
        return None


def fetch_google_calendar_constraints(config, start_date, end_date):
    """Fetch constraints directly from the synced Google Calendar."""
    cal_id = config.get("calendar", {}).get("write_calendar_id")
    key_path = config.get("calendar", {}).get("service_account_key_path", "service_account.json")
    if not cal_id or not Path(key_path).exists():
        return None, None, None

    service = _get_google_calendar_service(key_path)
    if not service:
        return None, None, None

    new_paid = set()
    new_unpaid = set()
    new_forced = set()

    time_min = start_date.isoformat() + "T00:00:00Z"
    time_max = (end_date + datetime.timedelta(days=1)).isoformat() + "T00:00:00Z"

    try:
        events_result = service.events().list(
            calendarId=cal_id, timeMin=time_min, timeMax=time_max, singleEvents=True
        ).execute()
        events = events_result.get("items", [])

        for event in events:
            summary = str(event.get("summary", "")).lower()
            start = event.get("start", {})
            dt = start.get("date") or start.get("dateTime")
            if dt:
                dt_obj = datetime.datetime.fromisoformat(dt.split("T")[0]).date()
                if start_date <= dt_obj <= end_date:
                    if summary in ("scheduled work day", "no work scheduled"):
                        continue
                    if "forced" in summary:
                        new_forced.add(dt_obj)
                    elif "unpaid" in summary:
                        new_unpaid.add(dt_obj)
                    elif "paid" in summary:
                        new_paid.add(dt_obj)
                    else:
                        new_unpaid.add(dt_obj)
        return new_paid, new_unpaid, new_forced
    except Exception as e:
        print(f"[!] Failed to fetch constraints from Google Calendar: {e}")
        return None, None, None


def _display_affected_month_comparison(
    yr: int,
    mo: int,
    before_schedule: dict,
    after_schedule: dict,
    before_constraints: dict,
    after_constraints: dict,
    holiday_set: set,
    target_workdays: int,
    before_feasible: bool,
    after_feasible: bool,
    changes_in_month: list,
    terminal_width: int,
):
    """Render side-by-side (or stacked) before/after comparison for an affected month."""
    changes_summary = []
    for d in changes_in_month:
        if d in after_constraints.get("paid_disabled_days", set()) and d not in before_constraints.get("paid_disabled_days", set()):
            changes_summary.append(f"{d} ➔ Paid Leave")
        elif d in after_constraints.get("unpaid_disabled_days", set()) and d not in before_constraints.get("unpaid_disabled_days", set()):
            changes_summary.append(f"{d} ➔ Unpaid Leave")
        elif d in after_constraints.get("forced_days", set()) and d not in before_constraints.get("forced_days", set()):
            changes_summary.append(f"{d} ➔ Forced Work")
    changes_desc = ", ".join(changes_summary) if changes_summary else "Constraints changed"

    print(f"\n{COLOR_BOLD}━━━ Affected Month: {calendar.month_name[mo]} {yr} ({changes_desc}) ━━━{COLOR_RESET}")

    block_before = render_month_block(
        yr, mo,
        schedule=before_schedule,
        forced_days=before_constraints.get("forced_days", set()),
        paid_disabled_days=before_constraints.get("paid_disabled_days", set()),
        unpaid_disabled_days=before_constraints.get("unpaid_disabled_days", set()),
        disabled_days=before_constraints.get("paid_disabled_days", set()) | before_constraints.get("unpaid_disabled_days", set()),
        holiday_set=holiday_set,
        target_workdays=target_workdays,
    )

    block_after = render_month_block(
        yr, mo,
        schedule=after_schedule,
        forced_days=after_constraints.get("forced_days", set()),
        paid_disabled_days=after_constraints.get("paid_disabled_days", set()),
        unpaid_disabled_days=after_constraints.get("unpaid_disabled_days", set()),
        disabled_days=after_constraints.get("paid_disabled_days", set()) | after_constraints.get("unpaid_disabled_days", set()),
        holiday_set=holiday_set,
        target_workdays=target_workdays,
    )

    # Feasibility status lines
    m_worked_b = sum(1 for d, h in before_schedule.items() if d.year == yr and d.month == mo and h > 0)
    m_paid_b = sum(1 for d in before_constraints.get("paid_disabled_days", set()) if d.year == yr and d.month == mo)
    tot_b = m_worked_b + m_paid_b
    if before_feasible and tot_b == target_workdays:
        st_b = f"{COLOR_GREEN}Status: Feasible{COLOR_RESET}".center(20)
    else:
        st_b = f"{COLOR_LIGHT_RED}Status: Infeasible{COLOR_RESET}".center(20)

    m_worked_a = sum(1 for d, h in after_schedule.items() if d.year == yr and d.month == mo and h > 0)
    m_paid_a = sum(1 for d in after_constraints.get("paid_disabled_days", set()) if d.year == yr and d.month == mo)
    tot_a = m_worked_a + m_paid_a
    if after_feasible and tot_a == target_workdays:
        st_a = f"{COLOR_GREEN}Status: Feasible{COLOR_RESET}".center(20)
    else:
        st_a = f"{COLOR_LIGHT_RED}{COLOR_BOLD}Status: INFEASIBLE{COLOR_RESET}".center(20)

    hdr_before = f"{COLOR_BOLD}{'BEFORE (Current)'.center(20)}{COLOR_RESET}"
    hdr_after = f"{COLOR_BOLD}{'AFTER (Google Cal)'.center(20)}{COLOR_RESET}"

    left_lines = [hdr_before] + block_before + [st_b]
    right_lines = [hdr_after] + block_after + [st_a]

    if terminal_width >= 48:
        sep = " " * 6
        indent = "  "
        for l_line, r_line in zip(left_lines, right_lines):
            vis_l = len(strip_ansi(l_line))
            pad = " " * max(0, 20 - vis_l) + sep
            print(f"{indent}{l_line}{pad}{r_line}")
    else:
        print("  --- BEFORE (Current) ---")
        for line in left_lines:
            print("  " + line)
        print("\n  --- AFTER (Google Cal) ---")
        for line in right_lines:
            print("  " + line)


def check_google_calendar_background(
    config,
    start_date,
    end_date,
    stored_constraints,
    sy=None,
    sm=None,
    ey=None,
    em=None,
    want_overtime=False,
    workdays=10,
    current_schedule=None,
):
    """
    Check Google Calendar for constraint changes, solve before and after schedules,
    show side-by-side affected months with feasibility, and prompt to apply them.
    Returns (has_changes, updated_constraints_tuple_or_none, status_string, updated_schedule_or_none).
    """
    cal_id = config.get("calendar", {}).get("write_calendar_id")
    key_path = config.get("calendar", {}).get("service_account_key_path", "service_account.json")

    if not cal_id:
        return False, None, "Not configured", None
    if not Path(key_path).exists():
        return False, None, f"Key file missing ({key_path})", None

    new_paid, new_unpaid, new_forced = fetch_google_calendar_constraints(config, start_date, end_date)
    if new_paid is None:
        return False, None, "Connection failed", None

    stored_paid = set(stored_constraints.get("paid_disabled_days", set()))
    stored_unpaid = set(stored_constraints.get("unpaid_disabled_days", set()))
    stored_forced = set(stored_constraints.get("forced_days", set()))

    added = {
        "paid_disabled_days": new_paid - stored_paid,
        "unpaid_disabled_days": new_unpaid - stored_unpaid,
        "forced_days": new_forced - stored_forced,
    }

    total_changes = (
        len(added["paid_disabled_days"])
        + len(added["unpaid_disabled_days"])
        + len(added["forced_days"])
    )

    if total_changes == 0:
        return False, None, "In sync", None

    if sy is None:
        sy = start_date.year
        sm = start_date.month
    if ey is None:
        ey = end_date.year
        em = end_date.month

    # Determine before schedule
    if current_schedule is not None and len(current_schedule) > 0:
        before_schedule = dict(current_schedule)
        before_feasible = True
    else:
        before_schedule = plan_workdays_multiple_months(
            sy, sm, ey, em,
            disabled_days=stored_paid | stored_unpaid,
            forced_days=stored_forced,
            want_overtime=want_overtime,
            workdays=workdays,
            paid_disabled_days=stored_paid,
            unpaid_disabled_days=stored_unpaid,
            verbose=False,
        ) or {}
        before_feasible = bool(before_schedule)

    # Determine proposed constraints
    proposed_paid = stored_paid | new_paid
    proposed_unpaid = stored_unpaid | new_unpaid
    proposed_forced = stored_forced | new_forced

    conflicts = (proposed_paid | proposed_unpaid) & proposed_forced
    if conflicts:
        formatted = ", ".join(str(d) for d in sorted(conflicts))
        print(f"[!] Conflict: Dates cannot be both disabled and forced: {formatted}")
        return False, None, "Conflict error", None

    proposed_constraints = {
        "paid_disabled_days": proposed_paid,
        "unpaid_disabled_days": proposed_unpaid,
        "forced_days": proposed_forced,
    }

    # Solve after schedule
    after_schedule = plan_workdays_multiple_months(
        sy, sm, ey, em,
        disabled_days=proposed_paid | proposed_unpaid,
        forced_days=proposed_forced,
        want_overtime=want_overtime,
        workdays=workdays,
        paid_disabled_days=proposed_paid,
        unpaid_disabled_days=proposed_unpaid,
        verbose=False,
    ) or {}
    after_feasible = bool(after_schedule)

    # Present changes cleanly to user
    print("\n" + "╭" + "─" * 68 + "╮")
    print(f"│ Google Calendar: {total_changes} new constraint(s) detected:".ljust(69) + "│")
    for d in sorted(added["paid_disabled_days"]):
        print(f"│  • {d}: unconstrained ➔ paid disabled day".ljust(69) + "│")
    for d in sorted(added["unpaid_disabled_days"]):
        print(f"│  • {d}: unconstrained ➔ unpaid disabled day".ljust(69) + "│")
    for d in sorted(added["forced_days"]):
        print(f"│  • {d}: unconstrained ➔ forced work day".ljust(69) + "│")
    print("╰" + "─" * 68 + "╯")

    # Show affected months comparison
    changed_dates = sorted(list(
        added["paid_disabled_days"] | added["unpaid_disabled_days"] | added["forced_days"]
    ))
    affected_months = sorted(list(set((d.year, d.month) for d in changed_dates)))
    holiday_set = get_japanese_holidays_in_range(sy, sm, ey, em)
    terminal_width = shutil.get_terminal_size((80, 24)).columns

    for yr, mo in affected_months:
        month_changes = [d for d in changed_dates if d.year == yr and d.month == mo]
        _display_affected_month_comparison(
            yr, mo,
            before_schedule=before_schedule,
            after_schedule=after_schedule,
            before_constraints=stored_constraints,
            after_constraints=proposed_constraints,
            holiday_set=holiday_set,
            target_workdays=workdays,
            before_feasible=before_feasible,
            after_feasible=after_feasible,
            changes_in_month=month_changes,
            terminal_width=terminal_width,
        )

    # Feasibility status banner across full period
    print("\n" + "╭" + "─" * 68 + "╮")
    if before_feasible and after_feasible:
        banner = " [✓] Feasibility: Both BEFORE and AFTER schedules are FEASIBLE."
        print(f"│{COLOR_GREEN}{banner.ljust(68)}{COLOR_RESET}│")
    elif before_feasible and not after_feasible:
        banner = " [!] WARNING: Applying changes will make the schedule INFEASIBLE!"
        print(f"│{COLOR_LIGHT_RED}{COLOR_BOLD}{banner.ljust(68)}{COLOR_RESET}│")
        print(f"│  • Target of {workdays} days/month or 28h/week limit cannot be satisfied.        │")
    elif not before_feasible and not after_feasible:
        banner = " [!] NOTE: Schedule was already INFEASIBLE and remains INFEASIBLE."
        print(f"│{COLOR_LIGHT_RED}{banner.ljust(68)}{COLOR_RESET}│")
    else:
        banner = " [+] Schedule was INFEASIBLE and will now become FEASIBLE!"
        print(f"│{COLOR_GREEN}{COLOR_BOLD}{banner.ljust(68)}{COLOR_RESET}│")
    print("╰" + "─" * 68 + "╯")

    # Prompt user
    if not after_feasible:
        prompt_str = "Do you want to apply these Google Calendar changes anyway? (y/n) [n]: "
        default_ans = "n"
    else:
        prompt_str = "Do you want to apply these Google Calendar changes? (y/n) [y]: "
        default_ans = "y"

    proceed = input(prompt_str).strip().lower()
    if not proceed:
        proceed = default_ans

    if proceed not in ("y", "yes"):
        print("Google Calendar changes were not applied.")
        return False, None, "Changes ignored", None

    try:
        save_day_constraints(proposed_constraints, additions=added)
        print("[+] Google Calendar constraints saved to constraints.yaml!")
        status_label = "Synced (applied)" if after_feasible else "Synced (infeasible applied)"
        return True, (proposed_paid, proposed_unpaid, proposed_forced), status_label, after_schedule
    except Exception as e:
        print(f"[!] Could not save imported calendar constraints: {e}")
        return False, None, f"Save error: {e}", None


def prompt_google_calendar_setup(config):
    """Prompt user for target calendar if not set, optionally creating a new one."""
    key_path = config.get("calendar", {}).get("service_account_key_path", "service_account.json")
    if not Path(key_path).exists():
        print(f"[!] Service account key not found at {key_path}. Cannot sync to Google Calendar.")
        return None

    service = _get_google_calendar_service(key_path)
    if not service:
        return None

    try:
        calendar_list = service.calendarList().list().execute().get("items", [])
    except Exception as e:
        print(f"[!] Failed to fetch calendar list: {e}")
        return None

    print("\nSelect a Target Google Calendar for syncing:")
    for idx, cal in enumerate(calendar_list, 1):
        print(f"[{idx}] {cal.get('summary')} (ID: {cal.get('id')})")
    print(f"[{len(calendar_list) + 1}] Create a new empty calendar (Recommended)")

    while True:
        choice = input(f"Select an option (1-{len(calendar_list) + 1}) or press Enter to skip: ").strip()
        if not choice:
            return None
        try:
            choice_idx = int(choice)
            if 1 <= choice_idx <= len(calendar_list):
                selected_id = calendar_list[choice_idx - 1]["id"]
                return selected_id
            elif choice_idx == len(calendar_list) + 1:
                cal_name = input("Enter a name for the new calendar [RA Master Schedule]: ").strip() or "RA Master Schedule"
                new_cal = {"summary": cal_name, "timeZone": "Asia/Tokyo"}
                created_cal = service.calendars().insert(body=new_cal).execute()
                new_id = created_cal["id"]
                print(f"[+] Created new calendar: {cal_name}")
                return new_id
        except ValueError:
            pass


def sync_schedule_to_google_calendar(schedule, config, paid_disabled_days, unpaid_disabled_days, forced_days):
    """Sync the schedule and constraints to Google Calendar."""
    cal_id = config.get("calendar", {}).get("write_calendar_id")
    if not cal_id:
        cal_id = prompt_google_calendar_setup(config)
        if not cal_id:
            return
        if "calendar" not in config:
            config["calendar"] = {}
        config["calendar"]["write_calendar_id"] = cal_id
        save_config(config)

    key_path = config.get("calendar", {}).get("service_account_key_path", "service_account.json")
    service = _get_google_calendar_service(key_path)
    if not service:
        return

    print(f"\nSyncing schedule to Google Calendar (ID: {cal_id})...")
    try:
        start_date = min(schedule.keys())
        end_date = max(schedule.keys())
        time_min = start_date.isoformat() + "T00:00:00Z"
        time_max = (end_date + datetime.timedelta(days=1)).isoformat() + "T00:00:00Z"

        events_result = service.events().list(
            calendarId=cal_id, timeMin=time_min, timeMax=time_max, singleEvents=True
        ).execute()
        events = events_result.get("items", [])

        def dummy_callback(request_id, response, exception):
            pass

        events_to_delete = []
        for event in events:
            summary = event.get("summary", "")
            if summary in ("Scheduled work day", "No work scheduled", "Forced work day", "Paid disabled day", "Unpaid disabled day"):
                events_to_delete.append(event["id"])

        if events_to_delete:
            print(f"Clearing {len(events_to_delete)} old generated events...")
            for i in range(0, len(events_to_delete), 50):
                batch = service.new_batch_http_request()
                for event_id in events_to_delete[i:i+50]:
                    batch.add(service.events().delete(calendarId=cal_id, eventId=event_id), callback=dummy_callback)
                batch.execute()

        events_to_insert = []
        for day, hours in schedule.items():
            if day in forced_days:
                summary = "Forced work day"
                description = f"Scheduled hours: {hours:.2f}"
            elif day in paid_disabled_days:
                summary = "Paid disabled day"
                description = "Paid leave"
            elif day in unpaid_disabled_days:
                summary = "Unpaid disabled day"
                description = "Unpaid leave"
            elif hours > 0:
                summary = "Scheduled work day"
                description = f"Scheduled hours: {hours:.2f}"
            else:
                continue

            start_dt = f"{day.isoformat()}T{DEFAULT_WORK_START_TIME}+09:00"
            end_dt = f"{day.isoformat()}T{DEFAULT_WORK_END_TIME}+09:00"

            event_body = {
                "summary": summary,
                "description": description,
                "start": {
                    "dateTime": start_dt,
                    "timeZone": DEFAULT_TIMEZONE,
                },
                "end": {
                    "dateTime": end_dt,
                    "timeZone": DEFAULT_TIMEZONE,
                },
                "reminders": {
                    "useDefault": False,
                    "overrides": [
                        {"method": "popup", "minutes": DEFAULT_ALERT_MINUTES},
                    ],
                },
            }
            events_to_insert.append(event_body)

        if events_to_insert:
            print(f"Inserting {len(events_to_insert)} new events...")
            for i in range(0, len(events_to_insert), 50):
                batch = service.new_batch_http_request()
                for event_body in events_to_insert[i:i+50]:
                    batch.add(service.events().insert(calendarId=cal_id, body=event_body), callback=dummy_callback)
                batch.execute()

        print("[+] Successfully synced to Google Calendar!")

        share_ans = input("\nShare calendar with an email or make public? (y/n) [n]: ").strip().lower()
        if share_ans in ("y", "yes"):
            while True:
                user_email = input("Enter email address to share with (or press Enter to finish): ").strip()
                if not user_email:
                    break
                rule = {"scope": {"type": "user", "value": user_email}, "role": "owner"}
                try:
                    service.acl().insert(calendarId=cal_id, body=rule).execute()
                    print(f"Shared calendar with {user_email}")
                except HttpError as e:
                    print(f"[!] Could not share with {user_email}: {e}")

        safe_id = cal_id.replace("@", "%40") if "@" in cal_id else cal_id
        print(f"\nWeb View URL: https://calendar.google.com/calendar/r?cid={cal_id}")
        print(f"Public iCal URL: https://calendar.google.com/calendar/ical/{safe_id}/public/basic.ics\n")
    except HttpError as error:
        print(f"[!] An error occurred syncing to Google Calendar: {error}")
