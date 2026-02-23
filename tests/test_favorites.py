"""Tests for sidebar favorites keyboard shortcuts (f + digit)."""

import pytest

from pyre.ui.app import PyreApp


@pytest.fixture
def fav_app(ui_db):
    """PyreApp with two sidebar-flagged accounts."""
    # Mark checking and cap1 as sidebar favorites
    ui_db.execute("UPDATE accounts SET sidebar = 1 WHERE id = 'checking'")
    ui_db.execute("UPDATE accounts SET sidebar = 1 WHERE id = 'cap1'")
    ui_db.commit()
    return PyreApp(con=ui_db)


@pytest.fixture
def no_fav_app(ui_db):
    """PyreApp with no sidebar favorites."""
    return PyreApp(con=ui_db)


# -- Sidebar display --

async def test_sidebar_shows_favorite_keys(fav_app):
    """Favorite accounts should display [f1], [f2] keys in the sidebar."""
    async with fav_app.run_test() as pilot:
        labels = fav_app.query(".fav-key")
        texts = [str(lbl.content) for lbl in labels]
        assert "[f1]" in texts[0]
        assert "[f2]" in texts[1]


async def test_sidebar_stores_account_list(fav_app):
    """refresh_balances should populate _sidebar_accounts."""
    async with fav_app.run_test() as pilot:
        assert len(fav_app._sidebar_accounts) == 2
        names = [name for _, name, _ in fav_app._sidebar_accounts]
        assert "Rewards Visa" in names
        assert "Main Checking" in names


# -- Favorites mode activation --

async def test_f_enters_favorites_mode(fav_app):
    """Pressing 'f' should activate favorites mode."""
    async with fav_app.run_test() as pilot:
        fav_app.query_one("#ledger-table").focus()
        await pilot.press("f")
        assert fav_app._favorites_mode is True


async def test_f_highlights_keys(fav_app):
    """Pressing 'f' should add fav-key-active class to key labels."""
    async with fav_app.run_test() as pilot:
        fav_app.query_one("#ledger-table").focus()
        await pilot.press("f")
        active = fav_app.query(".fav-key-active")
        assert len(active) == 2


async def test_f_with_no_favorites_warns(no_fav_app):
    """Pressing 'f' with no sidebar accounts should not enter favorites mode."""
    async with no_fav_app.run_test() as pilot:
        no_fav_app.query_one("#ledger-table").focus()
        await pilot.press("f")
        assert no_fav_app._favorites_mode is False


# -- Account selection --

async def test_f_then_1_selects_first_account(fav_app):
    """Pressing 'f' then '1' should navigate to the first sidebar account."""
    async with fav_app.run_test() as pilot:
        fav_app.query_one("#ledger-table").focus()
        await pilot.press("f")
        await pilot.press("1")

        assert fav_app._favorites_mode is False
        assert fav_app.account_filter is not None
        first_id, first_name, _ = fav_app._sidebar_accounts[0]
        assert fav_app.account_filter["id"] == first_id
        assert fav_app.account_filter["name"] == first_name


async def test_f_then_2_selects_second_account(fav_app):
    """Pressing 'f' then '2' should navigate to the second sidebar account."""
    async with fav_app.run_test() as pilot:
        fav_app.query_one("#ledger-table").focus()
        await pilot.press("f")
        await pilot.press("2")

        assert fav_app._favorites_mode is False
        second_id, second_name, _ = fav_app._sidebar_accounts[1]
        assert fav_app.account_filter["id"] == second_id
        assert fav_app.account_filter["name"] == second_name


async def test_f_then_digit_shows_account_transactions(fav_app):
    """After selecting a favorite, the ledger title should show the account name."""
    async with fav_app.run_test() as pilot:
        fav_app.query_one("#ledger-table").focus()
        await pilot.press("f")
        await pilot.press("1")

        title = str(fav_app.query_one("#ledger-title").content)
        first_name = fav_app._sidebar_accounts[0][1]
        assert first_name in title


async def test_f_then_out_of_range_digit_warns(fav_app):
    """Pressing a digit beyond the number of favorites should not crash."""
    async with fav_app.run_test() as pilot:
        fav_app.query_one("#ledger-table").focus()
        await pilot.press("f")
        await pilot.press("9")

        assert fav_app._favorites_mode is False
        assert fav_app.account_filter is None


# -- Cancellation --

async def test_f_then_escape_cancels(fav_app):
    """Pressing escape after 'f' should cancel favorites mode."""
    async with fav_app.run_test() as pilot:
        fav_app.query_one("#ledger-table").focus()
        await pilot.press("f")
        assert fav_app._favorites_mode is True

        await pilot.press("escape")
        assert fav_app._favorites_mode is False
        assert fav_app.account_filter is None


async def test_f_then_escape_removes_highlight(fav_app):
    """Cancelling favorites mode should remove the active highlight."""
    async with fav_app.run_test() as pilot:
        fav_app.query_one("#ledger-table").focus()
        await pilot.press("f")
        await pilot.press("escape")
        active = fav_app.query(".fav-key-active")
        assert len(active) == 0


async def test_f_then_non_digit_cancels(fav_app):
    """Pressing a non-digit key after 'f' should cancel favorites mode."""
    async with fav_app.run_test() as pilot:
        fav_app.query_one("#ledger-table").focus()
        await pilot.press("f")
        await pilot.press("x")
        assert fav_app._favorites_mode is False
        assert fav_app.account_filter is None
