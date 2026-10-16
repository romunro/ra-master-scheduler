import datetime
from pathlib import Path
import re
import yaml

from src.constants import CONSTRAINT_TYPES, CONSTRAINTS_PATH


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


def parse_short_date_input(line: str) -> set:
    """Parse user input like '2025-2-1,2,5,3-25,20,2026-1-15' into date objects."""
    tokens = [t.strip() for t in line.split(",") if t.strip()]
    result = set()

    current_year = None
    current_month = None

    for tok in tokens:
        parts = tok.split("-")
        if len(parts) == 3:
            y, m, d = parts
            y_i = int(y)
            m_i = int(m)
            d_i = int(d)
            _check_valid_date(y_i, m_i, d_i)
            current_year = y_i
            current_month = m_i
            result.add(datetime.date(y_i, m_i, d_i))
        elif len(parts) == 2:
            p1, p2 = parts
            p1_i = int(p1)
            p2_i = int(p2)
            if p1_i > 12:
                _check_year_month(p1_i, p2_i)
                current_year = p1_i
                current_month = p2_i
            else:
                if current_year is None:
                    _check_year_month(p1_i, p2_i)
                    current_year = p1_i
                    current_month = p2_i
                else:
                    _check_valid_date(current_year, p1_i, p2_i)
                    current_month = p1_i
                    result.add(datetime.date(current_year, current_month, p2_i))
        elif len(parts) == 1:
            d_i = int(parts[0])
            if current_year is not None and current_month is not None:
                _check_valid_date(current_year, current_month, d_i)
                result.add(datetime.date(current_year, current_month, d_i))
            else:
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
    datetime.date(y, m, d)


def safe_parse_short_date_input(prompt: str) -> set:
    """Prompt user repeatedly until they provide a valid short-date line or press Enter."""
    while True:
        line = input(prompt).strip()
        if not line:
            return set()
        try:
            return parse_short_date_input(line)
        except ValueError as e:
            print(f"Error parsing '{line}': {e}")
            print("Please re-enter the entire list of dates correctly.\n")


def _parse_removal_indices(choice_str, max_len, entries):
    """Parse user input string selecting entries to remove."""
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
    """Display list of custom entries and allow user to remove one or more."""
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
