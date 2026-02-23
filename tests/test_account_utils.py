"""Tests for account_utils module."""

from pyre.account_utils import slugify, get_account_category, get_all_account_types


class TestSlugify:
    def test_simple_name(self):
        assert slugify("Cash") == "cash"

    def test_spaces(self):
        assert slugify("Opening Balance Equity") == "opening_balance_equity"

    def test_asterisks(self):
        assert slugify("First National **1234") == "first_national_1234"

    def test_parentheses(self):
        assert slugify("Accounts Receivable (A/R)") == "accounts_receivable_ar"

    def test_ampersand(self):
        assert slugify("Salary & Wages") == "salary_wages"

    def test_commas_and_quotes(self):
        assert slugify("Travel, Per Diem") == "travel_per_diem"


class TestGetAccountCategory:
    def test_asset(self):
        assert get_account_category("asset") == "Assets"

    def test_credit_card(self):
        assert get_account_category("credit_card") == "Liabilities"

    def test_equity(self):
        assert get_account_category("equity") == "Equity"

    def test_income(self):
        assert get_account_category("income") == "Income"

    def test_expense(self):
        assert get_account_category("expense") == "Expenses"

    def test_cost_of_goods_sold(self):
        assert get_account_category("cost_of_goods_sold") == "Expenses"

    def test_unknown_returns_none(self):
        assert get_account_category("bogus") is None


class TestGetAllAccountTypes:
    def test_returns_16_types(self):
        types = get_all_account_types()
        assert len(types) == 16

    def test_contains_key_types(self):
        types = get_all_account_types()
        assert "asset" in types
        assert "liability" in types
        assert "equity" in types
        assert "income" in types
        assert "expense" in types
        assert "credit_card" in types
        assert "cost_of_goods_sold" in types

    def test_no_duplicates(self):
        types = get_all_account_types()
        assert len(types) == len(set(types))
