"""Account reconciliation screens."""

from textual import on
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, OptionList
from textual.widgets.option_list import Option

from rich.text import Text

from pyre.fuzzy_select import FuzzySelect

from pyre.account_models import get_all_accounts
from pyre.dates import DateInput
from pyre.formatting import cents, fmt, format_date
from pyre.models import (
    finish_reconciliation,
    get_last_reconciliation,
    get_reconcile_session,
    get_reconciled_balance,
    get_unreconciled_splits,
    save_reconciliation_progress,
)
from pyre.db import ASSET_TYPES, LIABILITY_TYPES
from pyre.ui.styles import (
    QUICK_FUNCTION_PICKER_CSS,
    RECONCILE_SETUP_CSS,
    RECONCILE_WORKSHEET_CSS,
)

# Account types that can be reconciled (balance sheet accounts)
RECONCILABLE_TYPES = frozenset(ASSET_TYPES + LIABILITY_TYPES)

_TYPE_DISPLAY = {
    "asset": "Asset", "accounts_receivable": "A/R",
    "other_current_asset": "Current Asset",
    "fixed_asset": "Fixed Asset", "other_asset": "Other Asset",
    "liability": "Liability", "accounts_payable": "A/P",
    "credit_card": "Credit Card",
    "other_current_liability": "Current Liability",
    "long_term_liability": "Long Term Liability",
}


def _build_reconcilable_options(con):
    """Build (label, id) list filtered to reconcilable account types."""
    accounts = get_all_accounts(con)
    by_id = {a["id"]: a for a in accounts}

    def build_path(account_id):
        parts = []
        current = account_id
        while current:
            acct = by_id.get(current)
            if not acct:
                break
            parts.append(acct["name"])
            current = acct["parent_id"]
        parts.reverse()
        return " : ".join(parts)

    options = []
    for a in accounts:
        if a["type"] not in RECONCILABLE_TYPES:
            continue
        path = build_path(a["id"])
        num = a["account_number"] or ""
        type_tag = _TYPE_DISPLAY.get(a["type"], a["type"])
        label = f"{num} - {path}" if num else path
        label = f"{label} ({type_tag})"
        options.append((label, a["id"]))
    return options


