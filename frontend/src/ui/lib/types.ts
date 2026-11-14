// Mirrors the backend schemas (backend/app/modules/*/schemas.py). All amounts are integer paise.

export interface AuthStatus {
  setup_required: boolean;
  authenticated: boolean;
  username: string | null;
}

// Credit cards and loans come later as their own features.
export type AccountType = 'asset' | 'cash' | 'credit_card' | 'emi_plan' | 'expense' | 'revenue';
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
  cards_owed: number; // outstanding on active credit cards (already taken off net_worth)
  card_dues: CardDue[]; // card statements overdue or due in the next 30 days (current month only)
  emergency: EmergencySummary | null; // once the emergency fund is set up
}

// ---------- credit cards (F17)

export type DueMode = 'days_after' | 'fixed_day';
export type CycleStatus = 'unbilled' | 'nothing_due' | 'billed' | 'partly_paid' | 'paid' | 'overdue';

export interface CardCycle {
  start: string;
  statement_date: string;
  due_date: string;
  spent: number;
  credits: number;
  total_due: number;
  min_due: number;
  paid: number;
  paid_on: string | null;
  status: CycleStatus;
  min_paid: boolean;
  official: boolean; // figures from the imported statement
}

export interface Card {
  id: number; // the card's account id
  name: string;
  bank: string | null;
  last4: string | null;
  network: string | null;
  color: string;
  credit_limit: number;
  min_due_pct: number;
  statement_day: number;
  due_mode: DueMode;
  due_value: number;
  opening_owed: number;
  opening_date: string | null;
  active: boolean;
  notes: string | null;
  owed: number;
  emi_outstanding: number; // EMI principal still to pay (not on a bill yet)
  emi_count: number;
  available: number | null; // limit − owed − EMIs
  utilisation: number | null;
  current: CardCycle;
  last_statement: CardCycle | null;
  due_now: number;
  next_due_date: string | null;
  due_status: CycleStatus | null;
  best_swipe_day: string;
  interest_free_days: number;
  transaction_count: number;
}

export interface CardDetail extends Card {
  cycles: CardCycle[]; // newest first
  emis: Emi[];
}

export interface Emi {
  id: number;
  card_id: number;
  account_id: number;
  name: string;
  kind: 'converted' | 'checkout' | 'existing';
  principal: number;
  tenure: number;
  instalment: number | null;
  interest_rate: number | null;
  processing_fee: number | null;
  no_cost: boolean;
  start_date: string;
  finish_date: string;
  paid_count: number;
  outstanding: number;
  principal_paid: number;
  interest_paid: number;
  next_date: string | null;
  status: 'active' | 'closed';
  closed_on: string | null;
  purchase_txn_id: number | null;
  notes: string | null;
}

export interface CardDue {
  card_id: number;
  name: string;
  last4: string | null;
  due_date: string;
  amount: number;
  min_due: number;
  status: CycleStatus;
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

export interface EmergencyCategory {
  category_id: number;
  name: string;
  icon: string;
  color: string;
  total: number; // over the months used
  per_month: number;
  share: number; // % of essential spending in those months
}

export interface EmergencyOneOff {
  transaction_id: number;
  date: string;
  description: string;
  category: string;
  amount: number;
  share: number; // % of its month's essential spending
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
  breakdown: EmergencyCategory[]; // biggest first, over the months in history
  one_offs: EmergencyOneOff[]; // single big payments that skew their month, biggest first
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

export type StatementRowStatus = 'ready' | 'link' | 'needs_category' | 'needs_account' | 'duplicate' | 'skipped' | 'imported';

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
  suggestion_kind: 'history' | 'card' | 'link' | 'emi' | null;
  duplicate_of: number | null;
  duplicate: Txn | null;
  link_txn_id: number | null; // card payment: this bank-side expense becomes the transfer on import
  link: Txn | null;
  flag: 'emi' | null;
  emi_id: number | null;
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
  figures: CardFigures | null; // card statements only
  opened_existing: boolean;
}

/** A card statement's summary box and the add-up check (previous + purchases − credits = total due). */
export interface CardFigures {
  statement_date: string | null;
  period_start: string | null;
  due_date: string | null;
  total_due: number | null;
  min_due: number | null;
  previous_balance: number | null;
  debits: number;
  credits: number;
  expected_total: number | null;
  difference: number | null;
  adds_up: boolean | null;
  card_statement_day: number | null;
  card_due_mode: string | null;
  card_due_value: number | null;
  suggest_statement_day: number | null; // the card is set to another statement day than this statement's
  suggest_due_days: number | null; // ...or another gap between statement and due date
}

/** Another import with the same transactions (e.g. the same statement from Gmail and uploaded). */
export interface StatementOverlap {
  id: number;
  filename: string;
  source: 'email' | 'upload';
  status: 'draft' | 'imported';
  shared_rows: number;
}
