"""Shared utilities for account operations."""

import re
from collections import OrderedDict


def slugify(name):
    """Convert account name to a stable slug ID.

    e.g. "First National **1234" -> "first_national_1234"
    """
    s = name.lower()
    s = re.sub(r"[*]+", "", s)           # strip asterisks
    s = re.sub(r"[()/'\"&,.]", "", s)    # strip punctuation
    s = re.sub(r"[^a-z0-9]+", "_", s)    # non-alnum -> underscore
    s = s.strip("_")
    return s


ACCOUNT_CATEGORIES = OrderedDict([
    ("Assets", [
        "asset", "accounts_receivable", "other_current_asset",
        "fixed_asset", "other_asset",
    ]),
    ("Liabilities", [
        "liability", "accounts_payable", "credit_card",
        "other_current_liability", "long_term_liability",
    ]),
    ("Equity", ["equity"]),
    ("Income", ["income", "other_income"]),
    ("Expenses", ["expense", "cost_of_goods_sold", "other_expense"]),
])


def get_account_category(account_type):
    """Return the category name for a given account type."""
    for category, types in ACCOUNT_CATEGORIES.items():
        if account_type in types:
            return category
    return None


def get_all_account_types():
    """Return a flat list of all 16 account types."""
    result = []
    for types in ACCOUNT_CATEGORIES.values():
        result.extend(types)
    return result


DEBIT_TYPES = (
    'asset', 'accounts_receivable', 'other_current_asset',
    'fixed_asset', 'other_asset',
    'expense', 'cost_of_goods_sold', 'other_expense',
)


def normal_balance_direction(account_type):
    """Return the normal balance direction for an account type."""
    return "DR" if account_type in DEBIT_TYPES else "CR"
