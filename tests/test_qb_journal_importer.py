"""Tests for QuickBooks journal entry importer: parser, account mapping, and UI."""

import os
import tempfile

import pytest
from textual.widgets import DataTable, Label

from pyre.importers.models import is_already_imported, log_import
from pyre.importers.journal import (
    JournalEntry,
    JournalSplit,
    compute_journal_hash,
)
from pyre.importers.journal import build_account_path_map
from pyre.importers.qb_journal_importer import (
    detect_qb_journal,
    parse_qb_journals,
    resolve_accounts,
)
from pyre.models import post_transaction
from pyre.ui.app import PyreApp
from pyre.ui.import_screen import JournalReviewScreen


# -- Helpers ------------------------------------------------------------------

def _write_csv(content):
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8",
    )
    f.write(content)
    f.close()
    return f.name


SAMPLE_QB_JOURNAL = (
    "JournalNo,JournalDate,AccountName,Debits,Credits,Description,Name,Currency,Location,Class\n"
    "20260131-1594-PayPal,,Sales:Hosting:VPS,,135.00,,,,,\n"
    "20260131-1594-PayPal,,Sales:Hosting:Backup,,14.00,,,,,\n"
    "20260131-1594-PayPal,,Sales:Hosting:IP Numbers,,10.00,,,,,\n"
    "20260131-1594-PayPal,,Sales:Hosting:Consulting,,90.00,,,,,\n"
    "20260131-1594-PayPal,01/31/2026,PayPal,249.00,,,,,,\n"
)

MULTI_ENTRY_CSV = (
    "JournalNo,JournalDate,AccountName,Debits,Credits,Description,Name,Currency,Location,Class\n"
    "J001,,Income:Consulting,,500.00,,,,,\n"
    "J001,02/15/2026,Checking,500.00,,,,,,\n"
    "J002,,Income:Consulting,,1000.00,,,,,\n"
    "J002,02/16/2026,Checking,1000.00,,,,,,\n"
)


# -- Detection ----------------------------------------------------------------

class TestDetectQBJournal:
    def test_detects_qb_journal_csv(self):
        path = _write_csv(SAMPLE_QB_JOURNAL)
        try:
            assert detect_qb_journal(path) is True
        finally:
            os.unlink(path)

    def test_rejects_bank_csv(self):
        path = _write_csv("Date,Description,Debit,Credit\n01/15/2026,TEST,,100.00\n")
        try:
            assert detect_qb_journal(path) is False
        finally:
            os.unlink(path)

    def test_rejects_empty_csv(self):
        path = _write_csv("")
        try:
            assert detect_qb_journal(path) is False
        finally:
            os.unlink(path)

    def test_handles_utf8_bom(self):
        """QB exports often include a UTF-8 BOM."""
        content = "\ufeff" + SAMPLE_QB_JOURNAL
        path = _write_csv(content)
        try:
            assert detect_qb_journal(path) is True
        finally:
            os.unlink(path)


# -- Parser -------------------------------------------------------------------

