QUICK_ENTRY_CSS = """
QuickEntryScreen {
    align: center middle;
}
#qe-dialog {
    width: 90%;
    max-width: 130;
    height: auto;
    max-height: 80%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#qe-title {
    text-style: bold;
    color: $text;
    margin-bottom: 1;
}
#qe-desc {
    color: $text-muted;
    margin-bottom: 1;
}
.qe-field-label {
    margin-top: 1;
    color: $text;
}
.qe-input {
    margin-bottom: 0;
}
#qe-date {
    width: 25;
}
#qe-items-container {
    height: auto;
}
.qe-item-row {
    height: 3;
    margin-top: 1;
}
.qe-item-desc {
    width: 1fr;
}
.qe-item-amount {
    width: 20;
    margin: 0 1;
}
.qe-item-remove {
    width: 4;
    min-width: 4;
}
#qe-add-item-row {
    height: auto;
    margin-top: 1;
}
#qe-extras-row {
    height: auto;
    margin-top: 1;
}
.qe-amount-group {
    height: auto;
    width: 1fr;
    margin-right: 1;
}
.qe-amount-group:last-of-type {
    margin-right: 0;
}
.qe-amount-field {
    margin-bottom: 0;
}
#qe-from {
    margin-top: 1;
    color: $text-muted;
}
.qe-pick-account {
    margin-top: 1;
    height: auto;
    width: 100%;
}
#qe-status {
    margin-top: 1;
    color: $success;
}
#qe-error {
    margin-top: 1;
    color: $error;
}
#qe-buttons {
    height: auto;
    margin-top: 1;
}
#qe-buttons Button {
    margin-right: 1;
}
"""

EDIT_TRANSACTION_CSS = """
EditTransactionScreen {
    align: center middle;
}
#edit-dialog {
    width: 100;
    height: auto;
    max-height: 80%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#edit-title {
    text-style: bold;
    color: $text;
    margin-bottom: 1;
}
.edit-field-label {
    margin-top: 1;
    color: $text;
}
.edit-input {
    margin-bottom: 0;
}
.split-row {
    height: 3;
    margin-top: 1;
}
.split-account-label {
    width: 1fr;
    height: 3;
    content-align-vertical: middle;
}
.split-amount-input {
    width: 30;
}
#edit-balance {
    margin-top: 1;
}
.edit-balanced {
    color: $success;
}
.edit-unbalanced {
    color: $error;
}
#edit-error {
    color: $error;
}
#edit-buttons {
    height: auto;
    margin-top: 1;
}
#edit-buttons Button {
    margin-right: 1;
}
#edit-spacer {
    width: 1fr;
}
"""

PROFIT_LOSS_CSS = """
ProfitLossScreen {
    align: center middle;
}
#pnl-container {
    width: 80;
    height: auto;
    max-height: 90%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#pnl-title {
    text-style: bold;
    color: $accent;
    text-align: center;
    margin-bottom: 1;
}
#pnl-subtitle {
    text-align: center;
    color: $text-muted;
    margin-bottom: 1;
}
#pnl-table {
    height: 1fr;
}
#pnl-hint {
    color: $text-muted;
    margin-top: 1;
}
"""

CASH_FLOW_CSS = """
CashFlowScreen {
    align: center middle;
}
#cf-container {
    width: 80;
    height: auto;
    max-height: 90%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#cf-title {
    text-style: bold;
    color: $accent;
    text-align: center;
    margin-bottom: 1;
}
#cf-subtitle {
    text-align: center;
    color: $text-muted;
    margin-bottom: 1;
}
#cf-table {
    height: 1fr;
}
#cf-hint {
    color: $text-muted;
    margin-top: 1;
}
"""

BALANCE_SHEET_CSS = """
BalanceSheetScreen {
    align: center middle;
}
#bs-container {
    width: 80;
    height: auto;
    max-height: 90%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#bs-title {
    text-style: bold;
    color: $accent;
    text-align: center;
    margin-bottom: 0;
}
#bs-subtitle {
    text-align: center;
    color: $text-muted;
    margin-bottom: 1;
}
#bs-table {
    height: 1fr;
}
#bs-hint {
    color: $text-muted;
    margin-top: 1;
}
"""

