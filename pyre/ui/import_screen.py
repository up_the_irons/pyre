"""Import screens for bank transaction import."""

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

from textual import on
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, Select

from rich.text import Text

from pyre.fuzzy_select import FuzzySelect

from pyre.account_models import account_path, get_all_accounts
from pyre.formatting import fmt, format_date, new_id
from pyre.vendor_models import get_all_vendors

def _generalize_pattern(description):
    """Strip trailing unique IDs/reference numbers to make a more general payee rule.

    "STRIPE TRANSFER ST-J1F0P8E2Z3N1" -> "STRIPE TRANSFER"
    "AMAZON.COM*A2B3C4" -> "AMAZON.COM"
    "PAYPAL TRANSFER" -> "PAYPAL TRANSFER" (no change)
    """
    # Strip trailing token that looks like a unique ID (mixed alpha+digits, or has dashes)
    # e.g. "ST-J1F0P8E2Z3N1", "*A2B3C4", "REF#12345"
    pattern = description.strip()
    # Remove trailing alphanumeric ID after * or # (e.g. AMAZON.COM*A2B3C4)
    pattern = re.sub(r'[*#]\w+$', '', pattern).strip()
    # Remove trailing token that's purely digits (e.g. "Trnsfr 2601")
    pattern = re.sub(r'\s+\d+$', '', pattern).strip()
    # Remove trailing token with mixed letters+digits (e.g. ST-J1F0P8E2Z3N1)
    pattern = re.sub(r'\s+(?=\S*\d)\S*(?=[A-Z])\S+$', '', pattern, flags=re.IGNORECASE).strip()
    pattern = re.sub(r'\s+\S*[A-Z]\S*\d\S*$', '', pattern, flags=re.IGNORECASE).strip()
    # Don't return empty
    return pattern if pattern else description.strip()


_TYPE_DISPLAY = {
    "asset": "Asset", "accounts_receivable": "A/R", "other_current_asset": "Current Asset",
    "fixed_asset": "Fixed Asset", "other_asset": "Other Asset",
    "liability": "Liability", "accounts_payable": "A/P", "credit_card": "Credit Card",
    "other_current_liability": "Current Liability", "long_term_liability": "Long Term Liability",
    "equity": "Equity",
    "income": "Income", "other_income": "Other Income",
    "expense": "Expense", "cost_of_goods_sold": "COGS", "other_expense": "Other Expense",
}


_account_path = account_path


def _build_account_options(con):
    """Build (label, id) list for account Select widgets, with type annotation.

    Sorted by usage frequency (most-used accounts first).
    """
    accounts = get_all_accounts(con)
    by_id = {a["id"]: a for a in accounts}

    # Count splits per account for frequency-based sorting
    usage = {}
    for row in con.execute(
        "SELECT account_id, COUNT(*) FROM splits GROUP BY account_id"
    ).fetchall():
        usage[row[0]] = row[1]

    options = []
    for a in accounts:
        path = _account_path(by_id, a["id"])
        num = a["account_number"] or ""
        type_tag = _TYPE_DISPLAY.get(a["type"], a["type"])
        label = f"{num} - {path}" if num else path
        label = f"{label} ({type_tag})"
        options.append((label, a["id"], usage.get(a["id"], 0)))
    options.sort(key=lambda x: x[2], reverse=True)
    return [(label, aid) for label, aid, _ in options]
from pyre.importers.matcher import match_transactions
from pyre.importers.models import (
    create_payee_rule,
    delete_payee_rule,
    find_account_by_ofx,
    get_payee_rules,
    is_already_imported,
    log_import,
    set_account_ofx_mapping,
    update_payee_rule,
)
from pyre.models import post_transaction
from pyre.ui.styles import IMPORT_FILE_CSS, IMPORT_REVIEW_CSS, JOURNAL_REVIEW_CSS, ACCOUNT_PICKER_CSS, PAYEE_RULES_CSS


