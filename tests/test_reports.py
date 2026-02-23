import pytest

from pyre.formatting import cents
from pyre.models import finish_reconciliation, post_transaction
from pyre.reports import generate_pnl, generate_balance_sheet, generate_trial_balance, generate_cash_flow, generate_expenses_by_vendor, generate_reconciliation_report


class TestGeneratePnl:
    def test_income_shown_positive(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-01-15", "Revenue", [
            ("checking", cents(15000)),
            ("hosting_rev", cents(-15000)),
        ])
        data = generate_pnl(con, "2025-01-01", "2025-12-31")
        # income_total should be positive for display
        assert data['income_total'] == cents(15000)

    def test_expenses_shown_positive(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-01-20", "Colocation", [
            ("datacenter", cents(7358.39)),
            ("cap1", cents(-7358.39)),
        ])
        data = generate_pnl(con, "2025-01-01", "2025-12-31")
        assert data['expense_total'] == cents(7358.39)

    def test_net_income_calculation(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-01-15", "Revenue", [
            ("checking", cents(15000)),
            ("hosting_rev", cents(-15000)),
        ])
        post_transaction(con, "2025-01-20", "Expense", [
            ("datacenter", cents(5000)),
            ("cap1", cents(-5000)),
        ])
        data = generate_pnl(con, "2025-01-01", "2025-12-31")
        assert data['net_income'] == cents(15000) - cents(5000)

    def test_date_filtering(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-01-15", "In range", [
            ("checking", cents(1000)),
            ("hosting_rev", cents(-1000)),
        ])
        post_transaction(con, "2025-06-15", "Out of range", [
            ("checking", cents(2000)),
            ("hosting_rev", cents(-2000)),
        ])
        data = generate_pnl(con, "2025-01-01", "2025-01-31")
        assert data['income_total'] == cents(1000)

    def test_hierarchical_subtotals(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-01-10", "DC expense", [
            ("datacenter", cents(3000)),
            ("cap1", cents(-3000)),
        ])
        post_transaction(con, "2025-01-11", "Cloud expense", [
            ("cloud", cents(2000)),
            ("cap1", cents(-2000)),
        ])
        data = generate_pnl(con, "2025-01-01", "2025-12-31")
        # Find the indirect_exp node and verify subtotal
        expenses_root = [r for r in data['roots'] if r['type'] == 'expense'][0]
        indirect = [c for c in expenses_root['children']
                    if c['id'] == 'indirect_exp'][0]
        assert indirect['subtotal'] == cents(3000) + cents(2000)

    def test_empty_pnl_no_transactions(self, sample_accounts):
        con = sample_accounts
        data = generate_pnl(con, "2025-01-01", "2025-12-31")
        assert data['income_total'] == 0
        assert data['expense_total'] == 0
        assert data['net_income'] == 0


