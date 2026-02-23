"""Database operations for import-related tables: payee_rules, import_log, OFX mappings."""

import re
from datetime import datetime

from pyre.formatting import new_id


# -- Payee Rules --

def create_payee_rule(con, pattern, account_id, priority=0, memo_pattern=None,
                      vendor_id=None):
    """Create a new payee rule. Returns the rule ID."""
    rule_id = new_id()
    con.execute(
        "INSERT INTO payee_rules (id, pattern, memo_pattern, account_id, vendor_id, priority, created) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (rule_id, pattern, memo_pattern, account_id, vendor_id, priority,
         datetime.now().isoformat()),
    )
    con.commit()
    return rule_id


def get_payee_rules(con):
    """Fetch all payee rules ordered by priority DESC, memo rules first, pattern length DESC."""
    rows = con.execute(
        "SELECT id, pattern, memo_pattern, account_id, vendor_id, priority, created "
        "FROM payee_rules "
        "ORDER BY priority DESC, (memo_pattern IS NOT NULL) DESC, LENGTH(pattern) DESC"
    ).fetchall()
    return [
        {"id": r[0], "pattern": r[1], "memo_pattern": r[2], "account_id": r[3],
         "vendor_id": r[4], "priority": r[5], "created": r[6]}
        for r in rows
    ]


def update_payee_rule(con, rule_id, pattern, memo_pattern=None, priority=None,
                      vendor_id=None, account_id=None):
    """Update an existing payee rule's fields."""
    fields = ["pattern = ?", "memo_pattern = ?", "vendor_id = ?"]
    params = [pattern, memo_pattern, vendor_id]
    if priority is not None:
        fields.append("priority = ?")
        params.append(priority)
    if account_id is not None:
        fields.append("account_id = ?")
        params.append(account_id)
    params.append(rule_id)
    con.execute(
        f"UPDATE payee_rules SET {', '.join(fields)} WHERE id = ?",
        params,
    )
    con.commit()


def delete_payee_rule(con, rule_id):
    """Delete a payee rule by ID."""
    con.execute("DELETE FROM payee_rules WHERE id = ?", (rule_id,))
    con.commit()


def _pattern_matches(pattern, description):
    """Check if a payee rule pattern matches a description (case-insensitive).

    Patterns containing '*' use wildcard matching (* = any characters).
    Plain patterns use substring matching.
    """
    pat_lower = pattern.lower()
    desc_lower = description.lower()
    if "*" in pat_lower:
        # Convert glob-style * to regex .* and search within the description
        parts = [re.escape(p) for p in pat_lower.split("*")]
        regex = ".*".join(parts)
        return re.search(regex, desc_lower) is not None
    return pat_lower in desc_lower


def match_payee(con, description, memo=""):
    """Find the best matching payee rule for a description (and optionally memo).

    Returns dict {"account_id": ..., "vendor_id": ...} or None.
    Patterns with '*' use wildcard matching;
    plain patterns use case-insensitive substring matching.
    When a rule has a memo_pattern, both description AND memo must match.
    Ties broken by: highest priority first, then longest pattern.
    """
    rules = get_payee_rules(con)  # already sorted by priority DESC, length DESC
    for rule in rules:
        if not _pattern_matches(rule["pattern"], description):
            continue
        if rule["memo_pattern"] and not _pattern_matches(rule["memo_pattern"], memo):
            continue
        return {"account_id": rule["account_id"], "vendor_id": rule["vendor_id"]}
    return None


# -- Import Log --

def log_import(con, source_file, fitid, hash_val, tx_id, status, account_id=None):
    """Log an imported transaction. Returns the log entry ID."""
    entry_id = new_id()
    con.execute(
        "INSERT INTO import_log (id, source_file, fitid, hash, tx_id, status, imported_at, account_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (entry_id, source_file, fitid, hash_val, tx_id, status, datetime.now().isoformat(), account_id),
    )
    con.commit()
    return entry_id


def is_already_imported(con, fitid, hash_val, account_id=None):
    """Check if a transaction has already been imported (by fitid or hash), scoped to account."""
    if fitid:
        if account_id:
            row = con.execute(
                "SELECT 1 FROM import_log WHERE fitid = ? AND account_id = ?", (fitid, account_id)
            ).fetchone()
        else:
            row = con.execute(
                "SELECT 1 FROM import_log WHERE fitid = ?", (fitid,)
            ).fetchone()
        if row:
            return True
    if hash_val:
        if account_id:
            row = con.execute(
                "SELECT 1 FROM import_log WHERE hash = ? AND account_id = ?", (hash_val, account_id)
            ).fetchone()
        else:
            row = con.execute(
                "SELECT 1 FROM import_log WHERE hash = ?", (hash_val,)
            ).fetchone()
        if row:
            return True
    return False


# -- OFX Account Mapping --

def set_account_ofx_mapping(con, account_id, bankid, acctid):
    """Set OFX routing/account numbers on an account for auto-detection."""
    con.execute(
        "UPDATE accounts SET ofx_bankid = ?, ofx_acctid = ? WHERE id = ?",
        (bankid, acctid, account_id),
    )
    con.commit()


def find_account_by_ofx(con, bankid, acctid):
    """Find an account by OFX bank ID and account ID. Returns dict or None."""
    if bankid:
        row = con.execute(
            "SELECT id, name, type FROM accounts WHERE ofx_bankid = ? AND ofx_acctid = ?",
            (bankid, acctid),
        ).fetchone()
    else:
        row = con.execute(
            "SELECT id, name, type FROM accounts WHERE ofx_acctid = ?",
            (acctid,),
        ).fetchone()
    if row:
        return {"id": row[0], "name": row[1], "type": row[2]}
    return None
