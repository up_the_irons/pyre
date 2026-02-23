#!/usr/bin/env python3
"""Seed a minimal Chart of Accounts for personal use."""

import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

# Allow running from project root or scripts/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DB_PATH = Path(
    os.environ.get("PYRE_DB_PATH", PROJECT_ROOT / "pyre.db")
).resolve()

# Minimal personal COA -- (id, name, type, parent_id)
ACCOUNTS = [
    # Assets
    ("checking",            "Checking Account",     "asset",        None),
    ("savings",             "Savings Account",       "asset",        None),

    # Liabilities
    ("credit_card",         "Credit Card",          "credit_card",  None),

    # Equity
    ("opening_balances",    "Opening Balances",     "equity",       None),

    # Income
    ("salary",              "Salary",               "income",       None),
    ("other_income",        "Other Income",         "income",       None),

    # Expenses -- parent categories
    ("food",                "Food",                 "expense",      None),
    ("housing",             "Housing",              "expense",      None),
    ("transportation",      "Transportation",       "expense",      None),
    ("medical",             "Medical",              "expense",      None),
    ("insurance",           "Insurance",            "expense",      None),
    ("entertainment",       "Entertainment",        "expense",      None),
    ("clothing",            "Clothing",             "expense",      None),
    ("subscriptions",       "Subscriptions",        "expense",      None),
    ("gifts",               "Gifts",                "expense",      None),
    ("miscellaneous",       "Miscellaneous",        "expense",      None),

    # Expenses -- sub-categories
    ("food__groceries",     "Groceries",            "expense",      "food"),
    ("food__dining",        "Dining Out",           "expense",      "food"),
    ("housing__rent",       "Rent / Mortgage",      "expense",      "housing"),
    ("housing__utilities",  "Utilities",            "expense",      "housing"),
    ("transportation__fuel","Fuel",                 "expense",      "transportation"),
    ("transportation__auto_insurance", "Auto Insurance", "expense", "transportation"),
    ("transportation__maintenance", "Maintenance",  "expense",      "transportation"),
]


def main():
    # Ensure the .env / DB path is configured
    if not (PROJECT_ROOT / ".env").exists():
        print("No .env file found. Creating one from .env.sample ...")
        sample = PROJECT_ROOT / ".env.sample"
        if sample.exists():
            (PROJECT_ROOT / ".env").write_text(sample.read_text())
        else:
            (PROJECT_ROOT / ".env").write_text("PYRE_DB_PATH=./pyre.db\n")

    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON")

    # Create schema if this is a fresh database
    schema_path = PROJECT_ROOT / "pyre" / "db.py"
    if schema_path.exists():
        # Import SCHEMA from the project rather than duplicating it
        sys.path.insert(0, str(PROJECT_ROOT))
        from pyre.db import SCHEMA, _migrate
        con.executescript(SCHEMA)
        _migrate(con)

    # Check if accounts already exist
    count = con.execute("SELECT count(*) FROM accounts").fetchone()[0]
    if count > 0:
        print(f"Database already has {count} account(s). Skipping COA setup.")
        print("  To start fresh, delete the database and run again.")
        con.close()
        return

    # Insert the starter accounts
    for acct_id, name, acct_type, parent_id in ACCOUNTS:
        con.execute(
            "INSERT INTO accounts (id, name, type, parent_id) VALUES (?, ?, ?, ?)",
            (acct_id, name, acct_type, parent_id),
        )
    con.commit()

    print(f"Created {len(ACCOUNTS)} accounts in {DB_PATH}")
    print()
    print("  Assets:       Checking Account, Savings Account")
    print("  Liabilities:  Credit Card")
    print("  Equity:       Opening Balances")
    print("  Income:       Salary, Other Income")
    print("  Expenses:     Food, Housing, Transportation, Medical,")
    print("                Insurance, Entertainment, Clothing,")
    print("                Subscriptions, Gifts, Miscellaneous")
    print()
    print("You can add, rename, or delete accounts from within Pyre.")

    con.close()


if __name__ == "__main__":
    main()
