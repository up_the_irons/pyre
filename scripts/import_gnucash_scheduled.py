#!/usr/bin/env python3
"""Import scheduled transactions from GNUCash XML into Pyre database."""

import gzip
import sys
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

# Allow running as standalone script
sys.path.insert(0, str(Path(__file__).parent.parent))

from pyre.db import DB_PATH, init_db, release_lock
from pyre.formatting import new_id
from scripts.import_gnucash_transactions import (
    build_guid_to_slug,
    rational_to_cents,
)

# XML namespaces
ACT = "{http://www.gnucash.org/XML/act}"
CMDTY = "{http://www.gnucash.org/XML/cmdty}"
GNC = "{http://www.gnucash.org/XML/gnc}"
REC = "{http://www.gnucash.org/XML/recurrence}"
SLOT = "{http://www.gnucash.org/XML/slot}"
SPLIT = "{http://www.gnucash.org/XML/split}"
SX = "{http://www.gnucash.org/XML/sx}"
TRN = "{http://www.gnucash.org/XML/trn}"

# Map GNUCash recurrence (mult, period_type) to Pyre frequency
FREQ_MAP = {
    (1, "week"): "weekly",
    (2, "week"): "biweekly",
    (1, "month"): "monthly",
    (1, "end of month"): "monthly",
    (3, "month"): "quarterly",
    (12, "month"): "yearly",
    (1, "year"): "yearly",
}


def _advance_gnc_date(iso_date, mult, period_type):
    """Advance date by the GNUCash recurrence to compute next_date."""
    import calendar
    from datetime import timedelta

    d = date.fromisoformat(iso_date)
    if period_type == "week":
        d = d + timedelta(days=7 * mult)
    elif period_type in ("month", "end of month"):
        month = d.month + mult
        year = d.year
        while month > 12:
            month -= 12
            year += 1
        if period_type == "end of month":
            day = calendar.monthrange(year, month)[1]
        else:
            day = min(d.day, calendar.monthrange(year, month)[1])
        d = date(year, month, day)
    elif period_type == "year":
        d = date(d.year + mult, d.month, d.day)
    return d.isoformat()


def parse_scheduled_transactions(root, guid_to_slug, all_guid_names):
    """Parse GNUCash scheduled transactions and their template splits.

    Returns list of dicts ready for insertion into Pyre.
    """
    # Collect template account GUIDs
    templ_acct_set = set()
    for acct in root.iter(f"{GNC}account"):
        commodity = acct.find(f"{ACT}commodity")
        if commodity is not None:
            space = commodity.find(f"{CMDTY}space")
            if space is not None and space.text == "template":
                templ_acct_set.add(acct.find(f"{ACT}id").text)

    # Build map: templ-acct GUID -> schedxaction metadata
    sx_map = {}
    for sx in root.iter(f"{GNC}schedxaction"):
        name_el = sx.find(f"{SX}name")
        templ = sx.find(f"{SX}templ-acct")
        enabled_el = sx.find(f"{SX}enabled")
        schedule = sx.find(f"{SX}schedule")
        end_el = sx.find(f"{SX}end")
        last_el = sx.find(f"{SX}last")
        start_el = sx.find(f"{SX}start")

        rec = schedule.find(f"{GNC}recurrence") if schedule is not None else None
        mult = int(rec.find(f"{REC}mult").text) if rec is not None else 1
        period = rec.find(f"{REC}period_type").text if rec is not None else "month"

        last_date = (
            last_el.find("gdate").text
            if last_el is not None and last_el.find("gdate") is not None
            else None
        )
        start_date = (
            start_el.find("gdate").text
            if start_el is not None and start_el.find("gdate") is not None
            else None
        )
        end_date = (
            end_el.find("gdate").text
            if end_el is not None and end_el.find("gdate") is not None
            else None
        )

        if templ is not None:
            sx_map[templ.text] = {
                "name": name_el.text if name_el is not None else "",
                "enabled": enabled_el.text == "y" if enabled_el is not None else True,
                "mult": mult,
                "period": period,
                "start": start_date,
                "last": last_date,
                "end": end_date,
            }

    # Parse template transactions to get splits
    results = []
    for trn in root.iter(f"{GNC}transaction"):
        split_els = trn.findall(f"{TRN}splits/{TRN}split")
        templ_acct_guid = None
        for sp in split_els:
            ag = sp.find(f"{SPLIT}account").text
            if ag in templ_acct_set:
                templ_acct_guid = ag
                break
        if templ_acct_guid is None:
            continue

        sx_info = sx_map.get(templ_acct_guid)
        if sx_info is None:
            continue

        description = sx_info["name"]

        # Map frequency
        freq_key = (sx_info["mult"], sx_info["period"])
        frequency = FREQ_MAP.get(freq_key)
        if frequency is None:
            print(f"  WARNING: Unsupported frequency {freq_key} for "
                  f"'{sx_info['name']}', skipping")
            continue

        # Compute next_date: advance from last occurrence, or use start
        if sx_info["last"]:
            next_date = _advance_gnc_date(
                sx_info["last"], sx_info["mult"], sx_info["period"],
            )
        else:
            next_date = sx_info["start"]

        # Parse splits from slot data
        splits = []
        unmapped = False
        for sp in split_els:
            slots = sp.find(f"{SPLIT}slots")
            if slots is None:
                continue
            sx_frame = None
            for slot in slots.findall("slot"):
                key_el = slot.find(f"{SLOT}key")
                if key_el is not None and key_el.text == "sched-xaction":
                    sx_frame = slot.find(f"{SLOT}value")
                    break
            if sx_frame is None:
                continue

            real_acct_guid = None
            debit = 0
            credit = 0
            for sub_slot in sx_frame.findall("slot"):
                k = sub_slot.find(f"{SLOT}key").text
                v = sub_slot.find(f"{SLOT}value")
                if v is None or v.text is None:
                    continue
                if k == "account":
                    real_acct_guid = v.text
                elif k == "debit-numeric":
                    debit = rational_to_cents(v.text)
                elif k == "credit-numeric":
                    credit = rational_to_cents(v.text)

            amount_cents = debit - credit
            # Drop zero-amount splits (variable placeholders in GNUCash)
            if amount_cents == 0:
                continue

            if real_acct_guid not in guid_to_slug:
                acct_name = all_guid_names.get(real_acct_guid, real_acct_guid)
                print(f"  WARNING: Unmapped account '{acct_name}' in "
                      f"'{sx_info['name']}', skipping")
                unmapped = True
                break

            splits.append((guid_to_slug[real_acct_guid], amount_cents))

        if unmapped:
            continue

        # Verify balance
        total = sum(s[1] for s in splits)
        if total != 0:
            print(f"  WARNING: Unbalanced scheduled tx '{sx_info['name']}' "
                  f"(off by {total} cents), skipping")
            continue

        if not splits:
            print(f"  WARNING: No splits for '{sx_info['name']}', skipping")
            continue

        results.append({
            "name": sx_info["name"],
            "description": description,
            "frequency": frequency,
            "next_date": next_date,
            "end_date": sx_info["end"],
            "enabled": sx_info["enabled"],
            "splits": splits,
        })

    return results


