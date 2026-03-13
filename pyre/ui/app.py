from rich.text import Text

from textual import on
from textual.app import App
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, Input, Label

from pyre.db import init_db
from pyre.formatting import fmt, format_date

# Color constants for ledger styling
DIM = "dim"
MUTED = "grey62"
TRANSFER_COLOR = "cyan"
POSITIVE_COLOR = "green"
NEGATIVE_COLOR = "red"
DETAIL_NAME = "dim"
DETAIL_POSITIVE = "green dim"
DETAIL_NEGATIVE = "red dim"
SPLITS_HINT = "dim"
IMPORTED_COLOR = "dark_cyan"
STATUS_MODES = ["compact", "columns", "color"]
from pyre.models import (
    delete_transaction,
    get_account_balance,
    get_account_transactions,
    get_recent_transactions,
    is_transaction_reconciled,
    search_transactions,
)
from pyre.account_models import account_path, get_all_accounts
from pyre.company import COMPANY_NAME
from pyre.db import DB_PATH
from pyre.preferences import load_preferences, save_preferences
from pyre.quick_functions import load_quick_functions
from pyre.ui.import_screen import ImportFileScreen, PayeeRulesScreen
from pyre.ui.reconcile_screen import ReconcileSetupScreen, ReconcileWorksheetScreen
from pyre.ui.scheduled_screen import PendingScheduledScreen, ScheduledListScreen
from pyre.ui.screens import (
    QuickEntryScreen,
    EditTransactionScreen,
    ConfirmDeleteTransactionScreen,
    ReportDateScreen,
    ProfitLossScreen,
    CashFlowScreen,
    BalanceSheetScreen,
    TrialBalanceScreen,
    ChartOfAccountsScreen,
    AddTransactionScreen,
    VendorListScreen,
    ExpensesByVendorScreen,
    BulkEditScreen,
    ReconciliationReportPickerScreen,
    ReconciliationReportScreen,
)
from pyre.ui.styles import APP_CSS


