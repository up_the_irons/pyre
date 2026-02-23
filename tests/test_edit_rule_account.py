"""Tests for the account picker in EditRuleScreen (payee rules)."""

from textual.widgets import Button, DataTable, Input

from pyre.importers.models import create_payee_rule, get_payee_rules, update_payee_rule
from pyre.ui.import_screen import EditRuleScreen, PayeeRulesScreen
from pyre.ui.screens import AccountFuzzyPickScreen


# -- Database layer --

def test_update_payee_rule_with_account_id(ui_db):
    """update_payee_rule should update account_id when provided."""
    rule_id = create_payee_rule(ui_db, "AMAZON", "office", priority=5)
    update_payee_rule(ui_db, rule_id, "AMAZON", account_id="hosting_exp")

    rules = get_payee_rules(ui_db)
    rule = next(r for r in rules if r["id"] == rule_id)
    assert rule["account_id"] == "hosting_exp"


def test_update_payee_rule_without_account_id(ui_db):
    """update_payee_rule should leave account_id unchanged when not provided."""
    rule_id = create_payee_rule(ui_db, "AMAZON", "office", priority=5)
    update_payee_rule(ui_db, rule_id, "AMAZON PRIME", priority=10)

    rules = get_payee_rules(ui_db)
    rule = next(r for r in rules if r["id"] == rule_id)
    assert rule["account_id"] == "office"
    assert rule["pattern"] == "AMAZON PRIME"


# -- UI: EditRuleScreen --

async def test_edit_rule_shows_account_button(app):
    """EditRuleScreen should display a button with the current account name."""
    create_payee_rule(app.con, "TEST PATTERN", "office", priority=0)

    async with app.run_test() as pilot:
        app.push_screen(PayeeRulesScreen(app.con))
        await pilot.pause()

        # Press e to edit the rule
        table = app.screen.query_one("#pr-table", DataTable)
        table.focus()
        await pilot.press("e")
        await pilot.pause()

        assert isinstance(app.screen, EditRuleScreen)
        btn = app.screen.query_one("#er-account-btn", Button)
        # Button label should contain the account name
        assert "Office Supplies" in str(btn.label)


async def test_edit_rule_account_button_opens_picker(app):
    """Pressing the account button should open AccountFuzzyPickScreen."""
    create_payee_rule(app.con, "TEST PATTERN", "office", priority=0)

    async with app.run_test() as pilot:
        app.push_screen(PayeeRulesScreen(app.con))
        await pilot.pause()

        table = app.screen.query_one("#pr-table", DataTable)
        table.focus()
        await pilot.press("e")
        await pilot.pause()

        # Press the account button
        app.screen.query_one("#er-account-btn", Button).press()
        await pilot.pause()

        assert isinstance(app.screen, AccountFuzzyPickScreen)


async def test_edit_rule_change_account(app):
    """Picking a new account in the modal should update the button label."""
    rule_id = create_payee_rule(app.con, "TEST PATTERN", "office", priority=0)

    async with app.run_test() as pilot:
        app.push_screen(PayeeRulesScreen(app.con))
        await pilot.pause()

        table = app.screen.query_one("#pr-table", DataTable)
        table.focus()
        await pilot.press("e")
        await pilot.pause()

        edit_screen = app.screen

        # Open account picker
        edit_screen.query_one("#er-account-btn", Button).press()
        await pilot.pause()

        assert isinstance(app.screen, AccountFuzzyPickScreen)

        # Type to filter for "Hosting" expense account
        filter_input = app.screen.query_one("#afp-filter", Input)
        filter_input.value = "Hosting"
        await pilot.pause()

        # Select the first result (press enter to focus list, enter to pick)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        # Should be back on EditRuleScreen with updated button
        assert app.screen is edit_screen
        btn_label = str(edit_screen.query_one("#er-account-btn", Button).label)
        assert "Hosting" in btn_label

        # Save the edit
        edit_screen.query_one("#er-save", Button).press()
        await pilot.pause()

        # Verify the DB was updated
        rules = get_payee_rules(app.con)
        rule = next(r for r in rules if r["id"] == rule_id)
        assert rule["account_id"] == "hosting_exp"


async def test_edit_rule_cancel_preserves_account(app):
    """Canceling the edit should not change the account in the DB."""
    rule_id = create_payee_rule(app.con, "TEST PATTERN", "office", priority=0)

    async with app.run_test() as pilot:
        app.push_screen(PayeeRulesScreen(app.con))
        await pilot.pause()

        table = app.screen.query_one("#pr-table", DataTable)
        table.focus()
        await pilot.press("e")
        await pilot.pause()

        # Cancel the edit
        await pilot.press("escape")
        await pilot.pause()

        rules = get_payee_rules(app.con)
        rule = next(r for r in rules if r["id"] == rule_id)
        assert rule["account_id"] == "office"
