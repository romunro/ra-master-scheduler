import datetime
from pathlib import Path


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


from src.constants import (
    DEFAULT_ALERT_HOURS_BEFORE,
    DEFAULT_TIMEZONE,
)


def export_schedule_to_ical(
    schedule,
    output_path,
    paid_disabled_days=None,
    unpaid_disabled_days=None,
    forced_days=None,
    calendar_name="RA Master Schedule",
):
    """Export scheduled work and constraints as iCalendar events with standard 9:00-17:45 time and 10h alert."""
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
        f"X-WR-TIMEZONE:{DEFAULT_TIMEZONE}",
        "BEGIN:VTIMEZONE",
        f"TZID:{DEFAULT_TIMEZONE}",
        "BEGIN:STANDARD",
        "DTSTART:19700101T000000",
        "TZOFFSETFROM:+0900",
        "TZOFFSETTO:+0900",
        "TZNAME:JST",
        "END:STANDARD",
        "END:VTIMEZONE",
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
            f"DTSTART;TZID={DEFAULT_TIMEZONE}:{day:%Y%m%d}T090000",
            f"DTEND;TZID={DEFAULT_TIMEZONE}:{day:%Y%m%d}T174500",
            f"SUMMARY:{_ical_escape(summary)}",
            f"DESCRIPTION:{_ical_escape(description)}",
            f"CATEGORIES:{','.join(categories)}",
            "TRANSP:TRANSPARENT",
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"DESCRIPTION:Reminder: {summary}",
            f"TRIGGER:-PT{DEFAULT_ALERT_HOURS_BEFORE}H",
            "END:VALARM",
            "END:VEVENT",
        ])

    lines.append("END:VCALENDAR")
    content = "\r\n".join(_ical_fold(line) for line in lines) + "\r\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(content.encode("utf-8"))
    return output_path


def prompt_for_export(schedule, paid_disabled_days, unpaid_disabled_days, forced_days):
    """Prompt user to export schedule to iCalendar file."""
    filename = input("\nEnter output filename [ra-master-schedule.ical]: ").strip()
    filename = filename or "ra-master-schedule.ical"
    try:
        exported = export_schedule_to_ical(
            schedule,
            filename,
            paid_disabled_days=paid_disabled_days,
            unpaid_disabled_days=unpaid_disabled_days,
            forced_days=forced_days,
        )
        print(f"[+] Exported iCalendar file: {exported.resolve()}")
    except OSError as error:
        print(f"[!] Could not export calendar: {error}")
