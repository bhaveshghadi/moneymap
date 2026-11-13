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
}

export interface PiggyEvent {
  id: number;
  date: string;
  amount: number; // + set aside, - taken out
  note: string | null;
}
