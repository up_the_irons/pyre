import os
from collections import defaultdict
from datetime import date as dt_date
from pathlib import Path

from weasyprint import HTML

from pyre.account_utils import DEBIT_TYPES
from pyre.company import COMPANY_NAME
from pyre.formatting import fmt, format_date


def resolve_report_path(prefs, report_type, date_str, **kwargs):
    """Resolve the output path for a report based on preferences.

    Returns a Path if report_output is configured, otherwise None (caller
    falls back to legacy behavior).

    prefs: the app preferences dict
    report_type: key in filenames dict (e.g. "reconciliation", "pnl")
    date_str: ISO date string used for strftime expansion of base_path
    **kwargs: format variables for the filename template
    """
    report_output = prefs.get("report_output")
    if not report_output:
        return None

    base_path = report_output.get("base_path")
    filenames = report_output.get("filenames", {})
    filename_template = filenames.get(report_type)
    if not base_path or not filename_template:
        return None

    d = dt_date.fromisoformat(date_str)

    expanded_base = d.strftime(base_path)
    expanded_base = os.path.expanduser(expanded_base)

    expanded_filename = d.strftime(filename_template).format(**kwargs)

    full_path = Path(expanded_base) / expanded_filename
    os.makedirs(full_path.parent, exist_ok=True)
    return full_path


def _fmt_color(amount_cents):
    """Format cents as dollar string, wrapping negatives in a span for color."""
    text = fmt(amount_cents)
    if amount_cents < 0:
        return f'<span class="negative">{text}</span>'
    return text


def _build_account_tree(rows):
    """Build a hierarchical account tree from query rows.

    Each row is (id, name, type, parent_id, balance).
    Returns (accounts_dict, roots_list) with subtotals calculated.
    Subtotals include the account's own balance plus all descendants,
    so direct-to-parent splits are never silently dropped.
    """
    accounts = {}
    for (acct_id, name, acct_type, parent_id, balance) in rows:
        accounts[acct_id] = {
            'id': acct_id,
            'name': name,
            'type': acct_type,
            'parent_id': parent_id,
            'balance': balance,
            'children': [],
        }

    roots = []
    for acct_id, acct in accounts.items():
        if acct['parent_id'] and acct['parent_id'] in accounts:
            accounts[acct['parent_id']]['children'].append(acct)
        else:
            roots.append(acct)

    def calc_subtotal(acct):
        child_total = sum(calc_subtotal(c) for c in acct['children'])
        acct['subtotal'] = acct['balance'] + child_total
        return acct['subtotal']

    for root in roots:
        calc_subtotal(root)

    return accounts, roots


def generate_pnl(con, start_date, end_date):
    """
    Generate Profit & Loss report data for date range.
    Returns a hierarchical tree of account balances.
    """
    # Get all income and expense account balances for the period
    rows = con.execute("""
        SELECT a.id, a.name, a.type, a.parent_id,
               COALESCE(SUM(CASE WHEN t.id IS NOT NULL THEN s.amount ELSE 0 END), 0) as balance
        FROM accounts a
        LEFT JOIN splits s ON s.account_id = a.id
        LEFT JOIN transactions t ON t.id = s.tx_id
            AND t.date >= ? AND t.date <= ?
        WHERE a.type IN ('income', 'other_income', 'expense', 'cost_of_goods_sold', 'other_expense')
        GROUP BY a.id
        ORDER BY a.type DESC, a.id
    """, (start_date, end_date)).fetchall()

    _accounts, roots = _build_account_tree(rows)

    # Calculate key totals
    income_total = sum(acct['subtotal'] for acct in roots if acct['type'] in ('income', 'other_income'))
    expense_total = sum(acct['subtotal'] for acct in roots if acct['type'] in ('expense', 'cost_of_goods_sold', 'other_expense'))

    # Income is stored as negative (credits), expenses as positive (debits)
    # For P&L display: show income as positive, expenses as positive
    net_income = -income_total - expense_total

    return {
        'roots': roots,
        'income_total': -income_total,  # flip sign for display
        'expense_total': expense_total,
        'net_income': net_income,
        'start_date': start_date,
        'end_date': end_date,
    }