class ImportFileScreen(ModalScreen):
    """Modal for entering the file path to import."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = IMPORT_FILE_CSS

    def __init__(self, con, filepath=None):
        super().__init__()
        self.con = con
        self._auto_filepath = filepath

    def compose(self):
        with Vertical(id="if-dialog"):
            yield Label("Import Bank Transactions", id="if-title")
            yield Label("Enter path to OFX/QFX, CSV, or XLSX file:", classes="if-field-label")
            yield Input(placeholder="/path/to/download.ofx", id="if-path", classes="if-input")
            yield Label("", id="if-error")
            with Horizontal(id="if-buttons"):
                yield Button("Import", variant="primary", id="if-import")
                yield Button("Cancel", id="if-cancel-btn")

    def on_mount(self):
        if self._auto_filepath:
            self.query_one("#if-path", Input).value = self._auto_filepath
            self.call_after_refresh(self._do_import)
        else:
            self.query_one("#if-path", Input).focus()

    @on(Input.Submitted, "#if-path")
    def on_path_submitted(self, event):
        self._do_import()

    @on(Button.Pressed, "#if-import")
    def on_import_pressed(self, event):
        self._do_import()

    @on(Button.Pressed, "#if-cancel-btn")
    def on_cancel_pressed(self, event):
        self.dismiss(None)

    def action_cancel(self):
        self.dismiss(None)

    def _do_import(self):
        filepath = self.query_one("#if-path", Input).value.strip()
        error_label = self.query_one("#if-error", Label)

        if not filepath:
            error_label.update("Please enter a file path.")
            return

        path = Path(filepath).expanduser()
        if not path.exists():
            error_label.update(f"File not found: {path}")
            return

        suffix = path.suffix.lower()

        try:
            if suffix in (".ofx", ".qfx"):
                self._import_ofx(path)
            elif suffix == ".csv":
                self._import_csv(path)
            elif suffix == ".xlsx":
                self._import_xlsx(path)
            else:
                error_label.update(f"Unsupported file type: {suffix}")
        except Exception as e:
            error_label.update(f"Parse error: {e}")

    def _import_ofx(self, path):
        from pyre.importers.ofx_importer import parse_ofx

        account_info, transactions = parse_ofx(path)

        if not transactions:
            self.query_one("#if-error", Label).update("No transactions found in file.")
            return

        # Try to auto-detect bank account
        bank_account = None
        if account_info:
            bank_account = find_account_by_ofx(
                self.con,
                account_info.get("bankid"),
                account_info.get("acctid"),
            )

        if bank_account:
            self._launch_review(path, transactions, bank_account["id"], account_info)
        else:
            # Need user to pick account
            def on_pick(result):
                if result:
                    account_id = result["account_id"]
                    if account_info:
                        set_account_ofx_mapping(
                            self.con, account_id,
                            account_info.get("bankid"),
                            account_info.get("acctid"),
                        )
                    self._launch_review(path, transactions, account_id, account_info)
                else:
                    self.dismiss(None)

            self.app.push_screen(
                AccountPickerScreen(self.con, "Select the bank account for this import:"),
                callback=on_pick,
            )

    def _import_csv(self, path):
        from pyre.importers.qb_journal_importer import detect_qb_journal

        if detect_qb_journal(path):
            self._import_qb_journal(path)
            return

        from pyre.importers.csv_importer import BANK_PROFILES, detect_bank_profile, parse_csv

        profile_key = detect_bank_profile(path)
        if profile_key:
            self._finish_csv_import(path, profile_key, parse_csv)
        else:
            # Auto-detection failed; let user pick the CSV format
            profile_names = {
                "wells_fargo": "Wells Fargo",
                "capital_one_cc": "Capital One CC",
                "us_bank": "US Bank",
                "brex_cc": "Brex Credit Card",
                "brex_cash": "Brex Cash",
            }
            options = [
                (profile_names.get(k, k), k) for k in BANK_PROFILES
            ]

            def on_profile(chosen):
                if chosen and chosen not in (Select.BLANK, Select.NULL):
                    self._finish_csv_import(path, chosen, parse_csv)
                else:
                    self.dismiss(None)

            self.app.push_screen(
                CsvProfilePickerScreen(options),
                callback=on_profile,
            )

    def _finish_csv_import(self, path, profile_key, parse_csv):
        transactions = parse_csv(path, profile_key)
        if not transactions:
            self.query_one("#if-error", Label).update("No transactions found in CSV.")
            return

        # CSV doesn't have OFX account info, ask user to pick
        def on_pick(result):
            if result:
                self._launch_review(path, transactions, result["account_id"], None)
            else:
                self.dismiss(None)

        self.app.push_screen(
            AccountPickerScreen(self.con, f"Select bank account for {path.name} ({profile_key}):"),
            callback=on_pick,
        )

    def _import_qb_journal(self, path):
        from pyre.importers.journal import build_account_path_map
        from pyre.importers.qb_journal_importer import (
            parse_qb_journals, resolve_accounts,
        )

        entries = parse_qb_journals(path)
        if not entries:
            self.query_one("#if-error", Label).update("No journal entries found in CSV.")
            return

        account_map = build_account_path_map(self.con)
        unmatched = resolve_accounts(entries, account_map)

        def on_review(result):
            self.dismiss(result)

        self.app.push_screen(
            JournalReviewScreen(self.con, str(path), entries, unmatched),
            callback=on_review,
        )

    def _import_xlsx(self, path):
        from pyre.importers.journal import build_account_path_map
        from pyre.importers.gusto_importer import (
            detect_gusto_gl,
            load_gusto_config,
            parse_gusto_gl,
            resolve_config_paths,
            resolve_gusto_accounts,
        )

        if not detect_gusto_gl(path):
            self.query_one("#if-error", Label).update(
                "Unrecognized XLSX format (expected Gusto General Ledger)."
            )
            return

        try:
            config = load_gusto_config()
        except FileNotFoundError as e:
            self.query_one("#if-error", Label).update(str(e))
            return

        entries = parse_gusto_gl(path)
        if not entries:
            self.query_one("#if-error", Label).update("No payroll entries found in file.")
            return

        # Resolve account paths from gusto.yaml to Pyre account IDs
        path_map = build_account_path_map(self.con)
        resolved_map, bad_paths = resolve_config_paths(
            config["account_map"], path_map,
        )
        if bad_paths:
            self.query_one("#if-error", Label).update(
                f"Unknown account paths in gusto.yaml: {', '.join(sorted(bad_paths))}"
            )
            return

        unmatched = resolve_gusto_accounts(entries, resolved_map)

        def on_review(result):
            self.dismiss(result)

        self.app.push_screen(
            JournalReviewScreen(
                self.con, str(path), entries, unmatched,
                title=f"Import Gusto Payroll: {path.name}",
            ),
            callback=on_review,
        )

    def _launch_review(self, path, transactions, bank_account_id, account_info):
        matches = match_transactions(self.con, transactions, bank_account_id)

        def on_review(result):
            self.dismiss(result)

        self.app.push_screen(
            ImportReviewScreen(self.con, str(path), matches, bank_account_id),
            callback=on_review,
        )


class JournalReviewScreen(ModalScreen):
    """Review screen for QuickBooks journal entry import."""

    BINDINGS = [
        Binding("escape", "cancel_import", "Cancel Import"),
        Binding("j", "nav_down", "Down", show=False),
        Binding("k", "nav_up", "Up", show=False),
        Binding("s", "skip", "Skip", show=False),
        Binding("d", "skip", "Skip", show=False),
        Binding("a", "accept_all", "Accept All", show=False),
        Binding("m", "peek", "Peek Splits", show=False),
        Binding("q", "finish", "Finish", show=False),
        Binding("enter", "accept", "Accept", show=False),
    ]

    DEFAULT_CSS = JOURNAL_REVIEW_CSS

    def __init__(self, con, source_file, entries, unmatched, title=None):
        super().__init__()
        self.con = con
        self.source_file = source_file
        self.entries = entries
        self.unmatched = unmatched
        self.title_text = title or f"Import QB Journals: {Path(source_file).name}"
        self.row_states = {}  # idx -> "OK" | "SKP"
        self._peek_toast = None
        # Pre-skip already-imported entries
        for idx, entry in enumerate(entries):
            if entry.hash and is_already_imported(con, fitid=None, hash_val=entry.hash):
                self.row_states[idx] = "SKP"

    def compose(self):
        with Vertical(id="jr-container"):
            yield Label(self.title_text, id="jr-title")
            yield Label("", id="jr-status")
            yield DataTable(id="jr-table")
            yield Label(
                "\\[J/K] Nav  \\[Enter] Accept  \\[S] Skip  "
                "\\[A] Accept All  \\[M] Peek Splits  "
                "\\[Q] Finish  \\[Esc] Cancel",
                id="jr-hint",
            )

    def on_mount(self):
        table = self.query_one("#jr-table", DataTable)
        table.cursor_type = "row"
        table.add_column("#", width=4)
        table.add_column("St", width=4)
        table.add_column("Date", width=12)
        table.add_column("Description")
        table.add_column("Splits", width=7)
        table.add_column("Debit Total", width=14)
        self._refresh_table()
        table.focus()
        self._update_status()

    def _entry_has_errors(self, idx):
        """True if any split in the entry has an unresolved account."""
        return any(s.account_id is None for s in self.entries[idx].splits)

    def _get_state(self, idx):
        if idx in self.row_states:
            return self.row_states[idx]
        if self._entry_has_errors(idx):
            return "ERR"
        return "NEW"

    _STATE_LABELS = {
        "NEW": "NEW", "OK": " OK", "SKP": "SKP", "ERR": "ERR",
    }
    _STATE_STYLE = {
        "NEW": "yellow", "OK": "bold green", "SKP": "dim", "ERR": "red",
    }

    def _styled(self, text, state):
        style = self._STATE_STYLE.get(state, "")
        return Text(str(text), style=style)

    def _refresh_table(self):
        table = self.query_one("#jr-table", DataTable)
        saved_row = table.cursor_row
        table.clear()
        for idx, entry in enumerate(self.entries):
            state = self._get_state(idx)
            debit_total = sum(s.amount_cents for s in entry.splits if s.amount_cents > 0)
            s = lambda t, st=state: self._styled(t, st)
            table.add_row(
                s(idx + 1),
                s(self._STATE_LABELS.get(state, state[:3])),
                s(format_date(entry.date)),
                s(entry.description),
                s(len(entry.splits)),
                s(fmt(debit_total)),
                key=str(idx),
            )
        if saved_row is not None and table.row_count > 0:
            table.move_cursor(row=min(saved_row, table.row_count - 1))

    def _update_status(self):
        total = len(self.entries)
        accepted = sum(1 for i in range(total) if self._get_state(i) == "OK")
        skipped = sum(1 for i in range(total) if self._get_state(i) == "SKP")
        errors = sum(1 for i in range(total) if self._get_state(i) == "ERR")
        new = sum(1 for i in range(total) if self._get_state(i) == "NEW")
        parts = [f"{total} entries:"]
        if new:
            parts.append(f"{new} new")
        if accepted:
            parts.append(f"{accepted} accepted")
        if skipped:
            parts.append(f"{skipped} skipped")
        if errors:
            parts.append(f"{errors} errors (unmatched accounts)")
        if self.unmatched:
            parts.append(f"Unmatched: {', '.join(sorted(self.unmatched))}")
        self.query_one("#jr-status", Label).update(", ".join(parts))

    def _current_row_idx(self):
        table = self.query_one("#jr-table", DataTable)
        if table.cursor_row is not None and table.row_count > 0:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            return int(row_key.value)
        return None

    @on(DataTable.RowHighlighted, "#jr-table")
    def on_jr_row_highlighted(self, event):
        self._dismiss_peek()

    @on(DataTable.RowSelected, "#jr-table")
    def on_jr_row_selected(self, event):
        self.action_accept()

    def _dismiss_peek(self):
        if self._peek_toast:
            self.app.clear_notifications()
            self._peek_toast = None

    def action_nav_down(self):
        self.query_one("#jr-table", DataTable).action_cursor_down()

    def action_nav_up(self):
        self.query_one("#jr-table", DataTable).action_cursor_up()

    def action_accept(self):
        idx = self._current_row_idx()
        if idx is None:
            return
        state = self._get_state(idx)
        if state == "ERR":
            self.notify("Cannot accept: entry has unmatched accounts", severity="warning")
            return
        if state == "OK":
            return
        self.row_states[idx] = "OK"
        self._refresh_table()
        self._update_status()
        self.query_one("#jr-table", DataTable).action_cursor_down()

    def action_skip(self):
        idx = self._current_row_idx()
        if idx is None:
            return
        state = self._get_state(idx)
        if state == "SKP":
            # Undo skip
            self.row_states.pop(idx, None)
        else:
            self.row_states[idx] = "SKP"
            self.query_one("#jr-table", DataTable).action_cursor_down()
        self._refresh_table()
        self._update_status()

    def action_accept_all(self):
        for idx in range(len(self.entries)):
            if self._get_state(idx) == "NEW":
                self.row_states[idx] = "OK"
        self._refresh_table()
        self._update_status()

    def action_peek(self):
        idx = self._current_row_idx()
        if idx is None:
            return
        entry = self.entries[idx]
        lines = [f"Date: {format_date(entry.date)}  {entry.description}"]
        for sp in entry.splits:
            name = sp.account_name
            if sp.account_id is None:
                name = f"{name} [UNMATCHED]"
            desc = f" ({sp.description})" if sp.description else ""
            lines.append(f"  {name}{desc}: {fmt(sp.amount_cents)}")
        balance = sum(sp.amount_cents for sp in entry.splits)
        if balance != 0:
            lines.append(f"  *** UNBALANCED by {fmt(balance)} ***")
        self.notify("\n".join(lines), severity="information", timeout=300)
        self._peek_toast = True

    def action_finish(self):
        committed = 0
        for idx, entry in enumerate(self.entries):
            if self._get_state(idx) != "OK":
                continue
            splits = [
                (sp.account_id, sp.amount_cents, sp.description)
                for sp in entry.splits
            ]
            try:
                tx_id = post_transaction(
                    self.con, entry.date, entry.description, splits,
                )
                if entry.hash:
                    log_import(
                        self.con, self.source_file,
                        fitid=None, hash_val=entry.hash,
                        tx_id=tx_id, status="imported",
                        account_id=None,
                    )
                committed += 1
            except Exception as e:
                log.exception(
                    "Journal import failed for entry %d (%s)",
                    idx + 1, entry.description,
                )
                self.notify(
                    f"Entry {idx + 1} failed: {e}",
                    severity="error", timeout=15,
                )
        self.dismiss({"committed": committed})

    def action_cancel_import(self):
        self.dismiss(None)


class CsvProfilePickerScreen(ModalScreen):
    """Modal to manually select a CSV bank profile when auto-detection fails."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = ACCOUNT_PICKER_CSS

    def __init__(self, options):
        super().__init__()
        self.options = options

    def compose(self):
        with Vertical(id="ap-dialog"):
            yield Label("Could not auto-detect CSV format. Select bank:", id="ap-title")
            yield Select(self.options, id="ap-select", allow_blank=True)
            with Horizontal(id="ap-buttons"):
                yield Button("OK", variant="primary", id="ap-ok")
                yield Button("Cancel", id="ap-cancel-btn")

    def on_mount(self):
        self.query_one("#ap-select", Select).focus()

    @on(Button.Pressed, "#ap-ok")
    def on_ok_pressed(self, event):
        sel = self.query_one("#ap-select", Select)
        if sel.value in (Select.BLANK, Select.NULL):
            return
        self.dismiss(sel.value)

    @on(Button.Pressed, "#ap-cancel-btn")
    def on_cancel_pressed(self, event):
        self.dismiss(None)

    def action_cancel(self):
        self.dismiss(None)


