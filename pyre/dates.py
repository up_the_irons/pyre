from datetime import date, timedelta

from textual.widgets import Input

from pyre.formatting import format_date


class DateInput(Input):
    """Input that auto-resolves shorthand dates on blur.

    Also supports +/= to step forward one day and - to step back.
    """

    def on_key(self, event):
        if event.character in ("-", "+", "="):
            event.prevent_default()
            event.stop()
            val = self.value.strip()
            if not val:
                return
            try:
                iso = parse_date(val)
                d = date.fromisoformat(iso)
            except ValueError:
                return
            delta = 1 if event.character in ("+", "=") else -1
            d += timedelta(days=delta)
            self.value = format_date(d.isoformat())
            self.cursor_position = len(self.value)

    def on_blur(self):
        val = self.value.strip()
        if val:
            try:
                self.value = format_date(parse_date(val))
            except ValueError:
                pass  # leave it, will error on submit


def parse_date(s):
    """
    Parse shorthand dates like GNUCash does.

    Accepted formats:
        1/5        -> Jan 5 of the most likely year
        12/25      -> Dec 25 of the most likely year
        1/5/26     -> Jan 5, 2026
        1/5/2026   -> Jan 5, 2026
        2026-01-05 -> Jan 5, 2026 (ISO passthrough)
        01-05      -> Jan 5 of the most likely year

    Slashes and dashes both work as separators.
    Two-digit years are assumed to be 2000s.
    If month/day with no year, picks the year where the resulting date
    is closest to today (within 6 months into the future, otherwise
    last year).

    Returns ISO format string: YYYY-MM-DD
    Raises ValueError on unparseable input.
    """
    s = s.strip()
    if not s:
        raise ValueError("Empty date")

    # Normalize separators
    s = s.replace("-", "/")
    parts = s.split("/")

    today = date.today()

    if len(parts) == 3:
        # M/D/Y or Y/M/D
        a, b, c = parts
        if len(a) == 4:
            # ISO-ish: 2026/01/05
            year, month, day = int(a), int(b), int(c)
        else:
            # M/D/Y
            month, day, year = int(a), int(b), int(c)
            if year < 100:
                year += 2000

    elif len(parts) == 2:
        # M/D -- no year, pick the closest one
        month, day = int(parts[0]), int(parts[1])
        # Try current year first
        candidate = date(today.year, month, day)
        delta = (candidate - today).days
        if delta > 180:
            # More than ~6 months in the future -> probably meant last year
            year = today.year - 1
        elif delta < -180:
            # More than ~6 months in the past -> probably meant next year
            year = today.year + 1
        else:
            year = today.year

    elif len(parts) == 1:
        # Maybe just a day number? Assume current month/year
        day = int(parts[0])
        month = today.month
        year = today.year

    else:
        raise ValueError(f"Cannot parse date: {s}")

    result = date(year, month, day)
    return result.isoformat()
