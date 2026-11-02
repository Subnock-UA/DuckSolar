"""One calendar boundary selector for all meter-derived monthly results."""
from datetime import datetime, timedelta


def boundary_window(target):
    previous_last = target - timedelta(days=1)
    return previous_last.replace(day=28, hour=0, minute=0, second=0), target.replace(day=4)


def choose_boundary(rows, target, now):
    lower, upper = boundary_window(target)
    candidates = []
    for row in rows:
        stamp = datetime.fromisoformat(row[2])
        if lower <= stamp < upper and stamp <= now:
            candidates.append((stamp, row))
    if not candidates:
        return None
    # Compare calendar dates; readings on day 01 always win, regardless of hour.
    # An equal date distance chooses the earlier date, then the earlier time.
    return min(candidates, key=lambda item: (abs((item[0].date()-target.date()).days), item[0]))[0]
