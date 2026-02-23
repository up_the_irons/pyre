import os
from pathlib import Path

import pytest

from pyre.reports import resolve_report_path


class TestResolveReportPathNoConfig:
    """When report_output is missing or incomplete, returns None."""

    def test_empty_prefs(self):
        assert resolve_report_path({}, "pnl", "2026-01-31") is None

    def test_no_report_output_key(self):
        prefs = {"theme": "dark"}
        assert resolve_report_path(prefs, "pnl", "2026-01-31") is None

    def test_empty_report_output(self):
        prefs = {"report_output": {}}
        assert resolve_report_path(prefs, "pnl", "2026-01-31") is None

    def test_missing_base_path(self):
        prefs = {"report_output": {"filenames": {"pnl": "P&L.pdf"}}}
        assert resolve_report_path(prefs, "pnl", "2026-01-31") is None

    def test_missing_filenames(self):
        prefs = {"report_output": {"base_path": "/tmp/reports/%Y/"}}
        assert resolve_report_path(prefs, "pnl", "2026-01-31") is None

    def test_missing_report_type_in_filenames(self):
        prefs = {
            "report_output": {
                "base_path": "/tmp/reports/%Y/",
                "filenames": {"pnl": "P&L.pdf"},
            }
        }
        assert resolve_report_path(prefs, "balance_sheet", "2026-01-31") is None


class TestResolveReportPathStrftime:
    """strftime placeholders in base_path and filenames are expanded."""

    def test_year_expansion(self, tmp_path):
        prefs = {
            "report_output": {
                "base_path": str(tmp_path / "%Y/"),
                "filenames": {"pnl": "Profit & Loss.pdf"},
            }
        }
        result = resolve_report_path(prefs, "pnl", "2026-01-31")
        assert result == tmp_path / "2026" / "Profit & Loss.pdf"

    def test_month_number_and_name(self, tmp_path):
        prefs = {
            "report_output": {
                "base_path": str(tmp_path / "%Y/%m - %B/"),
                "filenames": {"pnl": "Profit & Loss.pdf"},
            }
        }
        result = resolve_report_path(prefs, "pnl", "2026-03-15")
        assert result == tmp_path / "2026" / "03 - March" / "Profit & Loss.pdf"

    def test_strftime_in_filename(self, tmp_path):
        prefs = {
            "report_output": {
                "base_path": str(tmp_path) + "/",
                "filenames": {"pnl": "P&L %B %Y.pdf"},
            }
        }
        result = resolve_report_path(prefs, "pnl", "2026-07-31")
        assert result.name == "P&L July 2026.pdf"

    def test_full_path_example(self, tmp_path):
        prefs = {
            "report_output": {
                "base_path": str(tmp_path / "%Y - Financial Reporting/%m - %B/"),
                "filenames": {
                    "reconciliation": "{account_name} Reconciliation Report.pdf",
                    "pnl": "Profit & Loss.pdf",
                    "balance_sheet": "Balance Sheet.pdf",
                    "cash_flow": "Cash Flow Statement.pdf",
                    "expenses_by_vendor": "Expenses by Vendor Summary.pdf",
                },
            }
        }
        result = resolve_report_path(
            prefs, "reconciliation", "2026-01-31", account_name="Stripe",
        )
        expected = (
            tmp_path
            / "2026 - Financial Reporting"
            / "01 - January"
            / "Stripe Reconciliation Report.pdf"
        )
        assert result == expected


class TestResolveReportPathFormatVars:
    """Python .format() variables are expanded in filenames."""

    def test_account_name_placeholder(self, tmp_path):
        prefs = {
            "report_output": {
                "base_path": str(tmp_path) + "/",
                "filenames": {
                    "reconciliation": "{account_name} Reconciliation Report.pdf",
                },
            }
        }
        result = resolve_report_path(
            prefs, "reconciliation", "2026-01-31", account_name="Main Checking",
        )
        assert result.name == "Main Checking Reconciliation Report.pdf"

    def test_date_range_placeholders(self, tmp_path):
        prefs = {
            "report_output": {
                "base_path": str(tmp_path) + "/",
                "filenames": {
                    "pnl": "P&L {start_date} to {end_date}.pdf",
                },
            }
        }
        result = resolve_report_path(
            prefs, "pnl", "2026-01-31",
            start_date="2026-01-01", end_date="2026-01-31",
        )
        assert result.name == "P&L 2026-01-01 to 2026-01-31.pdf"

    def test_as_of_date_placeholder(self, tmp_path):
        prefs = {
            "report_output": {
                "base_path": str(tmp_path) + "/",
                "filenames": {
                    "balance_sheet": "Balance Sheet {as_of_date}.pdf",
                },
            }
        }
        result = resolve_report_path(
            prefs, "balance_sheet", "2026-06-30", as_of_date="2026-06-30",
        )
        assert result.name == "Balance Sheet 2026-06-30.pdf"


