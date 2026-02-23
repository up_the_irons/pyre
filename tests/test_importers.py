"""Tests for the bank import feature: payee rules, import log, OFX mapping,
CSV/OFX parsing, and the matching algorithm."""

import hashlib
import os
import tempfile

import pytest

from pyre.importers import ImportedTxn
from pyre.importers.models import (
    create_payee_rule,
    delete_payee_rule,
    find_account_by_ofx,
    get_payee_rules,
    is_already_imported,
    log_import,
    match_payee,
    set_account_ofx_mapping,
    update_payee_rule,
)
from pyre.importers.csv_importer import BANK_PROFILES, detect_bank_profile, parse_csv
from pyre.importers.matcher import MatchResult, match_transactions
from pyre.models import post_transaction
from pyre.ui.import_screen import _generalize_pattern


# ── Payee Rules ──────────────────────────────────────────────────────────────

class TestPayeeRules:
    def test_create_and_get(self, sample_accounts):
        rule_id = create_payee_rule(sample_accounts, "AMAZON", "expenses")
        rules = get_payee_rules(sample_accounts)
        assert len(rules) == 1
        assert rules[0]["id"] == rule_id
        assert rules[0]["pattern"] == "AMAZON"
        assert rules[0]["account_id"] == "expenses"

    def test_delete_rule(self, sample_accounts):
        rule_id = create_payee_rule(sample_accounts, "AMAZON", "expenses")
        delete_payee_rule(sample_accounts, rule_id)
        assert get_payee_rules(sample_accounts) == []

    def test_match_payee_substring(self, sample_accounts):
        create_payee_rule(sample_accounts, "AMAZON", "expenses")
        result = match_payee(sample_accounts, "AMAZON.COM*A2B3C4 PURCHASE")
        assert result["account_id"] == "expenses"

    def test_match_payee_case_insensitive(self, sample_accounts):
        create_payee_rule(sample_accounts, "amazon", "expenses")
        result = match_payee(sample_accounts, "AMAZON.COM*A2B3C4")
        assert result["account_id"] == "expenses"

    def test_match_payee_no_match(self, sample_accounts):
        create_payee_rule(sample_accounts, "AMAZON", "expenses")
        assert match_payee(sample_accounts, "NETFLIX") is None

    def test_match_payee_priority_ordering(self, sample_accounts):
        """Higher priority rule wins even if shorter."""
        create_payee_rule(sample_accounts, "AMAZON.COM", "expenses", priority=0)
        create_payee_rule(sample_accounts, "AMAZON", "payroll", priority=10)
        # "AMAZON" at priority 10 wins over "AMAZON.COM" at priority 0
        result = match_payee(sample_accounts, "AMAZON.COM*A2B3C4")
        assert result["account_id"] == "payroll"

    def test_match_payee_longest_on_tie(self, sample_accounts):
        """Same priority: longest pattern wins."""
        create_payee_rule(sample_accounts, "AMAZON", "expenses", priority=0)
        create_payee_rule(sample_accounts, "AMAZON.COM", "payroll", priority=0)
        result = match_payee(sample_accounts, "AMAZON.COM*A2B3C4")
        assert result["account_id"] == "payroll"

    def test_match_payee_wildcard(self, sample_accounts):
        """Wildcard * matches any characters."""
        create_payee_rule(sample_accounts, "THE GUARDIAN * GP INS", "expenses")
        assert match_payee(sample_accounts, "THE GUARDIAN JAN GP INS")["account_id"] == "expenses"
        assert match_payee(sample_accounts, "THE GUARDIAN FEB GP INS")["account_id"] == "expenses"
        assert match_payee(sample_accounts, "THE GUARDIAN DEC GP INS")["account_id"] == "expenses"

    def test_match_payee_wildcard_no_match(self, sample_accounts):
        create_payee_rule(sample_accounts, "THE GUARDIAN * GP INS", "expenses")
        assert match_payee(sample_accounts, "SOMETHING ELSE ENTIRELY") is None

    def test_match_payee_wildcard_case_insensitive(self, sample_accounts):
        create_payee_rule(sample_accounts, "guardian * gp ins", "expenses")
        assert match_payee(sample_accounts, "THE GUARDIAN FEB GP INS")["account_id"] == "expenses"

    def test_match_payee_wildcard_multiple_stars(self, sample_accounts):
        """Multiple wildcards in a single pattern."""
        create_payee_rule(sample_accounts, "GUSTO * FEE *", "payroll")
        assert match_payee(sample_accounts, "GUSTO TAX FEE 809387")["account_id"] == "payroll"
        assert match_payee(sample_accounts, "GUSTO PAY FEE 977554")["account_id"] == "payroll"

    def test_memo_pattern_match(self, sample_accounts):
        """Rule with memo_pattern matches when both description and memo match."""
        create_payee_rule(sample_accounts, "ONLINE TRANSFER", "expenses",
                          memo_pattern="*1234*")
        result = match_payee(sample_accounts, "ONLINE TRANSFER FROM ACME",
                             memo="CHECKING XXXXX1234")
        assert result["account_id"] == "expenses"

    def test_memo_pattern_no_match(self, sample_accounts):
        """Rule with memo_pattern does NOT match when memo doesn't match."""
        create_payee_rule(sample_accounts, "ONLINE TRANSFER", "expenses",
                          memo_pattern="*1234*")
        assert match_payee(sample_accounts, "ONLINE TRANSFER FROM ACME",
                           memo="CHECKING XXXXX9999") is None

    def test_memo_pattern_null_ignored(self, sample_accounts):
        """Rule without memo_pattern matches on description alone (backward compat)."""
        create_payee_rule(sample_accounts, "ONLINE TRANSFER", "expenses")
        result = match_payee(sample_accounts, "ONLINE TRANSFER FROM ACME",
                             memo="anything here")
        assert result["account_id"] == "expenses"

    def test_memo_pattern_wildcard(self, sample_accounts):
        """Memo pattern supports wildcard matching."""
        create_payee_rule(sample_accounts, "TRANSFER", "payroll",
                          memo_pattern="SAVINGS *9012*")
        assert match_payee(sample_accounts, "TRANSFER FROM BANK",
                           memo="SAVINGS XXXXX9012")["account_id"] == "payroll"
        assert match_payee(sample_accounts, "TRANSFER FROM BANK",
                           memo="CHECKING XXXXX1234") is None

    def test_memo_pattern_empty_memo_no_match(self, sample_accounts):
        """Rule with memo_pattern should not match when memo is empty."""
        create_payee_rule(sample_accounts, "ONLINE TRANSFER", "expenses",
                          memo_pattern="*1234*")
        assert match_payee(sample_accounts, "ONLINE TRANSFER FROM ACME", memo="") is None

    def test_create_rule_with_memo_pattern(self, sample_accounts):
        """memo_pattern is stored and returned by get_payee_rules."""
        create_payee_rule(sample_accounts, "TEST", "expenses", memo_pattern="*MEMO*")
        rules = get_payee_rules(sample_accounts)
        assert rules[0]["memo_pattern"] == "*MEMO*"

    def test_update_rule_memo_pattern(self, sample_accounts):
        """update_payee_rule can set memo_pattern."""
        rule_id = create_payee_rule(sample_accounts, "TEST", "expenses")
        update_payee_rule(sample_accounts, rule_id, "TEST", memo_pattern="*NEW*")
        rules = get_payee_rules(sample_accounts)
        assert rules[0]["memo_pattern"] == "*NEW*"

    def test_update_rule_clear_memo_pattern(self, sample_accounts):
        """update_payee_rule can clear memo_pattern back to None."""
        rule_id = create_payee_rule(sample_accounts, "TEST", "expenses",
                                     memo_pattern="*OLD*")
        update_payee_rule(sample_accounts, rule_id, "TEST", memo_pattern=None)
        rules = get_payee_rules(sample_accounts)
        assert rules[0]["memo_pattern"] is None

    def test_memo_rule_beats_longer_description_only_rule(self, sample_accounts):
        """A rule with memo_pattern should win over a longer description-only rule."""
        # Longer description pattern, no memo -- less specific
        create_payee_rule(sample_accounts, "CHASE BANK TRANSFER", "expenses")
        # Shorter description pattern, but has memo -- more specific
        create_payee_rule(sample_accounts, "CHASE BANK", "interest",
                          memo_pattern="LOAN PMT")

        result = match_payee(sample_accounts, "CHASE BANK TRANSFER",
                             memo="LOAN PMT")
        assert result["account_id"] == "interest"

    def test_memo_rule_skipped_when_memo_doesnt_match(self, sample_accounts):
        """Memo rule loses when memo doesn't match; description-only rule wins."""
        create_payee_rule(sample_accounts, "CHASE BANK TRANSFER", "expenses")
        create_payee_rule(sample_accounts, "CHASE BANK", "interest",
                          memo_pattern="LOAN PMT")

        # Memo doesn't match the memo rule, so description-only rule should win
        result = match_payee(sample_accounts, "CHASE BANK TRANSFER",
                             memo="WIRE PAYMENT")
        assert result["account_id"] == "expenses"

    def test_memo_rule_priority_still_respected(self, sample_accounts):
        """Explicit priority still trumps memo specificity."""
        # Higher priority, no memo
        create_payee_rule(sample_accounts, "CHASE", "expenses", priority=10)
        # Lower priority, has memo
        create_payee_rule(sample_accounts, "CHASE", "interest",
                          priority=0, memo_pattern="LOAN PMT")

        result = match_payee(sample_accounts, "CHASE BANK TRANSFER",
                             memo="LOAN PMT")
        assert result["account_id"] == "expenses"

    def test_match_payee_returns_vendor_id(self, sample_vendors):
        """match_payee returns vendor_id when rule has one."""
        create_payee_rule(sample_vendors, "ACME", "expenses",
                          vendor_id="acme_inc")
        result = match_payee(sample_vendors, "ACME PURCHASE")
        assert result["account_id"] == "expenses"
        assert result["vendor_id"] == "acme_inc"

    def test_match_payee_vendor_id_none_when_unset(self, sample_accounts):
        """match_payee returns vendor_id=None when rule has no vendor."""
        create_payee_rule(sample_accounts, "AMAZON", "expenses")
        result = match_payee(sample_accounts, "AMAZON.COM PURCHASE")
        assert result["account_id"] == "expenses"
        assert result["vendor_id"] is None

    def test_create_rule_with_vendor_id(self, sample_vendors):
        """vendor_id is stored and returned by get_payee_rules."""
        create_payee_rule(sample_vendors, "TEST", "expenses",
                          vendor_id="globex_corp")
        rules = get_payee_rules(sample_vendors)
        assert rules[0]["vendor_id"] == "globex_corp"

    def test_update_rule_vendor_id(self, sample_vendors):
        """update_payee_rule can set vendor_id."""
        rule_id = create_payee_rule(sample_vendors, "TEST", "expenses")
        update_payee_rule(sample_vendors, rule_id, "TEST",
                          vendor_id="initech")
        rules = get_payee_rules(sample_vendors)
        assert rules[0]["vendor_id"] == "initech"

    def test_update_rule_clear_vendor_id(self, sample_vendors):
        """update_payee_rule can clear vendor_id back to None."""
        rule_id = create_payee_rule(sample_vendors, "TEST", "expenses",
                                     vendor_id="acme_inc")
        update_payee_rule(sample_vendors, rule_id, "TEST", vendor_id=None)
        rules = get_payee_rules(sample_vendors)
        assert rules[0]["vendor_id"] is None


