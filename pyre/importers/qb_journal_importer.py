"""QuickBooks journal entry CSV parser."""

import csv
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime

from pyre.account_models import get_all_accounts


@dataclass
class JournalSplit:
    """A single split within a journal entry."""
    account_name: str       # QB path like "Sales:Hosting:VPS"
    amount_cents: int       # positive = debit, negative = credit
    account_id: str | None = None  # resolved Pyre account ID


@dataclass
class JournalEntry:
    """A complete journal entry with multiple splits."""
    date: str               # ISO YYYY-MM-DD
    description: str        # derived from debit account(s)
    splits: list[JournalSplit] = field(default_factory=list)
    hash: str | None = None  # SHA-256 for dedup


def _compute_journal_hash(entry):
    """Compute a deterministic SHA-256 hash for a journal entry.

    Hash is based on date + sorted account_name:amount_cents pairs.
    Uses raw QB account names (pre-resolution) so the hash is file-content-based.
    """
    parts = sorted(f"{s.account_name}:{s.amount_cents}" for s in entry.splits)
    raw = entry.date + "|" + "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()


def _clean_name(name):
    """Clean QB account name (e.g. 'First National **1234' -> 'First National - 1234')."""
    return re.sub(r"\s*\*\*(\d+)", r" - \1", name)


def detect_qb_journal(filepath):
    """Return True if the CSV is a QuickBooks journal entry export."""
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        try:
            headers = [h.strip() for h in next(reader)]
        except StopIteration:
            return False
    return ("JournalNo" in headers and "JournalDate" in headers
            and "AccountName" in headers)


def parse_qb_journals(filepath):
    """Parse QuickBooks journal entry CSV into JournalEntry objects.

    Rows are grouped by JournalNo. Each group becomes one JournalEntry
    with multiple splits. The date comes from JournalDate (present on
    one row per group). The description is derived from the debit
    account name(s).

    Returns list of JournalEntry.
    """
    entries_by_no = {}  # JournalNo -> JournalEntry
    entry_order = []    # preserve insertion order

    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            journal_no = row.get("JournalNo", "").strip()
            if not journal_no:
                continue

            account_name = row.get("AccountName", "").strip()
            if not account_name:
                continue

            # Debits are positive, Credits are negative
            debit_str = row.get("Debits", "").strip().replace(",", "")
            credit_str = row.get("Credits", "").strip().replace(",", "")

            if debit_str:
                amount_cents = int(round(float(debit_str) * 100))
            elif credit_str:
                amount_cents = -int(round(float(credit_str) * 100))
            else:
                continue

            date_str = row.get("JournalDate", "").strip()

            if journal_no not in entries_by_no:
                entries_by_no[journal_no] = JournalEntry(
                    date="", description="", splits=[],
                )
                entry_order.append(journal_no)

            entry = entries_by_no[journal_no]

            if date_str and not entry.date:
                dt = datetime.strptime(date_str, "%m/%d/%Y")
                entry.date = dt.strftime("%Y-%m-%d")

            entry.splits.append(JournalSplit(
                account_name=account_name,
                amount_cents=amount_cents,
            ))

    # Build descriptions from debit account names
    result = []
    for no in entry_order:
        entry = entries_by_no[no]
        if not entry.date:
            continue
        debit_names = [s.account_name for s in entry.splits if s.amount_cents > 0]
        entry.description = ", ".join(debit_names) if debit_names else no
        entry.hash = _compute_journal_hash(entry)
        result.append(entry)

    return result


def build_qb_account_map(con):
    """Build mapping from QB colon-delimited account paths to Pyre account IDs.

    Returns dict mapping QB-style paths (e.g. "Sales:Hosting:VPS") to
    Pyre account IDs.
    """
    accounts = get_all_accounts(con)
    by_id = {a["id"]: a for a in accounts}

    path_to_id = {}
    for a in accounts:
        parts = []
        current = a["id"]
        while current:
            acct = by_id.get(current)
            if not acct:
                break
            parts.append(acct["name"])
            current = acct["parent_id"]
        parts.reverse()
        path = ":".join(parts)
        path_to_id[path] = a["id"]

    return path_to_id


def resolve_accounts(entries, account_map):
    """Resolve QB account names to Pyre IDs for all journal entries.

    Cleans each component of the QB account path (handling ** patterns)
    and looks up the cleaned path in the account map.

    Returns set of unmatched QB account names.
    """
    unmatched = set()

    for entry in entries:
        for split in entry.splits:
            parts = split.account_name.split(":")
            cleaned = ":".join(_clean_name(p.strip()) for p in parts)

            if cleaned in account_map:
                split.account_id = account_map[cleaned]
            else:
                unmatched.add(split.account_name)

    return unmatched
