#!/usr/bin/env python3
"""Import GNUCash XML chart of accounts into Pyre database."""

import gzip
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# Allow running as standalone script
sys.path.insert(0, str(Path(__file__).parent.parent))

from pyre.account_utils import slugify
from pyre.db import init_db, release_lock

DEFAULT_GNUCASH_PATH = Path.home() / "Documents" / "Personal.gnucash"

# XML namespaces
ACT = "{http://www.gnucash.org/XML/act}"
CMDTY = "{http://www.gnucash.org/XML/cmdty}"
GNC = "{http://www.gnucash.org/XML/gnc}"

# Map GNUCash account types to Pyre types
GNC_TYPE_MAP = {
    "ASSET": "asset",
    "BANK": "asset",
    "CASH": "asset",
    "CREDIT": "credit_card",
    "EQUITY": "equity",
    "EXPENSE": "expense",
    "INCOME": "income",
    "LIABILITY": "liability",
    "PAYABLE": "accounts_payable",
    # RECEIVABLE would map to accounts_receivable if present
}

# GNUCash system accounts to skip
SKIP_NAMES = {"Imbalance-USD", "Imbalance-XXX", "Orphan-USD"}
SKIP_TYPES = {"ROOT", "TRADING"}

# Top-level GNUCash category accounts to flatten out.
# Pyre's UI already groups by these categories based on account type,
# so importing them creates redundant nesting (e.g. "Assets > Assets").
# Children of these accounts get promoted to top-level.
TOP_LEVEL_CATEGORIES = {"Assets", "Liabilities", "Equity", "Income", "Expenses"}


def parse_gnucash(gnucash_path):
    """Parse GNUCash XML file, return list of account dicts."""
    with gzip.open(gnucash_path, "rb") as f:
        tree = ET.parse(f)
    root = tree.getroot()

    # First pass: find ROOT GUIDs so we can identify top-level category accounts
    root_guids = set()
    for acct in root.iter(f"{GNC}account"):
        atype = acct.find(f"{ACT}type").text
        if atype == "ROOT":
            root_guids.add(acct.find(f"{ACT}id").text)

    # Second pass: collect accounts, skipping top-level categories
    # and re-parenting their children
    flattened_guids = set()  # GUIDs of skipped top-level category accounts
    accounts = []
    for acct in root.iter(f"{GNC}account"):
        name = acct.find(f"{ACT}name").text
        atype = acct.find(f"{ACT}type").text
        guid = acct.find(f"{ACT}id").text

        # Skip root, trading, and system accounts
        if atype in SKIP_TYPES:
            continue
        if name in SKIP_NAMES:
            continue

        parent_el = acct.find(f"{ACT}parent")
        parent_guid = parent_el.text if parent_el is not None else None

        # Skip top-level category accounts (direct children of ROOT with
        # matching names). Their children get promoted to top-level.
        if parent_guid in root_guids and name in TOP_LEVEL_CATEGORIES:
            flattened_guids.add(guid)
            print(f"  Flattening top-level category: {name}")
            continue

        desc_el = acct.find(f"{ACT}description")
        desc = desc_el.text if desc_el is not None else ""

        # Skip template accounts (scheduled transaction placeholders)
        # and non-USD accounts (RUB cash, XXX imbalance, etc.)
        commodity = acct.find(f"{ACT}commodity")
        if commodity is not None:
            cmdty_space = commodity.find(f"{CMDTY}space")
            cmdty_id = commodity.find(f"{CMDTY}id")
            space = cmdty_space.text if cmdty_space is not None else ""
            cid = cmdty_id.text if cmdty_id is not None else ""
            if space == "template":
                continue
            if space == "CURRENCY" and cid not in ("USD", ""):
                print(f"  Skipping non-USD account: {name} ({cid})")
                continue

        our_type = GNC_TYPE_MAP.get(atype)
        if our_type is None:
            print(f"  WARNING: Unknown GNUCash type '{atype}' for '{name}', skipping")
            continue

        # Re-parent children of flattened categories to top-level
        if parent_guid in flattened_guids:
            parent_guid = None

        accounts.append({
            "guid": guid,
            "name": name,
            "type": our_type,
            "parent_guid": parent_guid,
            "description": desc or "",
        })

    # Fix credit cards stored as LIABILITY under "Credit Cards" parent
    guid_to_name = {a["guid"]: a["name"] for a in accounts}
    for acct in accounts:
        if acct["type"] == "liability" and acct["parent_guid"]:
            parent_name = guid_to_name.get(acct["parent_guid"], "")
            if parent_name == "Credit Cards":
                acct["type"] = "credit_card"

    return accounts


