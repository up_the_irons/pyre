# Testing

## Running tests

```
. venv/bin/activate
pytest tests/
```

## Structure

- `tests/conftest.py` -- shared fixtures (DB, accounts, app)
- `tests/test_*.py` -- test modules organized by area

## Fixtures (conftest.py)

| Fixture           | Description                                         |
| ----------------- | --------------------------------------------------- |
| `db`              | In-memory SQLite with schema and migrations applied |
| `sample_accounts` | `db` + a full chart of accounts                     |
| `ui_db`           | `db` + minimal accounts + 3 seeded transactions     |
| `app`             | `PyreApp` wired to `ui_db` (never touches disk)     |

## Unit tests

Standard pytest. Use the `db` or `sample_accounts` fixtures:

```python
def test_balanced_succeeds(sample_accounts):
    tx_id = post_transaction(sample_accounts, "2026-01-01", "Test", [
        ("checking", 1000),
        ("expenses", -1000),
    ])
    assert tx_id
```

## UI tests (Textual Pilot)

Async tests using Textual's `run_test()` / `Pilot` API. The `app` fixture
provides a `PyreApp` backed by an in-memory DB.

```python
async def test_ledger_has_rows(app):
    async with app.run_test() as pilot:
        table = app.query_one("#ledger-table")
        assert table.row_count == 3
```

Key patterns:

- `await pilot.press("j")` -- simulate a keypress
- `await pilot.press("enter")` -- trigger row selection
- `app.query_one("#widget-id")` -- find a widget by CSS selector
- `app.screen` -- the currently active screen instance
- `str(label.content)` -- read a Label's text

pytest-asyncio is configured in `pyproject.toml` with `asyncio_mode = "auto"`,
so async test functions are recognized automatically (no decorator needed).

## Guidelines

- Keep tests fast. All DB access uses in-memory SQLite.
- One assertion per test when practical.
- UI tests should use the `app` fixture, not construct `PyreApp` directly.
- Add new shared fixtures to `conftest.py`, not in individual test files.
