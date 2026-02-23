"""Screens for scheduled transaction management and pending review."""

from datetime import date
from decimal import InvalidOperation

from textual import on
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, Select, Switch

from pyre.account_utils import normal_balance_direction
from pyre.dates import DateInput, parse_date
from pyre.formatting import cents, fmt, format_date
from pyre.scheduled_models import (
    create_scheduled_transaction,
    delete_scheduled_transaction,
    enter_pending_transactions,
    get_all_scheduled_transactions,
    get_pending_scheduled_transactions,
    get_scheduled_transaction_detail,
    toggle_scheduled_enabled,
    update_scheduled_transaction,
)
from pyre.vendor_models import get_all_vendors
from pyre.ui.screens import AccountFuzzyPickScreen
from pyre.ui.styles import (
    ADD_TRANSACTION_CSS,
    CONFIRM_DELETE_SCHEDULED_CSS,
    PENDING_SCHEDULED_CSS,
    SCHEDULED_FORM_CSS,
    SCHEDULED_LIST_CSS,
)


FREQUENCY_OPTIONS = [
    ("Weekly", "weekly"),
    ("Biweekly", "biweekly"),
    ("Monthly", "monthly"),
    ("Quarterly", "quarterly"),
    ("Yearly", "yearly"),
]

FREQUENCY_DISPLAY = dict((v, k) for k, v in FREQUENCY_OPTIONS)


class PendingScheduledScreen(ModalScreen):
    """Review screen for due scheduled transactions shown on launch."""

    BINDINGS = [
        Binding("j", "cursor_down", "Nav Down", show=False),
        Binding("k", "cursor_up", "Nav Up", show=False),
        Binding("space", "toggle_skip", "Skip/Include", show=False),
        Binding("escape", "close", "Close"),
    ]

    DEFAULT_CSS = PENDING_SCHEDULED_CSS

    def __init__(self, con):
        super().__init__()
        self.con = con
        self._pending = []
        self._skipped = set()
        self._row_map = {}

    def compose(self):
        with Vertical(id="ps-container"):
            yield Label("Scheduled Transactions Due", id="ps-title")
            yield DataTable(id="ps-table", cursor_type="row")
            yield Label(
                "\\[Space] Toggle skip  \\[Enter] Post selected  \\[Esc] Close",
                id="ps-hint",
            )
            with Horizontal(id="ps-buttons"):
                yield Button("Post All", variant="primary", id="ps-post")
                yield Button("Skip All", id="ps-skip-all")
                yield Button("Close", id="ps-close")

    def on_mount(self):
        self._pending = get_pending_scheduled_transactions(self.con)
        table = self.query_one("#ps-table", DataTable)
        table.add_columns("", "Date", "Description", "Frequency", "Amount")
        self._refresh_rows()

    def _refresh_rows(self):
        table = self.query_one("#ps-table", DataTable)
        table.clear()
        self._row_map = {}
        for i, p in enumerate(self._pending):
            key = f"ps_{i}"
            check = "  " if p["id"] in self._skipped else ">>>"
            table.add_row(
                check,
                format_date(p["next_date"]),
                p["description"],
                FREQUENCY_DISPLAY.get(p["frequency"], p["frequency"]),
                fmt(p["amount"]),
                key=key,
            )
            self._row_map[key] = p

    def action_cursor_down(self):
        self.query_one("#ps-table", DataTable).action_cursor_down()

    def action_cursor_up(self):
        self.query_one("#ps-table", DataTable).action_cursor_up()

    def action_toggle_skip(self):
        table = self.query_one("#ps-table", DataTable)
        if table.row_count == 0:
            return
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        p = self._row_map.get(str(row_key.value))
        if not p:
            return
        if p["id"] in self._skipped:
            self._skipped.discard(p["id"])
        else:
            self._skipped.add(p["id"])
        self._refresh_rows()

    @on(Button.Pressed, "#ps-post")
    def on_post(self):
        ids = [p["id"] for p in self._pending if p["id"] not in self._skipped]
        if not ids:
            self.dismiss({"posted": 0})
            return
        posted = enter_pending_transactions(self.con, ids)
        self.dismiss({"posted": len(posted)})

    @on(Button.Pressed, "#ps-skip-all")
    def on_skip_all(self):
        self.dismiss({"posted": 0})

    @on(Button.Pressed, "#ps-close")
    def on_close(self):
        self.dismiss({"posted": 0})

    def action_close(self):
        self.dismiss({"posted": 0})

    @on(DataTable.RowSelected, "#ps-table")
    def on_row_selected(self):
        self.on_post()