class TestParseQBJournals:
    def test_groups_rows_by_journal_no(self):
        path = _write_csv(SAMPLE_QB_JOURNAL)
        try:
            entries = parse_qb_journals(path)
            assert len(entries) == 1
            assert len(entries[0].splits) == 5
        finally:
            os.unlink(path)

    def test_parses_date_correctly(self):
        path = _write_csv(SAMPLE_QB_JOURNAL)
        try:
            entries = parse_qb_journals(path)
            assert entries[0].date == "2026-01-31"
        finally:
            os.unlink(path)

    def test_debits_are_positive(self):
        path = _write_csv(SAMPLE_QB_JOURNAL)
        try:
            entries = parse_qb_journals(path)
            debit_split = next(
                s for s in entries[0].splits if s.account_name == "PayPal"
            )
            assert debit_split.amount_cents == 24900
            assert debit_split.amount_cents > 0
        finally:
            os.unlink(path)

    def test_credits_are_negative(self):
        path = _write_csv(SAMPLE_QB_JOURNAL)
        try:
            entries = parse_qb_journals(path)
            credit_split = next(
                s for s in entries[0].splits
                if s.account_name == "Sales:Hosting:VPS"
            )
            assert credit_split.amount_cents == -13500
            assert credit_split.amount_cents < 0
        finally:
            os.unlink(path)

    def test_entry_balances_to_zero(self):
        path = _write_csv(SAMPLE_QB_JOURNAL)
        try:
            entries = parse_qb_journals(path)
            total = sum(s.amount_cents for s in entries[0].splits)
            assert total == 0
        finally:
            os.unlink(path)

    def test_description_derived_from_debit_accounts(self):
        path = _write_csv(SAMPLE_QB_JOURNAL)
        try:
            entries = parse_qb_journals(path)
            assert entries[0].description == "PayPal"
        finally:
            os.unlink(path)

    def test_multiple_entries_parsed_in_order(self):
        path = _write_csv(MULTI_ENTRY_CSV)
        try:
            entries = parse_qb_journals(path)
            assert len(entries) == 2
            assert entries[0].date == "2026-02-15"
            assert entries[1].date == "2026-02-16"
        finally:
            os.unlink(path)

    def test_empty_csv_returns_empty_list(self):
        path = _write_csv(
            "JournalNo,JournalDate,AccountName,Debits,Credits,"
            "Description,Name,Currency,Location,Class\n"
        )
        try:
            entries = parse_qb_journals(path)
            assert entries == []
        finally:
            os.unlink(path)

    def test_skips_rows_without_journal_no(self):
        content = (
            "JournalNo,JournalDate,AccountName,Debits,Credits,"
            "Description,Name,Currency,Location,Class\n"
            ",,Orphan Account,100.00,,,,,,\n"
            "J001,02/15/2026,Checking,500.00,,,,,,\n"
            "J001,,Income,,500.00,,,,,\n"
        )
        path = _write_csv(content)
        try:
            entries = parse_qb_journals(path)
            assert len(entries) == 1
            assert len(entries[0].splits) == 2
        finally:
            os.unlink(path)

    def test_skips_rows_without_amount(self):
        content = (
            "JournalNo,JournalDate,AccountName,Debits,Credits,"
            "Description,Name,Currency,Location,Class\n"
            "J001,,NoAmount,,,,,,,\n"
            "J001,02/15/2026,Checking,500.00,,,,,,\n"
            "J001,,Income,,500.00,,,,,\n"
        )
        path = _write_csv(content)
        try:
            entries = parse_qb_journals(path)
            assert len(entries[0].splits) == 2
        finally:
            os.unlink(path)

    def test_handles_comma_formatted_amounts(self):
        content = (
            "JournalNo,JournalDate,AccountName,Debits,Credits,"
            "Description,Name,Currency,Location,Class\n"
            'J001,,"Income",,"1,234.56",,,,,\n'
            'J001,01/15/2026,"Checking","1,234.56",,,,,,\n'
        )
        path = _write_csv(content)
        try:
            entries = parse_qb_journals(path)
            debit = next(
                s for s in entries[0].splits if s.amount_cents > 0
            )
            assert debit.amount_cents == 123456
        finally:
            os.unlink(path)

    def test_entry_without_date_is_skipped(self):
        """An entry group where no row has a JournalDate is dropped."""
        content = (
            "JournalNo,JournalDate,AccountName,Debits,Credits,"
            "Description,Name,Currency,Location,Class\n"
            "J001,,Income,,500.00,,,,,\n"
            "J001,,Checking,500.00,,,,,,\n"
        )
        path = _write_csv(content)
        try:
            entries = parse_qb_journals(path)
            assert entries == []
        finally:
            os.unlink(path)

    def test_multiple_debit_accounts_in_description(self):
        content = (
            "JournalNo,JournalDate,AccountName,Debits,Credits,"
            "Description,Name,Currency,Location,Class\n"
            "J001,,Income,,500.00,,,,,\n"
            "J001,02/15/2026,Checking,300.00,,,,,,\n"
            "J001,,Savings,200.00,,,,,,\n"
        )
        path = _write_csv(content)
        try:
            entries = parse_qb_journals(path)
            assert entries[0].description == "Checking, Savings"
        finally:
            os.unlink(path)


# -- Account Mapping ----------------------------------------------------------

