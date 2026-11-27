// Mirrors the backend schemas (backend/app/modules/*/schemas.py). All amounts are integer paise.

export interface AuthStatus {
  setup_required: boolean;
  authenticated: boolean;
  username: string | null;
}

// Credit cards and loans come later as their own features.
export type AccountType = 'asset' | 'cash' | 'credit_card' | 'emi_plan' | 'loan' | 'investment' | 'expense' | 'revenue';
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
  category_ids: number[]; // expenses in these categories count here by themselves
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
  loans_owed: number; // what's left on active loans (already taken off net_worth)
  loan_dues: LoanDue[]; // next loan EMIs, overdue or in the next 30 days
  investments_value: number; // active investments, value today (already added to net_worth)
  investments_invested: number;
  investments_count: number;
  investment_dues: InvestmentDue[]; // maturities, premiums, money due back, chit instalments (current month)
  card_dues: CardDue[]; // card statements overdue or due in the next 30 days (current month only)
  emergency: EmergencySummary | null; // once the emergency fund is set up
}

// ---------- loans (F14)

export type LoanMethod = 'reducing' | 'flat' | 'emi_only';
export type LoanFirstInterest = 'month' | 'days365' | 'days360';
export type LoanCountMode = 'whole_emi' | 'interest_only';
export type LoanKind = 'home' | 'car' | 'two_wheeler' | 'personal' | 'education' | 'gold' | 'property' | 'consumer' | 'other';

export interface LoanRow {
  n: number;
  date: string;
  emi: number;
  principal: number;
  interest: number;
  balance: number;
  paid: boolean;
}

export type LoanInterestBasis = 'month' | 'days365';

export interface Loan {
  id: number; // the loan's account id
  loan_id: number;
  name: string;
  lender: string | null;
  kind: LoanKind;
  loan_number: string | null;
  method: LoanMethod;
  count_mode: LoanCountMode;
  principal: number | null;
  rate: number | null;
  current_rate: number | null; // after rate changes
  rate_worked_out: boolean;
  tenure: number;
  emi: number;
  current_emi: number; // after part-payments / rate changes
  first_emi_date: string;
  disbursed_date: string | null;
  first_interest: LoanFirstInterest; // EMI 1: a month's interest, or the days since disbursed_date
  interest_basis: LoanInterestBasis; // each month's interest: rate/12, or the actual days / 365
  first_interest_days: number | null; // days counted in EMI 1
  last_emi_off: boolean; // the last EMI is > 2% away from the EMI (reducing, no changes)
  first_interest_suggestion: LoanFirstInterest | null; // the first-EMI interest that makes it fit
  end_date: string;
  pay_from_id: number | null;
  pay_from_name: string | null;
  paid_before: number;
  paid_count: number;
  prepaid: number;
  outstanding: number;
  total_interest: number;
  total_payable: number;
  interest_paid: number;
  next: { n: number; date: string; emi: number; principal: number; interest: number; overdue: boolean } | null;
  status: 'active' | 'closed';
  closed_on: string | null;
  notes: string | null;
  supports_changes: boolean; // part-payments / rate changes (reducing balance)
  events: LoanEvent[];
}

export interface LoanEvent {
  id: number;
  kind: 'prepay' | 'rate';
  date: string;
  /** close: the loan paid off early (a prepay that clears what was left) */
  mode: 'reduce_tenure' | 'reduce_emi' | 'close';
  amount: number | null;
  rate: number | null;
  before_n: number | null;
  emi_after: number | null;
  txn_id: number | null;
}

export interface LoanDetail extends Loan {
  schedule: LoanRow[];
}

export interface LoanLinkable {
  transaction_id: number;
  date: string;
  amount: number;
  description: string;
  paid_from: string;
  category: string | null;
  emi_like: boolean;
  suggested: boolean;
}