class AccountPickerScreen(ModalScreen):
    """Modal to pick a bank account for import."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = ACCOUNT_PICKER_CSS

    def __init__(self, con, prompt_text="Select account:"):
        super().__init__()
        self.con = con
        self.prompt_text = prompt_text

    def compose(self):
        options = _build_account_options(self.con)

        with Vertical(id="ap-dialog"):
            yield Label(self.prompt_text, id="ap-title")
            yield Select(options, id="ap-select", allow_blank=True)
            with Horizontal(id="ap-buttons"):
                yield Button("OK", variant="primary", id="ap-ok")
                yield Button("Cancel", id="ap-cancel-btn")

    def on_mount(self):
        self.query_one("#ap-select", Select).focus()

    @on(Button.Pressed, "#ap-ok")
    def on_ok_pressed(self, event):
        sel = self.query_one("#ap-select", Select)
        if sel.value in (Select.BLANK, Select.NULL):
            return
        self.dismiss({"account_id": sel.value})

    @on(Button.Pressed, "#ap-cancel-btn")
    def on_cancel_pressed(self, event):
        self.dismiss(None)

    def action_cancel(self):
        self.dismiss(None)


class AccountQuickPickScreen(ModalScreen):
    """Small modal with fuzzy-searchable account and optional vendor picker."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = ACCOUNT_PICKER_CSS

    def __init__(self, con):
        super().__init__()
        self.con = con
        self._vendor_options = []

    def compose(self):
        options = _build_account_options(self.con)
        self._vendor_options = [(v["name"], v["id"]) for v in get_all_vendors(self.con)]

        with Vertical(id="ap-dialog"):
            yield Label("Pick Account", id="ap-title")
            yield FuzzySelect(options, id="aqp-picker")
            yield Label("Vendor (optional):", classes="if-field-label", id="ap-vendor-label")
            yield Select(self._vendor_options, id="ap-vendor-select", allow_blank=True)
            with Horizontal(id="ap-buttons"):
                yield Button("OK", variant="primary", id="ap-ok")
                yield Button("Cancel", id="ap-cancel-btn")

    def on_mount(self):
        self.query_one("#aqp-picker", FuzzySelect).query_one(".fs-filter", Input).focus()

    @on(FuzzySelect.Selected, "#aqp-picker")
    def on_account_selected(self, event):
        self.query_one("#ap-vendor-select", Select).focus()

    @on(Button.Pressed, "#ap-ok")
    def on_ok_pressed(self, event):
        picker = self.query_one("#aqp-picker", FuzzySelect)
        if picker.value is not None:
            self._dismiss_with_selection(picker.value, picker.selected_label)

    def _dismiss_with_selection(self, account_id, account_name):
        vendor_sel = self.query_one("#ap-vendor-select", Select)
        vendor_id = None if vendor_sel.value in (Select.BLANK, Select.NULL) else vendor_sel.value
        self.dismiss({
            "account_id": account_id,
            "account_name": account_name or "?",
            "vendor_id": vendor_id,
        })

    @on(Button.Pressed, "#ap-cancel-btn")
    def on_cancel_pressed(self, event):
        self.dismiss(None)

    def action_cancel(self):
        self.dismiss(None)