@pytest.fixture
def journal_db(db):
    """DB with accounts that have a parent hierarchy matching QB paths."""
    accts = [
        ("checking",     None, "Checking",     "asset",       None),
        ("paypal",       None, "PayPal",       "asset",       None),
        ("stripe",       None, "Stripe",       "asset",       None),
        ("sales",        None, "Sales",        "income",      None),
        ("hosting",      None, "Hosting",      "income",      "sales"),
        ("vps",          None, "VPS",          "income",      "hosting"),
        ("backup",       None, "Backup",       "income",      "hosting"),
        ("ip_numbers",   None, "IP Numbers",   "income",      "hosting"),
        ("consulting",   None, "Consulting",   "income",      "hosting"),
    ]
    db.executemany(
        "INSERT INTO accounts (id, account_number, name, type, parent_id) "
        "VALUES (?,?,?,?,?)",
        accts,
    )
    db.commit()
    return db


class TestBuildQBAccountMap:
    def test_maps_top_level_accounts(self, journal_db):
        mapping = build_account_path_map(journal_db)
        assert mapping["PayPal"] == "paypal"
        assert mapping["Checking"] == "checking"

    def test_maps_nested_accounts(self, journal_db):
        mapping = build_account_path_map(journal_db)
        assert mapping["Sales:Hosting:VPS"] == "vps"
        assert mapping["Sales:Hosting:Backup"] == "backup"

    def test_maps_intermediate_accounts(self, journal_db):
        mapping = build_account_path_map(journal_db)
        assert mapping["Sales"] == "sales"
        assert mapping["Sales:Hosting"] == "hosting"

    def test_includes_all_accounts(self, journal_db):
        mapping = build_account_path_map(journal_db)
        assert len(mapping) == 9


class TestResolveAccounts:
    def test_resolves_all_accounts(self, journal_db):
        entries = [
            JournalEntry(date="2026-01-31", description="PayPal", splits=[
                JournalSplit("Sales:Hosting:VPS", -13500),
                JournalSplit("PayPal", 13500),
            ]),
        ]
        mapping = build_account_path_map(journal_db)
        unmatched = resolve_accounts(entries, mapping)

        assert unmatched == set()
        assert entries[0].splits[0].account_id == "vps"
        assert entries[0].splits[1].account_id == "paypal"

    def test_reports_unmatched_accounts(self, journal_db):
        entries = [
            JournalEntry(date="2026-01-31", description="Test", splits=[
                JournalSplit("Sales:Hosting:VPS", -5000),
                JournalSplit("NonExistent:Account", 5000),
            ]),
        ]
        mapping = build_account_path_map(journal_db)
        unmatched = resolve_accounts(entries, mapping)

        assert "NonExistent:Account" in unmatched
        assert entries[0].splits[0].account_id == "vps"
        assert entries[0].splits[1].account_id is None

    def test_cleans_star_star_names(self, db):
        """QB names like 'First National **1234' should match Pyre's 'First National - 1234'."""
        db.execute(
            "INSERT INTO accounts (id, name, type) VALUES (?, ?, ?)",
            ("fnb", "First National - 1234", "asset"),
        )
        db.commit()

        entries = [
            JournalEntry(date="2026-01-31", description="Test", splits=[
                JournalSplit("First National **1234", 5000),
            ]),
        ]
        mapping = build_account_path_map(db)
        unmatched = resolve_accounts(entries, mapping)

        assert unmatched == set()
        assert entries[0].splits[0].account_id == "fnb"


# -- Integration: Parse + Resolve --------------------------------------------

class TestParseAndResolve:
    def test_full_pipeline(self, journal_db):
        """Parse a CSV and resolve all accounts end-to-end."""
        path = _write_csv(SAMPLE_QB_JOURNAL)
        try:
            entries = parse_qb_journals(path)
            mapping = build_account_path_map(journal_db)
            unmatched = resolve_accounts(entries, mapping)

            assert len(entries) == 1
            assert unmatched == set()
            assert all(s.account_id is not None for s in entries[0].splits)
            # Verify balance
            assert sum(s.amount_cents for s in entries[0].splits) == 0
        finally:
            os.unlink(path)