# ── Import Log ───────────────────────────────────────────────────────────────

class TestImportLog:
    def test_log_and_check_fitid(self, sample_accounts):
        log_import(sample_accounts, "test.ofx", "FITID123", None, None, "imported", account_id="checking")
        assert is_already_imported(sample_accounts, "FITID123", None, "checking") is True
        assert is_already_imported(sample_accounts, "OTHER", None, "checking") is False

    def test_log_and_check_hash(self, sample_accounts):
        log_import(sample_accounts, "test.csv", None, "abc123hash", None, "imported", account_id="checking")
        assert is_already_imported(sample_accounts, None, "abc123hash", "checking") is True
        assert is_already_imported(sample_accounts, None, "other_hash", "checking") is False

    def test_fitid_dedup_unique(self, sample_accounts):
        """Duplicate fitid+account should raise on insert."""
        log_import(sample_accounts, "test.ofx", "DUP_FITID", None, None, "imported", account_id="checking")
        with pytest.raises(Exception):
            log_import(sample_accounts, "test.ofx", "DUP_FITID", None, None, "imported", account_id="checking")

    def test_hash_dedup_unique(self, sample_accounts):
        """Duplicate hash+account should raise on insert."""
        log_import(sample_accounts, "test.csv", None, "DUP_HASH", None, "imported", account_id="checking")
        with pytest.raises(Exception):
            log_import(sample_accounts, "test.csv", None, "DUP_HASH", None, "imported", account_id="checking")

    def test_none_fitid_and_hash_not_deduped(self, sample_accounts):
        """Multiple entries with None fitid and None hash should be OK."""
        log_import(sample_accounts, "a.csv", None, None, None, "skipped", account_id="checking")
        log_import(sample_accounts, "b.csv", None, None, None, "skipped", account_id="checking")
        assert is_already_imported(sample_accounts, None, None, "checking") is False

    def test_same_fitid_different_accounts(self, sample_accounts):
        """Same FITID in different accounts should NOT be treated as duplicate."""
        log_import(sample_accounts, "test.ofx", "SHARED_FIT", None, None, "imported", account_id="checking")
        # Same fitid for a different account should not be considered imported
        assert is_already_imported(sample_accounts, "SHARED_FIT", None, "cap1") is False
        # But same account should still detect it
        assert is_already_imported(sample_accounts, "SHARED_FIT", None, "checking") is True

    def test_same_hash_different_accounts(self, sample_accounts):
        """Same hash in different accounts should NOT be treated as duplicate."""
        log_import(sample_accounts, "test.csv", None, "SHARED_HASH", None, "imported", account_id="checking")
        assert is_already_imported(sample_accounts, None, "SHARED_HASH", "cap1") is False
        assert is_already_imported(sample_accounts, None, "SHARED_HASH", "checking") is True


