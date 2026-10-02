import calendar
import datetime
import re
import sys
from pathlib import Path

# Handle holidays package
try:
    import holidays
except ImportError:
    print("This script requires 'holidays' for handling public holidays.")
    print("Install it using: pip install holidays")
    sys.exit(1)

# Handle PuLP package
try:
    import pulp
except ImportError:
    print("This script requires 'pulp' (PuLP) for optimization.")
    print("Install it using: pip install pulp")
    sys.exit(1)

try:
    import yaml
except ImportError:
    print("This script requires 'PyYAML' for persistent day constraints.")
    print("Install it using: pip install PyYAML")
    sys.exit(1)


CONSTRAINTS_PATH = Path(__file__).resolve().parents[1] / "constraints.yaml"
CONSTRAINT_TYPES = (
    "paid_disabled_days",
    "unpaid_disabled_days",
    "forced_days",
)


def _empty_day_constraints():
    """Return a fresh constraint mapping with all supported day categories."""
    return {constraint_type: set() for constraint_type in CONSTRAINT_TYPES}


def _parse_yaml_constraint_date(value, context):
    """Convert a YAML scalar to a date and reject timestamps or malformed values."""
    if isinstance(value, datetime.datetime):
        raise ValueError(f"{context} must be a date, not a timestamp")
    if isinstance(value, datetime.date):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{context} must be an ISO date string")
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{context} contains invalid date {value!r}") from error


def _normalise_constraint_mapping(mapping, context):
    """Validate and normalise one YAML constraint mapping to sets of dates."""
    if mapping is None:
        mapping = {}
    if not isinstance(mapping, dict):
        raise ValueError(f"{context} must be a mapping")

    unknown = set(mapping) - set(CONSTRAINT_TYPES)
    if unknown:
        names = ", ".join(sorted(str(name) for name in unknown))
        raise ValueError(f"{context} contains unknown constraint types: {names}")

    constraints = _empty_day_constraints()
    for constraint_type in CONSTRAINT_TYPES:
        values = mapping.get(constraint_type, [])
        if values is None:
            values = []
        if not isinstance(values, list):
            raise ValueError(f"{context}.{constraint_type} must be a list")
        constraints[constraint_type] = {
            _parse_yaml_constraint_date(value, f"{context}.{constraint_type}")
            for value in values
        }
    return constraints


def _serialise_constraint_mapping(constraints):
    """Create deterministic YAML-safe lists from date constraint sets."""
    return {
        constraint_type: [
            day.isoformat() for day in sorted(constraints.get(constraint_type, set()))
        ]
        for constraint_type in CONSTRAINT_TYPES
    }


