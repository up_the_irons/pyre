"""Tests for locking reconciled transactions against edit/delete."""

import pytest

from pyre.models import (
    delete_transaction,
    is_transaction_reconciled,
    post_transaction,
    update_transaction,
    update_transaction_metadata,
    get_transaction_detail,
)
from pyre.ui.app import PyreApp


# -- Model tests --


class TestIsTransactionReconciled:
    def test_false_when_no_reconciled_splits(self, sample_accounts):
        con = sample_accounts
        tx_id = post_transaction(con, "2026-01-15", "Deposit", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        assert is_transaction_reconciled(con, tx_id) is False

    def test_true_when_split_reconciled(self, sample_accounts):
        con = sample_accounts
        tx_id = post_transaction(con, "2026-01-15", "Deposit", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        split = con.execute(
            "SELECT id FROM splits WHERE tx_id = ? LIMIT 1", (tx_id,)
        ).fetchone()
        con.execute(
            "UPDATE splits SET reconcile = 'r' WHERE id = ?", (split[0],)
        )
        con.commit()
        assert is_transaction_reconciled(con, tx_id) is True

    def test_false_when_only_cleared(self, sample_accounts):
        con = sample_accounts
        tx_id = post_transaction(con, "2026-01-15", "Deposit", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        split = con.execute(
            "SELECT id FROM splits WHERE tx_id = ? LIMIT 1", (tx_id,)
        ).fetchone()
        con.execute(
            "UPDATE splits SET reconcile = 'c' WHERE id = ?", (split[0],)
        )
        con.commit()
        assert is_transaction_reconciled(con, tx_id) is False


class TestDeleteReconciledTransaction:
    def test_delete_reconciled_raises(self, sample_accounts):
        con = sample_accounts
        tx_id = post_transaction(con, "2026-01-15", "Deposit", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        split = con.execute(
            "SELECT id FROM splits WHERE tx_id = ? LIMIT 1", (tx_id,)
        ).fetchone()
        con.execute(
            "UPDATE splits SET reconcile = 'r' WHERE id = ?", (split[0],)
        )
        con.commit()

        with pytest.raises(ValueError, match="Cannot delete a reconciled transaction"):
            delete_transaction(con, tx_id)

    def test_delete_unreconciled_still_works(self, sample_accounts):
        con = sample_accounts
        tx_id = post_transaction(con, "2026-01-15", "Deposit", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        delete_transaction(con, tx_id)
        tx, splits = get_transaction_detail(con, tx_id)
        assert tx is None


class TestUpdateReconciledTransaction:
    def test_update_reconciled_raises(self, sample_accounts):
        con = sample_accounts
        tx_id = post_transaction(con, "2026-01-15", "Deposit", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        tx, splits = get_transaction_detail(con, tx_id)
        con.execute(
            "UPDATE splits SET reconcile = 'r' WHERE id = ?", (splits[0][0],)
        )
        con.commit()

        with pytest.raises(ValueError, match="Cannot modify a reconciled transaction"):
            update_transaction(con, tx_id, "2026-01-16", "Updated", [
                (splits[0][0], 50000),
                (splits[1][0], -50000),
            ])


class TestUpdateTransactionMetadata:
    def test_metadata_update_on_reconciled(self, sample_accounts):
        con = sample_accounts
        tx_id = post_transaction(con, "2026-01-15", "Original", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        split = con.execute(
            "SELECT id FROM splits WHERE tx_id = ? LIMIT 1", (tx_id,)
        ).fetchone()
        con.execute(
            "UPDATE splits SET reconcile = 'r' WHERE id = ?", (split[0],)
        )
        con.commit()

        update_transaction_metadata(con, tx_id, "Updated Description",
                                    vendor_id=None)
        tx, _ = get_transaction_detail(con, tx_id)
        assert tx[2] == "Updated Description"

    def test_metadata_update_split_descriptions(self, sample_accounts):
        con = sample_accounts
        tx_id = post_transaction(con, "2026-01-15", "With splits", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        tx, splits = get_transaction_detail(con, tx_id)
        # Reconcile a split
        con.execute(
            "UPDATE splits SET reconcile = 'r' WHERE id = ?", (splits[0][0],)
        )
        con.commit()

        split_descs = {splits[0][0]: "desc A", splits[1][0]: "desc B"}
        update_transaction_metadata(con, tx_id, "With splits",
                                    split_descriptions=split_descs)
        tx, updated_splits = get_transaction_detail(con, tx_id)
        descs = {s[0]: s[4] for s in updated_splits}
        assert descs[splits[0][0]] == "desc A"
        assert descs[splits[1][0]] == "desc B"

    def test_split_accounts_updates_unreconciled(self, sample_accounts):
        con = sample_accounts
        tx_id = post_transaction(con, "2026-01-15", "Partial", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        tx, splits = get_transaction_detail(con, tx_id)
        # Reconcile only the first split
        con.execute(
            "UPDATE splits SET reconcile = 'r' WHERE id = ?", (splits[0][0],)
        )
        con.commit()

        # Change the unreconciled split's account
        update_transaction_metadata(
            con, tx_id, "Partial",
            split_accounts={splits[1][0]: "payroll"},
        )
        tx, updated_splits = get_transaction_detail(con, tx_id)
        accts = {s[0]: s[1] for s in updated_splits}
        assert accts[splits[1][0]] == "payroll"
        # Reconciled split unchanged
        assert accts[splits[0][0]] == "checking"

    def test_split_accounts_rejects_reconciled(self, sample_accounts):
        con = sample_accounts
        tx_id = post_transaction(con, "2026-01-15", "Locked", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        tx, splits = get_transaction_detail(con, tx_id)
        con.execute(
            "UPDATE splits SET reconcile = 'r' WHERE id = ?", (splits[0][0],)
        )
        con.commit()

        with pytest.raises(ValueError, match="Cannot change account on a reconciled split"):
            update_transaction_metadata(
                con, tx_id, "Locked",
                split_accounts={splits[0][0]: "payroll"},
            )


# -- UI tests --


@pytest.fixture
def reconciled_app(ui_db):
    """App with one fully-reconciled transaction in the ledger."""
    # Reconcile ALL splits on the Hosting Revenue transaction
    tx_row = ui_db.execute(
        "SELECT DISTINCT tx_id FROM splits WHERE account_id = 'checking' "
        "AND amount > 0 LIMIT 1"
    ).fetchone()
    tx_id = tx_row[0]
    ui_db.execute(
        "UPDATE splits SET reconcile = 'r' WHERE tx_id = ?", (tx_id,)
    )
    ui_db.commit()
    return PyreApp(con=ui_db)


@pytest.fixture
def partial_reconciled_app(ui_db):
    """App with a partially-reconciled transaction (one split reconciled)."""
    split = ui_db.execute(
        "SELECT id FROM splits WHERE account_id = 'checking' "
        "AND amount > 0 LIMIT 1"
    ).fetchone()
    ui_db.execute(
        "UPDATE splits SET reconcile = 'r' WHERE id = ?", (split[0],)
    )
    ui_db.commit()
    return PyreApp(con=ui_db)


class TestEditScreenPartialEdit:
    async def test_edit_screen_partial_for_reconciled(self, reconciled_app):
        """EditTransactionScreen should allow editing vendor/description
        but lock splits, date, and delete for reconciled transactions."""
        from pyre.ui.screens import EditTransactionScreen
        from textual.widgets import Input, Label, Select

        async with reconciled_app.run_test() as pilot:
            tx_id = reconciled_app.con.execute(
                "SELECT DISTINCT s.tx_id FROM splits s "
                "WHERE s.reconcile = 'r' LIMIT 1"
            ).fetchone()[0]

            screen = EditTransactionScreen(tx_id, reconciled_app.con)
            reconciled_app.push_screen(screen)
            await pilot.pause()

            # Title should indicate reconciled edit mode
            title = screen.query_one("#at-title", Label)
            assert "Reconciled" in str(title.content)

            # Description input should exist and be editable
            assert len(screen.query("#at-desc")) == 1

            # Vendor select exists if vendors are configured
            # (test DB may not have vendors)

            # No date input (date is a read-only label)
            assert len(screen.query("#at-date")) == 0

            # No split account/amount inputs
            assert len(screen.query(".at-split-account")) == 0
            assert len(screen.query(".at-split-amount")) == 0

            # Save button should exist
            assert len(screen.query("#at-save")) == 1

            # Delete button should not exist
            assert len(screen.query("#at-delete")) == 0


class TestUIDeleteBlocked:
    async def test_d_key_blocked_on_reconciled(self, reconciled_app):
        async with reconciled_app.run_test(notifications=True) as pilot:
            table = reconciled_app.query_one("#ledger-table")
            table.focus()
            await pilot.pause()

            # Navigate to the reconciled transaction (Hosting Revenue)
            # It has a reconciled split on checking
            # Find which row has the reconciled tx
            for i in range(table.row_count):
                table.move_cursor(row=i)
                await pilot.pause()
                key = str(table.coordinate_to_cell_key(
                    table.cursor_coordinate
                ).row_key.value)
                if key.startswith("_split:"):
                    continue
                if is_transaction_reconciled(reconciled_app.con, key):
                    break

            initial_count = table.row_count
            await pilot.press("d")
            await pilot.pause()

            # Row count should not change (delete was blocked)
            assert table.row_count == initial_count

    async def test_enter_opens_partial_edit_on_reconciled(self, reconciled_app):
        from pyre.ui.screens import EditTransactionScreen

        async with reconciled_app.run_test(notifications=True) as pilot:
            table = reconciled_app.query_one("#ledger-table")
            table.focus()
            await pilot.pause()

            # Navigate to the reconciled transaction
            for i in range(table.row_count):
                table.move_cursor(row=i)
                await pilot.pause()
                key = str(table.coordinate_to_cell_key(
                    table.cursor_coordinate
                ).row_key.value)
                if key.startswith("_split:"):
                    continue
                if is_transaction_reconciled(reconciled_app.con, key):
                    break

            await pilot.press("enter")
            await pilot.pause()

            # Should open EditTransactionScreen in reconciled-edit mode
            assert isinstance(reconciled_app.screen, EditTransactionScreen)
            assert reconciled_app.screen._reconciled is True


class TestPartialReconciledUI:
    async def test_partial_reconciled_shows_account_button_on_unreconciled(
        self, partial_reconciled_app
    ):
        """Partially-reconciled tx should show account picker button on
        unreconciled split but a locked label on the reconciled split."""
        from pyre.ui.screens import EditTransactionScreen
        from textual.widgets import Button, Input, Label

        app = partial_reconciled_app
        async with app.run_test() as pilot:
            tx_id = app.con.execute(
                "SELECT DISTINCT s.tx_id FROM splits s "
                "WHERE s.reconcile = 'r' LIMIT 1"
            ).fetchone()[0]

            screen = EditTransactionScreen(tx_id, app.con)
            app.push_screen(screen)
            await pilot.pause()

            assert screen._has_reconciled is True
            assert screen._reconciled is False

            # Title should indicate partially reconciled
            title = screen.query_one("#at-title", Label)
            assert "Partially Reconciled" in str(title.content)

            # Exactly one account picker button (for the unreconciled split)
            acct_buttons = screen.query(".at-split-account")
            assert len(acct_buttons) == 1

            # No amount inputs (amounts are locked in partial mode)
            assert len(screen.query(".at-split-amount")) == 0

            # No date input
            assert len(screen.query("#at-date")) == 0

            # No delete button
            assert len(screen.query("#at-delete")) == 0

            # Description input exists
            assert len(screen.query("#at-desc")) == 1

            # Save button exists
            assert len(screen.query("#at-save")) == 1
