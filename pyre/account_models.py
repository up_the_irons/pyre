"""Database operations for accounts."""

from pyre.db import TYPE_FAMILY


def get_all_accounts(con):
    """Fetch all accounts as a list of dicts."""
    rows = con.execute(
        "SELECT id, account_number, name, type, parent_id, description, sidebar, "
        "ofx_bankid, ofx_acctid "
        "FROM accounts ORDER BY account_number, name"
    ).fetchall()
    return [
        {
            "id": r[0],
            "account_number": r[1],
            "name": r[2],
            "type": r[3],
            "parent_id": r[4],
            "description": r[5],
            "sidebar": r[6],
            "ofx_bankid": r[7],
            "ofx_acctid": r[8],
        }
        for r in rows
    ]


def get_account_by_id(con, account_id):
    """Fetch a single account by ID, returns dict or None."""
    row = con.execute(
        "SELECT id, account_number, name, type, parent_id, description, sidebar, "
        "ofx_bankid, ofx_acctid "
        "FROM accounts WHERE id = ?",
        (account_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "account_number": row[1],
        "name": row[2],
        "type": row[3],
        "parent_id": row[4],
        "description": row[5],
        "sidebar": row[6],
        "ofx_bankid": row[7],
        "ofx_acctid": row[8],
    }


def _check_parent_type(con, parent_id, account_type):
    """Raise ValueError if parent exists and is in a different type family."""
    if parent_id is None:
        return
    parent = get_account_by_id(con, parent_id)
    if parent and TYPE_FAMILY.get(parent['type']) != TYPE_FAMILY.get(account_type):
        raise ValueError(
            f"Child type '{account_type}' does not match "
            f"parent type '{parent['type']}'"
        )


def _check_name(name):
    """Raise ValueError if the account name contains a colon."""
    if ":" in name:
        raise ValueError(
            "Account name cannot contain ':' (used as path separator)"
        )


def create_account(con, account_id, name, account_type, account_number=None,
                   parent_id=None, description="", sidebar=False):
    """Insert a new account."""
    _check_name(name)
    _check_parent_type(con, parent_id, account_type)
    con.execute(
        "INSERT INTO accounts (id, account_number, name, type, parent_id, description, sidebar) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (account_id, account_number, name, account_type, parent_id, description,
         1 if sidebar else 0),
    )
    con.commit()


def update_account(con, account_id, name, account_type, account_number=None,
                   parent_id=None, description="", sidebar=None):
    """Update an existing account."""
    _check_name(name)
    _check_parent_type(con, parent_id, account_type)
    if sidebar is not None:
        con.execute(
            "UPDATE accounts SET account_number = ?, name = ?, type = ?, "
            "parent_id = ?, description = ?, sidebar = ? WHERE id = ?",
            (account_number, name, account_type, parent_id, description,
             1 if sidebar else 0, account_id),
        )
    else:
        con.execute(
            "UPDATE accounts SET account_number = ?, name = ?, type = ?, "
            "parent_id = ?, description = ? WHERE id = ?",
            (account_number, name, account_type, parent_id, description, account_id),
        )
    con.commit()


def toggle_sidebar(con, account_id):
    """Flip the sidebar flag for an account."""
    con.execute(
        "UPDATE accounts SET sidebar = 1 - sidebar WHERE id = ?",
        (account_id,),
    )
    con.commit()


def delete_account(con, account_id):
    """Delete an account. Raises ValueError if children exist,
    IntegrityError if transactions reference it."""
    children = get_child_count(con, account_id)
    if children > 0:
        raise ValueError(f"Cannot delete: account has {children} child account(s)")
    con.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    con.commit()


def account_path(by_id, account_id):
    """Build colon-delimited ancestor path for an account, e.g. 'Expenses : Utilities'."""
    parts = []
    current = account_id
    while current:
        acct = by_id.get(current)
        if not acct:
            break
        parts.append(acct["name"])
        current = acct["parent_id"]
    parts.reverse()
    return ": ".join(parts)


def get_child_count(con, account_id):
    """Count child accounts."""
    row = con.execute(
        "SELECT count(*) FROM accounts WHERE parent_id = ?", (account_id,)
    ).fetchone()
    return row[0]


def get_transaction_count(con, account_id):
    """Count transactions referencing this account via splits."""
    row = con.execute(
        "SELECT count(DISTINCT tx_id) FROM splits WHERE account_id = ?",
        (account_id,),
    ).fetchone()
    return row[0]
