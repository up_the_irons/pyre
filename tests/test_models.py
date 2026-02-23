import pytest

from pyre.formatting import cents
from pyre.models import (
    post_transaction,
    get_account_balance,
    get_transaction_detail,
    update_transaction,
    delete_transaction,
    search_transactions,
)


class TestPostTransaction:
    def test_balanced_succeeds(self, sample_accounts):
        con = sample_accounts
        tx_id = post_transaction(con, "2025-01-15", "Test deposit", [
            ("checking", cents(1000)),
            ("hosting_rev", cents(-1000)),
        ])
        assert tx_id is not None
        assert len(tx_id) == 12

    def test_unbalanced_raises(self, sample_accounts):
        con = sample_accounts
        with pytest.raises(ValueError, match="does not balance"):
            post_transaction(con, "2025-01-15", "Bad tx", [
                ("checking", cents(1000)),
                ("hosting_rev", cents(-500)),
            ])

    def test_splits_stored(self, sample_accounts):
        con = sample_accounts
        tx_id = post_transaction(con, "2025-01-15", "Test", [
            ("checking", 10000),
            ("hosting_rev", -10000),
        ])
        tx, splits = get_transaction_detail(con, tx_id)
        assert len(splits) == 2


class TestPostTransactionVendor:
    def test_post_with_vendor_id(self, sample_vendors):
        con = sample_vendors
        tx_id = post_transaction(con, "2025-01-15", "Acme purchase", [
            ("datacenter", 50000),
            ("cap1", -50000),
        ], vendor_id="acme_inc")
        tx, splits = get_transaction_detail(con, tx_id)
        assert tx[4] == "acme_inc"

    def test_post_without_vendor_id(self, sample_accounts):
        con = sample_accounts
        tx_id = post_transaction(con, "2025-01-15", "No vendor", [
            ("checking", 10000),
            ("hosting_rev", -10000),
        ])
        tx, splits = get_transaction_detail(con, tx_id)
        assert tx[4] is None

    def test_update_vendor_id(self, sample_vendors):
        con = sample_vendors
        tx_id = post_transaction(con, "2025-01-15", "Original", [
            ("checking", 10000),
            ("hosting_rev", -10000),
        ], vendor_id="acme_inc")
        tx, splits = get_transaction_detail(con, tx_id)
        split_updates = [
            (splits[0][0], splits[0][1], 10000),
            (splits[1][0], splits[1][1], -10000),
        ]
        update_transaction(con, tx_id, "2025-01-15", "Updated",
                           split_updates, vendor_id="globex_corp")
        tx, _ = get_transaction_detail(con, tx_id)
        assert tx[4] == "globex_corp"

    def test_clear_vendor_id(self, sample_vendors):
        con = sample_vendors
        tx_id = post_transaction(con, "2025-01-15", "Had vendor", [
            ("checking", 10000),
            ("hosting_rev", -10000),
        ], vendor_id="acme_inc")
        tx, splits = get_transaction_detail(con, tx_id)
        split_updates = [
            (splits[0][0], splits[0][1], 10000),
            (splits[1][0], splits[1][1], -10000),
        ]
        update_transaction(con, tx_id, "2025-01-15", "No vendor",
                           split_updates, vendor_id=None)
        tx, _ = get_transaction_detail(con, tx_id)
        assert tx[4] is None


class TestGetAccountBalance:
    def test_balance_after_transactions(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-01-15", "Deposit 1", [
            ("checking", 50000),
            ("hosting_rev", -50000),
        ])
        post_transaction(con, "2025-01-20", "Deposit 2", [
            ("checking", 30000),
            ("hosting_rev", -30000),
        ])
        assert get_account_balance(con, "checking") == 80000
        assert get_account_balance(con, "hosting_rev") == -80000

    def test_zero_balance_no_transactions(self, sample_accounts):
        con = sample_accounts
        assert get_account_balance(con, "checking") == 0