TRIAL_BALANCE_CSS = """
TrialBalanceScreen {
    align: center middle;
}
#tb-container {
    width: 80;
    height: auto;
    max-height: 90%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#tb-title {
    text-style: bold;
    color: $accent;
    text-align: center;
    margin-bottom: 0;
}
#tb-subtitle {
    text-align: center;
    color: $text-muted;
    margin-bottom: 1;
}
#tb-table {
    height: 1fr;
}
#tb-hint {
    color: $text-muted;
    margin-top: 1;
}
"""

CHART_OF_ACCOUNTS_CSS = """
ChartOfAccountsScreen {
    align: center middle;
}
#coa-container {
    width: 90%;
    height: 90%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#coa-title {
    text-style: bold;
    color: $accent;
    text-align: center;
    margin-bottom: 1;
}
#coa-tree {
    height: 1fr;
    overflow-y: auto;
}
#coa-hint {
    color: $text-muted;
    margin-top: 1;
}
#coa-search-bar {
    height: 3;
    display: none;
    padding: 0;
}
#coa-search-bar.visible {
    display: block;
}
#coa-search-prompt {
    width: 2;
    height: 3;
    content-align-vertical: middle;
    color: $accent;
}
#coa-search-input {
    width: 1fr;
}
#coa-search-count {
    width: auto;
    padding: 0 1;
    height: 3;
    content-align-vertical: middle;
    color: $text-muted;
}
"""

ACCOUNT_FORM_CSS = """
AccountFormScreen {
    align: center middle;
}
#af-dialog {
    width: 80;
    height: auto;
    max-height: 80%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#af-title {
    text-style: bold;
    color: $text;
    margin-bottom: 1;
}
.af-field-label {
    margin-top: 1;
    color: $text;
}
.af-input {
    margin-bottom: 0;
}
#af-error {
    margin-top: 1;
    color: $error;
}
#af-buttons {
    height: auto;
    margin-top: 1;
}
#af-buttons Button {
    margin-right: 1;
}
.af-switch-row {
    height: auto;
    margin-top: 1;
}
.af-switch-row .af-field-label {
    margin-top: 0;
    padding-top: 1;
    width: auto;
}
#af-sidebar {
    margin-left: 1;
}
"""

SAVE_PDF_CSS = """
SavePdfDialog {
    align: center middle;
}
#sp-dialog {
    width: 50;
    height: auto;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#sp-title {
    text-style: bold;
    color: $accent;
    text-align: center;
    margin-bottom: 1;
}
#sp-buttons {
    height: auto;
    margin-top: 1;
}
#sp-buttons Button {
    margin-right: 1;
}
"""

CONFIRM_DELETE_CSS = """
ConfirmDeleteScreen {
    align: center middle;
}
#cd-dialog {
    width: 60;
    height: auto;
    max-height: 80%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#cd-title {
    text-style: bold;
    color: $error;
    margin-bottom: 1;
}
#cd-message {
    margin-bottom: 1;
}
#cd-buttons {
    height: auto;
    margin-top: 1;
}
#cd-buttons Button {
    margin-right: 1;
}
"""

CONFIRM_OVERWRITE_CSS = """
ConfirmOverwriteScreen {
    align: center middle;
}
#co-dialog {
    width: auto;
    max-width: 90;
    height: auto;
    max-height: 80%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#co-title {
    text-style: bold;
    color: $warning;
    margin-bottom: 1;
}
#co-message {
    margin-bottom: 1;
}
#co-buttons {
    height: auto;
    margin-top: 1;
}
#co-buttons Button {
    margin-right: 1;
}
"""

CONFIRM_DELETE_TX_CSS = """
ConfirmDeleteTransactionScreen {
    align: center middle;
}
#cd-dialog {
    width: 60;
    height: auto;
    max-height: 80%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#cd-title {
    text-style: bold;
    color: $error;
    margin-bottom: 1;
}
#cd-message {
    margin-bottom: 1;
}
#cd-buttons {
    height: auto;
    margin-top: 1;
}
#cd-buttons Button {
    margin-right: 1;
}
"""

