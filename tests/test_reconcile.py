"""Tests for account reconciliation feature."""

import textwrap

import pytest

from textual.widgets import Input, Label, OptionList

from pyre.fuzzy_select import FuzzySelect

from pyre.models import (
    finish_reconciliation,
    get_all_reconciliations,
    get_reconcile_session,
    get_reconciled_balance,
    get_last_reconciliation,
    get_unreconciled_splits,
    post_transaction,
    save_reconciliation_progress,
)
from pyre.ui.app import PyreApp


# -- Model tests --


class TestGetReconciledBalance:
    def test_zero_when_nothing_reconciled(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2026-01-15", "Deposit", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        assert get_reconciled_balance(con, "checking") == 0

    def test_zero_with_no_transactions(self, sample_accounts):
        con = sample_accounts
        assert get_reconciled_balance(con, "checking") == 0

    def test_includes_only_reconciled_splits(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2026-01-15", "Deposit", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        # Mark one split as reconciled
        split = con.execute(
            "SELECT id FROM splits WHERE account_id = 'checking'"
        ).fetchone()
        con.execute(
            "UPDATE splits SET reconcile = 'r' WHERE id = ?", (split[0],)
        )
        con.commit()

        assert get_reconciled_balance(con, "checking") == 50000

    def test_ignores_cleared_splits(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2026-01-15", "Deposit", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        split = con.execute(
            "SELECT id FROM splits WHERE account_id = 'checking'"
        ).fetchone()
        con.execute(
            "UPDATE splits SET reconcile = 'c' WHERE id = ?", (split[0],)
        )
        con.commit()

        assert get_reconciled_balance(con, "checking") == 0


class TestGetLastReconciliation:
    def test_none_when_no_reconciliations(self, sample_accounts):
        con = sample_accounts
        assert get_last_reconciliation(con, "checking") is None

    def test_returns_most_recent(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2026-01-15", "Deposit", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        splits = con.execute(
            "SELECT id FROM splits WHERE account_id = 'checking'"
        ).fetchall()

        finish_reconciliation(
            con, "checking", [s[0] for s in splits],
            "2026-01-31", 50000, 0,
        )

        last = get_last_reconciliation(con, "checking")
        assert last is not None
        assert last["statement_date"] == "2026-01-31"
        assert last["statement_balance"] == 50000
        assert last["beginning_balance"] == 0
        assert last["split_count"] == 1

    def test_scoped_to_account(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2026-01-15", "Deposit", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        splits = con.execute(
            "SELECT id FROM splits WHERE account_id = 'checking'"
        ).fetchall()

        finish_reconciliation(
            con, "checking", [s[0] for s in splits],
            "2026-01-31", 50000, 0,
        )

        # Different account should have no reconciliation
        assert get_last_reconciliation(con, "usbank") is None


class TestGetUnreconciledSplits:
    def test_returns_unreconciled(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2026-01-15", "Deposit", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        splits = get_unreconciled_splits(con, "checking", "2026-01-31")
        assert len(splits) == 1
        assert splits[0]["amount"] == 50000
        assert splits[0]["description"] == "Deposit"
        assert splits[0]["reconcile"] == "n"

    def test_includes_cleared(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2026-01-15", "Deposit", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        split = con.execute(
            "SELECT id FROM splits WHERE account_id = 'checking'"
        ).fetchone()
        con.execute(
            "UPDATE splits SET reconcile = 'c' WHERE id = ?", (split[0],)
        )
        con.commit()

        splits = get_unreconciled_splits(con, "checking", "2026-01-31")
        assert len(splits) == 1
        assert splits[0]["reconcile"] == "c"

    def test_excludes_reconciled(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2026-01-15", "Deposit", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        split = con.execute(
            "SELECT id FROM splits WHERE account_id = 'checking'"
        ).fetchone()
        con.execute(
            "UPDATE splits SET reconcile = 'r' WHERE id = ?", (split[0],)
        )
        con.commit()

        splits = get_unreconciled_splits(con, "checking", "2026-01-31")
        assert len(splits) == 0

    def test_respects_through_date(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2026-01-15", "Early", [
            ("checking", 30000),
            ("hosting_rev", -30000),
        ])
        post_transaction(con, "2026-02-15", "Late", [
            ("checking", 20000),
            ("hosting_rev", -20000),
        ])
        splits = get_unreconciled_splits(con, "checking", "2026-01-31")
        assert len(splits) == 1
        assert splits[0]["description"] == "Early"

    def test_ordered_by_date(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2026-01-20", "Second", [
            ("checking", 20000),
            ("hosting_rev", -20000),
        ])
        post_transaction(con, "2026-01-10", "First", [
            ("checking", 30000),
            ("hosting_rev", -30000),
        ])
        splits = get_unreconciled_splits(con, "checking", "2026-01-31")
        assert len(splits) == 2
        assert splits[0]["description"] == "First"
        assert splits[1]["description"] == "Second"

    def test_scoped_to_account(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2026-01-15", "Checking deposit", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        post_transaction(con, "2026-01-15", "USBank deposit", [
            ("usbank", 30000),
            ("hosting_rev", -30000),
        ])
        splits = get_unreconciled_splits(con, "checking", "2026-01-31")
        assert len(splits) == 1
        assert splits[0]["amount"] == 50000


