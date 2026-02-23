```
 ===============================================================================
 ||                                                                           ||
 ||           ooooooooo.   oooooo   oooo ooooooooo.   oooooooooooo            ||
 ||           `888   `Y88.  `888.   .8'  `888   `Y88. `888'     `8            ||
 ||            888   .d88'   `888. .8'    888   .d88'  888                    ||
 ||            888ooo88P'     `888.8'     888ooo88P'   888oooo8               ||
 ||            888             `888'      888`88b.     888    "               ||
 ||            888              888       888  `88b.   888       o            ||
 ||           o888o            o888o     o888o  o888o o888ooooood8            ||
 ||                                                                           ||
 ||                   * * *  D O U B L E - E N T R Y  * * *                   ||
 ||                     -= Accounting for the Terminal =-                     ||
 ||                                                                           ||
 ===============================================================================

                                        ,
                                       /|\
                                  ,   / | \   ,
                                 /|\ (  |  ) /|\
                                ( | ) \ | / ( | )
                                 \|/   \|/   \|/
                                  '     '     '
                                  |     |     |
                      ~~~~~~~~~~~~+~~~~~+~~~~~+~~~~~~~~~~~~

               .:[  Y O U R   B O O K S .   B A L A N C E D .  ]:.

  >> Your data .................... A single SQLite file
  >> Your interface ............... A fast, keyboard-driven TUI
  >> Your philosophy .............. No cloud. No subscription. No lock-in.
  >> Your sanity .................. No ads. No loading screens.
                                    We never bother you.

  +----------------------------------------------------------------------------+
  |       "For every debit, there must be an equal and opposite credit."       |
  +----------------------------------------------------------------------------+

                                [ LEDGER ONLINE ]
```

## Features

- Full double-entry ledger with split transactions
- Hierarchical Chart of Accounts (16 account types across 5 families)
- OFX/QFX, CSV, and Gusto payroll import with automatic payee matching
- Account reconciliation
- Scheduled/recurring transactions
- Balance Sheet, Profit & Loss, Trial Balance, Cash Flow, and Vendor reports (PDF export)
- Quick Functions -- one-key transaction templates for recurring purchases
- Keyboard-driven -- everything is a few keystrokes away

## Quick Start

```
# Install dependencies and seed a starter Chart of Accounts
make setup

# Run Pyre
make run
```

`make setup` creates a Python virtualenv, installs dependencies, and seeds a
minimal personal Chart of Accounts (checking, savings, credit card, common
expense categories, etc.). You can add, rename, or reorganize accounts from
within the app at any time.

To skip the starter accounts and start with an empty book:

```
make setup SKIP_COA=1
```

## Requirements

- Python 3.10+
- A terminal with 256-color support (most modern terminals)

## Configuration

Copy the sample files and edit to taste:

```
cp .env.sample .env
cp company.yaml.sample company.yaml
cp quick_functions.yaml.sample quick_functions.yaml
```

- `.env` -- set `PYRE_DB_PATH` to control where the database lives (default: `./pyre.db`)
- `company.yaml` -- company/entity name shown in reports and the title bar
- `quick_functions.yaml` -- keyboard-triggered transaction templates (see below)
- `gusto.yaml` -- Gusto payroll account mapping, copied from `gusto.yaml.sample` (see below)
- `preferences.yaml` -- UI theme and report output paths (see below)

## Report Output Paths

By default, PDF reports are saved to the current working directory with
auto-generated filenames. You can customize where reports are saved by adding
a `report_output` section to `preferences.yaml` (located next to your database
file).

```yaml
report_output:
  base_path: ~/reports/%Y/%m - %B/
  filenames:
    pnl: Profit & Loss.pdf
    balance_sheet: Balance Sheet.pdf
    cash_flow: Cash Flow Statement.pdf
    reconciliation: "{account_name} Reconciliation Report.pdf"
    expenses_by_vendor: Expenses by Vendor Summary.pdf
```

**base_path** is a directory template. **filenames** maps each report type to a
filename template. Both support `strftime` placeholders (`%Y`, `%m`, `%B`,
etc.) which are expanded using the report's date. Filename templates also
support Python `.format()` variables for report-specific data.

Available variables per report type:

| Report             | Key                  | Variables                |
| ------------------ | -------------------- | ------------------------ |
| Profit & Loss      | `pnl`                | `start_date`, `end_date` |
| Balance Sheet      | `balance_sheet`      | `as_of_date`             |
| Cash Flow          | `cash_flow`          | `start_date`, `end_date` |
| Reconciliation     | `reconciliation`     | `account_name`           |
| Expenses by Vendor | `expenses_by_vendor` | `start_date`, `end_date` |

Common `strftime` codes: `%Y` (2026), `%m` (01), `%B` (January), `%b` (Jan),
`%d` (31).

With the example configuration above and a January 2026 report, the P&L would
be saved to `~/reports/2026/01 - January/Profit & Loss.pdf`. Directories are
created automatically if they don't exist. If a file already exists at the
target path, Pyre will prompt before overwriting.

If `report_output` is not configured, reports fall back to the current directory
with default filenames.

## Gusto Payroll Import

Pyre can import payroll data from [Gusto](https://gusto.com) using their
General Ledger report. Each report covers one pay period and produces a
balanced journal entry with full line-item detail (wages, taxes, benefits,
net pay, etc.).

**Setup:**

1. Copy the sample config and edit the account mappings to match your Chart of
   Accounts:

```
cp gusto.yaml.sample gusto.yaml
```

```yaml
account_map:
  RegularWages: salaries_and_wages
  HolidayWages: salaries_and_wages
  BenefitCompanyContribution: employee_benefits
  BenefitLiability: payroll_liabilities
  DebitNetPay: checking          # your payroll bank account
  DebitTax: checking             # same payroll bank account

  # String value: all splits of this type go to one account
  # EmployerTax: payroll_taxes

  # Dict value: route by description substring for finer control
  EmployerTax:
    Social Security: payroll_taxes_fica
    Medicare: payroll_taxes_fica
    FUTA: payroll_taxes_futa
    SUI: payroll_taxes_sui
    ETT: payroll_taxes_ett
```

2. In Gusto, go to **Reports > General ledger report**, select a pay period,
   and download the XLSX file.

3. Import the file into Pyre (either from the TUI import screen or via
   `make import FILE=path/to/general_ledger.xlsx`).

Any Gusto account types not present in `gusto.yaml` will be flagged as errors
during import. Just add the missing type to your config and re-import.

## Usage

```
make run                            # Launch the TUI
make import FILE=path/to/file.qfx   # Import a bank file
make backup                         # Back up the database
make backup NOTE="before cleanup"   # Back up with a note
make backup-list                    # List existing backups
```

## Tests

```
make test
```

## Database Checker

Checks the database for integrity issues: unbalanced transactions, parent-child
type mismatches, orphaned references, circular hierarchies, and more.

```
make check
```

## Quick Functions

Quick Functions let you post common transactions with a single keypress.
Press `1` through `9` from the main ledger to fire a template instantly, or
press `Shift+F` to enter Quick Function mode for letter-key bindings.

Each template defines which accounts to debit/credit, which amounts to prompt
for, and which split auto-balances. A sample file is included:

```
cp quick_functions.yaml.sample quick_functions.yaml
```

Example entry (groceries charged to a credit card):

```yaml
- key: "1"
  group: Food
  label: Groceries
  description: Groceries
  splits:
    - account: food__groceries
      direction: debit
      prompt: Amount # ask the user for this amount
    - account: credit_card
      direction: credit
      prompt: null # auto-balance (pays the rest)
```

Optional fields on splits:

- `pick_account: true` -- let the user choose the account at runtime (e.g.
  pick which credit card to pay from)
- `amount: 2050` -- fixed amount in cents instead of prompting
- `vendor: "acme"` -- attach a vendor ID to the transaction

Set `fixed_splits: true` on the template to prompt for multiple amounts
without item-row duplication (useful for bills with separate line items like
principal + interest + escrow).

See `quick_functions.yaml.sample` for more examples.

## Importing an Existing Chart of Accounts

If you're migrating from another system, Pyre includes import scripts for
QuickBooks and GnuCash:

```
. venv/bin/activate
python scripts/import_chart_of_accounts.py accounts.csv    # QuickBooks CSV
python scripts/import_gnucash_accounts.py book.gnucash     # GnuCash XML
```

## Who's Using Pyre

- [ARP Networks, Inc.](https://arpnetworks.com) -- VPS and cloud dedicated server hosting

Using Pyre? Open a PR to add yourself here.

## License

MIT License. See [LICENSE](LICENSE) for details.