class PyreApp(App):
    """Pyre - the main application."""

    TITLE = "Pyre"
    SUB_TITLE = COMPANY_NAME if COMPANY_NAME else "Burn the boats 🔥"

    CSS = APP_CSS

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("slash", "search", "Search"),
        Binding("i", "import", "Import"),
        Binding("e", "reconcile", "Reconcile"),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("g", "cursor_top", "Top", show=False),
        Binding("G", "cursor_bottom", "Bottom", show=False),
        Binding("escape", "clear_search", "Clear", show=False),
        Binding("p", "show_pnl", "P&L Report"),
        Binding("b", "show_balance_sheet", "Bal Sheet"),
        Binding("c", "show_chart_of_accounts", "Accounts"),
        Binding("a", "add_transaction", "Add Txn"),
        Binding("d", "delete_transaction", "Delete"),
        Binding("T", "show_trial_balance", "Trial Bal"),
        Binding("C", "show_cash_flow", "Cash Flow"),
        Binding("v", "show_vendors", "Vendors"),
        Binding("V", "show_expenses_by_vendor", "By Vendor"),
        Binding("E", "show_reconciliation_reports", "Rec Report"),
        Binding("S", "show_scheduled", "Scheduled"),
        Binding("t", "toggle_status", "Status"),
        Binding("f", "favorites", "Favorites", show=False),
        Binding("R", "payee_rules", "Rules", show=False),
        Binding("F", "qf_mode", "QF Mode", show=False),
        Binding("B", "toggle_bulk", "Bulk", show=False),
        Binding("space", "toggle_splits", "Expand", show=False),
    ]

    def __init__(self, import_file=None, con=None, db_path=None):
        super().__init__()
        self.con = con if con is not None else init_db()
        self._db_path = db_path or DB_PATH
        self._preferences = load_preferences(self._db_path)
        self.theme = self._preferences.get("theme", "textual-dark")
        self._quick_functions = load_quick_functions(self._db_path)
        self.search_active = False
        self.search_query = ""
        self.account_filter = None  # dict with 'id' and 'name' when filtering
        self._row_splits = {}  # tx_id -> list of (name, amount, reconcile, account_id)
        self._row_imported = {}  # tx_id -> bool
        self._status_mode = "compact"
        self._ledger_data = []  # [(dt, desc, split_info, tx_id, imported, vendor_name), ...]
        self._ledger_balances = None  # list of balances or None
        self._account_types = {}  # account_id -> type
        self._is_account_view = False
        self._filter_id = None
        self._expanded_tx_id = None
        self._last_cursor_row = 0  # track direction for skipping detail rows
        self._row_index_to_key = []  # maps table row index -> row key string
        self._import_file = import_file  # auto-launch import on startup
        self._favorites_mode = False
        self._qf_mode = False
        self._sidebar_accounts = []  # [(id, name, type), ...]
        self._bulk_mode = False
        self._selected_tx_ids = set()

    def compose(self):
        yield Header()
        with Horizontal(id="main-container"):
            with Vertical(id="left-panel"):
                yield Label("⚡ Quick Functions", id="left-panel-title")
                if self._quick_functions:
                    current_group = None
                    for qf in self._quick_functions:
                        if qf.get("group") != current_group:
                            current_group = qf["group"]
                            yield Label(current_group, classes="qf-group")
                        with Horizontal(classes="qf-item"):
                            key_classes = "qf-key qf-key-active" if qf["key"] in "0123456789" else "qf-key"
                            yield Label(f"\\[{qf['key']}]", classes=key_classes)
                            yield Label(qf["label"], classes="qf-label")
                else:
                    yield Label("No quick functions defined", classes="qf-empty")

                yield Label("")
                yield Label("Account Balances", id="balances-title")
                yield Vertical(id="balances-box")

            with Vertical(id="right-panel"):
                yield Label("Recent Transactions", id="ledger-title")
                yield Label(
                    "BULK SELECT  --  space to select, Enter to edit, B to exit",
                    id="bulk-indicator",
                )
                yield DataTable(id="ledger-table")

        yield Footer()
        with Horizontal(id="search-bar"):
            yield Label("/", id="search-prompt")
            yield Input(placeholder="Search transactions...", id="search-input")
            yield Label("", id="search-count")

    def on_mount(self):
        self.refresh_balances()
        self.refresh_ledger()
        self._check_pending_scheduled()
        if self._import_file:
            self._launch_import(self._import_file)
            self._import_file = None

    def watch_theme(self, theme: str) -> None:
        self._preferences["theme"] = theme
        save_preferences(self._db_path, self._preferences)

    def refresh_balances(self):
        """Update the balances panel."""
        box = self.query_one("#balances-box")
        box.remove_children()

        from pyre.db import LIABILITY_TYPES

        sidebar_accounts = self.con.execute(
            "SELECT id, name, type FROM accounts WHERE sidebar = 1 ORDER BY name"
        ).fetchall()
        self._sidebar_accounts = sidebar_accounts
        for idx, (acct_id, label, acct_type) in enumerate(sidebar_accounts, 1):
            bal = get_account_balance(self.con, acct_id)
            display_bal = -bal if acct_type in LIABILITY_TYPES else bal
            css_class = "balance-amount-neg" if display_bal < 0 else "balance-amount"

            key_label = f"\\[f{idx}]" if idx <= 9 else ""
            row = Horizontal(classes="balance-row")
            box.mount(row)
            row.mount(Label(key_label, classes="fav-key"))
            row.mount(Label(label, classes="balance-label"))
            row.mount(Label(fmt(display_bal), classes=css_class))

    BALANCE_SHEET_TYPES = frozenset([
        "asset", "accounts_receivable", "other_current_asset",
        "fixed_asset", "other_asset",
        "liability", "accounts_payable", "credit_card",
        "other_current_liability", "long_term_liability",
        "equity",
    ])

    def _parse_splits(self, split_info):
        """Parse split_info string into list of (name, amount, reconcile, account_id) tuples."""
        parts = split_info.split("|")
        splits = []
        for part in parts:
            # Format: name:amount:reconcile:account_id
            pieces = part.rsplit(":", 3)
            name = pieces[0]
            amt = int(pieces[1])
            reconcile = pieces[2] if len(pieces) > 2 else "n"
            account_id = pieces[3] if len(pieces) > 3 else ""
            splits.append((name, amt, reconcile, account_id))
        return splits

    def _transfer_label(self, splits, account_types):
        """For 2-split balance-sheet transfers, return 'Source -> Dest'. Else ''."""
        if len(splits) != 2:
            return ""
        (name_a, amt_a, _, aid_a), (name_b, amt_b, _, aid_b) = splits
        type_a = account_types.get(aid_a)
        type_b = account_types.get(aid_b)
        if not (type_a in self.BALANCE_SHEET_TYPES and type_b in self.BALANCE_SHEET_TYPES):
            return ""
        fn = self._account_full_names.get
        label_a = fn(aid_a, name_a)
        label_b = fn(aid_b, name_b)
        # Positive amount = debit (destination), negative = credit (source)
        if amt_a < 0:
            return f"{label_a} → {label_b}"
        else:
            return f"{label_b} → {label_a}"

    def _max_text_width(self):
        """Max characters for wide text columns (30% of table width)."""
        table = self.query_one("#ledger-table", DataTable)
        w = table.size.width
        if w <= 0:
            # Not laid out yet; estimate: app width minus left panel + padding
            w = max(80, self.size.width - 50)
        return max(20, int(w * 0.30))

    @staticmethod
    def _truncate(value, max_chars):
        """Truncate a string or Rich Text to max_chars, adding ellipsis."""
        if isinstance(value, Text):
            if len(value) > max_chars:
                return value[:max_chars - 1] + Text("\u2026", style=value.style)
            return value
        if isinstance(value, str) and len(value) > max_chars:
            return value[:max_chars - 1] + "\u2026"
        return value

    def refresh_ledger(self):
        """Fetch ledger data and render the table."""
        table = self.query_one("#ledger-table", DataTable)
        table.clear(columns=True)
        table.cursor_type = "row"
        self._row_splits = {}
        self._row_imported = {}
        self._expanded_tx_id = None

        # Build account_id → type and account_id → full display path lookups
        self._account_types = {}
        self._account_full_names = {}
        all_accounts = get_all_accounts(self.con)
        by_id = {a["id"]: a for a in all_accounts}
        for a in all_accounts:
            self._account_types[a["id"]] = a["type"]
            self._account_full_names[a["id"]] = account_path(by_id, a["id"])

        self._is_account_view = bool(self.account_filter)

        if self._is_account_view:
            if self._status_mode == "compact":
                table.add_columns("St", "Date", "Description", "Vendor", "Other Account(s)", "Amount", "Balance")
            elif self._status_mode == "columns":
                table.add_columns("Src", "R", "Date", "Description", "Vendor", "Other Account(s)", "Amount", "Balance")
            else:  # color
                table.add_columns("R", "Date", "Description", "Vendor", "Other Account(s)", "Amount", "Balance")
            f_start = self.account_filter.get("start_date")
            f_end = self.account_filter.get("end_date")
            rows = get_account_transactions(
                self.con, self.account_filter["id"],
                start_date=f_start, end_date=f_end,
            )
            if self.search_query:
                q = self.search_query.lower()
                def _row_matches(r):
                    if q in r[0].lower() or q in r[1].lower() or q in r[2].lower() or q in r[5].lower():
                        return True
                    # Match against formatted split amounts
                    for part in r[2].split("|"):
                        pieces = part.rsplit(":", 3)
                        amt = int(pieces[1])
                        if q in fmt(amt).lower() or q in fmt(-amt).lower():
                            return True
                    return False
                rows = [r for r in rows if _row_matches(r)]
            title = self.query_one("#ledger-title", Label)
            filter_label = f"Account: {self.account_filter['name']}"
            if f_start and f_end:
                filter_label += f" ({format_date(f_start)} to {format_date(f_end)})"
            elif f_end:
                filter_label += f" (as of {format_date(f_end)})"
            if self.search_query:
                filter_label += f" / Search: \"{self.search_query}\""
            filter_label += f" ({len(rows)} transactions)"
            title.update(filter_label)
            self._filter_id = self.account_filter["id"]
        else:
            if self._status_mode == "compact":
                table.add_columns("St", "Date", "Description", "Vendor", "Transfer", "Amount")
            elif self._status_mode == "columns":
                table.add_columns("Src", "R", "Date", "Description", "Vendor", "Transfer", "Amount")
            else:  # color
                table.add_columns("R", "Date", "Description", "Vendor", "Transfer", "Amount")
            if self.search_query:
                rows = search_transactions(self.con, self.search_query)
                title = self.query_one("#ledger-title", Label)
                title.update(f"Search: \"{self.search_query}\" ({len(rows)} results)")
            else:
                rows = get_recent_transactions(self.con)
                title = self.query_one("#ledger-title", Label)
                title.update("All Transactions")
            self._filter_id = None

        # Parse splits for all rows
        self._ledger_data = rows
        for dt, desc, split_info, tx_id, imported, vendor_name in rows:
            self._row_splits[tx_id] = self._parse_splits(split_info)
            self._row_imported[tx_id] = bool(imported)

        # For account view, compute running balance bottom-up
        if self._is_account_view:
            bal_end = self.account_filter.get("end_date")
            running_balance = get_account_balance(
                self.con, self.account_filter["id"], end_date=bal_end,
            )
            balances = [0] * len(rows)
            for i in range(len(rows)):
                balances[i] = running_balance
                for _name, amt, _rec, aid in self._row_splits[rows[i][3]]:
                    if aid == self._filter_id:
                        running_balance -= amt
            self._ledger_balances = balances
        else:
            self._ledger_balances = None

        self._render_ledger_rows()

        # Auto-expand first row's splits if applicable
        if self._preferences.get("auto_expand_splits", False) and self._ledger_data:
            first_tx_id = self._ledger_data[0][3]
            if len(self._row_splits.get(first_tx_id, [])) > 2:
                self._expanded_tx_id = first_tx_id
                self._render_ledger_rows()

    @staticmethod
    def _styled_amount(amount_cents, positive_style=POSITIVE_COLOR,
                       negative_style=NEGATIVE_COLOR):
        """Return a Rich Text with color based on sign."""
        text = fmt(amount_cents)
        if amount_cents < 0:
            return Text(text, style=negative_style)
        elif amount_cents > 0:
            return Text(text, style=positive_style)
        return Text(text, style=DIM)

    def _tx_reconcile_status(self, splits):
        """Derive a single reconcile letter from splits: r > c > n."""
        best = "n"
        for _, _, rec, _ in splits:
            if rec == "r":
                return "R"
            if rec == "c":
                best = "c"
        return best if best == "c" else ""

    def _tx_reconcile_for_account(self, splits, account_id):
        """Get reconcile status for a specific account's split."""
        for _name, _, rec, aid in splits:
            if aid == account_id:
                if rec == "r":
                    return "R"
                if rec == "c":
                    return "c"
        return ""

    def _status_cells(self, tx_id, splits):
        """Return status column cells based on current mode."""
        imported = self._row_imported.get(tx_id, False)
        if self._is_account_view and self._filter_id:
            rec = self._tx_reconcile_for_account(splits, self._filter_id)
        else:
            rec = self._tx_reconcile_status(splits)

        if self._status_mode == "compact":
            src = "I" if imported else " "
            st = src + rec if rec else src + " "
            return [Text(st, style=DIM)]
        elif self._status_mode == "columns":
            src = Text("I", style=DIM) if imported else Text("")
            r_cell = Text(rec, style=DIM) if rec else Text("")
            return [src, r_cell]
        else:  # color
            r_cell = Text(rec, style=DIM) if rec else Text("")
            return [r_cell]

    def _status_empty_cells(self):
        """Return empty status cells for detail sub-rows."""
        if self._status_mode == "compact":
            return [""]
        elif self._status_mode == "columns":
            return ["", ""]
        else:
            return [""]

    def _render_ledger_rows(self, restore_tx_id=None):
        """Populate table rows, inserting detail sub-rows for expanded transaction."""
        table = self.query_one("#ledger-table", DataTable)
        self._row_index_to_key = []
        with self.prevent(DataTable.RowHighlighted):
            table.clear()  # rows only, keep columns

            target_row = 0
            for idx, (dt, desc, split_info, tx_id, imported, vendor_name) in enumerate(self._ledger_data):
                splits = self._row_splits[tx_id]
                amount = sum(amt for _, amt, _, _ in splits if amt > 0)

                if tx_id == restore_tx_id:
                    target_row = table.row_count

                amount_cell = self._styled_amount(amount)
                status_cells = self._status_cells(tx_id, splits)

                # In color mode, style imported descriptions differently
                if self._status_mode == "color" and self._row_imported.get(tx_id):
                    desc_cell = Text(desc, style=IMPORTED_COLOR)
                else:
                    desc_cell = desc

                # Prepend selection marker in bulk mode
                if self._bulk_mode and tx_id in self._selected_tx_ids:
                    if isinstance(desc_cell, Text):
                        desc_cell = Text("> ", style="bold yellow") + desc_cell
                    else:
                        desc_cell = Text(f"> {desc_cell}", style="bold yellow")

                display_date = format_date(dt)

                max_w = self._max_text_width()
                desc_cell = self._truncate(desc_cell, max_w)
                vendor_cell = Text(vendor_name, style=MUTED) if vendor_name else ""
                if self._is_account_view:
                    fn = self._account_full_names.get
                    other_names = [fn(aid, name) for name, _, _, aid in splits if aid != self._filter_id]
                    if len(splits) > 2:
                        other_col = Text(f"({len(splits)} splits)", style=SPLITS_HINT)
                    else:
                        other_col = " / ".join(other_names) if other_names else ""
                    other_col = self._truncate(other_col, max_w)
                    bal = self._ledger_balances[idx]
                    balance_cell = self._styled_amount(bal)
                    table.add_row(
                        *status_cells, display_date, desc_cell, vendor_cell, other_col,
                        amount_cell, balance_cell,
                        key=tx_id,
                    )
                else:
                    transfer_label = self._transfer_label(splits, self._account_types)
                    if transfer_label:
                        transfer_cell = Text(transfer_label, style=TRANSFER_COLOR)
                    elif len(splits) == 2:
                        non_bs = [(n, aid) for n, _, _, aid in splits if self._account_types.get(aid) not in self.BALANCE_SHEET_TYPES]
                        if non_bs:
                            name, aid = non_bs[0]
                        else:
                            name, aid = splits[1][0], splits[1][3]
                        transfer_cell = Text(self._account_full_names.get(aid, name), style=MUTED)
                    elif len(splits) > 2:
                        transfer_cell = Text(f"({len(splits)} splits)", style=SPLITS_HINT)
                    else:
                        transfer_cell = ""
                    transfer_cell = self._truncate(transfer_cell, max_w)
                    table.add_row(
                        *status_cells, display_date, desc_cell, vendor_cell, transfer_cell, amount_cell,
                        key=tx_id,
                    )
                self._row_index_to_key.append(tx_id)

                # Insert detail sub-rows for expanded multi-split transaction
                if tx_id == self._expanded_tx_id and len(splits) > 2:
                    empty_status = self._status_empty_cells()
                    for idx, (split_name, split_amt, _, split_aid) in enumerate(sorted(splits, key=lambda s: -s[1])):
                        detail_key = f"_split:{tx_id}:{idx}:{split_name}"
                        full_name = self._account_full_names.get(split_aid, split_name)
                        name_cell = Text(f"    {full_name}", style=DETAIL_NAME)
                        amt_cell = self._styled_amount(
                            split_amt, DETAIL_POSITIVE, DETAIL_NEGATIVE,
                        )
                        if self._is_account_view:
                            table.add_row(
                                *empty_status, "", name_cell, "", "",
                                amt_cell, "",
                                key=detail_key,
                            )
                        else:
                            table.add_row(
                                *empty_status, "", name_cell, "", "",
                                amt_cell,
                                key=detail_key,
                            )
                        self._row_index_to_key.append(detail_key)

            table.move_cursor(row=target_row)

    def _open_quick_function(self, qf):
        def on_dismiss(result):
            if result:
                self.refresh_balances()
                self.refresh_ledger()
                self.notify(f"Posted: {qf['label']}", severity="information")

        self.push_screen(QuickEntryScreen(qf, self.con), callback=on_dismiss)

    def action_cursor_down(self):
        table = self.query_one("#ledger-table", DataTable)
        if table.has_focus:
            table.action_cursor_down()

    def action_cursor_up(self):
        table = self.query_one("#ledger-table", DataTable)
        if table.has_focus:
            table.action_cursor_up()

    def action_cursor_top(self):
        table = self.query_one("#ledger-table", DataTable)
        if table.has_focus:
            table.move_cursor(row=0)

    def action_cursor_bottom(self):
        table = self.query_one("#ledger-table", DataTable)
        if table.has_focus:
            table.move_cursor(row=table.row_count - 1)

    def action_import(self):
        """Open the bank import flow."""
        self._launch_import()

    def action_reconcile(self):
        """Open the account reconciliation flow."""
        account_id = None
        account_name = None
        if self.account_filter:
            account_id = self.account_filter["id"]
            account_name = self.account_filter["name"]

        def on_setup(result):
            if not result:
                return
            self._launch_reconcile_worksheet(result)

        self.push_screen(
            ReconcileSetupScreen(self.con, account_id, account_name),
            callback=on_setup,
        )

    def _launch_reconcile_worksheet(self, setup_info):
        def on_worksheet(result):
            if result:
                self.refresh_balances()
                self.refresh_ledger()
                count = result.get("reconciled") or result.get("saved", 0)
                if "reconciled" in result:
                    self.notify(
                        f"Reconciled {count} transaction(s)",
                        severity="information",
                    )

        self.push_screen(
            ReconcileWorksheetScreen(self.con, setup_info),
            callback=on_worksheet,
        )

    def action_payee_rules(self):
        """Open the payee rules editor."""
        self.push_screen(PayeeRulesScreen(self.con))

    def action_search(self):
        """Open the search bar (vim-style /)."""
        bar = self.query_one("#search-bar")
        bar.add_class("visible")
        self.search_active = True
        search_input = self.query_one("#search-input", Input)
        search_input.select_on_focus = False
        search_input.value = self.search_query
        search_input.focus()
        search_input.cursor_position = len(search_input.value)

    def action_clear_search(self):
        """Close search bar, clear filter, or exit bulk mode."""
        if self.search_active:
            bar = self.query_one("#search-bar")
            bar.remove_class("visible")
            self.search_active = False
            self.search_query = ""
            self.refresh_ledger()
            self.query_one("#ledger-table", DataTable).focus()
        elif self._bulk_mode:
            self._exit_bulk_mode()
            self.notify("Bulk mode OFF", severity="information")
        elif self.account_filter:
            self.account_filter = None
            self.refresh_ledger()
            self.query_one("#ledger-table", DataTable).focus()

    @on(Input.Changed, "#search-input")
    def on_search_changed(self, event):
        """Live-filter the ledger as the user types."""
        self.search_query = event.value.strip()
        self.refresh_ledger()

    @on(Input.Submitted, "#search-input")
    def on_search_submitted(self, event):
        """Confirm search -- keep filter, close bar, focus table."""
        bar = self.query_one("#search-bar")
        bar.remove_class("visible")
        self.search_active = False
        self.query_one("#ledger-table", DataTable).focus()

    @on(DataTable.RowHighlighted, "#ledger-table")
    def on_ledger_row_highlighted(self, event):
        """Expand/collapse split detail rows inline, skip over detail rows."""
        tx_id = str(event.row_key.value)
        cursor_row = event.cursor_row

        # Skip over detail sub-rows to the next real transaction
        if tx_id.startswith("_split:"):
            moving_down = cursor_row >= self._last_cursor_row
            keys = self._row_index_to_key
            target = cursor_row
            if moving_down:
                while target < len(keys) - 1:
                    target += 1
                    if not keys[target].startswith("_split:"):
                        break
            else:
                while target > 0:
                    target -= 1
                    if not keys[target].startswith("_split:"):
                        break
            self._last_cursor_row = target
            self.query_one("#ledger-table", DataTable).move_cursor(row=target)
            return

        self._last_cursor_row = cursor_row
        if self._preferences.get("auto_expand_splits", False):
            splits = self._row_splits.get(tx_id, [])
            if len(splits) > 2:
                if self._expanded_tx_id != tx_id:
                    self._expanded_tx_id = tx_id
                    self._render_ledger_rows(restore_tx_id=tx_id)
                    self._last_cursor_row = self.query_one("#ledger-table", DataTable).cursor_row
            elif self._expanded_tx_id is not None:
                self._expanded_tx_id = None
                self._render_ledger_rows(restore_tx_id=tx_id)
                self._last_cursor_row = self.query_one("#ledger-table", DataTable).cursor_row

    def action_toggle_splits(self):
        """Toggle expand/collapse of splits, or toggle selection in bulk mode."""
        table = self.query_one("#ledger-table", DataTable)
        if not table.has_focus:
            return
        try:
            tx_id = self._row_index_to_key[table.cursor_row]
        except IndexError:
            return
        if tx_id.startswith("_split:"):
            return

        if self._bulk_mode:
            if tx_id in self._selected_tx_ids:
                self._selected_tx_ids.discard(tx_id)
            else:
                self._selected_tx_ids.add(tx_id)
            scroll_y = table.scroll_y
            self._render_ledger_rows(restore_tx_id=tx_id)
            # Advance cursor to the next row for rapid selection
            if table.cursor_row < table.row_count - 1:
                table.move_cursor(row=table.cursor_row + 1)
            self._last_cursor_row = table.cursor_row
            table.scroll_to(y=scroll_y, animate=False)
            return

        splits = self._row_splits.get(tx_id, [])
        if len(splits) <= 2:
            return
        scroll_y = table.scroll_y
        if self._expanded_tx_id == tx_id:
            self._expanded_tx_id = None
        else:
            self._expanded_tx_id = tx_id
        self._render_ledger_rows(restore_tx_id=tx_id)
        self._last_cursor_row = table.cursor_row
        # Restore scroll position so the row stays in place visually
        table.scroll_to(y=scroll_y, animate=False)

    @on(DataTable.RowSelected, "#ledger-table")
    def on_ledger_row_selected(self, event):
        """Open edit screen when Enter is pressed on a ledger row."""
        tx_id = str(event.row_key.value)
        # Ignore detail sub-rows
        if tx_id.startswith("_split:"):
            return

        if self._bulk_mode:
            if not self._selected_tx_ids:
                self.notify("Select transactions first (space to toggle)", severity="warning")
                return
            self._open_bulk_edit()
            return

        def on_dismiss(result):
            if result == "saved":
                self.refresh_balances()
                self.refresh_ledger()
                self.notify("Transaction updated", severity="information")
            elif result == "deleted":
                self.refresh_balances()
                self.refresh_ledger()
                self.notify("Transaction deleted", severity="warning")
            elif result == "copied":
                self.refresh_balances()
                self.refresh_ledger()
                self.notify("Transaction copied", severity="information")

        self.push_screen(EditTransactionScreen(tx_id, self.con), callback=on_dismiss)

    def _open_bulk_edit(self):
        """Open the bulk edit dialog for selected transactions."""
        tx_ids = list(self._selected_tx_ids)

        def on_dismiss(result):
            if result:
                self._selected_tx_ids.clear()
                self._exit_bulk_mode()
                self.refresh_balances()
                self.refresh_ledger()
                self.notify(f"Updated {len(tx_ids)} transactions", severity="information")

        # Use super().push_screen to avoid _exit_bulk_mode in push_screen override
        super(PyreApp, self).push_screen(
            BulkEditScreen(tx_ids, self.con), callback=on_dismiss,
        )

    def push_screen(self, *args, **kwargs):
        self._exit_bulk_mode()
        return super().push_screen(*args, **kwargs)

    def action_toggle_bulk(self):
        if self._bulk_mode:
            self._exit_bulk_mode()
            self.notify("Bulk mode OFF", severity="information")
        else:
            self._bulk_mode = True
            self.query_one("#bulk-indicator", Label).add_class("active")
            self.notify("Bulk select mode ON", severity="warning")

    def _exit_bulk_mode(self):
        if self._bulk_mode:
            self._bulk_mode = False
            self._selected_tx_ids.clear()
            self.query_one("#bulk-indicator", Label).remove_class("active")
            self._render_ledger_rows()

    def action_delete_transaction(self):
        if self.search_active:
            return
        self._delete_selected()

    def _delete_selected(self):
        """Delete the currently highlighted transaction (with confirmation)."""
        table = self.query_one("#ledger-table", DataTable)
        if table.row_count == 0:
            return
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        tx_id = str(row_key.value)
        if tx_id.startswith("_split:"):
            return
        if is_transaction_reconciled(self.con, tx_id):
            self.notify("Cannot delete a reconciled transaction", severity="error")
            return

        if self._bulk_mode:
            try:
                cursor_row = table.cursor_coordinate.row
                delete_transaction(self.con, tx_id)
                self.refresh_balances()
                self.refresh_ledger()
                # Restore cursor to same row, or last row if we deleted the end
                max_row = max(table.row_count - 1, 0)
                table.move_cursor(row=min(cursor_row, max_row))
                self.notify("Transaction deleted", severity="warning")
            except Exception as e:
                self.notify(f"Delete failed: {e}", severity="error")
            return

        # Find the transaction date and description for the confirmation dialog
        tx_data = next(
            ((dt, desc) for dt, desc, _, tid, *_ in self._ledger_data if tid == tx_id),
            None,
        )
        if not tx_data:
            return

        def on_confirm(confirmed):
            if confirmed:
                try:
                    delete_transaction(self.con, tx_id)
                    self.refresh_balances()
                    self.refresh_ledger()
                    self.notify("Transaction deleted", severity="warning")
                except Exception as e:
                    self.notify(f"Delete failed: {e}", severity="error")

        self.push_screen(
            ConfirmDeleteTransactionScreen(tx_data[0], tx_data[1]),
            callback=on_confirm,
        )

    def action_favorites(self):
        """Enter favorites mode to select a sidebar account by number."""
        if not self._sidebar_accounts:
            self.notify("No favorite accounts", severity="warning")
            return
        self._favorites_mode = True
        self._highlight_favorites(True)
        self.notify("Press 1-9 to jump to account, Esc to cancel",
                    severity="information")

    def _highlight_favorites(self, on):
        """Toggle highlight on sidebar favorite keys."""
        box = self.query_one("#balances-box")
        for label in box.query(".fav-key"):
            if on:
                label.add_class("fav-key-active")
            else:
                label.remove_class("fav-key-active")

    def action_qf_mode(self):
        """Enter quick function mode to select a QF by any key."""
        if not self._quick_functions:
            self.notify("No quick functions defined", severity="warning")
            return
        self._qf_mode = True
        self._highlight_qf_keys(True)
        self.notify("Press a key to run quick function, Esc to cancel",
                    severity="information")

    def _highlight_qf_keys(self, on):
        """Toggle highlight on non-digit quick function keys (digits stay highlighted)."""
        left = self.query_one("#left-panel")
        for label, qf in zip(left.query(".qf-key"), self._quick_functions):
            if on:
                label.add_class("qf-key-active")
            elif qf["key"] not in "0123456789":
                label.remove_class("qf-key-active")

    def _select_favorite(self, index):
        """Navigate to the favorite account at the given 0-based index."""
        if index < 0 or index >= len(self._sidebar_accounts):
            self.notify("No account at that position", severity="warning")
            return
        acct_id, name, _ = self._sidebar_accounts[index]
        self.account_filter = {"id": acct_id, "name": name}
        self.refresh_ledger()
        self.query_one("#ledger-table", DataTable).focus()

    def on_key(self, event):
        if self._qf_mode:
            self._qf_mode = False
            self._highlight_qf_keys(False)
            if event.key == "escape":
                event.prevent_default()
                event.stop()
                return
            if event.character:
                qf = next((q for q in self._quick_functions if q["key"] == event.character), None)
                if qf:
                    self._open_quick_function(qf)
                    event.prevent_default()
                    event.stop()
            return

        if not self._favorites_mode:
            if not self.search_active and event.character and event.character in "0123456789":
                qf = next((q for q in self._quick_functions if q["key"] == event.character), None)
                if qf:
                    self._open_quick_function(qf)
                    event.prevent_default()
                    event.stop()
            return
        key = event.key
        if key == "escape":
            self._favorites_mode = False
            self._highlight_favorites(False)
            event.prevent_default()
            event.stop()
        elif key in "123456789":
            self._favorites_mode = False
            self._highlight_favorites(False)
            self._select_favorite(int(key) - 1)
            event.prevent_default()
            event.stop()
        else:
            self._favorites_mode = False
            self._highlight_favorites(False)

    def action_toggle_status(self):
        idx = STATUS_MODES.index(self._status_mode)
        self._status_mode = STATUS_MODES[(idx + 1) % len(STATUS_MODES)]
        self.refresh_ledger()

    def action_refresh(self):
        self.refresh_balances()
        self.refresh_ledger()
        self.notify("Refreshed", severity="information")

    def action_show_chart_of_accounts(self):
        """Open the Chart of Accounts editor."""

        def on_dismiss(result):
            self.refresh_balances()
            if isinstance(result, dict) and result.get("action") == "view_transactions":
                acct = result["account"]
                self.account_filter = {"id": acct["id"], "name": acct["name"]}
                self.refresh_ledger()
                self.query_one("#ledger-table", DataTable).focus()

        self.push_screen(ChartOfAccountsScreen(self.con), callback=on_dismiss)

    def action_show_pnl(self):
        """Open the Profit & Loss report via date picker."""
        def on_dates(result):
            if result:
                def on_pnl(pnl_result):
                    if isinstance(pnl_result, dict) and pnl_result.get("action") == "view_transactions":
                        acct = pnl_result["account"]
                        self.account_filter = {
                            "id": acct["id"],
                            "name": acct["name"],
                            "start_date": pnl_result.get("start_date"),
                            "end_date": pnl_result.get("end_date"),
                        }
                        self.refresh_ledger()
                        self.query_one("#ledger-table", DataTable).focus()

                self.push_screen(
                    ProfitLossScreen(self.con, result["start"], result["end"]),
                    callback=on_pnl,
                )

        self.push_screen(ReportDateScreen("pnl"), callback=on_dates)

    def action_show_cash_flow(self):
        """Open the Cash Flow Statement via date picker."""
        def on_dates(result):
            if result:
                def on_cf(cf_result):
                    if isinstance(cf_result, dict) and cf_result.get("action") == "view_transactions":
                        acct = cf_result["account"]
                        self.account_filter = {
                            "id": acct["id"],
                            "name": acct["name"],
                            "start_date": cf_result.get("start_date"),
                            "end_date": cf_result.get("end_date"),
                        }
                        self.refresh_ledger()
                        self.query_one("#ledger-table", DataTable).focus()

                self.push_screen(
                    CashFlowScreen(self.con, result["start"], result["end"]),
                    callback=on_cf,
                )

        self.push_screen(ReportDateScreen("cash_flow"), callback=on_dates)

    def action_show_balance_sheet(self):
        """Open the Balance Sheet report via date picker."""
        def on_dates(result):
            if result:
                def on_bs(bs_result):
                    if isinstance(bs_result, dict) and bs_result.get("action") == "view_transactions":
                        acct = bs_result["account"]
                        self.account_filter = {
                            "id": acct["id"],
                            "name": acct["name"],
                            "end_date": bs_result.get("end_date"),
                        }
                        self.refresh_ledger()
                        self.query_one("#ledger-table", DataTable).focus()

                self.push_screen(
                    BalanceSheetScreen(self.con, result["as_of"]),
                    callback=on_bs,
                )

        self.push_screen(ReportDateScreen("balance_sheet"), callback=on_dates)

    def action_show_trial_balance(self):
        """Open the Trial Balance report via date picker."""
        def on_dates(result):
            if result:
                def on_tb(tb_result):
                    if isinstance(tb_result, dict) and tb_result.get("action") == "view_transactions":
                        acct = tb_result["account"]
                        self.account_filter = {
                            "id": acct["id"],
                            "name": acct["name"],
                            "end_date": tb_result.get("end_date"),
                        }
                        self.refresh_ledger()
                        self.query_one("#ledger-table", DataTable).focus()

                self.push_screen(
                    TrialBalanceScreen(self.con, result["as_of"]),
                    callback=on_tb,
                )

        self.push_screen(ReportDateScreen("balance_sheet"), callback=on_dates)

    def _launch_import(self, filepath=None):
        """Open the bank import flow. If filepath given, skip the file picker."""
        def on_dismiss(result):
            if result and isinstance(result, dict):
                count = result.get("committed", 0)
                self.refresh_balances()
                self.refresh_ledger()
                self.notify(f"Imported {count} transaction(s)", severity="information")

        screen = ImportFileScreen(self.con, filepath=filepath)
        self.push_screen(screen, callback=on_dismiss)

    def action_add_transaction(self):
        """Open the Add Transaction screen."""
        def on_dismiss(result):
            if result == "posted":
                self.refresh_balances()
                self.refresh_ledger()
                self.notify("Transaction posted", severity="information")

        self.push_screen(
            AddTransactionScreen(self.con, account_filter=self.account_filter),
            callback=on_dismiss,
        )

    def action_show_vendors(self):
        """Open the Vendor list/editor."""
        def on_dismiss(result):
            self.refresh_balances()
            self.refresh_ledger()

        self.push_screen(VendorListScreen(self.con), callback=on_dismiss)

    def _check_pending_scheduled(self):
        """Check for pending scheduled transactions and show review screen."""
        from pyre.scheduled_models import get_pending_scheduled_transactions
        pending = get_pending_scheduled_transactions(self.con)
        if pending:
            def on_dismiss(result):
                if result and result.get("posted", 0) > 0:
                    self.refresh_balances()
                    self.refresh_ledger()
                    self.notify(
                        f"Posted {result['posted']} scheduled transaction(s)",
                        severity="information",
                    )

            self.push_screen(PendingScheduledScreen(self.con), callback=on_dismiss)

    def action_show_scheduled(self):
        """Open the scheduled transactions editor."""
        def on_dismiss(result):
            self.refresh_balances()
            self.refresh_ledger()

        self.push_screen(ScheduledListScreen(self.con), callback=on_dismiss)

    def action_show_expenses_by_vendor(self):
        """Open the Expenses by Vendor Summary report via date picker."""
        def on_dates(result):
            if result:
                self.push_screen(
                    ExpensesByVendorScreen(
                        self.con, result["start"], result["end"],
                    ),
                )

        self.push_screen(ReportDateScreen("pnl"), callback=on_dates)

    def action_show_reconciliation_reports(self):
        """Open the Reconciliation Report picker."""
        def on_pick(rec_id):
            if rec_id:
                self.push_screen(
                    ReconciliationReportScreen(self.con, rec_id),
                )

        self.push_screen(
            ReconciliationReportPickerScreen(self.con),
            callback=on_pick,
        )