REPORT_DATE_CSS = """
ReportDateScreen {
    align: center middle;
}
#rd-dialog {
    width: 60;
    height: auto;
    max-height: 80%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#rd-title {
    text-style: bold;
    color: $accent;
    text-align: center;
    margin-bottom: 1;
}
.rd-preset {
    width: 100%;
    margin-bottom: 0;
}
.rd-preset.-active {
    background: $accent;
    color: $text;
}
#rd-custom-fields {
    height: auto;
    display: none;
    margin-top: 1;
}
#rd-custom-fields.visible {
    display: block;
}
.rd-field-label {
    margin-top: 1;
    color: $text;
}
.rd-input {
    margin-bottom: 0;
}
#rd-error {
    margin-top: 1;
    color: $error;
}
#rd-confirm-row {
    height: auto;
    margin-top: 1;
}
"""

ADD_TRANSACTION_CSS = """
TransactionFormBase, AddTransactionScreen, EditTransactionScreen {
    align: center middle;
}
#at-dialog {
    width: 60%;
    min-width: 100;
    height: auto;
    max-height: 80%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#at-title {
    text-style: bold;
    color: $text;
    margin-bottom: 1;
}
.at-field-label {
    margin-top: 1;
    color: $text;
}
.at-input {
    margin-bottom: 0;
}
.at-date-vendor-row {
    height: auto;
}
.at-date-col {
    width: 25;
    height: auto;
}
.at-vendor-col {
    width: 1fr;
    height: auto;
    margin-left: 2;
}
#at-splits-container {
    height: auto;
    margin-top: 1;
}
.at-split-row {
    height: 3;
    margin-top: 1;
}
.at-split-account {
    width: 1fr;
    text-align: left;
    background: $surface;
    border: tall $accent;
    color: $text;
}
.at-split-amount {
    width: 20;
    margin: 0 1;
}
.at-split-dir {
    width: 6;
    min-width: 6;
}
.at-split-remove {
    width: 4;
    min-width: 4;
    margin-left: 1;
}
.at-split-memo-row {
    height: 3;
}
.at-split-memo-row Input {
    width: 1fr;
}
.at-split-memo-row.hidden {
    display: none;
}
#at-add-split-row {
    height: auto;
    margin-top: 1;
}
#at-add-split-row Button {
    margin-right: 2;
}
#at-balance {
    margin-top: 1;
}
.at-balanced {
    color: $success;
}
.at-unbalanced {
    color: $error;
}
#at-error {
    color: $error;
}
#at-hint {
    color: $text-muted;
    text-align: center;
    margin-top: 1;
}
#at-buttons {
    height: auto;
    margin-top: 1;
}
#at-buttons Button {
    margin-right: 1;
}
#at-spacer {
    width: 1fr;
}
#at-delete {
    margin-right: 0;
}
"""

IMPORT_FILE_CSS = """
ImportFileScreen, EditDescriptionScreen, EditRuleScreen {
    align: center middle;
}
#if-dialog {
    width: 80;
    height: auto;
    max-height: 80%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#if-title {
    text-style: bold;
    color: $text;
    margin-bottom: 1;
}
.if-field-label {
    margin-top: 1;
    color: $text;
}
.if-input {
    margin-bottom: 0;
}
#if-error {
    margin-top: 1;
    color: $error;
}
#if-buttons {
    height: auto;
    margin-top: 1;
}
#if-buttons Button {
    margin-right: 1;
}
#er-account-btn {
    width: 1fr;
    text-align: left;
}
"""

IMPORT_REVIEW_CSS = """
ImportReviewScreen {
    align: center middle;
}
#ir-container {
    width: 95%;
    height: auto;
    max-height: 70%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#ir-title {
    text-style: bold;
    color: $accent;
    text-align: center;
    margin-bottom: 1;
}
#ir-status {
    color: $text-muted;
    margin-bottom: 1;
}
#ir-table {
    height: 1fr;
}
#ir-hint {
    color: $text-muted;
    margin-top: 1;
}
"""