def load_day_constraints(path=CONSTRAINTS_PATH):
    """Load current day constraints and their append-only history from YAML."""
    path = Path(path)
    if not path.exists():
        return _empty_day_constraints(), []

    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"Could not read {path}: {error}") from error

    if document is None:
        document = {}
    if not isinstance(document, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    if document.get("version", 1) != 1:
        raise ValueError(f"{path} uses an unsupported constraints version")

    constraints = _normalise_constraint_mapping(
        document.get("day_constraints"), "day_constraints"
    )
    history = document.get("history", [])
    if not isinstance(history, list):
        raise ValueError("history must be a list")

    validated_history = []
    for index, entry in enumerate(history):
        if not isinstance(entry, dict):
            raise ValueError(f"history[{index}] must be a mapping")
        recorded_at = entry.get("recorded_at")
        if not isinstance(recorded_at, str) or not recorded_at.strip():
            raise ValueError(f"history[{index}].recorded_at must be a string")
        additions = _normalise_constraint_mapping(
            entry.get("added"), f"history[{index}].added"
        )
        snapshot = _normalise_constraint_mapping(
            entry.get("constraints"), f"history[{index}].constraints"
        )
        history_entry = {
            "recorded_at": recorded_at,
            "added": _serialise_constraint_mapping(additions),
            "constraints": _serialise_constraint_mapping(snapshot),
        }
        if "removed" in entry:
            removals = _normalise_constraint_mapping(
                entry.get("removed"), f"history[{index}].removed"
            )
            history_entry["removed"] = _serialise_constraint_mapping(removals)
        validated_history.append(history_entry)

    conflicts = (
        constraints["forced_days"]
        & (
            constraints["paid_disabled_days"]
            | constraints["unpaid_disabled_days"]
        )
    )
    if conflicts:
        formatted = ", ".join(str(day) for day in sorted(conflicts))
        raise ValueError(
            f"Dates cannot be both forced and disabled in {path}: {formatted}"
        )
    return constraints, validated_history


def save_day_constraints(
    constraints,
    additions=None,
    path=CONSTRAINTS_PATH,
    recorded_at=None,
    removals=None,
):
    """Persist current constraints and append one accepted change to YAML history."""
    if additions is None:
        additions = _empty_day_constraints()
    if removals is None:
        removals = _empty_day_constraints()

    path = Path(path)
    normalised = _normalise_constraint_mapping(
        _serialise_constraint_mapping(constraints), "day_constraints"
    )
    normalised_additions = _normalise_constraint_mapping(
        _serialise_constraint_mapping(additions), "added"
    )
    normalised_removals = _normalise_constraint_mapping(
        _serialise_constraint_mapping(removals), "removed"
    )

    _, history = load_day_constraints(path)
    has_additions = any(normalised_additions[name] for name in CONSTRAINT_TYPES)
    has_removals = any(normalised_removals[name] for name in CONSTRAINT_TYPES)
    if has_additions or has_removals:
        if recorded_at is None:
            recorded_at = datetime.datetime.now(datetime.timezone.utc).isoformat(
                timespec="seconds"
            )
        entry = {
            "recorded_at": recorded_at,
            "added": _serialise_constraint_mapping(normalised_additions),
            "constraints": _serialise_constraint_mapping(normalised),
        }
        if has_removals:
            entry["removed"] = _serialise_constraint_mapping(normalised_removals)
        history.append(entry)

    document = {
        "version": 1,
        "day_constraints": _serialise_constraint_mapping(normalised),
        "history": history,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    try:
        temporary_path.write_text(
            yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError as error:
        raise OSError(f"Could not write {path}: {error}") from error
    return path


def _last_day_of_month(year, month):
    """Return a date object representing the last day of the given year and month."""
    if month == 12:
        return datetime.date(year, 12, 31)
    return datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)

def get_japanese_holidays_in_range(start_year, start_month, end_year, end_month):
    """
    Return a set of date objects for Japanese holidays within the specified month range.
    """

    holiday_set = set()
    for y in range(start_year, end_year + 1):
        jp_holidays = holidays.Japan(years=[y])
        for day in jp_holidays.keys():
            if (datetime.date(start_year, start_month, 1) <= day <= _last_day_of_month(end_year, end_month)):
                holiday_set.add(day)
    return holiday_set

def generate_date_list(start_year, start_month, end_year, end_month):
    """
    Generate all dates from the start of (start_year, start_month)
    through the end of (end_year, end_month).
    """
    start_date = datetime.date(start_year, start_month, 1)
    end_date = _last_day_of_month(end_year, end_month)
    all_dates = []
    current = start_date
    while current <= end_date:
        all_dates.append(current)
        current += datetime.timedelta(days=1)

    return all_dates

def plan_workdays_multiple_months(
    start_year, start_month, end_year, end_month,
    disabled_days=None, forced_days=None, want_overtime=False, workdays=10,
    paid_disabled_days=None, unpaid_disabled_days=None
):
    """
    Solves the scheduling problem across multiple consecutive months:

    - Total workdays plus paid disabled days per calendar month equals the monthly limit
      (10 for Master's student, 12 for PhD student by default).
    - A 'workday' has at least 7.75 hours (no explicit daily max, capped at 14).
    - No more than 28 hours in any rolling 7-day window (across month boundaries).
    - If want_overtime=True, maximize total hours; otherwise, minimize.
    - 'forced_days': set of specific dates that MUST be workdays.
    - 'paid_disabled_days': set of dates that are paid leave (non-working, but count towards monthly limit).
    - 'unpaid_disabled_days': set of dates that are unpaid leave (non-working, do not count towards monthly limit).

    Returns a dict {date: assigned_hours, ...} for each date in the range,
    or an empty dict if no feasible solution is found.
    """
    if disabled_days is None:
        disabled_days = set()
    else:
        disabled_days = set(disabled_days)

    if paid_disabled_days is None:
        paid_disabled_days = set()
    else:
        paid_disabled_days = set(paid_disabled_days)

    if unpaid_disabled_days is None:
        unpaid_disabled_days = set()
    else:
        unpaid_disabled_days = set(unpaid_disabled_days)

    all_disabled_days = disabled_days | paid_disabled_days | unpaid_disabled_days

    if forced_days is None:
        forced_days = set()
    else:
        forced_days = set(forced_days)

    # Generate the overall date range
    date_list = generate_date_list(start_year, start_month, end_year, end_month)
    holiday_set = get_japanese_holidays_in_range(start_year, start_month, end_year, end_month)

    # Prepare the LP problem
    problem_sense = pulp.LpMaximize if want_overtime else pulp.LpMinimize
    prob = pulp.LpProblem("MultiMonthWorkdayPlanner", problem_sense)

    # Decision variables:
    # - yes_no[d] in {0,1} indicates if day d is a chosen workday
    # - hours[d] >= 0 indicates how many hours we work on day d
    yes_no = {}
    hours = {}

    for d in date_list:
        feasible = not (
            d.weekday() >= 5 or  # Sat=5, Sun=6
            d in holiday_set or
            d in all_disabled_days
        )

        var_name = d.isoformat()

        # If forced, then yes_no must be 1, otherwise up to feasibility
        if d in forced_days:
            # If day is forced but also a weekend/holiday/disabled, likely infeasible.
            # We'll let the solver handle or fail, but we can also do a quick check.
            if not feasible:
                print(f"[!] Forced day {d} is not feasible (weekend/holiday/disabled). Could be infeasible.")
            yes_no_ub = 1
        else:
            yes_no_ub = 1 if feasible else 0

        if not feasible:
            # Create a normal binary variable
            yes_no[d] = pulp.LpVariable(f"yes_no_{var_name}", cat=pulp.LpBinary)

            # Then force it to 0 via a constraint
            prob += (yes_no[d] == 0, f"ForceZero_{d}")
        else:
            yes_no[d] = pulp.LpVariable(f"yes_no_{var_name}", cat=pulp.LpBinary, upBound=1)

        # Modify the hours variable to explicitly cap daily hours
        hours[d] = pulp.LpVariable(
            f"hours_{var_name}",
            lowBound=0,  # Minimum hours: 0
            upBound=14  # Maximum hours: 14
        )

    # Constraint 1: Exactly `workdays` days per month (counting paid disabled days)
    all_ym = sorted(list({(d.year, d.month) for d in date_list}))
    for (y, m) in all_ym:
        dates_in_month = [d for d in date_list if (d.year, d.month) == (y, m)]
        paid_in_month = [
            d for d in dates_in_month
            if d in paid_disabled_days and d.weekday() < 5 and d not in holiday_set
        ]
        target_workdays = max(0, workdays - len(paid_in_month))
        prob += (
            pulp.lpSum([yes_no[d] for d in dates_in_month]) == target_workdays,
            f"Exactly{workdays}days_{y}_{m}"
        )

    # Constraint 2: If yes_no[d] = 1, then hours[d] >= 7.75.
    # If yes_no[d] = 0, then hours[d] = 0.
    for d in date_list:
        prob += (hours[d] >= 7.75 * yes_no[d], f"Min7_75_ifWorked_{d}")
        prob += (hours[d] <= 14, f"Max14HoursIfWorked_{d}")  # Enforce 14-hour max
        prob += (hours[d] <= 28 * yes_no[d], f"Zero_ifNotWorked_{d}")

    # Constraint 2b: forced_days within the planning range must be chosen.
    dates_in_range = set(date_list)
    out_of_range_forced = forced_days - dates_in_range
    if out_of_range_forced:
        formatted = ", ".join(str(d) for d in sorted(out_of_range_forced))
        print(f"[!] Forced days outside the planning range were ignored: {formatted}")
    for fd in forced_days & dates_in_range:
        prob += (yes_no[fd] == 1, f"ForcedDay_{fd}")

    # Constraint 3: No more than 28 hours in any rolling 7-day window
    date_list_sorted = sorted(date_list)
    for i, d in enumerate(date_list_sorted):
        window_end = d + datetime.timedelta(days=6)
        window_days = [x for x in date_list_sorted if d <= x <= window_end]
        prob += (
            pulp.lpSum([hours[x] for x in window_days]) <= 28,
            f"Max28h_7days_start_{d}"
        )

    # Objective: sum of hours over entire range
    total_hours = pulp.lpSum([hours[d] for d in date_list])
    prob.setObjective(total_hours)

    # Solve
    status = prob.solve(pulp.PULP_CBC_CMD(msg=0))
    status_str = pulp.LpStatus[status]
    if status_str not in ("Optimal", "Feasible"):
        print(f"[!] No feasible solution found. Solver status: {status_str}")
        return {}

    # Collect results
    schedule = {}
    for d in date_list:
        val = pulp.value(hours[d])
        if val is None:
            val = 0.0
        schedule[d] = round(val, 2)

    return schedule

def parse_short_date_input(line: str) -> set:
    """
    Parse user input like '2025-2-1,2,5,3-25,20,2026-1-15' into date objects.
    Raises ValueError if any token is malformed or out of range.
    """
    tokens = [t.strip() for t in line.split(",") if t.strip()]
    result = set()

    current_year = None
    current_month = None

    for tok in tokens:
        parts = tok.split("-")
        if len(parts) == 3:
            # format: YYYY-mm-dd
            y, m, d = parts
            y_i = int(y)
            m_i = int(m)
            d_i = int(d)
            # Validate
            _check_valid_date(y_i, m_i, d_i)
            current_year = y_i
            current_month = m_i
            result.add(datetime.date(y_i, m_i, d_i))

        elif len(parts) == 2:
            # Could be (year, month) or (month, day).
            p1, p2 = parts
            p1_i = int(p1)
            p2_i = int(p2)
            # Decide which is year vs month vs day
            if p1_i > 12:
                # We interpret p1 as year, p2 as month => year-month
                _check_year_month(p1_i, p2_i)
                current_year = p1_i
                current_month = p2_i
            else:
                if current_year is None:
                    # interpret p1 as year, p2 as month
                    _check_year_month(p1_i, p2_i)
                    current_year = p1_i
                    current_month = p2_i
                else:
                    # interpret p1 as month, p2 as day => must have year
                    _check_valid_date(current_year, p1_i, p2_i)
                    current_month = p1_i
                    result.add(datetime.date(current_year, current_month, p2_i))
        elif len(parts) == 1:
            # Just a day number?
            d_i = int(parts[0])
            if current_year is not None and current_month is not None:
                _check_valid_date(current_year, current_month, d_i)
                result.add(datetime.date(current_year, current_month, d_i))
            else:
                # We have no prefix => error
                raise ValueError(f"Cannot parse single day '{tok}' without a known prefix.")
        else:
            raise ValueError(f"Could not parse token '{tok}'")

    return result

def _check_year_month(y: int, m: int):
    """Raise ValueError if invalid year-month."""
    if m < 1 or m > 12:
        raise ValueError(f"Invalid month={m} (should be 1..12)")
    if y < 1 or y > 9999:
        raise ValueError(f"Invalid year={y}")

def _check_valid_date(y: int, m: int, d: int):
    """Use datetime.date() to ensure validity or raise ValueError."""
    datetime.date(y, m, d)  # Will raise ValueError if out of range

def safe_parse_short_date_input(prompt: str) -> set:
    """
    Prompt user repeatedly until they provide a valid short-date line or press Enter (returns empty set).
    Any invalid token in the line => entire line is discarded => user re-prompts.
    """
    while True:
        line = input(prompt).strip()
        if not line:
            return set()  # empty => no dates
        try:
            parsed = parse_short_date_input(line)
            return parsed
        except ValueError as e:
            print(f"Error parsing '{line}': {e}")
            print("Please re-enter the entire list of dates correctly.\n")



def _parse_removal_indices(choice_str, max_len, entries):
    """
    Parse a user input string selecting entries to remove.
    Supports formats like:
      - 'x 1', 'x1', '1', '[1]', '[x] 1'
      - '1, 2, 3', 'x 1, x 2', '1 2'
      - '2026-12-25', 'x 2026-12-25'
      - 'all', 'x all', '*'
    """
    cleaned = choice_str.strip().lower()
    if not cleaned:
        return set()
    if cleaned in ("all", "x all", "xall", "*"):
        return set(range(1, max_len + 1))
    if cleaned == "x" and max_len == 1:
        return {1}

    raw_tokens = re.split(r"[,;\s]+", cleaned)
    tokens = [t for t in raw_tokens if t]

    indices = set()
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in ("x", "[x]", "[ ]"):
            if i + 1 < len(tokens):
                tok = tokens[i + 1]
                i += 1
            else:
                i += 1
                continue

        tok_clean = tok.lstrip("x[").rstrip("]")

        if tok_clean.isdigit():
            val = int(tok_clean)
            if 1 <= val <= max_len:
                indices.add(val)
            else:
                print(f"[!] Warning: Index {val} is out of range (1..{max_len}).")
        else:
            matched = False
            for entry_idx, (day, cat, label) in enumerate(entries, 1):
                if tok_clean == day.isoformat():
                    indices.add(entry_idx)
                    matched = True
                    break
            if not matched:
                print(f"[!] Warning: Could not parse token '{tok}'.")
        i += 1

    return indices


def prompt_remove_custom_entries(
    paid_disabled_days,
    unpaid_disabled_days,
    forced_days,
    path=CONSTRAINTS_PATH,
):
    """
    Display a list of custom entries and allow the user to remove one or more by entering their index / marking with 'x'.
    Saves the updated constraints to path and records removals in history.
    Returns (paid_disabled_days, unpaid_disabled_days, forced_days, changed).
    """
    paid_disabled_days = set(paid_disabled_days)
    unpaid_disabled_days = set(unpaid_disabled_days)
    forced_days = set(forced_days)

    removed_paid = set()
    removed_unpaid = set()
    removed_forced = set()

    while True:
        entries = []
        for d in sorted(paid_disabled_days):
            entries.append((d, "paid_disabled_days", "paid disabled day"))
        for d in sorted(unpaid_disabled_days):
            entries.append((d, "unpaid_disabled_days", "unpaid disabled day"))
        for d in sorted(forced_days):
            entries.append((d, "forced_days", "forced work day"))

        entries.sort(key=lambda item: (item[0], item[1]))

        if not entries:
            if not (removed_paid or removed_unpaid or removed_forced):
                print("No custom entries found to remove.")
            else:
                print("All custom entries have been removed.")
            break

        print("\nCustom entries:")
        for idx, (day, cat, label) in enumerate(entries, 1):
            print(f"  [ ] {idx}. {day} ({label})")

        choice = input(
            "\nEnter entry number(s) to remove (e.g. '1', 'x 1', '1, 3', 'all') [Enter when done]: "
        ).strip()
        if not choice:
            break

        selected_indices = _parse_removal_indices(choice, len(entries), entries)
        if not selected_indices:
            print("No valid entries selected.")
            continue

        for idx in sorted(selected_indices, reverse=True):
            day, cat, label = entries[idx - 1]
            print(f"Removed: [x] {day} ({label})")
            if cat == "paid_disabled_days":
                paid_disabled_days.remove(day)
                removed_paid.add(day)
            elif cat == "unpaid_disabled_days":
                unpaid_disabled_days.remove(day)
                removed_unpaid.add(day)
            elif cat == "forced_days":
                forced_days.remove(day)
                removed_forced.add(day)

    has_changed = bool(removed_paid or removed_unpaid or removed_forced)
    if has_changed:
        proposed_constraints = {
            "paid_disabled_days": paid_disabled_days,
            "unpaid_disabled_days": unpaid_disabled_days,
            "forced_days": forced_days,
        }
        removals = {
            "paid_disabled_days": removed_paid,
            "unpaid_disabled_days": removed_unpaid,
            "forced_days": removed_forced,
        }
        try:
            save_day_constraints(
                proposed_constraints,
                additions=_empty_day_constraints(),
                path=path,
                removals=removals,
            )
            print(f"Saved updated constraints and removal history to {path}.")
        except (OSError, ValueError) as error:
            print(f"[!] Constraints were not applied because they could not be saved: {error}")

    return paid_disabled_days, unpaid_disabled_days, forced_days, has_changed


# The combined display function:

def display_schedule(
    schedule,
    start_year, start_month,
    end_year, end_month,
    disabled_days=None,
    forced_days=None,
    paid_disabled_days=None,
    unpaid_disabled_days=None
):
    """
    Prints:
      1) A table of all dates with columns:
         - Date
         - WkDay
         - Type  (weekend, holiday, forbidden, forced, working, free)
         - Hours
         - Sum_of_next_7d

      2) A color-coded monthly calendar view.
    """
    if disabled_days is None:
        disabled_days = set()
    if forced_days is None:
        forced_days = set()
    if paid_disabled_days is None:
        paid_disabled_days = set()
    if unpaid_disabled_days is None:
        unpaid_disabled_days = set()
    disabled_days = set(disabled_days) | set(paid_disabled_days) | set(unpaid_disabled_days)

    holiday_set = get_japanese_holidays_in_range(start_year, start_month, end_year, end_month)

    # Colors
    COLOR_LIGHT_BLUISH_GREEN = "\033[38;5;86m"  # forced
    COLOR_LIGHT_RED          = "\033[91m"       # weekend & holiday
    COLOR_MAGENTA            = "\033[38;5;207m" # forbidden / unpaid leave
    COLOR_YELLOW             = "\033[93m"       # paid leave
    COLOR_GREEN              = "\033[92m"       # working
    COLOR_WHITE              = "\033[37m"       # free
    COLOR_RESET              = "\033[0m"

    def get_day_type(d, hrs):
        wday = d.weekday()
        if d in forced_days:
            return "forced"
        if wday >= 5:
            return "weekend"
        if d in holiday_set:
            return "holiday"
        if d in paid_disabled_days:
            return "paid leave"
        if d in unpaid_disabled_days:
            return "unpaid leave"
        if d in disabled_days:
            return "forbidden"
        if hrs > 0:
            return "working"
        return "free"

    def get_color(day_type):
        if day_type == "forced":
            return COLOR_LIGHT_BLUISH_GREEN
        if day_type == "working":
            return COLOR_GREEN
        if day_type in ("weekend", "holiday"):
            return COLOR_LIGHT_RED
        if day_type in ("paid leave", "paid disabled day"):
            return COLOR_YELLOW
        if day_type in ("forbidden", "unpaid leave"):
            return COLOR_MAGENTA
        return COLOR_WHITE

    # Table
    date_list = generate_date_list(start_year, start_month, end_year, end_month)
    date_list_sorted = sorted(date_list)
    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    print("Date        WkDay    Type     Hours  Sum_of_next_7d")
    print("-----------------------------------------------------")

    for d in date_list_sorted:
        end_d = d + datetime.timedelta(days=6)
        window_days = [x for x in date_list_sorted if d <= x <= end_d]
        sum_7d = sum(schedule.get(x, 0) for x in window_days)
        hrs = schedule.get(d, 0.0)
        dt = get_day_type(d, hrs)
        clr = get_color(dt)

        row = (
            f"{d}  {weekdays[d.weekday()]:>3}   "
            f"{clr}{dt:<10}{COLOR_RESET} "
            f"{hrs:5.2f}   "
            f"{sum_7d:5.2f}"
        )
        print(row)

    # Calendar
    print("\n========== Calendar View (Color-Coded) ==========")

    def month_range(y1,m1,y2,m2):
        y,m = y1,m1
        while (y<y2) or (y==y2 and m<=m2):
            yield y,m
            m+=1
            if m>12:
                m=1
                y+=1

    for (yr, mo) in month_range(start_year, start_month, end_year, end_month):
        title = f"{calendar.month_name[mo]} {yr}"
        print("\n"+title.center(29," "))
        print(" Su Mo Tu We Th Fr Sa")
        cal = calendar.Calendar(firstweekday=6)
        weeks = []
        cur = []
        for day in cal.itermonthdates(yr, mo):
            if day.month!=mo:
                cur.append("  ")
            else:
                day_hrs = schedule.get(day,0.0)
                dt = get_day_type(day, day_hrs)
                c = get_color(dt)
                ds = f"{day.day:2d}"
                ds_col = f"{c}{ds}{COLOR_RESET}"
                cur.append(ds_col)
            if len(cur)==7:
                weeks.append(cur)
                cur=[]
        if cur:
            weeks.append(cur)
        for w in weeks:
            print(" ".join(w))

    legend = {
        "working": ( get_color("working"), "Working (Scheduled normal workdays)"),
        "weekend": ( get_color("weekend"), "Weekend (Saturdays and Sundays)"),
        "holiday": (get_color( "holiday"), "Holiday (National holidays)"),
        "paid leave": (get_color("paid leave"), "Paid disabled day"),
        "unpaid leave": (get_color("unpaid leave"), "Unpaid disabled day"),
        "forced": (get_color("forced"), "Forced (User-mandated workdays)"),
        "free": ( get_color("free"), "Free (Non-working days)"),
    }

    print("\nColor Legend:")
    for key, (color, description) in legend.items():
        print(f"{color}■\033[0m {description}")

    print("\n=========================================\n")


def _ical_escape(value):
    """Escape text according to RFC 5545."""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def _ical_fold(line, limit=75):
    """Fold an iCalendar content line without splitting UTF-8 characters."""
    chunks = []
    current = ""
    current_size = 0
    for character in line:
        size = len(character.encode("utf-8"))
        if current and current_size + size > limit:
            chunks.append(current)
            current = " " + character
            current_size = 1 + size
        else:
            current += character
            current_size += size
    chunks.append(current)
    return "\r\n".join(chunks)


def export_schedule_to_ical(
    schedule,
    output_path,
    paid_disabled_days=None,
    unpaid_disabled_days=None,
    forced_days=None,
    calendar_name="RA Master Schedule",
):
    """
    Export scheduled work and explicitly entered constraints as all-day iCalendar events.

    Returns the resulting Path. Explicit constraints outside the schedule range are omitted.
    """
    paid_disabled_days = set(paid_disabled_days or ())
    unpaid_disabled_days = set(unpaid_disabled_days or ())
    forced_days = set(forced_days or ())
    schedule_dates = set(schedule)
    output_path = Path(output_path).expanduser()
    if output_path.suffix.lower() not in (".ics", ".ical"):
        output_path = output_path.with_suffix(".ical")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//RA Master Scheduler//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_ical_escape(calendar_name)}",
    ]

    event_dates = {
        d for d, hours in schedule.items() if hours > 0
    } | ((paid_disabled_days | unpaid_disabled_days | forced_days) & schedule_dates)

    for day in sorted(event_dates):
        hours = schedule.get(day, 0.0)
        categories = []
        if day in forced_days:
            summary = "Forced work day"
            categories.append("FORCED WORK")
        elif day in paid_disabled_days:
            summary = "Paid disabled day"
            categories.append("PAID LEAVE")
        elif day in unpaid_disabled_days:
            summary = "Unpaid disabled day"
            categories.append("UNPAID LEAVE")
        else:
            summary = "Scheduled work day"
            categories.append("WORK")

        description = f"Scheduled hours: {hours:.2f}" if hours > 0 else "No work scheduled"
        uid = f"{day:%Y%m%d}-{categories[0].lower().replace(' ', '-') }@ra-master-scheduler"
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTART;VALUE=DATE:{day:%Y%m%d}",
            f"DTEND;VALUE=DATE:{day + datetime.timedelta(days=1):%Y%m%d}",
            f"SUMMARY:{_ical_escape(summary)}",
            f"DESCRIPTION:{_ical_escape(description)}",
            f"CATEGORIES:{','.join(categories)}",
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ])

    lines.append("END:VCALENDAR")
    content = "\r\n".join(_ical_fold(line) for line in lines) + "\r\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(content.encode("utf-8"))
    return output_path


