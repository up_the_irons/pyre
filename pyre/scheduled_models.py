"""Database operations for scheduled transactions."""

import calendar
from datetime import date

from pyre.formatting import fmt, new_id
from pyre.models import post_transaction


def _advance_date(iso_date, frequency):
    """Advance an ISO date string by the given frequency.

    Uses calendar.monthrange for month-end safety (e.g. Jan 31 + 1 month = Feb 28).
    """
    d = date.fromisoformat(iso_date)
    if frequency == "weekly":
        from datetime import timedelta
        d = d + timedelta(days=7)
    elif frequency == "biweekly":
        from datetime import timedelta
        d = d + timedelta(days=14)
    elif frequency == "monthly":
        month = d.month + 1
        year = d.year
        if month > 12:
            month = 1
            year += 1
        day = min(d.day, calendar.monthrange(year, month)[1])
        d = date(year, month, day)
    elif frequency == "quarterly":
        month = d.month + 3
        year = d.year
        while month > 12:
            month -= 12
            year += 1
        day = min(d.day, calendar.monthrange(year, month)[1])
        d = date(year, month, day)
    elif frequency == "yearly":
        year = d.year + 1
        day = min(d.day, calendar.monthrange(year, d.month)[1])
        d = date(year, d.month, day)
    return d.isoformat()


def create_scheduled_transaction(con, description, frequency, next_date,
                                 splits, vendor_id=None, end_date=None):
    """Create a scheduled transaction with splits.

    splits: list of (account_id, amount_cents) or (account_id, amount_cents, description).
    Raises ValueError if splits don't balance.
    """
    total = sum(s[1] for s in splits)
    if total != 0:
        raise ValueError(f"Scheduled transaction does not balance: off by {fmt(total)}")

    st_id = new_id()
    con.execute(
        "INSERT INTO scheduled_transactions "
        "(id, description, vendor_id, frequency, next_date, end_date, enabled) "
        "VALUES (?, ?, ?, ?, ?, ?, 1)",
        (st_id, description, vendor_id, frequency, next_date, end_date),
    )
    for split in splits:
        desc = split[2] if len(split) > 2 else ""
        con.execute(
            "INSERT INTO scheduled_splits "
            "(id, scheduled_tx_id, account_id, amount, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (new_id(), st_id, split[0], split[1], desc),
        )
    con.commit()
    return st_id


def update_scheduled_transaction(con, st_id, description, frequency,
                                 next_date, splits, vendor_id=None,
                                 end_date=None, enabled=True):
    """Update a scheduled transaction, replacing all splits.

    splits: list of (account_id, amount_cents) or (account_id, amount_cents, description).
    Raises ValueError if splits don't balance.
    """
    total = sum(s[1] for s in splits)
    if total != 0:
        raise ValueError(f"Scheduled transaction does not balance: off by {fmt(total)}")

    con.execute(
        "UPDATE scheduled_transactions "
        "SET description=?, vendor_id=?, frequency=?, next_date=?, "
        "end_date=?, enabled=? WHERE id=?",
        (description, vendor_id, frequency, next_date, end_date,
         1 if enabled else 0, st_id),
    )
    con.execute(
        "DELETE FROM scheduled_splits WHERE scheduled_tx_id = ?", (st_id,)
    )
    for split in splits:
        desc = split[2] if len(split) > 2 else ""
        con.execute(
            "INSERT INTO scheduled_splits "
            "(id, scheduled_tx_id, account_id, amount, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (new_id(), st_id, split[0], split[1], desc),
        )
    con.commit()


def delete_scheduled_transaction(con, st_id):
    """Delete a scheduled transaction and its splits."""
    con.execute(
        "DELETE FROM scheduled_splits WHERE scheduled_tx_id = ?", (st_id,)
    )
    con.execute(
        "DELETE FROM scheduled_transactions WHERE id = ?", (st_id,)
    )
    con.commit()


def get_all_scheduled_transactions(con):
    """Return all scheduled transactions with summary info."""
    rows = con.execute("""
        SELECT st.id, st.description, st.frequency, st.next_date,
               st.end_date, st.enabled, COALESCE(v.name, '') as vendor_name,
               st.vendor_id
        FROM scheduled_transactions st
        LEFT JOIN vendors v ON v.id = st.vendor_id
        ORDER BY st.next_date
    """).fetchall()
    result = []
    for r in rows:
        # Get total debit amount for display
        amt_row = con.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM scheduled_splits "
            "WHERE scheduled_tx_id = ? AND amount > 0",
            (r[0],),
        ).fetchone()
        result.append({
            "id": r[0],
            "description": r[1],
            "frequency": r[2],
            "next_date": r[3],
            "end_date": r[4],
            "enabled": bool(r[5]),
            "vendor_name": r[6],
            "vendor_id": r[7],
            "amount": amt_row[0],
        })
    return result


