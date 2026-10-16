import datetime
from pathlib import Path
import yaml

from src.constants import CONFIG_PATH


def load_config(path=CONFIG_PATH):
    """Load configuration from config.yaml."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        return config or {}
    except (OSError, yaml.YAMLError) as error:
        print(f"[!] Could not read config {path}: {error}")
        return {}


def save_config(config, path=CONFIG_PATH):
    """Save configuration to config.yaml safely."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    try:
        temporary_path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")
        temporary_path.replace(path)
        return True
    except OSError as error:
        print(f"[!] Could not write config {path}: {error}")
        return False


def is_configured(config):
    """Check if the configuration has valid defaults set."""
    if not config or not isinstance(config, dict):
        return False
    defaults = config.get("defaults")
    if not defaults or not isinstance(defaults, dict):
        return False
    required_keys = ("start_year", "start_month", "duration", "workdays")
    return all(k in defaults and defaults[k] is not None for k in required_keys)


def prompt_initial_setup(config, path=CONFIG_PATH):
    """Run an initial setup wizard when no settings are found."""
    print("\n" + "=" * 60)
    print(" Welcome to RA Master Scheduler - First-time Setup")
    print("=" * 60)
    print("No existing configuration found. Please answer a few quick questions.\n")

    today = datetime.date.today()
    # Intelligent default: start next month or this month
    suggested_month = today.month + 1
    suggested_year = today.year
    if suggested_month > 12:
        suggested_month = 1
        suggested_year += 1

    # Start Year
    while True:
        sy_str = input(f"Enter start year (e.g., {suggested_year}) [default: {suggested_year}]: ").strip()
        if not sy_str:
            sy = suggested_year
            break
        try:
            sy = int(sy_str)
            if 2000 <= sy <= 2100:
                break
            print("Please enter a valid 4-digit year (2000-2100).")
        except ValueError:
            print("Invalid number. Please try again.")

    # Start Month
    while True:
        sm_str = input(f"Enter start month (1-12) [default: {suggested_month}]: ").strip()
        if not sm_str:
            sm = suggested_month
            break
        try:
            sm = int(sm_str)
            if 1 <= sm <= 12:
                break
            print("Please enter a month between 1 and 12.")
        except ValueError:
            print("Invalid number. Please try again.")

    # Duration
    while True:
        dur_str = input("Enter planning duration in months (e.g. 5) [default: 5]: ").strip()
        if not dur_str:
            duration = 5
            break
        try:
            duration = int(dur_str)
            if 1 <= duration <= 24:
                break
            print("Duration must be between 1 and 24 months.")
        except ValueError:
            print("Invalid number. Please try again.")

    # Workdays per month
    while True:
        wd_str = input("Target workdays per month (Master's: 10, PhD: 12) [default: 10]: ").strip()
        if not wd_str:
            workdays = 10
            break
        try:
            workdays = int(wd_str)
            if 1 <= workdays <= 31:
                break
            print("Workdays must be between 1 and 31.")
        except ValueError:
            print("Invalid number. Please try again.")

    # Overtime
    ot_str = input("Maximise overtime? (y/n) [default: n]: ").strip().lower()
    want_overtime = (ot_str in ("y", "yes"))

    if not isinstance(config, dict):
        config = {}

    config["defaults"] = {
        "start_year": sy,
        "start_month": sm,
        "duration": duration,
        "want_overtime": want_overtime,
        "workdays": workdays,
    }

    if "calendar" not in config:
        config["calendar"] = {
            "read_ical_url": "",
            "service_account_key_path": "service_account.json",
            "write_calendar_id": "",
        }

    save_config(config, path=path)
    print("\n[+] Configuration saved successfully to config.yaml!\n")
    return config


def prompt_edit_settings(config, path=CONFIG_PATH):
    """Edit current settings interactively from the menu."""
    defaults = config.setdefault("defaults", {})
    cur_sy = defaults.get("start_year", datetime.date.today().year)
    cur_sm = defaults.get("start_month", datetime.date.today().month)
    cur_dur = defaults.get("duration", 5)
    cur_wd = defaults.get("workdays", 10)
    cur_ot = defaults.get("want_overtime", False)

    print("\n--- Edit Planning Parameters ---")
    print(f"Current: Start={cur_sy}-{cur_sm:02d}, Duration={cur_dur} months, Workdays={cur_wd}/mo, Overtime={'Yes' if cur_ot else 'No'}")
    print("Press Enter to keep current value.\n")

    # Start Year
    sy_input = input(f"Start year [{cur_sy}]: ").strip()
    sy = int(sy_input) if sy_input.isdigit() else cur_sy

    # Start Month
    sm_input = input(f"Start month (1-12) [{cur_sm}]: ").strip()
    sm = int(sm_input) if sm_input.isdigit() and 1 <= int(sm_input) <= 12 else cur_sm

    # Duration
    dur_input = input(f"Duration in months [{cur_dur}]: ").strip()
    dur = int(dur_input) if dur_input.isdigit() and int(dur_input) > 0 else cur_dur

    # Workdays
    wd_input = input(f"Workdays per month [{cur_wd}]: ").strip()
    wd = int(wd_input) if wd_input.isdigit() and int(wd_input) > 0 else cur_wd

    # Overtime
    ot_input = input(f"Maximise overtime (y/n) [{'y' if cur_ot else 'n'}]: ").strip().lower()
    ot = cur_ot if not ot_input else (ot_input in ("y", "yes"))

    defaults["start_year"] = sy
    defaults["start_month"] = sm
    defaults["duration"] = dur
    defaults["workdays"] = wd
    defaults["want_overtime"] = ot

    save_config(config, path=path)
    print("\n[+] Parameters updated successfully!\n")
    return config
