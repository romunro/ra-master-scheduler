import calendar
import datetime
import warnings
import holidays
import pulp

# Filter harmless PuLP 3.x deprecation warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, module="pulp")


def _last_day_of_month(year, month):
    """Return a date object representing the last day of the given year and month."""
    if month == 12:
        return datetime.date(year, 12, 31)
    return datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)


def get_japanese_holidays_in_range(start_year, start_month, end_year, end_month):
    """Return a set of date objects for Japanese holidays within the specified month range."""
    holiday_set = set()
    start_date = datetime.date(start_year, start_month, 1)
    end_date = _last_day_of_month(end_year, end_month)
    for y in range(start_year, end_year + 1):
        jp_holidays = holidays.Japan(years=[y])
        for day in jp_holidays.keys():
            if start_date <= day <= end_date:
                holiday_set.add(day)
    return holiday_set


def generate_date_list(start_year, start_month, end_year, end_month):
    """Generate all dates from (start_year, start_month) through (end_year, end_month)."""
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
    paid_disabled_days=None, unpaid_disabled_days=None,
    verbose=True,
):
    """
    Solves the scheduling problem across multiple consecutive months:
    - Total workdays plus paid disabled days per calendar month equals monthly limit.
    - A 'workday' has at least 7.75 hours (capped at 14).
    - No more than 28 hours in any rolling 7-day window.
    - If want_overtime=True, maximize total hours; otherwise, minimize.
    - Front-loads work towards the start of each period.
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

    date_list = generate_date_list(start_year, start_month, end_year, end_month)
    if not date_list:
        return {}

    holiday_set = get_japanese_holidays_in_range(start_year, start_month, end_year, end_month)

    problem_sense = pulp.LpMaximize if want_overtime else pulp.LpMinimize
    prob = pulp.LpProblem("MultiMonthWorkdayPlanner", problem_sense)

    yes_no = {}
    hours = {}

    for d in date_list:
        feasible = not (
            d.weekday() >= 5 or  # Sat=5, Sun=6
            d in holiday_set or
            d in all_disabled_days
        )

        var_name = d.isoformat()

        if d in forced_days:
            if verbose and not feasible:
                print(f"[!] Warning: Forced day {d} is a weekend/holiday/disabled day.")
            yes_no[d] = pulp.LpVariable(f"yes_no_{var_name}", cat=pulp.LpBinary, upBound=1)
        elif not feasible:
            yes_no[d] = pulp.LpVariable(f"yes_no_{var_name}", cat=pulp.LpBinary)
            prob += (yes_no[d] == 0, f"ForceZero_{d}")
        else:
            yes_no[d] = pulp.LpVariable(f"yes_no_{var_name}", cat=pulp.LpBinary, upBound=1)

        hours[d] = pulp.LpVariable(
            f"hours_{var_name}",
            lowBound=0,
            upBound=14
        )

    # Monthly target workdays
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

    # Workday hours constraints
    for d in date_list:
        if d in paid_disabled_days:
            # Paid leave days count towards total days worked and count 7.75 hours of work
            prob += (hours[d] == 7.75, f"PaidDisabledHours_{d}")
        else:
            prob += (hours[d] >= 7.75 * yes_no[d], f"Min7_75_ifWorked_{d}")
            prob += (hours[d] <= 14, f"Max14HoursIfWorked_{d}")
            prob += (hours[d] <= 28 * yes_no[d], f"Zero_ifNotWorked_{d}")

    # Forced days
    dates_in_range = set(date_list)
    out_of_range_forced = forced_days - dates_in_range
    if verbose and out_of_range_forced:
        formatted = ", ".join(str(d) for d in sorted(out_of_range_forced))
        print(f"[!] Forced days outside the planning range were ignored: {formatted}")
    for fd in forced_days & dates_in_range:
        prob += (yes_no[fd] == 1, f"ForcedDay_{fd}")

    # Rolling 7-day max 28 hours
    date_list_sorted = sorted(date_list)
    for i, d in enumerate(date_list_sorted):
        window_end = d + datetime.timedelta(days=6)
        window_days = [x for x in date_list_sorted if d <= x <= window_end]
        prob += (
            pulp.lpSum([hours[x] for x in window_days]) <= 28,
            f"Max28h_7days_start_{d}"
        )

    # Objective with front-loading
    start_date = min(date_list)
    objective_terms = []
    for d in date_list:
        day_index = (d - start_date).days
        weight = 1.0 + (day_index * 0.001) if not want_overtime else 1.0 - (day_index * 0.001)
        objective_terms.append(hours[d] * weight)

    prob.setObjective(pulp.lpSum(objective_terms))

    status = prob.solve(pulp.PULP_CBC_CMD(msg=0))
    status_str = pulp.LpStatus[status]
    if status_str not in ("Optimal", "Feasible"):
        if verbose:
            print(f"[!] No feasible solution found. Solver status: {status_str}")
        return {}

    schedule = {}
    for d in date_list:
        val = pulp.value(hours[d])
        schedule[d] = round(val if val is not None else 0.0, 2)

    return schedule