# -- UI: JournalReviewScreen --------------------------------------------------

@pytest.fixture
def journal_app(journal_db):
    return PyreApp(con=journal_db)


def _make_resolved_entries(journal_db):
    """Create parsed and resolved journal entries for UI testing."""
    path = _write_csv(SAMPLE_QB_JOURNAL)
    try:
        entries = parse_qb_journals(path)
        mapping = build_account_path_map(journal_db)
        unmatched = resolve_accounts(entries, mapping)
        return entries, unmatched
    finally:
        os.unlink(path)


class TestJournalReviewScreen:
    async def test_screen_displays_entries(self, journal_app):
        entries, unmatched = _make_resolved_entries(journal_app.con)
        async with journal_app.run_test() as pilot:
            journal_app.push_screen(
                JournalReviewScreen(journal_app.con, "test.csv", entries, unmatched),
            )
            await pilot.pause()

            assert isinstance(journal_app.screen, JournalReviewScreen)
            table = journal_app.screen.query_one("#jr-table", DataTable)
            assert table.row_count == 1

    async def test_status_shows_entry_count(self, journal_app):
        entries, unmatched = _make_resolved_entries(journal_app.con)
        async with journal_app.run_test() as pilot:
            journal_app.push_screen(
                JournalReviewScreen(journal_app.con, "test.csv", entries, unmatched),
            )
            await pilot.pause()

            status = journal_app.screen.query_one("#jr-status", Label)
            assert "1 entries" in str(status.content)

    async def test_accept_entry(self, journal_app):
        entries, unmatched = _make_resolved_entries(journal_app.con)
        async with journal_app.run_test() as pilot:
            journal_app.push_screen(
                JournalReviewScreen(journal_app.con, "test.csv", entries, unmatched),
            )
            await pilot.pause()

            screen = journal_app.screen
            # Accept the entry
            await pilot.press("enter")
            await pilot.pause()

            assert screen._get_state(0) == "OK"

    async def test_skip_and_unskip_entry(self, journal_app):
        entries, unmatched = _make_resolved_entries(journal_app.con)
        async with journal_app.run_test() as pilot:
            journal_app.push_screen(
                JournalReviewScreen(journal_app.con, "test.csv", entries, unmatched),
            )
            await pilot.pause()

            screen = journal_app.screen
            # Skip
            await pilot.press("s")
            await pilot.pause()
            assert screen._get_state(0) == "SKP"

            # Move cursor back to row 0 (skip moved it down)
            await pilot.press("k")
            await pilot.pause()

            # Unskip
            await pilot.press("s")
            await pilot.pause()
            assert screen._get_state(0) == "NEW"

    async def test_accept_all(self, journal_app):
        csv_content = (
            "JournalNo,JournalDate,AccountName,Debits,Credits,"
            "Description,Name,Currency,Location,Class\n"
            "J001,,Sales:Hosting:VPS,,500.00,,,,,\n"
            "J001,02/15/2026,Checking,500.00,,,,,,\n"
            "J002,,Sales:Hosting:Backup,,200.00,,,,,\n"
            "J002,02/16/2026,PayPal,200.00,,,,,,\n"
        )
        path = _write_csv(csv_content)
        try:
            entries = parse_qb_journals(path)
            mapping = build_account_path_map(journal_app.con)
            unmatched = resolve_accounts(entries, mapping)
        finally:
            os.unlink(path)

        async with journal_app.run_test() as pilot:
            journal_app.push_screen(
                JournalReviewScreen(
                    journal_app.con, "test.csv", entries, unmatched,
                ),
            )
            await pilot.pause()

            screen = journal_app.screen
            assert screen._get_state(0) == "NEW"
            assert screen._get_state(1) == "NEW"

            await pilot.press("a")
            await pilot.pause()

            assert screen._get_state(0) == "OK"
            assert screen._get_state(1) == "OK"

    async def test_finish_commits_transactions(self, journal_app):
        entries, unmatched = _make_resolved_entries(journal_app.con)
        results = []

        async with journal_app.run_test() as pilot:
            journal_app.push_screen(
                JournalReviewScreen(
                    journal_app.con, "test.csv", entries, unmatched,
                ),
                callback=lambda r: results.append(r),
            )
            await pilot.pause()

            # Accept all and finish
            await pilot.press("a")
            await pilot.pause()
            await pilot.press("q")
            await pilot.pause()

        assert len(results) == 1
        assert results[0]["committed"] == 1

        # Verify the transaction was created in the database
        txns = journal_app.con.execute(
            "SELECT id, date, description FROM transactions"
        ).fetchall()
        assert len(txns) == 1
        assert txns[0][1] == "2026-01-31"
        assert txns[0][2] == "PayPal"

        # Verify splits
        splits = journal_app.con.execute(
            "SELECT account_id, amount FROM splits WHERE tx_id = ? ORDER BY amount DESC",
            (txns[0][0],),
        ).fetchall()
        assert len(splits) == 5
        # Debit to PayPal
        assert splits[0] == ("paypal", 24900)
        # Credits sum to -24900
        credit_total = sum(s[1] for s in splits if s[1] < 0)
        assert credit_total == -24900
        # Total should balance
        assert sum(s[1] for s in splits) == 0

    async def test_finish_skipped_entries_not_committed(self, journal_app):
        entries, unmatched = _make_resolved_entries(journal_app.con)
        results = []

        async with journal_app.run_test() as pilot:
            journal_app.push_screen(
                JournalReviewScreen(
                    journal_app.con, "test.csv", entries, unmatched,
                ),
                callback=lambda r: results.append(r),
            )
            await pilot.pause()

            # Skip all entries and finish
            await pilot.press("s")
            await pilot.pause()
            await pilot.press("q")
            await pilot.pause()

        assert results[0]["committed"] == 0

        txns = journal_app.con.execute(
            "SELECT count(*) FROM transactions"
        ).fetchone()
        assert txns[0] == 0

    async def test_cancel_commits_nothing(self, journal_app):
        entries, unmatched = _make_resolved_entries(journal_app.con)
        results = []

        async with journal_app.run_test() as pilot:
            journal_app.push_screen(
                JournalReviewScreen(
                    journal_app.con, "test.csv", entries, unmatched,
                ),
                callback=lambda r: results.append(r),
            )
            await pilot.pause()

            # Accept then cancel
            await pilot.press("a")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

        assert results[0] is None

        txns = journal_app.con.execute(
            "SELECT count(*) FROM transactions"
        ).fetchone()
        assert txns[0] == 0

    async def test_peek_shows_splits(self, journal_app):
        """Pressing M on an entry should call notify (no crash)."""
        entries, unmatched = _make_resolved_entries(journal_app.con)
        async with journal_app.run_test(notifications=True) as pilot:
            journal_app.push_screen(
                JournalReviewScreen(
                    journal_app.con, "test.csv", entries, unmatched,
                ),
            )
            await pilot.pause()

            await pilot.press("m")
            await pilot.pause()

            # Verify peek did not crash and we are still on the review screen
            assert isinstance(journal_app.screen, JournalReviewScreen)

    async def test_error_state_for_unmatched_accounts(self, journal_app):
        """Entries with unmatched accounts should show ERR state."""
        entries = [
            JournalEntry(date="2026-01-31", description="Bad Entry", splits=[
                JournalSplit("Sales:Hosting:VPS", -5000, account_id="vps"),
                JournalSplit("NonExistent:Account", 5000, account_id=None),
            ]),
        ]

        async with journal_app.run_test() as pilot:
            journal_app.push_screen(
                JournalReviewScreen(
                    journal_app.con, "test.csv", entries, {"NonExistent:Account"},
                ),
            )
            await pilot.pause()

            screen = journal_app.screen
            assert screen._get_state(0) == "ERR"

    async def test_cannot_accept_error_entry(self, journal_app):
        """Pressing enter on an ERR entry should not accept it."""
        entries = [
            JournalEntry(date="2026-01-31", description="Bad", splits=[
                JournalSplit("X", -5000, account_id="vps"),
                JournalSplit("Y", 5000, account_id=None),
            ]),
        ]

        async with journal_app.run_test() as pilot:
            journal_app.push_screen(
                JournalReviewScreen(
                    journal_app.con, "test.csv", entries, {"Y"},
                ),
            )
            await pilot.pause()

            await pilot.press("enter")
            await pilot.pause()

            assert journal_app.screen._get_state(0) == "ERR"

    async def test_accept_all_skips_error_entries(self, journal_app):
        """Accept All should skip entries with unmatched accounts."""
        entries = [
            JournalEntry(date="2026-01-31", description="Good", splits=[
                JournalSplit("Sales:Hosting:VPS", -5000, account_id="vps"),
                JournalSplit("Checking", 5000, account_id="checking"),
            ]),
            JournalEntry(date="2026-01-31", description="Bad", splits=[
                JournalSplit("X", -5000, account_id="vps"),
                JournalSplit("Y", 5000, account_id=None),
            ]),
        ]

        async with journal_app.run_test() as pilot:
            journal_app.push_screen(
                JournalReviewScreen(
                    journal_app.con, "test.csv", entries, {"Y"},
                ),
            )
            await pilot.pause()

            await pilot.press("a")
            await pilot.pause()

            screen = journal_app.screen
            assert screen._get_state(0) == "OK"
            assert screen._get_state(1) == "ERR"

    async def test_multi_entry_commit(self, journal_app):
        """Multiple accepted entries each become separate transactions."""
        csv_content = (
            "JournalNo,JournalDate,AccountName,Debits,Credits,"
            "Description,Name,Currency,Location,Class\n"
            "J001,,Sales:Hosting:VPS,,500.00,,,,,\n"
            "J001,02/15/2026,Checking,500.00,,,,,,\n"
            "J002,,Sales:Hosting:Backup,,200.00,,,,,\n"
            "J002,02/16/2026,PayPal,200.00,,,,,,\n"
        )
        path = _write_csv(csv_content)
        try:
            entries = parse_qb_journals(path)
            mapping = build_account_path_map(journal_app.con)
            unmatched = resolve_accounts(entries, mapping)
        finally:
            os.unlink(path)

        results = []
        async with journal_app.run_test() as pilot:
            journal_app.push_screen(
                JournalReviewScreen(
                    journal_app.con, "test.csv", entries, unmatched,
                ),
                callback=lambda r: results.append(r),
            )
            await pilot.pause()

            await pilot.press("a")
            await pilot.pause()
            await pilot.press("q")
            await pilot.pause()

        assert results[0]["committed"] == 2

        txns = journal_app.con.execute(
            "SELECT date, description FROM transactions ORDER BY date"
        ).fetchall()
        assert len(txns) == 2
        assert txns[0] == ("2026-02-15", "Checking")
        assert txns[1] == ("2026-02-16", "PayPal")


