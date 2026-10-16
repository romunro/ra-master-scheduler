import datetime
from src.constants import CONSTRAINTS_PATH
from src.constraints import save_day_constraints


def find_past_planned_workdays(schedule, forced_days, paid_disabled_days=None, today=None):
    """Find all scheduled workdays occurring strictly before today that are not forced yet."""
    if today is None:
        today = datetime.date.today()
    if paid_disabled_days is None:
        paid_disabled_days = set()
    return sorted([
        d for d, hrs in schedule.items()
        if d < today and hrs > 0 and d not in forced_days and d not in paid_disabled_days
    ])


def lock_past_workdays(
    schedule,
    forced_days,
    paid_disabled_days,
    unpaid_disabled_days,
    today=None,
    constraints_path=CONSTRAINTS_PATH,
    confirm=True,
):
    """
    Convert all previously planned workdays that have already passed into forced workdays.
    Returns (updated_forced_days, has_changed).
    """
    if today is None:
        today = datetime.date.today()

    forced_days = set(forced_days)
    paid_disabled_days = set(paid_disabled_days)
    unpaid_disabled_days = set(unpaid_disabled_days)

    to_lock = find_past_planned_workdays(schedule, forced_days, paid_disabled_days=paid_disabled_days, today=today)

    if not to_lock:
        print(f"\n[i] No unlocked past workdays found before {today}.")
        print("    All past workdays are already forced or no past work was scheduled.")
        return forced_days, False

    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    print(f"\nFound {len(to_lock)} past planned workday(s) before {today} to lock into forced workdays:")
    for d in to_lock:
        hrs = schedule.get(d, 0.0)
        print(f"  • {d} ({weekdays[d.weekday()]}): {hrs:.2f} hrs")

    if confirm:
        ans = input(f"\nLock these {len(to_lock)} day(s) as forced workdays? (y/n) [y]: ").strip().lower()
        if ans not in ("", "y", "yes"):
            print("Operation cancelled. Past workdays were not changed.")
            return forced_days, False

    new_forced = forced_days | set(to_lock)
    # Remove from disabled sets if any conflict (shouldn't happen since hrs > 0)
    paid_disabled_days -= set(to_lock)
    unpaid_disabled_days -= set(to_lock)

    additions = {
        "paid_disabled_days": set(),
        "unpaid_disabled_days": set(),
        "forced_days": set(to_lock),
    }
    proposed_constraints = {
        "paid_disabled_days": paid_disabled_days,
        "unpaid_disabled_days": unpaid_disabled_days,
        "forced_days": new_forced,
    }

    try:
        save_day_constraints(
            proposed_constraints,
            additions=additions,
            path=constraints_path,
        )
        print(f"\n[+] Successfully converted and locked {len(to_lock)} past workday(s) into forced workdays!")
        return new_forced, True
    except (OSError, ValueError) as error:
        print(f"[!] Could not save locked workdays to constraints: {error}")
        return forced_days, False
