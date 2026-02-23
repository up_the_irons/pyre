"""Bank transaction import package."""

from dataclasses import dataclass


@dataclass
class ImportedTxn:
    """A single transaction parsed from a bank file."""
    date: str           # ISO YYYY-MM-DD
    description: str
    amount_cents: int   # bank-statement sign (positive = money in, negative = money out)
    fitid: str | None   # OFX unique ID (None for CSV)
    memo: str
    txn_type: str       # DEBIT, CREDIT, CHECK, DEP, etc.
    hash: str | None    # computed for CSV dedup