# -- Dedup: Hash Computation --------------------------------------------------

class TestJournalHash:
    def test_hash_determinism(self):
        """Same content produces the same hash."""
        entry = JournalEntry(date="2026-01-31", description="PayPal", splits=[
            JournalSplit("Sales:Hosting:VPS", -13500),
            JournalSplit("PayPal", 13500),
        ])
        h1 = compute_journal_hash(entry)
        h2 = compute_journal_hash(entry)
        assert h1 == h2

    def test_hash_order_independence(self):
        """Splits in different order produce the same hash."""
        e1 = JournalEntry(date="2026-01-31", description="X", splits=[
            JournalSplit("A", 100),
            JournalSplit("B", -100),
        ])
        e2 = JournalEntry(date="2026-01-31", description="X", splits=[
            JournalSplit("B", -100),
            JournalSplit("A", 100),
        ])
        assert compute_journal_hash(e1) == compute_journal_hash(e2)

    def test_hash_uniqueness(self):
        """Different entries produce different hashes."""
        e1 = JournalEntry(date="2026-01-31", description="X", splits=[
            JournalSplit("A", 100),
            JournalSplit("B", -100),
        ])
        e2 = JournalEntry(date="2026-02-01", description="X", splits=[
            JournalSplit("A", 100),
            JournalSplit("B", -100),
        ])
        assert compute_journal_hash(e1) != compute_journal_hash(e2)

    def test_hash_differs_by_amount(self):
        """Different amounts produce different hashes."""
        e1 = JournalEntry(date="2026-01-31", description="X", splits=[
            JournalSplit("A", 100),
            JournalSplit("B", -100),
        ])
        e2 = JournalEntry(date="2026-01-31", description="X", splits=[
            JournalSplit("A", 200),
            JournalSplit("B", -200),
        ])
        assert compute_journal_hash(e1) != compute_journal_hash(e2)

    def test_parse_populates_hash(self):
        """parse_qb_journals should set hash on each entry."""
        path = _write_csv(SAMPLE_QB_JOURNAL)
        try:
            entries = parse_qb_journals(path)
            assert len(entries) == 1
            assert entries[0].hash is not None
            assert len(entries[0].hash) == 64  # SHA-256 hex
        finally:
            os.unlink(path)

    def test_parse_hash_is_deterministic(self):
        """Parsing the same file twice produces identical hashes."""
        path = _write_csv(SAMPLE_QB_JOURNAL)
        try:
            e1 = parse_qb_journals(path)
            e2 = parse_qb_journals(path)
            assert e1[0].hash == e2[0].hash
        finally:
            os.unlink(path)


