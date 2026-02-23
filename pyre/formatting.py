import re
import uuid
from datetime import date
from decimal import Decimal

_MATH_EXPR = re.compile(r'^[\d\.\+\-\*\/\(\)\s]+$')


def new_id():
    return uuid.uuid4().hex[:12]


def cents(d):
    """Convert a string/float/Decimal to integer cents.

    Supports simple arithmetic expressions like "2+4" or "10.50*3".
    """
    s = str(d).strip().replace("$", "").replace(",", "")
    if _MATH_EXPR.match(s) and re.search(r'\d\s*[\+\-\*\/]|\)|\(', s):
        try:
            result = eval(s, {"__builtins__": {}})  # noqa: S307
            return int(Decimal(str(result)) * 100)
        except (SyntaxError, TypeError, ZeroDivisionError):
            pass
    return int(Decimal(s) * 100)


def fmt(amount_cents):
    """Format integer cents as dollar string."""
    sign = "-" if amount_cents < 0 else ""
    abs_cents = abs(amount_cents)
    return f"{sign}${abs_cents // 100:,}.{abs_cents % 100:02d}"


# Display format for dates. Storage is always ISO (YYYY-MM-DD).
DATE_DISPLAY_FMT = "%m-%d-%Y"


def format_date(iso_date):
    """Format an ISO date string (YYYY-MM-DD) for display."""
    return date.fromisoformat(iso_date).strftime(DATE_DISPLAY_FMT)


def format_date_long(iso_date):
    """Format an ISO date string as 'Feb 19, 2026' for human-friendly display."""
    d = date.fromisoformat(iso_date)
    return d.strftime("%b %-d, %Y")