class ImportReviewScreen(ModalScreen):
    """Main import review screen with DataTable."""

    BINDINGS = [
        Binding("escape", "cancel_import", "Cancel Import"),
        Binding("j", "nav_down", "Down", show=False),
        Binding("k", "nav_up", "Up", show=False),
        Binding("s", "skip", "Skip", show=False),
        Binding("d", "skip", "Skip", show=False),
        Binding("a", "accept_all", "Accept All", show=False),
        Binding("e", "edit_desc", "Edit Desc", show=False),
        Binding("m", "peek", "Peek Match", show=False),
        Binding("q", "finish", "Finish", show=False),
        Binding("tab", "pick_acct", "Pick Account", show=False),
        Binding("enter", "accept", "Accept", show=False),
    ]

    DEFAULT_CSS = IMPORT_REVIEW_CSS

    def __init__(self, con, source_file, match_results, bank_account_id):
        super().__init__()
        self.con = con
        self.source_file = source_file
        self.match_results = match_results
        self.bank_account_id = bank_account_id
        # Track per-row state: overrides for account_id, account_name, state
        self.row_overrides = {}  # idx -> {"account_id": ..., "account_name": ..., "state": ...}
        self.accepted_count = 0
        self._peek_toast = None  # active toast to dismiss on cursor move

    def compose(self):
        with Vertical(id="ir-container"):
            yield Label(f"Import: {Path(self.source_file).name}", id="ir-title")
            yield Label("", id="ir-status")
            yield DataTable(id="ir-table")
            yield Label(
                "\\[J/K] Nav  \\[Enter] Accept  \\[Tab] Account+Vendor  "
                "\\[S] Skip  \\[A] Accept All  \\[E] Edit Desc  "
                "\\[M] Peek  \\[Q] Finish  \\[Esc] Cancel",
                id="ir-hint",
            )

    def on_mount(self):
        table = self.query_one("#ir-table", DataTable)
        table.cursor_type = "row"
        table.add_column("#", width=4)
        table.add_column("St", width=4)
        table.add_column("Date", width=12)
        table.add_column("Description")
        table.add_column("Memo")
        table.add_column("Amount", width=14)
        table.add_column("Account")
        self._refresh_table()
        table.focus()
        self._update_status()

    def _get_row_state(self, idx):
        """Get effective state for a row (with overrides applied)."""
        mr = self.match_results[idx]
        overrides = self.row_overrides.get(idx, {})
        return overrides.get("state", mr.state)

    def _get_row_account_display(self, idx):
        """Get the account display string for a row."""
        mr = self.match_results[idx]
        overrides = self.row_overrides.get(idx, {})
        state = overrides.get("state", mr.state)

        if state == "MATCH":
            date_str = format_date(mr.matched_tx_date) if mr.matched_tx_date else ""
            desc_str = mr.matched_tx_desc or ""
            return f"-> {desc_str} ({date_str})"
        elif state in ("AUTO", "NEW", "OK"):
            acct_name = overrides.get("account_name") or mr.suggested_account_name
            return f"-> {acct_name}" if acct_name else "???"
        elif state == "SKIP" or state == "SKP":
            return "(skip)"
        return "???"

    def _state_label(self, state):
        return {
            "MATCH": "MTC",
            "AUTO": "AUT",
            "NEW": "NEW",
            "SKIP": "SKP",
            "OK": " OK",
            "SKP": "SKP",
        }.get(state, state[:3])

    _STATE_STYLE = {
        "MATCH": "green",
        "AUTO":  "cyan",
        "NEW":   "yellow",
        "SKIP":  "dim",
        "SKP":   "dim",
        "OK":    "bold green",
    }

    def _styled(self, text, state):
        """Wrap text in a Rich Text with the state's color."""
        style = self._STATE_STYLE.get(state, "")
        return Text(str(text), style=style)

    def _refresh_table(self):
        table = self.query_one("#ir-table", DataTable)
        saved_row = table.cursor_row
        table.clear()
        for idx, mr in enumerate(self.match_results):
            state = self._get_row_state(idx)
            amt_str = fmt(mr.imported_txn.amount_cents)
            acct_display = self._get_row_account_display(idx)
            overrides = self.row_overrides.get(idx, {})
            desc = overrides.get("description", mr.imported_txn.description)
            memo = mr.imported_txn.memo
            if memo == desc:
                memo = ""
            s = lambda t: self._styled(t, state)
            table.add_row(
                s(idx + 1),
                s(self._state_label(state)),
                s(format_date(mr.imported_txn.date)),
                s(desc),
                s(memo),
                s(amt_str),
                s(acct_display),
                key=str(idx),
            )
        if saved_row is not None and table.row_count > 0:
            table.move_cursor(row=min(saved_row, table.row_count - 1))

    def _update_status(self):
        total = len(self.match_results)
        skipped = sum(1 for i in range(total) if self._get_row_state(i) in ("SKIP", "SKP"))
        accepted = sum(1 for i in range(total) if self._get_row_state(i) == "OK")
        matched = sum(1 for i in range(total) if self._get_row_state(i) == "MATCH")
        auto = sum(1 for i in range(total) if self._get_row_state(i) == "AUTO")
        new = sum(1 for i in range(total) if self._get_row_state(i) == "NEW")
        status = (
            f"{total} transactions: {matched} matched, {auto} auto, "
            f"{new} new, {accepted} accepted, {skipped} skipped"
        )
        self.query_one("#ir-status", Label).update(status)

    @on(DataTable.RowHighlighted, "#ir-table")
    def on_ir_row_highlighted(self, event):
        self._dismiss_peek()

    @on(DataTable.RowSelected, "#ir-table")
    def on_ir_row_selected(self, event):
        self._accept_current()

    def action_nav_down(self):
        self.query_one("#ir-table", DataTable).action_cursor_down()

    def action_nav_up(self):
        self.query_one("#ir-table", DataTable).action_cursor_up()

    def action_skip(self):
        self._skip_current()

    def action_accept_all(self):
        self._accept_all()

    def action_edit_desc(self):
        self._edit_description()

    def action_peek(self):
        self._peek_match()

    def action_finish(self):
        self._finish()

    def action_pick_acct(self):
        self._pick_account()

    def action_accept(self):
        self._accept_current()

    def _current_row_idx(self):
        table = self.query_one("#ir-table", DataTable)
        if table.cursor_row is not None and table.row_count > 0:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            return int(row_key.value)
        return None

    def _accept_current(self):
        idx = self._current_row_idx()
        if idx is None:
            return
        state = self._get_row_state(idx)
        mr = self.match_results[idx]

        if state == "OK":
            return  # already accepted
        if state == "SKIP" or state == "SKP":
            return

        if state == "MATCH":
            self.row_overrides.setdefault(idx, {})["state"] = "OK"
        elif state == "AUTO":
            self.row_overrides.setdefault(idx, {})["state"] = "OK"
        elif state == "NEW":
            overrides = self.row_overrides.get(idx, {})
            if not overrides.get("account_id"):
                # Need to pick account first
                self._pick_account()
                return
            overrides["state"] = "OK"
            self.row_overrides[idx] = overrides

        self._refresh_table()
        self._update_status()
        # Move to next row
        table = self.query_one("#ir-table", DataTable)
        table.action_cursor_down()

    def _dismiss_peek(self):
        if self._peek_toast:
            self.app.clear_notifications()
            self._peek_toast = None

    def _skip_current(self):
        idx = self._current_row_idx()
        if idx is None:
            return
        state = self._get_row_state(idx)
        if state == "SKP":
            # Undo skip: restore original state
            overrides = self.row_overrides.get(idx, {})
            overrides.pop("state", None)
            if not overrides:
                self.row_overrides.pop(idx, None)
        else:
            self.row_overrides.setdefault(idx, {})["state"] = "SKP"
            table = self.query_one("#ir-table", DataTable)
            table.action_cursor_down()
        self._refresh_table()
        self._update_status()

    def _accept_all(self):
        """Accept all MATCH and AUTO rows at once."""
        for idx, mr in enumerate(self.match_results):
            state = self._get_row_state(idx)
            if state in ("MATCH", "AUTO"):
                self.row_overrides.setdefault(idx, {})["state"] = "OK"
        self._refresh_table()
        self._update_status()

    def _pick_account(self):
        idx = self._current_row_idx()
        if idx is None:
            return

        def on_pick(result):
            if result:
                overrides = self.row_overrides.setdefault(idx, {})
                overrides["account_id"] = result["account_id"]
                overrides["account_name"] = result["account_name"]
                if result.get("vendor_id"):
                    overrides["vendor_id"] = result["vendor_id"]
                overrides["state"] = "OK"
                self._refresh_table()
                self._update_status()
                table = self.query_one("#ir-table", DataTable)
                table.action_cursor_down()

        self.app.push_screen(AccountQuickPickScreen(self.con), callback=on_pick)

    def _edit_description(self):
        idx = self._current_row_idx()
        if idx is None:
            return
        mr = self.match_results[idx]
        current_desc = self.row_overrides.get(idx, {}).get(
            "description", mr.imported_txn.description
        )

        def on_edit(result):
            if result is not None:
                self.row_overrides.setdefault(idx, {})["description"] = result
                self._refresh_table()

        self.app.push_screen(EditDescriptionScreen(current_desc), callback=on_edit)

    def _peek_match(self):
        idx = self._current_row_idx()
        if idx is None:
            return
        mr = self.match_results[idx]
        if mr.state != "MATCH" or not mr.matched_tx_id:
            self.notify("No match to peek", severity="warning")
            return

        from pyre.models import get_transaction_detail
        tx, splits = get_transaction_detail(self.con, mr.matched_tx_id)
        if not tx:
            self.notify("Transaction not found", severity="error")
            return

        lines = [f"Date: {format_date(tx[1])}  Desc: {tx[2]}"]
        for s in splits:
            lines.append(f"  {s[2]}: {fmt(s[3])}")
        self.notify("\n".join(lines), severity="information", timeout=300)
        self._peek_toast = True

    def _finish(self):
        """Commit all accepted rows and dismiss."""
        committed = 0
        for idx, mr in enumerate(self.match_results):
            state = self._get_row_state(idx)
            overrides = self.row_overrides.get(idx, {})

            if state == "OK":
                if mr.state == "MATCH" and mr.matched_tx_id:
                    # Link to existing transaction, mark split as cleared
                    log_import(
                        self.con, self.source_file,
                        mr.imported_txn.fitid, mr.imported_txn.hash,
                        mr.matched_tx_id, "matched",
                        account_id=self.bank_account_id,
                    )
                    # Mark the bank split as cleared
                    self.con.execute(
                        "UPDATE splits SET reconcile = 'c' "
                        "WHERE tx_id = ? AND account_id = ?",
                        (mr.matched_tx_id, self.bank_account_id),
                    )
                    self.con.commit()
                    committed += 1
                else:
                    # Create new transaction (AUTO or NEW with account picked)
                    contra_id = overrides.get("account_id") or mr.suggested_account_id
                    if not contra_id:
                        continue

                    desc = overrides.get("description", mr.imported_txn.description)
                    amt = mr.imported_txn.amount_cents
                    vendor_id = overrides.get("vendor_id") or mr.suggested_vendor_id

                    try:
                        tx_id = post_transaction(
                            self.con, mr.imported_txn.date, desc,
                            [
                                (self.bank_account_id, amt),
                                (contra_id, -amt),
                            ],
                            vendor_id=vendor_id,
                        )
                        log_import(
                            self.con, self.source_file,
                            mr.imported_txn.fitid, mr.imported_txn.hash,
                            tx_id, "imported",
                            account_id=self.bank_account_id,
                        )
                        # Mark the bank split as cleared
                        self.con.execute(
                            "UPDATE splits SET reconcile = 'c' "
                            "WHERE tx_id = ? AND account_id = ?",
                            (tx_id, self.bank_account_id),
                        )
                        self.con.commit()
                        committed += 1
                    except Exception as e:
                        log.exception("Import failed for row %d (%s)", idx + 1, mr.imported_txn.description)
                        self.notify(
                            f"Row {idx + 1} failed: {e} (see pyre.log)",
                            severity="error",
                            timeout=15,
                        )
                        continue
                    # Learn payee rule for NEW rows (best-effort, non-critical)
                    if mr.state == "NEW" or (mr.state != "MATCH" and not mr.suggested_account_id):
                        pattern = _generalize_pattern(mr.imported_txn.description)
                        if pattern:
                            try:
                                create_payee_rule(self.con, pattern, contra_id,
                                                  vendor_id=vendor_id)
                            except Exception:
                                pass

            elif state in ("SKP", "SKIP"):
                # Log as skipped
                if mr.imported_txn.fitid or mr.imported_txn.hash:
                    try:
                        log_import(
                            self.con, self.source_file,
                            mr.imported_txn.fitid, mr.imported_txn.hash,
                            None, "skipped",
                            account_id=self.bank_account_id,
                        )
                    except Exception:
                        pass

        self.dismiss({"committed": committed})

    def action_cancel_import(self):
        self.dismiss(None)


