import pytest

from pyre.vendor_models import (
    get_all_vendors,
    get_vendor_by_id,
    create_vendor,
    update_vendor,
    delete_vendor,
    get_vendor_transaction_count,
)
from pyre.models import post_transaction


class TestVendorCRUD:
    def test_create_and_get(self, sample_accounts):
        con = sample_accounts
        create_vendor(con, "test_vendor", "Test Vendor")
        vendor = get_vendor_by_id(con, "test_vendor")
        assert vendor is not None
        assert vendor["name"] == "Test Vendor"

    def test_get_all_vendors(self, sample_vendors):
        con = sample_vendors
        vendors = get_all_vendors(con)
        assert len(vendors) == 3
        # Sorted by name
        names = [v["name"] for v in vendors]
        assert names == sorted(names)

    def test_get_vendor_by_id_not_found(self, sample_accounts):
        con = sample_accounts
        assert get_vendor_by_id(con, "nonexistent") is None

    def test_update_vendor(self, sample_vendors):
        con = sample_vendors
        update_vendor(con, "acme_inc", "Acme Corporation")
        vendor = get_vendor_by_id(con, "acme_inc")
        assert vendor["name"] == "Acme Corporation"

    def test_delete_vendor_no_transactions(self, sample_vendors):
        con = sample_vendors
        delete_vendor(con, "initech")
        assert get_vendor_by_id(con, "initech") is None
        assert len(get_all_vendors(con)) == 2

    def test_delete_vendor_unlinks_transactions(self, sample_vendors):
        con = sample_vendors
        # Create a transaction linked to acme_inc
        tx_id = post_transaction(con, "2025-01-15", "Acme purchase", [
            ("datacenter", 50000),
            ("cap1", -50000),
        ], vendor_id="acme_inc")
        assert get_vendor_transaction_count(con, "acme_inc") == 1

        # Delete the vendor -- should set vendor_id to NULL
        delete_vendor(con, "acme_inc")
        assert get_vendor_by_id(con, "acme_inc") is None

        # Transaction still exists but vendor_id is NULL
        row = con.execute(
            "SELECT vendor_id FROM transactions WHERE id = ?", (tx_id,)
        ).fetchone()
        assert row[0] is None

    def test_get_vendor_transaction_count(self, sample_vendors):
        con = sample_vendors
        assert get_vendor_transaction_count(con, "acme_inc") == 0

        post_transaction(con, "2025-01-15", "Purchase 1", [
            ("datacenter", 10000),
            ("cap1", -10000),
        ], vendor_id="acme_inc")
        post_transaction(con, "2025-01-16", "Purchase 2", [
            ("cloud", 20000),
            ("cap1", -20000),
        ], vendor_id="acme_inc")

        assert get_vendor_transaction_count(con, "acme_inc") == 2
        assert get_vendor_transaction_count(con, "globex_corp") == 0
