"""Tests for Gusto General Ledger importer: parser, config, account mapping, and UI."""

import os
import tempfile

import openpyxl
import pytest
from textual.widgets import DataTable, Label

from pyre.importers.journal import JournalEntry, JournalSplit, compute_journal_hash
from pyre.importers.gusto_importer import (
    detect_gusto_gl,
    load_gusto_config,
    parse_gusto_gl,
    resolve_gusto_accounts,
)
from pyre.importers.models import is_already_imported, log_import
from pyre.models import post_transaction
from pyre.ui.app import PyreApp
from pyre.ui.import_screen import JournalReviewScreen


# -- Helpers ------------------------------------------------------------------

def _write_gusto_xlsx(rows, sheet_name="Basic"):
    """Create a minimal Gusto GL XLSX with the given rows on the named sheet.

    rows: list of tuples for each row. The first 3 rows are metadata,
    row 4 is the header, row 5+ is data.
    Returns the temp file path.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    for row in rows:
        ws.append(list(row))
    f = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    f.close()
    wb.save(f.name)
    wb.close()
    return f.name


def _write_gusto_config(account_map):
    """Write a temp gusto.yaml with the given account_map dict."""
    import yaml
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8",
    )
    yaml.dump({"account_map": account_map}, f)
    f.close()
    return f.name


SAMPLE_GL_ROWS = [
    ("Acme Corp.", None, None, None),
    ("Ledger for Regular Payroll Jan 1 - Jan 15", None, None, None),
    ("Check date: 2026-01-15", None, None, None),
    ("Account Type", "Account Description", "Debit", "Credit"),
    ("RegularWages", "Regular Wages", 3000.00, None),
    ("EmployerTax", "Social Security - employer tax", 186.00, None),
    ("EmployerTax", "Medicare - employer tax", 43.50, None),
    ("DebitNetPay", "Debit net pay", None, 2500.00),
    ("DebitTax", "Debit tax", None, 529.50),
    ("BenefitLiability", "Benefit Liabilities", None, 200.00),
    (None, "Totals", 3229.50, 3229.50),
]


SAMPLE_ACCOUNT_MAP = {
    "RegularWages": "salaries",
    "EmployerTax": "payroll_taxes",
    "DebitNetPay": "checking",
    "DebitTax": "checking",
    "BenefitLiability": "payroll_liabilities",
}


# -- Detection ----------------------------------------------------------------

class TestDetectGustoGL:
    def test_detects_valid_gusto_gl(self):
        path = _write_gusto_xlsx(SAMPLE_GL_ROWS)
        try:
            assert detect_gusto_gl(path) is True
        finally:
            os.unlink(path)

    def test_rejects_xlsx_without_basic_sheet(self):
        path = _write_gusto_xlsx(SAMPLE_GL_ROWS, sheet_name="Other")
        try:
            assert detect_gusto_gl(path) is False
        finally:
            os.unlink(path)

    def test_rejects_xlsx_with_wrong_headers(self):
        rows = [
            ("Company", None, None, None),
            ("Period", None, None, None),
            ("Date: 2026-01-15", None, None, None),
            ("Name", "Amount", "Balance", "Notes"),  # wrong headers
        ]
        path = _write_gusto_xlsx(rows)
        try:
            assert detect_gusto_gl(path) is False
        finally:
            os.unlink(path)

    def test_rejects_non_xlsx_file(self):
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".xlsx", delete=False,
        )
        f.write("not an xlsx file")
        f.close()
        try:
            assert detect_gusto_gl(f.name) is False
        finally:
            os.unlink(f.name)

    def test_rejects_empty_xlsx(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Basic"
        f = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        f.close()
        wb.save(f.name)
        wb.close()
        try:
            assert detect_gusto_gl(f.name) is False
        finally:
            os.unlink(f.name)


# -- Parser -------------------------------------------------------------------

class TestParseGustoGL:
    def test_parses_single_entry(self):
        path = _write_gusto_xlsx(SAMPLE_GL_ROWS)
        try:
            entries = parse_gusto_gl(path)
            assert len(entries) == 1
        finally:
            os.unlink(path)

    def test_extracts_check_date(self):
        path = _write_gusto_xlsx(SAMPLE_GL_ROWS)
        try:
            entries = parse_gusto_gl(path)
            assert entries[0].date == "2026-01-15"
        finally:
            os.unlink(path)

    def test_extracts_period_description(self):
        path = _write_gusto_xlsx(SAMPLE_GL_ROWS)
        try:
            entries = parse_gusto_gl(path)
            assert "Regular Payroll Jan 1" in entries[0].description
        finally:
            os.unlink(path)

    def test_debits_are_positive(self):
        path = _write_gusto_xlsx(SAMPLE_GL_ROWS)
        try:
            entries = parse_gusto_gl(path)
            wages = next(
                s for s in entries[0].splits
                if s.account_name == "RegularWages"
            )
            assert wages.amount_cents == 300000
            assert wages.amount_cents > 0
        finally:
            os.unlink(path)

    def test_credits_are_negative(self):
        path = _write_gusto_xlsx(SAMPLE_GL_ROWS)
        try:
            entries = parse_gusto_gl(path)
            net_pay = next(
                s for s in entries[0].splits
                if s.account_name == "DebitNetPay"
            )
            assert net_pay.amount_cents == -250000
            assert net_pay.amount_cents < 0
        finally:
            os.unlink(path)

    def test_entry_balances_to_zero(self):
        path = _write_gusto_xlsx(SAMPLE_GL_ROWS)
        try:
            entries = parse_gusto_gl(path)
            total = sum(s.amount_cents for s in entries[0].splits)
            assert total == 0
        finally:
            os.unlink(path)

    def test_skips_totals_row(self):
        path = _write_gusto_xlsx(SAMPLE_GL_ROWS)
        try:
            entries = parse_gusto_gl(path)
            # 6 data rows, Totals row should be excluded
            assert len(entries[0].splits) == 6
        finally:
            os.unlink(path)

    def test_split_descriptions_preserved(self):
        path = _write_gusto_xlsx(SAMPLE_GL_ROWS)
        try:
            entries = parse_gusto_gl(path)
            ss_split = next(
                s for s in entries[0].splits
                if "Social Security" in s.description
            )
            assert ss_split.description == "Social Security - employer tax"
        finally:
            os.unlink(path)

    def test_account_name_is_account_type(self):
        """account_name should be the Gusto Account Type, not the description."""
        path = _write_gusto_xlsx(SAMPLE_GL_ROWS)
        try:
            entries = parse_gusto_gl(path)
            names = {s.account_name for s in entries[0].splits}
            assert "EmployerTax" in names
            assert "Social Security - employer tax" not in names
        finally:
            os.unlink(path)

    def test_handles_holiday_wages(self):
        """Account types can vary across pay periods."""
        rows = list(SAMPLE_GL_ROWS)
        # Insert HolidayWages before the Totals row
        rows.insert(-1, ("HolidayWages", "Holiday Wages", 250.00, None))
        # Fix totals (not checked by parser, but let's be consistent)
        rows[-1] = (None, "Totals", 3479.50, 3229.50)
        path = _write_gusto_xlsx(rows)
        try:
            entries = parse_gusto_gl(path)
            names = [s.account_name for s in entries[0].splits]
            assert "HolidayWages" in names
        finally:
            os.unlink(path)

    def test_returns_empty_for_missing_check_date(self):
        rows = [
            ("Company", None, None, None),
            ("Period", None, None, None),
            ("No date here", None, None, None),
            ("Account Type", "Account Description", "Debit", "Credit"),
            ("RegularWages", "Wages", 1000.00, None),
        ]
        path = _write_gusto_xlsx(rows)
        try:
            entries = parse_gusto_gl(path)
            assert entries == []
        finally:
            os.unlink(path)

    def test_returns_empty_for_too_few_rows(self):
        rows = [
            ("Company", None, None, None),
            ("Period", None, None, None),
        ]
        path = _write_gusto_xlsx(rows)
        try:
            entries = parse_gusto_gl(path)
            assert entries == []
        finally:
            os.unlink(path)

    def test_returns_empty_for_no_data_rows(self):
        rows = [
            ("Company", None, None, None),
            ("Period", None, None, None),
            ("Check date: 2026-01-15", None, None, None),
            ("Account Type", "Account Description", "Debit", "Credit"),
            (None, "Totals", 0, 0),
        ]
        path = _write_gusto_xlsx(rows)
        try:
            entries = parse_gusto_gl(path)
            assert entries == []
        finally:
            os.unlink(path)


# -- Config -------------------------------------------------------------------

class TestLoadGustoConfig:
    def test_loads_valid_config(self):
        path = _write_gusto_config(SAMPLE_ACCOUNT_MAP)
        try:
            config = load_gusto_config(config_path=path)
            assert config["account_map"]["RegularWages"] == "salaries"
        finally:
            os.unlink(path)

    def test_raises_on_missing_file(self):
        with pytest.raises(FileNotFoundError, match="Gusto config not found"):
            load_gusto_config(config_path="/tmp/nonexistent_gusto_config.yaml")


# -- Account Resolution ------------------------------------------------------

class TestResolveGustoAccounts:
    def test_resolves_all_known_types_with_string_map(self):
        path = _write_gusto_xlsx(SAMPLE_GL_ROWS)
        try:
            entries = parse_gusto_gl(path)
        finally:
            os.unlink(path)
        unmatched = resolve_gusto_accounts(entries, SAMPLE_ACCOUNT_MAP)
        assert unmatched == set()
        for sp in entries[0].splits:
            assert sp.account_id is not None

    def test_dict_mapping_routes_by_description(self):
        """Dict values map description substrings to different accounts."""
        path = _write_gusto_xlsx(SAMPLE_GL_ROWS)
        try:
            entries = parse_gusto_gl(path)
        finally:
            os.unlink(path)
        account_map = {
            "RegularWages": "salaries",
            "EmployerTax": {
                "Social Security": "fica",
                "Medicare": "fica",
            },
            "DebitNetPay": "checking",
            "DebitTax": "checking",
            "BenefitLiability": "liabilities",
        }
        unmatched = resolve_gusto_accounts(entries, account_map)
        assert unmatched == set()

        ss_split = next(
            s for s in entries[0].splits
            if "Social Security" in s.description
        )
        assert ss_split.account_id == "fica"

        med_split = next(
            s for s in entries[0].splits
            if "Medicare" in s.description
        )
        assert med_split.account_id == "fica"

    def test_dict_mapping_reports_unmatched_description(self):
        """Dict map with missing description substring reports the split."""
        path = _write_gusto_xlsx(SAMPLE_GL_ROWS)
        try:
            entries = parse_gusto_gl(path)
        finally:
            os.unlink(path)
        account_map = {
            "RegularWages": "salaries",
            "EmployerTax": {
                "Social Security": "fica",
                # Medicare intentionally missing
            },
            "DebitNetPay": "checking",
            "DebitTax": "checking",
            "BenefitLiability": "liabilities",
        }
        unmatched = resolve_gusto_accounts(entries, account_map)
        assert any("Medicare" in u for u in unmatched)

    def test_reports_unmapped_types(self):
        path = _write_gusto_xlsx(SAMPLE_GL_ROWS)
        try:
            entries = parse_gusto_gl(path)
        finally:
            os.unlink(path)
        partial_map = {"RegularWages": "salaries"}  # missing others
        unmatched = resolve_gusto_accounts(entries, partial_map)
        assert any("EmployerTax" in u for u in unmatched)
        assert any("DebitNetPay" in u for u in unmatched)

    def test_unmatched_splits_have_no_account_id(self):
        path = _write_gusto_xlsx(SAMPLE_GL_ROWS)
        try:
            entries = parse_gusto_gl(path)
        finally:
            os.unlink(path)
        unmatched = resolve_gusto_accounts(entries, {})
        for sp in entries[0].splits:
            assert sp.account_id is None

    def test_description_matching_is_case_insensitive(self):
        path = _write_gusto_xlsx(SAMPLE_GL_ROWS)
        try:
            entries = parse_gusto_gl(path)
        finally:
            os.unlink(path)
        account_map = {
            "RegularWages": "salaries",
            "EmployerTax": {
                "social security": "fica",  # lowercase
                "medicare": "fica",
            },
            "DebitNetPay": "checking",
            "DebitTax": "checking",
            "BenefitLiability": "liabilities",
        }
        unmatched = resolve_gusto_accounts(entries, account_map)
        assert unmatched == set()


# -- Hash / Dedup -------------------------------------------------------------

class TestGustoHash:
    def test_hash_determinism(self):
        path = _write_gusto_xlsx(SAMPLE_GL_ROWS)
        try:
            e1 = parse_gusto_gl(path)
            e2 = parse_gusto_gl(path)
            assert e1[0].hash == e2[0].hash
        finally:
            os.unlink(path)

    def test_hash_is_sha256(self):
        path = _write_gusto_xlsx(SAMPLE_GL_ROWS)
        try:
            entries = parse_gusto_gl(path)
            assert len(entries[0].hash) == 64
        finally:
            os.unlink(path)

    def test_different_periods_produce_different_hashes(self):
        rows_jan = list(SAMPLE_GL_ROWS)
        rows_feb = list(SAMPLE_GL_ROWS)
        rows_feb[2] = ("Check date: 2026-02-13", None, None, None)

        path1 = _write_gusto_xlsx(rows_jan)
        path2 = _write_gusto_xlsx(rows_feb)
        try:
            e1 = parse_gusto_gl(path1)
            e2 = parse_gusto_gl(path2)
            assert e1[0].hash != e2[0].hash
        finally:
            os.unlink(path1)
            os.unlink(path2)

    def test_different_amounts_produce_different_hashes(self):
        rows_a = list(SAMPLE_GL_ROWS)
        rows_b = list(SAMPLE_GL_ROWS)
        # Change the wages amount
        rows_b[4] = ("RegularWages", "Regular Wages", 4000.00, None)

        path1 = _write_gusto_xlsx(rows_a)
        path2 = _write_gusto_xlsx(rows_b)
        try:
            e1 = parse_gusto_gl(path1)
            e2 = parse_gusto_gl(path2)
            assert e1[0].hash != e2[0].hash
        finally:
            os.unlink(path1)
            os.unlink(path2)


# -- Integration: Parse + Resolve --------------------------------------------

class TestParseAndResolve:
    def test_full_pipeline(self):
        path = _write_gusto_xlsx(SAMPLE_GL_ROWS)
        try:
            entries = parse_gusto_gl(path)
            unmatched = resolve_gusto_accounts(entries, SAMPLE_ACCOUNT_MAP)

            assert len(entries) == 1
            assert unmatched == set()
            assert all(s.account_id is not None for s in entries[0].splits)
            assert sum(s.amount_cents for s in entries[0].splits) == 0
        finally:
            os.unlink(path)


# -- UI: JournalReviewScreen with Gusto entries -------------------------------

@pytest.fixture
def gusto_db(db):
    """DB with accounts matching the sample Gusto account map."""
    accts = [
        ("checking",           None, "Payroll Checking", "asset",                  None),
        ("salaries",           None, "Salaries",         "expense",                None),
        ("payroll_taxes",      None, "Payroll Taxes",    "expense",                None),
        ("payroll_liabilities", None, "Payroll Liabilities", "other_current_liability", None),
    ]
    db.executemany(
        "INSERT INTO accounts (id, account_number, name, type, parent_id) "
        "VALUES (?,?,?,?,?)",
        accts,
    )
    db.commit()
    return db


@pytest.fixture
def gusto_app(gusto_db):
    return PyreApp(con=gusto_db)


def _make_resolved_gusto_entries():
    """Create parsed and resolved Gusto entries for UI testing."""
    path = _write_gusto_xlsx(SAMPLE_GL_ROWS)
    try:
        entries = parse_gusto_gl(path)
        unmatched = resolve_gusto_accounts(entries, SAMPLE_ACCOUNT_MAP)
        return entries, unmatched
    finally:
        os.unlink(path)


class TestGustoJournalReviewScreen:
    async def test_screen_displays_entries(self, gusto_app):
        entries, unmatched = _make_resolved_gusto_entries()
        async with gusto_app.run_test() as pilot:
            gusto_app.push_screen(
                JournalReviewScreen(
                    gusto_app.con, "test.xlsx", entries, unmatched,
                    title="Import Gusto Payroll: test.xlsx",
                ),
            )
            await pilot.pause()

            assert isinstance(gusto_app.screen, JournalReviewScreen)
            table = gusto_app.screen.query_one("#jr-table", DataTable)
            assert table.row_count == 1

    async def test_title_shown(self, gusto_app):
        entries, unmatched = _make_resolved_gusto_entries()
        async with gusto_app.run_test() as pilot:
            gusto_app.push_screen(
                JournalReviewScreen(
                    gusto_app.con, "test.xlsx", entries, unmatched,
                    title="Import Gusto Payroll: test.xlsx",
                ),
            )
            await pilot.pause()

            title = gusto_app.screen.query_one("#jr-title", Label)
            assert "Gusto" in str(title.content)

    async def test_accept_and_finish(self, gusto_app):
        entries, unmatched = _make_resolved_gusto_entries()
        results = []

        async with gusto_app.run_test() as pilot:
            gusto_app.push_screen(
                JournalReviewScreen(
                    gusto_app.con, "test.xlsx", entries, unmatched,
                    title="Import Gusto Payroll: test.xlsx",
                ),
                callback=lambda r: results.append(r),
            )
            await pilot.pause()

            await pilot.press("a")
            await pilot.pause()
            await pilot.press("q")
            await pilot.pause()

        assert len(results) == 1
        assert results[0]["committed"] == 1

        # Verify the transaction was created
        txns = gusto_app.con.execute(
            "SELECT id, date, description FROM transactions"
        ).fetchall()
        assert len(txns) == 1
        assert txns[0][1] == "2026-01-15"

        # Verify splits balance
        splits = gusto_app.con.execute(
            "SELECT account_id, amount, description FROM splits WHERE tx_id = ?",
            (txns[0][0],),
        ).fetchall()
        assert sum(s[1] for s in splits) == 0
        assert len(splits) == 6

    async def test_split_descriptions_saved(self, gusto_app):
        """Per-split descriptions from Gusto should be stored in the splits table."""
        entries, unmatched = _make_resolved_gusto_entries()
        results = []

        async with gusto_app.run_test() as pilot:
            gusto_app.push_screen(
                JournalReviewScreen(
                    gusto_app.con, "test.xlsx", entries, unmatched,
                    title="Import Gusto Payroll: test.xlsx",
                ),
                callback=lambda r: results.append(r),
            )
            await pilot.pause()

            await pilot.press("a")
            await pilot.pause()
            await pilot.press("q")
            await pilot.pause()

        txns = gusto_app.con.execute("SELECT id FROM transactions").fetchall()
        splits = gusto_app.con.execute(
            "SELECT description FROM splits WHERE tx_id = ? AND description != ''",
            (txns[0][0],),
        ).fetchall()
        descriptions = [s[0] for s in splits]
        assert "Regular Wages" in descriptions
        assert "Social Security - employer tax" in descriptions

    async def test_dedup_skips_already_imported(self, gusto_app):
        entries, unmatched = _make_resolved_gusto_entries()
        # Simulate previous import
        log_import(
            gusto_app.con, "old.xlsx",
            fitid=None, hash_val=entries[0].hash,
            tx_id=None, status="imported", account_id=None,
        )

        async with gusto_app.run_test() as pilot:
            gusto_app.push_screen(
                JournalReviewScreen(
                    gusto_app.con, "test.xlsx", entries, unmatched,
                    title="Import Gusto Payroll: test.xlsx",
                ),
            )
            await pilot.pause()

            screen = gusto_app.screen
            assert screen._get_state(0) == "SKP"

    async def test_cancel_commits_nothing(self, gusto_app):
        entries, unmatched = _make_resolved_gusto_entries()
        results = []

        async with gusto_app.run_test() as pilot:
            gusto_app.push_screen(
                JournalReviewScreen(
                    gusto_app.con, "test.xlsx", entries, unmatched,
                    title="Import Gusto Payroll: test.xlsx",
                ),
                callback=lambda r: results.append(r),
            )
            await pilot.pause()

            await pilot.press("a")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

        assert results[0] is None

        txns = gusto_app.con.execute(
            "SELECT count(*) FROM transactions"
        ).fetchone()
        assert txns[0] == 0

    async def test_unmatched_accounts_show_error(self, gusto_app):
        entries, _ = _make_resolved_gusto_entries()
        # Deliberately break one split
        entries[0].splits[0].account_id = None

        async with gusto_app.run_test() as pilot:
            gusto_app.push_screen(
                JournalReviewScreen(
                    gusto_app.con, "test.xlsx", entries,
                    {"RegularWages"},
                    title="Import Gusto Payroll: test.xlsx",
                ),
            )
            await pilot.pause()

            screen = gusto_app.screen
            assert screen._get_state(0) == "ERR"
