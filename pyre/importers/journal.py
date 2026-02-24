"""Shared journal entry data model for multi-split imports."""

import hashlib
from dataclasses import dataclass, field

from pyre.account_models import get_all_accounts


@dataclass
class JournalSplit:
    """A single split within a journal entry."""
    account_name: str       # source-specific key (QB path, Gusto account type, etc.)
    amount_cents: int       # positive = debit, negative = credit
    account_id: str | None = None  # resolved Pyre account ID
    description: str = ""   # per-split description (e.g. "Social Security - employer tax")


@dataclass
class JournalEntry:
    """A complete journal entry with multiple splits."""
    date: str               # ISO YYYY-MM-DD
    description: str        # human-readable summary
    splits: list[JournalSplit] = field(default_factory=list)
    hash: str | None = None  # SHA-256 for dedup


def compute_journal_hash(entry):
    """Compute a deterministic SHA-256 hash for a journal entry.

    Hash is based on date + sorted account_name:amount_cents pairs.
    Uses raw account names (pre-resolution) so the hash is file-content-based.
    """
    parts = sorted(f"{s.account_name}:{s.amount_cents}" for s in entry.splits)
    raw = entry.date + "|" + "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()


def build_account_path_map(con):
    """Build mapping from colon-delimited account paths to Pyre account IDs.

    Returns dict mapping paths (e.g. "Expenses:Payroll:Wages")
    to Pyre account IDs.
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