JOURNAL_REVIEW_CSS = """
JournalReviewScreen {
    align: center middle;
}
JournalReviewScreen Toast {
    width: 90;
    max-width: 75%;
}
#jr-container {
    width: 95%;
    height: auto;
    max-height: 70%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#jr-title {
    text-style: bold;
    color: $accent;
    text-align: center;
    margin-bottom: 1;
}
#jr-status {
    color: $text-muted;
    margin-bottom: 1;
}
#jr-table {
    height: 1fr;
}
#jr-hint {
    color: $text-muted;
    margin-top: 1;
}
"""

ACCOUNT_PICKER_CSS = """
AccountPickerScreen, AccountQuickPickScreen {
    align: center middle;
}
#ap-dialog {
    width: 120;
    height: auto;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#ap-title {
    text-style: bold;
    color: $text;
    margin-bottom: 1;
}
#ap-vendor-label {
    margin-top: 1;
}
#ap-buttons {
    height: auto;
    margin-top: 1;
}
#ap-buttons Button {
    margin-right: 1;
}
"""

PAYEE_RULES_CSS = """
PayeeRulesScreen {
    align: center middle;
}
#pr-container {
    width: 80%;
    height: auto;
    max-height: 60%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#pr-title {
    text-style: bold;
    color: $accent;
    text-align: center;
    margin-bottom: 1;
}
#pr-status {
    color: $text-muted;
    margin-bottom: 1;
}
#pr-table {
    height: 1fr;
}
#pr-hint {
    color: $text-muted;
    margin-top: 1;
}
"""

RECONCILE_SETUP_CSS = """
ReconcileSetupScreen {
    align: center middle;
}
#rs-dialog {
    height: auto;
    max-height: 80%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#rs-title {
    text-style: bold;
    color: $accent;
    text-align: center;
    margin-bottom: 1;
}
.rs-field-label {
    margin-top: 1;
    color: $text;
}
.rs-info {
    color: $text-muted;
}
.rs-input {
    margin-bottom: 0;
}
#rs-error {
    margin-top: 1;
    color: $error;
}
#rs-buttons {
    height: auto;
    margin-top: 1;
}
#rs-buttons Button {
    margin-right: 1;
}
"""

RECONCILE_WORKSHEET_CSS = """
ReconcileWorksheetScreen {
    align: center middle;
}
#rw-container {
    width: 70%;
    height: 70%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#rw-title {
    text-style: bold;
    color: $accent;
    text-align: center;
}
#rw-subtitle {
    text-align: center;
    color: $text-muted;
    margin-bottom: 1;
}
#rw-summary {
    height: 3;
    margin-bottom: 1;
}
.rw-summary-col {
    width: 1fr;
    height: 3;
    content-align: center middle;
}
.rw-summary-label {
    text-align: center;
    color: $text-muted;
}
.rw-summary-value {
    text-align: center;
    text-style: bold;
}
.rw-balanced {
    color: $success;
}
.rw-unbalanced {
    color: $error;
}
#rw-table {
    height: 1fr;
}
#rw-hint {
    color: $text-muted;
    margin-top: 1;
}
"""

QUICK_FUNCTION_PICKER_CSS = """
QuickFunctionPickerScreen {
    align: center middle;
}
#qfp-dialog {
    width: 60;
    height: auto;
    max-height: 70%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#qfp-title {
    text-style: bold;
    color: $accent;
    margin-bottom: 1;
}
#qfp-list {
    height: auto;
    max-height: 20;
}
#qfp-hint {
    color: $text-muted;
    margin-top: 1;
}
"""

VENDOR_LIST_CSS = """
VendorListScreen {
    align: center middle;
}
#vl-container {
    width: 70%;
    height: 70%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#vl-title {
    text-style: bold;
    color: $accent;
    text-align: center;
    margin-bottom: 1;
}
#vl-table {
    height: 1fr;
}
#vl-hint {
    color: $text-muted;
    margin-top: 1;
}
#vl-search-bar {
    height: 3;
    display: none;
    padding: 0;
}
#vl-search-bar.visible {
    display: block;
}
#vl-search-prompt {
    width: 2;
    height: 3;
    content-align-vertical: middle;
    color: $accent;
}
#vl-search-input {
    width: 1fr;
}
#vl-search-count {
    width: auto;
    padding: 0 1;
    height: 3;
    content-align-vertical: middle;
    color: $text-muted;
}
"""

