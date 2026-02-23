"""UI tests for bulk select mode and bulk edit dialog."""

import pytest

from pyre.ui.app import PyreApp


@pytest.fixture
def bulk_app(ui_db):
    """PyreApp with vendors seeded for bulk edit tests."""
    ui_db.executemany(
        "INSERT INTO vendors (id, name) VALUES (?, ?)",
        [("acme", "Acme Inc"), ("globex", "Globex Corp")],
    )
    ui_db.commit()
    return PyreApp(con=ui_db)


# -- Entering and exiting bulk mode --

async def test_b_enters_bulk_mode(bulk_app):
    """Pressing B should activate bulk select mode and show the indicator."""
    async with bulk_app.run_test() as pilot:
        table = bulk_app.query_one("#ledger-table")
        table.focus()

        await pilot.press("B")

        assert bulk_app._bulk_mode is True
        indicator = bulk_app.query_one("#bulk-indicator")
        assert indicator.has_class("active")


async def test_b_exits_bulk_mode(bulk_app):
    """Pressing B again should deactivate bulk mode."""
    async with bulk_app.run_test() as pilot:
        table = bulk_app.query_one("#ledger-table")
        table.focus()

        await pilot.press("B")
        await pilot.press("B")

        assert bulk_app._bulk_mode is False
        indicator = bulk_app.query_one("#bulk-indicator")
        assert not indicator.has_class("active")


async def test_escape_exits_bulk_mode(bulk_app):
    """Pressing Escape in bulk mode should exit it."""
    async with bulk_app.run_test() as pilot:
        table = bulk_app.query_one("#ledger-table")
        table.focus()

        await pilot.press("B")
        assert bulk_app._bulk_mode is True

        await pilot.press("escape")
        assert bulk_app._bulk_mode is False


async def test_exit_bulk_clears_selections(bulk_app):
    """Exiting bulk mode should clear any selections."""
    async with bulk_app.run_test() as pilot:
        table = bulk_app.query_one("#ledger-table")
        table.focus()

        await pilot.press("B")
        await pilot.press("space")  # select first row
        assert len(bulk_app._selected_tx_ids) == 1

        await pilot.press("B")  # exit
        assert len(bulk_app._selected_tx_ids) == 0


# -- Selection toggling --

async def test_space_selects_in_bulk_mode(bulk_app):
    """Space should toggle selection on current row in bulk mode."""
    async with bulk_app.run_test() as pilot:
        table = bulk_app.query_one("#ledger-table")
        table.focus()

        await pilot.press("B")
        await pilot.press("space")

        assert len(bulk_app._selected_tx_ids) == 1


async def test_space_deselects_in_bulk_mode(bulk_app):
    """Pressing space on an already-selected row should deselect it."""
    async with bulk_app.run_test() as pilot:
        table = bulk_app.query_one("#ledger-table")
        table.focus()

        await pilot.press("B")
        await pilot.press("space")  # select row 0, cursor advances to row 1
        assert len(bulk_app._selected_tx_ids) == 1

        await pilot.press("up")  # go back to row 0
        await pilot.press("space")  # deselect row 0
        assert len(bulk_app._selected_tx_ids) == 0


async def test_select_multiple_rows(bulk_app):
    """Should be able to select multiple different transactions."""
    async with bulk_app.run_test() as pilot:
        table = bulk_app.query_one("#ledger-table")
        table.focus()

        await pilot.press("B")
        await pilot.press("space")  # select row 0, cursor moves to row 1
        await pilot.press("space")  # select row 1, cursor moves to row 2

        assert len(bulk_app._selected_tx_ids) == 2


async def test_space_advances_cursor(bulk_app):
    """Space in bulk mode should advance cursor to the next row."""
    async with bulk_app.run_test() as pilot:
        table = bulk_app.query_one("#ledger-table")
        table.focus()

        await pilot.press("B")
        assert table.cursor_row == 0

        await pilot.press("space")
        assert table.cursor_row == 1


async def test_space_stays_on_last_row(bulk_app):
    """Space on the last row should not move cursor past the end."""
    async with bulk_app.run_test() as pilot:
        table = bulk_app.query_one("#ledger-table")
        table.focus()
        last_row = table.row_count - 1

        await pilot.press("B")
        table.move_cursor(row=last_row)

        await pilot.press("space")
        assert table.cursor_row == last_row
        assert len(bulk_app._selected_tx_ids) == 1