class ScheduledListScreen(ModalScreen):
    """Modal screen listing all scheduled transactions with CRUD."""

    BINDINGS = [
        Binding("j", "cursor_down", "Nav Down", show=False),
        Binding("k", "cursor_up", "Nav Up", show=False),
        Binding("g", "cursor_top", "Top", show=False),
        Binding("G", "cursor_bottom", "Bottom", show=False),
        Binding("a", "add_scheduled", "Add", show=False),
        Binding("e", "edit_scheduled", "Edit", show=False),
        Binding("d", "delete_scheduled", "Delete", show=False),
        Binding("t", "toggle_enabled", "Toggle", show=False),
        Binding("slash", "open_search", "Search", show=False),
        Binding("q", "close", "Close", show=False),
        Binding("escape", "close_or_clear", "Close", show=False),
    ]

    DEFAULT_CSS = SCHEDULED_LIST_CSS

    def __init__(self, con):
        super().__init__()
        self.con = con
        self.search_active = False
        self.search_query = ""
        self._schedules = []
        self._row_map = {}

    def compose(self):
        with Vertical(id="sl-container"):
            yield Label("Scheduled Transactions", id="sl-title")
            yield DataTable(id="sl-table", cursor_type="row")
            with Horizontal(id="sl-search-bar"):
                yield Label("/", id="sl-search-prompt")
                yield Input(
                    placeholder="Search scheduled...",
                    id="sl-search-input",
                )
                yield Label("", id="sl-search-count")
            yield Label(
                "\\[A] Add  \\[E] Edit  \\[D] Delete  \\[T] Toggle  \\[/] Search  \\[Q] Close",
                id="sl-hint",
            )

    def on_mount(self):
        table = self.query_one("#sl-table", DataTable)
        table.add_columns(
            "Enabled", "Description", "Vendor", "Frequency",
            "Next Date", "Amount",
        )
        self._refresh_rows()

    def _refresh_rows(self):
        table = self.query_one("#sl-table", DataTable)
        table.clear()
        self._row_map = {}

        self._schedules = get_all_scheduled_transactions(self.con)
        filtered = self._schedules
        if self.search_query:
            q = self.search_query.lower()
            filtered = [
                s for s in filtered
                if q in s["description"].lower()
                or q in s["vendor_name"].lower()
                or q in s["frequency"].lower()
            ]

        for i, s in enumerate(filtered):
            key = f"sl_{i}"
            enabled = "Yes" if s["enabled"] else "No"
            table.add_row(
                enabled,
                s["description"],
                s["vendor_name"],
                FREQUENCY_DISPLAY.get(s["frequency"], s["frequency"]),
                format_date(s["next_date"]),
                fmt(s["amount"]),
                key=key,
            )
            self._row_map[key] = s

        if self.search_active:
            self.query_one("#sl-search-count", Label).update(
                f"{len(filtered)} of {len(self._schedules)}"
            )

    def _get_selected(self):
        table = self.query_one("#sl-table", DataTable)
        if table.row_count == 0:
            return None
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        return self._row_map.get(str(row_key.value))

    def action_cursor_down(self):
        self.query_one("#sl-table", DataTable).action_cursor_down()

    def action_cursor_up(self):
        self.query_one("#sl-table", DataTable).action_cursor_up()

    def action_cursor_top(self):
        self.query_one("#sl-table", DataTable).move_cursor(row=0)

    def action_cursor_bottom(self):
        table = self.query_one("#sl-table", DataTable)
        table.move_cursor(row=table.row_count - 1)

    def action_close(self):
        self.dismiss()

    def action_close_or_clear(self):
        if self.search_active:
            bar = self.query_one("#sl-search-bar")
            bar.remove_class("visible")
            self.search_active = False
            self.search_query = ""
            self._refresh_rows()
            self.query_one("#sl-table", DataTable).focus()
        else:
            self.dismiss()

    def action_add_scheduled(self):
        def on_dismiss(result):
            if result:
                self._refresh_rows()

        self.app.push_screen(ScheduledFormScreen(self.con), callback=on_dismiss)

    def action_edit_scheduled(self):
        s = self._get_selected()
        if not s:
            return

        def on_dismiss(result):
            if result:
                self._refresh_rows()

        self.app.push_screen(
            ScheduledFormScreen(self.con, mode="edit", st_id=s["id"]),
            callback=on_dismiss,
        )

    @on(DataTable.RowSelected, "#sl-table")
    def on_row_selected(self):
        self.action_edit_scheduled()

    def action_delete_scheduled(self):
        s = self._get_selected()
        if not s:
            return

        def on_confirm(confirmed):
            if confirmed:
                delete_scheduled_transaction(self.con, s["id"])
                self._refresh_rows()

        self.app.push_screen(
            ConfirmDeleteScheduledScreen(s["description"]),
            callback=on_confirm,
        )

    def action_toggle_enabled(self):
        s = self._get_selected()
        if not s:
            return
        toggle_scheduled_enabled(self.con, s["id"])
        self._refresh_rows()

    def action_open_search(self):
        bar = self.query_one("#sl-search-bar")
        bar.add_class("visible")
        self.search_active = True
        search_input = self.query_one("#sl-search-input", Input)
        search_input.value = self.search_query
        search_input.focus()

    @on(Input.Changed, "#sl-search-input")
    def on_search_changed(self, event):
        self.search_query = event.value.strip()
        self._refresh_rows()

    @on(Input.Submitted, "#sl-search-input")
    def on_search_submitted(self, event):
        bar = self.query_one("#sl-search-bar")
        bar.remove_class("visible")
        self.search_active = False
        self.query_one("#sl-table", DataTable).focus()