export interface LoanDue {
  loan_id: number;
  name: string;
  date: string;
  amount: number;
  n: number;
  tenure: number;
  overdue: boolean;
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
  loan_emis: number; // EMIs of active loans, included in the typical month
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
  client_from_env: boolean; // MONEYMAP_GOOGLE_CLIENT_JSON on the server: nothing to paste here
  client_env_error: string | null;
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
  found: GmailFound[]; // every email found, to pick what to fetch
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
  category_id: number | null; // from your rules
  payee: string | null; // the merchant, renamed by a rule
  rule: string | null; // the rule(s) that matched
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
  suggestion_kind: 'history' | 'rule' | 'card' | 'link' | 'emi' | 'loan' | 'investment' | null;
  create_rule?: boolean; // "rule for next time", made on import
  rule_keyword?: string | null;
  duplicate_of: number | null;
  duplicate: Txn | null;
  link_txn_id: number | null; // card payment: this bank-side expense becomes the transfer on import
  link: Txn | null;
  flag: 'emi' | null;
  emi_id: number | null;
  loan_id: number | null; // bank statement: a loan's EMI / part-payment (recorded on import)
  loan_action: 'emi' | 'prepay' | null;
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

// ---------- investments (F15)

export type InvestmentKind =
  | 'mf' | 'fd' | 'rd' | 'post_office' | 'retirement' | 'insurance' | 'lent'
  | 'chit' | 'gold' | 'stocks' | 'crypto' | 'property' | 'other';
export type Compounding = 'monthly' | 'quarterly' | 'half_yearly' | 'yearly' | 'payout' | 'simple';
export type PremiumFrequency = 'monthly' | 'quarterly' | 'half_yearly' | 'yearly' | 'single';

export interface InvestmentDue {
  account_id: number;
  name: string;
  kind: InvestmentKind;
  date: string;
  what: 'matures' | 'premium' | 'due_back' | 'instalment' | 'balance';
  amount: number;
  overdue: boolean;
}

export interface Investment {
  id: number; // account id
  name: string;
  kind: InvestmentKind;
  subtype: string | null;
  institution: string | null;
  number: string | null;
  person: string | null;
  rate: number | null;
  compounding: Compounding | null;
  start_date: string | null;
  maturity_date: string | null;
  months: number | null;
  instalment: number | null;
  frequency: PremiumFrequency | null;
  sum_assured: number | null;
  maturity_amount: number | null;
  quantity: number | null;
  purity: string | null;
  unit_price: number | null;
  current_value: number | null;
  payout_on: string | null;
  payout_amount: number | null;
  pay_from_id: number | null;
  opening: number; // amount already invested before tracking
  closed_on: string | null;
  notes: string | null;
  status: 'active' | 'closed';
  money_in: number;
  money_out: number;
  invested: number;
  value: number;
  gain: number;
  gain_pct: number | null;
  value_date: string | null;
  maturity_value: number | null;
  paid_count: number | null;
  total_count: number | null;
  owed: number;
  stale: boolean;
  no_price: boolean;
  next_due: InvestmentDue | null;
  fund: FundInfo | null; // mutual funds
  property: PropertyPurchase | null; // property bought in parts
}

export interface FundInfo {
  scheme: string;
  amc: string | null;
  isin: string | null;
  folio: string | null;
  units: number;
  units_as_of: string | null;
  nav: number | null; // rupees
  nav_date: string | null;
  nav_source: 'cas' | 'amfi' | 'hand' | null;
  cost: number | null;
}

export interface FundTxn {
  id: number;
  date: string;
  kind: string;
  kind_label: string;
  description: string;
  amount: number;
  units: number;
  nav: number;
  stamp_duty: number;
  transaction_id: number | null;
}

export interface Scheme {
  code: string;
  isin: string | null;
  name: string;
  amc: string | null;
  nav: number | null; // 1/10000 rupee
  nav_date: string | null;
}

export interface NavStatus {
  last_run: string | null;
  updated: number;
  funds: number;
  error: string | null;
  not_found: string[];
}

export type CasAction = 'link' | 'convert' | 'transfer' | 'switch' | 'before' | 'units' | 'skip';

export type CasImportMode = 'both' | 'fund' | 'txns';

export interface CasFund {
  id: number;
  amc: string | null;
  folio: string | null;
  scheme: string;
  isin: string | null;
  opening_units: number; // milli-units
  closing_units: number | null;
  nav: number | null; // 1/10000 rupee
  nav_date: string | null;
  cost: number | null;
  market_value: number | null;
  account_id: number | null;
  account_name: string | null;
  skip: boolean;
  mode: CasImportMode; // both | fund (today's holding, no history) | txns (rows into a fund you have)
  rows: number;
  already_imported: number; // rows imported from an earlier CAS (skipped)
  replaces_opening: number | null; // joins a fund added by hand: its "already invested", replaced on import
  units_now: number | null; // the fund it joins: units recorded now
}

export interface CasRow {
  id: number;
  fund_id: number;
  date: string;
  description: string;
  kind: string;
  kind_label: string;
  amount: number;
  units: number;
  nav: number;
  balance: number;
  stamp_duty: number;
  action: CasAction;
  match: Txn | null;
  bank_account_id: number | null;
  pair_row_id: number | null;
  existing: boolean;
  user_set: boolean;
  transaction_id: number | null;
}

export interface CasDetail {
  id: number;
  filename: string;
  period_from: string | null;
  period_to: string | null;
  status: 'draft' | 'imported';
  created_at: string;
  imported_at: string | null;
  gmail_message_id: string | null;
  funds: CasFund[];
  rows: CasRow[];
  unparsed: string[];
  counts: Record<string, number>;
  /** A summary CAS: today's holdings only, no transactions (funds come in as "fund only"). */
  summary: boolean;
}

export interface CasSummary {
  id: number;
  filename: string;
  period_from: string | null;
  period_to: string | null;
  status: 'draft' | 'imported';
  created_at: string;
  funds: number;
  rows: number;
}

export interface InvestmentDetail extends Investment {
  moves: Txn[];
  fund_txns: FundTxn[];
}

export interface MetalRates {
  gold_24k: number | null; // paise per gram
  silver: number | null;
  date: string | null;
}

export interface InvestmentSummary {
  invested: number;
  value: number;
  gain: number;
  owed: number;
  count: number;
  by_kind: { kind: InvestmentKind; count: number; invested: number; value: number }[];
  dues: InvestmentDue[];
  rates: MetalRates;
}

export interface InvestmentLinkable {
  transaction_id: number;
  date: string;
  amount: number;
  direction: 'in' | 'out'; // in = from your bank into the investment
  description: string;
  account: string;
  counterparty: string;
  category: string | null;
  suggested: boolean;
  why: string | null;
}

// ---------- rules (F10)

export type RuleConditionType =
  | 'description_contains' | 'description_starts' | 'description_is' | 'payee_contains'
  | 'amount_is' | 'amount_more' | 'amount_less' | 'type_is' | 'account_is' | 'no_category' | 'has_tag';
export type RuleActionType =
  | 'set_category' | 'set_budget' | 'set_bill' | 'add_tag' | 'remove_tag' | 'set_payee' | 'set_description' | 'add_note';

export interface RuleItem<T extends string = string> {
  type: T;
  value?: string | number | null;
}

export interface Rule {
  id: number;
  title: string;
  position: number;
  active: boolean;
  match_all: boolean;
  stop: boolean;
  conditions: RuleItem<RuleConditionType>[];
  actions: RuleItem<RuleActionType>[];
}

export interface RuleTestResult {
  matched: number;
  would_change: number;
  items: { transaction: Txn; changes: string[] }[];
}

export interface RuleSuggestion {
  payee: string;
  type: 'withdrawal' | 'deposit';
  category_id: number;
  category: string;
  count: number;
  total: number;
}

// ---------- loan statements (F14 phase 3)

export interface LoanStatementField {
  value: string | number | null;
  source: 'statement' | 'worked_out';
}

export interface LoanStatementEvent {
  kind: 'prepay' | 'rate';
  date: string;
  amount: number | null;
  rate: number | null;
  mode: 'reduce_tenure' | 'reduce_emi';
  source: 'statement' | 'schedule';
  text: string | null;
  already_recorded: boolean;
  transaction_id: number | null;
  transaction: string | null;
  date_unknown: boolean;
}

export interface LoanStatementDiff {
  field: string;
  label: string;
  kind: 'money' | 'date' | 'rate' | 'count' | 'text' | 'kind' | 'first_interest' | 'method' | 'interest_basis';
  current: string | number | null; // money in paise, dates ISO
  statement: string | number | null;
  patch: Record<string, unknown> | null;
  note: string | null;
}

export interface LoanStatementResult {
  filename: string;
  file_ref: string | null;
  attachment_id: number | null;
  fields: Partial<Record<
    | 'loan_number' | 'lender' | 'kind' | 'method' | 'principal' | 'rate' | 'rate_now' | 'tenure' | 'emi'
    | 'first_emi_date' | 'disbursed_date' | 'first_interest' | 'interest_basis' | 'last_emi_date' | 'outstanding' | 'emis_paid'
    | 'emis_left' | 'statement_date',
    LoanStatementField
  >>;
  schedule_rows: number;
  check: { rows: number; max_diff: number; matches: boolean } | null;
  events: LoanStatementEvent[];
  match: { account_id: number; name: string; differences: LoanStatementDiff[] } | null;
}

// ---------------------------------------------------------------- savings plan (F18)

export type SavingsRule = '50_30_20' | '60_20_20' | '70_20_10' | '80_20' | 'custom';
export type SavingsBasis = 'actual' | 'avg3' | 'fixed';

export interface SavingsSettings {
  rule: SavingsRule;
  needs: number | null; // % (null with 80/20: needs and wants share one "spending" target)
  wants: number | null;
  savings: number;
  basis: SavingsBasis;
  fixed_income: number | null; // paise a month
}

export interface SavingsShare {
  amount: number;
  pct: number | null;
  target_pct: number | null;
  target: number | null;
  diff: number | null; // amount − target
}

export interface SavingsLine {
  category_id: number | null;
  name: string;
  icon: string;
  color: string;
  amount: number;
  before: number | null;
}

export interface SavingsSuggestion {
  kind: string;
  tone: 'warn' | 'info' | 'good';
  title: string;
  detail: string;
  amount: number | null;
  items: SavingsLine[];
}

export interface SavingsPlan {
  settings: SavingsSettings;
  period: string;
  period_label: string;
  months: number;
  period_start: string;
  period_end: string;
  income: number;
  income_used: number;
  needs: SavingsShare;
  wants: SavingsShare;
  spending: SavingsShare;
  savings: SavingsShare;
  savings_split: { to_investments: number; to_goals: number; left_in_bank: number };
  needs_lines: SavingsLine[];
  wants_lines: SavingsLine[];
  uncategorised: number;
  emi_monthly: number;
  suggestions: SavingsSuggestion[];
}

export interface BudgetProposal {
  category_id: number;
  name: string;
  icon: string;
  color: string;
  average: number;
  amount: number;
  budget_name: string | null;
}

export interface BudgetProposals {
  wants_target: number;
  total_average: number;
  items: BudgetProposal[];
  taken: BudgetProposal[];
}

// ---------------------------------------------------------------- start-up guide (F20)

export interface GuideStep {
  key: string;
  title: string;
  why: string;
  href: string;
  optional: boolean;
  manual: boolean;
  detail: string;
  done: boolean;
  skipped: boolean;
}

export interface Guide {
  steps: GuideStep[];
  done: number;
  total: number;
  hidden: boolean;
  finished: boolean;
  show_first: boolean;
  setup_page: boolean; // a new install: show the setup page first
}

// ---------------------------------------------------------------- property bought in parts

export type PropertyStatus = 'booked' | 'agreement' | 'registration_pending' | 'registered';
export type PropertyCostKind = 'stamp_duty' | 'registration' | 'legal' | 'broker' | 'other';

export interface PropertyInstalment {
  id: number;
  due_date: string;
  amount: number;
  note: string | null;
  paid: number;
  status: 'paid' | 'part' | 'due' | 'overdue';
}

export interface PropertyCost {
  id: number;
  kind: PropertyCostKind;
  amount: number;
  date: string;
  note: string | null;
  transaction_id: number | null;
}

export interface PropertyPurchase {
  price: number | null;
  size: string | null;
  location: string | null;
  survey_no: string | null;
  seller: string | null;
  agreement_date: string | null;
  status: PropertyStatus;
  registered_on: string | null;
  price_paid: number;
  balance: number | null;
  costs_total: number;
  total_cost: number;
  plan: PropertyInstalment[];
  unplanned: number | null;
  costs: PropertyCost[];
  goal_id: number | null;
  goal_saved: number | null;
}

export interface GmailFound {
  id: string;
  q: number; // index into the run's queries
  from: string | null;
  subject: string | null;
  date: string | null; // ISO, minutes
  size: number; // bytes
  known: boolean; // already in the Inbox
  last4: string | null; // account / card digits in the subject or preview
  account: string | null; // your account or card with those digits
}
