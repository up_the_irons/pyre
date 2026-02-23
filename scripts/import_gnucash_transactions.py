#!/usr/bin/env python3
"""Import recent transactions from GNUCash XML into Pyre database."""

import gzip
import logging
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

# Allow running as standalone script
sys.path.insert(0, str(Path(__file__).parent.parent))

from pyre.db import DB_PATH, init_db, release_lock
from pyre.formatting import new_id

log = logging.getLogger(__name__)

DEFAULT_GNUCASH_PATH = Path.home() / "Documents" / "Personal.gnucash"
DEFAULT_MONTHS = 3

# XML namespaces
ACT = "{http://www.gnucash.org/XML/act}"
GNC = "{http://www.gnucash.org/XML/gnc}"
TRN = "{http://www.gnucash.org/XML/trn}"
SPLIT = "{http://www.gnucash.org/XML/split}"
TS = "{http://www.gnucash.org/XML/ts}"
CMDTY = "{http://www.gnucash.org/XML/cmdty}"

SKIP_TYPES = {"ROOT", "TRADING"}
SKIP_NAMES = {"Imbalance-USD", "Imbalance-XXX"}

# GNUCash system accounts to redirect to a Pyre account instead of skipping
REDIRECT_ACCOUNTS = {
    "Orphan-USD": "opening_balances",
}


def rational_to_cents(value_str):
    """Convert GNUCash rational number (e.g. '2050/100') to integer cents."""
    num, den = value_str.split("/")
    num, den = int(num), int(den)
    if den == 100:
        return num
    # Scale to cents
    return round(num * 100 / den)


GNC_MEMO_PREFIX = "gnc:"

# Map GNUCash reconcile states to Pyre: n=not, c=cleared, y->r=reconciled
GNC_RECONCILE_MAP = {"n": "n", "c": "c", "y": "r"}


def build_guid_to_slug(gnucash_path, con):
    """Build a mapping from GNUCash account GUIDs to Pyre account slugs.

    Matches by account name since GUIDs are not preserved during import.
    """
    with gzip.open(gnucash_path, "rb") as f:
        tree = ET.parse(f)
    root = tree.getroot()

    # Get all GNUCash accounts with their GUIDs
    all_guid_names = {}  # every account, for logging unmapped references
    gnc_accounts = []
    guid_to_name = {}
    guid_to_parent = {}
    for acct in root.iter(f"{GNC}account"):
        name = acct.find(f"{ACT}name").text
        atype = acct.find(f"{ACT}type").text
        guid = acct.find(f"{ACT}id").text
        parent_el = acct.find(f"{ACT}parent")
        parent_guid = parent_el.text if parent_el is not None else None

        all_guid_names[guid] = name

        # Skip template accounts
        commodity = acct.find(f"{ACT}commodity")
        if commodity is not None:
            s = commodity.find(f"{CMDTY}space")
            if s is not None and s.text == "template":
                continue

        if atype in SKIP_TYPES or name in SKIP_NAMES:
            continue

        guid_to_name[guid] = name
        guid_to_parent[guid] = parent_guid
        gnc_accounts.append(guid)

    # Top-level GNUCash categories that were flattened during account import
    TOP_LEVEL_CATEGORIES = {"Assets", "Liabilities", "Equity", "Income", "Expenses"}

    # Build full path for a GNUCash account (strip flattened top-level categories)
    def gnc_full_path(guid):
        parts = []
        current = guid
        while current and current in guid_to_name:
            parts.append(guid_to_name[current])
            current = guid_to_parent.get(current)
        parts.reverse()
        # Strip top-level categories that were flattened during import
        while parts and parts[0] in TOP_LEVEL_CATEGORIES:
            parts = parts[1:]
        return parts

    # Build full path for Pyre accounts (walk parent_id)
    pyre_by_id = {}
    pyre_parents = {}
    for row in con.execute("SELECT id, name, parent_id FROM accounts").fetchall():
        pyre_by_id[row[0]] = row[1]
        pyre_parents[row[0]] = row[2]

    def pyre_full_path(acct_id):
        parts = []
        current = acct_id
        while current and current in pyre_by_id:
            parts.append(pyre_by_id[current])
            current = pyre_parents.get(current)
        parts.reverse()
        return parts

    # Build path-to-slug lookup for Pyre
    pyre_path_to_slug = {}
    for acct_id in pyre_by_id:
        path_key = ":".join(pyre_full_path(acct_id))
        pyre_path_to_slug[path_key] = acct_id

    # Also keep name-only lookup as fallback for unique names
    pyre_by_name = {}
    pyre_name_dupes = set()
    for acct_id, name in pyre_by_id.items():
        if name in pyre_by_name:
            pyre_name_dupes.add(name)
        pyre_by_name[name] = acct_id

    # Match GNUCash GUIDs to Pyre slugs by full path, then by name
    guid_to_slug = {}
    unmatched = []
    for guid in gnc_accounts:
        name = guid_to_name[guid]
        path_key = ":".join(gnc_full_path(guid))
        if path_key in pyre_path_to_slug:
            guid_to_slug[guid] = pyre_path_to_slug[path_key]
        elif name in pyre_by_name and name not in pyre_name_dupes:
            guid_to_slug[guid] = pyre_by_name[name]
        elif name not in REDIRECT_ACCOUNTS:
            unmatched.append(f"{path_key} ({name})")

    # Redirect system accounts (e.g. Orphan-USD -> opening_balances)
    pyre_slugs = set(pyre_by_id.keys())
    for acct in root.iter(f"{GNC}account"):
        name = acct.find(f"{ACT}name").text
        if name in REDIRECT_ACCOUNTS:
            guid = acct.find(f"{ACT}id").text
            target = REDIRECT_ACCOUNTS[name]
            if target in pyre_slugs:
                guid_to_slug[guid] = target
            else:
                unmatched.append(f"{name} -> {target} (target not found)")

    if unmatched:
        print(f"  WARNING: {len(unmatched)} GNUCash accounts not found in Pyre:")
        for name in unmatched[:10]:
            print(f"    - {name}")
        if len(unmatched) > 10:
            print(f"    ... and {len(unmatched) - 10} more")

    return guid_to_slug, all_guid_names, root