def import_scheduled(con, scheduled_txns):
    """Insert parsed scheduled transactions into Pyre database."""
    imported = 0
    for st in scheduled_txns:
        st_id = new_id()
        con.execute(
            "INSERT INTO scheduled_transactions "
            "(id, description, frequency, next_date, end_date, enabled) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (st_id, st["description"], st["frequency"], st["next_date"],
             st["end_date"], 1 if st["enabled"] else 0),
        )
        for acct_id, amount in st["splits"]:
            con.execute(
                "INSERT INTO scheduled_splits "
                "(id, scheduled_tx_id, account_id, amount, description) "
                "VALUES (?, ?, ?, ?, ?)",
                (new_id(), st_id, acct_id, amount, ""),
            )
        imported += 1

    con.commit()
    return imported


def main():
    if len(sys.argv) < 2:
        print("Usage: import_gnucash_scheduled.py <path-to-gnucash-file>")
        sys.exit(1)

    gnucash_path = Path(sys.argv[1])
    if not gnucash_path.exists():
        print(f"ERROR: GNUCash file not found: {gnucash_path}")
        sys.exit(1)

    print(f"Importing scheduled transactions from {gnucash_path}")

    con = init_db()

    # Check for existing scheduled transactions
    existing = con.execute(
        "SELECT count(*) FROM scheduled_transactions"
    ).fetchone()[0]
    if existing > 0:
        print(f"  Database already has {existing} scheduled transactions.")
        print("  Drop existing and reimport? (y/n) ", end="")
        answer = input().strip().lower()
        if answer == "y":
            con.execute("DELETE FROM scheduled_splits")
            con.execute("DELETE FROM scheduled_transactions")
            con.commit()
            print("  Cleared existing scheduled transactions.")
        else:
            print("  Aborting.")
            con.close()
            release_lock()
            sys.exit(0)

    print("Building account mapping...")
    guid_to_slug, all_guid_names, root = build_guid_to_slug(gnucash_path, con)
    print(f"  Mapped {len(guid_to_slug)} accounts")

    print("Parsing scheduled transactions...")
    scheduled_txns = parse_scheduled_transactions(
        root, guid_to_slug, all_guid_names,
    )

    print(f"  Found {len(scheduled_txns)} scheduled transactions:")
    for st in scheduled_txns:
        enabled_tag = "" if st["enabled"] else " (disabled)"
        print(f"    {st['description']:40s} {st['frequency']:10s} "
              f"next={st['next_date']}{enabled_tag}")

    print("\nImporting...")
    imported = import_scheduled(con, scheduled_txns)
    print(f"  Imported {imported} scheduled transactions")

    con.close()
    release_lock()
    print("\nDone.")


if __name__ == "__main__":
    main()
