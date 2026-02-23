"""Database operations for vendors."""


def get_all_vendors(con):
    """Fetch all vendors as a list of dicts, ordered by name."""
    rows = con.execute(
        "SELECT id, name FROM vendors ORDER BY name"
    ).fetchall()
    return [{"id": r[0], "name": r[1]} for r in rows]


def get_vendor_by_id(con, vendor_id):
    """Fetch a single vendor by ID, returns dict or None."""
    row = con.execute(
        "SELECT id, name FROM vendors WHERE id = ?",
        (vendor_id,),
    ).fetchone()
    if row is None:
        return None
    return {"id": row[0], "name": row[1]}


def create_vendor(con, vendor_id, name):
    """Insert a new vendor."""
    con.execute(
        "INSERT INTO vendors (id, name) VALUES (?, ?)",
        (vendor_id, name),
    )
    con.commit()


def update_vendor(con, vendor_id, name):
    """Update an existing vendor's name."""
    con.execute(
        "UPDATE vendors SET name = ? WHERE id = ?",
        (name, vendor_id),
    )
    con.commit()


def delete_vendor(con, vendor_id):
    """Delete a vendor. Sets vendor_id to NULL on any linked transactions or payee rules."""
    con.execute(
        "UPDATE transactions SET vendor_id = NULL WHERE vendor_id = ?",
        (vendor_id,),
    )
    con.execute(
        "UPDATE payee_rules SET vendor_id = NULL WHERE vendor_id = ?",
        (vendor_id,),
    )
    con.execute("DELETE FROM vendors WHERE id = ?", (vendor_id,))
    con.commit()


def get_vendor_transaction_count(con, vendor_id):
    """Count transactions linked to this vendor."""
    row = con.execute(
        "SELECT COUNT(*) FROM transactions WHERE vendor_id = ?",
        (vendor_id,),
    ).fetchone()
    return row[0]