class EditDescriptionScreen(ModalScreen):
    """Small modal to edit a transaction description."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = IMPORT_FILE_CSS

    def __init__(self, current_desc):
        super().__init__()
        self.current_desc = current_desc

    def compose(self):
        with Vertical(id="if-dialog"):
            yield Label("Edit Description", id="if-title")
            yield Input(value=self.current_desc, id="ed-input", classes="if-input")
            with Horizontal(id="if-buttons"):
                yield Button("Save", variant="primary", id="ed-save")
                yield Button("Cancel", id="ed-cancel-btn")

    def on_mount(self):
        inp = self.query_one("#ed-input", Input)
        inp.focus()

    @on(Input.Submitted, "#ed-input")
    def on_submitted(self, event):
        self.dismiss(self.query_one("#ed-input", Input).value.strip())

    @on(Button.Pressed, "#ed-save")
    def on_save(self, event):
        self.dismiss(self.query_one("#ed-input", Input).value.strip())

    @on(Button.Pressed, "#ed-cancel-btn")
    def on_cancel(self, event):
        self.dismiss(None)

    def action_cancel(self):
        self.dismiss(None)


class EditRuleScreen(ModalScreen):
    """Small modal to edit a payee rule pattern and optional memo pattern."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = IMPORT_FILE_CSS

    def __init__(self, con, current_pattern, current_memo_pattern="",
                 current_priority=0, current_vendor_id=None,
                 current_account_id=None):
        super().__init__()
        self.con = con
        self.current_pattern = current_pattern
        self.current_memo_pattern = current_memo_pattern or ""
        self.current_priority = current_priority
        self.current_vendor_id = current_vendor_id
        self.current_account_id = current_account_id

    def compose(self):
        vendors = get_all_vendors(self.con)
        vendor_options = [(v["name"], v["id"]) for v in vendors]

        by_id = {a["id"]: a for a in get_all_accounts(self.con)}
        acct_label = _account_path(by_id, self.current_account_id) or "Select account..."
        self._account_id = self.current_account_id

        with Vertical(id="if-dialog"):
            yield Label("Edit Rule", id="if-title")
            yield Label("Description pattern:", classes="if-field-label")
            yield Input(value=self.current_pattern, id="er-input", classes="if-input")
            yield Label("Memo pattern (optional):", classes="if-field-label")
            yield Input(value=self.current_memo_pattern, id="er-memo-input", classes="if-input")
            yield Label("Account:", classes="if-field-label")
            yield Button(acct_label, id="er-account-btn")
            yield Label("Priority (higher wins):", classes="if-field-label")
            yield Input(value=str(self.current_priority), id="er-priority-input", classes="if-input")
            yield Label("Vendor (optional):", classes="if-field-label")
            vendor_kwargs = {"allow_blank": True}
            if self.current_vendor_id:
                vendor_kwargs["value"] = self.current_vendor_id
            yield Select(
                vendor_options, id="er-vendor-select", **vendor_kwargs,
            )
            with Horizontal(id="if-buttons"):
                yield Button("Save", variant="primary", id="er-save")
                yield Button("Cancel", id="er-cancel-btn")

    def on_mount(self):
        inp = self.query_one("#er-input", Input)
        inp.focus()

    def _pick_account(self):
        from pyre.ui.screens import AccountFuzzyPickScreen

        def on_result(result):
            if result:
                self._account_id = result["account_id"]
                self.query_one("#er-account-btn", Button).label = result["account_name"]

        self.app.push_screen(AccountFuzzyPickScreen(self.con), on_result)

    def _save(self):
        pattern = self.query_one("#er-input", Input).value.strip()
        memo_pattern = self.query_one("#er-memo-input", Input).value.strip() or None
        account_id = self._account_id
        try:
            priority = int(self.query_one("#er-priority-input", Input).value.strip())
        except ValueError:
            priority = 0
        vendor_sel = self.query_one("#er-vendor-select", Select)
        vendor_id = vendor_sel.value if vendor_sel.value is not Select.BLANK and vendor_sel.value is not Select.NULL else None
        self.dismiss((pattern, memo_pattern, priority, vendor_id, account_id))

    @on(Input.Submitted, "#er-input")
    def on_submitted(self, event):
        self.query_one("#er-memo-input", Input).focus()

    @on(Input.Submitted, "#er-memo-input")
    def on_memo_submitted(self, event):
        self.query_one("#er-account-btn", Button).focus()

    @on(Button.Pressed, "#er-account-btn")
    def on_account_btn(self, event):
        self._pick_account()

    @on(Input.Submitted, "#er-priority-input")
    def on_priority_submitted(self, event):
        self.query_one("#er-vendor-select", Select).focus()

    @on(Button.Pressed, "#er-save")
    def on_save(self, event):
        self._save()

    @on(Button.Pressed, "#er-cancel-btn")
    def on_cancel(self, event):
        self.dismiss(None)

    def action_cancel(self):
        self.dismiss(None)