class TestGenerateBalanceSheet:
    def test_empty_balance_sheet(self, sample_accounts):
        con = sample_accounts
        data = generate_balance_sheet(con, "2025-12-31")
        assert data['total_assets'] == 0
        assert data['total_liabilities'] == 0
        assert data['total_equity'] == 0
        assert data['net_income'] == 0

    def test_asset_balance(self, sample_accounts):
        con = sample_accounts
        # Debit checking (asset), credit equity (opening balance)
        post_transaction(con, "2025-01-01", "Opening balance", [
            ("checking", cents(50000)),
            ("equity", cents(-50000)),
        ])
        data = generate_balance_sheet(con, "2025-12-31")
        assert data['total_assets'] == cents(50000)
        assert data['total_equity'] == cents(50000)

    def test_liability_shown_positive(self, sample_accounts):
        con = sample_accounts
        # Credit card purchase: debit expense, credit credit card
        post_transaction(con, "2025-01-15", "Purchase", [
            ("datacenter", cents(7000)),
            ("cap1", cents(-7000)),
        ])
        data = generate_balance_sheet(con, "2025-12-31")
        # Liability stored as negative (credit), displayed as positive
        assert data['total_liabilities'] == cents(7000)

    def test_assets_equal_liabilities_plus_equity(self, sample_accounts):
        con = sample_accounts
        # Opening balance
        post_transaction(con, "2025-01-01", "Opening", [
            ("checking", cents(100000)),
            ("equity", cents(-100000)),
        ])
        # Credit card purchase
        post_transaction(con, "2025-01-15", "Expense", [
            ("datacenter", cents(5000)),
            ("cap1", cents(-5000)),
        ])
        # Revenue
        post_transaction(con, "2025-02-01", "Revenue", [
            ("checking", cents(20000)),
            ("hosting_rev", cents(-20000)),
        ])
        data = generate_balance_sheet(con, "2025-12-31")
        # A = L + E (the accounting equation)
        assert data['total_assets'] == data['total_liabilities_and_equity']

    def test_date_cutoff(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-01-15", "Before cutoff", [
            ("checking", cents(10000)),
            ("equity", cents(-10000)),
        ])
        post_transaction(con, "2025-06-15", "After cutoff", [
            ("checking", cents(5000)),
            ("equity", cents(-5000)),
        ])
        data = generate_balance_sheet(con, "2025-03-31")
        assert data['total_assets'] == cents(10000)

    def test_net_income_included(self, sample_accounts):
        con = sample_accounts
        # Opening balance in checking
        post_transaction(con, "2025-01-01", "Opening", [
            ("checking", cents(100000)),
            ("equity", cents(-100000)),
        ])
        # Revenue increases checking
        post_transaction(con, "2025-02-01", "Revenue", [
            ("checking", cents(15000)),
            ("hosting_rev", cents(-15000)),
        ])
        data = generate_balance_sheet(con, "2025-12-31")
        assert data['net_income'] == cents(15000)
        # Assets = 100000 + 15000 = 115000
        assert data['total_assets'] == cents(115000)
        # L + E = equity(100000) + net_income(15000) = 115000
        assert data['total_liabilities_and_equity'] == cents(115000)


class TestGenerateTrialBalance:
    def test_empty_trial_balance(self, sample_accounts):
        con = sample_accounts
        data = generate_trial_balance(con, "2025-12-31")
        assert data['accounts'] == []
        assert data['total_debit'] == 0
        assert data['total_credit'] == 0

    def test_debits_equal_credits(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-01-01", "Opening", [
            ("checking", cents(50000)),
            ("equity", cents(-50000)),
        ])
        post_transaction(con, "2025-01-15", "Revenue", [
            ("checking", cents(10000)),
            ("hosting_rev", cents(-10000)),
        ])
        post_transaction(con, "2025-01-20", "Expense", [
            ("datacenter", cents(3000)),
            ("cap1", cents(-3000)),
        ])
        data = generate_trial_balance(con, "2025-12-31")
        assert data['total_debit'] == data['total_credit']

    def test_asset_in_debit_column(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-01-01", "Opening", [
            ("checking", cents(50000)),
            ("equity", cents(-50000)),
        ])
        data = generate_trial_balance(con, "2025-12-31")
        checking = next(a for a in data['accounts'] if a['id'] == 'checking')
        assert checking['debit'] == cents(50000)
        assert checking['credit'] == 0

    def test_liability_in_credit_column(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-01-15", "Purchase", [
            ("datacenter", cents(7000)),
            ("cap1", cents(-7000)),
        ])
        data = generate_trial_balance(con, "2025-12-31")
        cap1 = next(a for a in data['accounts'] if a['id'] == 'cap1')
        assert cap1['credit'] == cents(7000)
        assert cap1['debit'] == 0

    def test_income_in_credit_column(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-01-15", "Revenue", [
            ("checking", cents(15000)),
            ("hosting_rev", cents(-15000)),
        ])
        data = generate_trial_balance(con, "2025-12-31")
        hosting = next(a for a in data['accounts'] if a['id'] == 'hosting_rev')
        assert hosting['credit'] == cents(15000)
        assert hosting['debit'] == 0

    def test_expense_in_debit_column(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-01-20", "Colo", [
            ("datacenter", cents(5000)),
            ("cap1", cents(-5000)),
        ])
        data = generate_trial_balance(con, "2025-12-31")
        dc = next(a for a in data['accounts'] if a['id'] == 'datacenter')
        assert dc['debit'] == cents(5000)
        assert dc['credit'] == 0

    def test_date_cutoff(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-01-15", "Before cutoff", [
            ("checking", cents(10000)),
            ("equity", cents(-10000)),
        ])
        post_transaction(con, "2025-06-15", "After cutoff", [
            ("checking", cents(5000)),
            ("equity", cents(-5000)),
        ])
        data = generate_trial_balance(con, "2025-03-31")
        checking = next(a for a in data['accounts'] if a['id'] == 'checking')
        assert checking['debit'] == cents(10000)

    def test_zero_balance_omitted(self, sample_accounts):
        con = sample_accounts
        # Post and then reverse so checking nets to zero
        post_transaction(con, "2025-01-01", "In", [
            ("checking", cents(5000)),
            ("equity", cents(-5000)),
        ])
        post_transaction(con, "2025-01-02", "Out", [
            ("checking", cents(-5000)),
            ("equity", cents(5000)),
        ])
        data = generate_trial_balance(con, "2025-12-31")
        ids = [a['id'] for a in data['accounts']]
        assert 'checking' not in ids
        assert 'equity' not in ids


