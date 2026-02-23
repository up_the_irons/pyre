#!/usr/bin/env python3
"""Import QuickBooks Chart of Accounts CSV into Pyre database."""

import csv
import re
import sys
from pathlib import Path

# Allow running as standalone script
sys.path.insert(0, str(Path(__file__).parent.parent))

from pyre.account_utils import slugify
from pyre.db import init_db, release_lock

CSV_PATH = Path(__file__).parent.parent / "chart-of-accounts.csv"

# Map QuickBooks type names to our snake_case types
QB_TYPE_MAP = {
    "Bank": "asset",
    "Accounts receivable (A/R)": "accounts_receivable",
    "Other Current Assets": "other_current_asset",
    "Fixed Assets": "fixed_asset",
    "Other Assets": "other_asset",
    "Accounts payable (A/P)": "accounts_payable",
    "Credit Card": "credit_card",
    "Other Current Liabilities": "other_current_liability",
    "Long Term Liabilities": "long_term_liability",
    "Equity": "equity",
    "Income": "income",
    "Other Income": "other_income",
    "Cost of Goods Sold": "cost_of_goods_sold",
    "Expenses": "expense",
    "Other Expense": "other_expense",
}


def clean_name(name):
    """Clean up QB account names for display.

    e.g. "First National **1234" -> "First National - 1234"
         "Main Street **5678" -> "Main Street - 5678"
    """
    return re.sub(r"\s*\*\*(\d+)", r" - \1", name)


def parse_csv(csv_path):
    """Parse QB Chart of Accounts CSV, return list of account dicts."""
    accounts = []

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)

    # Find header row (starts with "Account #" or "Full name")
    header_idx = None
    for i, row in enumerate(rows):
        if row and row[0].strip() in ("Account #", "Full name"):
            header_idx = i
            break

    if header_idx is None:
        raise ValueError("Could not find header row in CSV")

    headers = [h.strip() for h in rows[header_idx]]

    for row in rows[header_idx + 1:]:
        # Skip empty rows, TOTAL row, timestamp rows
        if not row or not any(cell.strip() for cell in row):
            continue
        if row[0].strip().upper() == "TOTAL":
            continue
        # Skip timestamp footer lines
        first_cell = row[0].strip().strip('"')
        if first_cell and ("AM GMT" in first_cell or "PM GMT" in first_cell
                          or "AM GMTZ" in first_cell or "PM GMTZ" in first_cell):
            continue

        # Map columns
        data = {}
        for j, header in enumerate(headers):
            data[header] = row[j].strip() if j < len(row) else ""

        full_name = data.get("Full name", "")
        qb_type = data.get("Type", "")
        if not full_name or not qb_type:
            continue

        our_type = QB_TYPE_MAP.get(qb_type)
        if our_type is None:
            print(f"WARNING: Unknown QB type '{qb_type}' for '{full_name}', skipping")
            continue

        # Parse hierarchy from colon-delimited full name
        parts = [p.strip() for p in full_name.split(":")]
        name = clean_name(parts[-1])  # leaf name, cleaned for display

        # Build parent full name for hierarchy lookup
        parent_full_name = ":".join(parts[:-1]) if len(parts) > 1 else None

        account_number = data.get("Account #", "").strip() or None
        description = data.get("Description", "").strip()

        accounts.append({
            "full_name": full_name,
            "name": name,
            "type": our_type,
            "parent_full_name": parent_full_name,
            "account_number": account_number,
            "description": description,
        })

    return accounts


def build_ids(accounts):
    """Assign stable slug IDs and resolve parent_id references."""
    # Map full_name -> slug ID
    id_map = {}

    # First pass: resolve parent IDs and generate prefixed slugs
    # Parents appear before children in the QuickBooks export, so we can
    # look up the parent slug when processing a child.
    slug_counts = {}
    for acct in accounts:
        leaf_slug = slugify(acct["name"])
        parent_full = acct["parent_full_name"]
        if parent_full and parent_full in id_map:
            slug = f"{id_map[parent_full]}__{leaf_slug}"
        else:
            slug = leaf_slug

        if slug in slug_counts:
            slug_counts[slug] += 1
            slug = f"{slug}_{slug_counts[slug]}"
        else:
            slug_counts[slug] = 0

        acct["id"] = slug
        id_map[acct["full_name"]] = slug

    # Second pass: resolve parent IDs
    for acct in accounts:
        if acct["parent_full_name"] and acct["parent_full_name"] in id_map:
            acct["parent_id"] = id_map[acct["parent_full_name"]]
        else:
            acct["parent_id"] = None

    return accounts


def import_accounts(con, accounts):
    """Insert accounts into database in hierarchy order (parents first)."""
    # Topological sort: insert accounts with no parent first, then children
    inserted = set()
    remaining = list(accounts)
    rounds = 0

    while remaining:
        rounds += 1
        if rounds > len(accounts) + 1:
            unresolved = [a["full_name"] for a in remaining]
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
                "INSERT INTO accounts (id, account_number, name, type, parent_id, description) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (acct["id"], acct["account_number"], acct["name"],
                 acct["type"], acct["parent_id"], acct["description"]),
            )
            inserted.add(acct["id"])

        remaining = still_remaining

    con.commit()
    return len(inserted)


def main():
    csv_path = CSV_PATH
    if len(sys.argv) > 1:
        csv_path = Path(sys.argv[1])

    if not csv_path.exists():
        print(f"ERROR: CSV file not found: {csv_path}")
        sys.exit(1)

    print(f"Parsing {csv_path}...")
    accounts = parse_csv(csv_path)
    print(f"  Found {len(accounts)} accounts")

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
            sys.exit(0)

    print("Importing accounts...")
    count = import_accounts(con, accounts)

    print(f"\nImported {count} accounts:")
    for acct_type, cnt in sorted(type_counts.items()):
        print(f"  {acct_type}: {cnt}")

    # Verify hierarchy
    with_parent = con.execute(
        "SELECT count(*) FROM accounts WHERE parent_id IS NOT NULL"
    ).fetchone()[0]
    print(f"\n  {with_parent} accounts have a parent (hierarchical)")
    print(f"  {count - with_parent} are top-level accounts")

    con.close()
    release_lock()
    print("\nDone.")


if __name__ == "__main__":
    main()
