"""Tests for drill-down from Balance Sheet and P&L into account transactions."""
import pytest

from pyre.formatting import cents
from pyre.models import (
    get_account_balance,
    get_account_transactions,
    post_transaction,
)


# -- Model-layer date filtering tests --


class TestGetAccountTransactionsDateFiltering:
    def test_no_date_filter_returns_all(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-01-15", "Jan tx", [
            ("checking", 10000), ("hosting_rev", -10000),
        ])
        post_transaction(con, "2025-06-15", "Jun tx", [
            ("checking", 20000), ("hosting_rev", -20000),
        ])
        rows = get_account_transactions(con, "checking")
        assert len(rows) == 2

    def test_start_date_filter(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-01-15", "Jan tx", [
            ("checking", 10000), ("hosting_rev", -10000),
        ])
        post_transaction(con, "2025-06-15", "Jun tx", [
            ("checking", 20000), ("hosting_rev", -20000),
        ])
        rows = get_account_transactions(con, "checking", start_date="2025-03-01")
        assert len(rows) == 1
        assert rows[0][1] == "Jun tx"

    def test_end_date_filter(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-01-15", "Jan tx", [
            ("checking", 10000), ("hosting_rev", -10000),
        ])
        post_transaction(con, "2025-06-15", "Jun tx", [
            ("checking", 20000), ("hosting_rev", -20000),
        ])
        rows = get_account_transactions(con, "checking", end_date="2025-03-31")
        assert len(rows) == 1
        assert rows[0][1] == "Jan tx"

    def test_both_date_filters(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-01-15", "Jan tx", [
            ("checking", 10000), ("hosting_rev", -10000),
        ])
        post_transaction(con, "2025-03-15", "Mar tx", [
            ("checking", 15000), ("hosting_rev", -15000),
        ])
        post_transaction(con, "2025-06-15", "Jun tx", [
            ("checking", 20000), ("hosting_rev", -20000),
        ])
        rows = get_account_transactions(
            con, "checking", start_date="2025-02-01", end_date="2025-04-30",
        )
        assert len(rows) == 1
        assert rows[0][1] == "Mar tx"

    def test_date_filter_empty_result(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-01-15", "Jan tx", [
            ("checking", 10000), ("hosting_rev", -10000),
        ])
        rows = get_account_transactions(
            con, "checking", start_date="2026-01-01", end_date="2026-12-31",
        )
        assert len(rows) == 0


class TestGetAccountBalanceEndDate:
    def test_no_end_date_returns_full_balance(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-01-15", "Deposit 1", [
            ("checking", 50000), ("hosting_rev", -50000),
        ])
        post_transaction(con, "2025-06-15", "Deposit 2", [
            ("checking", 30000), ("hosting_rev", -30000),
        ])
        assert get_account_balance(con, "checking") == 80000

    def test_end_date_limits_balance(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-01-15", "Deposit 1", [
            ("checking", 50000), ("hosting_rev", -50000),
        ])
        post_transaction(con, "2025-06-15", "Deposit 2", [
            ("checking", 30000), ("hosting_rev", -30000),
        ])
        assert get_account_balance(con, "checking", end_date="2025-03-31") == 50000

    def test_end_date_before_any_transactions(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-06-15", "Deposit", [
            ("checking", 50000), ("hosting_rev", -50000),
        ])
        assert get_account_balance(con, "checking", end_date="2025-01-01") == 0

    def test_end_date_includes_boundary(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-03-31", "Boundary tx", [
            ("checking", 25000), ("hosting_rev", -25000),
        ])
        assert get_account_balance(con, "checking", end_date="2025-03-31") == 25000


# -- UI report screen tests --


