"""Tests for the chart of accounts import logic."""

import sqlite3
from pathlib import Path

import pytest

from pyre.db import SCHEMA

# Import the functions under test
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from import_chart_of_accounts import clean_name, slugify, parse_csv, build_ids, import_accounts, QB_TYPE_MAP


class TestCleanName:
    def test_double_asterisk(self):
        assert clean_name("First National **1234") == "First National - 1234"

    def test_no_asterisks(self):
        assert clean_name("Cash") == "Cash"

    def test_credit_card(self):
        assert clean_name("Main Street **5678") == "Main Street - 5678"

    def test_five_digit_number(self):
        assert clean_name("American Express **41008") == "American Express - 41008"


class TestSlugify:
    def test_simple_name(self):
        assert slugify("Cash") == "cash"

    def test_spaces(self):
        assert slugify("Opening Balance Equity") == "opening_balance_equity"

    def test_asterisks(self):
        assert slugify("First National **1234") == "first_national_1234"

    def test_parentheses(self):
        assert slugify("Accounts Receivable (A/R)") == "accounts_receivable_ar"

    def test_ampersand(self):
        assert slugify("Salary & Wages") == "salary_wages"

    def test_commas_and_quotes(self):
        assert slugify("Travel, Per Diem") == "travel_per_diem"

    def test_complex_name(self):
        assert slugify("Professional (E&O, Cyber)") == "professional_eo_cyber"


class TestQBTypeMap:
    def test_all_qb_types_mapped(self):
        expected_qb_types = [
            "Bank", "Accounts receivable (A/R)", "Other Current Assets",
            "Fixed Assets", "Other Assets", "Accounts payable (A/P)",
            "Credit Card", "Other Current Liabilities", "Long Term Liabilities",
            "Equity", "Income", "Other Income", "Cost of Goods Sold",
            "Expenses", "Other Expense",
        ]
        for qb_type in expected_qb_types:
            assert qb_type in QB_TYPE_MAP, f"Missing mapping for '{qb_type}'"

    def test_bank_maps_to_asset(self):
        assert QB_TYPE_MAP["Bank"] == "asset"

    def test_expenses_maps_to_expense(self):
        assert QB_TYPE_MAP["Expenses"] == "expense"

    def test_credit_card_mapping(self):
        assert QB_TYPE_MAP["Credit Card"] == "credit_card"


class TestBuildIds:
    def test_simple_hierarchy(self):
        accounts = [
            {"full_name": "Sales", "name": "Sales", "type": "income",
             "parent_full_name": None, "account_number": None, "description": ""},
            {"full_name": "Sales:Hosting", "name": "Hosting", "type": "income",
             "parent_full_name": "Sales", "account_number": None, "description": ""},
        ]
        result = build_ids(accounts)
        assert result[0]["id"] == "sales"
        assert result[0]["parent_id"] is None
        assert result[1]["id"] == "sales__hosting"
        assert result[1]["parent_id"] == "sales"

    def test_slug_collision(self):
        accounts = [
            {"full_name": "Cat A:Fees", "name": "Fees", "type": "expense",
             "parent_full_name": "Cat A", "account_number": None, "description": ""},
            {"full_name": "Cat B:Fees", "name": "Fees", "type": "expense",
             "parent_full_name": "Cat B", "account_number": None, "description": ""},
        ]
        result = build_ids(accounts)
        ids = [a["id"] for a in result]
        assert len(set(ids)) == 2, "IDs should be unique"

    def test_no_parent_gives_none(self):
        accounts = [
            {"full_name": "Cash", "name": "Cash", "type": "asset",
             "parent_full_name": None, "account_number": None, "description": ""},
        ]
        result = build_ids(accounts)
        assert result[0]["parent_id"] is None


class TestImportAccounts:
    @pytest.fixture
    def empty_db(self):
        con = sqlite3.connect(":memory:")
        con.execute("PRAGMA foreign_keys = ON")
        con.executescript(SCHEMA)
        return con

    def test_import_flat(self, empty_db):
        accounts = [
            {"id": "cash", "name": "Cash", "type": "asset",
             "parent_id": None, "account_number": None, "description": ""},
            {"id": "equity", "name": "Equity", "type": "equity",
             "parent_id": None, "account_number": None, "description": ""},
        ]
        count = import_accounts(empty_db, accounts)
        assert count == 2

        rows = empty_db.execute("SELECT id FROM accounts ORDER BY id").fetchall()
        assert [r[0] for r in rows] == ["cash", "equity"]

    def test_import_hierarchy(self, empty_db):
        accounts = [
            {"id": "expenses", "name": "Expenses", "type": "expense",
             "parent_id": None, "account_number": "5000", "description": ""},
            {"id": "payroll", "name": "Payroll", "type": "expense",
             "parent_id": "expenses", "account_number": "5010", "description": ""},
        ]
        count = import_accounts(empty_db, accounts)
        assert count == 2

        parent = empty_db.execute(
            "SELECT parent_id FROM accounts WHERE id = 'payroll'"
        ).fetchone()
        assert parent[0] == "expenses"

    def test_import_out_of_order(self, empty_db):
        """Children listed before parents should still work."""
        accounts = [
            {"id": "child", "name": "Child", "type": "expense",
             "parent_id": "parent", "account_number": None, "description": ""},
            {"id": "parent", "name": "Parent", "type": "expense",
             "parent_id": None, "account_number": None, "description": ""},
        ]
        count = import_accounts(empty_db, accounts)
        assert count == 2


class TestParseCSV:
    def test_parse_real_csv(self):
        csv_path = Path(__file__).parent.parent / "Sample_Co-Chart-of-Accounts.csv"
        if not csv_path.exists():
            pytest.skip("CSV file not present")

        accounts = parse_csv(csv_path)
        assert len(accounts) > 100  # We expect ~200 accounts

        # Check that types are all valid
        valid_types = set(QB_TYPE_MAP.values())
        for acct in accounts:
            assert acct["type"] in valid_types, f"Invalid type '{acct['type']}' for '{acct['name']}'"

        # Check some known accounts exist
        names = [a["name"] for a in accounts]
        assert "Cash" in names

    def test_skips_total_row(self):
        csv_path = Path(__file__).parent.parent / "Sample_Co-Chart-of-Accounts.csv"
        if not csv_path.exists():
            pytest.skip("CSV file not present")

        accounts = parse_csv(csv_path)
        names = [a["name"] for a in accounts]
        assert "TOTAL" not in [n.upper() for n in names]