class TestGenerateCashFlow:
    def test_empty_cash_flow(self, sample_accounts):
        con = sample_accounts
        data = generate_cash_flow(con, "2025-01-01", "2025-12-31")
        assert data["operating"] == []
        assert data["investing"] == []
        assert data["financing"] == []
        assert data["total_operating"] == 0
        assert data["total_investing"] == 0
        assert data["total_financing"] == 0
        assert data["net_change"] == 0
        assert data["beginning_balance"] == 0
        assert data["ending_balance"] == 0

    def test_revenue_is_operating_inflow(self, sample_accounts):
        con = sample_accounts
        # Cash received from revenue: debit checking (asset), credit income
        post_transaction(con, "2025-01-15", "Revenue", [
            ("checking", cents(15000)),
            ("hosting_rev", cents(-15000)),
        ])
        data = generate_cash_flow(con, "2025-01-01", "2025-12-31")
        assert len(data["operating"]) == 1
        assert data["operating"][0]["name"] == "Hosting"
        # Income credited -> negated -> positive = cash inflow
        assert data["operating"][0]["amount"] == cents(15000)
        assert data["total_operating"] == cents(15000)

    def test_expense_payment_is_operating_outflow(self, sample_accounts):
        con = sample_accounts
        # Pay expense from cash: debit expense, credit checking (asset)
        post_transaction(con, "2025-01-20", "Colocation", [
            ("datacenter", cents(7000)),
            ("checking", cents(-7000)),
        ])
        data = generate_cash_flow(con, "2025-01-01", "2025-12-31")
        assert len(data["operating"]) == 1
        assert data["operating"][0]["name"] == "Data Center"
        # Expense debited -> negated -> negative = cash outflow
        assert data["operating"][0]["amount"] == cents(-7000)
        assert data["total_operating"] == cents(-7000)

    def test_credit_card_payment_is_operating(self, sample_accounts):
        con = sample_accounts
        # Pay credit card from checking: debit credit_card, credit checking
        post_transaction(con, "2025-01-25", "CC Payment", [
            ("cap1", cents(5000)),
            ("checking", cents(-5000)),
        ])
        data = generate_cash_flow(con, "2025-01-01", "2025-12-31")
        # credit_card is operating per classification
        assert len(data["operating"]) == 1
        assert data["operating"][0]["name"] == "Rewards Visa"
        assert data["operating"][0]["amount"] == cents(-5000)

    def test_equity_is_financing(self, sample_accounts):
        con = sample_accounts
        # Owner deposit: debit checking, credit equity
        post_transaction(con, "2025-01-01", "Opening Balance", [
            ("checking", cents(50000)),
            ("equity", cents(-50000)),
        ])
        data = generate_cash_flow(con, "2025-01-01", "2025-12-31")
        assert len(data["financing"]) == 1
        assert data["financing"][0]["name"] == "Opening Balances"
        assert data["financing"][0]["amount"] == cents(50000)
        assert data["total_financing"] == cents(50000)

    def test_cash_to_cash_excluded(self, sample_accounts):
        con = sample_accounts
        # Transfer between two asset accounts: debit usbank, credit checking
        post_transaction(con, "2025-01-10", "Transfer", [
            ("usbank", cents(10000)),
            ("checking", cents(-10000)),
        ])
        data = generate_cash_flow(con, "2025-01-01", "2025-12-31")
        # Both sides are asset -> no non-cash splits -> no activity
        assert data["operating"] == []
        assert data["investing"] == []
        assert data["financing"] == []
        assert data["net_change"] == 0

    def test_net_change_equals_sum_of_categories(self, sample_accounts):
        con = sample_accounts
        # Add a fixed_asset account for investing
        con.execute(
            "INSERT INTO accounts (id, account_number, name, type, parent_id) "
            "VALUES ('equipment', NULL, 'Equipment', 'fixed_asset', NULL)"
        )
        post_transaction(con, "2025-01-15", "Revenue", [
            ("checking", cents(20000)),
            ("hosting_rev", cents(-20000)),
        ])
        post_transaction(con, "2025-01-20", "Buy equipment", [
            ("equipment", cents(8000)),
            ("checking", cents(-8000)),
        ])
        post_transaction(con, "2025-01-25", "Owner deposit", [
            ("checking", cents(30000)),
            ("equity", cents(-30000)),
        ])
        data = generate_cash_flow(con, "2025-01-01", "2025-12-31")
        assert data["net_change"] == (
            data["total_operating"] + data["total_investing"] + data["total_financing"]
        )

    def test_beginning_and_ending_balance(self, sample_accounts):
        con = sample_accounts
        # Pre-period transaction
        post_transaction(con, "2024-12-15", "Prior deposit", [
            ("checking", cents(40000)),
            ("equity", cents(-40000)),
        ])
        # In-period transaction
        post_transaction(con, "2025-01-15", "Revenue", [
            ("checking", cents(10000)),
            ("hosting_rev", cents(-10000)),
        ])
        data = generate_cash_flow(con, "2025-01-01", "2025-12-31")
        assert data["beginning_balance"] == cents(40000)
        assert data["ending_balance"] == cents(50000)
        assert data["beginning_balance"] + data["net_change"] == data["ending_balance"]

    def test_date_filtering(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-01-15", "In range", [
            ("checking", cents(5000)),
            ("hosting_rev", cents(-5000)),
        ])
        post_transaction(con, "2025-06-15", "Out of range", [
            ("checking", cents(8000)),
            ("hosting_rev", cents(-8000)),
        ])
        data = generate_cash_flow(con, "2025-01-01", "2025-01-31")
        assert data["total_operating"] == cents(5000)
        # Ending balance includes only through Jan 31
        assert data["ending_balance"] == cents(5000)

    def test_multi_split_classified_correctly(self, sample_accounts):
        con = sample_accounts
        # Add a fixed_asset account for investing
        con.execute(
            "INSERT INTO accounts (id, account_number, name, type, parent_id) "
            "VALUES ('equipment', NULL, 'Equipment', 'fixed_asset', NULL)"
        )
        # 3-split transaction: cash pays for both an expense and equipment
        post_transaction(con, "2025-02-01", "Mixed purchase", [
            ("checking", cents(-15000)),
            ("datacenter", cents(10000)),
            ("equipment", cents(5000)),
        ])
        data = generate_cash_flow(con, "2025-01-01", "2025-12-31")
        # Expense portion is operating outflow
        assert len(data["operating"]) == 1
        assert data["operating"][0]["amount"] == cents(-10000)
        # Equipment portion is investing outflow
        assert len(data["investing"]) == 1
        assert data["investing"][0]["amount"] == cents(-5000)
        assert data["net_change"] == cents(-15000)


