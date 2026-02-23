from pyre.formatting import new_id, cents, fmt

_TXN_SELECT = """
    SELECT t.date, t.description,
           GROUP_CONCAT(a.name || ':' || s.amount || ':' || s.reconcile || ':' || s.account_id, '|') as split_info,
           t.id,
           EXISTS(SELECT 1 FROM import_log il WHERE il.tx_id = t.id AND il.status = 'imported') as imported,
           COALESCE(v.name, '') as vendor_name
    FROM transactions t
    JOIN splits s ON s.tx_id = t.id
    JOIN accounts a ON a.id = s.account_id
    LEFT JOIN vendors v ON v.id = t.vendor_id
"""


def get_account_balance(con, account_id, end_date=None):
    """Get balance in cents for an account, optionally up to end_date."""
    if end_date:
        row = con.execute(
            "SELECT COALESCE(SUM(s.amount), 0) FROM splits s "
            "JOIN transactions t ON t.id = s.tx_id "
            "WHERE s.account_id = ? AND t.date <= ?",
            (account_id, end_date),
        ).fetchone()
    else:
        row = con.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM splits WHERE account_id = ?",
            (account_id,),
        ).fetchone()
    return row[0]


def get_recent_transactions(con):
    """Get all transactions with their splits."""
    rows = con.execute(
        _TXN_SELECT + """
        GROUP BY t.id
        ORDER BY t.date DESC, t.id DESC
    """).fetchall()
    return rows


def post_transaction(con, dt, description, splits, vendor_id=None):
    """
    Post a double-entry transaction.
    splits: list of (account_id, amount_cents) or (account_id, amount_cents, description) tuples.
    Raises ValueError if splits don't balance.
    """
    total = sum(s[1] for s in splits)
    if total != 0:
        raise ValueError(f"Transaction does not balance: off by {fmt(total)}")

    tx_id = new_id()
    con.execute(
        "INSERT INTO transactions (id, date, description, vendor_id) VALUES (?,?,?,?)",
        (tx_id, dt, description, vendor_id),
    )
    for split in splits:
        desc = split[2] if len(split) > 2 else ""
        con.execute(
            "INSERT INTO splits (id, tx_id, account_id, amount, description) VALUES (?,?,?,?,?)",
            (new_id(), tx_id, split[0], split[1], desc),
        )
    con.commit()
    return tx_id


def get_transaction_detail(con, tx_id):
    """Get a transaction with all its splits for editing."""
    tx = con.execute(
        "SELECT id, date, description, memo, vendor_id FROM transactions WHERE id = ?",
        (tx_id,),
    ).fetchone()
    if not tx:
        return None, []
    splits = con.execute("""
        SELECT s.id, s.account_id,
               CASE WHEN dup.cnt > 1 AND p.name IS NOT NULL
                    THEN p.name || ': ' || a.name
                    ELSE a.name END as display_name,
               s.amount, s.description
        FROM splits s
        JOIN accounts a ON a.id = s.account_id
        LEFT JOIN accounts p ON p.id = a.parent_id
        LEFT JOIN (SELECT name, COUNT(*) as cnt FROM accounts GROUP BY name) dup
             ON dup.name = a.name
        WHERE s.tx_id = ?
        ORDER BY s.amount DESC
    """, (tx_id,)).fetchall()
    return tx, splits


def is_transaction_reconciled(con, tx_id):
    """Return True if any split on this transaction is reconciled."""
    row = con.execute(
        "SELECT COUNT(*) FROM splits WHERE tx_id = ? AND reconcile = 'r'",
        (tx_id,),
    ).fetchone()
    return row[0] > 0


def update_transaction(con, tx_id, dt, description, split_updates,
                       new_splits=None, delete_split_ids=None,
                       vendor_id=None):
    """
    Update a transaction's date, description, and splits.
    split_updates: list of (split_id, account_id, new_amount_cents) or
                   (split_id, account_id, new_amount_cents, description) tuples.
    new_splits: list of (account_id, amount_cents) or
                (account_id, amount_cents, description) for newly added splits.
    delete_split_ids: list of split_id for splits to remove.
    Raises ValueError if splits don't balance.
    """
    if is_transaction_reconciled(con, tx_id):
        raise ValueError("Cannot modify a reconciled transaction")
    if new_splits is None:
        new_splits = []
    if delete_split_ids is None:
        delete_split_ids = []

    total = (sum(s[2] for s in split_updates)
             + sum(s[1] for s in new_splits))
    if total != 0:
        raise ValueError(f"Transaction does not balance: off by {fmt(total)}")

    con.execute(
        "UPDATE transactions SET date = ?, description = ?, vendor_id = ? WHERE id = ?",
        (dt, description, vendor_id, tx_id),
    )
    for split in split_updates:
        desc = split[3] if len(split) > 3 else ""
        con.execute(
            "UPDATE splits SET account_id = ?, amount = ?, description = ? WHERE id = ?",
            (split[1], split[2], desc, split[0]),
        )
    for split in new_splits:
        desc = split[2] if len(split) > 2 else ""
        con.execute(
            "INSERT INTO splits (id, tx_id, account_id, amount, description) VALUES (?,?,?,?,?)",
            (new_id(), tx_id, split[0], split[1], desc),
        )
    for split_id in delete_split_ids:
        con.execute("DELETE FROM splits WHERE id = ?", (split_id,))
    con.commit()