def _dates_within_range(dates, start_date, end_date, label):
    """Return in-range dates and report entries that cannot affect this schedule."""
    dates = set(dates)
    outside = dates - {d for d in dates if start_date <= d <= end_date}
    if outside:
        formatted = ", ".join(str(d) for d in sorted(outside))
        print(f"[!] {label} outside the planning range ignored: {formatted}")
    return {d for d in dates if start_date <= d <= end_date}


def _prompt_for_export(schedule, paid_disabled_days, unpaid_disabled_days, forced_days):
    answer = input("Export this schedule as iCalendar (.ical)? (y/n) [n]: ").strip().lower()
    if answer != "y":
        return
    filename = input("Output filename [ra-master-schedule.ical]: ").strip()
    filename = filename or "ra-master-schedule.ical"
    try:
        exported = export_schedule_to_ical(
            schedule,
            filename,
            paid_disabled_days=paid_disabled_days,
            unpaid_disabled_days=unpaid_disabled_days,
            forced_days=forced_days,
        )
    except OSError as error:
        print(f"[!] Could not export calendar: {error}")
        return
    print(f"Exported iCalendar file: {exported.resolve()}")


def main():
    """Prompt for a schedule, accumulate extra constraints, and optionally export it."""
    print("====== Multi-Month Workday Planner ======")

    today = datetime.date.today()
    next_month = today.replace(day=1) + datetime.timedelta(days=32)
    default_start_year = next_month.year
    default_start_month = next_month.month

    sy_str = input(f"Enter start year (e.g., {default_start_year}) [default: {default_start_year}]: ")
    sm_str = input(f"Enter start month (1-12) [default: {default_start_month}]: ")
    try:
        sy = int(sy_str) if sy_str.strip() else default_start_year
        sm = int(sm_str) if sm_str.strip() else default_start_month
        _check_year_month(sy, sm)
    except ValueError:
        print("Invalid input. Using default start date.")
        sy, sm = default_start_year, default_start_month

    duration_str = input("Enter duration in months (e.g., 2) [default: 2]: ")
    try:
        duration = int(duration_str) if duration_str.strip() else 2
        if duration < 1:
            raise ValueError
    except ValueError:
        duration = 2
        print("Invalid. Using default: 2 months.")

    end_month_index = sy * 12 + (sm - 1) + duration - 1
    ey, em_zero_based = divmod(end_month_index, 12)
    em = em_zero_based + 1
    range_start = datetime.date(sy, sm, 1)
    range_end = _last_day_of_month(ey, em)

    print(f"Planning schedule from {sy}-{sm:02d} to {ey}-{em:02d} ({duration} months).")
    want_overtime = input("Maximise overtime? (y/n) [n]: ").strip().lower() == "y"

    wd_pref = input("Number of workdays per month (Master's: 10, PhD: 12) [default: 10]: ")
    try:
        workdays = int(wd_pref) if wd_pref.strip() else 10
        if workdays < 1:
            raise ValueError
    except ValueError:
        workdays = 10
        print("Invalid input. Using default: 10 workdays (Master's student).")

    try:
        stored_constraints, constraint_history = load_day_constraints()
    except ValueError as error:
        print(f"[!] Invalid constraints file: {error}")
        return

    paid_disabled_days = stored_constraints["paid_disabled_days"]
    unpaid_disabled_days = stored_constraints["unpaid_disabled_days"]
    forced_days = stored_constraints["forced_days"]
    disabled_days = paid_disabled_days | unpaid_disabled_days
    current_schedule = plan_workdays_multiple_months(
        sy, sm, ey, em,
        disabled_days=disabled_days,
        forced_days=forced_days,
        want_overtime=want_overtime,
        workdays=workdays,
        paid_disabled_days=paid_disabled_days,
        unpaid_disabled_days=unpaid_disabled_days,
    )
    if not current_schedule:
        print("No valid schedule found with the constraints loaded from constraints.yaml.")
        return

    print(
        f"Loaded {sum(len(days) for days in stored_constraints.values())} day "
        f"constraint(s) and {len(constraint_history)} history record(s) "
        f"from {CONSTRAINTS_PATH}."
    )
    print("\n=== Initial schedule with persisted constraints ===")
    display_schedule(
        current_schedule, sy, sm, ey, em,
        disabled_days=disabled_days,
        forced_days=forced_days,
        paid_disabled_days=paid_disabled_days,
        unpaid_disabled_days=unpaid_disabled_days,
    )

    if input(
        "Do you want to remove custom entries? (y/n) [n]: "
    ).strip().lower() in ("y", "yes"):
        paid_disabled_days, unpaid_disabled_days, forced_days, changed = (
            prompt_remove_custom_entries(
                paid_disabled_days, unpaid_disabled_days, forced_days
            )
        )
        if changed:
            disabled_days = paid_disabled_days | unpaid_disabled_days
            updated_schedule = plan_workdays_multiple_months(
                sy, sm, ey, em,
                disabled_days=disabled_days,
                forced_days=forced_days,
                want_overtime=want_overtime,
                workdays=workdays,
                paid_disabled_days=paid_disabled_days,
                unpaid_disabled_days=unpaid_disabled_days,
            )
            if updated_schedule:
                current_schedule = updated_schedule
                print("\n=== Updated schedule after removing constraints ===")
                display_schedule(
                    current_schedule, sy, sm, ey, em,
                    disabled_days=disabled_days,
                    forced_days=forced_days,
                    paid_disabled_days=paid_disabled_days,
                    unpaid_disabled_days=unpaid_disabled_days,
                )

    while input(
        "Add additional paid/unpaid disabled days or forced work days? (y/n) [n]: "
    ).strip().lower() == "y":
        print("\nEnter dates as YYYY-M-D,D,M-D (press Enter to add none).")
        new_paid = safe_parse_short_date_input("Additional paid disabled days:\n> ")
        new_unpaid = safe_parse_short_date_input("Additional unpaid disabled days:\n> ")
        new_forced = safe_parse_short_date_input("Additional forced work days:\n> ")

        new_paid = _dates_within_range(new_paid, range_start, range_end, "Paid disabled days")
        new_unpaid = _dates_within_range(new_unpaid, range_start, range_end, "Unpaid disabled days")
        new_forced = _dates_within_range(new_forced, range_start, range_end, "Forced work days")

        proposed_paid = paid_disabled_days | new_paid
        proposed_unpaid = unpaid_disabled_days | new_unpaid
        proposed_forced = forced_days | new_forced
        proposed_disabled = proposed_paid | proposed_unpaid
        conflicts = proposed_disabled & proposed_forced
        if conflicts:
            formatted = ", ".join(str(d) for d in sorted(conflicts))
            print(f"[!] Dates cannot be both disabled and forced; additions not applied: {formatted}")
            continue

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
            print("No valid schedule with these additions; previous constraints retained.")
            continue

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
        except (OSError, ValueError) as error:
            print(f"[!] Constraints were not applied because they could not be saved: {error}")
            continue

        paid_disabled_days = proposed_paid
        unpaid_disabled_days = proposed_unpaid
        forced_days = proposed_forced
        current_schedule = proposed_schedule
        print(f"Saved constraints and history to {CONSTRAINTS_PATH}.")
        display_schedule(
            current_schedule, sy, sm, ey, em,
            disabled_days=proposed_disabled,
            forced_days=forced_days,
            paid_disabled_days=paid_disabled_days,
            unpaid_disabled_days=unpaid_disabled_days,
        )

        if input(
            "Do you want to remove custom entries? (y/n) [n]: "
        ).strip().lower() in ("y", "yes"):
            paid_disabled_days, unpaid_disabled_days, forced_days, changed = (
                prompt_remove_custom_entries(
                    paid_disabled_days, unpaid_disabled_days, forced_days
                )
            )
            if changed:
                disabled_days = paid_disabled_days | unpaid_disabled_days
                updated_schedule = plan_workdays_multiple_months(
                    sy, sm, ey, em,
                    disabled_days=disabled_days,
                    forced_days=forced_days,
                    want_overtime=want_overtime,
                    workdays=workdays,
                    paid_disabled_days=paid_disabled_days,
                    unpaid_disabled_days=unpaid_disabled_days,
                )
                if updated_schedule:
                    current_schedule = updated_schedule
                    print("\n=== Updated schedule after removing constraints ===")
                    display_schedule(
                        current_schedule, sy, sm, ey, em,
                        disabled_days=disabled_days,
                        forced_days=forced_days,
                        paid_disabled_days=paid_disabled_days,
                        unpaid_disabled_days=unpaid_disabled_days,
                    )

    _prompt_for_export(
        current_schedule,
        paid_disabled_days,
        unpaid_disabled_days,
        forced_days,
    )
    print("Done. Exiting.")


if __name__ == "__main__":
    main()
