// Mirrors the backend schemas (backend/app/modules/*/schemas.py). All amounts are integer paise.

export interface AuthStatus {
  setup_required: boolean;
  authenticated: boolean;
  username: string | null;
}

// Credit cards and loans come later as their own features.
export type AccountType = 'asset' | 'cash' | 'expense' | 'revenue';
export type TxnType = 'withdrawal' | 'deposit' | 'transfer';

export interface AccountRef {
  id: number;
  name: string;
  type: AccountType;
}

export interface Account extends AccountRef {
  account_number: string | null;
  opening_balance: number;
  opening_date: string | null;
  active: boolean;
  notes: string | null;
  balance: number;
  transaction_count: number;
  last_activity: string | null;
}

export type CategoryKind = 'expense' | 'income';

export interface CategoryRef {
  id: number;
  name: string;
  kind: CategoryKind;
  icon: string;
  color: string;
  essential: boolean; // counts towards the emergency fund
}

export interface Category extends CategoryRef {
  transaction_count: number;
  spent_this_month: number;
}

export interface Tag {
  id: number;
  name: string;
  transaction_count: number;
}

// ---------- budgets (F6)

export type BudgetMode = 'manual' | 'fixed' | 'rollover';

export interface Budget {
  id: number;
  name: string;
  active: boolean;
  mode: BudgetMode;
  amount: number; // per month (fixed / rollover)
  month: string;
  limit: number | null; // this month's amount; null = none set
  limit_is_auto: boolean;
  spent: number;
  left: number | null;
}

export interface BudgetMonth {
  month: string;
  budgets: Budget[];
  budgeted: number;
  spent: number;
  unbudgeted_spent: number;
}

export interface NamedRef {
  id: number;
  name: string;
}

export interface Txn {
  id: number;
  type: TxnType;
  date: string;
  amount: number;
  description: string;
  source: AccountRef;
  destination: AccountRef;
  category: CategoryRef | null;
  budget: NamedRef | null;
  bill: NamedRef | null;
  gmail: GmailRef | null; // the Inbox email it was recorded from
  tags: string[];
  notes: string | null;
}

export interface TxnPage {
  items: Txn[];
  total: number;
  sum_in: number;
  sum_out: number;
}

export interface CategorySpend {
  id: number | null; // null = uncategorised
  name: string;
  icon: string;
  color: string;
  amount: number;
}

export interface Overview {
  month: string;
  net_worth: number;
  income: number;
  spending: number;
  accounts: Account[];
  by_category: CategorySpend[];
  recent: Txn[];
  transaction_count: number;
  budgets: Budget[]; // the month's active budgets with an amount or spending
  upcoming_bills: BillDue[]; // overdue + due in the next 30 days (current month only)
  emergency: EmergencySummary | null; // once the emergency fund is set up
}

// ---------- bills (F7)

export type BillRepeat = 'weekly' | 'monthly' | 'quarterly' | 'half_yearly' | 'yearly';
export type BillStatus = 'paid' | 'due_soon' | 'overdue' | 'upcoming' | 'inactive';

export interface Bill {
  id: number;
  name: string;
  amount_min: number;
  amount_max: number;
  first_due: string;
  repeat: BillRepeat;
  skip: number;
  match: string | null;
  active: boolean;
  notes: string | null;
  next_due: string | null;
  status: BillStatus;
  last_paid_date: string | null;
  last_paid_amount: number | null;
  monthly_cost: number;
  transaction_count: number;
}

export interface BillDue {
  bill_id: number;
  name: string;
  due: string;
  status: BillStatus;
  expected: number;
}

// ---------- piggy banks (F8)

export interface Piggy {
  id: number;
  name: string;
  account: AccountRef;
  target_amount: number;
  target_date: string | null;
  active: boolean;
  notes: string | null;
  saved: number;
  account_balance: number;
  account_available: number; // the account's balance not yet set aside in any piggy bank
  monthly_needed: number | null;
  is_emergency: boolean; // the emergency fund's piggy bank (target set automatically)
}

export interface PiggyEvent {
  id: number;
  date: string;
  amount: number; // + set aside, - taken out
  note: string | null;
}

// ---------- emergency fund

export type EmergencyStatus = 'not_set_up' | 'no_data' | 'low' | 'building' | 'safe' | 'done';

export interface EmergencyMonth {
  month: string; // YYYY-MM
  amount: number;
}

export interface EmergencyEstimate {
  average_months: number;
  monthly: number;
  source: 'median' | 'estimate' | 'none';
  months_of_data: number;
}