class TestResolveReportPathDirectoryCreation:
    """Directories are auto-created when they do not exist."""

    def test_creates_missing_directories(self, tmp_path):
        prefs = {
            "report_output": {
                "base_path": str(tmp_path / "a/b/c/"),
                "filenames": {"pnl": "report.pdf"},
            }
        }
        result = resolve_report_path(prefs, "pnl", "2026-01-31")
        assert result.parent.is_dir()
        assert result.parent == tmp_path / "a" / "b" / "c"

    def test_existing_directories_ok(self, tmp_path):
        target = tmp_path / "existing"
        target.mkdir()
        prefs = {
            "report_output": {
                "base_path": str(target) + "/",
                "filenames": {"pnl": "report.pdf"},
            }
        }
        result = resolve_report_path(prefs, "pnl", "2026-01-31")
        assert result == target / "report.pdf"


class TestResolveReportPathTildeExpansion:
    """Tilde in base_path is expanded to user home."""

    def test_tilde_expanded(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        prefs = {
            "report_output": {
                "base_path": "~/reports/%Y/",
                "filenames": {"pnl": "P&L.pdf"},
            }
        }
        result = resolve_report_path(prefs, "pnl", "2026-01-31")
        assert result == tmp_path / "reports" / "2026" / "P&L.pdf"


class TestResolveReportPathAllReportTypes:
    """Each report type resolves correctly with its expected variables."""

    @pytest.fixture
    def prefs(self, tmp_path):
        return {
            "report_output": {
                "base_path": str(tmp_path / "%Y/%m - %B/"),
                "filenames": {
                    "reconciliation": "{account_name} Reconciliation Report.pdf",
                    "pnl": "Profit & Loss.pdf",
                    "balance_sheet": "Balance Sheet.pdf",
                    "cash_flow": "Cash Flow Statement.pdf",
                    "expenses_by_vendor": "Expenses by Vendor Summary.pdf",
                },
            }
        }

    def test_reconciliation(self, prefs, tmp_path):
        result = resolve_report_path(
            prefs, "reconciliation", "2026-01-31", account_name="Stripe",
        )
        assert result == (
            tmp_path / "2026" / "01 - January"
            / "Stripe Reconciliation Report.pdf"
        )

    def test_pnl(self, prefs, tmp_path):
        result = resolve_report_path(
            prefs, "pnl", "2026-01-31",
            start_date="2026-01-01", end_date="2026-01-31",
        )
        assert result == tmp_path / "2026" / "01 - January" / "Profit & Loss.pdf"

    def test_balance_sheet(self, prefs, tmp_path):
        result = resolve_report_path(
            prefs, "balance_sheet", "2026-06-30", as_of_date="2026-06-30",
        )
        assert result == tmp_path / "2026" / "06 - June" / "Balance Sheet.pdf"

    def test_cash_flow(self, prefs, tmp_path):
        result = resolve_report_path(
            prefs, "cash_flow", "2026-03-31",
            start_date="2026-01-01", end_date="2026-03-31",
        )
        assert result == (
            tmp_path / "2026" / "03 - March" / "Cash Flow Statement.pdf"
        )

    def test_expenses_by_vendor(self, prefs, tmp_path):
        result = resolve_report_path(
            prefs, "expenses_by_vendor", "2026-12-31",
            start_date="2026-01-01", end_date="2026-12-31",
        )
        assert result == (
            tmp_path / "2026" / "12 - December"
            / "Expenses by Vendor Summary.pdf"
        )
