#!/usr/bin/env python3
"""Check the Pyre database for inconsistencies and integrity issues."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pyre.db import init_db, release_lock


def check_parent_child_type_mismatch(con):
    """Child accounts must have the same type as their parent."""
    rows = con.execute("""
        SELECT c.id, c.name, c.type, p.id, p.name, p.type
        FROM accounts c
        JOIN accounts p ON p.id = c.parent_id
        WHERE c.type != p.type
    """).fetchall()
    for (cid, cname, ctype, pid, pname, ptype) in rows:
        yield "ERROR", f"Type mismatch: '{cname}' ({ctype}) under parent '{pname}' ({ptype})"


def check_orphaned_parent_refs(con):
    """Parent ID references a nonexistent account."""
    rows = con.execute("""
        SELECT id, name, parent_id FROM accounts
        WHERE parent_id IS NOT NULL
        AND parent_id NOT IN (SELECT id FROM accounts)
    """).fetchall()
    for (aid, name, pid) in rows:
        yield "ERROR", f"Orphaned parent: '{name}' references missing account '{pid}'"


def check_circular_hierarchy(con):
    """Detect cycles in the account parent chain."""
    rows = con.execute("SELECT id, parent_id FROM accounts WHERE parent_id IS NOT NULL").fetchall()
    parent_map = {r[0]: r[1] for r in rows}
    all_ids = set(parent_map.keys()) | set(parent_map.values())

    for start in parent_map:
        visited = set()
        current = start
        while current in parent_map:
            if current in visited:
                yield "ERROR", f"Circular hierarchy detected involving account '{start}'"
                break
            visited.add(current)
            current = parent_map[current]


def check_unbalanced_transactions(con):
    """Every transaction's splits must sum to zero."""
    rows = con.execute("""
        SELECT t.id, t.date, t.description, SUM(s.amount) as total
        FROM transactions t
        JOIN splits s ON s.tx_id = t.id
        GROUP BY t.id
        HAVING total != 0
    """).fetchall()
    for (tid, date, desc, total) in rows:
        cents = abs(total)
        yield "ERROR", f"Unbalanced transaction: '{desc}' ({date}) off by ${cents / 100:.2f} [id={tid}]"


def check_transactions_without_splits(con):
    """Every transaction should have at least 2 splits."""
    rows = con.execute("""
        SELECT t.id, t.date, t.description, COUNT(s.id) as split_count
        FROM transactions t
        LEFT JOIN splits s ON s.tx_id = t.id
        GROUP BY t.id
        HAVING split_count < 2
    """).fetchall()
    for (tid, date, desc, count) in rows:
        yield "ERROR", f"Transaction with {count} split(s): '{desc}' ({date}) [id={tid}]"


def check_splits_referencing_missing_accounts(con):
    """Splits should reference existing accounts."""
    rows = con.execute("""
        SELECT s.id, s.tx_id, s.account_id
        FROM splits s
        WHERE s.account_id NOT IN (SELECT id FROM accounts)
    """).fetchall()
    for (sid, tid, aid) in rows:
        yield "ERROR", f"Split references missing account '{aid}' [tx_id={tid}]"


def check_duplicate_account_numbers(con):
    """Account numbers should be unique when set."""
    rows = con.execute("""
        SELECT account_number, GROUP_CONCAT(name, ', ') as names, COUNT(*) as cnt
        FROM accounts
        WHERE account_number IS NOT NULL AND account_number != ''
        GROUP BY account_number
        HAVING cnt > 1
    """).fetchall()
    for (num, names, cnt) in rows:
        yield "WARN", f"Duplicate account number '{num}' shared by: {names}"


def check_empty_descriptions(con):
    """Transactions should have descriptions."""
    rows = con.execute("""
        SELECT id, date, description FROM transactions
        WHERE description IS NULL OR TRIM(description) = ''
    """).fetchall()
    for (tid, date, desc) in rows:
        yield "WARN", f"Transaction with empty description ({date}) [id={tid}]"


def check_invalid_dates(con):
    """Transaction dates should be valid ISO format."""
    rows = con.execute("""
        SELECT id, date, description FROM transactions
        WHERE date NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
    """).fetchall()
    for (tid, date, desc) in rows:
        yield "ERROR", f"Invalid date '{date}' on transaction '{desc}' [id={tid}]"


CHECKS = [
    ("Parent-child type mismatches", check_parent_child_type_mismatch),
    ("Orphaned parent references", check_orphaned_parent_refs),
    ("Circular account hierarchy", check_circular_hierarchy),
    ("Unbalanced transactions", check_unbalanced_transactions),
    ("Transactions without enough splits", check_transactions_without_splits),
    ("Splits referencing missing accounts", check_splits_referencing_missing_accounts),
    ("Duplicate account numbers", check_duplicate_account_numbers),
    ("Empty transaction descriptions", check_empty_descriptions),
    ("Invalid transaction dates", check_invalid_dates),
]


def main():
    con = init_db()

    acct_count = con.execute("SELECT count(*) FROM accounts").fetchone()[0]
    tx_count = con.execute("SELECT count(*) FROM transactions").fetchone()[0]
    split_count = con.execute("SELECT count(*) FROM splits").fetchone()[0]
    print(f"Database: {acct_count} accounts, {tx_count} transactions, {split_count} splits\n")

    errors = 0
    warnings = 0

    for check_name, check_fn in CHECKS:
        issues = list(check_fn(con))
        if issues:
            print(f"--- {check_name} ---")
            for level, msg in issues:
                print(f"  {level}: {msg}")
                if level == "ERROR":
                    errors += 1
                else:
                    warnings += 1
            print()

    if errors == 0 and warnings == 0:
        print("All checks passed.")
    else:
        print(f"Found {errors} error(s), {warnings} warning(s).")

    con.close()
    release_lock()
    return 1 if errors > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