CONFIRM_DELETE_VENDOR_CSS = """
ConfirmDeleteVendorScreen {
    align: center middle;
}
#cdv-dialog {
    width: 60;
    height: auto;
    max-height: 80%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#cdv-title {
    text-style: bold;
    color: $error;
    margin-bottom: 1;
}
#cdv-message {
    margin-bottom: 1;
}
#cdv-buttons {
    height: auto;
    margin-top: 1;
}
#cdv-buttons Button {
    margin-right: 1;
}
"""

VENDOR_FORM_CSS = """
VendorFormScreen {
    align: center middle;
}
#vf-dialog {
    width: 80;
    height: auto;
    max-height: 80%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#vf-title {
    text-style: bold;
    color: $text;
    margin-bottom: 1;
}
.vf-field-label {
    margin-top: 1;
    color: $text;
}
.vf-input {
    margin-bottom: 0;
}
#vf-error {
    margin-top: 1;
    color: $error;
}
#vf-buttons {
    height: auto;
    margin-top: 1;
}
#vf-buttons Button {
    margin-right: 1;
}
"""

EXPENSES_BY_VENDOR_CSS = """
ExpensesByVendorScreen {
    align: center middle;
}
#evs-container {
    width: 80;
    height: auto;
    max-height: 90%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#evs-title {
    text-style: bold;
    color: $accent;
    text-align: center;
    margin-bottom: 1;
}
#evs-subtitle {
    text-align: center;
    color: $text-muted;
    margin-bottom: 1;
}
#evs-table {
    height: 1fr;
}
#evs-hint {
    color: $text-muted;
    margin-top: 1;
}
"""

BULK_EDIT_CSS = """
BulkEditScreen {
    align: center middle;
}
#be-dialog {
    width: 60;
    height: auto;
    max-height: 80%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#be-title {
    text-style: bold;
    color: $text;
    margin-bottom: 1;
}
#be-hint {
    color: $text-muted;
    margin-bottom: 1;
}
#be-buttons {
    height: auto;
    margin-top: 1;
}
#be-buttons Button {
    margin-right: 1;
}
"""

APP_CSS = """
#main-container {
    height: 1fr;
}
#left-panel {
    width: 46;
    border-right: tall $accent;
    padding: 1;
}
#left-panel-title {
    text-style: bold;
    color: $accent;
    margin-bottom: 1;
}
#right-panel {
    width: 1fr;
    padding: 1;
}
#balances-title, #ledger-title {
    text-style: bold;
    color: $accent;
    margin-bottom: 1;
}
#bulk-indicator {
    display: none;
    color: $warning;
    text-style: bold;
    padding: 0 1;
    margin-bottom: 1;
}
#bulk-indicator.active {
    display: block;
}
#balances-box {
    height: auto;
    max-height: 14;
    margin-bottom: 1;
}
.balance-row {
    height: 1;
}
.fav-key {
    color: $text-muted;
    width: 5;
}
.fav-key-active {
    color: $accent;
    text-style: bold;
}
.balance-label {
    width: 1fr;
}
.balance-amount {
    width: 14;
    text-align: right;
}
.balance-amount-neg {
    width: 14;
    text-align: right;
    color: $error;
}
#ledger-table {
    height: 1fr;
}
.qf-group {
    height: 1;
    margin-top: 1;
    color: $text-muted;
    text-style: bold;
}
.qf-item {
    height: 1;
}
.qf-key {
    color: $text-muted;
    width: 4;
}
.qf-key-active {
    color: $accent;
    text-style: bold;
}
.qf-label {
    width: 1fr;
}
#status-line {
    dock: bottom;
    height: 1;
    background: $accent;
    color: $text;
    padding: 0 1;
}
#search-bar {
    dock: bottom;
    height: 6;
    padding: 1 1;
    background: $surface;
    border-top: tall $accent;
    display: none;
}
#search-bar.visible {
    display: block;
}
#search-input {
    width: 1fr;
}
#search-count {
    dock: right;
    width: auto;
    padding: 0 1;
    color: $text-muted;
}
"""

