"""Tests for the main ledger search (/) functionality."""

from textual.widgets import DataTable, Input


async def _type_into(pilot, text):
    """Simulate typing by pressing each character individually."""
    for char in text:
        await pilot.press(char)


# -- Opening and closing the search bar --

async def test_slash_opens_search_bar(app):
    """Pressing '/' should show the search bar and focus the input."""
    async with app.run_test() as pilot:
        await pilot.press("/")

        bar = app.query_one("#search-bar")
        assert "visible" in bar.classes
        assert app.query_one("#search-input", Input).has_focus


async def test_escape_closes_search_bar(app):
    """Pressing Escape while searching should hide the bar and clear the filter."""
    async with app.run_test() as pilot:
        await pilot.press("/")
        await pilot.press("escape")

        bar = app.query_one("#search-bar")
        assert "visible" not in bar.classes
        title = app.query_one("#ledger-title")
        assert "All Transactions" in str(title.content)


async def test_enter_confirms_search(app):
    """Enter should close the bar but keep the filter active."""
    async with app.run_test() as pilot:
        await pilot.press("/")
        await _type_into(pilot, "Amazon")
        await pilot.press("enter")

        # Bar hidden
        bar = app.query_one("#search-bar")
        assert "visible" not in bar.classes

        # Filter still active -- title shows search query
        title = str(app.query_one("#ledger-title").content)
        assert "Amazon" in title

        # Table focused for navigation
        assert app.query_one("#ledger-table", DataTable).has_focus


# -- Live filtering --

async def test_search_filters_ledger(app):
    """Typing in the search bar should live-filter the ledger rows."""
    async with app.run_test() as pilot:
        await pilot.press("/")
        # "Amazon" only matches "Office Supplies - Amazon"
        await _type_into(pilot, "Amazon")

        table = app.query_one("#ledger-table", DataTable)
        assert table.row_count == 1


async def test_search_no_matches(app):
    """A search with no matches should show 0 rows."""
    async with app.run_test() as pilot:
        await pilot.press("/")
        await _type_into(pilot, "xyznonexistent")

        table = app.query_one("#ledger-table", DataTable)
        assert table.row_count == 0

        title = str(app.query_one("#ledger-title").content)
        assert "xyznonexistent" in title


async def test_search_case_insensitive(app):
    """Search should be case-insensitive."""
    async with app.run_test() as pilot:
        await pilot.press("/")
        await _type_into(pilot, "amazon")

        table = app.query_one("#ledger-table", DataTable)
        assert table.row_count == 1


async def test_search_matches_account_names(app):
    """Search should also match account names in splits."""
    async with app.run_test() as pilot:
        await pilot.press("/")
        # "Hosting" matches both the revenue and expense account names
        await _type_into(pilot, "Hosting")

        table = app.query_one("#ledger-table", DataTable)
        assert table.row_count == 2


async def test_reopen_search_recalls_query_without_selection(app):
    """Reopening search with '/' should pre-fill the query with cursor at end, no selection."""
    async with app.run_test() as pilot:
        await pilot.press("/")
        await _type_into(pilot, "Amazon")
        await pilot.press("enter")  # confirm filter

        # Reopen search
        await pilot.press("/")
        search_input = app.query_one("#search-input", Input)
        assert search_input.value == "Amazon"
        assert search_input.cursor_position == len("Amazon")
        # No text should be selected (selection start == end == cursor)
        sel = search_input.selection
        assert sel.start == sel.end, (
            f"Text should not be selected, but selection is {sel}"
        )


async def test_reopen_search_and_escape_clears_filter(app):
    """After confirming search, reopening with '/' and pressing Escape clears it."""
    async with app.run_test() as pilot:
        await pilot.press("/")
        await _type_into(pilot, "Amazon")
        await pilot.press("enter")  # confirm

        # Filter is active
        table = app.query_one("#ledger-table", DataTable)
        assert table.row_count == 1

        # Reopen search and escape to clear
        await pilot.press("/")
        await pilot.press("escape")

        assert table.row_count == 3
        assert "All Transactions" in str(app.query_one("#ledger-title").content)
