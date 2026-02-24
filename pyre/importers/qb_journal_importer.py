"""QuickBooks journal entry CSV parser."""

import csv
import re
from datetime import datetime

from pyre.importers.journal import (
    JournalEntry,
    JournalSplit,
    compute_journal_hash,
)


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
        entry.hash = compute_journal_hash(entry)
        result.append(entry)

    return result




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