def build_ids(accounts):
    """Assign stable slug IDs and resolve parent references."""
    guid_to_acct = {a["guid"]: a for a in accounts}
    valid_guids = set(a["guid"] for a in accounts)

    # Build full path for each account (for prefixed slugs)
    # Parents come before children in GNUCash XML
    guid_to_slug = {}
    slug_counts = {}

    for acct in accounts:
        leaf_slug = slugify(acct["name"])
        parent_guid = acct["parent_guid"]

        # Only prefix if parent is in our valid set (not ROOT)
        if parent_guid and parent_guid in guid_to_slug:
            slug = f"{guid_to_slug[parent_guid]}__{leaf_slug}"
        else:
            slug = leaf_slug

        # Handle duplicates
        if slug in slug_counts:
            slug_counts[slug] += 1
            slug = f"{slug}_{slug_counts[slug]}"
        else:
            slug_counts[slug] = 0

        acct["id"] = slug
        guid_to_slug[acct["guid"]] = slug

    # Resolve parent_id
    for acct in accounts:
        pg = acct["parent_guid"]
        if pg and pg in guid_to_slug:
            acct["parent_id"] = guid_to_slug[pg]
        else:
            acct["parent_id"] = None

    return accounts


def import_accounts(con, accounts):
    """Insert accounts into database in hierarchy order."""
    inserted = set()
    remaining = list(accounts)
    rounds = 0

    while remaining:
        rounds += 1
        if rounds > len(accounts) + 1:
            unresolved = [a["name"] for a in remaining]
            raise RuntimeError(f"Circular or unresolvable hierarchy: {unresolved}")

        batch = []
        still_remaining = []
        for acct in remaining:
            if acct["parent_id"] is None or acct["parent_id"] in inserted:
                batch.append(acct)
            else:
                still_remaining.append(acct)

        for acct in batch:
            con.execute(
                "INSERT INTO accounts (id, name, type, parent_id, description) "
                "VALUES (?, ?, ?, ?, ?)",
                (acct["id"], acct["name"], acct["type"],
                 acct["parent_id"], acct["description"]),
            )
            inserted.add(acct["id"])

        remaining = still_remaining

    con.commit()
    return len(inserted)


def main():
    gnucash_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_GNUCASH_PATH

    if not gnucash_path.exists():
        print(f"ERROR: GNUCash file not found: {gnucash_path}")
        sys.exit(1)

    print(f"Parsing {gnucash_path}...")
    accounts = parse_gnucash(gnucash_path)
    print(f"  Found {len(accounts)} accounts (after filtering)")

    accounts = build_ids(accounts)

    # Count by type
    type_counts = {}
    for acct in accounts:
        type_counts[acct["type"]] = type_counts.get(acct["type"], 0) + 1

    con = init_db()

    # Check if accounts already exist
    existing = con.execute("SELECT count(*) FROM accounts").fetchone()[0]
    if existing > 0:
        print(f"  Database already has {existing} accounts.")
        print("  Drop existing accounts first? (y/n) ", end="")
        answer = input().strip().lower()
        if answer == "y":
            con.execute("DELETE FROM splits")
            con.execute("DELETE FROM transactions")
            con.execute("DELETE FROM accounts")
            con.commit()
            print("  Cleared existing data.")
        else:
            print("  Aborting.")
            con.close()
            release_lock()
            sys.exit(0)

    print("Importing accounts...")
    count = import_accounts(con, accounts)

    print(f"\nImported {count} accounts:")
    for acct_type, cnt in sorted(type_counts.items()):
        print(f"  {acct_type}: {cnt}")

    # Show hierarchy summary
    with_parent = con.execute(
        "SELECT count(*) FROM accounts WHERE parent_id IS NOT NULL"
    ).fetchone()[0]
    print(f"\n  {with_parent} accounts have a parent (hierarchical)")
    print(f"  {count - with_parent} are top-level accounts")

    # Print account IDs for reference
    print("\n=== Account IDs ===")
    rows = con.execute(
        "SELECT id, name, type FROM accounts ORDER BY type, name"
    ).fetchall()
    for row in rows:
        print(f"  {row[0]:60s} {row[1]} ({row[2]})")

    con.close()
    release_lock()
    print("\nDone.")


if __name__ == "__main__":
    main()
