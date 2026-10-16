import calendar
import curses
import datetime
import sys

from src.constants import CONSTRAINTS_PATH
from src.constraints import save_day_constraints, _empty_day_constraints
from src.planner import get_japanese_holidays_in_range, plan_workdays_multiple_months, _last_day_of_month


def _jump_month(d: datetime.date, delta_months: int, min_date: datetime.date, max_date: datetime.date) -> datetime.date:
    """Jump by delta_months while keeping day of month if valid."""
    year = d.year
    month = d.month + delta_months
    while month > 12:
        month -= 12
        year += 1
    while month < 1:
        month += 12
        year -= 1
    last_d = _last_day_of_month(year, month).day
    day = min(d.day, last_d)
    new_date = datetime.date(year, month, day)
    return max(min_date, min(new_date, max_date))


def _curses_editor_loop(
    stdscr,
    schedule,
    start_year,
    start_month,
    end_year,
    end_month,
    forced_days,
    paid_disabled_days,
    unpaid_disabled_days,
    disabled_days,
    want_overtime,
    workdays,
    constraints_path,
):
    """Internal curses loop for the interactive calendar editor."""
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    stdscr.scrollok(False)
    stdscr.idlok(False)
    stdscr.keypad(True)
    stdscr.timeout(-1)

    has_color = curses.has_colors()
    if has_color:
        curses.start_color()
        try:
            curses.use_default_colors()
            bg = -1
        except Exception:
            bg = curses.COLOR_BLACK

        curses.init_pair(1, curses.COLOR_GREEN, bg)    # working
        curses.init_pair(2, curses.COLOR_RED, bg)      # weekend/holiday/alert
        curses.init_pair(3, curses.COLOR_CYAN, bg)     # forced
        curses.init_pair(4, curses.COLOR_YELLOW, bg)   # paid leave
        curses.init_pair(5, curses.COLOR_MAGENTA, bg)  # unpaid leave
        curses.init_pair(6, curses.COLOR_WHITE, bg)    # free
        curses.init_pair(7, curses.COLOR_BLACK, curses.COLOR_WHITE) # cursor
        curses.init_pair(8, curses.COLOR_WHITE, curses.COLOR_BLUE)  # header
        curses.init_pair(9, curses.COLOR_YELLOW, bg)   # status / prompt
        curses.init_pair(10, curses.COLOR_WHITE, curses.COLOR_RED) # infeasible header

    range_start = datetime.date(start_year, start_month, 1)
    range_end = _last_day_of_month(end_year, end_month)
    today = datetime.date.today()

    selected_date = today if range_start <= today <= range_end else range_start
    holiday_set = get_japanese_holidays_in_range(start_year, start_month, end_year, end_month)

    # Initial and working copies
    cur_forced = set(forced_days)
    cur_paid = set(paid_disabled_days)
    cur_unpaid = set(unpaid_disabled_days)
    initial_forced = set(forced_days)
    initial_paid = set(paid_disabled_days)
    initial_unpaid = set(unpaid_disabled_days)
    initial_schedule = dict(schedule)
    cur_schedule = dict(schedule)

    dirty = False
    infeasible_warning = None
    status_msg = "Use Arrow Keys to navigate. Press [F], [P], [U], [C] to edit. [S]olve, [Q]uit."

    # Collect list of (year, month)
    months = []
    y, m = start_year, start_month
    while (y < end_year) or (y == end_year and m <= end_month):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1

    scroll_row_offset = 0

    while True:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()

        if max_y < 12 or max_x < 30:
            stdscr.addstr(0, 0, "Terminal window too small! Please enlarge.", curses.A_BOLD)
            stdscr.refresh()
            key = stdscr.getch()
            if key in (ord('q'), ord('Q'), 27):
                return initial_schedule, initial_forced, initial_paid, initial_unpaid, False
            continue

        # Check if constraints differ from initial state
        dirty = (cur_forced != initial_forced) or (cur_paid != initial_paid) or (cur_unpaid != initial_unpaid)

        # Top Header Bar (Row 0): Overwritten with prominent alert if schedule is infeasible
        if infeasible_warning:
            header_text = f" [!] INFEASIBLE: {infeasible_warning} — Adjust days and press 'S' to re-solve "
            header_attr = curses.color_pair(10) | curses.A_BOLD if has_color else curses.A_REVERSE | curses.A_BOLD
        else:
            header_text = f" RA Master Scheduler - Interactive Editor | {start_year}-{start_month:02d} to {end_year}-{end_month:02d} "
            if dirty:
                header_text += "[MODIFIED - Press 'S' to Solve, 'Q' to Exit & Save] "
            header_attr = curses.color_pair(8) if has_color else curses.A_REVERSE

        try:
            stdscr.addstr(0, 0, header_text.ljust(max_x - 1)[:max_x - 1], header_attr)
            # Row 1: Fixed empty padding row
            stdscr.addstr(1, 0, " " * (max_x - 1), curses.A_NORMAL)
        except curses.error:
            pass

        # Fixed Bottom Panel: Reserve exactly 4 rows at bottom
        info_y = max(2, max_y - 4)

        # Month layout calculations
        month_w = 20
        sep_w = 3
        max_cols_per_row = max(1, (max_x - 4) // (month_w + sep_w))

        # Check which month contains selected_date to auto-scroll if needed
        sel_month_idx = 0
        for idx, (yr, mo) in enumerate(months):
            if yr == selected_date.year and mo == selected_date.month:
                sel_month_idx = idx
                break
        sel_month_row = sel_month_idx // max_cols_per_row
        month_block_h = 10
        visible_rows = max(1, (info_y - 2) // month_block_h)

        if sel_month_row < scroll_row_offset:
            scroll_row_offset = sel_month_row
        elif sel_month_row >= scroll_row_offset + visible_rows:
            scroll_row_offset = sel_month_row - visible_rows + 1

        # Draw months
        for idx, (yr, mo) in enumerate(months):
            m_row = idx // max_cols_per_row
            m_col = idx % max_cols_per_row

            # Apply scroll offset
            effective_row = m_row - scroll_row_offset
            if effective_row < 0 or effective_row >= visible_rows:
                continue

            top_y = 2 + effective_row * month_block_h
            left_x = 2 + m_col * (month_w + sep_w)

            # Ensure month fits vertically without touching bottom panel and horizontally without wrapping
            if top_y + 8 >= info_y or left_x + 20 >= max_x:
                continue

            # Title
            title = f"{calendar.month_name[mo]} {yr}".center(20)
            try:
                stdscr.addstr(top_y, left_x, title[:max(0, max_x - left_x - 1)], curses.A_BOLD)
                stdscr.addstr(top_y + 1, left_x, "Su Mo Tu We Th Fr Sa"[:max(0, max_x - left_x - 1)], curses.A_UNDERLINE)
            except curses.error:
                pass

            cal = calendar.Calendar(firstweekday=6)
            w_idx = 0
            day_in_week = 0

            # Count worked days in month
            month_worked = 0
            month_hrs = 0.0

            for day in cal.itermonthdates(yr, mo):
                cell_y = top_y + 2 + w_idx
                cell_x = left_x + day_in_week * 3

                if cell_y < info_y and cell_x + 2 < max_x - 1:
                    if day.month != mo:
                        try:
                            stdscr.addstr(cell_y, cell_x, "  ", curses.A_NORMAL)
                        except curses.error:
                            pass
                    else:
                        hrs = cur_schedule.get(day, 0.0)
                        if day in cur_paid and hrs == 0.0:
                            hrs = 7.75
                        if hrs > 0:
                            month_worked += 1
                            month_hrs += hrs

                        # Determine day style
                        is_selected = (day == selected_date)
                        if is_selected:
                            attr = curses.color_pair(7) | curses.A_BOLD if has_color else curses.A_REVERSE | curses.A_BOLD
                        elif day in cur_forced:
                            attr = curses.color_pair(3) | curses.A_BOLD if has_color else curses.A_BOLD
                        elif day in cur_paid:
                            attr = curses.color_pair(4) | curses.A_BOLD if has_color else curses.A_BOLD
                        elif day in cur_unpaid:
                            attr = curses.color_pair(5) | curses.A_BOLD if has_color else curses.A_BOLD
                        elif hrs > 0:
                            attr = curses.color_pair(1) | curses.A_BOLD if has_color else curses.A_BOLD
                        elif day.weekday() >= 5 or day in holiday_set:
                            attr = curses.color_pair(2) if has_color else curses.A_DIM
                        else:
                            attr = curses.color_pair(6) if has_color else curses.A_NORMAL

                        try:
                            stdscr.addstr(cell_y, cell_x, f"{day.day:2d}", attr)
                        except curses.error:
                            pass

                day_in_week += 1
                if day_in_week == 7:
                    day_in_week = 0
                    w_idx += 1

            # Pad remaining weeks if fewer than 6
            while w_idx < 6:
                cell_y = top_y + 2 + w_idx
                if cell_y < info_y and left_x + 20 < max_x:
                    try:
                        stdscr.addstr(cell_y, left_x, " " * 20, curses.A_NORMAL)
                    except curses.error:
                        pass
                w_idx += 1

            # Progress summary
            try:
                prog_str = f"{month_worked}/{workdays}d ({month_hrs:.1f}h)".center(20)
                stdscr.addstr(top_y + 8, left_x, prog_str[:max(0, max_x - left_x - 1)], curses.A_DIM)
            except curses.error:
                pass

        # Render Fixed Bottom Inspector Panel
        sel_weekday = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][selected_date.weekday()]
        sel_hrs = cur_schedule.get(selected_date, 0.0)
        sel_status = "Free"
        if selected_date in cur_forced:
            sel_status = "Forced Workday"
        elif selected_date in cur_paid:
            sel_status = "Paid Leave (Paid Disabled)"
        elif selected_date in cur_unpaid:
            sel_status = "Unpaid Leave (Unpaid Disabled)"
        elif sel_hrs > 0:
            sel_status = f"Working ({sel_hrs:.2f} hrs)"
        elif selected_date.weekday() >= 5:
            sel_status = "Weekend"
        elif selected_date in holiday_set:
            sel_status = "Japanese National Holiday"

        sep_line = "─" * (max_x - 2)
        info_line = f" Selected: {selected_date} ({sel_weekday}) | Status: {sel_status} | Hours: {sel_hrs:.2f}h "
        help_line = " [F] Force Work  [P] Paid Leave  [U] Unpaid Leave  [C] Clear  [S] Solve (Memory)  [Q] Exit & Save "

        try:
            # Row info_y: Separator
            stdscr.addstr(info_y, 0, sep_line[:max_x - 2], curses.A_DIM)
            # Row info_y + 1: Details
            stdscr.addstr(info_y + 1, 0, info_line.ljust(max_x - 2)[:max_x - 2], curses.A_BOLD)
            # Row info_y + 2: Help shortcuts
            stdscr.addstr(info_y + 2, 0, help_line.ljust(max_x - 2)[:max_x - 2], curses.A_NORMAL)
            # Row info_y + 3: Status / alert message
            if status_msg.startswith("[!]"):
                msg_attr = curses.color_pair(2) | curses.A_BOLD if has_color else curses.A_BOLD
            elif status_msg.startswith("[+]"):
                msg_attr = curses.color_pair(1) | curses.A_BOLD if has_color else curses.A_BOLD
            else:
                msg_attr = curses.color_pair(9) if has_color else curses.A_NORMAL
            stdscr.addstr(info_y + 3, 0, f" {status_msg}".ljust(max_x - 2)[:max_x - 2], msg_attr)
        except curses.error:
            pass

        stdscr.refresh()

        key = stdscr.getch()

        # Navigation
        if key in (curses.KEY_LEFT, ord('h')):
            if selected_date > range_start:
                selected_date -= datetime.timedelta(days=1)
                if not status_msg.startswith("[!]"):
                    status_msg = ""
        elif key in (curses.KEY_RIGHT, ord('l')):
            if selected_date < range_end:
                selected_date += datetime.timedelta(days=1)
                if not status_msg.startswith("[!]"):
                    status_msg = ""
        elif key in (curses.KEY_UP, ord('k')):
            new_d = selected_date - datetime.timedelta(days=7)
            selected_date = max(range_start, new_d)
            if not status_msg.startswith("[!]"):
                status_msg = ""
        elif key in (curses.KEY_DOWN, ord('j')):
            new_d = selected_date + datetime.timedelta(days=7)
            selected_date = min(range_end, new_d)
            if not status_msg.startswith("[!]"):
                status_msg = ""
        elif key in (curses.KEY_PPAGE, ord('[')):
            selected_date = _jump_month(selected_date, -1, range_start, range_end)
            if not status_msg.startswith("[!]"):
                status_msg = ""
        elif key in (curses.KEY_NPAGE, ord(']')):
            selected_date = _jump_month(selected_date, 1, range_start, range_end)
            if not status_msg.startswith("[!]"):
                status_msg = ""
        elif key == curses.KEY_HOME:
            selected_date = range_start
            if not status_msg.startswith("[!]"):
                status_msg = ""
        elif key == curses.KEY_END:
            selected_date = range_end
            if not status_msg.startswith("[!]"):
                status_msg = ""

        # Toggles
        elif key in (ord('f'), ord('F')):
            if selected_date in cur_forced:
                cur_forced.remove(selected_date)
                status_msg = f"Cleared constraint for {selected_date}."
            else:
                cur_forced.add(selected_date)
                cur_paid.discard(selected_date)
                cur_unpaid.discard(selected_date)
                status_msg = f"Set {selected_date} as FORCED WORKDAY."
            dirty = True

        elif key in (ord('p'), ord('P')):
            if selected_date in cur_paid:
                cur_paid.remove(selected_date)
                status_msg = f"Cleared constraint for {selected_date}."
            else:
                cur_paid.add(selected_date)
                cur_forced.discard(selected_date)
                cur_unpaid.discard(selected_date)
                status_msg = f"Set {selected_date} as PAID LEAVE."
            dirty = True

        elif key in (ord('u'), ord('U')):
            if selected_date in cur_unpaid:
                cur_unpaid.remove(selected_date)
                status_msg = f"Cleared constraint for {selected_date}."
            else:
                cur_unpaid.add(selected_date)
                cur_forced.discard(selected_date)
                cur_paid.discard(selected_date)
                status_msg = f"Set {selected_date} as UNPAID LEAVE (disabled)."
            dirty = True

        elif key in (ord('c'), ord('C'), ord('x'), ord('X'), curses.KEY_DC, curses.KEY_BACKSPACE, 127):
            cur_forced.discard(selected_date)
            cur_paid.discard(selected_date)
            cur_unpaid.discard(selected_date)
            status_msg = f"Cleared all custom constraints on {selected_date}."
            dirty = True

        # Re-solve in memory without saving to disk
        elif key in (ord('s'), ord('S')):
            status_msg = "Solving schedule in memory with updated constraints..."
            try:
                stdscr.addstr(info_y + 3, 0, f" {status_msg}".ljust(max_x - 2)[:max_x - 2], curses.A_BOLD)
                stdscr.refresh()
            except curses.error:
                pass

            # Solve in memory ONLY - DO NOT touch constraints.yaml on disk
            new_sched = plan_workdays_multiple_months(
                start_year, start_month, end_year, end_month,
                disabled_days=cur_paid | cur_unpaid,
                forced_days=cur_forced,
                want_overtime=want_overtime,
                workdays=workdays,
                paid_disabled_days=cur_paid,
                unpaid_disabled_days=cur_unpaid,
                verbose=False,
            )

            if new_sched:
                cur_schedule = new_sched
                infeasible_warning = None
                status_msg = "[+] Solved successfully in memory! (Press 'Q' when done to save & exit)"
            else:
                infeasible_warning = "Monthly target or 28h/week limit exceeded"
                status_msg = "[!] INFEASIBLE: Monthly target or 28h/week limit exceeded! Adjust days and press 'S'."

        # Exit & Save prompt
        elif key in (ord('q'), ord('Q'), 27):
            dirty = (cur_forced != initial_forced) or (cur_paid != initial_paid) or (cur_unpaid != initial_unpaid)
            if dirty:
                prompt_msg = "Save changes before exiting? [y] Save & exit / [n] Discard / [c] Cancel: "
                try:
                    stdscr.addstr(
                        info_y + 3, 0,
                        prompt_msg.ljust(max_x - 2)[:max_x - 2],
                        curses.A_BOLD | (curses.color_pair(9) if has_color else curses.A_REVERSE)
                    )
                    stdscr.refresh()
                except curses.error:
                    pass

                while True:
                    conf_key = stdscr.getch()
                    if conf_key in (ord('y'), ord('Y')):
                        # Test solve first
                        new_sched = plan_workdays_multiple_months(
                            start_year, start_month, end_year, end_month,
                            disabled_days=cur_paid | cur_unpaid,
                            forced_days=cur_forced,
                            want_overtime=want_overtime,
                            workdays=workdays,
                            paid_disabled_days=cur_paid,
                            unpaid_disabled_days=cur_unpaid,
                            verbose=False,
                        )
                        if new_sched:
                            added = {
                                "paid_disabled_days": cur_paid - initial_paid,
                                "unpaid_disabled_days": cur_unpaid - initial_unpaid,
                                "forced_days": cur_forced - initial_forced,
                            }
                            removed = {
                                "paid_disabled_days": initial_paid - cur_paid,
                                "unpaid_disabled_days": initial_unpaid - cur_unpaid,
                                "forced_days": initial_forced - cur_forced,
                            }
                            proposed = {
                                "paid_disabled_days": cur_paid,
                                "unpaid_disabled_days": cur_unpaid,
                                "forced_days": cur_forced,
                            }
                            save_day_constraints(proposed, additions=added, removals=removed, path=constraints_path)
                            return new_sched, cur_forced, cur_paid, cur_unpaid, True
                        else:
                            infeasible_warning = "Cannot save: schedule is infeasible"
                            sub_msg = "[!] Infeasible plan cannot be saved! Discard changes and exit? [y/n]: "
                            try:
                                stdscr.addstr(
                                    info_y + 3, 0,
                                    sub_msg.ljust(max_x - 2)[:max_x - 2],
                                    curses.A_BOLD | (curses.color_pair(2) if has_color else curses.A_REVERSE)
                                )
                                stdscr.refresh()
                            except curses.error:
                                pass
                            sub_key = stdscr.getch()
                            if sub_key in (ord('y'), ord('Y')):
                                return initial_schedule, initial_forced, initial_paid, initial_unpaid, False
                            else:
                                status_msg = "Exit cancelled. Adjust days to make schedule feasible."
                                break
                    elif conf_key in (ord('n'), ord('N')):
                        # Discard all unsaved changes and return to initial state without writing to disk
                        return initial_schedule, initial_forced, initial_paid, initial_unpaid, False
                    elif conf_key in (ord('c'), ord('C'), 27):
                        status_msg = "Exit cancelled."
                        break
            else:
                return cur_schedule, cur_forced, cur_paid, cur_unpaid, False


def interactive_calendar_editor(
    schedule,
    start_year,
    start_month,
    end_year,
    end_month,
    forced_days,
    paid_disabled_days,
    unpaid_disabled_days,
    disabled_days=None,
    want_overtime=False,
    workdays=10,
    constraints_path=CONSTRAINTS_PATH,
):
    """
    Launch the full-screen curses interactive calendar editor.
    Returns (updated_schedule, forced_days, paid_disabled_days, unpaid_disabled_days, has_changed).
    Falls back gracefully if stdin/stdout is not a TTY or curses fails.
    """
    if not sys.stdin.isatty():
        print("[!] Terminal does not support full interactive TUI mode (not a TTY).")
        return schedule, forced_days, paid_disabled_days, unpaid_disabled_days, False

    try:
        return curses.wrapper(
            _curses_editor_loop,
            schedule,
            start_year,
            start_month,
            end_year,
            end_month,
            forced_days,
            paid_disabled_days,
            unpaid_disabled_days,
            disabled_days,
            want_overtime,
            workdays,
            constraints_path,
        )
    except Exception as e:
        print(f"[!] Interactive editor error: {e}")
        return schedule, forced_days, paid_disabled_days, unpaid_disabled_days, False
