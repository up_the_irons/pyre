"""Reusable fuzzy-searchable select widget."""

from textual import on
from textual.binding import Binding
from textual.containers import Vertical
from textual.fuzzy import Matcher
from textual.message import Message
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from rich.text import Text


class FuzzySelect(Static):
    """Input + OptionList with fuzzy filtering.

    After selection the picker collapses to a label showing the chosen item.

    Posts FuzzySelect.Selected(value, label) when an item is picked.
    """

    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
    ]

    DEFAULT_CSS = """
    FuzzySelect {
        height: auto;
    }
    FuzzySelect .fs-chosen {
        margin-top: 0;
    }
    FuzzySelect .fs-results {
        height: 12;
        margin-bottom: 0;
    }
    """

    class Selected(Message):
        """Posted when an option is selected."""

        def __init__(self, value, label):
            super().__init__()
            self.value = value
            self.label = label

        @property
        def control(self):
            return self._sender

    def __init__(self, options, placeholder="Type to filter...", **kwargs):
        """options: list of (label_str, value) tuples."""
        super().__init__(**kwargs)
        self._all_options = list(options)
        self._placeholder = placeholder
        self._id_by_index = {}
        self._selected_value = None
        self._selected_label = None

    @property
    def value(self):
        return self._selected_value

    @property
    def selected_label(self):
        return self._selected_label

    def compose(self):
        yield Label("", classes="fs-chosen")
        yield Input(placeholder=self._placeholder, classes="fs-filter")
        yield OptionList(classes="fs-results")

    def on_mount(self):
        self.query_one(".fs-chosen", Label).display = False
        self._refresh_options("")

    def _refresh_options(self, query):
        ol = self.query_one(".fs-results", OptionList)
        ol.clear_options()
        self._id_by_index = {}
        if query:
            matcher = Matcher(query)
            scored = []
            for label, val in self._all_options:
                score = matcher.match(label)
                if score > 0:
                    scored.append((score, label, val))
            scored.sort(key=lambda x: x[0], reverse=True)
            for idx, (_score, label, val) in enumerate(scored):
                highlight = matcher.highlight(label)
                ol.add_option(Option(highlight, id=val))
                self._id_by_index[idx] = val
        else:
            for idx, (label, val) in enumerate(self._all_options):
                ol.add_option(Option(Text(label), id=val))
                self._id_by_index[idx] = val
        if self._id_by_index:
            ol.highlighted = 0

    @on(Input.Changed, ".fs-filter")
    def _on_filter_changed(self, event):
        self._refresh_options(event.value.strip())

    @on(Input.Submitted, ".fs-filter")
    def _on_filter_submitted(self, event):
        ol = self.query_one(".fs-results", OptionList)
        if len(self._id_by_index) == 1:
            self._pick_highlighted()
        elif self._id_by_index:
            ol.focus()

    @on(OptionList.OptionSelected, ".fs-results")
    def _on_option_selected(self, event):
        self._pick_highlighted()

    def _pick_highlighted(self):
        ol = self.query_one(".fs-results", OptionList)
        idx = ol.highlighted
        if idx is not None and idx in self._id_by_index:
            val = self._id_by_index[idx]
            self._selected_value = val
            for label, oid in self._all_options:
                if oid == val:
                    self._selected_label = label
                    chosen = self.query_one(".fs-chosen", Label)
                    chosen.update(label)
                    chosen.display = True
                    break
            self.query_one(".fs-filter", Input).display = False
            ol.display = False
            self.post_message(self.Selected(val, self._selected_label))

    def action_cursor_down(self):
        ol = self.query_one(".fs-results", OptionList)
        if ol.display:
            ol.action_cursor_down()

    def action_cursor_up(self):
        ol = self.query_one(".fs-results", OptionList)
        if ol.display:
            ol.action_cursor_up()
