from unittest.mock import patch
from datetime import date

import pytest

from pyre.dates import DateInput, parse_date


class TestParseDate:
    def test_iso_passthrough(self):
        assert parse_date("2026-01-05") == "2026-01-05"

    def test_two_digit_year(self):
        assert parse_date("1/5/26") == "2026-01-05"

    def test_four_digit_year(self):
        assert parse_date("1/5/2026") == "2026-01-05"

    def test_iso_style_with_slashes(self):
        assert parse_date("2026/01/05") == "2026-01-05"

    @patch("pyre.dates.date")
    def test_shorthand_current_year(self, mock_date):
        mock_date.today.return_value = date(2026, 2, 16)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        # Feb 1 is close to Feb 16, should be current year
        assert parse_date("2/1") == "2026-02-01"

    @patch("pyre.dates.date")
    def test_shorthand_rolls_to_last_year(self, mock_date):
        mock_date.today.return_value = date(2026, 2, 16)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        # Sep 15 is >6 months in the future from Feb -> last year
        assert parse_date("9/15") == "2025-09-15"

    @patch("pyre.dates.date")
    def test_shorthand_rolls_to_next_year(self, mock_date):
        mock_date.today.return_value = date(2026, 11, 1)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        # Feb 15 is >6 months in the past from Nov -> next year
        assert parse_date("2/15") == "2027-02-15"

    @patch("pyre.dates.date")
    def test_day_only(self, mock_date):
        mock_date.today.return_value = date(2026, 2, 16)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        assert parse_date("15") == "2026-02-15"

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="Empty date"):
            parse_date("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="Empty date"):
            parse_date("   ")

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_date("not-a-date")

    def test_dashes_as_separators(self):
        assert parse_date("01-05-2026") == "2026-01-05"

    def test_invalid_day_for_month(self):
        with pytest.raises(ValueError):
            parse_date("2/30/2026")

    def test_feb_29_non_leap_year(self):
        with pytest.raises(ValueError):
            parse_date("2/29/2025")


class TestDateInputStepping:
    """Test +/= and - keys to step dates forward/back in DateInput."""

    @pytest.fixture
    def app(self):
        from textual.app import App, ComposeResult

        class DateApp(App):
            def compose(self) -> ComposeResult:
                yield DateInput(value="02-15-2026", id="date")

        return DateApp()

    async def test_minus_steps_back_one_day(self, app):
        async with app.run_test() as pilot:
            inp = app.query_one("#date", DateInput)
            inp.focus()
            await pilot.press("-")
            assert inp.value == "02-14-2026"

    async def test_plus_steps_forward_one_day(self, app):
        async with app.run_test() as pilot:
            inp = app.query_one("#date", DateInput)
            inp.focus()
            await pilot.press("+")
            assert inp.value == "02-16-2026"

    async def test_equals_steps_forward_one_day(self, app):
        async with app.run_test() as pilot:
            inp = app.query_one("#date", DateInput)
            inp.focus()
            await pilot.press("=")
            assert inp.value == "02-16-2026"

    async def test_multiple_steps(self, app):
        async with app.run_test() as pilot:
            inp = app.query_one("#date", DateInput)
            inp.focus()
            await pilot.press("-")
            await pilot.press("-")
            await pilot.press("-")
            assert inp.value == "02-12-2026"

    async def test_step_across_month_boundary(self, app):
        from textual.app import App, ComposeResult

        class MarchApp(App):
            def compose(self) -> ComposeResult:
                yield DateInput(value="03-01-2026", id="date")

        async with MarchApp().run_test() as pilot:
            inp = pilot.app.query_one("#date", DateInput)
            inp.focus()
            await pilot.press("-")
            assert inp.value == "02-28-2026"

    async def test_step_does_nothing_on_empty(self, app):
        async with app.run_test() as pilot:
            inp = app.query_one("#date", DateInput)
            inp.value = ""
            inp.focus()
            await pilot.press("-")
            assert inp.value == ""