# -- Dedup: Import Log Integration -------------------------------------------

class TestJournalDedup:
    async def test_already_imported_entries_show_skip(self, journal_app):
        """Entries whose hash is already in import_log should be pre-skipped."""
        entries, unmatched = _make_resolved_entries(journal_app.con)
        # Simulate a previous import by logging the hash (tx_id=None is valid)
        log_import(
            journal_app.con, "old.csv",
            fitid=None, hash_val=entries[0].hash,
            tx_id=None, status="imported", account_id=None,
        )

        async with journal_app.run_test() as pilot:
            journal_app.push_screen(
                JournalReviewScreen(
                    journal_app.con, "test.csv", entries, unmatched,
                ),
            )
            await pilot.pause()

            screen = journal_app.screen
            assert screen._get_state(0) == "SKP"

    async def test_committed_entries_are_logged(self, journal_app):
        """After finishing, committed entries should be in import_log."""
        entries, unmatched = _make_resolved_entries(journal_app.con)
        results = []

        async with journal_app.run_test() as pilot:
            journal_app.push_screen(
                JournalReviewScreen(
                    journal_app.con, "test.csv", entries, unmatched,
                ),
                callback=lambda r: results.append(r),
            )
            await pilot.pause()

            await pilot.press("a")
            await pilot.pause()
            await pilot.press("q")
            await pilot.pause()

        assert results[0]["committed"] == 1
        assert is_already_imported(
            journal_app.con, fitid=None, hash_val=entries[0].hash,
        )

    async def test_reimport_shows_skip_after_commit(self, journal_app):
        """After committing, constructing a new screen with the same entries pre-skips them."""
        entries, unmatched = _make_resolved_entries(journal_app.con)
        results = []

        # First import: accept and finish
        async with journal_app.run_test() as pilot:
            journal_app.push_screen(
                JournalReviewScreen(
                    journal_app.con, "test.csv", entries, unmatched,
                ),
                callback=lambda r: results.append(r),
            )
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            await pilot.press("q")
            await pilot.pause()

        assert results[0]["committed"] == 1

        # Re-parse the same data (simulates re-import)
        entries2, unmatched2 = _make_resolved_entries(journal_app.con)

        # Verify the dedup check works at the screen constructor level
        screen2 = JournalReviewScreen(
            journal_app.con, "test2.csv", entries2, unmatched2,
        )
        assert screen2.row_states[0] == "SKP"


# -- Import File Screen Integration ------------------------------------------

class TestImportFileDetection:
    def test_qb_journal_not_detected_as_bank_profile(self):
        """QB journal CSV should not be misidentified as a bank CSV profile."""
        from pyre.importers.csv_importer import detect_bank_profile

        path = _write_csv(SAMPLE_QB_JOURNAL)
        try:
            assert detect_bank_profile(path) is None
        finally:
            os.unlink(path)

    def test_qb_journal_detected_before_bank_profiles(self):
        """detect_qb_journal should return True for QB journal files."""
        path = _write_csv(SAMPLE_QB_JOURNAL)
        try:
            assert detect_qb_journal(path) is True
        finally:
            os.unlink(path)
