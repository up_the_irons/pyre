import sqlite3

import pytest

from pyre.db import SCHEMA, _migrate
from pyre.models import post_transaction
from pyre.ui.app import PyreApp


@pytest.fixture
def db():
    """In-memory SQLite connection with schema applied."""
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    _migrate(con)
    return con


@pytest.fixture
def sample_vendors(sample_accounts):
    """Insert a few vendors into the sample_accounts DB."""
    db = sample_accounts
    db.executemany(
        "INSERT INTO vendors (id, name) VALUES (?, ?)",
        [
            ("acme_inc", "Acme Inc"),
            ("globex_corp", "Globex Corp"),
            ("initech", "Initech"),
        ],
    )
    db.commit()
    return db


@pytest.fixture
def sample_accounts(db):
    """Insert a minimal chart of accounts for testing."""
    accts = [
        ("checking",    None, "Main Checking",       "asset",     None),
        ("usbank",      None, "Other Checking",        "asset",     None),
        ("cap1",        None, "Rewards Visa",    "credit_card", None),
        ("income",      None, "Income",              "income",    None),
        ("sales",       None, "Sales",               "income",    "income"),
        ("hosting_rev", None, "Hosting",             "income",    "sales"),
        ("expenses",    None, "Expenses",            "expense",   None),
        ("direct_exp",  "5000", "Direct Expenses",   "expense",   "expenses"),
        ("payroll",     "5010", "Salary & Wages",    "expense",   "direct_exp"),
        ("indirect_exp","6000", "Indirect Expenses", "expense",   "expenses"),
        ("datacenter",  None, "Data Center",         "expense",   "indirect_exp"),
        ("cloud",       None, "Cloud Hosting",       "expense",   "indirect_exp"),
        ("interest",    None, "Interest Expense",    "expense",   "indirect_exp"),
        ("other_exp",   None, "Other Expenses",      "expense",   "expenses"),
        ("equity",      None, "Opening Balances",    "equity",    None),
    ]
    db.executemany(
        "INSERT INTO accounts (id, account_number, name, type, parent_id) VALUES (?,?,?,?,?)",
        accts,
    )
    db.commit()
    return db


# -- UI test fixtures --

@pytest.fixture
def ui_db(db):
    """DB with a minimal chart of accounts and a few transactions for UI tests."""
    accts = [
        ("checking",    None, "Main Checking",      "asset",       None),
        ("usbank",      None, "Other Checking",       "asset",       None),
        ("cap1",        None, "Rewards Visa",   "credit_card", None),
        ("expenses",    None, "Expenses",           "expense",     None),
        ("office",      None, "Office Supplies",    "expense",     "expenses"),
        ("hosting_exp", None, "Hosting",            "expense",     "expenses"),
        ("income",      None, "Income",             "income",      None),
        ("hosting_rev", None, "Hosting Revenue",    "income",      "income"),
    ]
    db.executemany(
        "INSERT INTO accounts (id, account_number, name, type, parent_id) VALUES (?,?,?,?,?)",
        accts,
    )
    db.commit()

    post_transaction(db, "2026-02-15", "Office Supplies - Amazon", [
        ("office", 2500),
        ("cap1", -2500),
    ])
    post_transaction(db, "2026-02-16", "Hosting Revenue", [
        ("checking", 50000),
        ("hosting_rev", -50000),
    ])
    post_transaction(db, "2026-02-17", "Colo Payment", [
        ("hosting_exp", 15000),
        ("checking", -15000),
    ])

    return db


@pytest.fixture
def app(ui_db):
    """PyreApp wired to the in-memory test database."""
    return PyreApp(con=ui_db)


@pytest.fixture
def coa_app(sample_accounts):
    """PyreApp backed by sample_accounts (deep hierarchy, no transactions)."""
    return PyreApp(con=sample_accounts)