class QuickFunctionPickerScreen(ModalScreen):
    """Modal picker for selecting a quick function."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = QUICK_FUNCTION_PICKER_CSS

    def __init__(self, quick_functions):
        super().__init__()
        self._quick_functions = quick_functions

    def compose(self):
        with Vertical(id="qfp-dialog"):
            yield Label("Quick Functions", id="qfp-title")
            ol = OptionList(id="qfp-list")
            for qf in self._quick_functions:
                key = qf["key"]
                label = qf["label"]
                ol.add_option(Option(f"\\[{key}] {label}"))
            yield ol
            yield Label("Enter=select  Esc=cancel", id="qfp-hint")

    def on_mount(self):
        ol = self.query_one("#qfp-list", OptionList)
        if self._quick_functions:
            ol.highlighted = 0
        ol.focus()

    @on(OptionList.OptionSelected, "#qfp-list")
    def on_option_selected(self, event):
        idx = event.option_index
        if 0 <= idx < len(self._quick_functions):
            self.dismiss(self._quick_functions[idx])

    def on_key(self, event):
        if event.character:
            qf = next((q for q in self._quick_functions if q["key"] == event.character), None)
            if qf:
                self.dismiss(qf)
                event.prevent_default()
                event.stop()

    def action_cancel(self):
        self.dismiss(None)


class ReconcileSetupScreen(ModalScreen):
    """Setup dialog for account reconciliation."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = RECONCILE_SETUP_CSS

    def __init__(self, con, account_id=None, account_name=None):
        super().__init__()
        self.con = con
        self._preset_account_id = account_id
        self._preset_account_name = account_name
        self._account_type_map = {}

    def compose(self):
        options = _build_reconcilable_options(self.con)
        self._option_labels = options
        # Build type lookup
        for a in get_all_accounts(self.con):
            self._account_type_map[a["id"]] = a["type"]

        with Vertical(id="rs-dialog"):
            yield Label("Reconcile Account", id="rs-title")

            if self._preset_account_id:
                yield Label(
                    f"Account: {self._preset_account_name}",
                    classes="rs-field-label",
                )
            else:
                yield Label("Account:", classes="rs-field-label")
                yield FuzzySelect(options, id="rs-account-picker")

            yield Label("", id="rs-last-info", classes="rs-info")
            yield Label("", id="rs-beginning-bal", classes="rs-field-label")

            yield Label("Statement date:", classes="rs-field-label")
            yield DateInput(
                placeholder="MM-DD-YYYY", id="rs-stmt-date", classes="rs-input",
            )
            yield Label("Statement ending balance:", classes="rs-field-label")
            yield Input(
                placeholder="$0.00", id="rs-stmt-balance", classes="rs-input",
            )

            yield Label("", id="rs-error")
            with Horizontal(id="rs-buttons"):
                yield Button("Continue", variant="primary", id="rs-continue")
                yield Button("Cancel", id="rs-cancel-btn")

    def on_mount(self):
        # Dynamically size dialog to fit the longest account name
        # padding(2*2) + border(2*2) + some extra breathing room
        padding_border = 10
        if self._preset_account_id and self._preset_account_name:
            max_label = len(self._preset_account_name) + len("Account: ")
        else:
            max_label = max(
                (len(label) for label, _ in self._option_labels),
                default=0,
            )
        dialog_width = max(70, min(max_label + padding_border, 120))
        self.query_one("#rs-dialog").styles.width = dialog_width

        if self._preset_account_id:
            self._update_account_info(self._preset_account_id)
            self.query_one("#rs-stmt-date", DateInput).focus()
        else:
            self.query_one("#rs-last-info").display = False
            self.query_one("#rs-beginning-bal").display = False
            self.query_one("#rs-account-picker", FuzzySelect).query_one(".fs-filter", Input).focus()

    @on(FuzzySelect.Selected, "#rs-account-picker")
    def on_account_picked(self, event):
        self.query_one("#rs-last-info").display = True
        self.query_one("#rs-beginning-bal").display = True
        self._update_account_info(event.value)
        self.query_one("#rs-stmt-date", DateInput).focus()

    def _update_account_info(self, account_id):
        """Update the last reconciliation info and beginning balance.
        Pre-fill date/balance from an in-progress session if one exists."""
        beginning = get_reconciled_balance(self.con, account_id)
        acct_type = self._account_type_map.get(account_id, "")
        display_bal = -beginning if acct_type in LIABILITY_TYPES else beginning

        session = get_reconcile_session(self.con, account_id)
        last = get_last_reconciliation(self.con, account_id)

        if session:
            self.query_one("#rs-last-info", Label).update(
                f"Resuming in-progress reconciliation (saved {format_date(session['saved_at'][:10])})"
            )
            self.query_one("#rs-stmt-date", DateInput).value = format_date(session["statement_date"])
            stmt_bal = session["statement_balance"]
            if acct_type in LIABILITY_TYPES:
                stmt_bal = -stmt_bal
            self.query_one("#rs-stmt-balance", Input).value = fmt(stmt_bal)
        elif last:
            self.query_one("#rs-last-info", Label).update(
                f"Last reconciled: {format_date(last['statement_date'])} "
                f"({last['split_count']} items)"
            )
        else:
            self.query_one("#rs-last-info", Label).update(
                "No previous reconciliation"
            )

        self.query_one("#rs-beginning-bal", Label).update(
            f"Beginning balance: {fmt(display_bal)}"
        )

    def _get_account_id(self):
        if self._preset_account_id:
            return self._preset_account_id
        return self.query_one("#rs-account-picker", FuzzySelect).value

    @on(Input.Submitted, "#rs-stmt-date")
    def on_date_submitted(self, event):
        self.query_one("#rs-stmt-balance", Input).focus()

    @on(Input.Submitted, "#rs-stmt-balance")
    def on_balance_submitted(self, event):
        self._do_continue()

    @on(Button.Pressed, "#rs-continue")
    def on_continue_pressed(self, event):
        self._do_continue()

    @on(Button.Pressed, "#rs-cancel-btn")
    def on_cancel_pressed(self, event):
        self.dismiss(None)

    def action_cancel(self):
        self.dismiss(None)

    def _do_continue(self):
        error = self.query_one("#rs-error", Label)

        account_id = self._get_account_id()
        if not account_id:
            error.update("Please select an account.")
            return

        date_val = self.query_one("#rs-stmt-date", DateInput).value.strip()
        if not date_val:
            error.update("Please enter a statement date.")
            return

        from pyre.dates import parse_date
        try:
            statement_date = parse_date(date_val)
        except ValueError:
            error.update("Invalid date format.")
            return

        balance_val = self.query_one("#rs-stmt-balance", Input).value.strip()
        if not balance_val:
            error.update("Please enter the statement ending balance.")
            return

        try:
            cleaned = balance_val.replace("$", "").replace(",", "")
            statement_balance = cents(cleaned)
        except Exception:
            error.update("Invalid balance amount.")
            return

        # Negate for liability accounts (user enters positive = what they owe)
        acct_type = self._account_type_map.get(account_id, "")
        if acct_type in LIABILITY_TYPES:
            statement_balance = -statement_balance

        beginning_balance = get_reconciled_balance(self.con, account_id)

        # Get account name for display
        account_name = self._preset_account_name
        if not account_name:
            acct = self.con.execute(
                "SELECT name FROM accounts WHERE id = ?", (account_id,)
            ).fetchone()
            account_name = acct[0] if acct else account_id

        self.dismiss({
            "account_id": account_id,
            "account_name": account_name,
            "account_type": acct_type,
            "statement_date": statement_date,
            "statement_balance": statement_balance,
            "beginning_balance": beginning_balance,
        })