class TestGenerateExpensesByVendor:
    def test_empty_report(self, sample_vendors):
        con = sample_vendors
        data = generate_expenses_by_vendor(con, "2025-01-01", "2025-12-31")
        assert data["vendors"] == []
        assert data["grand_total"] == 0

    def test_single_vendor(self, sample_vendors):
        con = sample_vendors
        post_transaction(con, "2025-01-15", "DC Payment", [
            ("datacenter", cents(7000)),
            ("cap1", cents(-7000)),
        ], vendor_id="acme_inc")
        data = generate_expenses_by_vendor(con, "2025-01-01", "2025-12-31")
        assert len(data["vendors"]) == 1
        assert data["vendors"][0]["name"] == "Acme Inc"
        assert data["vendors"][0]["total"] == cents(7000)
        assert data["grand_total"] == cents(7000)

    def test_multiple_vendors_sorted_descending(self, sample_vendors):
        con = sample_vendors
        # Acme: 5000
        post_transaction(con, "2025-01-15", "Acme expense", [
            ("datacenter", cents(5000)),
            ("cap1", cents(-5000)),
        ], vendor_id="acme_inc")
        # Globex: 8000 (bigger, should be first)
        post_transaction(con, "2025-01-20", "Globex expense", [
            ("cloud", cents(8000)),
            ("checking", cents(-8000)),
        ], vendor_id="globex_corp")
        data = generate_expenses_by_vendor(con, "2025-01-01", "2025-12-31")
        assert len(data["vendors"]) == 2
        assert data["vendors"][0]["name"] == "Globex Corp"
        assert data["vendors"][0]["total"] == cents(8000)
        assert data["vendors"][1]["name"] == "Acme Inc"
        assert data["grand_total"] == cents(13000)

    def test_date_filtering(self, sample_vendors):
        con = sample_vendors
        post_transaction(con, "2025-01-15", "In range", [
            ("datacenter", cents(3000)),
            ("cap1", cents(-3000)),
        ], vendor_id="acme_inc")
        post_transaction(con, "2025-06-15", "Out of range", [
            ("cloud", cents(5000)),
            ("cap1", cents(-5000)),
        ], vendor_id="acme_inc")
        data = generate_expenses_by_vendor(con, "2025-01-01", "2025-01-31")
        assert len(data["vendors"]) == 1
        assert data["grand_total"] == cents(3000)

    def test_non_expense_splits_excluded(self, sample_vendors):
        con = sample_vendors
        # Transaction with vendor but only asset splits (not expense)
        post_transaction(con, "2025-01-15", "Transfer", [
            ("checking", cents(10000)),
            ("hosting_rev", cents(-10000)),
        ], vendor_id="acme_inc")
        data = generate_expenses_by_vendor(con, "2025-01-01", "2025-12-31")
        # Income splits should not appear in expense report
        assert data["vendors"] == []

    def test_no_vendor_transactions_excluded(self, sample_vendors):
        con = sample_vendors
        # Transaction without a vendor
        post_transaction(con, "2025-01-15", "No vendor", [
            ("datacenter", cents(4000)),
            ("cap1", cents(-4000)),
        ])
        data = generate_expenses_by_vendor(con, "2025-01-01", "2025-12-31")
        assert data["vendors"] == []
        assert data["grand_total"] == 0