def export_pnl_pdf(con, start_date, end_date, output_path, color=True):
    """Generate a PDF Profit & Loss report."""
    data = generate_pnl(con, start_date, end_date)
    _fmt = _fmt_color if color else fmt

    # Index root accounts by type for virtual hierarchy
    by_type = defaultdict(list)
    for acct in data['roots']:
        by_type[acct['type']].append(acct)

    def add_account(acct, indent=0, negate=False):
        lines = []
        indent_class = f"indent-{indent}" if indent > 0 else ""
        bal = acct.get('subtotal', acct['balance'])
        if negate:
            bal = -bal
        if bal != 0:
            if acct['children']:
                lines.append(f'<tr><td class="{indent_class}">{acct["name"]}</td><td class="amount"></td></tr>')
                for child in acct['children']:
                    lines.extend(add_account(child, indent + 1, negate=negate))
                lines.append(f'<tr class="subtotal"><td class="{indent_class}"><strong>Total {acct["name"]}</strong></td><td class="amount"><strong>{_fmt(bal)}</strong></td></tr>')
            else:
                lines.append(f'<tr><td class="{indent_class}">{acct["name"]}</td><td class="amount">{_fmt(bal)}</td></tr>')
        return lines

    def type_total(type_keys, negate=False):
        total = 0
        for k in type_keys:
            for acct in by_type.get(k, []):
                bal = acct.get('subtotal', acct['balance'])
                total += (-bal if negate else bal)
        return total

    # Compute section totals
    income_total = type_total(['income'], negate=True)
    cogs_total = type_total(['cost_of_goods_sold'])
    gross_profit = income_total - cogs_total
    expense_total = type_total(['expense'])
    net_operating_income = gross_profit - expense_total
    other_income_total = type_total(['other_income'], negate=True)
    other_expense_total = type_total(['other_expense'])
    net_other_income = other_income_total - other_expense_total
    net_income = net_operating_income + net_other_income

    body = ''

    # --- INCOME ---
    body += '<tr><td class="section-header">INCOME</td><td class="amount"></td></tr>'
    for acct in by_type.get('income', []):
        body += '\n'.join(add_account(acct, indent=1, negate=True))
    body += f'<tr class="subtotal"><td><strong>Total Income</strong></td><td class="amount"><strong>{_fmt(income_total)}</strong></td></tr>'

    # --- COST OF GOODS SOLD ---
    if by_type.get('cost_of_goods_sold'):
        body += '<tr><td class="section-header">COST OF GOODS SOLD</td><td class="amount"></td></tr>'
        for acct in by_type['cost_of_goods_sold']:
            body += '\n'.join(add_account(acct, indent=1))
        body += f'<tr class="subtotal"><td><strong>Total Cost of Goods Sold</strong></td><td class="amount"><strong>{_fmt(cogs_total)}</strong></td></tr>'

    body += f'<tr class="grand-total"><td>GROSS PROFIT</td><td class="amount">{_fmt(gross_profit)}</td></tr>'

    # --- EXPENSES ---
    body += '<tr><td class="section-header">EXPENSES</td><td class="amount"></td></tr>'
    for acct in by_type.get('expense', []):
        body += '\n'.join(add_account(acct, indent=1))
    body += f'<tr class="subtotal"><td><strong>Total Expenses</strong></td><td class="amount"><strong>{_fmt(expense_total)}</strong></td></tr>'

    body += f'<tr class="grand-total"><td>NET OPERATING INCOME</td><td class="amount">{_fmt(net_operating_income)}</td></tr>'

    # --- OTHER INCOME ---
    if by_type.get('other_income'):
        body += '<tr><td class="section-header">OTHER INCOME</td><td class="amount"></td></tr>'
        for acct in by_type['other_income']:
            body += '\n'.join(add_account(acct, indent=1, negate=True))
        body += f'<tr class="subtotal"><td><strong>Total Other Income</strong></td><td class="amount"><strong>{_fmt(other_income_total)}</strong></td></tr>'

    # --- OTHER EXPENSES ---
    if by_type.get('other_expense'):
        body += '<tr><td class="section-header">OTHER EXPENSES</td><td class="amount"></td></tr>'
        for acct in by_type['other_expense']:
            body += '\n'.join(add_account(acct, indent=1))
        body += f'<tr class="subtotal"><td><strong>Total Other Expenses</strong></td><td class="amount"><strong>{_fmt(other_expense_total)}</strong></td></tr>'

    if by_type.get('other_income') or by_type.get('other_expense'):
        body += f'<tr class="grand-total"><td>NET OTHER INCOME</td><td class="amount">{_fmt(net_other_income)}</td></tr>'

    body += f'<tr class="grand-total"><td>NET INCOME</td><td class="amount">{_fmt(net_income)}</td></tr>'

    period = f"{_format_long_date(start_date)} through {_format_long_date(end_date)}"
    html_content = _pdf_html("Profit and Loss", period, body, color=color)
    HTML(string=html_content).write_pdf(output_path)
    return output_path


