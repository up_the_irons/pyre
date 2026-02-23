"""List all payee rules."""
from pyre.db import init_db, release_lock
from pyre.importers.models import get_payee_rules

con = init_db()
rules = get_payee_rules(con)
print(f"{len(rules)} payee rules:")
print()
for r in rules:
    acct = con.execute(
        "SELECT name FROM accounts WHERE id = ?", (r["account_id"],)
    ).fetchone()
    name = acct[0] if acct else r["account_id"]
    memo_part = f' + memo:"{r["memo_pattern"]}"' if r.get("memo_pattern") else ""
    print(f'  "{r["pattern"]}"{memo_part} -> {name} (pri={r["priority"]})')
release_lock()
