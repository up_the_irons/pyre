"""Transaction matching algorithm for bank imports."""

from dataclasses import dataclass

from pyre.importers import ImportedTxn
from pyre.importers.models import is_already_imported, match_payee


@dataclass
class MatchResult:
    """Result of matching an imported transaction against the ledger."""
    imported_txn: ImportedTxn
    state: str                          # "MATCH", "AUTO", "NEW", "SKIP"
    matched_tx_id: str | None           # for MATCH
    matched_tx_date: str | None
    matched_tx_desc: str | None
    suggested_account_id: str | None    # for AUTO (from payee rule)
    suggested_account_name: str | None
    suggested_vendor_id: str | None     # for AUTO (from payee rule)
    suggested_vendor_name: str | None
    confidence: float                   # 0.0-1.0


def _token_overlap(a, b):
    """Compute Jaccard-like token overlap between two strings."""
    tokens_a = set(a.lower().split())
    tokens_b = set(b.lower().split())
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def match_transactions(con, imported, bank_account_id):
    """Match a list of ImportedTxn against existing ledger entries.

    Returns list[MatchResult] in the same order as imported.
    """
    # Pre-fetch import_log tx_ids for THIS account to exclude from matching.
    # Only exclude transactions linked from the same bank account -- a transfer
    # imported via the other side should still be matchable.
    already_linked = set()
    for row in con.execute(
        "SELECT tx_id FROM import_log WHERE tx_id IS NOT NULL AND account_id = ?",
        (bank_account_id,),
    ).fetchall():
        already_linked.add(row[0])

    # Pre-fetch account and vendor names for payee rule results
    account_names = {}
    for row in con.execute("SELECT id, name FROM accounts").fetchall():
        account_names[row[0]] = row[1]
    vendor_names = {}
    for row in con.execute("SELECT id, name FROM vendors").fetchall():
        vendor_names[row[0]] = row[1]

    results = []
    used_tx_ids = set()  # prevent double-matching

    for txn in imported:
        # Step 1: Dedup check
        if is_already_imported(con, txn.fitid, txn.hash, bank_account_id):
            results.append(MatchResult(
                imported_txn=txn,
                state="SKIP",
                matched_tx_id=None,
                matched_tx_date=None,
                matched_tx_desc=None,
                suggested_account_id=None,
                suggested_account_name=None,
                suggested_vendor_id=None,
                suggested_vendor_name=None,
                confidence=1.0,
            ))
            continue

        # Step 2: Try to match existing transaction
        # Look for splits with exact amount on the bank account within +/- 5 days
        candidates = con.execute("""
            SELECT s.tx_id, t.date, t.description
            FROM splits s
            JOIN transactions t ON t.id = s.tx_id
            WHERE s.account_id = ?
              AND s.amount = ?
              AND t.date BETWEEN date(?, '-5 days') AND date(?, '+5 days')
            ORDER BY ABS(julianday(t.date) - julianday(?))
        """, (bank_account_id, txn.amount_cents, txn.date, txn.date, txn.date)).fetchall()

        best_match = None
        best_score = 0.0

        for tx_id, tx_date, tx_desc in candidates:
            if tx_id in already_linked or tx_id in used_tx_ids:
                continue

            # Score: date proximity (1.0 for exact, decays 0.06/day)
            day_diff = abs(_date_diff_days(txn.date, tx_date))
            date_score = max(0.0, 1.0 - day_diff * 0.06)

            # Bonus for description overlap
            desc_bonus = _token_overlap(txn.description, tx_desc) * 0.3

            score = date_score + desc_bonus

            if score > best_score:
                best_score = score
                best_match = (tx_id, tx_date, tx_desc)

        if best_match:
            used_tx_ids.add(best_match[0])
            results.append(MatchResult(
                imported_txn=txn,
                state="MATCH",
                matched_tx_id=best_match[0],
                matched_tx_date=best_match[1],
                matched_tx_desc=best_match[2],
                suggested_account_id=None,
                suggested_account_name=None,
                suggested_vendor_id=None,
                suggested_vendor_name=None,
                confidence=min(best_score, 1.0),
            ))
            continue

        # Step 3: Try payee rules
        rule_match = match_payee(con, txn.description, memo=txn.memo)
        if rule_match:
            rule_account_id = rule_match["account_id"]
            rule_vendor_id = rule_match["vendor_id"]
            results.append(MatchResult(
                imported_txn=txn,
                state="AUTO",
                matched_tx_id=None,
                matched_tx_date=None,
                matched_tx_desc=None,
                suggested_account_id=rule_account_id,
                suggested_account_name=account_names.get(rule_account_id, "?"),
                suggested_vendor_id=rule_vendor_id,
                suggested_vendor_name=vendor_names.get(rule_vendor_id, "") if rule_vendor_id else None,
                confidence=0.8,
            ))
            continue

        # Step 4: New -- no match, no rule
        results.append(MatchResult(
            imported_txn=txn,
            state="NEW",
            matched_tx_id=None,
            matched_tx_date=None,
            matched_tx_desc=None,
            suggested_account_id=None,
            suggested_account_name=None,
            suggested_vendor_id=None,
            suggested_vendor_name=None,
            confidence=0.0,
        ))

    return results


def _date_diff_days(date_a, date_b):
    """Compute absolute day difference between two ISO date strings."""
    from datetime import date
    a = date.fromisoformat(date_a)
    b = date.fromisoformat(date_b)
    return abs((a - b).days)