class TestUpdateTransaction:
    def test_update_amounts(self, sample_accounts):
        con = sample_accounts
        tx_id = post_transaction(con, "2025-01-15", "Original", [
            ("checking", 10000),
            ("hosting_rev", -10000),
        ])
        tx, splits = get_transaction_detail(con, tx_id)
        split_updates = [
            (splits[0][0], splits[0][1], 20000),
            (splits[1][0], splits[1][1], -20000),
        ]
        update_transaction(con, tx_id, "2025-01-16", "Updated", split_updates)

        tx, splits = get_transaction_detail(con, tx_id)
        assert tx[1] == "2025-01-16"
        assert tx[2] == "Updated"
        amounts = sorted([s[3] for s in splits])
        assert amounts == [-20000, 20000]

    def test_unbalanced_update_raises(self, sample_accounts):
        con = sample_accounts
        tx_id = post_transaction(con, "2025-01-15", "Original", [
            ("checking", 10000),
            ("hosting_rev", -10000),
        ])
        tx, splits = get_transaction_detail(con, tx_id)
        with pytest.raises(ValueError, match="does not balance"):
            update_transaction(con, tx_id, "2025-01-16", "Bad", [
                (splits[0][0], splits[0][1], 20000),
                (splits[1][0], splits[1][1], -10000),
            ])

    def test_update_account(self, sample_accounts):
        con = sample_accounts
        tx_id = post_transaction(con, "2025-01-15", "Original", [
            ("checking", 10000),
            ("hosting_rev", -10000),
        ])
        tx, splits = get_transaction_detail(con, tx_id)
        # Change the debit split from checking to usbank
        split_updates = [
            (splits[0][0], "usbank", 10000),
            (splits[1][0], splits[1][1], -10000),
        ]
        update_transaction(con, tx_id, "2025-01-15", "Original", split_updates)

        tx, splits = get_transaction_detail(con, tx_id)
        acct_ids = {s[1] for s in splits}
        assert "usbank" in acct_ids
        assert "checking" not in acct_ids
        assert get_account_balance(con, "checking") == 0
        assert get_account_balance(con, "usbank") == 10000

    def test_add_new_split(self, sample_accounts):
        con = sample_accounts
        tx_id = post_transaction(con, "2025-01-15", "Original", [
            ("checking", 10000),
            ("hosting_rev", -10000),
        ])
        tx, splits = get_transaction_detail(con, tx_id)
        # Reduce hosting_rev credit, add a new payroll credit split
        split_updates = [
            (splits[0][0], splits[0][1], 10000),
            (splits[1][0], splits[1][1], -7000),
        ]
        new_splits = [("payroll", -3000)]
        update_transaction(con, tx_id, "2025-01-15", "Original",
                           split_updates, new_splits=new_splits)

        tx, updated_splits = get_transaction_detail(con, tx_id)
        assert len(updated_splits) == 3
        amounts = sorted([s[3] for s in updated_splits])
        assert amounts == [-7000, -3000, 10000]

    def test_remove_split(self, sample_accounts):
        con = sample_accounts
        tx_id = post_transaction(con, "2025-01-15", "Original", [
            ("checking", 10000),
            ("hosting_rev", -7000),
            ("payroll", -3000),
        ])
        tx, splits = get_transaction_detail(con, tx_id)
        # Find the payroll split and remove it, adjust hosting_rev to absorb
        by_acct = {s[1]: s for s in splits}
        checking_s = by_acct["checking"]
        hosting_s = by_acct["hosting_rev"]
        payroll_s = by_acct["payroll"]
        split_updates = [
            (checking_s[0], checking_s[1], 10000),
            (hosting_s[0], hosting_s[1], -10000),
        ]
        update_transaction(con, tx_id, "2025-01-15", "Original",
                           split_updates, delete_split_ids=[payroll_s[0]])

        tx, updated_splits = get_transaction_detail(con, tx_id)
        assert len(updated_splits) == 2
        assert get_account_balance(con, "payroll") == 0

    def test_preserves_transaction_id(self, sample_accounts):
        con = sample_accounts
        tx_id = post_transaction(con, "2025-01-15", "Original", [
            ("checking", 10000),
            ("hosting_rev", -10000),
        ])
        tx, splits = get_transaction_detail(con, tx_id)
        split_updates = [
            (splits[0][0], splits[0][1], 20000),
            (splits[1][0], splits[1][1], -20000),
        ]
        update_transaction(con, tx_id, "2025-01-16", "Updated", split_updates)

        tx, _ = get_transaction_detail(con, tx_id)
        assert tx[0] == tx_id


class TestDeleteTransaction:
    def test_delete_removes_all(self, sample_accounts):
        con = sample_accounts
        tx_id = post_transaction(con, "2025-01-15", "To delete", [
            ("checking", 10000),
            ("hosting_rev", -10000),
        ])
        delete_transaction(con, tx_id)
        tx, splits = get_transaction_detail(con, tx_id)
        assert tx is None
        assert splits == []
        assert get_account_balance(con, "checking") == 0


class TestSearchTransactions:
    def test_search_by_description(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-01-15", "Hosting revenue deposit", [
            ("checking", 150000),
            ("hosting_rev", -150000),
        ])
        post_transaction(con, "2025-01-20", "Payroll transfer", [
            ("payroll", 50000),
            ("checking", -50000),
        ])
        results = search_transactions(con, "Hosting")
        assert len(results) == 1
        assert "Hosting" in results[0][1]

    def test_search_by_account_name(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-01-15", "Some payment", [
            ("datacenter", 73584),
            ("cap1", -73584),
        ])
        results = search_transactions(con, "Data Center")
        assert len(results) == 1

    def test_search_by_amount(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-01-15", "Exact amount test", [
            ("checking", 123456),
            ("hosting_rev", -123456),
        ])
        results = search_transactions(con, "$1,234.56")
        assert len(results) == 1


class TestSplitDescriptions:
    def test_post_with_description(self, sample_accounts):
        con = sample_accounts
        tx_id = post_transaction(con, "2025-01-15", "With descriptions", [
            ("checking", 10000, "deposit desc"),
            ("hosting_rev", -10000, "revenue desc"),
        ])
        tx, splits = get_transaction_detail(con, tx_id)
        descs = {s[4] for s in splits}
        assert "deposit desc" in descs
        assert "revenue desc" in descs

    def test_post_without_description_defaults_empty(self, sample_accounts):
        con = sample_accounts
        tx_id = post_transaction(con, "2025-01-15", "No descriptions", [
            ("checking", 10000),
            ("hosting_rev", -10000),
        ])
        tx, splits = get_transaction_detail(con, tx_id)
        for s in splits:
            assert s[4] == ""

    def test_update_with_description(self, sample_accounts):
        con = sample_accounts
        tx_id = post_transaction(con, "2025-01-15", "Original", [
            ("checking", 10000),
            ("hosting_rev", -10000),
        ])
        tx, splits = get_transaction_detail(con, tx_id)
        split_updates = [
            (splits[0][0], splits[0][1], 10000, "updated desc"),
            (splits[1][0], splits[1][1], -10000, "other desc"),
        ]
        update_transaction(con, tx_id, "2025-01-15", "Updated", split_updates)
        tx, splits = get_transaction_detail(con, tx_id)
        descs = {s[4] for s in splits}
        assert "updated desc" in descs
        assert "other desc" in descs
