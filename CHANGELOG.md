# Changelog

All notable changes to the `ra-master-scheduler` project are documented in this file.

## [Unreleased] - 2026-10-16

### Added
- **Interactive Calendar Editor (`curses` TUI)**:
  - Full-screen terminal user interface with arrow-key navigation (←, →, ↑, ↓) and month jumping (`[` / `]`, `PgUp` / `PgDn`).
  - One-key toggling: `[F]` for Forced Workday, `[P]` for Paid Leave, `[U]` for Unpaid Leave, `[C]` to Clear.
  - `[S]` solves schedule in memory immediately without touching disk.
  - `[Q]` / `[Esc]` prompts to save or discard changes upon exiting.
  - Dynamic top header alert bar that displays feasibility warnings without disrupting screen layout.
  - Pinned 4-row bottom inspector displaying detailed status of the selected date and available shortcuts.
- **Google Calendar Before & After Comparison**:
  - Detects remote constraint modifications (paid leave, unpaid leave, forced workdays) in the background.
  - Identifies affected months and solves the proposed schedule in memory in advance.
  - Renders side-by-side **Before & After visual calendar comparison** for only the affected months.
  - Warns prominently if remote changes make the schedule infeasible (28h weekly rolling limit or target days unsatisfied) and defaults confirmation prompt to `[n]`.
- **Lock Past Workdays**:
  - Automated detection of past planned workdays before today.
  - One-click locking into forced workdays to preserve historical work records against future re-solving.
- **Horizontal Multi-Month Responsive Layout**:
  - Automatically calculates terminal width and stacks months horizontally side-by-side.
  - Wraps to a new row only when an entire month cannot fit.
  - Visual color legend and per-month progress summaries (e.g. `10/10d (77.5h)`).
- **First-Run Wizard vs. Instant Launch**:
  - Guided setup on first run when settings are missing.
  - Clean overview dashboard and interactive numeric menu on all subsequent runs.
- **Standardized Timing & Alerts**:
  - Scheduled workdays and leave days set to 09:00 – 17:45 (`Asia/Tokyo`).
  - Standard popup reminder set to 10 hours prior (23:00 the evening before) in both iCal export and Google Calendar.
- **Paid Leave Accounting**:
  - Paid leave days count toward monthly target workdays (e.g., 9 workdays + 1 paid leave = 10 target days).
  - Each paid leave day accounts for 7.75 hours in scheduling, rolling 7-day limits, and calendar exports.
- **Comprehensive Unit Test Suite**:
  - 19 automated unit tests covering LP solver, paid leave accounting, past workday locking, horizontal rendering, iCal generation, curses safety, and Google Calendar before/after comparison.

### Changed
- Refactored monolithic script into a clean modular package under `src/`:
  - `planner.py`: Linear programming schedule solver and date math.
  - `constraints.py`: Yaml constraint storage, additions, and removals with change tracking.
  - `interactive_editor.py`: Curses full-screen interactive calendar editor.
  - `calendar_renderer.py`: Terminal calendar formatting and responsive horizontal stacking.
  - `gcalendar.py`: Google Calendar API integration, batched sync, and change detection.
  - `ical_export.py`: iCalendar (.ical) export with 10h alert triggers.
  - `past_workdays.py`: Detection and locking of passed workdays.
  - `config.py` & `constants.py`: Centralized configuration and constants.

### Fixed
- **Terminal Shift & Week Bleeding**:
  - Disabled terminal scrolling (`scrollok(False)`, `idlok(False)`) and clamped line lengths to prevent curses buffer scrolling.
  - Moved infeasible warnings from the bottom to the top header bar, eliminating vertical row shifts and week displacement.
- **Constraint Persistence on Discard**:
  - Resolved premature writing to `constraints.yaml` during infeasible interactive attempts.
  - Ensured disk persistence is only executed upon explicit save confirmation when exiting.