export interface Emergency {
  configured: boolean;
  piggy: Piggy | null;
  months_cover: number;
  average_months: number;
  monthly_override: number | null;
  monthly_essential: number; // the typical month used for the target
  monthly_source: 'median' | 'estimate' | 'override' | 'none';
  months_of_data: number;
  history: EmergencyMonth[]; // oldest first
  essential_categories: string[];
  estimates: EmergencyEstimate[]; // typical month for each averaging window (3, 6, 12) — for live previews
  target: number;
  saved: number;
  covered_months: number | null;
  status: EmergencyStatus;
  monthly_to_save: number | null;
}

export interface EmergencySummary {
  target: number;
  saved: number;
  months_cover: number;
  covered_months: number | null;
  status: EmergencyStatus;
}

// ---------- Gmail import + Inbox

export interface GmailRef {
  id: string;
  subject: string | null;
  from_addr: string | null;
}

export interface GmailStatus {
  client_configured: boolean;
  client_id_hint: string | null;
  connected: boolean;
  email: string | null;
  connected_at: string | null;
  last_fetch_to: string | null;
  consent_threshold_mb: number;
}

export interface GmailProvider {
  id: string;
  provider_id: string;
  name: string;
  doc_type: string; // readable kind
  kind: 'bank_statement' | 'credit_card_statement' | 'loan_statement' | 'mf_statement' | 'transaction_alert';
}

export interface GmailRun {
  id: number;
  status: 'estimated' | 'running' | 'cancelling' | 'done' | 'cancelled' | 'error';
  date_from: string;
  date_to: string;
  queries: { label: string; provider_id: string | null; doc_type: string | null; query: string }[];
  matched_count: number;
  new_count: number;
  bytes_estimated: number;
  bytes_human: string;
  consent_required: boolean;
  message_count: number;
  attachment_count: number;
  bytes_downloaded: number;
  progress: string | null;
  error: string | null;
}

export interface GmailConnectOut {
  url: string;
  redirect_uri: string;
  direct: boolean;
}

export interface InboxAttachment {
  id: number;
  filename: string;
  mime_type: string | null;
  size: number;
}

export interface InboxItem {
  id: string;
  from_addr: string | null;
  subject: string | null;
  sent_at: string | null;
  snippet: string | null;
  provider_id: string | null;
  doc_type: string | null;
  status: 'new' | 'handled' | 'ignored';
  attachments: InboxAttachment[];
  transaction_count: number;
  is_alert: boolean; // a transaction alert MoneyMap could read
}

export interface AlertSuggestion {
  type: 'withdrawal' | 'deposit';
  amount: number;
  date: string;
  merchant: string | null;
  account_last4: string | null;
  account_id: number | null;
}

export interface InboxDetail extends InboxItem {
  body_text: string | null;
  matched_query: string | null;
  transactions: Txn[];
  suggestion: AlertSuggestion | null;
}

export interface InboxPage {
  items: InboxItem[];
  total: number;
  counts: Record<'new' | 'handled' | 'ignored', number>;
}

// ---------- statement import

export type StatementRowStatus = 'ready' | 'needs_category' | 'needs_account' | 'duplicate' | 'skipped' | 'imported';

export interface StatementRow {
  id: number;
  idx: number;
  date: string;
  amount: number; // signed paise: − out of the account, + in
  description: string;
  raw: string;
  counterparty: string | null;
  balance: number | null;
  include: boolean;
  kind: 'expense' | 'income' | 'transfer';
  payee: string;
  category_id: number | null;
  budget_id: number | null;
  transfer_account_id: number | null;
  leave_uncategorised: boolean;
  user_set: boolean;
  suggestion: string | null;
  suggestion_kind: 'history' | null;
  duplicate_of: number | null;
  duplicate: Txn | null;
  transaction_id: number | null;
  status: StatementRowStatus;
}

export interface StatementSummary {
  id: number;
  filename: string;
  doc_type: 'bank_statement' | 'card_statement';
  account_last4: string | null;
  account_id: number | null;
  gmail_message_id: string | null;
  upload_path: string | null;
  status: 'draft' | 'imported';
  imported_count: number;
  created_at: string;
  imported_at: string | null;
  row_count: number;
  counts: Record<StatementRowStatus, number>;
}

export interface StatementDetail extends StatementSummary {
  unparsed: string[];
  rows: StatementRow[];
  account_suggested: boolean;
  overlaps: StatementOverlap[];
  opened_existing: boolean;
}

/** Another import with the same transactions (e.g. the same statement from Gmail and uploaded). */
export interface StatementOverlap {
  id: number;
  filename: string;
  source: 'email' | 'upload';
  status: 'draft' | 'imported';
  shared_rows: number;
}