def generate_balance_sheet(con, as_of_date):
    """
    Generate Balance Sheet data as of a given date.
    Returns hierarchical trees for Assets, Liabilities, and Equity.
    """
    # Get all asset, liability, and equity account balances up to as_of_date
    rows = con.execute("""
        SELECT a.id, a.name, a.type, a.parent_id,
               COALESCE(SUM(CASE WHEN t.id IS NOT NULL THEN s.amount ELSE 0 END), 0) as balance
        FROM accounts a
        LEFT JOIN splits s ON s.account_id = a.id
        LEFT JOIN transactions t ON t.id = s.tx_id
            AND t.date <= ?
        WHERE a.type IN (
            'asset', 'accounts_receivable', 'other_current_asset',
            'fixed_asset', 'other_asset',
            'liability', 'accounts_payable', 'credit_card',
            'other_current_liability', 'long_term_liability',
            'equity'
        )
        GROUP BY a.id
        ORDER BY a.type, a.id
    """, (as_of_date,)).fetchall()

    _accounts, roots = _build_account_tree(rows)

    from pyre.db import ASSET_TYPES, LIABILITY_TYPES

    # Assets are stored as positive (debits)
    total_assets = sum(acct['subtotal'] for acct in roots if acct['type'] in ASSET_TYPES)
    # Liabilities are stored as negative (credits) — flip for display
    total_liabilities = -sum(acct['subtotal'] for acct in roots if acct['type'] in LIABILITY_TYPES)
    # Equity is stored as negative (credits) — flip for display
    total_equity = -sum(acct['subtotal'] for acct in roots if acct['type'] == 'equity')

    # Net income (retained earnings not yet closed) = -(income) - expenses
    # Pull income/expense totals up to as_of_date
    net_income_row = con.execute("""
        SELECT COALESCE(SUM(
            CASE WHEN a.type IN ('income', 'other_income') THEN -s.amount
                 WHEN a.type IN ('expense', 'cost_of_goods_sold', 'other_expense') THEN -s.amount
                 ELSE 0 END
        ), 0)
        FROM splits s
        JOIN accounts a ON a.id = s.account_id
        JOIN transactions t ON t.id = s.tx_id
        WHERE t.date <= ?
    """, (as_of_date,)).fetchone()
    net_income = net_income_row[0]

    return {
        'roots': roots,
        'total_assets': total_assets,
        'total_liabilities': total_liabilities,
        'total_equity': total_equity,
        'net_income': net_income,
        'total_liabilities_and_equity': total_liabilities + total_equity + net_income,
        'as_of_date': as_of_date,
    }


def generate_trial_balance(con, as_of_date):
    """
    Generate Trial Balance data as of a given date.
    Lists every account with a non-zero balance, classified into debit/credit columns.
    Total debits must equal total credits.
    """
    rows = con.execute("""
        SELECT a.id, a.name, a.type,
               COALESCE(SUM(s.amount), 0) as balance
        FROM accounts a
        JOIN splits s ON s.account_id = a.id
        JOIN transactions t ON t.id = s.tx_id
        WHERE t.date <= ?
        GROUP BY a.id
        HAVING balance != 0
        ORDER BY a.name
    """, (as_of_date,)).fetchall()

    accounts = []
    total_debit = 0
    total_credit = 0

    for acct_id, name, acct_type, balance in rows:
        if acct_type in DEBIT_TYPES:
            # Natural debit accounts: positive balance = debit
            debit = balance
            credit = 0
        else:
            # Natural credit accounts (liability, equity, income):
            # stored as negative, negate for credit column
            debit = 0
            credit = -balance

        accounts.append({
            'id': acct_id,
            'name': name,
            'type': acct_type,
            'debit': debit,
            'credit': credit,
        })
        total_debit += debit
        total_credit += credit

    return {
        'accounts': accounts,
        'total_debit': total_debit,
        'total_credit': total_credit,
        'as_of_date': as_of_date,
    }