# ── OFX Account Mapping ─────────────────────────────────────────────────────

class TestOFXMapping:
    def test_set_and_find(self, sample_accounts):
        set_account_ofx_mapping(sample_accounts, "checking", "021000021", "1234567890")
        result = find_account_by_ofx(sample_accounts, "021000021", "1234567890")
        assert result is not None
        assert result["id"] == "checking"
        assert result["name"] == "Main Checking"

    def test_find_no_match(self, sample_accounts):
        result = find_account_by_ofx(sample_accounts, "999999", "000000")
        assert result is None

    def test_find_by_acctid_only(self, sample_accounts):
        """Credit cards may not have a bankid."""
        set_account_ofx_mapping(sample_accounts, "cap1", None, "4111111111115678")
        result = find_account_by_ofx(sample_accounts, None, "4111111111115678")
        assert result is not None
        assert result["id"] == "cap1"

    def test_round_trip(self, sample_accounts):
        set_account_ofx_mapping(sample_accounts, "checking", "021000021", "1234")
        acct = find_account_by_ofx(sample_accounts, "021000021", "1234")
        assert acct["id"] == "checking"
        assert acct["type"] == "asset"


# ── CSV Parser ───────────────────────────────────────────────────────────────

class TestCSVParser:
    def _write_csv(self, content):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8")
        f.write(content)
        f.close()
        return f.name

    def test_wells_fargo_format(self):
        csv_content = (
            "Date,Description,Debit,Credit\n"
            "01/15/2026,PAYROLL DEPOSIT,,5000.00\n"
            "01/16/2026,AMAZON.COM*A2B3C4,47.99,\n"
        )
        path = self._write_csv(csv_content)
        try:
            txns = parse_csv(path, "wells_fargo")
            assert len(txns) == 2
            assert txns[0].date == "2026-01-15"
            assert txns[0].description == "PAYROLL DEPOSIT"
            assert txns[0].amount_cents == 500000
            assert txns[1].amount_cents == -4799
            assert txns[1].txn_type == "DEBIT"
        finally:
            os.unlink(path)

    def test_capital_one_cc_format(self):
        csv_content = (
            "Transaction Date,Posted Date,Card No.,Description,Category,Debit,Credit\n"
            "2026-01-16,2026-01-17,5678,AMAZON.COM,Shopping,47.99,\n"
            "2026-01-20,2026-01-21,5678,PAYMENT RECEIVED,,500.00,\n"
        )
        path = self._write_csv(csv_content)
        try:
            txns = parse_csv(path, "capital_one_cc")
            assert len(txns) == 2
            assert txns[0].date == "2026-01-16"
            assert txns[0].amount_cents == -4799
            assert txns[1].amount_cents == -50000
        finally:
            os.unlink(path)

    def test_us_bank_format(self):
        csv_content = (
            "Date,Description,Amount\n"
            "2026-01-15,DIRECT DEPOSIT,5000.00\n"
            "2026-01-16,CHECK 1234,-123.45\n"
        )
        path = self._write_csv(csv_content)
        try:
            txns = parse_csv(path, "us_bank")
            assert len(txns) == 2
            assert txns[0].amount_cents == 500000
            assert txns[1].amount_cents == -12345
        finally:
            os.unlink(path)

    def test_hash_determinism(self):
        csv_content = (
            "Date,Description,Amount\n"
            "2026-01-15,DIRECT DEPOSIT,5000.00\n"
        )
        path = self._write_csv(csv_content)
        try:
            txns1 = parse_csv(path, "us_bank")
            txns2 = parse_csv(path, "us_bank")
            assert txns1[0].hash == txns2[0].hash
            assert txns1[0].hash is not None
        finally:
            os.unlink(path)

    def test_detect_wells_fargo(self):
        csv_content = "Date,Description,Debit,Credit\n01/15/2026,TEST,,100.00\n"
        path = self._write_csv(csv_content)
        try:
            assert detect_bank_profile(path) == "wells_fargo"
        finally:
            os.unlink(path)

    def test_detect_capital_one(self):
        csv_content = "Transaction Date,Posted Date,Card No.,Description,Category,Debit,Credit\n"
        path = self._write_csv(csv_content)
        try:
            assert detect_bank_profile(path) == "capital_one_cc"
        finally:
            os.unlink(path)

    def test_detect_us_bank(self):
        csv_content = "Date,Description,Amount\n2026-01-15,TEST,100.00\n"
        path = self._write_csv(csv_content)
        try:
            assert detect_bank_profile(path) == "us_bank"
        finally:
            os.unlink(path)

    def test_empty_csv_returns_none(self):
        path = self._write_csv("")
        try:
            assert detect_bank_profile(path) is None
        finally:
            os.unlink(path)


