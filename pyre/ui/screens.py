from datetime import date
from decimal import InvalidOperation
from pathlib import Path

from textual import on
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalGroup, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.fuzzy import Matcher
from textual.widgets import Button, DataTable, Input, Label, OptionList, Select, Switch, Tree
from textual.widgets.option_list import Option

from rich.text import Text

from pyre.db import TYPE_FAMILY
from pyre.account_models import (
    account_path,
    get_all_accounts,
    create_account,
    update_account,
    delete_account,
    get_child_count,
    get_transaction_count,
    toggle_sidebar,
)
from pyre.account_utils import (
    ACCOUNT_CATEGORIES,
    get_account_category,
    get_all_account_types,
    normal_balance_direction,
    slugify,
)
from pyre.dates import DateInput, parse_date
from pyre.formatting import cents, fmt, format_date, format_date_long
from pyre.models import (
    get_account_balance,
    is_transaction_reconciled,
    post_transaction,
    get_transaction_detail,
    update_transaction,
    update_transaction_metadata,
    delete_transaction,
)
from pyre.reports import (
    generate_pnl, export_pnl_pdf,
    generate_balance_sheet, export_balance_sheet_pdf,
    generate_trial_balance,
    generate_cash_flow, export_cash_flow_pdf,
    generate_expenses_by_vendor, export_expenses_by_vendor_pdf,
    generate_reconciliation_report, export_reconciliation_report_pdf,
    resolve_report_path,
)
from pyre.vendor_models import (
    get_all_vendors,
    get_vendor_by_id,
    create_vendor,
    update_vendor,
    delete_vendor,
    get_vendor_transaction_count,
)
from pyre.models import get_all_reconciliations
from pyre.ui.styles import (
    QUICK_ENTRY_CSS,
    PROFIT_LOSS_CSS,
    CASH_FLOW_CSS,
    BALANCE_SHEET_CSS,
    TRIAL_BALANCE_CSS,
    CHART_OF_ACCOUNTS_CSS,
    ACCOUNT_FORM_CSS,
    CONFIRM_DELETE_CSS,
    CONFIRM_DELETE_TX_CSS,
    CONFIRM_OVERWRITE_CSS,
    REPORT_DATE_CSS,
    ADD_TRANSACTION_CSS,
    VENDOR_LIST_CSS,
    VENDOR_FORM_CSS,
    EXPENSES_BY_VENDOR_CSS,
    CONFIRM_DELETE_VENDOR_CSS,
    SAVE_PDF_CSS,
    ACCOUNT_FUZZY_PICK_CSS,
    BULK_EDIT_CSS,
    RECONCILIATION_PICKER_CSS,
    RECONCILIATION_REPORT_CSS,
)


def _save_report_pdf(screen, output_path, export_fn):
    """Shared save-with-overwrite-confirm logic for all report screens.

    screen: the ModalScreen instance (provides self.app)
    output_path: resolved Path for the PDF
    export_fn: callable(color: bool) that writes the PDF
    """
    def on_choice(result):
        if result is None:
            return

        def do_save(confirmed=True):
            if not confirmed:
                return
            try:
                export_fn(str(output_path), result == "color")
                screen.app.notify(
                    f"Saved to {output_path}", severity="information", timeout=5,
                )
            except Exception as e:
                screen.app.notify(f"Error saving PDF: {e}", severity="error")

        if output_path.exists():
            screen.app.push_screen(
                ConfirmOverwriteScreen(output_path), callback=do_save,
            )
        else:
            do_save()

    screen.app.push_screen(SavePdfDialog(), callback=on_choice)


class QuickEntryScreen(ModalScreen):
    """Modal for entering a quick-function transaction with split items."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = QUICK_ENTRY_CSS

    def __init__(self, qf, con):
        super().__init__()
        self.qf = qf
        self.con = con
        self.fixed_splits = qf.get("fixed_splits", False)
        prompted = [(i, s) for i, s in enumerate(qf["splits"]) if s.get("prompt")]
        if self.fixed_splits:
            # All prompted splits shown as labeled amount fields, no item rows
            self.item_split_def = None
            self.extra_splits = prompted
        else:
            # First prompted split = "item" (can be duplicated with descriptions).
            # Remaining prompted splits = "extras" (single amount fields).
            self.item_split_def = prompted[0][1] if prompted else None
            self.extra_splits = prompted[1:]
        self._next_item_id = 1
        self._alive_items = [0]
        # Pre-populate pick_account defaults from YAML
        self._pick_account_ids = {}
        for idx, s in enumerate(qf["splits"]):
            if s.get("pick_account") and not s.get("prompt"):
                self._pick_account_ids[idx] = s["account"]

    def compose(self):
        # Build account lookup for full hierarchy labels
        all_accounts = get_all_accounts(self.con)
        by_id = {a["id"]: a for a in all_accounts}

        with Vertical(id="qe-dialog"):
            yield Label(f"\u26a1 {self.qf['label']}", id="qe-title")
            yield Label(self.qf["description"], id="qe-desc")

            # Date field
            yield Label("Date:", classes="qe-field-label")
            yield DateInput(
                value=format_date(date.today().isoformat()),
                placeholder="M/D, M/D/YY, or MM-DD-YYYY",
                id="qe-date",
                classes="qe-input",
            )

            # Item rows: each has description + amount on the same row
            if self.item_split_def:
                item_label = account_path(by_id, self.item_split_def["account"]) or self.item_split_def["prompt"]
                yield Label(f"{item_label}:", classes="qe-field-label")
                with Vertical(id="qe-items-container"):
                    with Horizontal(classes="qe-item-row", id="qe-item-row-0"):
                        yield Input(
                            value=self.qf["description"],
                            id="qe-item-desc-0",
                            classes="qe-item-desc",
                        )
                        yield Input(
                            placeholder="0.00",
                            id="qe-item-amount-0",
                            classes="qe-item-amount",
                        )
                        yield Button(
                            "X",
                            id="qe-item-remove-0",
                            classes="qe-item-remove",
                            disabled=True,
                        )
                with Horizontal(id="qe-add-item-row"):
                    yield Button("+ Add Item", id="qe-add-item")

            # Extra amount fields (sales tax, shipping, etc.)
            if self.extra_splits:
                with Horizontal(id="qe-extras-row"):
                    for orig_idx, split in self.extra_splits:
                        with Vertical(classes="qe-amount-group"):
                            extra_label = account_path(by_id, split["account"]) or split["prompt"]
                            yield Label(f"{extra_label}:", classes="qe-field-label")
                            yield Input(
                                placeholder="0.00",
                                id=f"qe-extra-{orig_idx}",
                                classes="qe-amount-field",
                            )

            # Show auto-balance account(s)
            auto_splits = [
                (i, s) for i, s in enumerate(self.qf["splits"])
                if not s.get("prompt")
            ]
            if auto_splits:
                for idx, s in auto_splits:
                    row = self.con.execute(
                        "SELECT name FROM accounts WHERE id = ?", (s["account"],)
                    ).fetchone()
                    name = row[0] if row else s["account"]
                    if s.get("pick_account"):
                        yield Button(
                            f"From: {name}",
                            id=f"qe-pick-account-{idx}",
                            classes="qe-pick-account",
                        )
                    else:
                        yield Label(f"From: {name}", id=f"qe-from-{idx}", classes="qe-from")

            yield Label("", id="qe-status")
            yield Label("", id="qe-error")
            with Horizontal(id="qe-buttons"):
                yield Button("Post", variant="primary", id="qe-post")
                yield Button("Cancel", id="qe-cancel-btn")

    def on_mount(self):
        self.query_one("#qe-date", Input).focus()

    def _update_total(self):
        total = 0
        if self.item_split_def:
            for item_id in self._alive_items:
                val = self.query_one(f"#qe-item-amount-{item_id}", Input).value.strip()
                if val:
                    try:
                        total += cents(val)
                    except (ValueError, InvalidOperation):
                        pass
        for orig_idx, _split in self.extra_splits:
            val = self.query_one(f"#qe-extra-{orig_idx}", Input).value.strip()
            if val:
                try:
                    total += cents(val)
                except (ValueError, InvalidOperation):
                    pass
        self.query_one("#qe-status", Label).update(f"Total: {fmt(total)}")

    @on(Input.Changed)
    def on_input_changed(self, event):
        inp_id = event.input.id
        if inp_id and (
            inp_id.startswith("qe-item-amount-") or inp_id.startswith("qe-extra-")
        ):
            self._update_total()

    @on(Input.Submitted)
    def handle_submit(self, event):
        inp_id = event.input.id
        if inp_id and inp_id.startswith("qe-item-desc-"):
            # Enter on description -> move to its amount field
            idx = inp_id.split("-")[-1]
            self.query_one(f"#qe-item-amount-{idx}", Input).focus()
        else:
            self._post()

    def on_key(self, event):
        if event.key == "space":
            focused = self.screen.focused
            if isinstance(focused, Button) and focused.id == "qe-add-item":
                event.prevent_default()
                event.stop()
                self._add_item()

    @on(Button.Pressed)
    def on_button_pressed(self, event):
        btn_id = event.button.id
        if not btn_id:
            return
        if btn_id == "qe-post":
            self._post()
        elif btn_id == "qe-cancel-btn":
            self.dismiss(False)
        elif btn_id == "qe-add-item":
            self._add_item()
        elif btn_id.startswith("qe-pick-account-"):
            idx = int(btn_id.split("-")[-1])
            self._pick_auto_account(idx)
        elif btn_id.startswith("qe-item-remove-"):
            idx = int(btn_id.split("-")[-1])
            self._remove_item(idx)

    def _pick_auto_account(self, idx):
        def on_pick(result):
            if result:
                acct_id = result["account_id"]
                acct_name = result["account_name"]
                self._pick_account_ids[idx] = acct_id
                self.query_one(f"#qe-pick-account-{idx}", Button).label = f"From: {acct_name}"

        self.app.push_screen(AccountFuzzyPickScreen(self.con), on_pick)

    def _add_item(self):
        i = self._next_item_id
        self._next_item_id += 1
        self._alive_items.append(i)

        container = self.query_one("#qe-items-container")
        row = Horizontal(classes="qe-item-row", id=f"qe-item-row-{i}")
        container.mount(row)
        row.mount(Input(
            placeholder="Description",
            id=f"qe-item-desc-{i}",
            classes="qe-item-desc",
        ))
        row.mount(Input(
            placeholder="0.00",
            id=f"qe-item-amount-{i}",
            classes="qe-item-amount",
        ))
        row.mount(Button(
            "X",
            id=f"qe-item-remove-{i}",
            classes="qe-item-remove",
        ))
        self._update_item_remove_buttons()
        self.query_one(f"#qe-item-desc-{i}", Input).focus()

    def _remove_item(self, idx):
        if len(self._alive_items) <= 1:
            return
        row = self.query_one(f"#qe-item-row-{idx}")
        row.remove()
        self._alive_items.remove(idx)
        self._update_item_remove_buttons()
        self._update_total()

    def _update_item_remove_buttons(self):
        for item_id in self._alive_items:
            try:
                btn = self.query_one(f"#qe-item-remove-{item_id}", Button)
                btn.disabled = len(self._alive_items) <= 1
            except Exception:
                continue

    def _post(self):
        """Post the transaction."""
        try:
            dt = parse_date(self.query_one("#qe-date", Input).value)

            # Collect item descriptions and amounts
            descriptions = []
            splits = []
            if self.item_split_def:
                for item_id in self._alive_items:
                    desc = self.query_one(f"#qe-item-desc-{item_id}", Input).value.strip()
                    amount_str = self.query_one(f"#qe-item-amount-{item_id}", Input).value.strip()
                    if not amount_str:
                        self.query_one("#qe-error", Label).update("All item amounts are required.")
                        return
                    amt = cents(amount_str)
                    if self.item_split_def["direction"] == "credit":
                        amt = -amt
                    splits.append((self.item_split_def["account"], amt))
                    if desc:
                        descriptions.append(desc)

            running_total = sum(s[1] for s in splits)

            # Extra splits (sales tax, shipping, etc.)
            for orig_idx, split_def in self.extra_splits:
                val = self.query_one(f"#qe-extra-{orig_idx}", Input).value.strip()
                if not val:
                    self.query_one("#qe-error", Label).update("All amount fields are required.")
                    return
                amt = cents(val)
                if split_def["direction"] == "credit":
                    amt = -amt
                splits.append((split_def["account"], amt))
                running_total += amt

            # Fixed-amount splits and auto-balance split(s)
            for split_idx, split_def in enumerate(self.qf["splits"]):
                if not split_def.get("prompt"):
                    account_id = split_def["account"]
                    if split_def.get("pick_account"):
                        if split_idx not in self._pick_account_ids:
                            self.query_one("#qe-error", Label).update(
                                "Please select an account."
                            )
                            return
                        account_id = self._pick_account_ids[split_idx]
                    if "amount" in split_def:
                        amt = split_def["amount"]
                        if split_def["direction"] == "credit":
                            amt = -amt
                        splits.append((account_id, amt))
                        running_total += amt
                    else:
                        splits.append((account_id, -running_total))

            description = "; ".join(descriptions) if descriptions else self.qf["description"]
            vendor_id = self.qf.get("vendor")
            post_transaction(self.con, dt, description, splits, vendor_id=vendor_id)
            self.dismiss(True)

        except Exception as e:
            self.query_one("#qe-error", Label).update(f"Error: {e}")

    def action_cancel(self):
        self.dismiss(False)


class AccountFuzzyPickScreen(ModalScreen):
    """Fuzzy-search modal for picking an account from a large list."""

    BINDINGS = [
        Binding("j", "cursor_down", "Nav Down", show=False),
        Binding("k", "cursor_up", "Nav Up", show=False),
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = ACCOUNT_FUZZY_PICK_CSS

    def __init__(self, con):
        super().__init__()
        self.con = con
        self._all_options = []
        self._id_by_index = {}
        self._type_by_id = {}

    def compose(self):
        from pyre.ui.import_screen import _build_account_options
        self._all_options = _build_account_options(self.con)
        for a in get_all_accounts(self.con):
            self._type_by_id[a["id"]] = a["type"]

        with Vertical(id="afp-dialog"):
            yield Label("Pick Account", id="afp-title")
            yield Input(placeholder="Type to filter...", id="afp-filter")
            option_list = OptionList(id="afp-results")
            yield option_list
            yield Label("Enter=select  Esc=cancel", id="afp-hint")

    def on_mount(self):
        self._refresh_options("")
        # Size dialog to fit longest account label (+ padding/border)
        max_label = max((len(lbl) for lbl, _ in self._all_options), default=40)
        width = min(max(max_label + 10, 60), self.app.size.width * 65 // 100)
        self.query_one("#afp-dialog").styles.width = width
        self.query_one("#afp-filter", Input).focus()

    def _refresh_options(self, query):
        ol = self.query_one("#afp-results", OptionList)
        ol.clear_options()
        self._id_by_index = {}
        if query:
            matcher = Matcher(query)
            scored = []
            for label, aid in self._all_options:
                score = matcher.match(label)
                if score > 0:
                    scored.append((score, label, aid))
            scored.sort(key=lambda x: x[0], reverse=True)
            for idx, (score, label, aid) in enumerate(scored):
                highlight = matcher.highlight(label)
                ol.add_option(Option(highlight, id=aid))
                self._id_by_index[idx] = aid
        else:
            for idx, (label, aid) in enumerate(self._all_options):
                ol.add_option(Option(Text(label), id=aid))
                self._id_by_index[idx] = aid
        if self._id_by_index:
            ol.highlighted = 0

    @on(Input.Changed, "#afp-filter")
    def on_filter_changed(self, event):
        self._refresh_options(event.value.strip())

    @on(Input.Submitted, "#afp-filter")
    def on_filter_submitted(self, event):
        ol = self.query_one("#afp-results", OptionList)
        if len(self._id_by_index) == 1:
            self._select_highlighted()
        else:
            ol.focus()

    def action_cursor_down(self):
        self.query_one("#afp-results", OptionList).action_cursor_down()

    def action_cursor_up(self):
        self.query_one("#afp-results", OptionList).action_cursor_up()

    @on(OptionList.OptionSelected, "#afp-results")
    def on_option_selected(self, event):
        self._select_highlighted()

    def _select_highlighted(self):
        ol = self.query_one("#afp-results", OptionList)
        idx = ol.highlighted
        if idx is not None and idx in self._id_by_index:
            aid = self._id_by_index[idx]
            name = None
            for label, oid in self._all_options:
                if oid == aid:
                    name = label
                    break
            atype = self._type_by_id.get(aid, "asset")
            self.dismiss({"account_id": aid, "account_name": name or "?", "account_type": atype})

    def action_cancel(self):
        self.dismiss(None)


class TransactionFormBase(ModalScreen):
    """Base class for transaction add/edit screens with split-editing UI."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save", show=False),
        Binding("ctrl+d", "toggle_descs", "Descriptions", show=False),
    ]

    DEFAULT_CSS = ADD_TRANSACTION_CSS

    def __init__(self, con):
        super().__init__()
        self.con = con
        self._next_split_id = 0
        self._alive_splits = []
        self.split_directions = {}
        self._memos_visible = False
        self._split_account_ids = {}
        self._split_account_types = {}
        self._user_touched_dir = set()
        self._user_touched_amount = set()
        self._programmatic_amount = set()

    def _base_mount(self):
        self.query_one("#at-date", Input).focus()
        self._update_balance()

    def action_save(self):
        self._save()

    def action_toggle_descs(self):
        self._toggle_memos()

    def action_cancel(self):
        self.dismiss(None)

    def _save(self):
        raise NotImplementedError

    def _update_balance(self):
        total = 0
        for i in self._alive_splits:
            inp = self.query_one(f"#at-split-amount-{i}", Input)
            val = inp.value.strip()
            if val:
                try:
                    c = cents(val)
                    if self.split_directions.get(i) == "CR":
                        c = -c
                    total += c
                except (ValueError, InvalidOperation):
                    pass
        label = self.query_one("#at-balance", Label)
        if total == 0:
            label.update("Balanced")
            label.remove_class("at-unbalanced")
            label.add_class("at-balanced")
            self.query_one("#at-error", Label).update("")
        else:
            label.update(f"Off by {fmt(total)}")
            label.remove_class("at-balanced")
            label.add_class("at-unbalanced")
        try:
            self.query_one("#at-save", Button).disabled = (total != 0)
        except Exception:
            pass

    def _update_remove_buttons(self):
        for i in self._alive_splits:
            try:
                btn = self.query_one(f"#at-split-remove-{i}", Button)
                btn.disabled = len(self._alive_splits) <= 2
            except Exception:
                continue

    def on_key(self, event):
        if event.key == "space":
            focused = self.screen.focused
            if isinstance(focused, Button) and focused.id == "at-add-split":
                event.prevent_default()
                event.stop()
                self._add_split()

    @on(Input.Changed)
    def on_input_changed(self, event):
        if event.input.id and event.input.id.startswith("at-split-amount-"):
            idx = int(event.input.id.split("-")[-1])
            if idx in self._programmatic_amount:
                self._programmatic_amount.discard(idx)
            else:
                self._user_touched_amount.add(idx)
                self._update_balance()
                self._auto_fill_last_split()
                return
            self._update_balance()

    @on(Button.Pressed)
    def on_button_pressed(self, event):
        btn_id = event.button.id
        if not btn_id:
            return
        if btn_id == "at-save":
            self._save()
        elif btn_id == "at-cancel-btn":
            self.dismiss(None)
        elif btn_id == "at-delete":
            if hasattr(self, '_delete'):
                self._delete()
        elif btn_id == "at-add-split":
            self._add_split()
        elif btn_id == "at-toggle-memos":
            self._toggle_memos()
        elif btn_id.startswith("at-split-account-"):
            idx = int(btn_id.split("-")[-1])
            self._pick_account(idx)
        elif btn_id.startswith("at-split-dir-"):
            idx = int(btn_id.split("-")[-1])
            self._toggle_direction(idx)
        elif btn_id.startswith("at-split-remove-"):
            idx = int(btn_id.split("-")[-1])
            self._remove_split(idx)

    @on(Input.Submitted)
    def handle_submit(self, event):
        self._save()

    def _pick_account(self, idx):
        def on_result(result):
            if result:
                self._split_account_ids[idx] = result["account_id"]
                self._split_account_types[idx] = result["account_type"]
                btn = self.query_one(f"#at-split-account-{idx}", Button)
                btn.label = result["account_name"]
                self._set_direction_for_account(idx, result["account_type"])
                self.query_one(f"#at-split-amount-{idx}", Input).focus()
        self.app.push_screen(AccountFuzzyPickScreen(self.con), on_result)

    def _toggle_memos(self):
        self._memos_visible = not self._memos_visible
        for row in self.query(".at-split-memo-row"):
            if self._memos_visible:
                row.remove_class("hidden")
            else:
                row.add_class("hidden")
        try:
            btn = self.query_one("#at-toggle-memos", Button)
            btn.label = "- Desc" if self._memos_visible else "+ Desc"
        except NoMatches:
            pass

    def _toggle_direction(self, idx):
        self._user_touched_dir.add(idx)
        current = self.split_directions.get(idx, "DR")
        new_dir = "CR" if current == "DR" else "DR"
        self.split_directions[idx] = new_dir
        self.query_one(f"#at-split-dir-{idx}", Button).label = new_dir
        self._update_balance()

    def _set_direction_for_account(self, idx, account_type):
        if idx in self._user_touched_dir:
            return
        direction = normal_balance_direction(account_type)
        self.split_directions[idx] = direction
        try:
            self.query_one(f"#at-split-dir-{idx}", Button).label = direction
        except NoMatches:
            pass
        self._update_balance()
        self._auto_fill_last_split()

    def _auto_fill_last_split(self):
        if len(self._alive_splits) < 2:
            return
        last = self._alive_splits[-1]
        if last in self._user_touched_amount:
            return
        # Sum all splits except the last
        total = 0
        for i in self._alive_splits[:-1]:
            inp = self.query_one(f"#at-split-amount-{i}", Input)
            val = inp.value.strip()
            if val:
                try:
                    c = cents(val)
                    if self.split_directions.get(i) == "CR":
                        c = -c
                    total += c
                except (ValueError, InvalidOperation):
                    pass
        if total == 0:
            return
        # Set last split to balance: opposite of the running total
        amount = abs(total)
        direction = "CR" if total > 0 else "DR"
        if last not in self._user_touched_dir:
            self.split_directions[last] = direction
            try:
                self.query_one(f"#at-split-dir-{last}", Button).label = direction
            except NoMatches:
                pass
        amount_input = self.query_one(f"#at-split-amount-{last}", Input)
        self._programmatic_amount.add(last)
        amount_input.value = f"{amount / 100:.2f}"
        self._update_balance()

    def _add_split(self):
        i = self._next_split_id
        self._next_split_id += 1
        self.split_directions[i] = "DR"
        self._split_account_ids[i] = None
        self._alive_splits.append(i)

        container = self.query_one("#at-splits-container")
        row = Horizontal(classes="at-split-row", id=f"at-split-row-{i}")
        container.mount(row)
        row.mount(Button(
            "Select account...",
            id=f"at-split-account-{i}", classes="at-split-account",
        ))
        row.mount(Input(
            placeholder="0.00",
            id=f"at-split-amount-{i}", classes="at-split-amount at-input",
        ))
        row.mount(Button("DR", id=f"at-split-dir-{i}", classes="at-split-dir"))
        row.mount(Button("X", id=f"at-split-remove-{i}", classes="at-split-remove"))
        memo_classes = "at-split-memo-row" + ("" if self._memos_visible else " hidden")
        memo_row = Horizontal(classes=memo_classes, id=f"at-split-memo-{i}")
        container.mount(memo_row)
        memo_row.mount(Input(placeholder="Description (optional)", id=f"at-split-memo-input-{i}"))
        self._update_remove_buttons()
        self._update_balance()
        self._pick_account(i)

    def _remove_split(self, idx):
        if len(self._alive_splits) <= 2:
            return
        self.query_one(f"#at-split-row-{idx}").remove()
        try:
            self.query_one(f"#at-split-memo-{idx}").remove()
        except NoMatches:
            pass
        del self.split_directions[idx]
        self._split_account_ids.pop(idx, None)
        self._split_account_types.pop(idx, None)
        self._user_touched_dir.discard(idx)
        self._user_touched_amount.discard(idx)
        self._alive_splits.remove(idx)
        self._update_remove_buttons()
        self._update_balance()


