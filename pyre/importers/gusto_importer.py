"""Gusto General Ledger XLSX parser."""

import re
from datetime import datetime
from pathlib import Path

import openpyxl
import yaml

from pyre.importers.journal import JournalEntry, JournalSplit, compute_journal_hash


def detect_gusto_gl(filepath):
    """Return True if the XLSX looks like a Gusto General Ledger export.

    Checks for a 'Basic' sheet whose 4th row contains the expected headers:
    Account Type, Account Description, Debit, Credit.
    """
    try:
        wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    except Exception:
        return False

    try:
        if "Basic" not in wb.sheetnames:
            return False
        ws = wb["Basic"]
        row4_rows = list(ws.iter_rows(min_row=4, max_row=4))
        if not row4_rows:
            return False
        row4 = [cell.value for cell in row4_rows[0]]
        expected = ["Account Type", "Account Description", "Debit", "Credit"]
        return row4 == expected
    finally:
        wb.close()


def load_gusto_config(config_path=None):
    """Load the Gusto account mapping from gusto.yaml.

    Searches for gusto.yaml in the current directory by default.
    Returns the parsed YAML dict (with an 'account_map' key).
    Raises FileNotFoundError if the file is missing.
    """
    if config_path is None:
        config_path = Path("gusto.yaml")
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(
            f"Gusto config not found: {config_path}\n"
            "Run: cp gusto.yaml.sample gusto.yaml  "
            "then edit the account mappings."
        )

    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_gusto_gl(filepath):
    """Parse a Gusto General Ledger XLSX into JournalEntry objects.

    Reads the 'Basic' sheet. Each file produces one JournalEntry
    (one pay period). The check date becomes the transaction date.

    Returns list of JournalEntry (always 0 or 1 element).
    """
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    try:
        ws = wb["Basic"]
        rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()

    if len(rows) < 5:
        return []

    # Row 2 (index 1): period description, e.g. "Ledger for Regular Payroll Jan 1 - Jan 15"
    # Row 3 (index 2): check date, e.g. "Check date: 2026-01-15"
    description = rows[1][0] or ""
    check_date_raw = rows[2][0] or ""

    # Extract the ISO date from "Check date: YYYY-MM-DD"
    m = re.search(r"Check date:\s*(\d{4}-\d{2}-\d{2})", check_date_raw)
    if not m:
        return []
    check_date = m.group(1)

    # Validate the date parses
    try:
        datetime.strptime(check_date, "%Y-%m-%d")
    except ValueError:
        return []

    # Row 4 (index 3) is the header row; data starts at row 5 (index 4)
    splits = []
    for row in rows[4:]:
        account_type = row[0]
        if account_type is None:
            continue  # skip Totals row and blanks

        account_desc = row[1] or ""
        debit = row[2]
        credit = row[3]

        if debit is not None:
            amount_cents = int(round(float(debit) * 100))
        elif credit is not None:
            amount_cents = -int(round(float(credit) * 100))
        else:
            continue

        splits.append(JournalSplit(
            account_name=str(account_type),
            amount_cents=amount_cents,
            description=str(account_desc),
        ))

    if not splits:
        return []

    entry = JournalEntry(
        date=check_date,
        description=str(description),
        splits=splits,
    )
    entry.hash = compute_journal_hash(entry)
    return [entry]


def resolve_gusto_accounts(entries, account_map):
    """Resolve Gusto account types to Pyre account IDs.

    account_map: dict mapping Gusto Account Type strings to Pyre account IDs
                 (from gusto.yaml).

    Returns set of unmapped Gusto account type names.
    """
    unmatched = set()

    for entry in entries:
        for split in entry.splits:
            pyre_id = account_map.get(split.account_name)
            if pyre_id:
                split.account_id = pyre_id
            else:
                unmatched.add(split.account_name)

    return unmatched