def export_balance_sheet_pdf(con, as_of_date, output_path, color=True):
    """Generate a PDF Balance Sheet report."""
    data = generate_balance_sheet(con, as_of_date)
    _fmt = _fmt_color if color else fmt

    # Index root accounts by type for the virtual hierarchy
    by_type = defaultdict(list)
    for acct in data['roots']:
        by_type[acct['type']].append(acct)

    def add_account(acct, indent=0, negate=False):
        """Render one account row (and its children if any). Skips $0 accounts."""
        lines = []
        indent_class = f"indent-{indent}" if indent > 0 else ""
        bal = acct.get('subtotal', acct['balance'])
        if negate:
            bal = -bal
        if bal != 0:
            if acct['children']:
                lines.append(f'<tr><td class="{indent_class}">{acct["name"]}</td><td class="amount"></td></tr>')
                for child in acct['children']:
                    lines.extend(add_account(child, indent + 1, negate=negate))
                lines.append(f'<tr class="subtotal"><td class="{indent_class}"><strong>Total {acct["name"]}</strong></td><td class="amount"><strong>{_fmt(bal)}</strong></td></tr>')
            else:
                lines.append(f'<tr><td class="{indent_class}">{acct["name"]}</td><td class="amount">{_fmt(bal)}</td></tr>')
        return lines

    def type_total(type_keys, negate=False):
        total = 0
        for k in type_keys:
            for acct in by_type.get(k, []):
                bal = acct.get('subtotal', acct['balance'])
                total += (-bal if negate else bal)
        return total

    def add_type_group(label, type_keys, indent=2, negate=False):
        """Render a QB-style virtual group (e.g. 'Bank Accounts').
        Always shows the group header. Shows accounts and a Total line only
        when the group has non-zero balances."""
        accounts = []
        for k in type_keys:
            accounts.extend(by_type.get(k, []))
        indent_class = f"indent-{indent}"
        lines = [f'<tr><td class="{indent_class}">{label}</td><td class="amount"></td></tr>']
        account_rows = []
        for acct in accounts:
            account_rows.extend(add_account(acct, indent + 1, negate=negate))
        if account_rows:
            lines.extend(account_rows)
            total = type_total(type_keys, negate=negate)
            lines.append(f'<tr class="subtotal"><td class="{indent_class}"><strong>Total {label}</strong></td><td class="amount"><strong>{_fmt(total)}</strong></td></tr>')
        return lines

    # --- ASSETS ---
    body = '<tr><td class="section-header">ASSETS</td><td class="amount"></td></tr>'

    body += '<tr><td class="indent-1">Current Assets</td><td class="amount"></td></tr>'
    body += '\n'.join(add_type_group('Bank Accounts', ['asset'], indent=2))
    body += '\n'.join(add_type_group('Accounts Receivable', ['accounts_receivable'], indent=2))
    body += '\n'.join(add_type_group('Other Current Assets', ['other_current_asset'], indent=2))
    ca_total = type_total(['asset', 'accounts_receivable', 'other_current_asset'])
    body += f'<tr class="subtotal"><td class="indent-1"><strong>Total Current Assets</strong></td><td class="amount"><strong>{_fmt(ca_total)}</strong></td></tr>'

    body += '\n'.join(add_type_group('Fixed Assets', ['fixed_asset'], indent=1))
    body += '\n'.join(add_type_group('Other Assets', ['other_asset'], indent=1))

    body += f'<tr class="grand-total"><td>TOTAL ASSETS</td><td class="amount">{_fmt(data["total_assets"])}</td></tr>'

    # --- LIABILITIES ---
    body += '<tr><td class="section-header">LIABILITIES</td><td class="amount"></td></tr>'

    body += '<tr><td class="indent-1">Current Liabilities</td><td class="amount"></td></tr>'
    body += '\n'.join(add_type_group('Accounts Payable', ['accounts_payable'], indent=2, negate=True))
    body += '\n'.join(add_type_group('Credit Cards', ['credit_card'], indent=2, negate=True))
    body += '\n'.join(add_type_group('Other Current Liabilities', ['other_current_liability'], indent=2, negate=True))
    cl_total = type_total(['accounts_payable', 'credit_card', 'other_current_liability'], negate=True)
    body += f'<tr class="subtotal"><td class="indent-1"><strong>Total Current Liabilities</strong></td><td class="amount"><strong>{_fmt(cl_total)}</strong></td></tr>'

    body += '\n'.join(add_type_group('Long-term Liabilities', ['long_term_liability', 'liability'], indent=1, negate=True))

    body += f'<tr class="grand-total"><td>TOTAL LIABILITIES</td><td class="amount">{_fmt(data["total_liabilities"])}</td></tr>'

    # --- EQUITY ---
    body += '<tr><td class="section-header">EQUITY</td><td class="amount"></td></tr>'
    for acct in by_type.get('equity', []):
        body += '\n'.join(add_account(acct, indent=1, negate=True))

    if data['net_income'] != 0:
        body += f'<tr><td class="indent-1">Net Income</td><td class="amount">{_fmt(data["net_income"])}</td></tr>'

    body += f'<tr class="grand-total"><td>TOTAL EQUITY</td><td class="amount">{_fmt(data["total_equity"] + data["net_income"])}</td></tr>'
    body += f'<tr class="grand-total"><td>TOTAL LIABILITIES AND EQUITY</td><td class="amount">{_fmt(data["total_liabilities_and_equity"])}</td></tr>'

    date_line = f"As of {_format_long_date(as_of_date)}"
    html_content = _pdf_html("Balance Sheet", date_line, body, color=color)
    HTML(string=html_content).write_pdf(output_path)
    return output_path


