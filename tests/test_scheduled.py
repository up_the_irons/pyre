import pytest

from pyre.scheduled_models import (
    create_scheduled_transaction,
    update_scheduled_transaction,
    delete_scheduled_transaction,
    get_all_scheduled_transactions,
    get_scheduled_transaction_detail,
    get_pending_scheduled_transactions,
    enter_scheduled_transaction,
    enter_pending_transactions,
    toggle_scheduled_enabled,
    _advance_date,
)
from pyre.models import get_transaction_detail


class TestScheduledCRUD:
    def test_create_and_get_all(self, sample_accounts):
        con = sample_accounts
        st_id = create_scheduled_transaction(
            con, "Monthly Rent", "monthly", "2026-03-01",
            [("datacenter", 100000), ("checking", -100000)],
        )
        assert st_id is not None
        all_st = get_all_scheduled_transactions(con)
        assert len(all_st) == 1
        assert all_st[0]["description"] == "Monthly Rent"
        assert all_st[0]["frequency"] == "monthly"
        assert all_st[0]["amount"] == 100000

    def test_get_detail(self, sample_accounts):
        con = sample_accounts
        st_id = create_scheduled_transaction(
            con, "Payroll", "biweekly", "2026-03-15",
            [("payroll", 500000), ("checking", -500000)],
        )
        st, splits = get_scheduled_transaction_detail(con, st_id)
        assert st["description"] == "Payroll"
        assert st["frequency"] == "biweekly"
        assert st["next_date"] == "2026-03-15"
        assert st["enabled"] is True
        assert len(splits) == 2
        amounts = sorted([s["amount"] for s in splits])
        assert amounts == [-500000, 500000]

    def test_get_detail_not_found(self, sample_accounts):
        con = sample_accounts
        st, splits = get_scheduled_transaction_detail(con, "nonexistent")
        assert st is None
        assert splits == []

    def test_update_replaces_splits(self, sample_accounts):
        con = sample_accounts
        st_id = create_scheduled_transaction(
            con, "Original", "monthly", "2026-03-01",
            [("datacenter", 50000), ("checking", -50000)],
        )
        update_scheduled_transaction(
            con, st_id, "Updated", "weekly", "2026-04-01",
            [("cloud", 30000), ("payroll", 20000), ("checking", -50000)],
            enabled=False,
        )
        st, splits = get_scheduled_transaction_detail(con, st_id)
        assert st["description"] == "Updated"
        assert st["frequency"] == "weekly"
        assert st["next_date"] == "2026-04-01"
        assert st["enabled"] is False
        assert len(splits) == 3

    def test_delete(self, sample_accounts):
        con = sample_accounts
        st_id = create_scheduled_transaction(
            con, "To Delete", "monthly", "2026-03-01",
            [("datacenter", 10000), ("checking", -10000)],
        )
        delete_scheduled_transaction(con, st_id)
        st, splits = get_scheduled_transaction_detail(con, st_id)
        assert st is None
        assert get_all_scheduled_transactions(con) == []

    def test_create_with_vendor(self, sample_vendors):
        con = sample_vendors
        st_id = create_scheduled_transaction(
            con, "Vendor Bill", "monthly", "2026-03-01",
            [("datacenter", 10000), ("cap1", -10000)],
            vendor_id="acme_inc",
        )
        all_st = get_all_scheduled_transactions(con)
        assert all_st[0]["vendor_name"] == "Acme Inc"
        assert all_st[0]["vendor_id"] == "acme_inc"

    def test_create_with_end_date(self, sample_accounts):
        con = sample_accounts
        st_id = create_scheduled_transaction(
            con, "Temp", "monthly", "2026-03-01",
            [("datacenter", 10000), ("checking", -10000)],
            end_date="2026-06-01",
        )
        st, _ = get_scheduled_transaction_detail(con, st_id)
        assert st["end_date"] == "2026-06-01"

    def test_create_with_split_descriptions(self, sample_accounts):
        con = sample_accounts
        st_id = create_scheduled_transaction(
            con, "Described", "monthly", "2026-03-01",
            [("datacenter", 10000, "Server costs"), ("checking", -10000, "Payment")],
        )
        _, splits = get_scheduled_transaction_detail(con, st_id)
        descs = sorted([s["description"] for s in splits])
        assert "Payment" in descs
        assert "Server costs" in descs


