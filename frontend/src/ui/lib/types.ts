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
}
