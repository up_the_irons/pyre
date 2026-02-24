"""Tests for account_models module."""

import sqlite3

import pytest

from pyre.account_models import (
    get_all_accounts,
    get_account_by_id,
    create_account,
    update_account,
    delete_account,
    get_child_count,
    get_transaction_count,
)
from pyre.formatting import new_id


class TestGetAllAccounts:
    def test_returns_all(self, sample_accounts):
        accounts = get_all_accounts(sample_accounts)
        assert len(accounts) == 15

    def test_returns_dicts(self, sample_accounts):
        accounts = get_all_accounts(sample_accounts)
        for a in accounts:
            assert "id" in a
            assert "name" in a
            assert "type" in a


class TestGetAccountById:
    def test_found(self, sample_accounts):
        acct = get_account_by_id(sample_accounts, "checking")
        assert acct is not None
        assert acct["name"] == "Main Checking"
        assert acct["type"] == "asset"

    def test_not_found(self, sample_accounts):
        acct = get_account_by_id(sample_accounts, "nonexistent")
        assert acct is None


class TestCreateAccount:
    def test_create_simple(self, sample_accounts):
        create_account(sample_accounts, "new_acct", "New Account", "asset")
        acct = get_account_by_id(sample_accounts, "new_acct")
        assert acct is not None
        assert acct["name"] == "New Account"
        assert acct["type"] == "asset"

    def test_create_with_parent(self, sample_accounts):
        create_account(
            sample_accounts, "sub_checking", "Sub Checking", "asset",
            parent_id="checking",
        )
        acct = get_account_by_id(sample_accounts, "sub_checking")
        assert acct["parent_id"] == "checking"

    def test_create_with_all_fields(self, sample_accounts):
        create_account(
            sample_accounts, "test_full", "Full Account", "expense",
            account_number="9999", parent_id="expenses",
            description="Test description",
        )
        acct = get_account_by_id(sample_accounts, "test_full")
        assert acct["account_number"] == "9999"
        assert acct["description"] == "Test description"

    def test_duplicate_id_raises(self, sample_accounts):
        with pytest.raises(sqlite3.IntegrityError):
            create_account(sample_accounts, "checking", "Duplicate", "asset")

    def test_create_rejects_parent_type_mismatch(self, sample_accounts):
        with pytest.raises(ValueError, match="does not match parent type"):
            create_account(
                sample_accounts, "bad_child", "Bad Child", "income",
                parent_id="expenses",
            )

    def test_create_rejects_colon_in_name(self, sample_accounts):
        with pytest.raises(ValueError, match="cannot contain ':'"):
            create_account(sample_accounts, "bad_name", "Foo:Bar", "asset")


class TestUpdateAccount:
    def test_update_name(self, sample_accounts):
        update_account(sample_accounts, "checking", "Updated Checking", "asset")
        acct = get_account_by_id(sample_accounts, "checking")
        assert acct["name"] == "Updated Checking"

    def test_update_type(self, sample_accounts):
        update_account(
            sample_accounts, "checking", "Main Checking", "other_current_asset",
        )
        acct = get_account_by_id(sample_accounts, "checking")
        assert acct["type"] == "other_current_asset"

    def test_update_rejects_parent_type_mismatch(self, sample_accounts):
        with pytest.raises(ValueError, match="does not match parent type"):
            update_account(
                sample_accounts, "datacenter", "Data Center", "income",
                parent_id="indirect_exp",
            )

    def test_update_rejects_colon_in_name(self, sample_accounts):
        with pytest.raises(ValueError, match="cannot contain ':'"):
            update_account(sample_accounts, "checking", "Main:Checking", "asset")


class TestDeleteAccount:
    def test_delete_leaf(self, sample_accounts):
        create_account(sample_accounts, "deleteme", "Delete Me", "asset")
        delete_account(sample_accounts, "deleteme")
        assert get_account_by_id(sample_accounts, "deleteme") is None

    def test_delete_blocked_by_children(self, sample_accounts):
        with pytest.raises(ValueError, match="child account"):
            delete_account(sample_accounts, "expenses")

    def test_delete_blocked_by_transactions(self, sample_accounts):
        con = sample_accounts
        # Create a transaction referencing 'checking'
        tx_id = new_id()
        split_id1 = new_id()
        split_id2 = new_id()
        con.execute(
            "INSERT INTO transactions (id, date, description) VALUES (?, ?, ?)",
            (tx_id, "2025-01-15", "Test"),
        )
        con.execute(
            "INSERT INTO splits (id, tx_id, account_id, amount) VALUES (?, ?, ?, ?)",
            (split_id1, tx_id, "checking", 1000),
        )
        con.execute(
            "INSERT INTO splits (id, tx_id, account_id, amount) VALUES (?, ?, ?, ?)",
            (split_id2, tx_id, "hosting_rev", -1000),
        )
        con.commit()

        with pytest.raises(sqlite3.IntegrityError):
            delete_account(con, "checking")


class TestGetChildCount:
    def test_with_children(self, sample_accounts):
        count = get_child_count(sample_accounts, "expenses")
        assert count == 3  # direct_exp, indirect_exp, other_exp

    def test_leaf_node(self, sample_accounts):
        count = get_child_count(sample_accounts, "checking")
        assert count == 0


class TestGetTransactionCount:
    def test_no_transactions(self, sample_accounts):
        count = get_transaction_count(sample_accounts, "checking")
        assert count == 0

    def test_with_transactions(self, sample_accounts):
        con = sample_accounts
        tx_id = new_id()
        split_id = new_id()
        con.execute(
            "INSERT INTO transactions (id, date, description) VALUES (?, ?, ?)",
            (tx_id, "2025-01-15", "Test"),
        )
        con.execute(
            "INSERT INTO splits (id, tx_id, account_id, amount) VALUES (?, ?, ?, ?)",
            (split_id, tx_id, "checking", 1000),
        )
        con.commit()

        count = get_transaction_count(con, "checking")
        assert count == 1
