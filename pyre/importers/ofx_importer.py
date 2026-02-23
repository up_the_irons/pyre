"""OFX file parser using ofxtools."""

from decimal import Decimal

from ofxtools.Parser import OFXTree

from pyre.importers import ImportedTxn


def parse_ofx(filepath):
    """Parse an OFX/QFX file.

    Returns (account_info, transactions) where:
        account_info: {"bankid": str|None, "acctid": str, "accttype": str}
        transactions: list[ImportedTxn]
    """
    parser = OFXTree()
    with open(filepath, "rb") as f:
        parser.parse(f)
    ofx = parser.convert()

    account_info = None
    transactions = []

    # Handle bank statements (STMTRS)
    for stmt in getattr(ofx, "statements", []):
        account_info = {
            "bankid": getattr(stmt.account, "bankid", None),
            "acctid": stmt.account.acctid,
            "accttype": getattr(stmt.account, "accttype", "CHECKING"),
        }
        for txn in stmt.transactions:
            amt = int(Decimal(str(txn.trnamt)) * 100)
            transactions.append(ImportedTxn(
                date=txn.dtposted.strftime("%Y-%m-%d"),
                description=(txn.name or txn.memo or "").strip(),
                amount_cents=amt,
                fitid=txn.fitid,
                memo=(txn.memo or "").strip(),
                txn_type=(txn.trntype or "OTHER").strip(),
                hash=None,
            ))

    # Handle credit card statements (CCSTMTRS)
    for stmt in getattr(ofx, "ccstatements", []) if not account_info else []:
        account_info = {
            "bankid": None,
            "acctid": stmt.account.acctid,
            "accttype": "CREDITCARD",
        }
        for txn in stmt.transactions:
            amt = int(Decimal(str(txn.trnamt)) * 100)
            transactions.append(ImportedTxn(
                date=txn.dtposted.strftime("%Y-%m-%d"),
                description=(txn.name or txn.memo or "").strip(),
                amount_cents=amt,
                fitid=txn.fitid,
                memo=(txn.memo or "").strip(),
                txn_type=(txn.trntype or "OTHER").strip(),
                hash=None,
            ))

    return account_info, transactions