class TestGenerateReconciliationReport:
    def test_returns_none_for_invalid_id(self, sample_accounts):
        con = sample_accounts
        assert generate_reconciliation_report(con, "nonexistent") is None

    def test_basic_report(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-01-15", "Deposit", [
            ("checking", cents(500)),
            ("hosting_rev", cents(-500)),
        ])
        post_transaction(con, "2025-01-20", "Payment", [
            ("datacenter", cents(200)),
            ("checking", cents(-200)),
        ])
        splits = con.execute(
            "SELECT id FROM splits WHERE account_id = 'checking'"
        ).fetchall()
        split_ids = [s[0] for s in splits]

        rec_id = finish_reconciliation(
            con, "checking", split_ids,
            "2025-01-31", cents(300), 0,
        )

        data = generate_reconciliation_report(con, rec_id)
        assert data is not None
        assert data["account_name"] == "Main Checking"
        assert data["statement_date"] == "2025-01-31"
        assert data["statement_balance"] == cents(300)
        assert data["beginning_balance"] == 0
        assert data["split_count"] == 2

    def test_cleared_debits_and_credits(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-01-15", "Deposit", [
            ("checking", cents(500)),
            ("hosting_rev", cents(-500)),
        ])
        post_transaction(con, "2025-01-20", "Payment", [
            ("datacenter", cents(200)),
            ("checking", cents(-200)),
        ])
        splits = con.execute(
            "SELECT id FROM splits WHERE account_id = 'checking'"
        ).fetchall()
        split_ids = [s[0] for s in splits]

        rec_id = finish_reconciliation(
            con, "checking", split_ids,
            "2025-01-31", cents(300), 0,
        )

        data = generate_reconciliation_report(con, rec_id)
        # Deposit is positive (debit to checking)
        assert len(data["cleared_debits"]) == 1
        assert data["cleared_debits"][0]["amount"] == cents(500)
        # Payment is negative (credit from checking)
        assert len(data["cleared_credits"]) == 1
        assert data["cleared_credits"][0]["amount"] == cents(-200)
        assert data["debit_total"] == cents(500)
        assert data["credit_total"] == cents(-200)
        assert data["cleared_total"] == cents(300)

    def test_uncleared_items(self, sample_accounts):
        con = sample_accounts
        # Reconciled transaction
        post_transaction(con, "2025-01-15", "Deposit", [
            ("checking", cents(500)),
            ("hosting_rev", cents(-500)),
        ])
        # Unreconciled transaction within statement period
        post_transaction(con, "2025-01-20", "Pending", [
            ("checking", cents(100)),
            ("hosting_rev", cents(-100)),
        ])

        split = con.execute(
            "SELECT id FROM splits WHERE account_id = 'checking' "
            "ORDER BY rowid LIMIT 1"
        ).fetchone()

        rec_id = finish_reconciliation(
            con, "checking", [split[0]],
            "2025-01-31", cents(500), 0,
        )

        data = generate_reconciliation_report(con, rec_id)
        assert len(data["uncleared_items"]) == 1
        assert data["uncleared_items"][0]["description"] == "Pending"
        assert data["uncleared_total"] == cents(100)

    def test_register_balance(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-01-15", "Deposit", [
            ("checking", cents(500)),
            ("hosting_rev", cents(-500)),
        ])
        split = con.execute(
            "SELECT id FROM splits WHERE account_id = 'checking'"
        ).fetchone()

        rec_id = finish_reconciliation(
            con, "checking", [split[0]],
            "2025-01-31", cents(500), 0,
        )

        data = generate_reconciliation_report(con, rec_id)
        assert data["register_balance"] == cents(500)

    def test_negate_for_liability(self, sample_accounts):
        con = sample_accounts
        post_transaction(con, "2025-01-15", "CC Purchase", [
            ("datacenter", cents(200)),
            ("cap1", cents(-200)),
        ])
        split = con.execute(
            "SELECT id FROM splits WHERE account_id = 'cap1'"
        ).fetchone()

        rec_id = finish_reconciliation(
            con, "cap1", [split[0]],
            "2025-01-31", cents(-200), 0,
        )

        data = generate_reconciliation_report(con, rec_id)
        assert data["negate"] is True
