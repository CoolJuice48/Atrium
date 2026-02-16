"""SM-2 spaced repetition scheduler."""

from datetime import date, timedelta
from typing import Dict


def sm2_schedule(
    quality: int,
    reps: int,
    ease_factor: float,
    interval_days: int,
    lapses: int,
) -> Dict:
    """
    SM-2 spaced repetition scheduling.

    Args:
        quality:       User grade 0-5 (0=blackout, 5=perfect)
        reps:          Current repetition count
        ease_factor:   Current ease factor (>= 1.3)
        interval_days: Current interval in days
        lapses:        Current lapse count

    Returns:
        Dict with: due_date, interval_days, ease_factor, reps, lapses
    """
    if not (0 <= quality <= 5):
        raise ValueError(f"Quality must be 0-5, got {quality}")

    if quality < 3:
        # Lapse: reset interval, increment lapses, decrease ease
        new_interval = 1
        new_reps = 0
        new_lapses = lapses + 1
        new_ease = max(1.3, ease_factor - 0.20)
    else:
        # Success
        new_lapses = lapses

        if reps == 0:
            new_interval = 1
        elif reps == 1:
            new_interval = 6
        else:
            new_interval = round(interval_days * ease_factor)

        new_reps = reps + 1

        # SM-2 ease adjustment:
        # EF' = EF + (0.1 - (5-q) * (0.08 + (5-q) * 0.02))
        new_ease = ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
        new_ease = max(1.3, new_ease)

    new_due = (date.today() + timedelta(days=new_interval)).isoformat()

    return {
        'due_date': new_due,
        'interval_days': new_interval,
        'ease_factor': round(new_ease, 4),
        'reps': new_reps,
        'lapses': new_lapses,
    }