PENDING_SCHEDULED_CSS = """
PendingScheduledScreen {
    align: center middle;
}
#ps-container {
    width: 100;
    height: auto;
    max-height: 80%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#ps-title {
    text-style: bold;
    color: $accent;
    text-align: center;
    margin-bottom: 1;
}
#ps-table {
    height: 1fr;
}
#ps-hint {
    color: $text-muted;
    margin-top: 1;
}
#ps-buttons {
    height: auto;
    margin-top: 1;
}
#ps-buttons Button {
    margin-right: 1;
}
"""

SCHEDULED_LIST_CSS = """
ScheduledListScreen {
    align: center middle;
}
#sl-container {
    width: 70%;
    height: 70%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#sl-title {
    text-style: bold;
    color: $accent;
    text-align: center;
    margin-bottom: 1;
}
#sl-table {
    height: 1fr;
}
#sl-hint {
    color: $text-muted;
    margin-top: 1;
}
#sl-search-bar {
    height: 3;
    display: none;
    padding: 0;
}
#sl-search-bar.visible {
    display: block;
}
#sl-search-prompt {
    width: 2;
    height: 3;
    content-align-vertical: middle;
    color: $accent;
}
#sl-search-input {
    width: 1fr;
}
#sl-search-count {
    width: auto;
    padding: 0 1;
    height: 3;
    content-align-vertical: middle;
    color: $text-muted;
}
"""

SCHEDULED_FORM_CSS = """
ScheduledFormScreen {
    align: center middle;
}
#sf-dialog {
    width: 60%;
    min-width: 100;
    height: auto;
    max-height: 80%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#sf-title {
    text-style: bold;
    color: $text;
    margin-bottom: 1;
}
.sf-field-label {
    margin-top: 1;
    color: $text;
}
.sf-input {
    margin-bottom: 0;
}
.sf-schedule-row {
    height: auto;
}
.sf-schedule-col {
    width: 1fr;
    height: auto;
    margin-right: 2;
}
.sf-schedule-col:last-of-type {
    margin-right: 0;
}
.sf-enabled-row {
    height: auto;
    margin-top: 1;
}
.sf-enabled-row .sf-field-label {
    margin-top: 0;
    padding-top: 1;
    width: auto;
}
#sf-enabled {
    margin-left: 1;
}
"""

CONFIRM_DELETE_SCHEDULED_CSS = """
ConfirmDeleteScheduledScreen {
    align: center middle;
}
#cds-dialog {
    width: 60;
    height: auto;
    max-height: 80%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#cds-title {
    text-style: bold;
    color: $error;
    margin-bottom: 1;
}
#cds-message {
    margin-bottom: 1;
}
#cds-buttons {
    height: auto;
    margin-top: 1;
}
#cds-buttons Button {
    margin-right: 1;
}
"""

ACCOUNT_FUZZY_PICK_CSS = """
AccountFuzzyPickScreen {
    align: center middle;
}
#afp-dialog {
    width: 80;
    height: auto;
    max-height: 70%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#afp-title {
    text-style: bold;
    color: $text;
    margin-bottom: 1;
}
#afp-results {
    height: 20;
    margin-top: 1;
}
#afp-hint {
    color: $text-muted;
    margin-top: 1;
}
"""

RECONCILIATION_PICKER_CSS = """
ReconciliationReportPickerScreen {
    align: center middle;
}
#rrp-container {
    width: 70%;
    height: 70%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#rrp-title {
    text-style: bold;
    color: $accent;
    text-align: center;
    margin-bottom: 1;
}
#rrp-table {
    height: 1fr;
}
#rrp-hint {
    color: $text-muted;
    margin-top: 1;
}
"""

RECONCILIATION_REPORT_CSS = """
ReconciliationReportScreen {
    align: center middle;
}
#rr-container {
    width: 70%;
    height: 70%;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}
#rr-title {
    text-style: bold;
    color: $accent;
    text-align: center;
    margin-bottom: 0;
}
#rr-subtitle {
    text-align: center;
    color: $text-muted;
    margin-bottom: 1;
}
#rr-table {
    height: 1fr;
}
#rr-hint {
    color: $text-muted;
    margin-top: 1;
}
"""
