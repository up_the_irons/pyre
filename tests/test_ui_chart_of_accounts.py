"""Tests for the Chart of Accounts screen."""

from textual.widgets import Input, Tree

from pyre.models import post_transaction
from pyre.ui.screens import (
    AccountFormScreen,
    ChartOfAccountsScreen,
    ConfirmDeleteScreen,
)


async def _type_into(pilot, text):
    """Simulate typing by pressing each character individually."""
    for char in text:
        await pilot.press(char)


# -- Opening and dismissing --

async def test_c_opens_chart_of_accounts(app):
    """Pressing 'c' should push ChartOfAccountsScreen."""
    async with app.run_test() as pilot:
        await pilot.press("c")
        assert isinstance(app.screen, ChartOfAccountsScreen)


async def test_q_dismisses_chart_of_accounts(app):
    """Pressing 'q' inside CoA should return to main screen."""
    async with app.run_test() as pilot:
        await pilot.press("c")
        await pilot.press("q")
        assert not isinstance(app.screen, ChartOfAccountsScreen)


async def test_escape_dismisses_chart_of_accounts(app):
    """Pressing Escape should also dismiss CoA."""
    async with app.run_test() as pilot:
        await pilot.press("c")
        await pilot.press("escape")
        assert not isinstance(app.screen, ChartOfAccountsScreen)


# -- Tree is populated --

async def test_tree_has_account_nodes(coa_app):
    """The tree should contain nodes for seeded accounts."""
    async with coa_app.run_test() as pilot:
        await pilot.press("c")
        screen = coa_app.screen
        tree = screen.query_one("#coa-tree", Tree)
        labels = [str(n.label) for n in _walk_tree(tree.root)]
        assert any("Main Checking" in l for l in labels)
        assert any("Expenses" in l for l in labels)
        assert any("Salary & Wages" in l for l in labels)


async def test_tree_has_category_grouping(coa_app):
    """Top-level tree nodes should be category headers."""
    async with coa_app.run_test() as pilot:
        await pilot.press("c")
        screen = coa_app.screen
        tree = screen.query_one("#coa-tree", Tree)
        top_labels = [str(child.label) for child in tree.root.children]
        assert any("Assets" in l for l in top_labels)
        assert any("Expenses" in l for l in top_labels)


# -- Navigation --

async def test_j_k_moves_tree_cursor(coa_app):
    """Vim j/k should navigate the tree."""
    async with coa_app.run_test() as pilot:
        await pilot.press("c")
        screen = coa_app.screen
        tree = screen.query_one("#coa-tree", Tree)
        tree.focus()

        start_line = tree.cursor_line
        await pilot.press("j")
        assert tree.cursor_line == start_line + 1

        await pilot.press("k")
        assert tree.cursor_line == start_line


# -- Add account --

async def test_a_opens_add_account_form(coa_app):
    """Pressing 'a' should push AccountFormScreen in add mode."""
    async with coa_app.run_test() as pilot:
        await pilot.press("c")
        await pilot.press("a")
        assert isinstance(coa_app.screen, AccountFormScreen)
        title = coa_app.screen.query_one("#af-title")
        assert "Add" in str(title.content)


# -- Edit account --

async def test_e_opens_edit_account_form(coa_app):
    """Pressing 'e' on an account node should push AccountFormScreen in edit mode."""
    async with coa_app.run_test() as pilot:
        await pilot.press("c")
        screen = coa_app.screen
        tree = screen.query_one("#coa-tree", Tree)
        tree.focus()

        await _move_to_account_node(pilot, tree)

        await pilot.press("e")
        assert isinstance(coa_app.screen, AccountFormScreen)
        title = coa_app.screen.query_one("#af-title")
        assert "Edit" in str(title.content)


# -- Delete account --

async def test_d_opens_confirm_delete(coa_app):
    """Pressing 'd' on an account should push ConfirmDeleteScreen."""
    async with coa_app.run_test() as pilot:
        await pilot.press("c")
        screen = coa_app.screen
        tree = screen.query_one("#coa-tree", Tree)
        tree.focus()

        await _move_to_account_node(pilot, tree)

        await pilot.press("d")
        assert isinstance(coa_app.screen, ConfirmDeleteScreen)


async def test_delete_blocked_by_children(coa_app):
    """Deleting an account with children should show an error toast, not a dialog."""
    async with coa_app.run_test(notifications=True) as pilot:
        await pilot.press("c")
        screen = coa_app.screen
        tree = screen.query_one("#coa-tree", Tree)
        tree.focus()

        # "Direct Expenses" has child "Salary & Wages"
        await _move_to_node_by_name(pilot, tree, "Direct Expenses")

        await pilot.press("d")
        # Should stay on CoA screen (no dialog pushed)
        assert not isinstance(coa_app.screen, ConfirmDeleteScreen)


