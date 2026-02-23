"""UI tests for the Pyre TUI using Textual's Pilot framework."""


# -- App loads and shows main screen --

async def test_app_loads_with_recent_transactions(app):
    """The app should mount and show 'All Transactions' as the ledger title."""
    async with app.run_test() as pilot:
        title = app.query_one("#ledger-title")
        assert "All Transactions" in str(title.content)


async def test_ledger_has_rows(app):
    """The ledger table should contain our seeded transactions."""
    async with app.run_test() as pilot:
        table = app.query_one("#ledger-table")
        assert table.row_count == 3


# -- Keyboard navigation --

async def test_arrow_down_moves_cursor(app):
    """Pressing arrow-down should advance the cursor row."""
    async with app.run_test() as pilot:
        table = app.query_one("#ledger-table")
        table.focus()
        start_row = table.cursor_row

        await pilot.press("down")
        assert table.cursor_row == start_row + 1


async def test_arrow_up_moves_cursor(app):
    """Pressing arrow-up from row 1 should move back to row 0."""
    async with app.run_test() as pilot:
        table = app.query_one("#ledger-table")
        table.focus()

        await pilot.press("down")
        await pilot.press("up")
        assert table.cursor_row == 0


async def test_j_moves_cursor_down(app):
    """Vim-style 'j' should move the cursor down."""
    async with app.run_test() as pilot:
        table = app.query_one("#ledger-table")
        table.focus()
        start_row = table.cursor_row

        await pilot.press("j")
        assert table.cursor_row == start_row + 1


async def test_k_moves_cursor_up(app):
    """Vim-style 'k' should move the cursor up."""
    async with app.run_test() as pilot:
        table = app.query_one("#ledger-table")
        table.focus()

        await pilot.press("j")  # down first
        await pilot.press("k")
        assert table.cursor_row == 0


# -- Enter opens EditTransactionScreen --

async def test_enter_opens_edit_screen(app):
    """Pressing Enter on a ledger row should push EditTransactionScreen."""
    from pyre.ui.screens import EditTransactionScreen

    async with app.run_test() as pilot:
        table = app.query_one("#ledger-table")
        table.focus()

        await pilot.press("enter")

        # The top screen on the stack should be the edit modal
        assert isinstance(app.screen, EditTransactionScreen)


async def test_escape_dismisses_edit_screen(app):
    """Pressing Escape in the edit screen should return to the main screen."""
    async with app.run_test() as pilot:
        table = app.query_one("#ledger-table")
        table.focus()

        await pilot.press("enter")  # open edit screen
        await pilot.press("escape")  # dismiss it

        # Should be back on the main screen with the ledger visible
        title = app.query_one("#ledger-title")
        assert "All Transactions" in str(title.content)