def get_scheduled_transaction_detail(con, st_id):
    """Return (st_dict, splits_list) for a scheduled transaction."""
    row = con.execute(
        "SELECT id, description, vendor_id, frequency, next_date, "
        "end_date, enabled FROM scheduled_transactions WHERE id = ?",
        (st_id,),
    ).fetchone()
    if not row:
        return None, []
    st = {
        "id": row[0],
        "description": row[1],
        "vendor_id": row[2],
        "frequency": row[3],
        "next_date": row[4],
        "end_date": row[5],
        "enabled": bool(row[6]),
    }
    splits = con.execute("""
        SELECT ss.id, ss.account_id, a.name, ss.amount, ss.description
        FROM scheduled_splits ss
        JOIN accounts a ON a.id = ss.account_id
        WHERE ss.scheduled_tx_id = ?
        ORDER BY ss.amount DESC
    """, (st_id,)).fetchall()
    split_list = [
        {
            "id": s[0],
            "account_id": s[1],
            "account_name": s[2],
            "amount": s[3],
            "description": s[4],
        }
        for s in splits
    ]
    return st, split_list


def get_pending_scheduled_transactions(con, as_of=None):
    """Return scheduled transactions that are due (next_date <= as_of).

    Only returns enabled schedules that have not passed their end_date.
    """
    if as_of is None:
        as_of = date.today().isoformat()
    rows = con.execute("""
        SELECT st.id, st.description, st.frequency, st.next_date,
               st.end_date, COALESCE(v.name, '') as vendor_name,
               st.vendor_id
        FROM scheduled_transactions st
        LEFT JOIN vendors v ON v.id = st.vendor_id
        WHERE st.enabled = 1
          AND st.next_date <= ?
          AND (st.end_date IS NULL OR st.end_date >= st.next_date)
        ORDER BY st.next_date
    """, (as_of,)).fetchall()
    result = []
    for r in rows:
        amt_row = con.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM scheduled_splits "
            "WHERE scheduled_tx_id = ? AND amount > 0",
            (r[0],),
        ).fetchone()
        result.append({
            "id": r[0],
            "description": r[1],
            "frequency": r[2],
            "next_date": r[3],
            "end_date": r[4],
            "vendor_name": r[5],
            "vendor_id": r[6],
            "amount": amt_row[0],
        })
    return result


def enter_scheduled_transaction(con, st_id):
    """Post a real transaction from a scheduled transaction template.

    Advances next_date and disables if past end_date.
    Returns the posted transaction ID.
    """
    st, splits = get_scheduled_transaction_detail(con, st_id)
    if not st:
        raise ValueError(f"Scheduled transaction {st_id} not found")

    split_tuples = [
        (s["account_id"], s["amount"], s["description"])
        for s in splits
    ]
    tx_id = post_transaction(
        con, st["next_date"], st["description"], split_tuples,
        vendor_id=st["vendor_id"],
    )

    new_next = _advance_date(st["next_date"], st["frequency"])
    con.execute(
        "UPDATE scheduled_transactions SET next_date = ? WHERE id = ?",
        (new_next, st_id),
    )

    # Disable if the new next_date is past the end_date
    if st["end_date"] and new_next > st["end_date"]:
        con.execute(
            "UPDATE scheduled_transactions SET enabled = 0 WHERE id = ?",
            (st_id,),
        )

    con.commit()
    return tx_id


def enter_pending_transactions(con, st_ids, as_of=None):
    """Post all due occurrences for a list of scheduled transaction IDs.

    Handles multi-period catch-up: loops until next_date > as_of.
    Returns list of posted transaction IDs.
    """
    if as_of is None:
        as_of = date.today().isoformat()

    posted = []
    for st_id in st_ids:
        while True:
            st, _ = get_scheduled_transaction_detail(con, st_id)
            if not st or not st["enabled"]:
                break
            if st["next_date"] > as_of:
                break
            if st["end_date"] and st["next_date"] > st["end_date"]:
                break
            tx_id = enter_scheduled_transaction(con, st_id)
            posted.append(tx_id)
    return posted


def toggle_scheduled_enabled(con, st_id):
    """Toggle the enabled flag on a scheduled transaction."""
    row = con.execute(
        "SELECT enabled FROM scheduled_transactions WHERE id = ?",
        (st_id,),
    ).fetchone()
    if row is None:
        return
    new_val = 0 if row[0] else 1
    con.execute(
        "UPDATE scheduled_transactions SET enabled = ? WHERE id = ?",
        (new_val, st_id),
    )
    con.commit()