class EditTransactionScreen(TransactionFormBase):
    """Modal for editing an existing transaction with full split editing."""

    def __init__(self, tx_id, con):
        super().__init__(con)
        self.tx_id = tx_id
        self.tx = None
        self.orig_splits = []
        self._reconciled = False
        self._has_reconciled = False
        self._reconciled_split_ids = set()

    def compose(self):
        self.tx, self.orig_splits = get_transaction_detail(self.con, self.tx_id)
        if not self.tx:
            yield Label("Transaction not found")
            return

        from pyre.ui.import_screen import _build_account_options
        acct_labels = {aid: lbl for lbl, aid in _build_account_options(self.con)}

        # Determine per-split reconciliation status
        rec_rows = self.con.execute(
            "SELECT id FROM splits WHERE tx_id = ? AND reconcile = 'r'",
            (self.tx_id,),
        ).fetchall()
        self._reconciled_split_ids = {r[0] for r in rec_rows}
        self._has_reconciled = len(self._reconciled_split_ids) > 0
        all_reconciled = len(self._reconciled_split_ids) == len(self.orig_splits)
        self._reconciled = all_reconciled
        _, tx_date, tx_desc, tx_memo, tx_vendor_id = self.tx

        if self._reconciled:
            # All splits reconciled -- metadata-only edit
            vendor_options = [(v["name"], v["id"]) for v in get_all_vendors(self.con)]
            with VerticalScroll(id="at-dialog"):
                yield Label("Edit Transaction (Reconciled)", id="at-title")
                yield Label(
                    "Amounts, accounts, and date are locked.",
                    id="at-error",
                )
                yield Label(f"Date: {format_date(tx_date)}", classes="at-field-label")

                if vendor_options:
                    yield Label("Vendor:", classes="at-field-label")
                    vendor_val = tx_vendor_id if tx_vendor_id else Select.NULL
                    yield Select(vendor_options, value=vendor_val, allow_blank=True, id="at-vendor", classes="at-input")

                yield Label("Description:", classes="at-field-label")
                yield Input(value=tx_desc, id="at-desc", classes="at-input")

                yield Label("Splits:", classes="at-field-label")
                for i, (_sid, acct_id, acct_name, amount, split_desc) in enumerate(self.orig_splits):
                    direction = "DR" if amount > 0 else "CR"
                    display_name = acct_labels.get(acct_id, acct_name)
                    yield Label(
                        f"  {display_name}  {fmt(abs(amount))}  {direction}",
                        classes="at-field-label",
                        shrink=True,
                    )
                    memo_classes = "at-split-memo-row" + ("" if split_desc else " hidden")
                    with Horizontal(classes=memo_classes, id=f"at-split-memo-{i}"):
                        yield Input(value=split_desc, placeholder="Description (optional)", id=f"at-split-memo-input-{i}")
                with Horizontal(id="at-buttons"):
                    yield Button("Save", variant="primary", id="at-save")
                    yield Button("Cancel", id="at-cancel-btn")
            return

        if self._has_reconciled:
            # Partial -- some splits reconciled, some not
            vendor_options = [(v["name"], v["id"]) for v in get_all_vendors(self.con)]
            with VerticalScroll(id="at-dialog"):
                yield Label("Edit Transaction (Partially Reconciled)", id="at-title")
                yield Label(
                    "Reconciled splits are locked. Unreconciled accounts can be changed.",
                    id="at-error",
                )
                yield Label(f"Date: {format_date(tx_date)}", classes="at-field-label")

                if vendor_options:
                    yield Label("Vendor:", classes="at-field-label")
                    vendor_val = tx_vendor_id if tx_vendor_id else Select.NULL
                    yield Select(vendor_options, value=vendor_val, allow_blank=True, id="at-vendor", classes="at-input")

                yield Label("Description:", classes="at-field-label")
                yield Input(value=tx_desc, id="at-desc", classes="at-input")

                yield Label("Splits:", classes="at-field-label")
                for i, (sid, acct_id, acct_name, amount, split_desc) in enumerate(self.orig_splits):
                    direction = "DR" if amount > 0 else "CR"
                    display_name = acct_labels.get(acct_id, acct_name)
                    if sid in self._reconciled_split_ids:
                        yield Label(
                            f"  {display_name}  {fmt(abs(amount))}  {direction}",
                            classes="at-field-label",
                            shrink=True,
                        )
                    else:
                        self._split_account_ids[i] = acct_id
                        with Horizontal(classes="at-split-row", id=f"at-split-row-{i}"):
                            yield Button(
                                display_name or "Select account...",
                                id=f"at-split-account-{i}",
                                classes="at-split-account",
                            )
                            yield Label(
                                f"  {fmt(abs(amount))}  {direction}",
                                classes="at-field-label",
                            )
                    memo_classes = "at-split-memo-row" + ("" if split_desc else " hidden")
                    with Horizontal(classes=memo_classes, id=f"at-split-memo-{i}"):
                        yield Input(value=split_desc, placeholder="Description (optional)", id=f"at-split-memo-input-{i}")

                with Horizontal(id="at-add-split-row"):
                    yield Button("+ Desc", id="at-toggle-memos")
                with Horizontal(id="at-buttons"):
                    yield Button("Save", variant="primary", id="at-save")
                    yield Button("Cancel", id="at-cancel-btn")
                yield Label("\\[Ctrl+S] Save  \\[Ctrl+D] Descriptions", id="at-hint")
            return

        self._next_split_id = len(self.orig_splits)
        self._alive_splits = list(range(len(self.orig_splits)))
        vendor_options = [(v["name"], v["id"]) for v in get_all_vendors(self.con)]

        with VerticalScroll(id="at-dialog"):
            yield Label("Edit Transaction", id="at-title")

            with Horizontal(classes="at-date-vendor-row"):
                with Vertical(classes="at-date-col"):
                    yield Label("Date:", classes="at-field-label")
                    yield DateInput(value=format_date(tx_date), id="at-date", classes="at-input")
                if vendor_options:
                    with Vertical(classes="at-vendor-col"):
                        yield Label("Vendor:", classes="at-field-label")
                        vendor_val = tx_vendor_id if tx_vendor_id else Select.NULL
                        yield Select(vendor_options, value=vendor_val, allow_blank=True, id="at-vendor", classes="at-input")

            yield Label("Description:", classes="at-field-label")
            yield Input(value=tx_desc, id="at-desc", classes="at-input")

            yield Label("Splits:", classes="at-field-label")
            with Vertical(id="at-splits-container"):
                for i, (split_id, acct_id, acct_name, amount, split_desc) in enumerate(self.orig_splits):
                    direction = "DR" if amount > 0 else "CR"
                    self.split_directions[i] = direction
                    self._split_account_ids[i] = acct_id
                    abs_cents = abs(amount)
                    display_val = f"{abs_cents / 100:.2f}"
                    display_name = acct_labels.get(acct_id, acct_name) or "Select account..."
                    with Horizontal(classes="at-split-row", id=f"at-split-row-{i}"):
                        yield Button(
                            display_name,
                            id=f"at-split-account-{i}",
                            classes="at-split-account",
                        )
                        yield Input(
                            value=display_val,
                            id=f"at-split-amount-{i}",
                            classes="at-split-amount at-input",
                        )
                        yield Button(
                            direction,
                            id=f"at-split-dir-{i}",
                            classes="at-split-dir",
                        )
                        yield Button(
                            "X",
                            id=f"at-split-remove-{i}",
                            classes="at-split-remove",
                            disabled=len(self.orig_splits) <= 2,
                        )
                    memo_classes = "at-split-memo-row" + ("" if split_desc else " hidden")
                    with Horizontal(classes=memo_classes, id=f"at-split-memo-{i}"):
                        yield Input(value=split_desc, placeholder="Description (optional)", id=f"at-split-memo-input-{i}")

            with Horizontal(id="at-add-split-row"):
                yield Button("+ Add Split", id="at-add-split")
                yield Button("+ Desc", id="at-toggle-memos")

            yield Label("", id="at-balance")
            yield Label("", id="at-error")
            with Horizontal(id="at-buttons"):
                yield Button("Save", variant="primary", id="at-save")
                yield Button("Cancel", id="at-cancel-btn")
                yield Label("", id="at-spacer")
                yield Button("Delete", variant="error", id="at-delete")
            yield Label("\\[Ctrl+S] Save  \\[Ctrl+D] Descriptions", id="at-hint")

    def on_mount(self):
        if self._reconciled:
            return
        if self._has_reconciled:
            # Partial-reconciled: focus description, reveal memos if needed
            if any(s[4] for s in self.orig_splits):
                self._memos_visible = True
                for row in self.query(".at-split-memo-row"):
                    row.remove_class("hidden")
                try:
                    self.query_one("#at-toggle-memos", Button).label = "- Desc"
                except NoMatches:
                    pass
            self.query_one("#at-desc", Input).focus()
            return
        # Mark all loaded splits as user-touched so auto-fill doesn't overwrite
        for i in self._alive_splits:
            self._user_touched_dir.add(i)
            self._user_touched_amount.add(i)
        # If any split has a description, reveal all description rows
        if any(s[4] for s in self.orig_splits):
            self._memos_visible = True
            for row in self.query(".at-split-memo-row"):
                row.remove_class("hidden")
            try:
                self.query_one("#at-toggle-memos", Button).label = "- Desc"
            except NoMatches:
                pass
        self._base_mount()

    def action_toggle_descs(self):
        if not self._reconciled or self._has_reconciled:
            self._toggle_memos()

    def _pick_account(self, idx):
        if self._has_reconciled:
            def on_result(result):
                if result:
                    self._split_account_ids[idx] = result["account_id"]
                    btn = self.query_one(f"#at-split-account-{idx}", Button)
                    btn.label = result["account_name"]
            self.app.push_screen(AccountFuzzyPickScreen(self.con), on_result)
        else:
            super()._pick_account(idx)

    def _save_metadata(self):
        try:
            description = self.query_one("#at-desc", Input).value.strip()
            vendor_id = None
            try:
                vendor_select = self.query_one("#at-vendor", Select)
                if vendor_select.value is not Select.NULL:
                    vendor_id = vendor_select.value
            except NoMatches:
                pass
            split_descs = {}
            for i, (sid, *_rest) in enumerate(self.orig_splits):
                try:
                    desc_input = self.query_one(f"#at-split-memo-input-{i}", Input)
                    split_descs[sid] = desc_input.value.strip()
                except NoMatches:
                    pass
            split_accounts = {}
            for i, (sid, orig_acct_id, *_rest) in enumerate(self.orig_splits):
                if sid in self._reconciled_split_ids:
                    continue
                new_acct_id = self._split_account_ids.get(i)
                if new_acct_id and new_acct_id != orig_acct_id:
                    split_accounts[sid] = new_acct_id
            update_transaction_metadata(self.con, self.tx_id, description,
                                        vendor_id=vendor_id,
                                        split_descriptions=split_descs,
                                        split_accounts=split_accounts or None)
            self.dismiss("saved")
        except Exception as e:
            self.query_one("#at-error", Label).update(f"Error: {e}")

    def _save(self):
        if self._has_reconciled:
            return self._save_metadata()
        try:
            dt = parse_date(self.query_one("#at-date", Input).value)
            description = self.query_one("#at-desc", Input).value.strip()

            orig_count = len(self.orig_splits)
            split_updates = []
            new_splits = []
            for n, i in enumerate(self._alive_splits):
                acct_id = self._split_account_ids.get(i)
                amount_input = self.query_one(f"#at-split-amount-{i}", Input)

                if not acct_id:
                    self.query_one("#at-error", Label).update(
                        f"Error: Split {n + 1} has no account selected"
                    )
                    return
                val = amount_input.value.strip()
                if not val:
                    self.query_one("#at-error", Label).update(
                        f"Error: Split {n + 1} has no amount"
                    )
                    return
                c = cents(val)
                if self.split_directions.get(i) == "CR":
                    c = -c
                split_desc = ""
                try:
                    split_desc = self.query_one(f"#at-split-memo-input-{i}", Input).value.strip()
                except NoMatches:
                    pass
                if i < orig_count:
                    split_id = self.orig_splits[i][0]
                    split_updates.append((split_id, acct_id, c, split_desc))
                else:
                    new_splits.append((acct_id, c, split_desc))

            delete_split_ids = [
                self.orig_splits[i][0]
                for i in range(orig_count)
                if i not in self._alive_splits
            ]

            vendor_id = None
            try:
                vendor_select = self.query_one("#at-vendor", Select)
                if vendor_select.value is not Select.NULL:
                    vendor_id = vendor_select.value
            except NoMatches:
                pass

            update_transaction(self.con, self.tx_id, dt, description,
                               split_updates, new_splits, delete_split_ids,
                               vendor_id=vendor_id)
            self.dismiss("saved")

        except Exception as e:
            self.query_one("#at-error", Label).update(f"Error: {e}")

    def _delete(self):
        delete_transaction(self.con, self.tx_id)
        self.dismiss("deleted")