# -- Enter in bulk mode --

async def test_enter_with_no_selection_warns(bulk_app):
    """Enter in bulk mode with no selections should notify, not open dialog."""
    from pyre.ui.screens import BulkEditScreen

    async with bulk_app.run_test() as pilot:
        table = bulk_app.query_one("#ledger-table")
        table.focus()

        await pilot.press("B")
        await pilot.press("enter")

        assert not isinstance(bulk_app.screen, BulkEditScreen)


async def test_enter_with_selection_opens_bulk_edit(bulk_app):
    """Enter in bulk mode with selections should open BulkEditScreen."""
    from pyre.ui.screens import BulkEditScreen

    async with bulk_app.run_test() as pilot:
        table = bulk_app.query_one("#ledger-table")
        table.focus()

        await pilot.press("B")
        await pilot.press("space")  # select current row
        await pilot.press("enter")

        assert isinstance(bulk_app.screen, BulkEditScreen)


async def test_bulk_edit_cancel_keeps_selections(bulk_app):
    """Cancelling bulk edit should not clear selections or exit bulk mode."""
    from pyre.ui.screens import BulkEditScreen

    async with bulk_app.run_test() as pilot:
        table = bulk_app.query_one("#ledger-table")
        table.focus()

        await pilot.press("B")
        await pilot.press("space")
        await pilot.press("enter")

        assert isinstance(bulk_app.screen, BulkEditScreen)
        await pilot.press("escape")

        # Should be back on main screen, still in bulk mode with selection
        assert not isinstance(bulk_app.screen, BulkEditScreen)


async def test_bulk_edit_saves_vendor(bulk_app):
    """Saving in bulk edit should assign vendor to all selected transactions."""
    from pyre.ui.screens import BulkEditScreen
    from textual.widgets import Select

    async with bulk_app.run_test() as pilot:
        table = bulk_app.query_one("#ledger-table")
        table.focus()

        # Select two transactions (space auto-advances cursor)
        await pilot.press("B")
        await pilot.press("space")  # select row 0, advance to row 1
        await pilot.press("space")  # select row 1, advance to row 2
        selected_ids = set(bulk_app._selected_tx_ids)
        await pilot.press("enter")

        assert isinstance(bulk_app.screen, BulkEditScreen)

        # Set vendor to "Acme Inc"
        vendor_select = bulk_app.screen.query_one("#be-vendor", Select)
        vendor_select.value = "acme"

        # Click Save
        await pilot.click("#be-save")

        # Verify vendor was set on the selected transactions
        for tx_id in selected_ids:
            row = bulk_app.con.execute(
                "SELECT vendor_id FROM transactions WHERE id = ?", (tx_id,)
            ).fetchone()
            assert row[0] == "acme"


async def test_bulk_edit_clear_vendor(bulk_app):
    """Saving with blank vendor should clear vendor_id."""
    async with bulk_app.run_test() as pilot:
        table = bulk_app.query_one("#ledger-table")
        table.focus()

        # First set a vendor on a transaction
        tx_id = bulk_app._ledger_data[0][3]
        bulk_app.con.execute(
            "UPDATE transactions SET vendor_id = 'acme' WHERE id = ?", (tx_id,)
        )
        bulk_app.con.commit()

        # Enter bulk mode, select that row, open edit
        await pilot.press("B")
        await pilot.press("space")
        await pilot.press("enter")

        # Save with blank (default) - should clear vendor
        await pilot.click("#be-save")

        row = bulk_app.con.execute(
            "SELECT vendor_id FROM transactions WHERE id = ?", (tx_id,)
        ).fetchone()
        assert row[0] is None


# -- Normal space still works outside bulk mode --

async def test_space_expands_splits_outside_bulk(bulk_app):
    """Space should expand splits (not select) when not in bulk mode."""
    async with bulk_app.run_test() as pilot:
        table = bulk_app.query_one("#ledger-table")
        table.focus()

        await pilot.press("space")
        assert len(bulk_app._selected_tx_ids) == 0