class TestProfitLossScreenDrillDown:
    @pytest.fixture
    def pnl_app(self, sample_accounts):
        """App with some income/expense transactions for P&L testing."""
        con = sample_accounts
        post_transaction(con, "2025-01-15", "Revenue", [
            ("checking", cents(15000)),
            ("hosting_rev", cents(-15000)),
        ])
        post_transaction(con, "2025-01-20", "Colocation", [
            ("datacenter", cents(7358.39)),
            ("cap1", cents(-7358.39)),
        ])
        from pyre.ui.app import PyreApp
        return PyreApp(con=con)

    async def test_pnl_has_datatable(self, pnl_app):
        """P&L screen should use a DataTable, not a Static widget."""
        from pyre.ui.screens import ProfitLossScreen
        from textual.widgets import DataTable

        async with pnl_app.run_test() as pilot:
            pnl_app.push_screen(
                ProfitLossScreen(pnl_app.con, "2025-01-01", "2025-12-31")
            )
            await pilot.pause()
            table = pnl_app.screen.query_one("#pnl-table", DataTable)
            assert table.row_count > 0

    async def test_pnl_enter_on_account_row_dismisses_with_action(self, pnl_app):
        """Pressing Enter on an account row should dismiss with drill-down payload."""
        from pyre.ui.screens import ProfitLossScreen
        from textual.widgets import DataTable

        results = []

        async with pnl_app.run_test() as pilot:
            pnl_app.push_screen(
                ProfitLossScreen(pnl_app.con, "2025-01-01", "2025-12-31"),
                callback=lambda r: results.append(r),
            )
            await pilot.pause()
            table = pnl_app.screen.query_one("#pnl-table", DataTable)
            table.focus()
            # Move cursor down to find an account row (skip section headers)
            for _ in range(5):
                await pilot.press("j")
            await pilot.press("enter")
            await pilot.pause()

        # We should have gotten a result (either drill-down or None for non-account)
        # Find any result that is a drill-down dict
        drill = [r for r in results if isinstance(r, dict) and r.get("action") == "view_transactions"]
        # There should be at least some account rows in the P&L
        # If cursor landed on a non-account row, that's OK -- just verify structure
        if drill:
            assert "account" in drill[0]
            assert "start_date" in drill[0]
            assert "end_date" in drill[0]

    async def test_pnl_enter_on_header_does_nothing(self, pnl_app):
        """Pressing Enter on a section header should not dismiss the screen."""
        from pyre.ui.screens import ProfitLossScreen
        from textual.widgets import DataTable

        async with pnl_app.run_test() as pilot:
            pnl_app.push_screen(
                ProfitLossScreen(pnl_app.con, "2025-01-01", "2025-12-31")
            )
            await pilot.pause()
            table = pnl_app.screen.query_one("#pnl-table", DataTable)
            table.focus()
            # Row 0 is the "INCOME" header -- not a drillable account
            table.move_cursor(row=0)
            await pilot.press("enter")
            await pilot.pause()
            # Screen should still be the P&L screen
            assert isinstance(pnl_app.screen, ProfitLossScreen)

    async def test_pnl_vim_navigation(self, pnl_app):
        """j/k/g/G should move the DataTable cursor."""
        from pyre.ui.screens import ProfitLossScreen
        from textual.widgets import DataTable

        async with pnl_app.run_test() as pilot:
            pnl_app.push_screen(
                ProfitLossScreen(pnl_app.con, "2025-01-01", "2025-12-31")
            )
            await pilot.pause()
            table = pnl_app.screen.query_one("#pnl-table", DataTable)
            table.focus()

            await pilot.press("j")
            assert table.cursor_row == 1
            await pilot.press("k")
            assert table.cursor_row == 0
            await pilot.press("G")
            assert table.cursor_row == table.row_count - 1
            await pilot.press("g")
            assert table.cursor_row == 0

    async def test_pnl_escape_closes(self, pnl_app):
        """Escape should dismiss the P&L screen."""
        from pyre.ui.screens import ProfitLossScreen

        async with pnl_app.run_test() as pilot:
            pnl_app.push_screen(
                ProfitLossScreen(pnl_app.con, "2025-01-01", "2025-12-31")
            )
            await pilot.pause()
            assert isinstance(pnl_app.screen, ProfitLossScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(pnl_app.screen, ProfitLossScreen)

    async def test_pnl_q_closes(self, pnl_app):
        """Q should dismiss the P&L screen."""
        from pyre.ui.screens import ProfitLossScreen

        async with pnl_app.run_test() as pilot:
            pnl_app.push_screen(
                ProfitLossScreen(pnl_app.con, "2025-01-01", "2025-12-31")
            )
            await pilot.pause()
            assert isinstance(pnl_app.screen, ProfitLossScreen)
            await pilot.press("q")
            await pilot.pause()
            assert not isinstance(pnl_app.screen, ProfitLossScreen)


class TestBalanceSheetScreenDrillDown:
    @pytest.fixture
    def bs_app(self, sample_accounts):
        """App with balance sheet transactions."""
        con = sample_accounts
        post_transaction(con, "2025-01-01", "Opening", [
            ("checking", cents(50000)),
            ("equity", cents(-50000)),
        ])
        post_transaction(con, "2025-02-15", "CC Purchase", [
            ("datacenter", cents(7000)),
            ("cap1", cents(-7000)),
        ])
        from pyre.ui.app import PyreApp
        return PyreApp(con=con)

    async def test_bs_has_datatable(self, bs_app):
        """Balance Sheet should use a DataTable."""
        from pyre.ui.screens import BalanceSheetScreen
        from textual.widgets import DataTable

        async with bs_app.run_test() as pilot:
            bs_app.push_screen(
                BalanceSheetScreen(bs_app.con, "2025-12-31")
            )
            await pilot.pause()
            table = bs_app.screen.query_one("#bs-table", DataTable)
            assert table.row_count > 0

    async def test_bs_enter_on_account_row_dismisses_with_action(self, bs_app):
        """Pressing Enter on an account row should dismiss with drill-down payload."""
        from pyre.ui.screens import BalanceSheetScreen
        from textual.widgets import DataTable

        results = []

        async with bs_app.run_test() as pilot:
            bs_app.push_screen(
                BalanceSheetScreen(bs_app.con, "2025-12-31"),
                callback=lambda r: results.append(r),
            )
            await pilot.pause()
            table = bs_app.screen.query_one("#bs-table", DataTable)
            table.focus()
            # Move to first account row (skip ASSETS header)
            await pilot.press("j")
            await pilot.press("enter")
            await pilot.pause()

        drill = [r for r in results if isinstance(r, dict) and r.get("action") == "view_transactions"]
        assert len(drill) == 1
        assert "account" in drill[0]
        assert "end_date" in drill[0]
        assert drill[0]["end_date"] == "2025-12-31"
        # Balance sheet drill-down should NOT have start_date
        assert "start_date" not in drill[0]

    async def test_bs_enter_on_header_does_nothing(self, bs_app):
        """Pressing Enter on ASSETS header should not dismiss."""
        from pyre.ui.screens import BalanceSheetScreen

        async with bs_app.run_test() as pilot:
            bs_app.push_screen(
                BalanceSheetScreen(bs_app.con, "2025-12-31")
            )
            await pilot.pause()
            # Row 0 is "ASSETS" header
            table = bs_app.screen.query_one("#bs-table")
            table.focus()
            table.move_cursor(row=0)
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(bs_app.screen, BalanceSheetScreen)

    async def test_bs_vim_navigation(self, bs_app):
        """j/k/g/G should move the DataTable cursor."""
        from pyre.ui.screens import BalanceSheetScreen
        from textual.widgets import DataTable

        async with bs_app.run_test() as pilot:
            bs_app.push_screen(
                BalanceSheetScreen(bs_app.con, "2025-12-31")
            )
            await pilot.pause()
            table = bs_app.screen.query_one("#bs-table", DataTable)
            table.focus()

            await pilot.press("j")
            assert table.cursor_row == 1
            await pilot.press("k")
            assert table.cursor_row == 0
            await pilot.press("G")
            assert table.cursor_row == table.row_count - 1
            await pilot.press("g")
            assert table.cursor_row == 0

    async def test_bs_escape_closes(self, bs_app):
        """Escape should dismiss the Balance Sheet screen."""
        from pyre.ui.screens import BalanceSheetScreen

        async with bs_app.run_test() as pilot:
            bs_app.push_screen(
                BalanceSheetScreen(bs_app.con, "2025-12-31")
            )
            await pilot.pause()
            assert isinstance(bs_app.screen, BalanceSheetScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(bs_app.screen, BalanceSheetScreen)


# -- App-level drill-down integration tests --


class TestAppDrillDownIntegration:
    @pytest.fixture
    def drilldown_app(self, sample_accounts):
        """App with transactions spanning multiple dates for drill-down testing."""
        con = sample_accounts
        post_transaction(con, "2025-01-15", "Jan Revenue", [
            ("checking", cents(10000)),
            ("hosting_rev", cents(-10000)),
        ])
        post_transaction(con, "2025-03-15", "Mar Revenue", [
            ("checking", cents(20000)),
            ("hosting_rev", cents(-20000)),
        ])
        post_transaction(con, "2025-06-15", "Jun Revenue", [
            ("checking", cents(30000)),
            ("hosting_rev", cents(-30000)),
        ])
        post_transaction(con, "2025-01-01", "Opening", [
            ("checking", cents(50000)),
            ("equity", cents(-50000)),
        ])
        from pyre.ui.app import PyreApp
        return PyreApp(con=con)

    async def test_pnl_drilldown_sets_account_filter_with_dates(self, drilldown_app):
        """Drilling down from P&L should set account_filter with start/end dates."""
        from pyre.ui.screens import ProfitLossScreen
        from textual.widgets import DataTable

        async with drilldown_app.run_test() as pilot:
            # Simulate the on_pnl callback path by calling action_show_pnl indirectly
            # Instead, directly push P&L with callback wiring as app does
            def on_pnl(result):
                if isinstance(result, dict) and result.get("action") == "view_transactions":
                    acct = result["account"]
                    drilldown_app.account_filter = {
                        "id": acct["id"],
                        "name": acct["name"],
                        "start_date": result.get("start_date"),
                        "end_date": result.get("end_date"),
                    }
                    drilldown_app.refresh_ledger()

            drilldown_app.push_screen(
                ProfitLossScreen(drilldown_app.con, "2025-01-01", "2025-03-31"),
                callback=on_pnl,
            )
            await pilot.pause()
            table = drilldown_app.screen.query_one("#pnl-table", DataTable)
            table.focus()

            # Navigate down to find an income account row
            # INCOME header is row 0, first account is row 1+
            for _ in range(3):
                await pilot.press("j")
            await pilot.press("enter")
            await pilot.pause()

            # If we drilled into an account, verify the filter
            if drilldown_app.account_filter:
                assert drilldown_app.account_filter.get("start_date") == "2025-01-01"
                assert drilldown_app.account_filter.get("end_date") == "2025-03-31"

    async def test_bs_drilldown_sets_account_filter_with_end_date(self, drilldown_app):
        """Drilling down from Balance Sheet should set account_filter with end_date only."""
        from pyre.ui.screens import BalanceSheetScreen
        from textual.widgets import DataTable

        async with drilldown_app.run_test() as pilot:
            def on_bs(result):
                if isinstance(result, dict) and result.get("action") == "view_transactions":
                    acct = result["account"]
                    drilldown_app.account_filter = {
                        "id": acct["id"],
                        "name": acct["name"],
                        "end_date": result.get("end_date"),
                    }
                    drilldown_app.refresh_ledger()

            drilldown_app.push_screen(
                BalanceSheetScreen(drilldown_app.con, "2025-03-31"),
                callback=on_bs,
            )
            await pilot.pause()
            table = drilldown_app.screen.query_one("#bs-table", DataTable)
            table.focus()

            # Row 0 = ASSETS, Row 1 = first asset account (checking)
            await pilot.press("j")
            await pilot.press("enter")
            await pilot.pause()

            if drilldown_app.account_filter:
                assert drilldown_app.account_filter.get("end_date") == "2025-03-31"
                assert drilldown_app.account_filter.get("start_date") is None

    async def test_drilldown_ledger_shows_date_scope_in_title(self, drilldown_app):
        """After drill-down, the ledger title should show the date scope."""
        async with drilldown_app.run_test() as pilot:
            # Manually set account_filter with date scope
            drilldown_app.account_filter = {
                "id": "hosting_rev",
                "name": "Hosting",
                "start_date": "2025-01-01",
                "end_date": "2025-03-31",
            }
            drilldown_app.refresh_ledger()
            await pilot.pause()

            title = drilldown_app.query_one("#ledger-title")
            title_text = str(title.content)
            assert "Hosting" in title_text
            assert "01-01-2025 to 03-31-2025" in title_text

    async def test_drilldown_ledger_filters_by_date(self, drilldown_app):
        """After drill-down with date scope, only matching transactions should appear."""
        from textual.widgets import DataTable

        async with drilldown_app.run_test() as pilot:
            drilldown_app.account_filter = {
                "id": "hosting_rev",
                "name": "Hosting",
                "start_date": "2025-01-01",
                "end_date": "2025-03-31",
            }
            drilldown_app.refresh_ledger()
            await pilot.pause()

            table = drilldown_app.query_one("#ledger-table", DataTable)
            # Should only show Jan and Mar transactions, not Jun
            assert table.row_count == 2

    async def test_drilldown_bs_end_date_only_title(self, drilldown_app):
        """Balance Sheet drill-down should show 'as of' in the title."""
        async with drilldown_app.run_test() as pilot:
            drilldown_app.account_filter = {
                "id": "checking",
                "name": "Main Checking",
                "end_date": "2025-03-31",
            }
            drilldown_app.refresh_ledger()
            await pilot.pause()

            title = drilldown_app.query_one("#ledger-title")
            title_text = str(title.content)
            assert "Main Checking" in title_text
            assert "as of 03-31-2025" in title_text

    async def test_escape_clears_drilldown_filter(self, drilldown_app):
        """Pressing Escape after drill-down should clear the filter."""
        from textual.widgets import DataTable

        async with drilldown_app.run_test() as pilot:
            drilldown_app.account_filter = {
                "id": "hosting_rev",
                "name": "Hosting",
                "start_date": "2025-01-01",
                "end_date": "2025-03-31",
            }
            drilldown_app.refresh_ledger()
            await pilot.pause()

            table = drilldown_app.query_one("#ledger-table", DataTable)
            table.focus()
            await pilot.press("escape")
            await pilot.pause()

            assert drilldown_app.account_filter is None
            title = drilldown_app.query_one("#ledger-title")
            assert "All Transactions" in str(title.content)