class TestBalanceValidation:
    def test_create_unbalanced_raises(self, sample_accounts):
        con = sample_accounts
        with pytest.raises(ValueError, match="does not balance"):
            create_scheduled_transaction(
                con, "Bad", "monthly", "2026-03-01",
                [("datacenter", 10000), ("checking", -5000)],
            )

    def test_update_unbalanced_raises(self, sample_accounts):
        con = sample_accounts
        st_id = create_scheduled_transaction(
            con, "Good", "monthly", "2026-03-01",
            [("datacenter", 10000), ("checking", -10000)],
        )
        with pytest.raises(ValueError, match="does not balance"):
            update_scheduled_transaction(
                con, st_id, "Bad", "monthly", "2026-03-01",
                [("datacenter", 10000), ("checking", -5000)],
            )


class TestPendingDetection:
    def test_due_today_returned(self, sample_accounts):
        con = sample_accounts
        create_scheduled_transaction(
            con, "Due Today", "monthly", "2026-02-21",
            [("datacenter", 10000), ("checking", -10000)],
        )
        pending = get_pending_scheduled_transactions(con, as_of="2026-02-21")
        assert len(pending) == 1
        assert pending[0]["description"] == "Due Today"

    def test_past_due_returned(self, sample_accounts):
        con = sample_accounts
        create_scheduled_transaction(
            con, "Past Due", "monthly", "2026-02-01",
            [("datacenter", 10000), ("checking", -10000)],
        )
        pending = get_pending_scheduled_transactions(con, as_of="2026-02-21")
        assert len(pending) == 1

    def test_future_excluded(self, sample_accounts):
        con = sample_accounts
        create_scheduled_transaction(
            con, "Future", "monthly", "2026-03-01",
            [("datacenter", 10000), ("checking", -10000)],
        )
        pending = get_pending_scheduled_transactions(con, as_of="2026-02-21")
        assert len(pending) == 0

    def test_disabled_excluded(self, sample_accounts):
        con = sample_accounts
        st_id = create_scheduled_transaction(
            con, "Disabled", "monthly", "2026-02-01",
            [("datacenter", 10000), ("checking", -10000)],
        )
        toggle_scheduled_enabled(con, st_id)
        pending = get_pending_scheduled_transactions(con, as_of="2026-02-21")
        assert len(pending) == 0

    def test_past_end_date_excluded(self, sample_accounts):
        con = sample_accounts
        create_scheduled_transaction(
            con, "Expired", "monthly", "2026-02-15",
            [("datacenter", 10000), ("checking", -10000)],
            end_date="2026-02-01",
        )
        pending = get_pending_scheduled_transactions(con, as_of="2026-02-21")
        assert len(pending) == 0


class TestDateAdvancement:
    def test_weekly(self):
        assert _advance_date("2026-02-21", "weekly") == "2026-02-28"

    def test_biweekly(self):
        assert _advance_date("2026-02-21", "biweekly") == "2026-03-07"

    def test_monthly(self):
        assert _advance_date("2026-02-15", "monthly") == "2026-03-15"

    def test_monthly_end_of_month(self):
        # Jan 31 + 1 month = Feb 28
        assert _advance_date("2026-01-31", "monthly") == "2026-02-28"

    def test_monthly_end_of_month_march(self):
        # Mar 31 + 1 month = Apr 30
        assert _advance_date("2026-03-31", "monthly") == "2026-04-30"

    def test_quarterly(self):
        assert _advance_date("2026-01-15", "quarterly") == "2026-04-15"

    def test_quarterly_end_of_month(self):
        # Nov 30 + 3 months = Feb 28
        assert _advance_date("2025-11-30", "quarterly") == "2026-02-28"

    def test_yearly(self):
        assert _advance_date("2026-02-21", "yearly") == "2027-02-21"

    def test_yearly_leap_year(self):
        # Feb 29, 2024 + 1 year = Feb 28, 2025
        assert _advance_date("2024-02-29", "yearly") == "2025-02-28"

    def test_monthly_december_wraps(self):
        assert _advance_date("2026-12-15", "monthly") == "2027-01-15"


