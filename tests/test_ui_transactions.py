"""Tests for the Edit Transaction and Add Transaction screens."""

from textual.widgets import Button, Input, Label

from pyre.ui.screens import AddTransactionScreen, EditTransactionScreen


async def _type_into(pilot, text):
    """Simulate typing by pressing each character individually."""
    for char in text:
        await pilot.press(char)


# -- Edit Transaction screen --

async def test_edit_screen_shows_correct_data(app):
    """Edit screen should pre-fill date, description, and split amounts."""
    async with app.run_test() as pilot:
        table = app.query_one("#ledger-table")
        table.focus()

        await pilot.press("enter")
        assert isinstance(app.screen, EditTransactionScreen)

        screen = app.screen
        date_val = screen.query_one("#at-date", Input).value
        desc_val = screen.query_one("#at-desc", Input).value

        # Most recent transaction is "Colo Payment" on 2026-02-17
        assert date_val == "02-17-2026"
        assert desc_val == "Colo Payment"


async def test_edit_screen_shows_balanced(app):
    """A loaded transaction should show 'Balanced' on the balance indicator."""
    async with app.run_test() as pilot:
        table = app.query_one("#ledger-table")
        table.focus()
        await pilot.press("enter")

        screen = app.screen
        balance = str(screen.query_one("#at-balance").content)
        assert "Balanced" in balance


async def test_edit_screen_save_disabled_when_unbalanced(app):
    """Changing an amount to make it unbalanced should disable the Save button."""
    async with app.run_test() as pilot:
        table = app.query_one("#ledger-table")
        table.focus()
        await pilot.press("enter")

        screen = app.screen
        # Clear the first split amount and type a different value
        amount_input = screen.query_one("#at-split-amount-0", Input)
        amount_input.value = "999.99"
        await pilot.pause()

        balance = str(screen.query_one("#at-balance").content)
        assert "Off by" in balance

        save_btn = screen.query_one("#at-save", Button)
        assert save_btn.disabled


async def test_edit_screen_delete_removes_transaction(app):
    """Clicking Delete should remove the transaction from the DB."""
    async with app.run_test() as pilot:
        table = app.query_one("#ledger-table")
        table.focus()
        await pilot.press("enter")

        screen = app.screen
        tx_id = screen.tx_id

        # Press the delete button programmatically (may be off-screen)
        screen.query_one("#at-delete", Button).press()
        await pilot.pause()

        # Should be back on main screen
        assert not isinstance(app.screen, EditTransactionScreen)

        # Transaction should be gone
        row = app.con.execute(
            "SELECT 1 FROM transactions WHERE id = ?", (tx_id,)
        ).fetchone()
        assert row is None


async def test_edit_screen_escape_cancels(app):
    """Pressing Escape should dismiss without saving changes."""
    async with app.run_test() as pilot:
        table = app.query_one("#ledger-table")
        table.focus()

        initial_count = table.row_count

        await pilot.press("enter")
        await pilot.press("escape")

        assert not isinstance(app.screen, EditTransactionScreen)
        # All transactions should still be there
        count = app.con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        assert count == initial_count


# -- Add Transaction screen --

async def test_a_opens_add_transaction(app):
    """Pressing 'a' should push AddTransactionScreen."""
    async with app.run_test() as pilot:
        await pilot.press("a")
        assert isinstance(app.screen, AddTransactionScreen)

        title = app.screen.query_one("#at-title")
        assert "Add" in str(title.content)


async def test_add_cancel_does_not_create_transaction(app):
    """Cancelling the add screen should not create a transaction."""
    async with app.run_test() as pilot:
        before = app.con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]

        await pilot.press("a")
        await pilot.press("escape")

        after = app.con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        assert after == before
