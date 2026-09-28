"""Validate contest schedule times in the America/New_York time zone."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


EASTERN = ZoneInfo("America/New_York")


def eastern_time(value: object, field: str) -> datetime:
    if value is None or not str(value).strip():
        raise ValueError(f"{field} is required (use an Eastern local time such as 2026-09-27T14:00:00)")
    if not re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", str(value)):
        raise ValueError(f"{field} must include a date and time in ISO 8601 format")

    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO 8601 date and time") from exc

    local = parsed.replace(tzinfo=None)
    candidates = []
    for fold in (0, 1):
        candidate = local.replace(tzinfo=EASTERN, fold=fold)
        round_trip = candidate.astimezone(timezone.utc).astimezone(EASTERN)
        if round_trip.replace(tzinfo=None) == local and candidate.utcoffset() == round_trip.utcoffset():
            if candidate.utcoffset() not in [valid.utcoffset() for valid in candidates]:
                candidates.append(candidate)

    if not candidates:
        raise ValueError(f"{field} falls in a skipped Eastern daylight saving time hour")

    if parsed.utcoffset() is None:
        if len(candidates) > 1:
            raise ValueError(f"{field} is ambiguous in Eastern time; include -04:00 or -05:00")
        return candidates[0]

    for candidate in candidates:
        if candidate.utcoffset() == parsed.utcoffset():
            return candidate
    raise ValueError(f"{field} has the wrong UTC offset for Eastern time on this date")


def contest_duration(start: datetime, end: datetime) -> str:
    elapsed = end.astimezone(timezone.utc) - start.astimezone(timezone.utc)
    if elapsed <= timedelta(0):
        raise ValueError("end_time must be after start_time")
    milliseconds = elapsed // timedelta(milliseconds=1)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1_000)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