class TestEnterScheduledTransaction:
    def test_posts_real_transaction(self, sample_accounts):
        con = sample_accounts
        st_id = create_scheduled_transaction(
            con, "Rent Payment", "monthly", "2026-02-01",
            [("datacenter", 100000), ("checking", -100000)],
        )
        tx_id = enter_scheduled_transaction(con, st_id)
        assert tx_id is not None
        tx, splits = get_transaction_detail(con, tx_id)
        assert tx is not None
        assert tx[1] == "2026-02-01"  # date
        assert tx[2] == "Rent Payment"  # description

    def test_advances_next_date(self, sample_accounts):
        con = sample_accounts
        st_id = create_scheduled_transaction(
            con, "Monthly", "monthly", "2026-02-01",
            [("datacenter", 10000), ("checking", -10000)],
        )
        enter_scheduled_transaction(con, st_id)
        st, _ = get_scheduled_transaction_detail(con, st_id)
        assert st["next_date"] == "2026-03-01"

    def test_disables_when_past_end_date(self, sample_accounts):
        con = sample_accounts
        st_id = create_scheduled_transaction(
            con, "Ending", "monthly", "2026-02-01",
            [("datacenter", 10000), ("checking", -10000)],
            end_date="2026-02-15",
        )
        enter_scheduled_transaction(con, st_id)
        st, _ = get_scheduled_transaction_detail(con, st_id)
        assert st["enabled"] is False

    def test_posts_with_vendor(self, sample_vendors):
        con = sample_vendors
        st_id = create_scheduled_transaction(
            con, "Vendor Bill", "monthly", "2026-02-01",
            [("datacenter", 10000), ("cap1", -10000)],
            vendor_id="acme_inc",
        )
        tx_id = enter_scheduled_transaction(con, st_id)
        tx, _ = get_transaction_detail(con, tx_id)
        assert tx[4] == "acme_inc"


class TestMultiPeriodCatchUp:
    def test_posts_all_due_occurrences(self, sample_accounts):
        con = sample_accounts
        # Monthly starting Jan 1, checking as of Mar 15 = 3 occurrences
        st_id = create_scheduled_transaction(
            con, "Monthly Bill", "monthly", "2026-01-01",
            [("datacenter", 10000), ("checking", -10000)],
        )
        posted = enter_pending_transactions(con, [st_id], as_of="2026-03-15")
        assert len(posted) == 3
        st, _ = get_scheduled_transaction_detail(con, st_id)
        assert st["next_date"] == "2026-04-01"

    def test_respects_end_date(self, sample_accounts):
        con = sample_accounts
        # Monthly starting Jan 1, end_date Feb 15 -> posts Jan and Feb, then disables
        st_id = create_scheduled_transaction(
            con, "Ending Bill", "monthly", "2026-01-01",
            [("datacenter", 10000), ("checking", -10000)],
            end_date="2026-02-15",
        )
        posted = enter_pending_transactions(con, [st_id], as_of="2026-06-01")
        assert len(posted) == 2
        st, _ = get_scheduled_transaction_detail(con, st_id)
        assert st["enabled"] is False

    def test_skips_disabled(self, sample_accounts):
        con = sample_accounts
        st_id = create_scheduled_transaction(
            con, "Disabled", "monthly", "2026-01-01",
            [("datacenter", 10000), ("checking", -10000)],
        )
        toggle_scheduled_enabled(con, st_id)
        posted = enter_pending_transactions(con, [st_id], as_of="2026-06-01")
        assert len(posted) == 0

    def test_multiple_schedules(self, sample_accounts):
        con = sample_accounts
        st1 = create_scheduled_transaction(
            con, "Bill A", "monthly", "2026-02-01",
            [("datacenter", 10000), ("checking", -10000)],
        )
        st2 = create_scheduled_transaction(
            con, "Bill B", "weekly", "2026-02-14",
            [("cloud", 5000), ("checking", -5000)],
        )
        posted = enter_pending_transactions(con, [st1, st2], as_of="2026-02-21")
        # st1: 1 occurrence (Feb 1), st2: 2 occurrences (Feb 14, Feb 21)
        assert len(posted) == 3