class ScheduledFormScreen(ModalScreen):
    """Modal for adding or editing a scheduled transaction with splits."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save", show=False),
    ]

    DEFAULT_CSS = ADD_TRANSACTION_CSS + SCHEDULED_FORM_CSS

    def __init__(self, con, mode="add", st_id=None):
        super().__init__()
        self.con = con
        self.mode = mode
        self.st_id = st_id
        self._next_split_id = 0
        self._alive_splits = []
        self.split_directions = {}
        self._split_account_ids = {}
        self._split_account_types = {}
        self._user_touched_dir = set()
        self._user_touched_amount = set()
        self._programmatic_amount = set()

    def compose(self):
        title = "Edit Scheduled Transaction" if self.mode == "edit" else "Add Scheduled Transaction"
        vendor_options = [(v["name"], v["id"]) for v in get_all_vendors(self.con)]

        # Defaults
        desc_val = ""
        freq_val = "monthly"
        next_date_val = format_date(date.today().isoformat())
        end_date_val = ""
        enabled_val = True
        vendor_val = Select.NULL
        existing_splits = []

        if self.mode == "edit" and self.st_id:
            st, splits = get_scheduled_transaction_detail(self.con, self.st_id)
            if st:
                desc_val = st["description"]
                freq_val = st["frequency"]
                next_date_val = format_date(st["next_date"])
                end_date_val = format_date(st["end_date"]) if st["end_date"] else ""
                enabled_val = st["enabled"]
                vendor_val = st["vendor_id"] if st["vendor_id"] else Select.NULL
                existing_splits = splits

        if existing_splits:
            self._next_split_id = len(existing_splits)
            self._alive_splits = list(range(len(existing_splits)))
        else:
            self._next_split_id = 2
            self._alive_splits = [0, 1]

        with VerticalScroll(id="sf-dialog"):
            yield Label(title, id="sf-title")

            yield Label("Description:", classes="sf-field-label")
            yield Input(
                value=desc_val,
                placeholder="Transaction description",
                id="sf-desc",
                classes="sf-input",
            )

            with Horizontal(classes="sf-schedule-row"):
                with Vertical(classes="sf-schedule-col"):
                    yield Label("Frequency:", classes="sf-field-label")
                    yield Select(
                        FREQUENCY_OPTIONS,
                        value=freq_val,
                        id="sf-frequency",
                        classes="sf-input",
                    )
                with Vertical(classes="sf-schedule-col"):
                    yield Label("Next Date:", classes="sf-field-label")
                    yield DateInput(
                        value=next_date_val,
                        placeholder="M/D, M/D/YY, or MM-DD-YYYY",
                        id="sf-next-date",
                        classes="sf-input",
                    )
                if vendor_options:
                    with Vertical(classes="sf-schedule-col"):
                        yield Label("Vendor:", classes="sf-field-label")
                        yield Select(
                            vendor_options,
                            value=vendor_val,
                            allow_blank=True,
                            id="sf-vendor",
                            classes="sf-input",
                        )

            with Horizontal(classes="sf-schedule-row"):
                with Vertical(classes="sf-schedule-col"):
                    yield Label("End Date (optional):", classes="sf-field-label")
                    yield DateInput(
                        value=end_date_val,
                        placeholder="Leave blank for no end",
                        id="sf-end-date",
                        classes="sf-input",
                    )
                with Vertical(classes="sf-schedule-col"):
                    pass

            with Horizontal(classes="sf-enabled-row"):
                yield Label("Enabled:", classes="sf-field-label")
                yield Switch(value=enabled_val, id="sf-enabled")

            yield Label("Splits:", classes="sf-field-label")
            with Vertical(id="at-splits-container"):
                if existing_splits:
                    from pyre.ui.import_screen import _build_account_options
                    acct_labels = {aid: lbl for lbl, aid in _build_account_options(self.con)}
                    for i, s in enumerate(existing_splits):
                        direction = "DR" if s["amount"] > 0 else "CR"
                        self.split_directions[i] = direction
                        self._split_account_ids[i] = s["account_id"]
                        abs_cents = abs(s["amount"])
                        display_val = f"{abs_cents / 100:.2f}"
                        display_name = acct_labels.get(s["account_id"], s["account_name"]) or "Select account..."
                        with Horizontal(classes="at-split-row", id=f"at-split-row-{i}"):
                            yield Button(
                                display_name,
                                id=f"at-split-account-{i}",
                                classes="at-split-account",
                            )
                            yield Input(
                                value=display_val,
                                id=f"at-split-amount-{i}",
                                classes="at-split-amount sf-input",
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
                                disabled=len(existing_splits) <= 2,
                            )
                else:
                    for i in self._alive_splits:
                        self.split_directions[i] = "DR" if i == 0 else "CR"
                        self._split_account_ids[i] = None
                        with Horizontal(classes="at-split-row", id=f"at-split-row-{i}"):
                            yield Button(
                                "Select account...",
                                id=f"at-split-account-{i}",
                                classes="at-split-account",
                            )
                            yield Input(
                                placeholder="0.00",
                                id=f"at-split-amount-{i}",
                                classes="at-split-amount sf-input",
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

            with Horizontal(id="at-add-split-row"):
                yield Button("+ Add Split", id="at-add-split")

            yield Label("", id="at-balance")
            yield Label("", id="at-error")
            with Horizontal(id="at-buttons"):
                yield Button("Save", variant="primary", id="sf-save")
                yield Button("Cancel", id="sf-cancel-btn")

    def on_mount(self):
        self.query_one("#sf-desc", Input).focus()
        self._update_balance()

    def action_save(self):
        self._save()

    def action_cancel(self):
        self.dismiss(None)

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
        if btn_id == "sf-save":
            self._save()
        elif btn_id == "sf-cancel-btn":
            self.dismiss(None)
        elif btn_id == "at-add-split":
            self._add_split()
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
            self.query_one("#sf-save", Button).disabled = (total != 0)
        except Exception:
            pass

    def _update_remove_buttons(self):
        for i in self._alive_splits:
            try:
                btn = self.query_one(f"#at-split-remove-{i}", Button)
                btn.disabled = len(self._alive_splits) <= 2
            except Exception:
                continue

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
        except Exception:
            pass
        self._update_balance()
        self._auto_fill_last_split()

    def _auto_fill_last_split(self):
        if len(self._alive_splits) < 2:
            return
        last = self._alive_splits[-1]
        if last in self._user_touched_amount:
            return
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
        amount = abs(total)
        direction = "CR" if total > 0 else "DR"
        if last not in self._user_touched_dir:
            self.split_directions[last] = direction
            try:
                self.query_one(f"#at-split-dir-{last}", Button).label = direction
            except Exception:
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
            id=f"at-split-amount-{i}", classes="at-split-amount sf-input",
        ))
        row.mount(Button("DR", id=f"at-split-dir-{i}", classes="at-split-dir"))
        row.mount(Button("X", id=f"at-split-remove-{i}", classes="at-split-remove"))
        self._update_remove_buttons()
        self._update_balance()
        self._pick_account(i)

    def _remove_split(self, idx):
        if len(self._alive_splits) <= 2:
            return
        self.query_one(f"#at-split-row-{idx}").remove()
        del self.split_directions[idx]
        self._split_account_ids.pop(idx, None)
        self._split_account_types.pop(idx, None)
        self._user_touched_dir.discard(idx)
        self._user_touched_amount.discard(idx)
        self._alive_splits.remove(idx)
        self._update_remove_buttons()
        self._update_balance()

    def _save(self):
        try:
            description = self.query_one("#sf-desc", Input).value.strip()
            if not description:
                self.query_one("#at-error", Label).update("Error: Description is required")
                return

            freq_select = self.query_one("#sf-frequency", Select)
            if freq_select.value is Select.NULL:
                self.query_one("#at-error", Label).update("Error: Frequency is required")
                return
            frequency = freq_select.value

            next_date = parse_date(self.query_one("#sf-next-date", Input).value)

            end_date_val = self.query_one("#sf-end-date", Input).value.strip()
            end_date = parse_date(end_date_val) if end_date_val else None

            enabled = self.query_one("#sf-enabled", Switch).value

            vendor_id = None
            try:
                vendor_select = self.query_one("#sf-vendor", Select)
                if vendor_select.value is not Select.NULL:
                    vendor_id = vendor_select.value
            except Exception:
                pass

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
                splits.append((acct_id, c))

            if self.mode == "edit":
                update_scheduled_transaction(
                    self.con, self.st_id, description, frequency,
                    next_date, splits, vendor_id=vendor_id,
                    end_date=end_date, enabled=enabled,
                )
            else:
                create_scheduled_transaction(
                    self.con, description, frequency, next_date,
                    splits, vendor_id=vendor_id, end_date=end_date,
                )
            self.dismiss(True)

        except Exception as e:
            self.query_one("#at-error", Label).update(f"Error: {e}")

    def on_key(self, event):
        if event.key == "space":
            focused = self.screen.focused
            if isinstance(focused, Button) and focused.id == "at-add-split":
                event.prevent_default()
                event.stop()
                self._add_split()


class ConfirmDeleteScheduledScreen(ModalScreen):
    """Confirmation dialog for deleting a scheduled transaction."""

    BINDINGS = [
        Binding("y", "confirm", "Yes", show=False),
        Binding("n", "cancel", "No", show=False),
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = CONFIRM_DELETE_SCHEDULED_CSS
    AUTO_FOCUS = "#cds-no"

    def __init__(self, description):
        super().__init__()
        self.description = description

    def compose(self):
        with Vertical(id="cds-dialog"):
            yield Label("Delete Scheduled Transaction", id="cds-title")
            yield Label(
                f"Delete scheduled transaction \"{self.description}\"?",
                shrink=True,
                id="cds-message",
            )
            with Horizontal(id="cds-buttons"):
                yield Button("Delete", variant="error", id="cds-yes")
                yield Button("Cancel", id="cds-no")

    @on(Button.Pressed, "#cds-yes")
    def on_yes(self):
        self.dismiss(True)

    @on(Button.Pressed, "#cds-no")
    def on_no(self):
        self.dismiss(False)

    def action_confirm(self):
        self.dismiss(True)

    def action_cancel(self):
        self.dismiss(False)