def get_imported_gnc_guids(con):
    """Get GNUCash GUIDs already imported (stored in transaction memo)."""
    rows = con.execute(
        "SELECT memo FROM transactions WHERE memo LIKE ?",
        (GNC_MEMO_PREFIX + "%",),
    ).fetchall()
    return {row[0][len(GNC_MEMO_PREFIX):] for row in rows}


def import_transactions(con, root, guid_to_slug, all_guid_names, cutoff_date):
    """Import transactions from GNUCash XML into Pyre."""
    existing_guids = get_imported_gnc_guids(con)
    imported = 0
    skipped = 0
    dupes = 0

    for trn in root.iter(f"{GNC}transaction"):
        gnc_guid = trn.find(f"{TRN}id").text

        # Dedup: skip if this GNUCash transaction was already imported
        if gnc_guid in existing_guids:
            dupes += 1
            continue

        date_el = trn.find(f"{TRN}date-posted/{TS}date")
        date_str = date_el.text[:10]
        date = datetime.strptime(date_str, "%Y-%m-%d")
        if date < cutoff_date:
            continue

        desc = trn.find(f"{TRN}description").text or ""

        # Parse splits
        splits = []
        skip_tx = False
        for sp in trn.findall(f"{TRN}splits/{TRN}split"):
            acct_guid = sp.find(f"{SPLIT}account").text
            value = sp.find(f"{SPLIT}value").text
            memo_el = sp.find(f"{SPLIT}memo")
            memo = memo_el.text if memo_el is not None else ""
            recon_el = sp.find(f"{SPLIT}reconciled-state")
            recon = GNC_RECONCILE_MAP.get(
                recon_el.text if recon_el is not None else "n", "n",
            )

            amount_cents = rational_to_cents(value)

            if acct_guid not in guid_to_slug:
                acct_name = all_guid_names.get(acct_guid, acct_guid)
                if amount_cents == 0:
                    # Zero-amount splits to unmapped accounts (e.g. Orphan-USD)
                    # are safe to drop
                    log.info(
                        "Dropping $0 split to unmapped account '%s' in '%s' (%s)",
                        acct_name, desc, date_str,
                    )
                    continue
                log.warning(
                    "Skipping '%s' (%s): unmapped account '%s' (value=%s)",
                    desc, date_str, acct_name, value,
                )
                skip_tx = True
                break

            splits.append((guid_to_slug[acct_guid], amount_cents, memo, recon))

        if skip_tx:
            skipped += 1
            continue

        # Verify balance
        total = sum(s[1] for s in splits)
        if total != 0:
            print(f"  WARNING: Unbalanced transaction '{desc}' on {date_str} "
                  f"(off by {total} cents), skipping")
            skipped += 1
            continue

        # Insert transaction with GNUCash GUID in memo for dedup
        tx_id = new_id()
        con.execute(
            "INSERT INTO transactions (id, date, description, memo) "
            "VALUES (?, ?, ?, ?)",
            (tx_id, date_str, desc, GNC_MEMO_PREFIX + gnc_guid),
        )
        for acct_id, amount, memo, recon in splits:
            con.execute(
                "INSERT INTO splits (id, tx_id, account_id, amount, description, reconcile) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (new_id(), tx_id, acct_id, amount, memo, recon),
            )
        imported += 1

    con.commit()

    if skipped:
        print(f"  Skipped {skipped} transactions referencing unmapped accounts")
    if dupes:
        print(f"  Skipped {dupes} duplicate transactions (already in DB)")

    return imported, skipped


def main():
    gnucash_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_GNUCASH_PATH
    months = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_MONTHS

    if not gnucash_path.exists():
        print(f"ERROR: GNUCash file not found: {gnucash_path}")
        sys.exit(1)

    cutoff = datetime.now() - timedelta(days=months * 30)
    print(f"Importing transactions from {gnucash_path}")
    print(f"  Since: {cutoff.strftime('%Y-%m-%d')} (~{months} months)")

    con = init_db()

    # Log to the pyre.log file next to the database
    log_path = DB_PATH.with_name("pyre.log")
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    # Check for existing transactions
    existing = con.execute("SELECT count(*) FROM transactions").fetchone()[0]
    if existing > 0:
        print(f"  Database already has {existing} transactions.")
        print("  Continue and add more? (y/n) ", end="")
        answer = input().strip().lower()
        if answer != "y":
            print("  Aborting.")
            con.close()
            release_lock()
            sys.exit(0)

    print("Building account mapping...")
    guid_to_slug, all_guid_names, root = build_guid_to_slug(gnucash_path, con)
    print(f"  Mapped {len(guid_to_slug)} accounts")

    print("Importing transactions...")
    imported, skipped = import_transactions(
        con, root, guid_to_slug, all_guid_names, cutoff,
    )

    print(f"\nImported {imported} transactions ({skipped} skipped)")

    # Show date range
    row = con.execute(
        "SELECT min(date), max(date), count(*) FROM transactions"
    ).fetchone()
    print(f"  Date range: {row[0]} to {row[1]}")
    print(f"  Total transactions in DB: {row[2]}")

    con.close()
    release_lock()
    print("\nDone.")


if __name__ == "__main__":
    main()