OPERATING_TYPES = frozenset([
    'income', 'other_income', 'expense', 'cost_of_goods_sold', 'other_expense',
    'accounts_receivable', 'other_current_asset', 'accounts_payable',
    'credit_card', 'other_current_liability', 'liability',
])
INVESTING_TYPES = frozenset(['fixed_asset', 'other_asset'])
FINANCING_TYPES = frozenset(['equity', 'long_term_liability'])


def generate_cash_flow(con, start_date, end_date):
    """
    Generate Cash Flow Statement using the direct method.

    Finds all transactions touching cash accounts (type='asset') in the date
    range, then classifies the non-cash counterpart splits into Operating,
    Investing, and Financing activities. Amounts are negated so that positive
    means cash inflow and negative means cash outflow.
    """
    # Get non-cash splits from transactions that touch at least one cash account
    rows = con.execute("""
        SELECT a.id, a.name, a.type, -s.amount as cf_amount
        FROM splits s
        JOIN accounts a ON a.id = s.account_id
        JOIN transactions t ON t.id = s.tx_id
        WHERE t.date >= ? AND t.date <= ?
          AND a.type != 'asset'
          AND t.id IN (
              SELECT DISTINCT s2.tx_id
              FROM splits s2
              JOIN accounts a2 ON a2.id = s2.account_id
              WHERE a2.type = 'asset'
          )
    """, (start_date, end_date)).fetchall()

    # Aggregate by category and account
    operating = defaultdict(int)
    investing = defaultdict(int)
    financing = defaultdict(int)
    op_ids = {}
    inv_ids = {}
    fin_ids = {}

    for acct_id, name, acct_type, cf_amount in rows:
        if acct_type in OPERATING_TYPES:
            operating[name] += cf_amount
            op_ids[name] = acct_id
        elif acct_type in INVESTING_TYPES:
            investing[name] += cf_amount
            inv_ids[name] = acct_id
        elif acct_type in FINANCING_TYPES:
            financing[name] += cf_amount
            fin_ids[name] = acct_id

    def to_list(amounts, ids):
        return sorted(
            [{"id": ids[n], "name": n, "amount": a} for n, a in amounts.items()],
            key=lambda x: x["name"],
        )

    op_list = to_list(operating, op_ids)
    inv_list = to_list(investing, inv_ids)
    fin_list = to_list(financing, fin_ids)

    total_operating = sum(item["amount"] for item in op_list)
    total_investing = sum(item["amount"] for item in inv_list)
    total_financing = sum(item["amount"] for item in fin_list)
    net_change = total_operating + total_investing + total_financing

    # Beginning cash balance: all asset-type account balances before start_date
    beginning_row = con.execute("""
        SELECT COALESCE(SUM(s.amount), 0)
        FROM splits s
        JOIN accounts a ON a.id = s.account_id
        JOIN transactions t ON t.id = s.tx_id
        WHERE a.type = 'asset' AND t.date < ?
    """, (start_date,)).fetchone()
    beginning_balance = beginning_row[0]

    # Ending cash balance: all asset-type account balances through end_date
    ending_row = con.execute("""
        SELECT COALESCE(SUM(s.amount), 0)
        FROM splits s
        JOIN accounts a ON a.id = s.account_id
        JOIN transactions t ON t.id = s.tx_id
        WHERE a.type = 'asset' AND t.date <= ?
    """, (end_date,)).fetchone()
    ending_balance = ending_row[0]

    return {
        "operating": op_list,
        "investing": inv_list,
        "financing": fin_list,
        "total_operating": total_operating,
        "total_investing": total_investing,
        "total_financing": total_financing,
        "net_change": net_change,
        "beginning_balance": beginning_balance,
        "ending_balance": ending_balance,
        "start_date": start_date,
        "end_date": end_date,
    }


