"""Tests for correct display of accounts with duplicate names under different parents.

Regression: accounts named identically (e.g. 'Accumulated Depreciation' under both
Computer Equipment and Vehicles) were all shown with the same parent prefix because
_account_full_names was keyed by account name instead of account_id.
"""
import pytest

from pyre.models import post_transaction, get_recent_transactions
from pyre.account_models import account_path
from pyre.ui.app import PyreApp


@pytest.fixture
def dup_name_db(db):
    """DB with duplicate-named child accounts under different parents."""
    accts = [
        ("checking",    None, "Main Checking",             "asset",       None),
        ("equity",      None, "Opening Balances",          "equity",      None),
        ("comp_equip",  None, "Computer Equipment",        "fixed_asset", None),
        ("comp_accum",  None, "Accumulated Depreciation",  "fixed_asset", "comp_equip"),
        ("comp_cost",   None, "Original cost",             "fixed_asset", "comp_equip"),
        ("vehicles",    None, "Vehicles",                  "fixed_asset", None),
        ("veh_accum",   None, "Accumulated Depreciation",  "fixed_asset", "vehicles"),
        ("veh_cost",    None, "Original cost",             "fixed_asset", "vehicles"),
    ]
    db.executemany(
        "INSERT INTO accounts (id, account_number, name, type, parent_id) VALUES (?,?,?,?,?)",
        accts,
    )
    db.commit()
    return db


@pytest.fixture
def dup_name_app(dup_name_db):
    """App with duplicate-named accounts and a multi-split transaction."""
    con = dup_name_db
    post_transaction(con, "2026-01-01", "Opening Balances", [
        ("comp_cost",  7155237),
        ("comp_accum", -7155237),
        ("veh_cost",   4851905),
        ("veh_accum",  -4851905),
        ("equity",     -5000000),
        ("checking",   5000000),
    ])
    return PyreApp(con=con)


class TestSplitInfoIncludesAccountId:
    """The GROUP_CONCAT split_info string must include account_id for disambiguation."""

    def test_split_info_contains_account_ids(self, dup_name_db):
        """Each split in split_info should have name:amount:reconcile:account_id."""
        con = dup_name_db
        post_transaction(con, "2026-01-01", "Test", [
            ("comp_accum", -100),
            ("veh_accum", -200),
            ("checking", 300),
        ])
        rows = get_recent_transactions(con)
        split_info = rows[0][2]
        parts = split_info.split("|")
        for part in parts:
            fields = part.rsplit(":", 3)
            assert len(fields) == 4, f"Expected 4 fields in '{part}', got {len(fields)}"
            name, amount, reconcile, account_id = fields
            assert account_id in ("comp_accum", "veh_accum", "checking")

    async def test_parse_splits_returns_account_id(self, dup_name_app):
        """_parse_splits should return 4-tuples with account_id."""
        async with dup_name_app.run_test():
            dup_name_app.refresh_ledger()
            for tx_id, splits in dup_name_app._row_splits.items():
                for split in splits:
                    assert len(split) == 4, f"Expected 4-tuple, got {len(split)}: {split}"
                    name, amount, reconcile, account_id = split
                    assert account_id != "", "account_id should not be empty"


class TestAccountFullNamesDisambiguation:
    """_account_full_names must distinguish accounts with identical names."""

    async def test_full_names_keyed_by_id(self, dup_name_app):
        """Both 'Accumulated Depreciation' accounts should have distinct full names."""
        async with dup_name_app.run_test():
            dup_name_app.refresh_ledger()
            fn = dup_name_app._account_full_names
            comp_path = fn.get("comp_accum")
            veh_path = fn.get("veh_accum")
            assert comp_path is not None, "comp_accum missing from _account_full_names"
            assert veh_path is not None, "veh_accum missing from _account_full_names"
            assert comp_path != veh_path, (
                f"Paths should differ: comp={comp_path}, veh={veh_path}"
            )
            assert "Computer Equipment" in comp_path
            assert "Vehicles" in veh_path

    async def test_account_types_keyed_by_id(self, dup_name_app):
        """_account_types should be keyed by account_id, not name."""
        async with dup_name_app.run_test():
            dup_name_app.refresh_ledger()
            types = dup_name_app._account_types
            assert "comp_accum" in types
            assert "veh_accum" in types
            assert "comp_cost" in types
            assert "veh_cost" in types


class TestExpandedSplitDisplay:
    """Expanded multi-split transaction should show correct parent paths."""

    async def test_split_lookup_resolves_distinct_parents(self, dup_name_app):
        """When resolving full names for splits, each 'Accumulated Depreciation'
        should show its correct parent (Computer Equipment vs Vehicles)."""
        async with dup_name_app.run_test() as pilot:
            dup_name_app.refresh_ledger()
            await pilot.pause()

            # Get any transaction's splits
            tx_id = list(dup_name_app._row_splits.keys())[0]
            splits = dup_name_app._row_splits[tx_id]
            fn = dup_name_app._account_full_names

            # Resolve full names the same way the expanded split view does
            full_names = [fn.get(aid, name) for name, _, _, aid in splits]

            comp_names = [n for n in full_names if "Computer Equipment" in n]
            veh_names = [n for n in full_names if "Vehicles" in n]
            assert len(comp_names) >= 1, (
                f"Expected at least one Computer Equipment path, got: {full_names}"
            )
            assert len(veh_names) >= 1, (
                f"Expected at least one Vehicles path, got: {full_names}"
            )