# ── Matching Algorithm ───────────────────────────────────────────────────────

class TestMatcher:
    def _make_txn(self, date="2026-01-15", desc="TEST VENDOR", amount=-5000,
                  fitid=None, hash_val=None):
        return ImportedTxn(
            date=date,
            description=desc,
            amount_cents=amount,
            fitid=fitid,
            memo="",
            txn_type="DEBIT",
            hash=hash_val,
        )

    def test_exact_match(self, sample_accounts):
        """Transaction with exact amount and date should match."""
        # Create a manual transaction in the ledger
        tx_id = post_transaction(sample_accounts, "2026-01-15", "Manual entry", [
            ("checking", -5000),
            ("expenses", 5000),
        ])

        imported = [self._make_txn(date="2026-01-15", amount=-5000)]
        results = match_transactions(sample_accounts, imported, "checking")

        assert len(results) == 1
        assert results[0].state == "MATCH"
        assert results[0].matched_tx_id == tx_id
        assert results[0].confidence > 0.9

    def test_no_match_different_amount(self, sample_accounts):
        """Different amount should not match."""
        post_transaction(sample_accounts, "2026-01-15", "Manual entry", [
            ("checking", -5000),
            ("expenses", 5000),
        ])

        imported = [self._make_txn(date="2026-01-15", amount=-9999)]
        results = match_transactions(sample_accounts, imported, "checking")

        assert len(results) == 1
        assert results[0].state == "NEW"

    def test_match_within_date_window(self, sample_accounts):
        """Transaction within 5-day window should match."""
        tx_id = post_transaction(sample_accounts, "2026-01-13", "Manual entry", [
            ("checking", -5000),
            ("expenses", 5000),
        ])

        imported = [self._make_txn(date="2026-01-15", amount=-5000)]
        results = match_transactions(sample_accounts, imported, "checking")

        assert results[0].state == "MATCH"
        assert results[0].matched_tx_id == tx_id

    def test_no_match_outside_date_window(self, sample_accounts):
        """Transaction outside 5-day window should not match."""
        post_transaction(sample_accounts, "2026-01-01", "Manual entry", [
            ("checking", -5000),
            ("expenses", 5000),
        ])

        imported = [self._make_txn(date="2026-01-15", amount=-5000)]
        results = match_transactions(sample_accounts, imported, "checking")

        assert results[0].state == "NEW"

    def test_auto_from_payee_rule(self, sample_accounts):
        """Payee rule should produce AUTO state."""
        create_payee_rule(sample_accounts, "AMAZON", "expenses")

        imported = [self._make_txn(desc="AMAZON.COM*PURCHASE")]
        results = match_transactions(sample_accounts, imported, "checking")

        assert results[0].state == "AUTO"
        assert results[0].suggested_account_id == "expenses"
        assert results[0].suggested_vendor_id is None

    def test_auto_from_payee_rule_with_vendor(self, sample_vendors):
        """Payee rule with vendor_id should populate vendor fields on AUTO."""
        create_payee_rule(sample_vendors, "ACME", "expenses",
                          vendor_id="acme_inc")

        imported = [self._make_txn(desc="ACME PURCHASE")]
        results = match_transactions(sample_vendors, imported, "checking")

        assert results[0].state == "AUTO"
        assert results[0].suggested_account_id == "expenses"
        assert results[0].suggested_vendor_id == "acme_inc"
        assert results[0].suggested_vendor_name == "Acme Inc"

    def test_already_imported_skip(self, sample_accounts):
        """Already-imported fitid should produce SKIP."""
        log_import(sample_accounts, "old.ofx", "FIT001", None, None, "imported", account_id="checking")

        imported = [self._make_txn(fitid="FIT001")]
        results = match_transactions(sample_accounts, imported, "checking")

        assert results[0].state == "SKIP"

    def test_already_imported_hash_skip(self, sample_accounts):
        """Already-imported hash should produce SKIP."""
        log_import(sample_accounts, "old.csv", None, "HASH001", None, "imported", account_id="checking")

        imported = [self._make_txn(hash_val="HASH001")]
        results = match_transactions(sample_accounts, imported, "checking")

        assert results[0].state == "SKIP"

    def test_cross_account_fitid_not_skipped(self, sample_accounts):
        """FITID imported into one account should NOT cause skip in another."""
        log_import(sample_accounts, "old.ofx", "FIT001", None, None, "imported", account_id="cap1")

        imported = [self._make_txn(fitid="FIT001")]
        results = match_transactions(sample_accounts, imported, "checking")

        assert results[0].state != "SKIP"

    def test_match_excludes_already_linked(self, sample_accounts):
        """Transaction already linked in import_log should not be matched again."""
        tx_id = post_transaction(sample_accounts, "2026-01-15", "Already linked", [
            ("checking", -5000),
            ("expenses", 5000),
        ])
        log_import(sample_accounts, "prev.ofx", "PREV_FIT", None, tx_id, "matched", account_id="checking")

        imported = [self._make_txn(date="2026-01-15", amount=-5000, fitid="NEW_FIT")]
        results = match_transactions(sample_accounts, imported, "checking")

        # Should not match the already-linked tx
        assert results[0].state == "NEW"

    def test_cross_account_transfer_matches(self, sample_accounts):
        """Transfer imported from one bank should MATCH when importing the other side."""
        # Step 1: Import a transfer from main checking to other checking
        tx_id = post_transaction(sample_accounts, "2026-01-15", "TRANSFER TO OTHER BANK", [
            ("checking", -50000),
            ("usbank", 50000),
        ])
        log_import(sample_accounts, "bank.ofx", "BANK_FIT_001", None,
                   tx_id, "imported", account_id="checking")

        # Step 2: Import from other bank -- the same transfer, opposite direction
        imported = [self._make_txn(date="2026-01-15", desc="TRANSFER FROM MAIN",
                                   amount=50000)]
        results = match_transactions(sample_accounts, imported, "usbank")

        # Should match the existing transaction, not create a duplicate
        assert results[0].state == "MATCH"
        assert results[0].matched_tx_id == tx_id

    def test_same_account_still_excludes_linked(self, sample_accounts):
        """Transaction already linked from the SAME account should still be excluded."""
        tx_id = post_transaction(sample_accounts, "2026-01-15", "Already linked", [
            ("checking", -5000),
            ("expenses", 5000),
        ])
        log_import(sample_accounts, "prev.ofx", "PREV_FIT", None,
                   tx_id, "matched", account_id="checking")

        imported = [self._make_txn(date="2026-01-15", amount=-5000, fitid="NEW_FIT")]
        results = match_transactions(sample_accounts, imported, "checking")

        # Same account -- should NOT match the already-linked tx
        assert results[0].state == "NEW"

    def test_new_when_no_match_no_rule(self, sample_accounts):
        """No match and no payee rule -> NEW."""
        imported = [self._make_txn(desc="UNKNOWN VENDOR")]
        results = match_transactions(sample_accounts, imported, "checking")

        assert results[0].state == "NEW"
        assert results[0].confidence == 0.0