def _format_long_date(iso_date):
    """Format ISO date as 'January 1, 2025' style for PDF reports."""
    from datetime import date as dt_date
    d = dt_date.fromisoformat(iso_date)
    return d.strftime("%B ") + str(d.day) + d.strftime(", %Y")


def _pdf_html(report_title, date_line, table_body, color=True):
    """Wrap report table body in a complete HTML document with standard header."""
    color_css = ""
    if color:
        color_css = """
        .section-header {
            color: #1a3a5c;
        }
        .grand-total {
            background-color: #f5f5f5;
        }
        .negative {
            color: #8b0000;
        }"""
    return f"""\
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{report_title}</title>
    <style>
        @page {{
            size: letter;
            margin: 0.75in;
        }}
        body {{
            font-family: Arial, sans-serif;
            font-size: 10pt;
            color: #000;
        }}
        .header {{
            text-align: center;
            margin-bottom: 15px;
        }}
        .company-name {{
            font-size: 18pt;
            font-weight: bold;
            margin: 0 0 8px 0;
        }}
        .report-title {{
            font-size: 12pt;
            font-weight: bold;
            margin: 0 0 6px 0;
        }}
        .report-period {{
            font-size: 10pt;
            margin: 0;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        td {{
            padding: 2px 0;
        }}
        .amount {{
            text-align: right;
            width: 120px;
        }}
        .section-header {{
            font-weight: bold;
            padding-top: 18px;
        }}
        .indent-1 {{ padding-left: 20px; }}
        .indent-2 {{ padding-left: 40px; }}
        .indent-3 {{ padding-left: 60px; }}
        .subtotal {{
            font-weight: bold;
            border-top: 1px solid #000;
            padding-top: 3px;
        }}
        .total {{
            font-weight: bold;
            border-top: 1px solid #000;
            padding-top: 5px;
        }}
        .grand-total {{
            font-weight: bold;
            border-top: 3px double #000;
            padding-top: 5px;
        }}
{color_css}
    </style>
</head>
<body>
    <div class="header">
        <p class="company-name">{COMPANY_NAME}</p>
        <p class="report-title">{report_title}</p>
        <p class="report-period">{date_line}</p>
    </div>
    <table>
{table_body}
    </table>
</body>
</html>"""


def generate_expenses_by_vendor(con, start_date, end_date):
    """
    Generate Expenses by Vendor Summary for date range.
    Returns vendor totals sorted by total descending (biggest spenders first).
    """
    rows = con.execute("""
        SELECT v.id, v.name, SUM(s.amount) as total
        FROM vendors v
        JOIN transactions t ON t.vendor_id = v.id
        JOIN splits s ON s.tx_id = t.id
        JOIN accounts a ON a.id = s.account_id
        WHERE a.type IN ('expense', 'cost_of_goods_sold', 'other_expense')
          AND t.date >= ? AND t.date <= ?
        GROUP BY v.id
        HAVING total != 0
        ORDER BY total DESC
    """, (start_date, end_date)).fetchall()
    vendors = [{"id": r[0], "name": r[1], "total": r[2]} for r in rows]
    grand_total = sum(v["total"] for v in vendors)
    return {
        "vendors": vendors,
        "grand_total": grand_total,
        "start_date": start_date,
        "end_date": end_date,
    }


def export_expenses_by_vendor_pdf(con, start_date, end_date, output_path, color=True):
    """Generate a PDF Expenses by Vendor Summary report."""
    data = generate_expenses_by_vendor(con, start_date, end_date)
    _fmt = _fmt_color if color else fmt

    body = '<tr><td class="section-header">VENDOR</td><td class="amount section-header">TOTAL</td></tr>'
    for vendor in data["vendors"]:
        body += f'<tr><td class="indent-1">{vendor["name"]}</td><td class="amount">{_fmt(vendor["total"])}</td></tr>'

    body += f'<tr class="grand-total"><td>TOTAL</td><td class="amount">{_fmt(data["grand_total"])}</td></tr>'

    period = f"{_format_long_date(start_date)} through {_format_long_date(end_date)}"
    html_content = _pdf_html("Expenses by Vendor Summary", period, body, color=color)
    HTML(string=html_content).write_pdf(output_path)
    return output_path