class ReportDateScreen(ModalScreen):
    """Modal for choosing report date range before opening P&L or Balance Sheet."""

    DEFAULT_CSS = REPORT_DATE_CSS

    PRESETS = [
        ("This Year", "this_year"),
        ("Last Year", "last_year"),
        ("This Quarter", "this_quarter"),
        ("Last Quarter", "last_quarter"),
        ("Custom", "custom"),
    ]

    def __init__(self, report_type):
        super().__init__()
        self.report_type = report_type  # "pnl" or "balance_sheet"
        self.selected_index = 0

    def _is_period_report(self):
        return self.report_type in ("pnl", "cash_flow")

    def compose(self):
        titles = {"pnl": "Profit & Loss", "cash_flow": "Cash Flow"}
        title = titles.get(self.report_type, "Balance Sheet")
        with Vertical(id="rd-dialog"):
            yield Label(f"{title} — Date Range", id="rd-title")
            for i, (label, _) in enumerate(self.PRESETS):
                yield Button(
                    f"[{i + 1}] {label}",
                    id=f"rd-preset-{i}",
                    classes="rd-preset",
                )
            with Vertical(id="rd-custom-fields"):
                if self._is_period_report():
                    yield Label("Start date:", classes="rd-field-label")
                    yield DateInput(
                        placeholder="MM-DD-YYYY",
                        id="rd-start",
                        classes="rd-input",
                    )
                    yield Label("End date:", classes="rd-field-label")
                    yield DateInput(
                        placeholder="MM-DD-YYYY",
                        id="rd-end",
                        classes="rd-input",
                    )
                else:
                    yield Label("As of date:", classes="rd-field-label")
                    yield DateInput(
                        placeholder="MM-DD-YYYY",
                        id="rd-asof",
                        classes="rd-input",
                    )
                yield Label("", id="rd-error")
                with Horizontal(id="rd-confirm-row"):
                    yield Button("OK", variant="primary", id="rd-ok")
                    yield Button("Cancel", id="rd-cancel-custom")

    def on_mount(self):
        self._highlight(0)

    def _highlight(self, index):
        for i in range(len(self.PRESETS)):
            btn = self.query_one(f"#rd-preset-{i}", Button)
            if i == index:
                btn.add_class("-active")
            else:
                btn.remove_class("-active")
        self.selected_index = index

    def _is_custom_focused(self):
        """Check if an Input widget inside custom fields has focus."""
        custom = self.query_one("#rd-custom-fields")
        if not custom.has_class("visible"):
            return False
        focused = self.screen.focused
        return focused is not None and isinstance(focused, Input)

    def on_key(self, event):
        if self._is_custom_focused():
            # Let input handle keys; only intercept Escape
            if event.key == "escape":
                event.prevent_default()
                event.stop()
                self._hide_custom()
            return

        key_map = {"1": 0, "2": 1, "3": 2, "4": 3, "5": 4}
        if event.character in key_map:
            event.prevent_default()
            event.stop()
            idx = key_map[event.character]
            self._highlight(idx)
            self._activate_preset(idx)
            return

        if event.character in ("j",) or event.key == "down":
            event.prevent_default()
            event.stop()
            new = min(self.selected_index + 1, len(self.PRESETS) - 1)
            self._highlight(new)
            return

        if event.character in ("k",) or event.key == "up":
            event.prevent_default()
            event.stop()
            new = max(self.selected_index - 1, 0)
            self._highlight(new)
            return

        if event.key == "enter":
            event.prevent_default()
            event.stop()
            self._activate_preset(self.selected_index)
            return

        if event.key == "escape":
            event.prevent_default()
            event.stop()
            self.dismiss(None)
            return

    def _activate_preset(self, index):
        _, key = self.PRESETS[index]
        if key == "custom":
            self._show_custom()
            return
        today = date.today()
        if key == "this_year":
            start = f"{today.year}-01-01"
            end = today.isoformat()
        elif key == "last_year":
            start = f"{today.year - 1}-01-01"
            end = f"{today.year - 1}-12-31"
        elif key == "this_quarter":
            q_month = ((today.month - 1) // 3) * 3 + 1
            start = f"{today.year}-{q_month:02d}-01"
            end = today.isoformat()
        elif key == "last_quarter":
            q_month = ((today.month - 1) // 3) * 3 + 1
            if q_month == 1:
                # Last quarter is Q4 of previous year
                start = f"{today.year - 1}-10-01"
                end = f"{today.year - 1}-12-31"
            else:
                lq_start = q_month - 3
                # End of last quarter: day before current quarter start
                lq_end_date = date(today.year, q_month, 1).isoformat()
                lq_end_date = date(today.year, q_month, 1)
                from datetime import timedelta
                lq_end_date = (lq_end_date - timedelta(days=1)).isoformat()
                start = f"{today.year}-{lq_start:02d}-01"
                end = lq_end_date
        else:
            return

        if self._is_period_report():
            self.dismiss({"start": start, "end": end})
        else:
            self.dismiss({"as_of": end})

    def _show_custom(self):
        custom = self.query_one("#rd-custom-fields")
        custom.add_class("visible")
        if self._is_period_report():
            self.query_one("#rd-start", Input).focus()
        else:
            self.query_one("#rd-asof", Input).focus()

    def _hide_custom(self):
        custom = self.query_one("#rd-custom-fields")
        custom.remove_class("visible")
        self.query_one("#rd-error", Label).update("")

    @on(Button.Pressed)
    def on_button_pressed(self, event):
        btn_id = event.button.id
        if btn_id and btn_id.startswith("rd-preset-"):
            idx = int(btn_id.split("-")[-1])
            self._highlight(idx)
            self._activate_preset(idx)
        elif btn_id == "rd-ok":
            self._submit_custom()
        elif btn_id == "rd-cancel-custom":
            self._hide_custom()

    @on(Input.Submitted)
    def on_input_submitted(self, event):
        self._submit_custom()

    def _submit_custom(self):
        try:
            if self._is_period_report():
                start = parse_date(self.query_one("#rd-start", Input).value)
                end = parse_date(self.query_one("#rd-end", Input).value)
                self.dismiss({"start": start, "end": end})
            else:
                as_of = parse_date(self.query_one("#rd-asof", Input).value)
                self.dismiss({"as_of": as_of})
        except ValueError as e:
            self.query_one("#rd-error", Label).update(f"Error: {e}")


class ProfitLossScreen(ModalScreen):
    """Modal screen to view Profit & Loss report with drill-down."""

    BINDINGS = [
        Binding("j", "cursor_down", "Nav Down", show=False),
        Binding("k", "cursor_up", "Nav Up", show=False),
        Binding("g", "cursor_top", "Top", show=False),
        Binding("G", "cursor_bottom", "Bottom", show=False),
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
        Binding("ctrl+s", "save_pdf", "Save PDF"),
    ]

    DEFAULT_CSS = PROFIT_LOSS_CSS

    def __init__(self, con, start_date, end_date):
        super().__init__()
        self.con = con
        self.start_date = start_date
        self.end_date = end_date
        self._row_accounts = {}  # row_key -> {"id": ..., "name": ...}

    def compose(self):
        with Vertical(id="pnl-container"):
            yield Label("Profit & Loss", id="pnl-title")
            yield Label(
                f"{format_date(self.start_date)} to {format_date(self.end_date)}",
                id="pnl-subtitle",
            )
            yield DataTable(id="pnl-table", show_header=False, cursor_type="row")
            yield Label(
                "\\[Enter] Drill into account  \\[Ctrl+S] Save PDF  \\[Q] Close",
                id="pnl-hint",
            )

    def on_mount(self):
        self._populate_table()

    def _populate_table(self):
        """Generate the P&L report as DataTable rows."""
        table = self.query_one("#pnl-table", DataTable)
        table.add_columns("Account", "Amount")

        data = generate_pnl(self.con, self.start_date, self.end_date)
        row_idx = 0

        def add_account(acct, indent=0):
            nonlocal row_idx
            prefix = "  " * indent
            bal = acct.get('subtotal', acct['balance'])

            # For income, flip sign for display (credits shown as positive)
            if acct['type'] in ('income', 'other_income'):
                bal = -bal

            if bal != 0 or acct['children']:
                if acct['children']:
                    key = f"pnl_{row_idx}"
                    table.add_row(prefix + acct['name'], "", key=key)
                    self._row_accounts[key] = {"id": acct['id'], "name": acct['name']}
                    row_idx += 1
                    for child in acct['children']:
                        add_account(child, indent + 1)
                    key = f"pnl_{row_idx}"
                    table.add_row(
                        Text(f"{prefix}Total {acct['name']}", style="bold"),
                        Text(fmt(bal), style="bold"),
                        key=key,
                    )
                    row_idx += 1
                else:
                    key = f"pnl_{row_idx}"
                    table.add_row(prefix + acct['name'], fmt(bal), key=key)
                    self._row_accounts[key] = {"id": acct['id'], "name": acct['name']}
                    row_idx += 1

        # Income section
        key = f"pnl_{row_idx}"
        table.add_row(Text("INCOME", style="bold underline"), "", key=key)
        row_idx += 1
        income_accounts = [a for a in data['roots'] if a['type'] in ('income', 'other_income')]
        for acct in income_accounts:
            add_account(acct, indent=1)
        key = f"pnl_{row_idx}"
        table.add_row("", "", key=key)
        row_idx += 1
        key = f"pnl_{row_idx}"
        table.add_row(Text("TOTAL INCOME", style="bold"), Text(fmt(data['income_total']), style="bold"), key=key)
        row_idx += 1
        key = f"pnl_{row_idx}"
        table.add_row(Text("GROSS PROFIT", style="bold"), Text(fmt(data['income_total']), style="bold"), key=key)
        row_idx += 1
        key = f"pnl_{row_idx}"
        table.add_row("", "", key=key)
        row_idx += 1

        # Expense section
        key = f"pnl_{row_idx}"
        table.add_row(Text("EXPENSES", style="bold underline"), "", key=key)
        row_idx += 1
        expense_accounts = [a for a in data['roots'] if a['type'] in ('expense', 'cost_of_goods_sold', 'other_expense')]
        for acct in expense_accounts:
            add_account(acct, indent=1)
        key = f"pnl_{row_idx}"
        table.add_row("", "", key=key)
        row_idx += 1
        key = f"pnl_{row_idx}"
        table.add_row(Text("TOTAL EXPENSES", style="bold"), Text(fmt(data['expense_total']), style="bold"), key=key)
        row_idx += 1
        key = f"pnl_{row_idx}"
        table.add_row("", "", key=key)
        row_idx += 1

        # Net income
        key = f"pnl_{row_idx}"
        table.add_row(Text("NET INCOME", style="bold cyan"), Text(fmt(data['net_income']), style="bold cyan"), key=key)

    @on(DataTable.RowSelected, "#pnl-table")
    def on_data_table_row_selected(self, event):
        key = str(event.row_key.value)
        acct = self._row_accounts.get(key)
        if acct:
            self.dismiss({
                "action": "view_transactions",
                "account": acct,
                "start_date": self.start_date,
                "end_date": self.end_date,
            })

    def action_cursor_down(self):
        self.query_one("#pnl-table", DataTable).action_cursor_down()

    def action_cursor_up(self):
        self.query_one("#pnl-table", DataTable).action_cursor_up()

    def action_cursor_top(self):
        self.query_one("#pnl-table", DataTable).move_cursor(row=0)

    def action_cursor_bottom(self):
        table = self.query_one("#pnl-table", DataTable)
        table.move_cursor(row=table.row_count - 1)

    def action_close(self):
        self.dismiss()

    def action_save_pdf(self):
        """Export the P&L report as a PDF."""
        output_path = resolve_report_path(
            self.app._preferences, "pnl", self.end_date,
            start_date=self.start_date, end_date=self.end_date,
        )
        if output_path is None:
            output_path = Path.cwd() / f"pnl_{self.start_date}_to_{self.end_date}.pdf"
        _save_report_pdf(self, output_path, lambda p, c: export_pnl_pdf(
            self.con, self.start_date, self.end_date, p, color=c,
        ))


class CashFlowScreen(ModalScreen):
    """Modal screen to view Cash Flow Statement with drill-down."""

    BINDINGS = [
        Binding("j", "cursor_down", "Nav Down", show=False),
        Binding("k", "cursor_up", "Nav Up", show=False),
        Binding("g", "cursor_top", "Top", show=False),
        Binding("G", "cursor_bottom", "Bottom", show=False),
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
        Binding("ctrl+s", "save_pdf", "Save PDF"),
    ]

    DEFAULT_CSS = CASH_FLOW_CSS

    def __init__(self, con, start_date, end_date):
        super().__init__()
        self.con = con
        self.start_date = start_date
        self.end_date = end_date
        self._row_accounts = {}

    def compose(self):
        with Vertical(id="cf-container"):
            yield Label("Cash Flow Statement", id="cf-title")
            yield Label(
                f"{format_date(self.start_date)} to {format_date(self.end_date)}",
                id="cf-subtitle",
            )
            yield DataTable(id="cf-table", show_header=False, cursor_type="row")
            yield Label(
                "\\[Enter] Drill into account  \\[Ctrl+S] Save PDF  \\[Q] Close",
                id="cf-hint",
            )

    def on_mount(self):
        self._populate_table()

    def _populate_table(self):
        table = self.query_one("#cf-table", DataTable)
        table.add_columns("Account", "Amount")

        data = generate_cash_flow(self.con, self.start_date, self.end_date)
        row_idx = 0

        def add_section(title, items, total, total_label):
            nonlocal row_idx

            key = f"cf_{row_idx}"
            table.add_row(Text(title, style="bold underline"), "", key=key)
            row_idx += 1

            for item in items:
                key = f"cf_{row_idx}"
                table.add_row(f"  {item['name']}", fmt(item['amount']), key=key)
                self._row_accounts[key] = {
                    "id": item["id"], "name": item["name"],
                }
                row_idx += 1

            key = f"cf_{row_idx}"
            table.add_row("", "", key=key)
            row_idx += 1

            key = f"cf_{row_idx}"
            table.add_row(
                Text(total_label, style="bold"),
                Text(fmt(total), style="bold"),
                key=key,
            )
            row_idx += 1

            key = f"cf_{row_idx}"
            table.add_row("", "", key=key)
            row_idx += 1

        add_section(
            "OPERATING ACTIVITIES", data["operating"],
            data["total_operating"], "Total Operating Activities",
        )
        add_section(
            "INVESTING ACTIVITIES", data["investing"],
            data["total_investing"], "Total Investing Activities",
        )
        add_section(
            "FINANCING ACTIVITIES", data["financing"],
            data["total_financing"], "Total Financing Activities",
        )

        # Net change in cash
        key = f"cf_{row_idx}"
        table.add_row(
            Text("NET CHANGE IN CASH", style="bold cyan"),
            Text(fmt(data["net_change"]), style="bold cyan"),
            key=key,
        )
        row_idx += 1

        # Blank separator
        key = f"cf_{row_idx}"
        table.add_row("", "", key=key)
        row_idx += 1

        # Beginning balance
        key = f"cf_{row_idx}"
        table.add_row(
            "Beginning Cash Balance",
            fmt(data["beginning_balance"]),
            key=key,
        )
        row_idx += 1

        # Ending balance
        key = f"cf_{row_idx}"
        table.add_row(
            Text("Ending Cash Balance", style="bold cyan"),
            Text(fmt(data["ending_balance"]), style="bold cyan"),
            key=key,
        )

    @on(DataTable.RowSelected, "#cf-table")
    def on_data_table_row_selected(self, event):
        key = str(event.row_key.value)
        acct = self._row_accounts.get(key)
        if acct:
            self.dismiss({
                "action": "view_transactions",
                "account": acct,
                "start_date": self.start_date,
                "end_date": self.end_date,
            })

    def action_cursor_down(self):
        self.query_one("#cf-table", DataTable).action_cursor_down()

    def action_cursor_up(self):
        self.query_one("#cf-table", DataTable).action_cursor_up()

    def action_cursor_top(self):
        self.query_one("#cf-table", DataTable).move_cursor(row=0)

    def action_cursor_bottom(self):
        table = self.query_one("#cf-table", DataTable)
        table.move_cursor(row=table.row_count - 1)

    def action_close(self):
        self.dismiss()

    def action_save_pdf(self):
        """Export the Cash Flow Statement as a PDF."""
        output_path = resolve_report_path(
            self.app._preferences, "cash_flow", self.end_date,
            start_date=self.start_date, end_date=self.end_date,
        )
        if output_path is None:
            output_path = Path.cwd() / f"cash_flow_{self.start_date}_to_{self.end_date}.pdf"
        _save_report_pdf(self, output_path, lambda p, c: export_cash_flow_pdf(
            self.con, self.start_date, self.end_date, p, color=c,
        ))


class BalanceSheetScreen(ModalScreen):
    """Modal screen to view Balance Sheet report with drill-down."""

    BINDINGS = [
        Binding("j", "cursor_down", "Nav Down", show=False),
        Binding("k", "cursor_up", "Nav Up", show=False),
        Binding("g", "cursor_top", "Top", show=False),
        Binding("G", "cursor_bottom", "Bottom", show=False),
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
        Binding("ctrl+s", "save_pdf", "Save PDF"),
    ]

    DEFAULT_CSS = BALANCE_SHEET_CSS

    def __init__(self, con, as_of_date):
        super().__init__()
        self.con = con
        self.as_of_date = as_of_date
        self._row_accounts = {}  # row_key -> {"id": ..., "name": ...}

    def compose(self):
        with Vertical(id="bs-container"):
            yield Label("Balance Sheet", id="bs-title")
            yield Label(f"As of {format_date(self.as_of_date)}", id="bs-subtitle")
            yield DataTable(id="bs-table", show_header=False, cursor_type="row")
            yield Label(
                "\\[Enter] Drill into account  \\[Ctrl+S] Save PDF  \\[Q] Close",
                id="bs-hint",
            )

    def on_mount(self):
        self._populate_table()

    def _populate_table(self):
        """Generate the Balance Sheet as DataTable rows."""
        table = self.query_one("#bs-table", DataTable)
        table.add_columns("Account", "Amount")

        data = generate_balance_sheet(self.con, self.as_of_date)

        from pyre.db import ASSET_TYPES, LIABILITY_TYPES

        row_idx = 0

        def add_account(acct, indent=0, negate=False):
            nonlocal row_idx
            prefix = "  " * indent
            bal = acct.get('subtotal', acct['balance'])
            if negate:
                bal = -bal

            if bal != 0 or acct['children']:
                if acct['children']:
                    key = f"bs_{row_idx}"
                    table.add_row(prefix + acct['name'], "", key=key)
                    self._row_accounts[key] = {"id": acct['id'], "name": acct['name']}
                    row_idx += 1
                    for child in acct['children']:
                        add_account(child, indent + 1, negate=negate)
                    key = f"bs_{row_idx}"
                    table.add_row(
                        Text(f"{prefix}Total {acct['name']}", style="bold"),
                        Text(fmt(bal), style="bold"),
                        key=key,
                    )
                    row_idx += 1
                else:
                    key = f"bs_{row_idx}"
                    table.add_row(prefix + acct['name'], fmt(bal), key=key)
                    self._row_accounts[key] = {"id": acct['id'], "name": acct['name']}
                    row_idx += 1

        # Assets
        key = f"bs_{row_idx}"
        table.add_row(Text("ASSETS", style="bold underline"), "", key=key)
        row_idx += 1
        asset_accounts = [a for a in data['roots'] if a['type'] in ASSET_TYPES]
        for acct in asset_accounts:
            add_account(acct, indent=1)
        key = f"bs_{row_idx}"
        table.add_row("", "", key=key)
        row_idx += 1
        key = f"bs_{row_idx}"
        table.add_row(Text("TOTAL ASSETS", style="bold"), Text(fmt(data['total_assets']), style="bold"), key=key)
        row_idx += 1
        key = f"bs_{row_idx}"
        table.add_row("", "", key=key)
        row_idx += 1

        # Liabilities
        key = f"bs_{row_idx}"
        table.add_row(Text("LIABILITIES", style="bold underline"), "", key=key)
        row_idx += 1
        liability_accounts = [a for a in data['roots'] if a['type'] in LIABILITY_TYPES]
        for acct in liability_accounts:
            add_account(acct, indent=1, negate=True)
        key = f"bs_{row_idx}"
        table.add_row("", "", key=key)
        row_idx += 1
        key = f"bs_{row_idx}"
        table.add_row(Text("TOTAL LIABILITIES", style="bold"), Text(fmt(data['total_liabilities']), style="bold"), key=key)
        row_idx += 1
        key = f"bs_{row_idx}"
        table.add_row("", "", key=key)
        row_idx += 1

        # Equity
        key = f"bs_{row_idx}"
        table.add_row(Text("EQUITY", style="bold underline"), "", key=key)
        row_idx += 1
        equity_accounts = [a for a in data['roots'] if a['type'] == 'equity']
        for acct in equity_accounts:
            add_account(acct, indent=1, negate=True)
        if data['net_income'] != 0:
            key = f"bs_{row_idx}"
            table.add_row("  Net Income", fmt(data['net_income']), key=key)
            row_idx += 1
        key = f"bs_{row_idx}"
        table.add_row("", "", key=key)
        row_idx += 1
        key = f"bs_{row_idx}"
        table.add_row(
            Text("TOTAL EQUITY", style="bold"),
            Text(fmt(data['total_equity'] + data['net_income']), style="bold"),
            key=key,
        )
        row_idx += 1
        key = f"bs_{row_idx}"
        table.add_row("", "", key=key)
        row_idx += 1

        # Grand total
        key = f"bs_{row_idx}"
        table.add_row(
            Text("TOTAL LIABILITIES AND EQUITY", style="bold cyan"),
            Text(fmt(data['total_liabilities_and_equity']), style="bold cyan"),
            key=key,
        )

    @on(DataTable.RowSelected, "#bs-table")
    def on_data_table_row_selected(self, event):
        key = str(event.row_key.value)
        acct = self._row_accounts.get(key)
        if acct:
            self.dismiss({
                "action": "view_transactions",
                "account": acct,
                "end_date": self.as_of_date,
            })

    def action_cursor_down(self):
        self.query_one("#bs-table", DataTable).action_cursor_down()

    def action_cursor_up(self):
        self.query_one("#bs-table", DataTable).action_cursor_up()

    def action_cursor_top(self):
        self.query_one("#bs-table", DataTable).move_cursor(row=0)

    def action_cursor_bottom(self):
        table = self.query_one("#bs-table", DataTable)
        table.move_cursor(row=table.row_count - 1)

    def action_close(self):
        self.dismiss()

    def action_save_pdf(self):
        """Export the Balance Sheet as a PDF."""
        output_path = resolve_report_path(
            self.app._preferences, "balance_sheet", self.as_of_date,
            as_of_date=self.as_of_date,
        )
        if output_path is None:
            output_path = Path.cwd() / f"balance_sheet_{self.as_of_date}.pdf"
        _save_report_pdf(self, output_path, lambda p, c: export_balance_sheet_pdf(
            self.con, self.as_of_date, p, color=c,
        ))


class TrialBalanceScreen(ModalScreen):
    """Modal screen to view Trial Balance report with drill-down."""

    BINDINGS = [
        Binding("j", "cursor_down", "Nav Down", show=False),
        Binding("k", "cursor_up", "Nav Up", show=False),
        Binding("g", "cursor_top", "Top", show=False),
        Binding("G", "cursor_bottom", "Bottom", show=False),
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
    ]

    DEFAULT_CSS = TRIAL_BALANCE_CSS

    def __init__(self, con, as_of_date):
        super().__init__()
        self.con = con
        self.as_of_date = as_of_date
        self._row_accounts = {}

    def compose(self):
        with Vertical(id="tb-container"):
            yield Label("Trial Balance", id="tb-title")
            yield Label(f"As of {format_date(self.as_of_date)}", id="tb-subtitle")
            yield DataTable(id="tb-table", show_header=True, cursor_type="row")
            yield Label(
                "\\[Enter] Drill into account  \\[Q] Close",
                id="tb-hint",
            )

    def on_mount(self):
        self._populate_table()

    def _populate_table(self):
        table = self.query_one("#tb-table", DataTable)
        table.add_columns("Account", "Debit", "Credit")

        data = generate_trial_balance(self.con, self.as_of_date)
        row_idx = 0

        for acct in data['accounts']:
            key = f"tb_{row_idx}"
            debit_cell = fmt(acct['debit']) if acct['debit'] else ""
            credit_cell = fmt(acct['credit']) if acct['credit'] else ""
            table.add_row(acct['name'], debit_cell, credit_cell, key=key)
            self._row_accounts[key] = {"id": acct['id'], "name": acct['name']}
            row_idx += 1

        # Blank separator
        key = f"tb_{row_idx}"
        table.add_row("", "", "", key=key)
        row_idx += 1

        # Totals row
        key = f"tb_{row_idx}"
        table.add_row(
            Text("TOTAL", style="bold"),
            Text(fmt(data['total_debit']), style="bold"),
            Text(fmt(data['total_credit']), style="bold"),
            key=key,
        )

    @on(DataTable.RowSelected, "#tb-table")
    def on_data_table_row_selected(self, event):
        key = str(event.row_key.value)
        acct = self._row_accounts.get(key)
        if acct:
            self.dismiss({
                "action": "view_transactions",
                "account": acct,
                "end_date": self.as_of_date,
            })

    def action_cursor_down(self):
        self.query_one("#tb-table", DataTable).action_cursor_down()

    def action_cursor_up(self):
        self.query_one("#tb-table", DataTable).action_cursor_up()

    def action_cursor_top(self):
        self.query_one("#tb-table", DataTable).move_cursor(row=0)

    def action_cursor_bottom(self):
        table = self.query_one("#tb-table", DataTable)
        table.move_cursor(row=table.row_count - 1)

    def action_close(self):
        self.dismiss()


class ChartOfAccountsScreen(ModalScreen):
    """Modal tree view of the chart of accounts with CRUD."""

    BINDINGS = [
        Binding("j", "cursor_down", "Nav Down", show=False),
        Binding("k", "cursor_up", "Nav Up", show=False),
        Binding("g", "cursor_top", "Top", show=False),
        Binding("G", "cursor_bottom", "Bottom", show=False),
        Binding("a", "add_account", "Add", show=False),
        Binding("e", "edit_account", "Edit", show=False),
        Binding("d", "delete_account", "Delete", show=False),
        Binding("s", "toggle_sidebar", "Sidebar", show=False),
        Binding("r", "refresh_tree", "Refresh", show=False),
        Binding("slash", "open_search", "Search", show=False),
        Binding("minus", "collapse_level", "Collapse", show=False),
        Binding("equals_sign", "expand_level", "Expand", show=False),
        Binding("plus", "expand_level", "Expand", show=False),
        Binding("q", "close", "Close", show=False),
        Binding("escape", "close_or_clear", "Close", show=False),
    ]

    DEFAULT_CSS = CHART_OF_ACCOUNTS_CSS

    def __init__(self, con):
        super().__init__()
        self.con = con
        self.search_active = False
        self.search_query = ""

    def compose(self):
        with Vertical(id="coa-container"):
            yield Label("Chart of Accounts", id="coa-title")
            yield Tree("Accounts", id="coa-tree")
            with Horizontal(id="coa-search-bar"):
                yield Label("/", id="coa-search-prompt")
                yield Input(
                    placeholder="Search accounts...",
                    id="coa-search-input",
                )
                yield Label("", id="coa-search-count")
            yield Label(
                "\\[A] Add  \\[E] Edit  \\[D] Delete  \\[S] Sidebar  \\[/] Search  \\[Enter] Txns  \\[Q] Close",
                id="coa-hint",
            )

    def on_mount(self):
        self.populate_tree()

    def action_close(self):
        self.dismiss()

    @on(Tree.NodeSelected)
    def on_node_selected(self, event):
        """Enter pressed on a node — view transactions for that account."""
        # Ignore programmatic selection (e.g. from search filtering)
        if self.search_active:
            return
        if event.node.data is not None:
            self.dismiss({"action": "view_transactions", "account": event.node.data})

    def action_cursor_down(self):
        tree = self.query_one("#coa-tree", Tree)
        tree.action_cursor_down()

    def action_cursor_up(self):
        tree = self.query_one("#coa-tree", Tree)
        tree.action_cursor_up()

    def action_cursor_top(self):
        tree = self.query_one("#coa-tree", Tree)
        tree.move_cursor_to_line(0)
        tree.scroll_home()

    def action_cursor_bottom(self):
        tree = self.query_one("#coa-tree", Tree)
        last = tree.last_line
        if last >= 0:
            tree.move_cursor_to_line(last)
            tree.scroll_end()


    def _get_node_depth(self, node):
        """Return depth of a node (root=0, categories=1, top-level accounts=2, etc.)."""
        depth = 0
        n = node
        while n.parent is not None:
            depth += 1
            n = n.parent
        return depth

    def _walk_nodes(self, node):
        """Yield all nodes in the tree (depth-first)."""
        yield node
        for child in node.children:
            yield from self._walk_nodes(child)

    def action_collapse_level(self):
        """Collapse the deepest currently-expanded level."""
        tree = self.query_one("#coa-tree", Tree)
        # Find the max depth of any expanded node that has children
        max_depth = 0
        for node in self._walk_nodes(tree.root):
            if node.is_expanded and node.children and node != tree.root:
                d = self._get_node_depth(node)
                if d > max_depth:
                    max_depth = d
        if max_depth == 0:
            return
        # Collapse all nodes at that depth
        for node in self._walk_nodes(tree.root):
            if node.is_expanded and node.children and self._get_node_depth(node) == max_depth:
                node.collapse()

    def action_expand_level(self):
        """Expand one level deeper than the current deepest expanded level."""
        tree = self.query_one("#coa-tree", Tree)
        # Find the max depth of any expanded node
        max_depth = 0
        for node in self._walk_nodes(tree.root):
            if node.is_expanded and node != tree.root:
                d = self._get_node_depth(node)
                if d > max_depth:
                    max_depth = d
        # Expand all collapsed nodes at depth max_depth + 1
        # (children of currently-expanded nodes at max_depth)
        target = max_depth + 1
        expanded_any = False
        for node in self._walk_nodes(tree.root):
            if (not node.is_expanded and node.allow_expand
                    and self._get_node_depth(node) == target):
                node.expand()
                expanded_any = True
        # If nothing to expand at next level, try expanding from depth 1 (categories)
        if not expanded_any:
            for node in self._walk_nodes(tree.root):
                if not node.is_expanded and node.allow_expand and node != tree.root:
                    node.expand()
                    break

    def populate_tree(self):
        tree = self.query_one("#coa-tree", Tree)
        tree.clear()
        tree.root.expand()

        accounts = get_all_accounts(self.con)

        # Pre-fetch all balances in one query
        balances = {}
        rows = self.con.execute(
            "SELECT account_id, SUM(amount) FROM splits GROUP BY account_id"
        ).fetchall()
        for acct_id, total in rows:
            balances[acct_id] = total

        # Group top-level accounts by category
        categorized = {cat: [] for cat in ACCOUNT_CATEGORIES}
        children_of = {}  # parent_id -> [account, ...]

        for acct in accounts:
            pid = acct["parent_id"]
            if pid:
                children_of.setdefault(pid, []).append(acct)
            else:
                cat = get_account_category(acct["type"])
                if cat:
                    categorized[cat].append(acct)

        def is_leaf(acct_id):
            return acct_id not in children_of

        sidebar_ids = set(
            r[0] for r in self.con.execute(
                "SELECT id FROM accounts WHERE sidebar = 1"
            ).fetchall()
        )

        def make_label(acct, expandable=False):
            num = acct.get("account_number")
            if num:
                name = f"{num} - {acct['name']}"
            else:
                name = acct["name"]
            star_parts = (("\u2605 ", "bold yellow"), ) if acct["id"] in sidebar_ids else ()
            # star is 2 chars wide when present
            display_len = len(name) + (2 if star_parts else 0)
            bal = balances.get(acct["id"])
            if bal:
                bal_str = fmt(bal)
                col = 58 if expandable else 60
                pad = max(1, col - display_len)
                return Text.assemble(*star_parts, name, " " * pad, (bal_str, "dim"))
            return Text.assemble(*star_parts, name) if star_parts else name

        def add_children(parent_node, parent_id):
            for child in children_of.get(parent_id, []):
                leaf = is_leaf(child["id"])
                child_node = parent_node.add(
                    make_label(child, expandable=not leaf),
                    data=child, allow_expand=not leaf,
                )
                if not leaf:
                    child_node.expand()
                    add_children(child_node, child["id"])

        for category in ACCOUNT_CATEGORIES:
            cat_accounts = categorized[category]
            if not cat_accounts:
                continue
            cat_node = tree.root.add(f"[bold]{category}[/bold]", data=None)
            cat_node.expand()
            for acct in cat_accounts:
                leaf = is_leaf(acct["id"])
                acct_node = cat_node.add(
                    make_label(acct, expandable=not leaf),
                    data=acct, allow_expand=not leaf,
                )
                if not leaf:
                    acct_node.expand()
                    add_children(acct_node, acct["id"])

    def _get_selected_account(self):
        """Return the selected account dict, or None if a category header."""
        tree = self.query_one("#coa-tree", Tree)
        node = tree.cursor_node
        if node is None or node.data is None:
            return None
        return node.data

    def action_add_account(self):
        def on_dismiss(result):
            if result:
                self.populate_tree()

        self.app.push_screen(AccountFormScreen(self.con, mode="add"), callback=on_dismiss)

    def action_edit_account(self):
        acct = self._get_selected_account()
        if acct is None:
            self.app.notify("Select an account to edit", severity="warning")
            return

        def on_dismiss(result):
            if result:
                self.populate_tree()

        self.app.push_screen(
            AccountFormScreen(self.con, mode="edit", account=acct),
            callback=on_dismiss,
        )

    def action_delete_account(self):
        acct = self._get_selected_account()
        if acct is None:
            self.app.notify("Select an account to delete", severity="warning")
            return

        children = get_child_count(self.con, acct["id"])
        if children > 0:
            self.app.notify(
                f"Cannot delete \"{acct['name']}\": has {children} child account(s)",
                severity="error",
            )
            return

        txns = get_transaction_count(self.con, acct["id"])
        if txns > 0:
            self.app.notify(
                f"Cannot delete \"{acct['name']}\": has {txns} transaction(s)",
                severity="error",
            )
            return

        def on_dismiss(result):
            if result:
                self.populate_tree()

        self.app.push_screen(
            ConfirmDeleteScreen(self.con, acct),
            callback=on_dismiss,
        )

    def action_toggle_sidebar(self):
        acct = self._get_selected_account()
        if acct is None:
            self.app.notify("Select an account to toggle", severity="warning")
            return
        toggle_sidebar(self.con, acct["id"])
        self.populate_tree()
        self.app.refresh_balances()

    def action_refresh_tree(self):
        self.populate_tree()

    def action_open_search(self):
        self.search_active = True
        bar = self.query_one("#coa-search-bar")
        bar.add_class("visible")
        search_input = self.query_one("#coa-search-input", Input)
        search_input.value = ""
        search_input.focus()

    def _close_search(self):
        self.search_active = False
        self.search_query = ""
        bar = self.query_one("#coa-search-bar")
        bar.remove_class("visible")
        self.query_one("#coa-search-count", Label).update("")
        self.populate_tree()
        self.query_one("#coa-tree", Tree).focus()

    @on(Input.Changed, "#coa-search-input")
    def on_search_changed(self, event):
        self.search_query = event.value.strip().lower()
        self._filter_tree()

    @on(Input.Submitted, "#coa-search-input")
    def on_search_submitted(self, event):
        """Confirm search — close bar, keep filter, focus tree."""
        self.search_active = False
        bar = self.query_one("#coa-search-bar")
        bar.remove_class("visible")
        self.query_one("#coa-tree", Tree).focus()

    def _filter_tree(self):
        """Show only matching accounts (and their ancestors) in the tree."""
        tree = self.query_one("#coa-tree", Tree)
        query = self.search_query
        if not query:
            self.populate_tree()
            self.query_one("#coa-search-count", Label).update("")
            return

        accounts = get_all_accounts(self.con)
        by_id = {a["id"]: a for a in accounts}

        # Find accounts matching the query
        matching_ids = set()
        for acct in accounts:
            name = acct["name"].lower()
            num = (acct["account_number"] or "").lower()
            if query in name or query in num:
                matching_ids.add(acct["id"])

        # Include all ancestors of matching accounts so tree structure is visible
        ancestor_ids = set()
        for acct_id in matching_ids:
            current = by_id[acct_id].get("parent_id")
            while current:
                ancestor_ids.add(current)
                current = by_id.get(current, {}).get("parent_id")

        visible_ids = matching_ids | ancestor_ids

        # Pre-fetch balances
        balances = {}
        rows = self.con.execute(
            "SELECT account_id, SUM(amount) FROM splits GROUP BY account_id"
        ).fetchall()
        for acct_id, total in rows:
            balances[acct_id] = total

        # Rebuild tree with only visible accounts
        tree.clear()
        tree.root.expand()

        categorized = {cat: [] for cat in ACCOUNT_CATEGORIES}
        children_of = {}

        for acct in accounts:
            if acct["id"] not in visible_ids:
                continue
            pid = acct["parent_id"]
            if pid and pid in visible_ids:
                children_of.setdefault(pid, []).append(acct)
            elif not pid:
                cat = get_account_category(acct["type"])
                if cat:
                    categorized[cat].append(acct)
            else:
                # Parent not visible — promote to top level
                cat = get_account_category(acct["type"])
                if cat:
                    categorized[cat].append(acct)

        sidebar_ids = set(
            r[0] for r in self.con.execute(
                "SELECT id FROM accounts WHERE sidebar = 1"
            ).fetchall()
        )

        def is_leaf(acct_id):
            return acct_id not in children_of

        def make_label(acct, expandable=False):
            num = acct.get("account_number")
            if num:
                name = f"{num} - {acct['name']}"
            else:
                name = acct["name"]
            star_parts = (("\u2605 ", "bold yellow"), ) if acct["id"] in sidebar_ids else ()
            display_len = len(name) + (2 if star_parts else 0)
            bal = balances.get(acct["id"])
            if bal:
                bal_str = fmt(bal)
                col = 58 if expandable else 60
                pad = max(1, col - display_len)
                return Text.assemble(*star_parts, name, " " * pad, (bal_str, "dim"))
            return Text.assemble(*star_parts, name) if star_parts else name

        first_actionable_node = None

        def track_match(node, acct_id):
            nonlocal match_count, first_actionable_node
            if acct_id in matching_ids:
                match_count += 1
                if first_actionable_node is None:
                    first_actionable_node = node

        def add_children(parent_node, parent_id):
            for child in children_of.get(parent_id, []):
                leaf = is_leaf(child["id"])
                child_node = parent_node.add(
                    make_label(child, expandable=not leaf),
                    data=child, allow_expand=not leaf,
                )
                track_match(child_node, child["id"])
                if not leaf:
                    child_node.expand()
                    add_children(child_node, child["id"])

        match_count = 0
        for category in ACCOUNT_CATEGORIES:
            cat_accounts = categorized[category]
            if not cat_accounts:
                continue
            cat_node = tree.root.add(f"[bold]{category}[/bold]", data=None)
            cat_node.expand()
            for acct in cat_accounts:
                leaf = is_leaf(acct["id"])
                acct_node = cat_node.add(
                    make_label(acct, expandable=not leaf),
                    data=acct, allow_expand=not leaf,
                )
                track_match(acct_node, acct["id"])
                if not leaf:
                    acct_node.expand()
                    add_children(acct_node, acct["id"])

        self.query_one("#coa-search-count", Label).update(
            f"{match_count} match{'es' if match_count != 1 else ''}"
        )

        # Move cursor to first actionable match (an actual account, not a category).
        # Force the tree to rebuild its internal line cache so node._line is valid.
        if first_actionable_node is not None:
            tree._build()
            tree.move_cursor(first_actionable_node)

    def action_close_or_clear(self):
        if self.search_active:
            self._close_search()
        elif self.search_query:
            # Search bar closed but filter still active — clear it
            self.search_query = ""
            self.populate_tree()
        else:
            self.dismiss()


class AccountFormScreen(ModalScreen):
    """Modal form for adding or editing an account."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = ACCOUNT_FORM_CSS

    def __init__(self, con, mode="add", account=None):
        super().__init__()
        self.con = con
        self.mode = mode
        self.account = account  # dict for edit mode

    def compose(self):
        title = "Edit Account" if self.mode == "edit" else "Add Account"
        all_types = get_all_account_types()
        type_options = [(t.replace("_", " ").title(), t) for t in all_types]

        with VerticalScroll(id="af-dialog"):
            yield Label(title, id="af-title")

            yield Label("Name:", classes="af-field-label")
            yield Input(
                value=self.account["name"] if self.account else "",
                placeholder="Account name",
                id="af-name",
                classes="af-input",
            )

            yield Label("Account Number:", classes="af-field-label")
            yield Input(
                value=self.account["account_number"] or "" if self.account else "",
                placeholder="Optional",
                id="af-number",
                classes="af-input",
            )

            yield Label("Type:", classes="af-field-label")
            if self.account:
                yield Select(
                    type_options,
                    value=self.account["type"],
                    id="af-type",
                    classes="af-input",
                )
            else:
                yield Select(
                    type_options,
                    allow_blank=True,
                    id="af-type",
                    classes="af-input",
                )

            yield Label("Parent:", classes="af-field-label")
            yield Select(
                [],
                allow_blank=True,
                id="af-parent",
                classes="af-input",
            )

            yield Label("Description:", classes="af-field-label")
            yield Input(
                value=self.account["description"] or "" if self.account else "",
                placeholder="Optional",
                id="af-description",
                classes="af-input",
            )

            with Horizontal(classes="af-switch-row"):
                yield Label("Show in sidebar:", classes="af-field-label")
                yield Switch(
                    value=bool(self.account["sidebar"]) if self.account else False,
                    id="af-sidebar",
                )

            yield Label("", id="af-error")
            with Horizontal(id="af-buttons"):
                yield Button("Save", variant="primary", id="af-save")
                yield Button("Cancel", id="af-cancel")

    def on_mount(self):
        self._update_parent_options()
        self.query_one("#af-name", Input).focus()

    @on(Select.Changed, "#af-type")
    def on_type_changed(self, event):
        self._update_parent_options()

    @staticmethod
    def _build_account_path(account_id, by_id):
        return account_path(by_id, account_id)

    def _update_parent_options(self):
        """Filter parent select to accounts in the same type family."""
        type_select = self.query_one("#af-type", Select)
        parent_select = self.query_one("#af-parent", Select)
        selected_type = type_select.value

        if selected_type is Select.NULL:
            parent_select.set_options([])
            return

        family = TYPE_FAMILY.get(selected_type, selected_type)
        accounts = get_all_accounts(self.con)
        by_id = {a["id"]: a for a in accounts}
        options = []
        for a in accounts:
            if TYPE_FAMILY.get(a["type"]) == family:
                # Don't list self as potential parent
                if self.account and a["id"] == self.account["id"]:
                    continue
                label = self._build_account_path(a["id"], by_id)
                options.append((label, a["id"]))

        parent_select.set_options(options)

        # Restore parent selection in edit mode
        if self.account and self.account["parent_id"]:
            parent_ids = [o[1] for o in options]
            if self.account["parent_id"] in parent_ids:
                parent_select.value = self.account["parent_id"]

    @on(Input.Submitted)
    def handle_submit(self, event):
        self._save()

    @on(Button.Pressed, "#af-save")
    def on_save_pressed(self, event):
        self._save()

    @on(Button.Pressed, "#af-cancel")
    def on_cancel_pressed(self, event):
        self.dismiss(False)

    def _save(self):
        try:
            name = self.query_one("#af-name", Input).value.strip()
            if not name:
                self.query_one("#af-error", Label).update("Name is required.")
                return

            number = self.query_one("#af-number", Input).value.strip() or None
            acct_type = self.query_one("#af-type", Select).value
            if acct_type is Select.NULL:
                self.query_one("#af-error", Label).update("Type is required.")
                return

            parent_id = self.query_one("#af-parent", Select).value
            if parent_id is Select.NULL:
                parent_id = None

            description = self.query_one("#af-description", Input).value.strip()
            sidebar = self.query_one("#af-sidebar", Switch).value

            if self.mode == "add":
                account_id = self._generate_unique_id(name, parent_id)
                create_account(
                    self.con, account_id, name, acct_type,
                    account_number=number, parent_id=parent_id,
                    description=description, sidebar=sidebar,
                )
            else:
                update_account(
                    self.con, self.account["id"], name, acct_type,
                    account_number=number, parent_id=parent_id,
                    description=description, sidebar=sidebar,
                )

            self.dismiss(True)

        except Exception as e:
            self.query_one("#af-error", Label).update(f"Error: {e}")

    def _generate_unique_id(self, name, parent_id=None):
        """Generate a unique slug ID, prefixed by parent slug on child accounts."""
        base = slugify(name)
        if parent_id:
            base = f"{parent_id}__{base}"
        candidate = base
        suffix = 1
        while True:
            existing = self.con.execute(
                "SELECT 1 FROM accounts WHERE id = ?", (candidate,)
            ).fetchone()
            if existing is None:
                return candidate
            candidate = f"{base}_{suffix}"
            suffix += 1

    def action_cancel(self):
        self.dismiss(False)


class SavePdfDialog(ModalScreen):
    """Dialog to choose Color or B&W PDF output."""

    BINDINGS = [
        Binding("c", "color", "Color", show=False),
        Binding("b", "bw", "B&W", show=False),
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = SAVE_PDF_CSS

    def compose(self):
        with Vertical(id="sp-dialog"):
            yield Label("Save PDF", id="sp-title")
            with Horizontal(id="sp-buttons"):
                yield Button("Color", variant="primary", id="sp-color")
                yield Button("B&W", id="sp-bw")

    @on(Button.Pressed, "#sp-color")
    def on_color(self, event):
        self.dismiss("color")

    @on(Button.Pressed, "#sp-bw")
    def on_bw(self, event):
        self.dismiss("bw")

    def action_color(self):
        self.dismiss("color")

    def action_bw(self):
        self.dismiss("bw")

    def action_cancel(self):
        self.dismiss(None)


class ConfirmOverwriteScreen(ModalScreen):
    """Confirmation dialog when a report file already exists."""

    BINDINGS = [
        Binding("y", "confirm", "Yes", show=False),
        Binding("n", "cancel", "No", show=False),
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = CONFIRM_OVERWRITE_CSS
    AUTO_FOCUS = "#co-no"

    def __init__(self, path):
        super().__init__()
        self.path = path

    def compose(self):
        with Vertical(id="co-dialog"):
            yield Label("File Already Exists", id="co-title")
            yield Label(
                f"Overwrite {self.path}?",
                id="co-message",
                shrink=True,
            )
            with Horizontal(id="co-buttons"):
                yield Button("Overwrite", variant="warning", id="co-yes")
                yield Button("Cancel", id="co-no")

    @on(Button.Pressed, "#co-yes")
    def on_yes(self, event):
        self.dismiss(True)

    @on(Button.Pressed, "#co-no")
    def on_no(self, event):
        self.dismiss(False)

    def action_confirm(self):
        self.dismiss(True)

    def action_cancel(self):
        self.dismiss(False)


class ConfirmDeleteScreen(ModalScreen):
    """Confirmation dialog for deleting an account."""

    BINDINGS = [
        Binding("y", "confirm", "Yes", show=False),
        Binding("n", "cancel", "No", show=False),
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = CONFIRM_DELETE_CSS
    AUTO_FOCUS = "#cd-no"

    def __init__(self, con, account):
        super().__init__()
        self.con = con
        self.account = account

    def compose(self):
        with Vertical(id="cd-dialog"):
            yield Label("Delete Account", id="cd-title")
            yield Label(
                f"Delete \"{self.account['name']}\"?",
                id="cd-message",
            )
            with Horizontal(id="cd-buttons"):
                yield Button("Delete", variant="error", id="cd-yes")
                yield Button("Cancel", id="cd-no")

    @on(Button.Pressed, "#cd-yes")
    def on_yes(self, event):
        self.action_confirm()

    @on(Button.Pressed, "#cd-no")
    def on_no(self, event):
        self.dismiss(False)

    def action_confirm(self):
        try:
            delete_account(self.con, self.account["id"])
            self.dismiss(True)
        except Exception as e:
            self.app.notify(f"Error: {e}", severity="error")
            self.dismiss(False)

    def action_cancel(self):
        self.dismiss(False)


class ConfirmDeleteTransactionScreen(ModalScreen):
    """Confirmation dialog for deleting a transaction."""

    BINDINGS = [
        Binding("y", "confirm", "Yes", show=False),
        Binding("n", "cancel", "No", show=False),
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = CONFIRM_DELETE_TX_CSS
    AUTO_FOCUS = "#cd-no"

    def __init__(self, tx_date, tx_desc):
        super().__init__()
        self.tx_date = tx_date
        self.tx_desc = tx_desc

    def compose(self):
        with Vertical(id="cd-dialog"):
            yield Label("Delete Transaction", id="cd-title")
            yield Label(
                f"Delete \"{self.tx_desc}\" on {format_date_long(self.tx_date)}?",
                shrink=True,
                id="cd-message",
            )
            with Horizontal(id="cd-buttons"):
                yield Button("Delete", variant="error", id="cd-yes")
                yield Button("Cancel", id="cd-no")

    @on(Button.Pressed, "#cd-yes")
    def on_yes(self, event):
        self.dismiss(True)

    @on(Button.Pressed, "#cd-no")
    def on_no(self, event):
        self.dismiss(False)

    def action_confirm(self):
        self.dismiss(True)

    def action_cancel(self):
        self.dismiss(False)


class AddTransactionScreen(TransactionFormBase):
    """Modal for creating a new transaction with arbitrary splits."""

    def __init__(self, con, account_filter=None):
        super().__init__(con)
        self.account_filter = account_filter
        self._next_split_id = 2
        self._alive_splits = [0, 1]

    def compose(self):
        vendor_options = [(v["name"], v["id"]) for v in get_all_vendors(self.con)]

        # Pre-fill first split account from filter if present
        acct_name_0 = "Select account..."
        split0_dir = "DR"
        if self.account_filter:
            from pyre.ui.import_screen import _build_account_options
            acct_labels = {aid: lbl for lbl, aid in _build_account_options(self.con)}
            self._split_account_ids[0] = self.account_filter["id"]
            acct_name_0 = acct_labels.get(self.account_filter["id"],
                                          self.account_filter.get("name", "Select account..."))
            row = self.con.execute(
                "SELECT type FROM accounts WHERE id = ?",
                (self.account_filter["id"],),
            ).fetchone()
            if row:
                acct_type = row[0]
                self._split_account_types[0] = acct_type
                split0_dir = normal_balance_direction(acct_type)
        else:
            self._split_account_ids[0] = None
        self._split_account_ids[1] = None

        with VerticalScroll(id="at-dialog"):
            yield Label("Add Transaction", id="at-title")

            with Horizontal(classes="at-date-vendor-row"):
                with Vertical(classes="at-date-col"):
                    yield Label("Date:", classes="at-field-label")
                    yield DateInput(
                        value=format_date(date.today().isoformat()),
                        placeholder="M/D, M/D/YY, or MM-DD-YYYY",
                        id="at-date",
                        classes="at-input",
                    )
                if vendor_options:
                    with Vertical(classes="at-vendor-col"):
                        yield Label("Vendor:", classes="at-field-label")
                        yield Select(vendor_options, allow_blank=True, id="at-vendor", classes="at-input")

            yield Label("Description:", classes="at-field-label")
            yield Input(placeholder="Transaction description", id="at-desc", classes="at-input")

            yield Label("Splits:", classes="at-field-label")
            with Vertical(id="at-splits-container"):
                for i in self._alive_splits:
                    self.split_directions[i] = split0_dir if i == 0 else ("CR" if split0_dir == "DR" else "DR")
                    btn_label = acct_name_0 if i == 0 else "Select account..."
                    with Horizontal(classes="at-split-row", id=f"at-split-row-{i}"):
                        yield Button(
                            btn_label,
                            id=f"at-split-account-{i}",
                            classes="at-split-account",
                        )
                        yield Input(
                            placeholder="0.00",
                            id=f"at-split-amount-{i}",
                            classes="at-split-amount at-input",
                        )
                        yield Button(
                            self.split_directions[i],
                            id=f"at-split-dir-{i}",
                            classes="at-split-dir",
                        )
                        yield Button(
                            "X",
                            id=f"at-split-remove-{i}",
                            classes="at-split-remove",
                            disabled=True,
                        )
                    with Horizontal(classes="at-split-memo-row hidden", id=f"at-split-memo-{i}"):
                        yield Input(placeholder="Description (optional)", id=f"at-split-memo-input-{i}")

            with Horizontal(id="at-add-split-row"):
                yield Button("+ Add Split", id="at-add-split")
                yield Button("+ Desc", id="at-toggle-memos")

            yield Label("", id="at-balance")
            yield Label("", id="at-error")
            with Horizontal(id="at-buttons"):
                yield Button("Save", variant="primary", id="at-save")
                yield Button("Cancel", id="at-cancel-btn")
            yield Label("\\[Ctrl+S] Save  \\[Ctrl+D] Descriptions", id="at-hint")

    def on_mount(self):
        self._base_mount()

    def _save(self):
        try:
            dt = parse_date(self.query_one("#at-date", Input).value)
            description = self.query_one("#at-desc", Input).value.strip()

            splits = []
            for n, i in enumerate(self._alive_splits):
                acct_id = self._split_account_ids.get(i)
                amount_input = self.query_one(f"#at-split-amount-{i}", Input)

                if not acct_id:
                    self.query_one("#at-error", Label).update(
                        f"Error: Split {n + 1} has no account selected"
                    )
                    return
                val = amount_input.value.strip()
                if not val:
                    self.query_one("#at-error", Label).update(
                        f"Error: Split {n + 1} has no amount"
                    )
                    return
                c = cents(val)
                if self.split_directions.get(i) == "CR":
                    c = -c
                split_desc = ""
                try:
                    split_desc = self.query_one(f"#at-split-memo-input-{i}", Input).value.strip()
                except NoMatches:
                    pass
                splits.append((acct_id, c, split_desc))

            vendor_id = None
            try:
                vendor_select = self.query_one("#at-vendor", Select)
                if vendor_select.value is not Select.NULL:
                    vendor_id = vendor_select.value
            except NoMatches:
                pass

            post_transaction(self.con, dt, description, splits,
                             vendor_id=vendor_id)
            self.dismiss("posted")

        except Exception as e:
            self.query_one("#at-error", Label).update(f"Error: {e}")


class VendorListScreen(ModalScreen):
    """Modal screen listing all vendors with CRUD."""

    BINDINGS = [
        Binding("j", "cursor_down", "Nav Down", show=False),
        Binding("k", "cursor_up", "Nav Up", show=False),
        Binding("g", "cursor_top", "Top", show=False),
        Binding("G", "cursor_bottom", "Bottom", show=False),
        Binding("a", "add_vendor", "Add", show=False),
        Binding("e", "edit_vendor", "Edit", show=False),
        Binding("d", "delete_vendor", "Delete", show=False),
        Binding("slash", "open_search", "Search", show=False),
        Binding("q", "close", "Close", show=False),
        Binding("escape", "close_or_clear", "Close", show=False),
    ]

    DEFAULT_CSS = VENDOR_LIST_CSS

    def __init__(self, con):
        super().__init__()
        self.con = con
        self.search_active = False
        self.search_query = ""
        self._vendors = []
        self._row_vendors = {}

    def compose(self):
        with Vertical(id="vl-container"):
            yield Label("Vendors", id="vl-title")
            yield DataTable(id="vl-table", cursor_type="row")
            with Horizontal(id="vl-search-bar"):
                yield Label("/", id="vl-search-prompt")
                yield Input(
                    placeholder="Search vendors...",
                    id="vl-search-input",
                )
                yield Label("", id="vl-search-count")
            yield Label(
                "\\[A] Add  \\[E] Edit  \\[D] Delete  \\[/] Search  \\[Q] Close",
                id="vl-hint",
            )

    def on_mount(self):
        table = self.query_one("#vl-table", DataTable)
        table.add_columns("Name", "Transactions")
        self._refresh_rows()

    def _populate_table(self):
        self._refresh_rows()

    def _refresh_rows(self):
        table = self.query_one("#vl-table", DataTable)
        table.clear()
        self._row_vendors = {}

        self._vendors = get_all_vendors(self.con)
        filtered = self._vendors
        if self.search_query:
            q = self.search_query.lower()
            filtered = [v for v in filtered if q in v["name"].lower()]

        for i, v in enumerate(filtered):
            key = f"vl_{i}"
            tx_count = get_vendor_transaction_count(self.con, v["id"])
            table.add_row(v["name"], str(tx_count), key=key)
            self._row_vendors[key] = v

        if self.search_active:
            self.query_one("#vl-search-count", Label).update(
                f"{len(filtered)} of {len(self._vendors)}"
            )

    def action_cursor_down(self):
        self.query_one("#vl-table", DataTable).action_cursor_down()

    def action_cursor_up(self):
        self.query_one("#vl-table", DataTable).action_cursor_up()

    def action_cursor_top(self):
        self.query_one("#vl-table", DataTable).move_cursor(row=0)

    def action_cursor_bottom(self):
        table = self.query_one("#vl-table", DataTable)
        table.move_cursor(row=table.row_count - 1)

    def action_close(self):
        self.dismiss()

    def _get_selected_vendor(self):
        table = self.query_one("#vl-table", DataTable)
        if table.row_count == 0:
            return None
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        return self._row_vendors.get(str(row_key.value))

    def action_add_vendor(self):
        def on_dismiss(result):
            if result:
                self._populate_table()

        self.app.push_screen(VendorFormScreen(self.con), callback=on_dismiss)

    def action_edit_vendor(self):
        vendor = self._get_selected_vendor()
        if not vendor:
            return

        def on_dismiss(result):
            if result:
                self._populate_table()

        self.app.push_screen(
            VendorFormScreen(self.con, mode="edit", vendor=vendor),
            callback=on_dismiss,
        )

    def action_delete_vendor(self):
        vendor = self._get_selected_vendor()
        if not vendor:
            return

        tx_count = get_vendor_transaction_count(self.con, vendor["id"])
        if tx_count > 0:
            msg = (
                f"Vendor \"{vendor['name']}\" is linked to {tx_count} "
                f"transaction(s). Deleting will unlink them. Continue?"
            )
        else:
            msg = f"Delete vendor \"{vendor['name']}\"?"

        def on_confirm(confirmed):
            if confirmed:
                delete_vendor(self.con, vendor["id"])
                self._populate_table()

        self.app.push_screen(
            ConfirmDeleteVendorScreen(vendor["name"], msg),
            callback=on_confirm,
        )

    def action_open_search(self):
        bar = self.query_one("#vl-search-bar")
        bar.add_class("visible")
        self.search_active = True
        search_input = self.query_one("#vl-search-input", Input)
        search_input.value = self.search_query
        search_input.focus()

    @on(Input.Changed, "#vl-search-input")
    def on_search_changed(self, event):
        self.search_query = event.value.strip()
        self._populate_table()

    @on(Input.Submitted, "#vl-search-input")
    def on_search_submitted(self, event):
        bar = self.query_one("#vl-search-bar")
        bar.remove_class("visible")
        self.search_active = False
        self.query_one("#vl-table", DataTable).focus()

    def action_close_or_clear(self):
        if self.search_active:
            bar = self.query_one("#vl-search-bar")
            bar.remove_class("visible")
            self.search_active = False
            self.search_query = ""
            self._populate_table()
            self.query_one("#vl-table", DataTable).focus()
        else:
            self.dismiss()


class VendorFormScreen(ModalScreen):
    """Modal for adding or editing a vendor."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = VENDOR_FORM_CSS

    def __init__(self, con, mode="add", vendor=None):
        super().__init__()
        self.con = con
        self.mode = mode
        self.vendor = vendor

    def compose(self):
        title = "Edit Vendor" if self.mode == "edit" else "Add Vendor"
        with Vertical(id="vf-dialog"):
            yield Label(title, id="vf-title")
            yield Label("Name:", classes="vf-field-label")
            yield Input(
                value=self.vendor["name"] if self.vendor else "",
                placeholder="Vendor name",
                id="vf-name",
                classes="vf-input",
            )
            yield Label("", id="vf-error")
            with Horizontal(id="vf-buttons"):
                yield Button("Save", variant="primary", id="vf-save")
                yield Button("Cancel", id="vf-cancel-btn")

    def on_mount(self):
        self.query_one("#vf-name", Input).focus()

    @on(Input.Submitted)
    def handle_submit(self, event):
        self._save()

    @on(Button.Pressed)
    def on_button_pressed(self, event):
        if event.button.id == "vf-save":
            self._save()
        elif event.button.id == "vf-cancel-btn":
            self.dismiss(False)

    def _save(self):
        name = self.query_one("#vf-name", Input).value.strip()
        if not name:
            self.query_one("#vf-error", Label).update("Name is required")
            return

        try:
            if self.mode == "edit":
                update_vendor(self.con, self.vendor["id"], name)
            else:
                vendor_id = slugify(name)
                # Ensure uniqueness
                suffix = 0
                base_id = vendor_id
                while get_vendor_by_id(self.con, vendor_id) is not None:
                    suffix += 1
                    vendor_id = f"{base_id}_{suffix}"
                create_vendor(self.con, vendor_id, name)
            self.dismiss(True)
        except Exception as e:
            self.query_one("#vf-error", Label).update(f"Error: {e}")

    def action_cancel(self):
        self.dismiss(False)


class ConfirmDeleteVendorScreen(ModalScreen):
    """Confirmation dialog for deleting a vendor."""

    BINDINGS = [
        Binding("y", "confirm", "Yes", show=False),
        Binding("n", "cancel", "No", show=False),
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = CONFIRM_DELETE_VENDOR_CSS
    AUTO_FOCUS = "#cdv-no"

    def __init__(self, vendor_name, message):
        super().__init__()
        self.vendor_name = vendor_name
        self.message = message

    def compose(self):
        with Vertical(id="cdv-dialog"):
            yield Label("Delete Vendor", id="cdv-title")
            yield Label(self.message, shrink=True, id="cdv-message")
            with Horizontal(id="cdv-buttons"):
                yield Button("Delete", variant="error", id="cdv-yes")
                yield Button("Cancel", id="cdv-no")

    @on(Button.Pressed, "#cdv-yes")
    def on_yes(self, event):
        self.action_confirm()

    @on(Button.Pressed, "#cdv-no")
    def on_no(self, event):
        self.dismiss(False)

    def action_confirm(self):
        self.dismiss(True)

    def action_cancel(self):
        self.dismiss(False)


class BulkEditScreen(ModalScreen):
    """Modal for bulk-editing selected transactions (vendor assignment)."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = BULK_EDIT_CSS

    def __init__(self, tx_ids, con):
        super().__init__()
        self.tx_ids = tx_ids
        self.con = con

    def compose(self):
        vendors = get_all_vendors(self.con)
        vendor_options = [(v["name"], v["id"]) for v in vendors]
        with Vertical(id="be-dialog"):
            yield Label(f"Bulk Edit - {len(self.tx_ids)} transactions", id="be-title")
            yield Label("Vendor")
            yield Select(vendor_options, allow_blank=True, id="be-vendor")
            yield Label("(leave blank to clear vendor)", id="be-hint")
            with Horizontal(id="be-buttons"):
                yield Button("Save", variant="primary", id="be-save")
                yield Button("Cancel", id="be-cancel")

    @on(Button.Pressed, "#be-save")
    def on_save(self, event):
        from pyre.models import bulk_set_vendor
        vendor_select = self.query_one("#be-vendor", Select)
        vendor_id = vendor_select.value
        if vendor_id is Select.NULL:
            vendor_id = None
        bulk_set_vendor(self.con, self.tx_ids, vendor_id)
        self.dismiss(True)

    @on(Button.Pressed, "#be-cancel")
    def on_cancel(self, event):
        self.action_cancel()

    def action_cancel(self):
        self.dismiss(None)


class ExpensesByVendorScreen(ModalScreen):
    """Modal screen to view Expenses by Vendor Summary report."""

    BINDINGS = [
        Binding("j", "cursor_down", "Nav Down", show=False),
        Binding("k", "cursor_up", "Nav Up", show=False),
        Binding("g", "cursor_top", "Top", show=False),
        Binding("G", "cursor_bottom", "Bottom", show=False),
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
        Binding("ctrl+s", "save_pdf", "Save PDF"),
    ]

    DEFAULT_CSS = EXPENSES_BY_VENDOR_CSS

    def __init__(self, con, start_date, end_date):
        super().__init__()
        self.con = con
        self.start_date = start_date
        self.end_date = end_date

    def compose(self):
        with Vertical(id="evs-container"):
            yield Label("Expenses by Vendor Summary", id="evs-title")
            yield Label(
                f"{format_date(self.start_date)} to {format_date(self.end_date)}",
                id="evs-subtitle",
            )
            yield DataTable(id="evs-table", show_header=True, cursor_type="row")
            yield Label(
                "\\[Ctrl+S] Save PDF  \\[Q] Close",
                id="evs-hint",
            )

    def on_mount(self):
        self._populate_table()

    def _populate_table(self):
        table = self.query_one("#evs-table", DataTable)
        table.add_columns("Vendor", "Total")

        data = generate_expenses_by_vendor(
            self.con, self.start_date, self.end_date,
        )

        for vendor in data["vendors"]:
            table.add_row(vendor["name"], fmt(vendor["total"]))

        # Blank separator
        table.add_row("", "")

        # Grand total
        table.add_row(
            Text("TOTAL", style="bold"),
            Text(fmt(data["grand_total"]), style="bold"),
        )

    def action_cursor_down(self):
        self.query_one("#evs-table", DataTable).action_cursor_down()

    def action_cursor_up(self):
        self.query_one("#evs-table", DataTable).action_cursor_up()

    def action_cursor_top(self):
        self.query_one("#evs-table", DataTable).move_cursor(row=0)

    def action_cursor_bottom(self):
        table = self.query_one("#evs-table", DataTable)
        table.move_cursor(row=table.row_count - 1)

    def action_close(self):
        self.dismiss()

    def action_save_pdf(self):
        """Export the Expenses by Vendor Summary as a PDF."""
        output_path = resolve_report_path(
            self.app._preferences, "expenses_by_vendor", self.end_date,
            start_date=self.start_date, end_date=self.end_date,
        )
        if output_path is None:
            output_path = (
                Path.cwd()
                / f"expenses_by_vendor_{self.start_date}_to_{self.end_date}.pdf"
            )
        _save_report_pdf(self, output_path, lambda p, c: export_expenses_by_vendor_pdf(
            self.con, self.start_date, self.end_date, p, color=c,
        ))


class ReconciliationReportPickerScreen(ModalScreen):
    """Modal listing all past reconciliations for viewing reports."""

    BINDINGS = [
        Binding("j", "cursor_down", "Nav Down", show=False),
        Binding("k", "cursor_up", "Nav Up", show=False),
        Binding("g", "cursor_top", "Top", show=False),
        Binding("G", "cursor_bottom", "Bottom", show=False),
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
    ]

    DEFAULT_CSS = RECONCILIATION_PICKER_CSS

    def __init__(self, con):
        super().__init__()
        self.con = con

    def compose(self):
        with Vertical(id="rrp-container"):
            yield Label("Reconciliation Reports", id="rrp-title")
            yield DataTable(id="rrp-table", show_header=True, cursor_type="row")
            yield Label(
                "\\[Enter] View Report  \\[Q] Close",
                id="rrp-hint",
            )

    def on_mount(self):
        self._populate_table()

    def _populate_table(self):
        table = self.query_one("#rrp-table", DataTable)
        table.add_columns("Account", "Statement Date", "Balance", "Items", "Reconciled At")

        from pyre.db import LIABILITY_TYPES
        recs = get_all_reconciliations(self.con)
        self._recs = recs

        for rec in recs:
            acct_type = self.con.execute(
                "SELECT type FROM accounts WHERE id = ?",
                (rec["account_id"],),
            ).fetchone()
            negate = acct_type and acct_type[0] in LIABILITY_TYPES
            display_bal = -rec["statement_balance"] if negate else rec["statement_balance"]

            reconciled_at = rec["reconciled_at"]
            if "T" in reconciled_at:
                reconciled_at = reconciled_at.split("T")[0]

            table.add_row(
                rec["account_name"],
                format_date(rec["statement_date"]),
                fmt(display_bal),
                str(rec["split_count"]),
                format_date(reconciled_at),
                key=rec["id"],
            )

        if not recs:
            table.add_row("No reconciliations found", "", "", "", "")

    @on(DataTable.RowSelected, "#rrp-table")
    def on_row_selected(self, event):
        rec_id = str(event.row_key.value)
        if not self._recs:
            return
        self.dismiss(rec_id)

    def action_cursor_down(self):
        self.query_one("#rrp-table", DataTable).action_cursor_down()

    def action_cursor_up(self):
        self.query_one("#rrp-table", DataTable).action_cursor_up()

    def action_cursor_top(self):
        self.query_one("#rrp-table", DataTable).move_cursor(row=0)

    def action_cursor_bottom(self):
        table = self.query_one("#rrp-table", DataTable)
        table.move_cursor(row=table.row_count - 1)

    def action_close(self):
        self.dismiss(None)


class ReconciliationReportScreen(ModalScreen):
    """Modal DataTable showing a reconciliation report with PDF export."""

    BINDINGS = [
        Binding("j", "cursor_down", "Nav Down", show=False),
        Binding("k", "cursor_up", "Nav Up", show=False),
        Binding("g", "cursor_top", "Top", show=False),
        Binding("G", "cursor_bottom", "Bottom", show=False),
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
        Binding("ctrl+s", "save_pdf", "Save PDF"),
    ]

    DEFAULT_CSS = RECONCILIATION_REPORT_CSS

    def __init__(self, con, reconciliation_id):
        super().__init__()
        self.con = con
        self.reconciliation_id = reconciliation_id

    def compose(self):
        with Vertical(id="rr-container"):
            yield Label("Reconciliation Report", id="rr-title")
            yield Label("", id="rr-subtitle")
            yield DataTable(id="rr-table", show_header=True, cursor_type="row")
            yield Label(
                "\\[Ctrl+S] Save PDF  \\[Q] Close",
                id="rr-hint",
            )

    def on_mount(self):
        self._populate_table()

    def _populate_table(self):
        data = generate_reconciliation_report(self.con, self.reconciliation_id)
        if not data:
            return

        self._data = data
        negate = data["negate"]

        def _display(amount):
            return -amount if negate else amount

        subtitle = self.query_one("#rr-subtitle", Label)
        subtitle.update(
            f"{data['account_name']} - Statement Date: "
            f"{format_date(data['statement_date'])}"
        )

        table = self.query_one("#rr-table", DataTable)
        table.add_columns("Date", "Description", "Amount")

        # Summary
        table.add_row(
            Text("SUMMARY", style="bold"), "", "",
            key="_summary_header",
        )
        table.add_row(
            "", "Beginning Balance",
            Text(fmt(_display(data["beginning_balance"])), style="bold"),
            key="_beginning",
        )
        table.add_row(
            "", "Statement Ending Balance",
            Text(fmt(_display(data["statement_balance"])), style="bold"),
            key="_ending",
        )
        table.add_row("", "", "", key="_sep1")

        # Section headings depend on account type
        if negate:
            # Credit card / liability: charges first, then payments
            sections = [
                ("CHARGES AND CASH ADVANCES CLEARED", "Total Charges and Cash Advances",
                 data["cleared_credits"], data["credit_total"], "credit"),
                ("PAYMENTS AND CREDITS CLEARED", "Total Payments and Credits",
                 data["cleared_debits"], data["debit_total"], "debit"),
            ]
        else:
            # Bank / asset: deposits first, then checks
            sections = [
                ("DEPOSITS AND OTHER CREDITS CLEARED", "Total Deposits and Credits",
                 data["cleared_debits"], data["debit_total"], "debit"),
                ("CHECKS AND PAYMENTS CLEARED", "Total Checks and Payments",
                 data["cleared_credits"], data["credit_total"], "credit"),
            ]

        for sec_idx, (header, total_label, items, total, prefix) in enumerate(sections):
            table.add_row(
                Text(header, style="bold"), "", "",
                key=f"_{prefix}_header",
            )
            for i, item in enumerate(items):
                desc = item["description"]
                if item["vendor_name"]:
                    desc += f" ({item['vendor_name']})"
                table.add_row(
                    format_date(item["date"]),
                    desc,
                    fmt(_display(item["amount"])),
                    key=f"_{prefix}_{i}",
                )
            table.add_row(
                "", Text(total_label, style="bold"),
                Text(fmt(_display(total)), style="bold"),
                key=f"_{prefix}_total",
            )
            table.add_row("", "", "", key=f"_sep{sec_idx + 2}")

        # Cleared total
        table.add_row(
            "", Text("CLEARED BALANCE", style="bold"),
            Text(fmt(_display(data["cleared_total"])), style="bold"),
            key="_cleared_total",
        )

        # Uncleared items
        if data["uncleared_items"]:
            table.add_row("", "", "", key="_sep4")
            table.add_row(
                Text("UNCLEARED TRANSACTIONS", style="bold"), "", "",
                key="_uncleared_header",
            )
            for i, item in enumerate(data["uncleared_items"]):
                desc = item["description"]
                if item["vendor_name"]:
                    desc += f" ({item['vendor_name']})"
                table.add_row(
                    format_date(item["date"]),
                    desc,
                    fmt(_display(item["amount"])),
                    key=f"_uncleared_{i}",
                )
            table.add_row(
                "", Text("Total Uncleared", style="bold"),
                Text(fmt(_display(data["uncleared_total"])), style="bold"),
                key="_uncleared_total",
            )

        # Register balance
        table.add_row("", "", "", key="_sep5")
        table.add_row(
            "", Text("REGISTER BALANCE", style="bold"),
            Text(fmt(_display(data["register_balance"])), style="bold"),
            key="_register",
        )

    def action_cursor_down(self):
        self.query_one("#rr-table", DataTable).action_cursor_down()

    def action_cursor_up(self):
        self.query_one("#rr-table", DataTable).action_cursor_up()

    def action_cursor_top(self):
        self.query_one("#rr-table", DataTable).move_cursor(row=0)

    def action_cursor_bottom(self):
        table = self.query_one("#rr-table", DataTable)
        table.move_cursor(row=table.row_count - 1)

    def action_close(self):
        self.dismiss()

    def action_save_pdf(self):
        """Export the Reconciliation Report as a PDF."""
        data = self._data
        output_path = resolve_report_path(
            self.app._preferences, "reconciliation",
            data["statement_date"],
            account_name=data["account_name"],
        )
        if output_path is None:
            output_path = (
                Path.cwd()
                / f"reconciliation_{data['account_name']}_{data['statement_date']}.pdf"
            )
        _save_report_pdf(self, output_path, lambda p, c: export_reconciliation_report_pdf(
            self.con, self.reconciliation_id, p, color=c,
        ))