class TestFinishReconciliation:
    def test_marks_splits_as_reconciled(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2026-01-15", "Deposit", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        split = con.execute(
            "SELECT id FROM splits WHERE account_id = 'checking'"
        ).fetchone()

        finish_reconciliation(
            con, "checking", [split[0]],
            "2026-01-31", 50000, 0,
        )

        rec = con.execute(
            "SELECT reconcile FROM splits WHERE id = ?", (split[0],)
        ).fetchone()
        assert rec[0] == "r"

    def test_creates_reconciliation_record(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2026-01-15", "Deposit", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        split = con.execute(
            "SELECT id FROM splits WHERE account_id = 'checking'"
        ).fetchone()

        rec_id = finish_reconciliation(
            con, "checking", [split[0]],
            "2026-01-31", 50000, 0,
        )

        row = con.execute(
            "SELECT account_id, statement_date, statement_balance, "
            "beginning_balance, split_count FROM reconciliations WHERE id = ?",
            (rec_id,),
        ).fetchone()
        assert row[0] == "checking"
        assert row[1] == "2026-01-31"
        assert row[2] == 50000
        assert row[3] == 0
        assert row[4] == 1

    def test_multiple_splits(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2026-01-10", "Deposit 1", [
            ("checking", 30000),
            ("hosting_rev", -30000),
        ])
        post_transaction(con, "2026-01-20", "Deposit 2", [
            ("checking", 20000),
            ("hosting_rev", -20000),
        ])
        splits = con.execute(
            "SELECT id FROM splits WHERE account_id = 'checking'"
        ).fetchall()
        split_ids = [s[0] for s in splits]

        finish_reconciliation(
            con, "checking", split_ids,
            "2026-01-31", 50000, 0,
        )

        for sid in split_ids:
            rec = con.execute(
                "SELECT reconcile FROM splits WHERE id = ?", (sid,)
            ).fetchone()
            assert rec[0] == "r"

    def test_reconciled_splits_excluded_from_next_session(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2026-01-15", "Jan deposit", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        split = con.execute(
            "SELECT id FROM splits WHERE account_id = 'checking'"
        ).fetchone()

        finish_reconciliation(
            con, "checking", [split[0]],
            "2026-01-31", 50000, 0,
        )

        # Add a new transaction
        post_transaction(con, "2026-02-10", "Feb deposit", [
            ("checking", 25000),
            ("hosting_rev", -25000),
        ])

        # Next session should only see the new one
        unrec = get_unreconciled_splits(con, "checking", "2026-02-28")
        assert len(unrec) == 1
        assert unrec[0]["description"] == "Feb deposit"

        # Beginning balance should reflect reconciled amount
        assert get_reconciled_balance(con, "checking") == 50000


