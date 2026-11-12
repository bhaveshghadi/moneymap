// Formatting helpers (₹ with Indian grouping, dates, paise helpers).
import type { AccountType, Txn } from './types';

export const inr = (n: number): string => '₹' + Math.abs(Math.round(n)).toLocaleString('en-IN');

export const inr2 = (n: number): string =>
  '₹' + Math.abs(n).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Compact Indian notation for headline stats: ₹1.53 Cr / ₹14.75 L. */
export const inrCompact = (n: number): string => {
  const abs = Math.abs(Math.round(n));
  const scaled = (v: number, unit: string): string => {
    const s = (Math.round(v * 100) / 100).toFixed(2).replace(/\.?0+$/, '');
    return `₹${s} ${unit}`;
  };
  if (abs >= 1_00_00_000) return scaled(abs / 1_00_00_000, 'Cr');
  if (abs >= 1_00_000) return scaled(abs / 1_00_000, 'L');
  return inr(abs);
};

/** Paise (API) -> rupees (Money component). */
export const rs = (paise: number): number => paise / 100;

/** User-typed rupees ("1,234.50") -> integer paise, or null if not a number. */
export function toPaise(input: string): number | null {
  const clean = input.replace(/[₹,\s]/g, '');
  if (!/^-?\d+(\.\d{0,2})?$/.test(clean)) return null;
  return Math.round(parseFloat(clean) * 100);
}

/** Paise -> plain editable rupee string ("1234.5"). */
export const paiseToInput = (paise: number): string => (paise / 100).toString();

/** Format an ISO date ("2026-04-12") as "12 Apr 2026". */
export function fmtDate(iso: string): string {
  const d = new Date(iso + 'T00:00:00');
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
}

export function fmtDayHead(iso: string): string {
  const d = new Date(iso + 'T00:00:00');
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('en-IN', { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' });
}

export function todayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** 'YYYY-MM' helpers for the month switcher. */
export function currentMonth(): string {
  return todayIso().slice(0, 7);
}
export function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split('-').map(Number);
  const d = new Date(y, m - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}
export function monthLabel(month: string): string {
  const [y, m] = month.split('-').map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString('en-IN', { month: 'long', year: 'numeric' });
}
export function monthRange(month: string): { from: string; to: string } {
  const [y, m] = month.split('-').map(Number);
  const last = new Date(y, m, 0).getDate();
  return { from: `${month}-01`, to: `${month}-${String(last).padStart(2, '0')}` };
}

export const ACCOUNT_TYPE_LABEL: Record<AccountType, string> = {
  asset: 'Bank account',
  cash: 'Cash',
  expense: 'Expense account',
  revenue: 'Revenue account',
};

export const ACCOUNT_TYPE_ICON: Record<AccountType, { icon: string; color: string }> = {
  asset: { icon: 'landmark', color: 'indigo' },
  cash: { icon: 'banknote', color: 'mint' },
  expense: { icon: 'shopping-cart', color: 'slate' },
  revenue: { icon: 'briefcase', color: 'mint' },
};

/** The "other side" of a transaction, as shown in list rows. */
export function counterparty(t: Txn): string {
  if (t.type === 'withdrawal') return t.destination.name;
  if (t.type === 'deposit') return t.source.name;
  return `${t.source.name} → ${t.destination.name}`;
}

/** Which of your own accounts the transaction touched. */
export function ownAccount(t: Txn): string {
  if (t.type === 'withdrawal') return t.source.name;
  if (t.type === 'deposit') return t.destination.name;
  return '';
}

export const REPEAT_LABEL: Record<string, string> = {
  daily: 'Daily',
  weekly: 'Weekly',
  monthly: 'Monthly',
  quarterly: 'Quarterly',
  half_yearly: 'Every 6 months',
  yearly: 'Yearly',
};

export function repeatText(repeat: string, skip: number): string {
  if (!skip) return REPEAT_LABEL[repeat] ?? repeat;
  const unit = { daily: 'days', weekly: 'weeks', monthly: 'months', quarterly: 'quarters', half_yearly: 'half-years', yearly: 'years' }[repeat] ?? repeat;
  return `Every ${skip + 1} ${unit}`;
}

/** Days from today to an ISO date (negative = past). */
export function daysUntil(iso: string): number {
  const d = new Date(iso + 'T00:00:00');
  const t = new Date(todayIso() + 'T00:00:00');
  return Math.round((d.getTime() - t.getTime()) / 86400000);
}

export function dueText(iso: string): string {
  const n = daysUntil(iso);
  if (n === 0) return 'Due today';
  if (n === 1) return 'Due tomorrow';
  if (n > 1) return `Due in ${n} days`;
  if (n === -1) return '1 day overdue';
  return `${-n} days overdue`;
}

/** Timestamps the database fills in itself (created_at, imported_at) are UTC
 * without a zone marker; read them as UTC so dates show in local time. */
export function fromUtc(ts: string): Date {
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(ts) ? ts : ts.replace(' ', 'T') + 'Z');
}

/** Mutual fund units are stored ×1000 (3 decimals). */
export const fmtUnits = (milli: number): string =>
  (milli / 1000).toLocaleString('en-IN', { minimumFractionDigits: 3, maximumFractionDigits: 3 });

/** NAVs are stored ×10000 (4 decimals). */
export const fmtNav = (e4: number): string =>
  '₹' + (e4 / 10000).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 4 });