def generate_reconciliation_report(con, reconciliation_id):
    """Generate reconciliation report data for a single reconciliation.

    Returns a dict with summary info, cleared debits/credits, and uncleared items.
    """
    from pyre.db import LIABILITY_TYPES

    # Get reconciliation record
    rec = con.execute(
        "SELECT r.id, r.account_id, a.name, a.type, r.statement_date, "
        "r.statement_balance, r.beginning_balance, r.reconciled_at, r.split_count "
        "FROM reconciliations r "
        "JOIN accounts a ON a.id = r.account_id "
        "WHERE r.id = ?",
        (reconciliation_id,),
    ).fetchone()
    if not rec:
        return None

    rec_id, account_id, account_name, account_type, statement_date, \
        statement_balance, beginning_balance, reconciled_at, split_count = rec

    # Sign: liability/credit accounts display with flipped sign
    negate = account_type in LIABILITY_TYPES

    # Get cleared splits linked to this reconciliation
    cleared = con.execute(
        "SELECT s.id, t.date, t.description, s.amount, "
        "COALESCE(v.name, '') as vendor_name "
        "FROM splits s "
        "JOIN transactions t ON t.id = s.tx_id "
        "LEFT JOIN vendors v ON v.id = t.vendor_id "
        "WHERE s.reconciliation_id = ? "
        "ORDER BY t.date, t.id",
        (reconciliation_id,),
    ).fetchall()

    # Split into debits (positive amounts) and credits (negative amounts)
    # For liability accounts, the meaning flips
    cleared_debits = []
    cleared_credits = []
    for split_id, dt, desc, amount, vendor_name in cleared:
        item = {
            "date": dt,
            "description": desc,
            "amount": amount,
            "vendor_name": vendor_name,
        }
        if amount >= 0:
            cleared_debits.append(item)
        else:
            cleared_credits.append(item)

    debit_total = sum(d["amount"] for d in cleared_debits)
    credit_total = sum(c["amount"] for c in cleared_credits)
    cleared_total = debit_total + credit_total

    # Uncleared items: splits on this account through statement_date that
    # were not reconciled in this or any prior reconciliation
    uncleared = con.execute(
        "SELECT t.date, t.description, s.amount, "
        "COALESCE(v.name, '') as vendor_name "
        "FROM splits s "
        "JOIN transactions t ON t.id = s.tx_id "
        "LEFT JOIN vendors v ON v.id = t.vendor_id "
        "WHERE s.account_id = ? AND t.date <= ? "
        "AND (s.reconciliation_id IS NULL "
        "     OR s.reconciliation_id IN ("
        "         SELECT id FROM reconciliations "
        "         WHERE account_id = ? AND reconciled_at > ("
        "             SELECT reconciled_at FROM reconciliations WHERE id = ?)"
        "     ))"
        "ORDER BY t.date, t.id",
        (account_id, statement_date, account_id, reconciliation_id),
    ).fetchall()

    uncleared_items = [
        {
            "date": r[0],
            "description": r[1],
            "amount": r[2],
            "vendor_name": r[3],
        }
        for r in uncleared
    ]
    uncleared_total = sum(u["amount"] for u in uncleared_items)

    # Register balance as of statement date
    from pyre.models import get_account_balance
    register_balance = get_account_balance(con, account_id, statement_date)

    return {
        "reconciliation_id": rec_id,
        "account_id": account_id,
        "account_name": account_name,
        "account_type": account_type,
        "negate": negate,
        "statement_date": statement_date,
        "statement_balance": statement_balance,
        "beginning_balance": beginning_balance,
        "reconciled_at": reconciled_at,
        "split_count": split_count,
        "cleared_debits": cleared_debits,
        "cleared_credits": cleared_credits,
        "debit_total": debit_total,
        "credit_total": credit_total,
        "cleared_total": cleared_total,
        "uncleared_items": uncleared_items,
        "uncleared_total": uncleared_total,
        "register_balance": register_balance,
    }