# ── Pattern Generalization ───────────────────────────────────────────────

class TestGeneralizePattern:
    def test_stripe_transfer_id(self):
        assert _generalize_pattern("STRIPE TRANSFER ST-J1F0P8E2Z3N1") == "STRIPE TRANSFER"

    def test_amazon_star_id(self):
        assert _generalize_pattern("AMAZON.COM*A2B3C4") == "AMAZON.COM"

    def test_no_change_when_no_id(self):
        assert _generalize_pattern("PAYPAL TRANSFER") == "PAYPAL TRANSFER"

    def test_preserves_meaningful_words(self):
        assert _generalize_pattern("ONLINE TRANSFER TO ACME CORP") == "ONLINE TRANSFER TO ACME CORP"

    def test_strips_trailing_digits(self):
        assert _generalize_pattern("JPMorgan Chase Ext Trnsfr 2601") == "JPMorgan Chase Ext Trnsfr"

    def test_check_number(self):
        assert _generalize_pattern("CHECK 1234") == "CHECK"

    def test_capital_one_pmt_unchanged(self):
        assert _generalize_pattern("CAPITAL ONE ONLINE PMT") == "CAPITAL ONE ONLINE PMT"

    def test_us_bank_transfer_unchanged(self):
        assert _generalize_pattern("US BANK TRANSFER TRANSFER") == "US BANK TRANSFER TRANSFER"

    def test_empty_after_strip_returns_original(self):
        """If stripping would leave empty, return the original."""
        assert _generalize_pattern("*ABC123") != ""

    def test_whitespace_only_input(self):
        assert _generalize_pattern("   SOME VENDOR   ") == "SOME VENDOR"

    def test_hash_ref_number(self):
        assert _generalize_pattern("PURCHASE#78901") == "PURCHASE"

    def test_multiple_stripe_variants(self):
        """All Stripe transfers should generalize to the same pattern."""
        ids = [
            "STRIPE TRANSFER ST-J1F0P8E2Z3N1",
            "STRIPE TRANSFER ST-S2H5J6I3J4T7",
            "STRIPE TRANSFER ST-M8F3R7U0S9H1",
            "STRIPE TRANSFER ST-E5D8L9B4L5M6",
        ]
        results = {_generalize_pattern(d) for d in ids}
        assert results == {"STRIPE TRANSFER"}
