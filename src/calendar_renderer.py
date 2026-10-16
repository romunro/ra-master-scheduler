import calendar
import datetime
import re
import shutil

from src.constants import (
    COLOR_BOLD,
    COLOR_GRAY,
    COLOR_GREEN,
    COLOR_LIGHT_BLUISH_GREEN,
    COLOR_LIGHT_RED,
    COLOR_MAGENTA,
    COLOR_RESET,
    COLOR_WHITE,
    COLOR_YELLOW,
    LEGEND_ITEMS,
)
from src.planner import get_japanese_holidays_in_range, generate_date_list


def strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences from a string to compute its visual width."""
    return re.sub(r"\033\[[0-9;]*m", "", text)


def get_day_status(
    d: datetime.date,
    schedule: dict,
    holiday_set: set,
    disabled_days: set = None,
    forced_days: set = None,
    paid_disabled_days: set = None,
    unpaid_disabled_days: set = None,
):
    """Determine the type, ANSI color, and label for a specific date."""
    if disabled_days is None:
        disabled_days = set()
    if forced_days is None:
        forced_days = set()
    if paid_disabled_days is None:
        paid_disabled_days = set()
    if unpaid_disabled_days is None:
        unpaid_disabled_days = set()

    hrs = schedule.get(d, 0.0)

    if d in forced_days:
        return "forced", COLOR_LIGHT_BLUISH_GREEN, "Forced work"
    if d in paid_disabled_days:
        return "paid leave", COLOR_YELLOW, "Paid leave"
    if d in unpaid_disabled_days:
        return "unpaid leave", COLOR_MAGENTA, "Unpaid leave"
    if d in disabled_days:
        return "forbidden", COLOR_MAGENTA, "Forbidden"
    if hrs > 0:
        return "working", COLOR_GREEN, f"Work ({hrs:.2f}h)"
    if d.weekday() >= 5:
        return "weekend", COLOR_LIGHT_RED, "Weekend"
    if d in holiday_set:
        return "holiday", COLOR_LIGHT_RED, "Holiday"
    return "free", COLOR_WHITE, "Free"


def render_month_block(
    yr: int,
    mo: int,
    schedule: dict,
    forced_days: set,
    paid_disabled_days: set,
    unpaid_disabled_days: set,
    disabled_days: set,
    holiday_set: set,
    target_workdays: int = 10,
    highlight_today: bool = True,
):
    """
    Render a single month calendar block into 9 lines of exactly 20 visual characters width.
    Lines:
      0: Month Year title
      1: Su Mo Tu We Th Fr Sa
      2-7: Weeks 1-6
      8: Monthly work progress summary
    """
    lines = []
    today = datetime.date.today()

    title = f"{calendar.month_name[mo]} {yr}"
    lines.append(title.center(20))
    lines.append("Su Mo Tu We Th Fr Sa")

    cal = calendar.Calendar(firstweekday=6)
    weeks = []
    cur_week = []
    month_worked = 0
    month_hrs = 0.0

    for day in cal.itermonthdates(yr, mo):
        if day.month != mo:
            cur_week.append("  ")
        else:
            hrs = schedule.get(day, 0.0)
            if day in paid_disabled_days and hrs == 0.0:
                hrs = 7.75
            status, clr, _ = get_day_status(
                day,
                schedule,
                holiday_set,
                disabled_days=disabled_days,
                forced_days=forced_days,
                paid_disabled_days=paid_disabled_days,
                unpaid_disabled_days=unpaid_disabled_days,
            )
            if hrs > 0:
                month_worked += 1
                month_hrs += hrs

            # If it's today, we can underline or bold
            is_today = highlight_today and (day == today)
            style_prefix = f"{COLOR_BOLD}\033[4m" if is_today else ""
            cur_week.append(f"{style_prefix}{clr}{day.day:2d}{COLOR_RESET}")

        if len(cur_week) == 7:
            weeks.append(" ".join(cur_week))
            cur_week = []

    if cur_week:
        weeks.append(" ".join(cur_week))

    while len(weeks) < 6:
        weeks.append(" " * 20)

    lines.extend(weeks)

    progress_str = f"{month_worked}/{target_workdays}d ({month_hrs:.1f}h)"
    lines.append(progress_str.center(20))
    return lines


def render_horizontal_calendar(
    schedule: dict,
    start_year: int,
    start_month: int,
    end_year: int,
    end_month: int,
    disabled_days: set = None,
    forced_days: set = None,
    paid_disabled_days: set = None,
    unpaid_disabled_days: set = None,
    target_workdays: int = 10,
    terminal_width: int = None,
):
    """
    Render all months stacked horizontally to fit terminal width,
    wrapping to a new row only when a month cannot fit horizontally.
    """
    if terminal_width is None:
        terminal_width = shutil.get_terminal_size((80, 24)).columns

    if disabled_days is None:
        disabled_days = set()
    if forced_days is None:
        forced_days = set()
    if paid_disabled_days is None:
        paid_disabled_days = set()
    if unpaid_disabled_days is None:
        unpaid_disabled_days = set()

    holiday_set = get_japanese_holidays_in_range(start_year, start_month, end_year, end_month)

    # Collect month tuples
    months = []
    y, m = start_year, start_month
    while (y < end_year) or (y == end_year and m <= end_month):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1

    # Pre-render all month blocks
    rendered_blocks = [
        render_month_block(
            yr,
            mo,
            schedule,
            forced_days=forced_days,
            paid_disabled_days=paid_disabled_days,
            unpaid_disabled_days=unpaid_disabled_days,
            disabled_days=disabled_days,
            holiday_set=holiday_set,
            target_workdays=target_workdays,
        )
        for (yr, mo) in months
    ]

    # Month width = 20, separator = "   " (3 spaces)
    # Total width for k months: 20 * k + 3 * (k - 1) = 23 * k - 3
    month_width = 20
    sep = "   "
    max_per_row = max(1, (terminal_width + len(sep)) // (month_width + len(sep)))

    output_lines = []
    for i in range(0, len(rendered_blocks), max_per_row):
        row_blocks = rendered_blocks[i : i + max_per_row]
        for line_idx in range(9):
            combined_row = sep.join(block[line_idx] for block in row_blocks)
            output_lines.append(combined_row)
        output_lines.append("")  # Blank line between rows

    return output_lines


def display_overview(
    schedule: dict,
    start_year: int,
    start_month: int,
    end_year: int,
    end_month: int,
    disabled_days: set = None,
    forced_days: set = None,
    paid_disabled_days: set = None,
    unpaid_disabled_days: set = None,
    target_workdays: int = 10,
    want_overtime: bool = False,
    google_calendar_status: str = "",
):
    """Display an uncluttered, responsive dashboard overview of the schedule."""
    term_width = shutil.get_terminal_size((80, 24)).columns
    banner_width = min(term_width, 80)

    effective_schedule = dict(schedule)
    if paid_disabled_days:
        for p_day in paid_disabled_days:
            if effective_schedule.get(p_day, 0.0) == 0.0:
                effective_schedule[p_day] = 7.75

    total_worked_days = sum(1 for hrs in effective_schedule.values() if hrs > 0)
    total_hours = sum(effective_schedule.values())
    today = datetime.date.today()

    duration = (end_year - start_year) * 12 + (end_month - start_month) + 1

    print("\n" + "═" * banner_width)
    print(f" {COLOR_BOLD}RA MASTER SCHEDULER{COLOR_RESET}".center(banner_width + 8))
    print(f" Period: {start_year}-{start_month:02d} to {end_year}-{end_month:02d} ({duration} months) | Target: {target_workdays} days/month | Overtime: {'On' if want_overtime else 'Off'}".center(banner_width))
    print(f" Today: {today} | Total Scheduled: {total_worked_days} days ({total_hours:.2f} hrs)".center(banner_width))
    if google_calendar_status:
        print(f" Google Calendar: {google_calendar_status}".center(banner_width))
    print("═" * banner_width + "\n")

    # Calendar Grid
    calendar_lines = render_horizontal_calendar(
        effective_schedule,
        start_year,
        start_month,
        end_year,
        end_month,
        disabled_days=disabled_days,
        forced_days=forced_days,
        paid_disabled_days=paid_disabled_days,
        unpaid_disabled_days=unpaid_disabled_days,
        target_workdays=target_workdays,
        terminal_width=term_width,
    )
    for line in calendar_lines:
        print(line)

    # Compact Legend
    print("Legend:")
    legend_items = [
        f"{COLOR_GREEN}■{COLOR_RESET} Working",
        f"{COLOR_LIGHT_BLUISH_GREEN}■{COLOR_RESET} Forced",
        f"{COLOR_YELLOW}■{COLOR_RESET} Paid Leave (7.75h)",
        f"{COLOR_MAGENTA}■{COLOR_RESET} Unpaid Leave",
        f"{COLOR_LIGHT_RED}■{COLOR_RESET} Weekend/Holiday",
        f"{COLOR_WHITE}■{COLOR_RESET} Free",
    ]
    print("  " + "   ".join(legend_items))
    print("─" * banner_width)


def display_detailed_table(
    schedule: dict,
    start_year: int,
    start_month: int,
    end_year: int,
    end_month: int,
    disabled_days: set = None,
    forced_days: set = None,
    paid_disabled_days: set = None,
    unpaid_disabled_days: set = None,
):
    """Display the detailed day-by-day table of all dates with hours and 7-day sums."""
    date_list = generate_date_list(start_year, start_month, end_year, end_month)
    holiday_set = get_japanese_holidays_in_range(start_year, start_month, end_year, end_month)
    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    effective_schedule = dict(schedule)
    if paid_disabled_days:
        for p_day in paid_disabled_days:
            if effective_schedule.get(p_day, 0.0) == 0.0:
                effective_schedule[p_day] = 7.75

    print("\nDetailed Day-by-Day Schedule:")
    print("Date        WkDay    Type         Hours   Sum_next_7d")
    print("─────────────────────────────────────────────────────")

    for d in sorted(date_list):
        end_d = d + datetime.timedelta(days=6)
        window_days = [x for x in date_list if d <= x <= end_d]
        sum_7d = sum(effective_schedule.get(x, 0.0) for x in window_days)
        hrs = effective_schedule.get(d, 0.0)

        status, clr, label = get_day_status(
            d,
            effective_schedule,
            holiday_set,
            disabled_days=disabled_days,
            forced_days=forced_days,
            paid_disabled_days=paid_disabled_days,
            unpaid_disabled_days=unpaid_disabled_days,
        )

        print(
            f"{d}  {weekdays[d.weekday()]:>3}   "
            f"{clr}{status:<12}{COLOR_RESET} "
            f"{hrs:5.2f}    "
            f"{sum_7d:5.2f}"
        )
    print("─────────────────────────────────────────────────────\n")
