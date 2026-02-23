#!/usr/bin/env python3
"""Inspect GNUCash XML file to understand account structure."""
import gzip
import sys
import xml.etree.ElementTree as ET

if len(sys.argv) < 2:
    print("Usage: inspect_gnucash.py <path-to-gnucash-file>")
    sys.exit(1)
path = sys.argv[1]

with gzip.open(path, "rb") as f:
    tree = ET.parse(f)
root = tree.getroot()

ACT = "{http://www.gnucash.org/XML/act}"
CMDTY = "{http://www.gnucash.org/XML/cmdty}"
GNC = "{http://www.gnucash.org/XML/gnc}"

accounts = []
for acct in root.iter(f"{GNC}account"):
    name = acct.find(f"{ACT}name").text
    atype = acct.find(f"{ACT}type").text
    guid = acct.find(f"{ACT}id").text
    parent_el = acct.find(f"{ACT}parent")
    parent_guid = parent_el.text if parent_el is not None else None
    desc_el = acct.find(f"{ACT}description")
    desc = desc_el.text if desc_el is not None else ""
    commodity = acct.find(f"{ACT}commodity")
    cmdty_space = ""
    cmdty_id = ""
    if commodity is not None:
        s = commodity.find(f"{CMDTY}space")
        i = commodity.find(f"{CMDTY}id")
        if s is not None:
            cmdty_space = s.text
        if i is not None:
            cmdty_id = i.text
    accounts.append({
        "guid": guid,
        "name": name,
        "type": atype,
        "parent_guid": parent_guid,
        "desc": desc,
        "cmdty_space": cmdty_space,
        "cmdty_id": cmdty_id,
    })

types = {}
for a in accounts:
    types[a["type"]] = types.get(a["type"], 0) + 1
print("=== Account type counts ===")
for t, c in sorted(types.items()):
    print(f"  {t}: {c}")

guid_map = {a["guid"]: a for a in accounts}
children = {}
for a in accounts:
    if a["parent_guid"]:
        children.setdefault(a["parent_guid"], []).append(a)


def show(guid, indent=0):
    acct = guid_map[guid]
    tag = ""
    if acct["cmdty_space"] not in ("CURRENCY", "") or acct["cmdty_id"] not in ("USD", ""):
        tag = f' [{acct["cmdty_space"]}:{acct["cmdty_id"]}]'
    print(f"{'  ' * indent}{acct['name']} ({acct['type']}){tag}")
    for child in sorted(children.get(guid, []), key=lambda x: x["name"]):
        show(child["guid"], indent + 1)


print()
print("=== Account tree ===")
root_acct = [a for a in accounts if a["type"] == "ROOT"][0]
show(root_acct["guid"])
