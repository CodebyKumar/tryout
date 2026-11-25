"""Integrity signals from the candidate's browser, summarised for the report. Context for a human, never a score."""

from collections import Counter

from ..models import IntegrityEvent

AWAY = ("tab_hidden", "window_blur", "fullscreen_exit")
MAX_EVENTS = 300  # per interview; the room batches, this stops a runaway page filling the database


def summarize(events: list[IntegrityEvent]) -> dict:
    counts = Counter(e.kind for e in events)
    away_sec = round(sum(e.seconds for e in events if e.kind in AWAY))
    times_away = sum(counts[k] for k in AWAY)
    # A paste into a spoken interview or repeated long absences deserve a look; a second monitor alone does not.
    level = "review" if counts["paste"] or times_away >= 3 or away_sec >= 60 else "some" if events else "none"
    return {
        "level": level,
        "counts": dict(counts),
        "times_away": times_away,
        "away_sec": away_sec,
        "events": [e.model_dump() for e in events],
    }
