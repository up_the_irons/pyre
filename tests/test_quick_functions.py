"""Tests for YAML-based quick functions loading and UI integration."""

import textwrap
from pathlib import Path

import pytest

from pyre.quick_functions import load_quick_functions
from pyre.ui.app import PyreApp


# -- load_quick_functions unit tests --


@pytest.fixture
def qf_dir(tmp_path):
    """Temp directory with a fake db path for testing YAML loading."""
    db_path = tmp_path / "pyre.db"
    db_path.touch()
    return db_path


def test_load_valid_yaml(qf_dir):
    yaml_path = qf_dir.with_name("quick_functions.yaml")
    yaml_path.write_text(textwrap.dedent("""\
        - key: "1"
          group: Payments
          label: Pay Rent
          description: Pay rent from checking
          splits:
            - account: rent_expense
              direction: debit
              prompt: Amount
            - account: checking
              direction: credit
              prompt: null
    """))
    result = load_quick_functions(qf_dir)
    assert len(result) == 1
    assert result[0]["key"] == "1"
    assert result[0]["label"] == "Pay Rent"
    assert len(result[0]["splits"]) == 2


def test_load_missing_file_returns_empty(qf_dir):
    result = load_quick_functions(qf_dir)
    assert result == []


def test_load_invalid_yaml_returns_empty(qf_dir):
    yaml_path = qf_dir.with_name("quick_functions.yaml")
    yaml_path.write_text("{{not valid yaml")
    result = load_quick_functions(qf_dir)
    assert result == []


def test_load_non_list_returns_empty(qf_dir):
    yaml_path = qf_dir.with_name("quick_functions.yaml")
    yaml_path.write_text("key: value\n")
    result = load_quick_functions(qf_dir)
    assert result == []


def test_load_multiple_entries(qf_dir):
    yaml_path = qf_dir.with_name("quick_functions.yaml")
    yaml_path.write_text(textwrap.dedent("""\
        - key: "1"
          group: A
          label: First
          description: First entry
          splits:
            - account: a
              direction: debit
              prompt: Amount
            - account: b
              direction: credit
              prompt: null
        - key: "2"
          group: B
          label: Second
          description: Second entry
          splits:
            - account: c
              direction: debit
              prompt: Amount
            - account: d
              direction: credit
              prompt: null
    """))
    result = load_quick_functions(qf_dir)
    assert len(result) == 2
    assert result[0]["key"] == "1"
    assert result[1]["key"] == "2"


# -- UI integration tests --


@pytest.fixture
def qf_yaml(tmp_path):
    """Write a small quick_functions.yaml and return the fake db_path."""
    db_path = tmp_path / "pyre.db"
    db_path.touch()
    yaml_path = tmp_path / "quick_functions.yaml"
    yaml_path.write_text(textwrap.dedent("""\
        - key: "1"
          group: Payments
          label: Test Payment
          description: Test payment from checking
          splits:
            - account: checking
              direction: debit
              prompt: Amount
            - account: cap1
              direction: credit
              prompt: null
        - key: "2"
          group: Revenue
          label: Test Revenue
          description: Test revenue deposit
          splits:
            - account: checking
              direction: debit
              prompt: Deposit
            - account: hosting_rev
              direction: credit
              prompt: null
    """))
    return db_path


def test_sidebar_renders_quick_functions(ui_db, qf_yaml):
    """Quick functions from YAML should appear in the sidebar."""
    app = PyreApp(con=ui_db, db_path=qf_yaml)
    assert len(app._quick_functions) == 2


async def test_sidebar_shows_labels(ui_db, qf_yaml):
    """Quick function labels should be rendered in the sidebar."""
    app = PyreApp(con=ui_db, db_path=qf_yaml)
    async with app.run_test() as pilot:
        labels = app.query(".qf-label")
        texts = [str(lbl.content) for lbl in labels]
        assert "Test Payment" in texts
        assert "Test Revenue" in texts


async def test_sidebar_shows_group_headers(ui_db, qf_yaml):
    """Group headers should appear in the sidebar."""
    app = PyreApp(con=ui_db, db_path=qf_yaml)
    async with app.run_test() as pilot:
        groups = app.query(".qf-group")
        texts = [str(lbl.content) for lbl in groups]
        assert "Payments" in texts
        assert "Revenue" in texts


async def test_empty_state_when_no_yaml(ui_db, tmp_path):
    """When no YAML file exists, sidebar shows empty state message."""
    db_path = tmp_path / "pyre.db"
    db_path.touch()
    app = PyreApp(con=ui_db, db_path=db_path)
    async with app.run_test() as pilot:
        empty_labels = app.query(".qf-empty")
        assert len(empty_labels) == 1
        assert "No quick functions defined" in str(empty_labels[0].content)


async def test_digit_key_opens_quick_function(ui_db, qf_yaml):
    """Pressing a digit key should open the corresponding quick function screen."""
    app = PyreApp(con=ui_db, db_path=qf_yaml)
    async with app.run_test() as pilot:
        app.query_one("#ledger-table").focus()
        await pilot.press("1")
        # QuickEntryScreen should now be on the screen stack
        assert len(app.screen_stack) > 1


async def test_unbound_digit_does_nothing(ui_db, qf_yaml):
    """Pressing a digit with no matching quick function should not open a screen."""
    app = PyreApp(con=ui_db, db_path=qf_yaml)
    async with app.run_test() as pilot:
        app.query_one("#ledger-table").focus()
        await pilot.press("9")
        assert len(app.screen_stack) == 1


async def test_digit_keys_ignored_during_search(ui_db, qf_yaml):
    """Digit keys should type into the search input, not trigger quick functions."""
    app = PyreApp(con=ui_db, db_path=qf_yaml)
    async with app.run_test() as pilot:
        app.query_one("#ledger-table").focus()
        await pilot.press("slash")
        await pilot.press("1")
        assert len(app.screen_stack) == 1
        search_input = app.query_one("#search-input")
        assert "1" in search_input.value


async def test_favorites_mode_overrides_quick_functions(ui_db, qf_yaml):
    """In favorites mode, digit keys select favorites, not quick functions."""
    ui_db.execute("UPDATE accounts SET sidebar = 1 WHERE id = 'checking'")
    ui_db.commit()
    app = PyreApp(con=ui_db, db_path=qf_yaml)
    async with app.run_test() as pilot:
        app.query_one("#ledger-table").focus()
        await pilot.press("f")
        assert app._favorites_mode is True
        await pilot.press("1")
        # Should have selected a favorite, not opened a quick function screen
        assert app._favorites_mode is False
        assert app.account_filter is not None
        assert len(app.screen_stack) == 1
