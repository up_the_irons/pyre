import json
import os
import socket
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DB_PATH = Path(
    os.environ.get("PYRE_DB_PATH", Path(__file__).parent.parent / "pyre.db")
).resolve()
LOCK_PATH = DB_PATH.with_name(DB_PATH.name + ".lock")


def acquire_lock():
    """Create a lock file to prevent concurrent access to the database."""
    if LOCK_PATH.exists():
        try:
            info = json.loads(LOCK_PATH.read_text())
            holder = f"{info.get('hostname')} (PID {info.get('pid')}, since {info.get('timestamp')})"
        except (json.JSONDecodeError, OSError):
            holder = "unknown"
        print(f"Error: Database is locked by {holder}", file=sys.stderr)
        print(f"If this is stale, delete {LOCK_PATH}", file=sys.stderr)
        sys.exit(1)
    lock_info = {
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    LOCK_PATH.write_text(json.dumps(lock_info))


def release_lock():
    """Remove the lock file if it exists."""
    try:
        LOCK_PATH.unlink(missing_ok=True)
    except OSError:
        pass

# Account type families -- each tuple groups subtypes under a category
ASSET_TYPES = (
    "asset", "accounts_receivable", "other_current_asset",
    "fixed_asset", "other_asset",
)
LIABILITY_TYPES = (
    "liability", "accounts_payable", "credit_card",
    "other_current_liability", "long_term_liability",
)
EQUITY_TYPES = ("equity",)
INCOME_TYPES = ("income", "other_income")
EXPENSE_TYPES = ("expense", "cost_of_goods_sold", "other_expense")

# Map each type to its family name for grouping/parent matching
TYPE_FAMILY = {}
for _types, _family in [
    (ASSET_TYPES, "asset"), (LIABILITY_TYPES, "liability"),
    (EQUITY_TYPES, "equity"), (INCOME_TYPES, "income"),
    (EXPENSE_TYPES, "expense"),
]:
    for _t in _types:
        TYPE_FAMILY[_t] = _family

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id              TEXT PRIMARY KEY,
    account_number  TEXT,
    name            TEXT NOT NULL,
    type            TEXT NOT NULL CHECK(type IN (
        'asset','accounts_receivable','other_current_asset','fixed_asset','other_asset',
        'liability','accounts_payable','credit_card','other_current_liability','long_term_liability',
        'equity',
        'income','other_income',
        'expense','cost_of_goods_sold','other_expense'
    )),
    parent_id       TEXT REFERENCES accounts(id),
    description     TEXT DEFAULT '',
    sidebar         INTEGER NOT NULL DEFAULT 0,
    ofx_bankid      TEXT,
    ofx_acctid      TEXT
);

CREATE TABLE IF NOT EXISTS vendors (
    id    TEXT PRIMARY KEY,
    name  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    id          TEXT PRIMARY KEY,
    date        TEXT NOT NULL,
    description TEXT NOT NULL,
    memo        TEXT DEFAULT '',
    vendor_id   TEXT REFERENCES vendors(id)
);

CREATE TABLE IF NOT EXISTS splits (
    id          TEXT PRIMARY KEY,
    tx_id       TEXT NOT NULL REFERENCES transactions(id),
    account_id  TEXT NOT NULL REFERENCES accounts(id),
    amount      INTEGER NOT NULL,  -- cents, positive = debit, negative = credit
    reconcile   TEXT DEFAULT 'n' CHECK(reconcile IN ('n','c','r')),
    description TEXT DEFAULT '',
    reconciliation_id TEXT REFERENCES reconciliations(id)
);