def update_transaction_metadata(con, tx_id, description, vendor_id=None,
                                split_descriptions=None,
                                split_accounts=None):
    """Update only the description and vendor_id of a transaction.

    Safe to call on reconciled transactions since these fields do not
    affect account balances or reconciliation integrity.

    split_descriptions: optional dict {split_id: text} to update per-split
    descriptions.
    split_accounts: optional dict {split_id: account_id} to update per-split
    accounts.  Only unreconciled splits may be changed; raises ValueError
    if a reconciled split is targeted.
    """
    con.execute(
        "UPDATE transactions SET description = ?, vendor_id = ? WHERE id = ?",
        (description, vendor_id, tx_id),
    )
    if split_descriptions:
        for split_id, desc in split_descriptions.items():
            con.execute(
                "UPDATE splits SET description = ? WHERE id = ?",
                (desc, split_id),
            )
    if split_accounts:
        for split_id, account_id in split_accounts.items():
            row = con.execute(
                "SELECT reconcile FROM splits WHERE id = ?", (split_id,)
            ).fetchone()
            if row and row[0] == "r":
                raise ValueError(
                    "Cannot change account on a reconciled split"
                )
            con.execute(
                "UPDATE splits SET account_id = ? WHERE id = ?",
                (account_id, split_id),
            )
    con.commit()


def bulk_set_vendor(con, tx_ids, vendor_id):
    """Set vendor_id on multiple transactions at once."""
    placeholders = ",".join("?" for _ in tx_ids)
    con.execute(
        f"UPDATE transactions SET vendor_id = ? WHERE id IN ({placeholders})",
        [vendor_id] + list(tx_ids),
    )
    con.commit()


def delete_transaction(con, tx_id):
    """Delete a transaction and its splits (and any import_log reference)."""
    if is_transaction_reconciled(con, tx_id):
        raise ValueError("Cannot delete a reconciled transaction")
    con.execute("DELETE FROM import_log WHERE tx_id = ?", (tx_id,))
    con.execute("DELETE FROM splits WHERE tx_id = ?", (tx_id,))
    con.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
    con.commit()


def get_account_transactions(con, account_id, start_date=None, end_date=None):
    """Get transactions involving a specific account, optionally filtered by date."""
    sql = _TXN_SELECT + """
        WHERE t.id IN (
            SELECT DISTINCT tx_id FROM splits WHERE account_id = ?
        )
    """
    params = [account_id]
    if start_date:
        sql += " AND t.date >= ?"
        params.append(start_date)
    if end_date:
        sql += " AND t.date <= ?"
        params.append(end_date)
    sql += """
        GROUP BY t.id
        ORDER BY t.date DESC, t.id DESC
    """
    rows = con.execute(sql, params).fetchall()
    return rows


def search_transactions(con, query):
    """Search transactions by description, account name, date, or amount."""
    like = f"%{query}%"
    # Also try matching the query as a dollar amount
    amount_cents = None
    try:
        cleaned = query.replace("$", "").replace(",", "").strip()
        if cleaned:
            amount_cents = cents(cleaned)
    except Exception:
        pass

    # Find matching transaction IDs first, so the account/split filter
    # does not exclude sibling splits from the GROUP_CONCAT.
    id_sql = """
        SELECT DISTINCT t.id
        FROM transactions t
        JOIN splits s ON s.tx_id = t.id
        JOIN accounts a ON a.id = s.account_id
        LEFT JOIN vendors v ON v.id = t.vendor_id
        WHERE t.description LIKE ?
           OR t.date LIKE ?
           OR a.name LIKE ?
           OR v.name LIKE ?
    """
    id_params = [like, like, like, like]

    if amount_cents is not None:
        id_sql += " OR ABS(s.amount) = ?"
        id_params.append(amount_cents)

    # Also match partial amounts (e.g. "7358" matches 735839 cents = $7,358.39)
    id_sql += " OR CAST(ABS(s.amount) AS TEXT) LIKE ?"
    id_params.append(f"%{query.replace('$', '').replace(',', '').replace('.', '').strip()}%")

    sql = _TXN_SELECT + """
        WHERE t.id IN (""" + id_sql + """)
        GROUP BY t.id
        ORDER BY t.date DESC, t.id DESC
    """
    return con.execute(sql, id_params).fetchall()


def get_reconciled_balance(con, account_id):
    """Sum of amounts for reconciled splits (reconcile='r') for an account."""
    row = con.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM splits "
        "WHERE account_id = ? AND reconcile = 'r'",
        (account_id,),
    ).fetchone()
    return row[0]


