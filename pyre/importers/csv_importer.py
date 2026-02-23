"""CSV file parser with bank-specific profile detection."""

import csv
import hashlib
from datetime import datetime

from pyre.importers import ImportedTxn


BANK_PROFILES = {
    "wells_fargo": {
        "date": "Date",
        "desc": "Description",
        "debit": "Debit",
        "credit": "Credit",
        "date_fmt": "%m/%d/%Y",
    },
    "capital_one_cc": {
        "date": "Transaction Date",
        "desc": "Description",
        "debit": "Debit",
        "credit": "Credit",
        "date_fmt": "%Y-%m-%d",
    },
    "us_bank": {
        "date": "Date",
        "desc": "Description",
        "amount": "Amount",
        "date_fmt": "%Y-%m-%d",
    },
    "brex_cc": {
        "date": "Posted Date",
        "desc": "Statement Descriptor",
        "desc_fallback": "Merchant Name",
        "amount": "Amount",
        "date_fmt": "%m/%d/%Y",
        "negate": True,
        "memo_col": "Memo",
        "fitid_col": "Id",
    },
    "brex_cash": {
        "date": "Date",
        "desc": "To/From",
        "amount": "Amount",
        "date_fmt": "%m/%d/%Y",
        "memo_col": "Memo",
        "skip_status": "Canceled",
    },
}

# Map header sets to profile keys for auto-detection
_HEADER_SIGNATURES = {
    frozenset({"Date", "Description", "Debit", "Credit"}): None,  # ambiguous, need more
    frozenset({"Transaction Date", "Description", "Debit", "Credit"}): "capital_one_cc",
}


def _compute_hash(date_str, description, amount_cents):
    """Compute a deterministic hash for CSV dedup."""
    raw = f"{date_str}|{description}|{amount_cents}"
    return hashlib.sha256(raw.encode()).hexdigest()


def detect_bank_profile(filepath):
    """Sniff CSV headers and return the matching profile key, or None."""
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        try:
            headers = next(reader)
        except StopIteration:
            return None

    headers = [h.strip() for h in headers]
    header_set = set(headers)

    # Brex CC: "Brex Category" is unique to Brex credit card exports
    if "Brex Category" in header_set:
        return "brex_cc"

    # Brex Cash: "To/From" is unique to Brex cash account exports
    if "To/From" in header_set and "Method" in header_set:
        return "brex_cash"

    # Capital One CC has a unique "Transaction Date" header
    if "Transaction Date" in header_set:
        return "capital_one_cc"

    # US Bank uses a single "Amount" column
    if "Amount" in header_set and "Debit" not in header_set:
        return "us_bank"

    # Wells Fargo uses Date + Debit + Credit (MM/DD/YYYY format)
    if "Date" in header_set and "Debit" in header_set and "Credit" in header_set:
        # Peek at first data row to check date format
        with open(filepath, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                date_val = row.get("Date", "")
                if "/" in date_val:
                    return "wells_fargo"
                return "wells_fargo"  # default if Date+Debit+Credit
        return "wells_fargo"

    return None


def parse_csv(filepath, profile_key):
    """Parse a CSV file using the specified bank profile.

    Returns list[ImportedTxn].
    """
    profile = BANK_PROFILES[profile_key]
    transactions = []

    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Skip rows with a particular status (e.g. Brex Cash "Canceled")
            skip_status = profile.get("skip_status")
            if skip_status and row.get("Status", "").strip() == skip_status:
                continue

            # Parse date
            date_raw = row[profile["date"]].strip()
            if not date_raw:
                continue
            dt = datetime.strptime(date_raw, profile["date_fmt"])
            date_iso = dt.strftime("%Y-%m-%d")

            # Parse description (with optional fallback column)
            description = row[profile["desc"]].strip()
            if not description and "desc_fallback" in profile:
                description = row[profile["desc_fallback"]].strip()

            # Parse memo (optional column)
            memo = ""
            if "memo_col" in profile:
                memo = row.get(profile["memo_col"], "").strip()

            # Parse amount
            if "amount" in profile:
                # Single amount column: negative = debit, positive = credit
                amt_str = row[profile["amount"]].strip().replace(",", "")
                if not amt_str:
                    continue
                amount_cents = int(round(float(amt_str) * 100))
            else:
                # Separate debit/credit columns
                debit_str = row[profile["debit"]].strip().replace(",", "")
                credit_str = row[profile["credit"]].strip().replace(",", "")
                if debit_str:
                    amount_cents = -abs(int(round(float(debit_str) * 100)))
                elif credit_str:
                    amount_cents = abs(int(round(float(credit_str) * 100)))
                else:
                    continue

            # Negate for profiles where CSV sign is opposite bank-statement convention
            if profile.get("negate"):
                amount_cents = -amount_cents

            # Use CSV-provided unique ID for dedup if available
            fitid = None
            if "fitid_col" in profile:
                fitid = row.get(profile["fitid_col"], "").strip() or None

            tx_hash = _compute_hash(date_iso, description, amount_cents)

            txn_type = "CREDIT" if amount_cents > 0 else "DEBIT"

            transactions.append(ImportedTxn(
                date=date_iso,
                description=description,
                amount_cents=amount_cents,
                fitid=fitid,
                memo=memo,
                txn_type=txn_type,
                hash=tx_hash,
            ))

    return transactions