class ReconcileWorksheetScreen(ModalScreen):
    """Worksheet for checking off transactions during reconciliation."""

    BINDINGS = [
        Binding("escape", "cancel_reconcile", "Cancel"),
        Binding("space", "toggle_item", "Toggle", show=False),
        Binding("j", "nav_down", "Down", show=False),
        Binding("k", "nav_up", "Up", show=False),
        Binding("g", "nav_top", "Top", show=False),
        Binding("G", "nav_bottom", "Bottom", show=False),
        Binding("a", "select_all", "All", show=False),
        Binding("n", "clear_all", "None", show=False),
        Binding("o", "add_transaction", "Add Txn", show=False),
        Binding("q", "quick_function", "Quick Fn", show=False),
        Binding("w", "finish_later", "Save", show=False),
    ]

    DEFAULT_CSS = RECONCILE_WORKSHEET_CSS

    def __init__(self, con, setup_info):
        super().__init__()
        self.con = con
        self.account_id = setup_info["account_id"]
        self.account_name = setup_info["account_name"]
        self.account_type = setup_info["account_type"]
        self.statement_date = setup_info["statement_date"]
        self.statement_balance = setup_info["statement_balance"]
        self.beginning_balance = setup_info["beginning_balance"]
        self._splits = []  # list of split dicts
        self._cleared = set()  # set of split_ids that are checked

    def compose(self):
        with Vertical(id="rw-container"):
            yield Label(f"Reconcile: {self.account_name}", id="rw-title")
            yield Label(
                f"Statement date: {format_date(self.statement_date)}", id="rw-subtitle",
            )

            with Horizontal(id="rw-summary"):
                with Vertical(classes="rw-summary-col"):
                    yield Label("Beginning", classes="rw-summary-label")
                    yield Label("", id="rw-begin-val", classes="rw-summary-value")
                with Vertical(classes="rw-summary-col"):
                    yield Label("Cleared", classes="rw-summary-label")
                    yield Label("", id="rw-cleared-val", classes="rw-summary-value")
                with Vertical(classes="rw-summary-col"):
                    yield Label("Statement", classes="rw-summary-label")
                    yield Label("", id="rw-stmt-val", classes="rw-summary-value")
                with Vertical(classes="rw-summary-col"):
                    yield Label("Difference", classes="rw-summary-label")
                    yield Label("", id="rw-diff-val", classes="rw-summary-value")

            yield DataTable(id="rw-table")
            yield Label(
                "\\[Space] Toggle  \\[A] All  \\[N] None  \\[O] New Txn  "
                "\\[Q] Quick Fn  \\[Enter] Finish  \\[W] Save  \\[Esc] Cancel",
                id="rw-hint",
            )

    def on_mount(self):
        self._load_splits()
        table = self.query_one("#rw-table", DataTable)
        table.cursor_type = "row"
        table.add_column("", width=3)
        table.add_column("Date", width=12)
        table.add_column("Description")
        table.add_column("Amount", width=14)
        self._refresh_table()
        self._update_summary()
        table.focus()

    def _load_splits(self):
        """Load unreconciled splits and pre-check cleared ones."""
        self._splits = get_unreconciled_splits(
            self.con, self.account_id, self.statement_date,
        )
        self._cleared = set()
        for s in self._splits:
            if s["reconcile"] == "c":
                self._cleared.add(s["split_id"])

    def _reload(self):
        """Reload splits while preserving user selections, then refresh."""
        prev_cleared = set(self._cleared)
        self._load_splits()
        self._cleared |= prev_cleared
        self._refresh_table()
        self._update_summary()

    def _refresh_table(self):
        table = self.query_one("#rw-table", DataTable)
        saved_row = table.cursor_row
        table.clear()
        is_liability = self.account_type in LIABILITY_TYPES
        for s in self._splits:
            check = Text("X", style="bold green") if s["split_id"] in self._cleared else Text("")
            amt = -s["amount"] if is_liability else s["amount"]
            amt_text = fmt(amt)
            if amt < 0:
                amt_cell = Text(amt_text, style="red")
            elif amt > 0:
                amt_cell = Text(amt_text, style="green")
            else:
                amt_cell = Text(amt_text, style="dim")
            desc = s["description"]
            if not desc and s.get("vendor_name"):
                desc = Text(s["vendor_name"], style="dim")
            table.add_row(check, format_date(s["date"]), desc, amt_cell,
                          key=s["split_id"])

        if saved_row is not None and table.row_count > 0:
            table.move_cursor(row=min(saved_row, table.row_count - 1))

    def _update_summary(self):
        is_liability = self.account_type in LIABILITY_TYPES
        cleared_sum = sum(
            s["amount"] for s in self._splits if s["split_id"] in self._cleared
        )
        cleared_balance = self.beginning_balance + cleared_sum
        difference = self.statement_balance - cleared_balance

        # Display values: negate for liabilities
        disp_begin = -self.beginning_balance if is_liability else self.beginning_balance
        disp_cleared = -cleared_balance if is_liability else cleared_balance
        disp_stmt = -self.statement_balance if is_liability else self.statement_balance
        disp_diff = -difference if is_liability else difference

        self.query_one("#rw-begin-val", Label).update(fmt(disp_begin))
        self.query_one("#rw-cleared-val", Label).update(fmt(disp_cleared))
        self.query_one("#rw-stmt-val", Label).update(fmt(disp_stmt))

        diff_label = self.query_one("#rw-diff-val", Label)
        diff_label.update(fmt(disp_diff))
        diff_label.remove_class("rw-balanced")
        diff_label.remove_class("rw-unbalanced")
        if difference == 0:
            diff_label.add_class("rw-balanced")
        else:
            diff_label.add_class("rw-unbalanced")

    def _current_split_id(self):
        table = self.query_one("#rw-table", DataTable)
        if table.cursor_row is not None and table.row_count > 0:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            return str(row_key.value)
        return None

    def action_toggle_item(self):
        split_id = self._current_split_id()
        if not split_id:
            return
        table = self.query_one("#rw-table", DataTable)
        at_last_row = (table.cursor_row == table.row_count - 1)
        if split_id in self._cleared:
            self._cleared.discard(split_id)
        else:
            self._cleared.add(split_id)
        self._refresh_table()
        self._update_summary()
        if not at_last_row:
            table.action_cursor_down()

    def action_nav_down(self):
        self.query_one("#rw-table", DataTable).action_cursor_down()

    def action_nav_up(self):
        self.query_one("#rw-table", DataTable).action_cursor_up()

    def action_nav_top(self):
        self.query_one("#rw-table", DataTable).move_cursor(row=0)

    def action_nav_bottom(self):
        table = self.query_one("#rw-table", DataTable)
        table.move_cursor(row=table.row_count - 1)

    def action_select_all(self):
        for s in self._splits:
            self._cleared.add(s["split_id"])
        self._refresh_table()
        self._update_summary()

    def action_clear_all(self):
        self._cleared.clear()
        self._refresh_table()
        self._update_summary()

    def action_finish(self):
        cleared_sum = sum(
            s["amount"] for s in self._splits if s["split_id"] in self._cleared
        )
        cleared_balance = self.beginning_balance + cleared_sum
        difference = self.statement_balance - cleared_balance

        if difference != 0:
            is_liability = self.account_type in LIABILITY_TYPES
            disp_diff = -difference if is_liability else difference
            self.notify(
                f"Cannot finish: difference is {fmt(disp_diff)}",
                severity="error",
            )
            return

        split_ids = list(self._cleared)
        finish_reconciliation(
            self.con, self.account_id, split_ids,
            self.statement_date, self.statement_balance,
            self.beginning_balance,
        )
        self.dismiss({"reconciled": len(split_ids)})

    def action_finish_later(self):
        """Save progress: mark checked as 'c', unchecked as 'n'."""
        all_ids = {s["split_id"] for s in self._splits}
        uncleared_ids = all_ids - self._cleared
        save_reconciliation_progress(
            self.con, self.account_id,
            list(self._cleared), list(uncleared_ids),
            self.statement_date, self.statement_balance,
        )
        self.notify(
            f"Progress saved: {len(self._cleared)} items cleared",
            severity="information",
        )
        self.dismiss({"saved": len(self._cleared)})

    def action_cancel_reconcile(self):
        self.dismiss(None)

    def action_add_transaction(self):
        """Open AddTransactionScreen pre-filtered to this account."""
        from pyre.ui.screens import AddTransactionScreen

        def on_dismiss(result):
            if result == "posted":
                self._reload()
                self.notify("Transaction posted", severity="information")

        self.app.push_screen(
            AddTransactionScreen(
                self.con,
                account_filter={"id": self.account_id, "name": self.account_name},
            ),
            callback=on_dismiss,
        )

    def action_quick_function(self):
        """Open quick function picker, then run the selected quick function."""
        from pyre.ui.screens import QuickEntryScreen

        quick_functions = self.app._quick_functions
        if not quick_functions:
            self.notify("No quick functions defined", severity="warning")
            return

        def on_pick(qf):
            if qf is None:
                return

            def on_entry(result):
                if result:
                    self._reload()
                    self.notify(
                        f"Posted: {qf['label']}", severity="information",
                    )

            self.app.push_screen(
                QuickEntryScreen(qf, self.con), callback=on_entry,
            )

        self.app.push_screen(
            QuickFunctionPickerScreen(quick_functions), callback=on_pick,
        )

    @on(DataTable.RowSelected, "#rw-table")
    def on_row_selected(self, event):
        """Enter on a row triggers finish."""
        self.action_finish()