class TestSaveReconciliationProgress:
    def test_marks_cleared(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2026-01-15", "Deposit", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        split = con.execute(
            "SELECT id FROM splits WHERE account_id = 'checking'"
        ).fetchone()

        save_reconciliation_progress(
            con, "checking", [split[0]], [],
            "2026-01-31", 50000,
        )

        rec = con.execute(
            "SELECT reconcile FROM splits WHERE id = ?", (split[0],)
        ).fetchone()
        assert rec[0] == "c"

    def test_unmarks_cleared(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2026-01-15", "Deposit", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        split = con.execute(
            "SELECT id FROM splits WHERE account_id = 'checking'"
        ).fetchone()

        # First mark as cleared
        con.execute(
            "UPDATE splits SET reconcile = 'c' WHERE id = ?", (split[0],)
        )
        con.commit()

        # Then unmark
        save_reconciliation_progress(
            con, "checking", [], [split[0]],
            "2026-01-31", 50000,
        )

        rec = con.execute(
            "SELECT reconcile FROM splits WHERE id = ?", (split[0],)
        ).fetchone()
        assert rec[0] == "n"

    def test_does_not_downgrade_reconciled(self, sample_accounts):
        """save_reconciliation_progress should not touch 'r' splits."""
        con = sample_accounts
        post_transaction(con, "2026-01-15", "Deposit", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        split = con.execute(
            "SELECT id FROM splits WHERE account_id = 'checking'"
        ).fetchone()

        # Mark as fully reconciled
        con.execute(
            "UPDATE splits SET reconcile = 'r' WHERE id = ?", (split[0],)
        )
        con.commit()

        # Try to clear it -- should not change 'r' to 'c'
        save_reconciliation_progress(
            con, "checking", [split[0]], [],
            "2026-01-31", 50000,
        )

        rec = con.execute(
            "SELECT reconcile FROM splits WHERE id = ?", (split[0],)
        ).fetchone()
        assert rec[0] == "r"

    def test_saves_session_info(self, sample_accounts):
        """save_reconciliation_progress should persist statement date/balance."""
        con = sample_accounts
        post_transaction(con, "2026-01-15", "Deposit", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        split = con.execute(
            "SELECT id FROM splits WHERE account_id = 'checking'"
        ).fetchone()

        save_reconciliation_progress(
            con, "checking", [split[0]], [],
            "2026-01-31", 50000,
        )

        session = get_reconcile_session(con, "checking")
        assert session is not None
        assert session["statement_date"] == "2026-01-31"
        assert session["statement_balance"] == 50000

    def test_finish_clears_session(self, sample_accounts):
        """finish_reconciliation should delete the in-progress session."""
        con = sample_accounts
        post_transaction(con, "2026-01-15", "Deposit", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        split = con.execute(
            "SELECT id FROM splits WHERE account_id = 'checking'"
        ).fetchone()

        # Save a session first
        save_reconciliation_progress(
            con, "checking", [split[0]], [],
            "2026-01-31", 50000,
        )
        assert get_reconcile_session(con, "checking") is not None

        # Finish reconciliation
        finish_reconciliation(
            con, "checking", [split[0]],
            "2026-01-31", 50000, 0,
        )
        assert get_reconcile_session(con, "checking") is None

    def test_cleared_splits_show_prechecked(self, sample_accounts):
        """Splits saved as 'c' should appear pre-checked in next session."""
        con = sample_accounts
        post_transaction(con, "2026-01-10", "Already cleared", [
            ("checking", 30000),
            ("hosting_rev", -30000),
        ])
        post_transaction(con, "2026-01-20", "Not cleared", [
            ("checking", 20000),
            ("hosting_rev", -20000),
        ])

        splits = get_unreconciled_splits(con, "checking", "2026-01-31")
        # Clear only the first
        save_reconciliation_progress(
            con, "checking",
            [splits[0]["split_id"]], [splits[1]["split_id"]],
            "2026-01-31", 50000,
        )

        # Reload
        refreshed = get_unreconciled_splits(con, "checking", "2026-01-31")
        assert len(refreshed) == 2
        statuses = {s["description"]: s["reconcile"] for s in refreshed}
        assert statuses["Already cleared"] == "c"
        assert statuses["Not cleared"] == "n"


class TestReconciliationId:
    def test_finish_sets_reconciliation_id(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2026-01-15", "Deposit", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        split = con.execute(
            "SELECT id FROM splits WHERE account_id = 'checking'"
        ).fetchone()

        rec_id = finish_reconciliation(
            con, "checking", [split[0]],
            "2026-01-31", 50000, 0,
        )

        row = con.execute(
            "SELECT reconciliation_id FROM splits WHERE id = ?", (split[0],)
        ).fetchone()
        assert row[0] == rec_id

    def test_multiple_splits_all_get_reconciliation_id(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2026-01-10", "Deposit 1", [
            ("checking", 30000),
            ("hosting_rev", -30000),
        ])
        post_transaction(con, "2026-01-20", "Deposit 2", [
            ("checking", 20000),
            ("hosting_rev", -20000),
        ])
        splits = con.execute(
            "SELECT id FROM splits WHERE account_id = 'checking'"
        ).fetchall()
        split_ids = [s[0] for s in splits]

        rec_id = finish_reconciliation(
            con, "checking", split_ids,
            "2026-01-31", 50000, 0,
        )

        for sid in split_ids:
            row = con.execute(
                "SELECT reconciliation_id FROM splits WHERE id = ?", (sid,)
            ).fetchone()
            assert row[0] == rec_id

    def test_second_reconciliation_has_different_id(self, sample_accounts):
        con = sample_accounts
        # First reconciliation
        post_transaction(con, "2026-01-15", "Jan deposit", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        split1 = con.execute(
            "SELECT id FROM splits WHERE account_id = 'checking'"
        ).fetchone()
        rec_id_1 = finish_reconciliation(
            con, "checking", [split1[0]],
            "2026-01-31", 50000, 0,
        )

        # Second reconciliation
        post_transaction(con, "2026-02-15", "Feb deposit", [
            ("checking", 25000),
            ("hosting_rev", -25000),
        ])
        split2 = con.execute(
            "SELECT id FROM splits WHERE account_id = 'checking' "
            "AND reconciliation_id IS NULL"
        ).fetchone()
        rec_id_2 = finish_reconciliation(
            con, "checking", [split2[0]],
            "2026-02-28", 75000, 50000,
        )

        assert rec_id_1 != rec_id_2
        row1 = con.execute(
            "SELECT reconciliation_id FROM splits WHERE id = ?", (split1[0],)
        ).fetchone()
        row2 = con.execute(
            "SELECT reconciliation_id FROM splits WHERE id = ?", (split2[0],)
        ).fetchone()
        assert row1[0] == rec_id_1
        assert row2[0] == rec_id_2

    def test_unreconciled_splits_have_null_reconciliation_id(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2026-01-15", "Deposit", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        row = con.execute(
            "SELECT reconciliation_id FROM splits WHERE account_id = 'checking'"
        ).fetchone()
        assert row[0] is None


class TestGetAccountReconciliations:
    def test_empty(self, sample_accounts):
        con = sample_accounts
        assert get_all_reconciliations(con, "checking") == []

    def test_returns_reconciliations(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2026-01-15", "Deposit", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        split = con.execute(
            "SELECT id FROM splits WHERE account_id = 'checking'"
        ).fetchone()
        finish_reconciliation(
            con, "checking", [split[0]],
            "2026-01-31", 50000, 0,
        )

        recs = get_all_reconciliations(con, "checking")
        assert len(recs) == 1
        assert recs[0]["account_name"] == "Main Checking"
        assert recs[0]["statement_date"] == "2026-01-31"

    def test_scoped_to_account(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2026-01-15", "Deposit", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        split = con.execute(
            "SELECT id FROM splits WHERE account_id = 'checking'"
        ).fetchone()
        finish_reconciliation(
            con, "checking", [split[0]],
            "2026-01-31", 50000, 0,
        )

        assert get_all_reconciliations(con, "usbank") == []


class TestGetAllReconciliations:
    def test_empty(self, sample_accounts):
        con = sample_accounts
        assert get_all_reconciliations(con) == []

    def test_returns_all(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2026-01-15", "Deposit", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        split = con.execute(
            "SELECT id FROM splits WHERE account_id = 'checking'"
        ).fetchone()
        finish_reconciliation(
            con, "checking", [split[0]],
            "2026-01-31", 50000, 0,
        )

        recs = get_all_reconciliations(con)
        assert len(recs) == 1
        assert recs[0]["account_name"] == "Main Checking"


# -- UI tests --


class TestReconcileSetupUI:
    async def test_e_opens_reconcile_setup(self, app):
        from pyre.ui.reconcile_screen import ReconcileSetupScreen

        async with app.run_test() as pilot:
            await pilot.press("e")
            assert isinstance(app.screen, ReconcileSetupScreen)

    async def test_escape_dismisses_setup(self, app):
        async with app.run_test() as pilot:
            await pilot.press("e")
            await pilot.press("escape")
            title = app.query_one("#ledger-title")
            assert "All Transactions" in str(title.content)

    async def test_setup_has_account_picker(self, app):
        async with app.run_test() as pilot:
            await pilot.press("e")
            picker = app.screen.query_one("#rs-account-picker", FuzzySelect)
            assert picker is not None
            assert picker.query_one(".fs-filter", Input) is not None
            assert picker.query_one(".fs-results", OptionList) is not None

    async def test_picker_hides_after_account_selected(self, app):
        async with app.run_test() as pilot:
            await pilot.press("e")
            screen = app.screen
            picker = screen.query_one("#rs-account-picker", FuzzySelect)
            filter_input = picker.query_one(".fs-filter", Input)
            results = picker.query_one(".fs-results", OptionList)
            chosen_label = picker.query_one(".fs-chosen", Label)

            # Before selection: filter and results visible, chosen label hidden
            assert filter_input.display is True
            assert results.display is True
            assert chosen_label.display is False

            # Type to narrow to one account, then press enter to select
            filter_input.value = "Main"
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            # After selection: filter and results hidden, chosen label visible
            assert filter_input.display is False
            assert results.display is False
            assert chosen_label.display is True
            assert "Main Checking" in str(chosen_label.content)

            # Account should be stored on the FuzzySelect widget
            assert picker.value == "checking"

            # Focus should have moved to the date field
            from pyre.dates import DateInput
            assert isinstance(app.focused, DateInput)

    async def test_setup_has_date_and_balance_inputs(self, app):
        async with app.run_test() as pilot:
            await pilot.press("e")
            date_input = app.screen.query_one("#rs-stmt-date")
            balance_input = app.screen.query_one("#rs-stmt-balance")
            assert date_input is not None
            assert balance_input is not None

    async def test_setup_shows_validation_error(self, app):
        async with app.run_test() as pilot:
            await pilot.press("e")
            # Trigger continue without filling in fields
            app.screen._do_continue()
            await pilot.pause()
            error = app.screen.query_one("#rs-error")
            # Should show some validation error (account, date, or balance)
            assert str(error.content) != ""


class TestReconcileWorksheetUI:
    @pytest.fixture
    def reconcile_app(self, ui_db):
        """App with transactions ready for reconciliation."""
        # Mark one split as cleared (simulating bank import)
        split = ui_db.execute(
            "SELECT id FROM splits WHERE account_id = 'checking' "
            "ORDER BY rowid LIMIT 1"
        ).fetchone()
        if split:
            ui_db.execute(
                "UPDATE splits SET reconcile = 'c' WHERE id = ?",
                (split[0],),
            )
            ui_db.commit()
        return PyreApp(con=ui_db)

    async def test_worksheet_shows_splits(self, reconcile_app):
        from pyre.ui.reconcile_screen import ReconcileWorksheetScreen

        async with reconcile_app.run_test() as pilot:
            # Push worksheet directly with setup info
            setup_info = {
                "account_id": "checking",
                "account_name": "Main Checking",
                "account_type": "asset",
                "statement_date": "2026-02-28",
                "statement_balance": 35000,
                "beginning_balance": 0,
            }
            reconcile_app.push_screen(
                ReconcileWorksheetScreen(reconcile_app.con, setup_info)
            )
            await pilot.pause()

            assert isinstance(reconcile_app.screen, ReconcileWorksheetScreen)
            table = reconcile_app.screen.query_one("#rw-table")
            # checking has 2 splits: the $500 deposit and -$150 colo payment
            assert table.row_count == 2

    async def test_worksheet_prechecks_cleared(self, reconcile_app):
        from pyre.ui.reconcile_screen import ReconcileWorksheetScreen

        async with reconcile_app.run_test() as pilot:
            setup_info = {
                "account_id": "checking",
                "account_name": "Main Checking",
                "account_type": "asset",
                "statement_date": "2026-02-28",
                "statement_balance": 35000,
                "beginning_balance": 0,
            }
            screen = ReconcileWorksheetScreen(reconcile_app.con, setup_info)
            reconcile_app.push_screen(screen)
            await pilot.pause()

            # At least one split should be pre-cleared
            assert len(screen._cleared) >= 1

    async def test_space_toggles_checkmark(self, reconcile_app):
        from pyre.ui.reconcile_screen import ReconcileWorksheetScreen

        async with reconcile_app.run_test() as pilot:
            setup_info = {
                "account_id": "checking",
                "account_name": "Main Checking",
                "account_type": "asset",
                "statement_date": "2026-02-28",
                "statement_balance": 35000,
                "beginning_balance": 0,
            }
            screen = ReconcileWorksheetScreen(reconcile_app.con, setup_info)
            reconcile_app.push_screen(screen)
            await pilot.pause()

            table = screen.query_one("#rw-table")
            table.focus()

            initial_count = len(screen._cleared)
            await pilot.press("space")
            # Should have toggled one item
            assert len(screen._cleared) != initial_count

    async def test_a_selects_all(self, reconcile_app):
        from pyre.ui.reconcile_screen import ReconcileWorksheetScreen

        async with reconcile_app.run_test() as pilot:
            setup_info = {
                "account_id": "checking",
                "account_name": "Main Checking",
                "account_type": "asset",
                "statement_date": "2026-02-28",
                "statement_balance": 35000,
                "beginning_balance": 0,
            }
            screen = ReconcileWorksheetScreen(reconcile_app.con, setup_info)
            reconcile_app.push_screen(screen)
            await pilot.pause()

            table = screen.query_one("#rw-table")
            table.focus()
            await pilot.press("a")

            assert len(screen._cleared) == len(screen._splits)

    async def test_n_clears_all(self, reconcile_app):
        from pyre.ui.reconcile_screen import ReconcileWorksheetScreen

        async with reconcile_app.run_test() as pilot:
            setup_info = {
                "account_id": "checking",
                "account_name": "Main Checking",
                "account_type": "asset",
                "statement_date": "2026-02-28",
                "statement_balance": 35000,
                "beginning_balance": 0,
            }
            screen = ReconcileWorksheetScreen(reconcile_app.con, setup_info)
            reconcile_app.push_screen(screen)
            await pilot.pause()

            table = screen.query_one("#rw-table")
            table.focus()
            await pilot.press("a")  # select all first
            await pilot.press("n")  # clear all

            assert len(screen._cleared) == 0

    async def test_escape_cancels_worksheet(self, reconcile_app):
        from pyre.ui.reconcile_screen import ReconcileWorksheetScreen

        async with reconcile_app.run_test() as pilot:
            setup_info = {
                "account_id": "checking",
                "account_name": "Main Checking",
                "account_type": "asset",
                "statement_date": "2026-02-28",
                "statement_balance": 35000,
                "beginning_balance": 0,
            }
            reconcile_app.push_screen(
                ReconcileWorksheetScreen(reconcile_app.con, setup_info)
            )
            await pilot.pause()

            await pilot.press("escape")
            assert not isinstance(
                reconcile_app.screen, ReconcileWorksheetScreen
            )

    async def test_enter_blocked_when_unbalanced(self, reconcile_app):
        from pyre.ui.reconcile_screen import ReconcileWorksheetScreen

        async with reconcile_app.run_test() as pilot:
            setup_info = {
                "account_id": "checking",
                "account_name": "Main Checking",
                "account_type": "asset",
                "statement_date": "2026-02-28",
                "statement_balance": 99999999,  # impossible balance
                "beginning_balance": 0,
            }
            screen = ReconcileWorksheetScreen(reconcile_app.con, setup_info)
            reconcile_app.push_screen(screen)
            await pilot.pause()

            table = screen.query_one("#rw-table")
            table.focus()
            await pilot.press("a")  # select all
            await pilot.press("enter")
            await pilot.pause()

            # Should still be on the worksheet (not dismissed)
            assert isinstance(reconcile_app.screen, ReconcileWorksheetScreen)

    async def test_enter_finishes_when_balanced(self, reconcile_app):
        """Pressing Enter on the DataTable finalizes when difference is $0."""
        from pyre.ui.reconcile_screen import ReconcileWorksheetScreen

        async with reconcile_app.run_test() as pilot:
            # checking has +50000 and -15000 = net 35000
            setup_info = {
                "account_id": "checking",
                "account_name": "Main Checking",
                "account_type": "asset",
                "statement_date": "2026-02-28",
                "statement_balance": 35000,
                "beginning_balance": 0,
            }
            screen = ReconcileWorksheetScreen(reconcile_app.con, setup_info)
            reconcile_app.push_screen(screen)
            await pilot.pause()

            table = screen.query_one("#rw-table")
            table.focus()
            await pilot.press("a")  # select all -- difference should be $0
            await pilot.press("enter")
            await pilot.pause()

            # Should be dismissed
            assert not isinstance(
                reconcile_app.screen, ReconcileWorksheetScreen
            )

            # Splits should be reconciled
            rows = reconcile_app.con.execute(
                "SELECT reconcile FROM splits WHERE account_id = 'checking'"
            ).fetchall()
            assert all(r[0] == "r" for r in rows)

    async def test_finish_later_saves_progress(self, reconcile_app):
        from pyre.ui.reconcile_screen import ReconcileWorksheetScreen

        async with reconcile_app.run_test() as pilot:
            setup_info = {
                "account_id": "checking",
                "account_name": "Main Checking",
                "account_type": "asset",
                "statement_date": "2026-02-28",
                "statement_balance": 35000,
                "beginning_balance": 0,
            }
            screen = ReconcileWorksheetScreen(reconcile_app.con, setup_info)
            reconcile_app.push_screen(screen)
            await pilot.pause()

            table = screen.query_one("#rw-table")
            table.focus()
            await pilot.press("a")  # select all
            await pilot.press("w")  # finish later
            await pilot.pause()

            # Should be dismissed
            assert not isinstance(
                reconcile_app.screen, ReconcileWorksheetScreen
            )

            # Splits should be cleared (c) not reconciled (r)
            rows = reconcile_app.con.execute(
                "SELECT reconcile FROM splits WHERE account_id = 'checking'"
            ).fetchall()
            assert all(r[0] == "c" for r in rows)

    async def test_setup_prefills_from_saved_session(self, reconcile_app):
        """After 'finish later', re-opening setup pre-fills date and balance."""
        from pyre.ui.reconcile_screen import (
            ReconcileSetupScreen,
            ReconcileWorksheetScreen,
        )

        async with reconcile_app.run_test() as pilot:
            # First: open worksheet and save for later
            setup_info = {
                "account_id": "checking",
                "account_name": "Main Checking",
                "account_type": "asset",
                "statement_date": "2026-02-28",
                "statement_balance": 35000,
                "beginning_balance": 0,
            }
            screen = ReconcileWorksheetScreen(reconcile_app.con, setup_info)
            reconcile_app.push_screen(screen)
            await pilot.pause()

            table = screen.query_one("#rw-table")
            table.focus()
            await pilot.press("a")
            await pilot.press("w")  # finish later
            await pilot.pause()

            # Now open setup again for the same account
            setup = ReconcileSetupScreen(
                reconcile_app.con, "checking", "Main Checking",
            )
            reconcile_app.push_screen(setup)
            await pilot.pause()

            # Date and balance should be pre-filled
            date_val = setup.query_one("#rs-stmt-date").value
            balance_val = setup.query_one("#rs-stmt-balance").value
            assert date_val == "02-28-2026"
            assert balance_val == "$350.00"

            # Info label should mention resuming
            info = str(setup.query_one("#rs-last-info").content)
            assert "resuming" in info.lower()


class TestQuickFunctionPickerUI:
    """Tests for the quick function picker in the reconciliation worksheet."""

    SETUP_INFO = {
        "account_id": "checking",
        "account_name": "Main Checking",
        "account_type": "asset",
        "statement_date": "2026-02-28",
        "statement_balance": 35000,
        "beginning_balance": 0,
    }

    @pytest.fixture
    def qf_yaml(self, tmp_path):
        """Write a quick_functions.yaml and return the fake db_path."""
        db_path = tmp_path / "pyre.db"
        db_path.touch()
        yaml_path = tmp_path / "quick_functions.yaml"
        yaml_path.write_text(textwrap.dedent("""\
            - key: "1"
              group: Payments
              label: Test Payment
              description: Test payment from checking
              splits:
                - account: checking
                  direction: debit
                  prompt: Amount
                - account: cap1
                  direction: credit
                  prompt: null
            - key: "2"
              group: Revenue
              label: Test Revenue
              description: Test revenue deposit
              splits:
                - account: checking
                  direction: debit
                  prompt: Deposit
                - account: hosting_rev
                  direction: credit
                  prompt: null
        """))
        return db_path

    async def test_q_opens_picker(self, ui_db, qf_yaml):
        from pyre.ui.reconcile_screen import (
            QuickFunctionPickerScreen,
            ReconcileWorksheetScreen,
        )

        app = PyreApp(con=ui_db, db_path=qf_yaml)
        async with app.run_test() as pilot:
            screen = ReconcileWorksheetScreen(ui_db, self.SETUP_INFO)
            app.push_screen(screen)
            await pilot.pause()

            table = screen.query_one("#rw-table")
            table.focus()
            await pilot.press("q")
            await pilot.pause()

            assert isinstance(app.screen, QuickFunctionPickerScreen)

    async def test_picker_lists_all_quick_functions(self, ui_db, qf_yaml):
        from pyre.ui.reconcile_screen import (
            QuickFunctionPickerScreen,
            ReconcileWorksheetScreen,
        )

        app = PyreApp(con=ui_db, db_path=qf_yaml)
        async with app.run_test() as pilot:
            screen = ReconcileWorksheetScreen(ui_db, self.SETUP_INFO)
            app.push_screen(screen)
            await pilot.pause()

            table = screen.query_one("#rw-table")
            table.focus()
            await pilot.press("q")
            await pilot.pause()

            ol = app.screen.query_one("#qfp-list", OptionList)
            assert ol.option_count == 2

    async def test_escape_dismisses_picker(self, ui_db, qf_yaml):
        from pyre.ui.reconcile_screen import (
            QuickFunctionPickerScreen,
            ReconcileWorksheetScreen,
        )

        app = PyreApp(con=ui_db, db_path=qf_yaml)
        async with app.run_test() as pilot:
            screen = ReconcileWorksheetScreen(ui_db, self.SETUP_INFO)
            app.push_screen(screen)
            await pilot.pause()

            table = screen.query_one("#rw-table")
            table.focus()
            await pilot.press("q")
            await pilot.pause()

            await pilot.press("escape")
            await pilot.pause()

            # Should be back on the worksheet, not the picker
            assert isinstance(app.screen, ReconcileWorksheetScreen)

    async def test_enter_selects_and_opens_quick_entry(self, ui_db, qf_yaml):
        from pyre.ui.reconcile_screen import ReconcileWorksheetScreen
        from pyre.ui.screens import QuickEntryScreen

        app = PyreApp(con=ui_db, db_path=qf_yaml)
        async with app.run_test() as pilot:
            screen = ReconcileWorksheetScreen(ui_db, self.SETUP_INFO)
            app.push_screen(screen)
            await pilot.pause()

            table = screen.query_one("#rw-table")
            table.focus()
            await pilot.press("q")
            await pilot.pause()

            # Select the first quick function
            await pilot.press("enter")
            await pilot.pause()

            assert isinstance(app.screen, QuickEntryScreen)

    async def test_q_warns_when_no_quick_functions(self, ui_db, tmp_path):
        from pyre.ui.reconcile_screen import ReconcileWorksheetScreen

        # No quick_functions.yaml
        db_path = tmp_path / "pyre.db"
        db_path.touch()
        app = PyreApp(con=ui_db, db_path=db_path)
        async with app.run_test() as pilot:
            screen = ReconcileWorksheetScreen(ui_db, self.SETUP_INFO)
            app.push_screen(screen)
            await pilot.pause()

            table = screen.query_one("#rw-table")
            table.focus()
            await pilot.press("q")
            await pilot.pause()

            # Should still be on the worksheet (no picker opened)
            assert isinstance(app.screen, ReconcileWorksheetScreen)

    @pytest.fixture
    def qf_yaml_with_letters(self, tmp_path):
        """Write a quick_functions.yaml with digit and letter keys."""
        db_path = tmp_path / "pyre.db"
        db_path.touch()
        yaml_path = tmp_path / "quick_functions.yaml"
        yaml_path.write_text(textwrap.dedent("""\
            - key: "1"
              group: Payments
              label: Test Payment
              description: Test payment from checking
              splits:
                - account: checking
                  direction: debit
                  prompt: Amount
                - account: cap1
                  direction: credit
                  prompt: null
            - key: "t"
              group: Services
              label: ACME Corp
              description: ACME monthly service
              splits:
                - account: checking
                  direction: debit
                  prompt: Amount
                - account: hosting_rev
                  direction: credit
                  prompt: null
        """))
        return db_path

    async def test_letter_key_selects_quick_function(self, ui_db, qf_yaml_with_letters):
        """Pressing a letter key in the picker selects the matching QF."""
        from pyre.ui.reconcile_screen import ReconcileWorksheetScreen
        from pyre.ui.screens import QuickEntryScreen

        app = PyreApp(con=ui_db, db_path=qf_yaml_with_letters)
        async with app.run_test() as pilot:
            screen = ReconcileWorksheetScreen(ui_db, self.SETUP_INFO)
            app.push_screen(screen)
            await pilot.pause()

            table = screen.query_one("#rw-table")
            table.focus()
            await pilot.press("q")
            await pilot.pause()

            # Press "t" to select the ACME quick function
            await pilot.press("t")
            await pilot.pause()

            assert isinstance(app.screen, QuickEntryScreen)

    async def test_digit_key_selects_quick_function(self, ui_db, qf_yaml_with_letters):
        """Pressing a digit key in the picker selects the matching QF."""
        from pyre.ui.reconcile_screen import ReconcileWorksheetScreen
        from pyre.ui.screens import QuickEntryScreen

        app = PyreApp(con=ui_db, db_path=qf_yaml_with_letters)
        async with app.run_test() as pilot:
            screen = ReconcileWorksheetScreen(ui_db, self.SETUP_INFO)
            app.push_screen(screen)
            await pilot.pause()

            table = screen.query_one("#rw-table")
            table.focus()
            await pilot.press("q")
            await pilot.pause()

            # Press "1" to select the Test Payment quick function
            await pilot.press("1")
            await pilot.pause()

            assert isinstance(app.screen, QuickEntryScreen)