class TestToggleEnabled:
    def test_toggle_disables(self, sample_accounts):
        con = sample_accounts
        st_id = create_scheduled_transaction(
            con, "Toggle Me", "monthly", "2026-03-01",
            [("datacenter", 10000), ("checking", -10000)],
        )
        toggle_scheduled_enabled(con, st_id)
        st, _ = get_scheduled_transaction_detail(con, st_id)
        assert st["enabled"] is False

    def test_toggle_re_enables(self, sample_accounts):
        con = sample_accounts
        st_id = create_scheduled_transaction(
            con, "Toggle Me", "monthly", "2026-03-01",
            [("datacenter", 10000), ("checking", -10000)],
        )
        toggle_scheduled_enabled(con, st_id)
        toggle_scheduled_enabled(con, st_id)
        st, _ = get_scheduled_transaction_detail(con, st_id)
        assert st["enabled"] is True

    def test_toggle_nonexistent(self, sample_accounts):
        con = sample_accounts
        # Should not raise
        toggle_scheduled_enabled(con, "nonexistent")


# -- UI Tests --

from pyre.ui.app import PyreApp


async def test_pending_screen_appears_on_launch(ui_db):
    """Pending review screen should appear when scheduled txns are due."""
    create_scheduled_transaction(
        ui_db, "Due Bill", "monthly", "2026-02-01",
        [("office", 5000), ("cap1", -5000)],
    )
    app = PyreApp(con=ui_db)
    async with app.run_test() as pilot:
        await pilot.pause()
        # The PendingScheduledScreen should be on the screen stack
        from pyre.ui.scheduled_screen import PendingScheduledScreen
        screens = [type(s).__name__ for s in app.screen_stack]
        assert "PendingScheduledScreen" in screens


async def test_pending_post_all(ui_db):
    """Post All should create transactions and dismiss."""
    create_scheduled_transaction(
        ui_db, "Due Bill", "monthly", "2026-02-01",
        [("office", 5000), ("cap1", -5000)],
    )
    app = PyreApp(con=ui_db)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Click Post All
        await pilot.click("#ps-post")
        await pilot.pause()
        # Should be dismissed back to main
        screens = [type(s).__name__ for s in app.screen_stack]
        assert "PendingScheduledScreen" not in screens
        # Transaction should be posted (original 3 + 1 scheduled)
        tx_count = ui_db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        assert tx_count == 4


async def test_pending_skip_excludes(ui_db):
    """Pressing space should toggle skip, and Post All should exclude skipped."""
    create_scheduled_transaction(
        ui_db, "Skip Me", "monthly", "2026-02-01",
        [("office", 5000), ("cap1", -5000)],
    )
    create_scheduled_transaction(
        ui_db, "Post Me", "monthly", "2026-02-15",
        [("hosting_exp", 3000), ("checking", -3000)],
    )
    app = PyreApp(con=ui_db)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Toggle skip on first row (skip it)
        table = app.screen.query_one("#ps-table")
        table.focus()
        await pilot.press("space")
        await pilot.pause()
        # Post All -- only the second should be posted
        await pilot.click("#ps-post")
        await pilot.pause()
        # 3 original + 1 posted (the one not skipped)
        tx_count = ui_db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        assert tx_count == 4


async def test_scheduled_list_opens_via_S(ui_db):
    """Pressing S should open the ScheduledListScreen."""
    app = PyreApp(con=ui_db)
    async with app.run_test() as pilot:
        await pilot.press("S")
        await pilot.pause()
        from pyre.ui.scheduled_screen import ScheduledListScreen
        screens = [type(s).__name__ for s in app.screen_stack]
        assert "ScheduledListScreen" in screens