def export_reconciliation_report_pdf(con, reconciliation_id, output_path,
                                     color=True):
    """Generate a PDF Reconciliation Report."""
    data = generate_reconciliation_report(con, reconciliation_id)
    if not data:
        return None
    _fmt = _fmt_color if color else fmt

    negate = data["negate"]

    def _display(amount):
        return _fmt(-amount if negate else amount)

    # Summary section
    body = '<tr><td class="section-header">SUMMARY</td><td class="amount"></td></tr>'
    body += f'<tr><td class="indent-1">Account</td><td class="amount">{data["account_name"]}</td></tr>'
    body += f'<tr><td class="indent-1">Statement Date</td><td class="amount">{_format_long_date(data["statement_date"])}</td></tr>'
    body += f'<tr><td class="indent-1">Beginning Balance</td><td class="amount">{_display(data["beginning_balance"])}</td></tr>'
    body += f'<tr><td class="indent-1">Statement Ending Balance</td><td class="amount">{_display(data["statement_balance"])}</td></tr>'
    body += f'<tr><td class="indent-1">Items Cleared</td><td class="amount">{data["split_count"]}</td></tr>'

    # Section headings depend on account type
    if negate:
        # Credit card / liability: charges first, then payments
        sections = [
            ("CHARGES AND CASH ADVANCES CLEARED", "Total Charges and Cash Advances",
             data["cleared_credits"], data["credit_total"]),
            ("PAYMENTS AND CREDITS CLEARED", "Total Payments and Credits",
             data["cleared_debits"], data["debit_total"]),
        ]
    else:
        # Bank / asset: deposits first, then checks
        sections = [
            ("DEPOSITS AND OTHER CREDITS CLEARED", "Total Deposits and Credits",
             data["cleared_debits"], data["debit_total"]),
            ("CHECKS AND PAYMENTS CLEARED", "Total Checks and Payments",
             data["cleared_credits"], data["credit_total"]),
        ]

    for header, total_label, items, total in sections:
        body += f'<tr><td class="section-header">{header}</td><td class="amount"></td></tr>'
        for item in items:
            label = item["description"]
            if item["vendor_name"]:
                label += f' ({item["vendor_name"]})'
            body += f'<tr><td class="indent-1">{format_date(item["date"])}  {label}</td><td class="amount">{_display(item["amount"])}</td></tr>'
        body += f'<tr class="subtotal"><td><strong>{total_label}</strong></td><td class="amount"><strong>{_display(total)}</strong></td></tr>'

    # Uncleared items
    if data["uncleared_items"]:
        body += '<tr><td class="section-header">UNCLEARED TRANSACTIONS</td><td class="amount"></td></tr>'
        for item in data["uncleared_items"]:
            label = item["description"]
            if item["vendor_name"]:
                label += f' ({item["vendor_name"]})'
            body += f'<tr><td class="indent-1">{format_date(item["date"])}  {label}</td><td class="amount">{_display(item["amount"])}</td></tr>'
        body += f'<tr class="subtotal"><td><strong>Total Uncleared</strong></td><td class="amount"><strong>{_display(data["uncleared_total"])}</strong></td></tr>'

    # Register balance
    body += f'<tr class="grand-total"><td>REGISTER BALANCE</td><td class="amount">{_display(data["register_balance"])}</td></tr>'

    date_line = f"Statement Date: {_format_long_date(data['statement_date'])}"
    html_content = _pdf_html(
        f"Reconciliation Report - {data['account_name']}",
        date_line, body, color=color,
    )
    HTML(string=html_content).write_pdf(output_path)
    return output_path


def export_cash_flow_pdf(con, start_date, end_date, output_path, color=True):
    """Generate a PDF Cash Flow Statement."""
    data = generate_cash_flow(con, start_date, end_date)
    _fmt = _fmt_color if color else fmt

    def add_section(title, items, total, total_label):
        lines = [f'<tr><td class="section-header">{title}</td><td class="amount"></td></tr>']
        for item in items:
            lines.append(f'<tr><td class="indent-1">{item["name"]}</td><td class="amount">{_fmt(item["amount"])}</td></tr>')
        lines.append(f'<tr class="subtotal"><td><strong>{total_label}</strong></td><td class="amount"><strong>{_fmt(total)}</strong></td></tr>')
        return '\n'.join(lines)

    body = add_section(
        "OPERATING ACTIVITIES", data["operating"],
        data["total_operating"], "Total Operating Activities",
    )
    body += add_section(
        "INVESTING ACTIVITIES", data["investing"],
        data["total_investing"], "Total Investing Activities",
    )
    body += add_section(
        "FINANCING ACTIVITIES", data["financing"],
        data["total_financing"], "Total Financing Activities",
    )
    body += f'''
        <tr class="grand-total"><td>NET CHANGE IN CASH</td><td class="amount">{_fmt(data["net_change"])}</td></tr>
        <tr><td>Beginning Cash Balance</td><td class="amount">{_fmt(data["beginning_balance"])}</td></tr>
        <tr class="grand-total"><td>Ending Cash Balance</td><td class="amount">{_fmt(data["ending_balance"])}</td></tr>
    '''

    period = f"{_format_long_date(start_date)} through {_format_long_date(end_date)}"
    html_content = _pdf_html("Cash Flow Statement", period, body, color=color)
    HTML(string=html_content).write_pdf(output_path)
    return output_path