CREATE TABLE IF NOT EXISTS payee_rules (
    id            TEXT PRIMARY KEY,
    pattern       TEXT NOT NULL,
    memo_pattern  TEXT,
    account_id    TEXT NOT NULL REFERENCES accounts(id),
    vendor_id     TEXT REFERENCES vendors(id),
    priority      INTEGER NOT NULL DEFAULT 0,
    created       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS import_log (
    id          TEXT PRIMARY KEY,
    source_file TEXT,
    fitid       TEXT,
    hash        TEXT,
    tx_id       TEXT REFERENCES transactions(id),
    status      TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    account_id  TEXT REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS reconciliations (
    id                TEXT PRIMARY KEY,
    account_id        TEXT NOT NULL REFERENCES accounts(id),
    statement_date    TEXT NOT NULL,
    statement_balance INTEGER NOT NULL,
    beginning_balance INTEGER NOT NULL,
    reconciled_at     TEXT NOT NULL,
    split_count       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reconcile_sessions (
    account_id        TEXT PRIMARY KEY REFERENCES accounts(id),
    statement_date    TEXT NOT NULL,
    statement_balance INTEGER NOT NULL,
    saved_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scheduled_transactions (
    id          TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    vendor_id   TEXT REFERENCES vendors(id),
    frequency   TEXT NOT NULL CHECK(frequency IN ('weekly','biweekly','monthly','quarterly','yearly')),
    next_date   TEXT NOT NULL,
    end_date    TEXT,
    enabled     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS scheduled_splits (
    id                TEXT PRIMARY KEY,
    scheduled_tx_id   TEXT NOT NULL REFERENCES scheduled_transactions(id),
    account_id        TEXT NOT NULL REFERENCES accounts(id),
    amount            INTEGER NOT NULL,
    description       TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_splits_acct_amt ON splits(account_id, amount);

-- NOTE: We enforce double-entry balance in application code (post_transaction, update_transaction)
-- rather than with triggers, because splits are inserted one-at-a-time and would fail mid-insert.
-- The application checks SUM(amount) = 0 before committing.
"""


def _migrate(con):
    """Run schema migrations for existing databases."""
    cols = [r[1] for r in con.execute("PRAGMA table_info(accounts)").fetchall()]

    # Add sidebar column
    if "sidebar" not in cols:
        con.execute("ALTER TABLE accounts ADD COLUMN sidebar INTEGER NOT NULL DEFAULT 0")
        con.commit()

    # Add OFX mapping columns
    if "ofx_bankid" not in cols:
        con.execute("ALTER TABLE accounts ADD COLUMN ofx_bankid TEXT")
        con.execute("ALTER TABLE accounts ADD COLUMN ofx_acctid TEXT")
        con.commit()

    # Create payee_rules table
    con.execute("""
        CREATE TABLE IF NOT EXISTS payee_rules (
            id          TEXT PRIMARY KEY,
            pattern     TEXT NOT NULL,
            account_id  TEXT NOT NULL REFERENCES accounts(id),
            priority    INTEGER NOT NULL DEFAULT 0,
            created     TEXT NOT NULL
        )
    """)

    # Create import_log table
    con.execute("""
        CREATE TABLE IF NOT EXISTS import_log (
            id          TEXT PRIMARY KEY,
            source_file TEXT,
            fitid       TEXT,
            hash        TEXT,
            tx_id       TEXT REFERENCES transactions(id),
            status      TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            account_id  TEXT REFERENCES accounts(id)
        )
    """)
    # Migrate: add account_id column if missing (existing databases)
    cols = {r[1] for r in con.execute("PRAGMA table_info(import_log)").fetchall()}
    if "account_id" not in cols:
        con.execute("ALTER TABLE import_log ADD COLUMN account_id TEXT REFERENCES accounts(id)")
    # Drop old global indexes and create account-scoped ones
    con.execute("DROP INDEX IF EXISTS idx_import_log_fitid")
    con.execute("DROP INDEX IF EXISTS idx_import_log_hash")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_import_log_acct_fitid ON import_log(account_id, fitid) WHERE fitid IS NOT NULL")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_import_log_acct_hash ON import_log(account_id, hash) WHERE hash IS NOT NULL")
    con.execute("CREATE INDEX IF NOT EXISTS idx_splits_acct_amt ON splits(account_id, amount)")
    # Add memo_pattern column to payee_rules
    pr_cols = {r[1] for r in con.execute("PRAGMA table_info(payee_rules)").fetchall()}
    if "memo_pattern" not in pr_cols:
        con.execute("ALTER TABLE payee_rules ADD COLUMN memo_pattern TEXT")
    if "vendor_id" not in pr_cols:
        con.execute("ALTER TABLE payee_rules ADD COLUMN vendor_id TEXT REFERENCES vendors(id)")
    # Create reconcile_sessions table (in-progress reconciliation state)
    con.execute("""
        CREATE TABLE IF NOT EXISTS reconcile_sessions (
            account_id        TEXT PRIMARY KEY REFERENCES accounts(id),
            statement_date    TEXT NOT NULL,
            statement_balance INTEGER NOT NULL,
            saved_at          TEXT NOT NULL
        )
    """)
    # Create reconciliations table
    con.execute("""
        CREATE TABLE IF NOT EXISTS reconciliations (
            id                TEXT PRIMARY KEY,
            account_id        TEXT NOT NULL REFERENCES accounts(id),
            statement_date    TEXT NOT NULL,
            statement_balance INTEGER NOT NULL,
            beginning_balance INTEGER NOT NULL,
            reconciled_at     TEXT NOT NULL,
            split_count       INTEGER NOT NULL DEFAULT 0
        )
    """)
    # Create vendors table
    con.execute("""
        CREATE TABLE IF NOT EXISTS vendors (
            id   TEXT PRIMARY KEY,
            name TEXT NOT NULL
        )
    """)
    # Add vendor_id to transactions
    tx_cols = {r[1] for r in con.execute("PRAGMA table_info(transactions)").fetchall()}
    if "vendor_id" not in tx_cols:
        con.execute("ALTER TABLE transactions ADD COLUMN vendor_id TEXT REFERENCES vendors(id)")
    # Add description column to splits
    split_cols = {r[1] for r in con.execute("PRAGMA table_info(splits)").fetchall()}
    if "description" not in split_cols:
        con.execute("ALTER TABLE splits ADD COLUMN description TEXT DEFAULT ''")

    # Add reconciliation_id to splits
    if "reconciliation_id" not in split_cols:
        con.execute("ALTER TABLE splits ADD COLUMN reconciliation_id TEXT REFERENCES reconciliations(id)")
        # Backfill: assign reconciliation_id to already-reconciled splits
        recs = con.execute(
            "SELECT id, account_id, split_count FROM reconciliations "
            "ORDER BY reconciled_at ASC"
        ).fetchall()
        for rec_id, acct_id, split_count in recs:
            if split_count <= 0:
                continue
            # Find unlinked reconciled splits for this account, oldest first
            unlinked = con.execute(
                "SELECT s.id FROM splits s "
                "JOIN transactions t ON t.id = s.tx_id "
                "WHERE s.account_id = ? AND s.reconcile = 'r' "
                "AND s.reconciliation_id IS NULL "
                "ORDER BY t.date, s.id "
                "LIMIT ?",
                (acct_id, split_count),
            ).fetchall()
            for (sid,) in unlinked:
                con.execute(
                    "UPDATE splits SET reconciliation_id = ? WHERE id = ?",
                    (rec_id, sid),
                )

    # Create scheduled_transactions and scheduled_splits tables
    con.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_transactions (
            id          TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            vendor_id   TEXT REFERENCES vendors(id),
            frequency   TEXT NOT NULL CHECK(frequency IN ('weekly','biweekly','monthly','quarterly','yearly')),
            next_date   TEXT NOT NULL,
            end_date    TEXT,
            enabled     INTEGER NOT NULL DEFAULT 1
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_splits (
            id                TEXT PRIMARY KEY,
            scheduled_tx_id   TEXT NOT NULL REFERENCES scheduled_transactions(id),
            account_id        TEXT NOT NULL REFERENCES accounts(id),
            amount            INTEGER NOT NULL,
            description       TEXT DEFAULT ''
        )
    """)

    con.commit()


def init_db():
    acquire_lock()
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    _migrate(con)
    return con
