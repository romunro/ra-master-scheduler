from pathlib import Path

# Paths
ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT_DIR / "config.yaml"
CONSTRAINTS_PATH = ROOT_DIR / "constraints.yaml"

# Constraint Types
CONSTRAINT_TYPES = (
    "paid_disabled_days",
    "unpaid_disabled_days",
    "forced_days",
)

# Terminal ANSI Colors
COLOR_LIGHT_BLUISH_GREEN = "\033[38;5;86m"  # forced
COLOR_LIGHT_RED          = "\033[91m"       # weekend & holiday
COLOR_MAGENTA            = "\033[38;5;207m" # forbidden / unpaid leave
COLOR_YELLOW             = "\033[93m"       # paid leave
COLOR_GREEN              = "\033[92m"       # working
COLOR_WHITE              = "\033[37m"       # free
COLOR_GRAY               = "\033[90m"       # dimmed / past
COLOR_BOLD               = "\033[1m"
COLOR_RESET              = "\033[0m"

# Legend definitions
LEGEND_ITEMS = {
    "working": (COLOR_GREEN, "Working (Scheduled normal workdays)"),
    "weekend": (COLOR_LIGHT_RED, "Weekend (Saturdays and Sundays)"),
    "holiday": (COLOR_LIGHT_RED, "Holiday (Japanese national holidays)"),
    "paid leave": (COLOR_YELLOW, "Paid disabled day (Paid leave)"),
    "unpaid leave": (COLOR_MAGENTA, "Unpaid disabled day (Unpaid leave / off)"),
    "forced": (COLOR_LIGHT_BLUISH_GREEN, "Forced (User-mandated workdays)"),
    "free": (COLOR_WHITE, "Free (Non-working weekdays)"),
}

# Standard Event Timing & Alerts
DEFAULT_WORK_START_TIME = "09:00:00"
DEFAULT_WORK_END_TIME = "17:45:00"
DEFAULT_ALERT_HOURS_BEFORE = 10
DEFAULT_ALERT_MINUTES = DEFAULT_ALERT_HOURS_BEFORE * 60  # 600 minutes
DEFAULT_TIMEZONE = "Asia/Tokyo"
