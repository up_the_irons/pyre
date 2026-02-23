#!/usr/bin/env python3
"""One-time migration: rename ambiguous account IDs to parent-prefixed format.

Renames the 12 accounts that had collision suffixes (_1, _2) to use
parent_id__leaf_slug format instead, e.g. original_cost_1 -> photography_equipment__original_cost.

Updates accounts.id, accounts.parent_id (children), and splits.account_id.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from pyre.db import DB_PATH

RENAMES = {
    "original_cost":              "computer_equipment__original_cost",
    "original_cost_1":            "photography_equipment__original_cost",
    "original_cost_2":            "vehicles__original_cost",
    "accumulated_depreciation":   "computer_equipment__accumulated_depreciation",
    "accumulated_depreciation_1": "photography_equipment__accumulated_depreciation",
    "accumulated_depreciation_2": "vehicles__accumulated_depreciation",
    "bandwidth":                  "hosting__bandwidth",
    "bandwidth_1":                "data_center_expenses__bandwidth",
    "domain_names":               "hosting__domain_names",
    "domain_names_1":             "indirect_expenses__domain_names",
    "ip_numbers":                 "hosting__ip_numbers",
    "ip_numbers_1":               "data_center_expenses__ip_numbers",
}


def migrate():
    con = sqlite3.connect(DB_PATH)
    # Disable FK enforcement so we can update IDs without ordering issues
    con.execute("PRAGMA foreign_keys = OFF")
    cur = con.cursor()

    try:
        cur.execute("BEGIN")

        for old_id, new_id in RENAMES.items():
            # Check the account exists
            row = cur.execute(
                "SELECT 1 FROM accounts WHERE id = ?", (old_id,)
            ).fetchone()
            if row is None:
                print(f"  SKIP {old_id} (not found)")
                continue

            # Rename the account
            cur.execute(
                "UPDATE accounts SET id = ? WHERE id = ?", (new_id, old_id)
            )

            # Update children pointing to this as parent
            cur.execute(
                "UPDATE accounts SET parent_id = ? WHERE parent_id = ?",
                (new_id, old_id),
            )

            # Update any splits referencing this account
            n = cur.execute(
                "UPDATE splits SET account_id = ? WHERE account_id = ?",
                (new_id, old_id),
            ).rowcount

            suffix = f" (+{n} splits)" if n else ""
            print(f"  {old_id} -> {new_id}{suffix}")

        cur.execute("COMMIT")

        # Verify FK integrity
        violations = con.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            print(f"\nWARNING: {len(violations)} FK violations found!")
            for v in violations:
                print(f"  {v}")
        else:
            print("\nFK integrity check passed.")

    except Exception:
        cur.execute("ROLLBACK")
        raise
    finally:
        con.close()


if __name__ == "__main__":
    print(f"Migrating account IDs in {DB_PATH} ...")
    migrate()
    print("Done.")