def get_last_reconciliation(con, account_id):
    """Most recent reconciliation record for an account, or None."""
    row = con.execute(
        "SELECT id, statement_date, statement_balance, beginning_balance, "
        "reconciled_at, split_count FROM reconciliations "
        "WHERE account_id = ? ORDER BY reconciled_at DESC LIMIT 1",
        (account_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "statement_date": row[1],
        "statement_balance": row[2],
        "beginning_balance": row[3],
        "reconciled_at": row[4],
        "split_count": row[5],
    }


def get_unreconciled_splits(con, account_id, through_date):
    """Get unreconciled splits for an account through a date.

    Returns list of dicts with split_id, tx_id, date, description, amount,
    reconcile status.
    """
    rows = con.execute("""
        SELECT s.id, s.tx_id, t.date, t.description, s.amount, s.reconcile,
               COALESCE(v.name, '') as vendor_name
        FROM splits s
        JOIN transactions t ON t.id = s.tx_id
        LEFT JOIN vendors v ON v.id = t.vendor_id
        WHERE s.account_id = ?
          AND s.reconcile IN ('n', 'c')
          AND t.date <= ?
        ORDER BY t.date, t.id
    """, (account_id, through_date)).fetchall()
    return [
        {
            "split_id": r[0],
            "tx_id": r[1],
            "date": r[2],
            "description": r[3],
            "amount": r[4],
            "reconcile": r[5],
            "vendor_name": r[6],
        }
        for r in rows
    ]


def finish_reconciliation(con, account_id, split_ids, statement_date,
                          statement_balance, beginning_balance):
    """Mark splits as reconciled and record the reconciliation."""
    from datetime import datetime, timezone
    rec_id = new_id()
    con.execute(
        "INSERT INTO reconciliations "
        "(id, account_id, statement_date, statement_balance, "
        "beginning_balance, reconciled_at, split_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (rec_id, account_id, statement_date, statement_balance,
         beginning_balance, datetime.now(timezone.utc).isoformat(),
         len(split_ids)),
    )
    for sid in split_ids:
        con.execute(
            "UPDATE splits SET reconcile = 'r', reconciliation_id = ? WHERE id = ?",
            (rec_id, sid),
        )
    # Clear any in-progress session
    con.execute(
        "DELETE FROM reconcile_sessions WHERE account_id = ?",
        (account_id,),
    )
    con.commit()
    return rec_id


def save_reconciliation_progress(con, account_id, cleared_ids, uncleared_ids,
                                 statement_date, statement_balance):
    """Save reconciliation progress by marking cleared/uncleared splits
    and persisting the session info."""
    from datetime import datetime, timezone
    for sid in cleared_ids:
        con.execute(
            "UPDATE splits SET reconcile = 'c' WHERE id = ? AND reconcile = 'n'",
            (sid,),
        )
    for sid in uncleared_ids:
        con.execute(
            "UPDATE splits SET reconcile = 'n' WHERE id = ? AND reconcile = 'c'",
            (sid,),
        )
    con.execute(
        "INSERT OR REPLACE INTO reconcile_sessions "
        "(account_id, statement_date, statement_balance, saved_at) "
        "VALUES (?, ?, ?, ?)",
        (account_id, statement_date, statement_balance,
         datetime.now(timezone.utc).isoformat()),
    )
    con.commit()


def get_reconcile_session(con, account_id):
    """Get in-progress reconciliation session for an account, or None."""
    row = con.execute(
        "SELECT statement_date, statement_balance, saved_at "
        "FROM reconcile_sessions WHERE account_id = ?",
        (account_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "statement_date": row[0],
        "statement_balance": row[1],
        "saved_at": row[2],
    }


def delete_reconcile_session(con, account_id):
    """Remove the in-progress session after finishing reconciliation."""
    con.execute(
        "DELETE FROM reconcile_sessions WHERE account_id = ?",
        (account_id,),
    )
    con.commit()


def get_all_reconciliations(con, account_id=None):
    """List reconciliations, most recent first.

    If account_id is given, returns only that account's reconciliations.
    """
    sql = (
        "SELECT r.id, r.account_id, a.name, r.statement_date, "
        "r.statement_balance, r.beginning_balance, r.reconciled_at, r.split_count "
        "FROM reconciliations r "
        "JOIN accounts a ON a.id = r.account_id "
    )
    params = ()
    if account_id:
        sql += "WHERE r.account_id = ? "
        params = (account_id,)
    sql += "ORDER BY r.reconciled_at DESC"
    rows = con.execute(sql, params).fetchall()
    return [
        {
            "id": r[0],
            "account_id": r[1],
            "account_name": r[2],
            "statement_date": r[3],
            "statement_balance": r[4],
            "beginning_balance": r[5],
            "reconciled_at": r[6],
            "split_count": r[7],
        }
        for r in rows
    ]