async def test_delete_blocked_by_transactions(coa_app):
    """Deleting an account with transactions should show an error toast, not a dialog."""
    post_transaction(coa_app.con, "2026-01-01", "Test", [
        ("checking", 1000),
        ("expenses", -1000),
    ])

    async with coa_app.run_test(notifications=True) as pilot:
        await pilot.press("c")
        screen = coa_app.screen
        tree = screen.query_one("#coa-tree", Tree)
        tree.focus()

        await _move_to_node_by_name(pilot, tree, "Main Checking")

        await pilot.press("d")
        # Should stay on CoA screen (no dialog pushed)
        assert not isinstance(coa_app.screen, ConfirmDeleteScreen)


async def test_delete_succeeds_on_clean_leaf(coa_app):
    """A leaf account with no transactions can be deleted."""
    async with coa_app.run_test() as pilot:
        await pilot.press("c")
        screen = coa_app.screen
        tree = screen.query_one("#coa-tree", Tree)
        tree.focus()

        await _move_to_node_by_name(pilot, tree, "Opening Balances")

        await pilot.press("d")
        assert isinstance(coa_app.screen, ConfirmDeleteScreen)

        await pilot.press("y")

        # Should be back on CoA screen
        assert isinstance(coa_app.screen, ChartOfAccountsScreen)

        # Account should be gone from the DB
        row = coa_app.con.execute(
            "SELECT 1 FROM accounts WHERE id = 'equity'"
        ).fetchone()
        assert row is None


# -- Sidebar toggle --

async def test_s_toggles_sidebar(coa_app):
    """Pressing 's' should toggle the sidebar flag on the selected account."""
    async with coa_app.run_test() as pilot:
        await pilot.press("c")
        screen = coa_app.screen
        tree = screen.query_one("#coa-tree", Tree)
        tree.focus()

        await _move_to_node_by_name(pilot, tree, "Main Checking")

        before = coa_app.con.execute(
            "SELECT sidebar FROM accounts WHERE id = 'checking'"
        ).fetchone()[0]

        await pilot.press("s")

        after = coa_app.con.execute(
            "SELECT sidebar FROM accounts WHERE id = 'checking'"
        ).fetchone()[0]
        assert after != before


# -- Search within CoA --

async def test_coa_search_filters_tree(coa_app):
    """Typing in the CoA search bar should filter the tree to matching accounts."""
    async with coa_app.run_test() as pilot:
        await pilot.press("c")
        screen = coa_app.screen
        full_count = _count_account_nodes(screen.query_one("#coa-tree", Tree))

        await pilot.press("/")
        assert screen.query_one("#coa-search-input", Input).has_focus

        await _type_into(pilot, "salary")
        await pilot.pause()

        # Tree should be filtered down (fewer nodes than before)
        filtered_count = _count_account_nodes(screen.query_one("#coa-tree", Tree))
        assert filtered_count < full_count

        # "Salary & Wages" should still be in the tree
        labels = [str(n.label) for n in _walk_tree(screen.query_one("#coa-tree", Tree).root)]
        assert any("Salary" in l for l in labels)


async def test_coa_search_cursor_lands_on_first_account(coa_app):
    """After search, cursor should land on first matching account, not root or category."""
    async with coa_app.run_test() as pilot:
        await pilot.press("c")
        screen = coa_app.screen
        tree = screen.query_one("#coa-tree", Tree)

        await pilot.press("/")
        await _type_into(pilot, "salary")
        await pilot.pause()

        # Cursor should be on a node with data (an actual account), not root/category
        cursor_node = tree.cursor_node
        assert cursor_node is not None, "cursor_node is None"
        assert cursor_node.data is not None, (
            f"Cursor is on '{cursor_node.label}' which has no data (category/root)"
        )
        assert "Salary" in str(cursor_node.label), (
            f"Expected cursor on 'Salary & Wages', got '{cursor_node.label}'"
        )


async def test_coa_search_escape_restores_tree(coa_app):
    """Pressing Escape during CoA search should restore the full tree."""
    async with coa_app.run_test() as pilot:
        await pilot.press("c")
        screen = coa_app.screen
        tree = screen.query_one("#coa-tree", Tree)
        full_count = _count_account_nodes(tree)

        await pilot.press("/")
        await _type_into(pilot, "Salary")
        await pilot.press("escape")

        restored_count = _count_account_nodes(tree)
        assert restored_count == full_count


# -- Helpers --

def _walk_tree(node):
    """Yield all nodes depth-first."""
    yield node
    for child in node.children:
        yield from _walk_tree(child)


def _count_account_nodes(tree):
    """Count tree nodes that have data (real accounts, not headers)."""
    return sum(1 for n in _walk_tree(tree.root) if n.data is not None)


async def _move_to_account_node(pilot, tree):
    """Move cursor down until we land on a node with account data."""
    for _ in range(20):
        node = tree.cursor_node
        if node is not None and node.data is not None:
            return
        await pilot.press("j")
    raise AssertionError("Could not find an account node in the tree")


async def _move_to_node_by_name(pilot, tree, name):
    """Move cursor down until the node label contains the given name."""
    await pilot.press("g")
    for _ in range(50):
        node = tree.cursor_node
        if node is not None and name in str(node.label):
            return
        await pilot.press("j")
    raise AssertionError(f"Could not find tree node containing '{name}'")