class PayeeRulesScreen(ModalScreen):
    """View and manage payee rules for auto-categorization."""

    BINDINGS = [
        Binding("j", "cursor_down", "Nav Down", show=False),
        Binding("k", "cursor_up", "Nav Up", show=False),
        Binding("e", "edit_rule", "Edit", show=False),
        Binding("d", "delete_rule", "Delete", show=False),
        Binding("escape", "dismiss_screen", "Close"),
        Binding("q", "dismiss_screen", "Close", show=False),
    ]

    DEFAULT_CSS = PAYEE_RULES_CSS

    def __init__(self, con):
        super().__init__()
        self.con = con

    def compose(self):
        with Vertical(id="pr-container"):
            yield Label("Payee Rules", id="pr-title")
            yield Label("", id="pr-status")
            yield DataTable(id="pr-table")
            yield Label(
                "\\[J/K] Nav  \\[E] Edit  \\[D] Delete  \\[Q/Esc] Close",
                id="pr-hint",
            )

    def on_mount(self):
        table = self.query_one("#pr-table", DataTable)
        table.cursor_type = "row"
        table.add_column("Pattern")
        table.add_column("Memo", width=20)
        table.add_column("Account", width=60)
        table.add_column("Vendor", width=20)
        table.add_column("Pri", width=4)
        self._refresh_table()
        table.focus()

    def _refresh_table(self):
        table = self.query_one("#pr-table", DataTable)
        saved_row = table.cursor_row
        table.clear()

        rules = get_payee_rules(self.con)
        by_id = {a["id"]: a for a in get_all_accounts(self.con)}
        vendors = {v["id"]: v["name"] for v in get_all_vendors(self.con)}

        for r in rules:
            acct_name = _account_path(by_id, r["account_id"]) or r["account_id"]
            vendor_name = vendors.get(r["vendor_id"], "") if r["vendor_id"] else ""
            table.add_row(
                r["pattern"],
                r["memo_pattern"] or "",
                acct_name,
                vendor_name,
                str(r["priority"]),
                key=r["id"],
            )

        if saved_row is not None and table.row_count > 0:
            table.move_cursor(row=min(saved_row, table.row_count - 1))

        self.query_one("#pr-status", Label).update(f"{len(rules)} rules")

    def action_cursor_down(self):
        self.query_one("#pr-table", DataTable).action_cursor_down()

    def action_cursor_up(self):
        self.query_one("#pr-table", DataTable).action_cursor_up()

    def action_edit_rule(self):
        self._edit_current()

    def action_delete_rule(self):
        self._delete_current()

    def on_data_table_row_selected(self, event):
        self._edit_current()

    def _get_current_rule_id(self):
        table = self.query_one("#pr-table", DataTable)
        if table.cursor_row is None or table.row_count == 0:
            return None
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        return str(row_key.value)

    def _edit_current(self):
        rule_id = self._get_current_rule_id()
        if not rule_id:
            return
        # Find the rule to get current pattern, memo_pattern, vendor_id
        rules = get_payee_rules(self.con)
        rule = next((r for r in rules if r["id"] == rule_id), None)
        if not rule:
            return
        current_pattern = rule["pattern"]
        current_memo = rule["memo_pattern"] or ""
        current_priority = rule["priority"]
        current_vendor_id = rule["vendor_id"]
        current_account_id = rule["account_id"]

        def on_edit_result(result):
            if result:
                pattern, memo_pattern, priority, vendor_id, account_id = result
                update_payee_rule(self.con, rule_id, pattern,
                                  memo_pattern=memo_pattern, priority=priority,
                                  vendor_id=vendor_id, account_id=account_id)
                self._refresh_table()
                self.notify("Rule updated")

        self.app.push_screen(
            EditRuleScreen(self.con, current_pattern, current_memo,
                           current_priority, current_vendor_id,
                           current_account_id),
            on_edit_result,
        )

    def _delete_current(self):
        rule_id = self._get_current_rule_id()
        if not rule_id:
            return
        delete_payee_rule(self.con, rule_id)
        self._refresh_table()
        self.notify("Rule deleted", severity="warning")

    def action_dismiss_screen(self):
        self.dismiss(None)
