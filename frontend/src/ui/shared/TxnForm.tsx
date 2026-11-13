'use client';
import { useState, type FormEvent } from 'react';
import type { Account, Bill, BudgetMonth, Category, Tag, Txn, TxnType } from '../lib/types';
import { api } from '../lib/api';
import { paiseToInput, toPaise, todayIso } from '../lib/format';
import { useApi, useShell } from '../contexts/ShellCtx';
import { Dialog, useDialogClose } from '../primitives/Dialog';
import { Button } from '../primitives/Button';
import { SegmentedControl } from '../primitives/SegmentedControl';
import { Icon } from '../primitives/Icon';
import { DrawerHead } from './DrawerHead';
import { CategoryOptions, kindFor } from './CategoryOptions';

export interface TxnDefaults {
  type?: TxnType;
  date?: string;
  amount?: number; // paise
  description?: string;
  source_id?: number;
  destination_id?: number;
  source_name?: string;
  destination_name?: string;
  category_id?: number;
  budget_id?: number;
  bill_id?: number;
  notes?: string;
  /** Inbox: the email this transaction is recorded from. */
  gmail_message_id?: string;
  gmail_subject?: string;
}

const TYPE_OPTIONS = [
  { value: 'withdrawal', label: 'Expense' },
  { value: 'deposit', label: 'Income' },
  { value: 'transfer', label: 'Transfer' },
];

function initial(txn?: Txn, d: TxnDefaults = {}) {
  if (txn) {
    return {
      type: txn.type,
      date: txn.date,
      amount: paiseToInput(txn.amount),
      description: txn.description,
      sourceId: txn.type !== 'deposit' ? String(txn.source.id) : '',
      destId: txn.type !== 'withdrawal' ? String(txn.destination.id) : '',
      sourceName: txn.type === 'deposit' ? txn.source.name : '',
      destName: txn.type === 'withdrawal' ? txn.destination.name : '',
      categoryId: txn.category ? String(txn.category.id) : '',
      budgetId: txn.budget ? String(txn.budget.id) : '',
      billId: txn.bill ? String(txn.bill.id) : 'none',
      tags: txn.tags.join(', '),
      notes: txn.notes ?? '',
      gmailId: txn.gmail?.id ?? '',
      gmailSubject: txn.gmail?.subject ?? '',
    };
  }
  return {
    type: d.type ?? ('withdrawal' as TxnType),
    date: d.date ?? todayIso(),
    amount: d.amount != null ? paiseToInput(d.amount) : '',
    description: d.description ?? '',
    sourceId: d.source_id ? String(d.source_id) : '',
    destId: d.destination_id ? String(d.destination_id) : '',
    sourceName: d.source_name ?? '',
    destName: d.destination_name ?? '',
    categoryId: d.category_id ? String(d.category_id) : '',
    budgetId: d.budget_id ? String(d.budget_id) : '',
    // 'auto' = let the server match a bill; 'none' = not a bill; otherwise a bill id
    billId: d.bill_id ? String(d.bill_id) : 'auto',
    tags: '',
    notes: d.notes ?? '',
    gmailId: d.gmail_message_id ?? '',
    gmailSubject: d.gmail_subject ?? '',
  };
}

export function TxnForm({ txn, defaults, onClose }: { txn?: Txn; defaults?: TxnDefaults; onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label={txn ? 'Edit transaction' : 'Add transaction'} width={520}>
      <TxnFormBody txn={txn} defaults={defaults} />
    </Dialog>
  );
}

function TxnFormBody({ txn, defaults }: { txn?: Txn; defaults?: TxnDefaults }) {
  const close = useDialogClose();
  const { bump } = useShell();
  const [f, setF] = useState(() => initial(txn, defaults));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const accounts = useApi<Account[]>('/accounts?type=asset&type=cash&include_inactive=false');
  const counterparties = useApi<Account[]>('/accounts?type=expense&type=revenue');
  const categories = useApi<Category[]>('/categories');
  const tags = useApi<Tag[]>('/tags');
  const budgets = useApi<BudgetMonth>(`/budgets?month=${f.date.slice(0, 7)}`);
  const bills = useApi<Bill[]>('/bills');

  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((p) => ({ ...p, [k]: v }));
  // Inactive accounts are hidden, except the one this transaction already uses.
  const own = accounts.data ?? [];
  const keepOwn = txn ? [txn.source, txn.destination].filter((a) => ['asset', 'cash'].includes(a.type) && !own.some((o) => o.id === a.id)) : [];
  const ownOptions = [...own, ...keepOwn];
  const expenseNames = (counterparties.data ?? []).filter((a) => a.type === 'expense').map((a) => a.name);
  const revenueNames = (counterparties.data ?? []).filter((a) => a.type === 'revenue').map((a) => a.name);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const amount = toPaise(f.amount);
    if (amount === null || amount <= 0) return setError('Enter an amount greater than zero, e.g. 1250 or 1250.50');
    const body: Record<string, unknown> = {
      type: f.type,
      date: f.date,
      amount,
      description: f.description,
      category_id: f.type !== 'transfer' && f.categoryId ? Number(f.categoryId) : null,
      budget_id: f.type === 'withdrawal' && f.budgetId ? Number(f.budgetId) : null,
      bill_id: f.type === 'withdrawal' && !['auto', 'none'].includes(f.billId) ? Number(f.billId) : null,
      auto_match_bill: f.billId === 'auto',
      tags: f.tags.split(',').map((s) => s.trim()).filter(Boolean),
      notes: f.notes || null,
      gmail_message_id: f.gmailId || null,
    };
    if (f.type === 'withdrawal') {
      body.source_id = f.sourceId ? Number(f.sourceId) : null;
      body.destination_name = f.destName;
    } else if (f.type === 'deposit') {
      body.source_name = f.sourceName;
      body.destination_id = f.destId ? Number(f.destId) : null;
    } else {
      body.source_id = f.sourceId ? Number(f.sourceId) : null;
      body.destination_id = f.destId ? Number(f.destId) : null;
    }
    setSaving(true);
    try {
      if (txn) await api(`/transactions/${txn.id}`, { method: 'PUT', body });
      else await api('/transactions', { method: 'POST', body });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!txn) return;
    if (!confirmDelete) return setConfirmDelete(true);
    setSaving(true);
    try {
      await api(`/transactions/${txn.id}`, { method: 'DELETE' });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  const ownSelect = (value: string, onChange: (v: string) => void, label: string, id: string) => (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <select id={id} className="inp" value={value} onChange={(e) => onChange(e.target.value)} required>
        <option value="">Choose an account…</option>
        {ownOptions.map((a) => (
          <option key={a.id} value={a.id}>
            {a.name}
          </option>
        ))}
      </select>
      {accounts.data && own.length === 0 && <div className="hint">No accounts yet — add one on the Accounts page first.</div>}
    </div>
  );

  const nameInput = (value: string, onChange: (v: string) => void, label: string, id: string, options: string[], hint: string) => (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input id={id} className="inp" list={`${id}-list`} value={value} onChange={(e) => onChange(e.target.value)} required placeholder={hint} />
      <datalist id={`${id}-list`}>
        {options.map((n) => (
          <option key={n} value={n} />
        ))}
      </datalist>
      <div className="hint">Pick an existing one or type a new name — it&apos;s created automatically.</div>
    </div>
  );

  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead title={txn ? 'Edit transaction' : 'Add transaction'} sub="Amounts are in ₹" />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        {f.gmailId && (
          <div className="note info" style={{ marginBottom: 14 }}>
            <Icon name="mail" size={15} />
            <span style={{ flex: 1, minWidth: 0 }}>
              From email: <b>{f.gmailSubject || '(no subject)'}</b>
            </span>
            <button type="button" className="prov" onClick={() => setF((p) => ({ ...p, gmailId: '', gmailSubject: '' }))} title="Unlink the email">
              <Icon name="unlink" size={13} /> Unlink
            </button>
          </div>
        )}
        <div className="field">
          <SegmentedControl aria-label="Transaction type" value={f.type} onChange={(v) => set('type', v as TxnType)} options={TYPE_OPTIONS} />
        </div>
        <div className="field">
          <label htmlFor="tx-desc">Description</label>
          <input id="tx-desc" className="inp" value={f.description} onChange={(e) => set('description', e.target.value)} required maxLength={255} placeholder="e.g. Groceries at DMart" />
        </div>
        <div className="row2">
          <div className="field">
            <label htmlFor="tx-amt">Amount (₹)</label>
            <input id="tx-amt" className="inp" inputMode="decimal" value={f.amount} onChange={(e) => set('amount', e.target.value)} required placeholder="0.00" />
          </div>
          <div className="field">
            <label htmlFor="tx-date">Date</label>
            <input id="tx-date" type="date" className="inp" value={f.date} onChange={(e) => set('date', e.target.value)} required />
          </div>
        </div>

        {f.type === 'withdrawal' && (
          <>
            {ownSelect(f.sourceId, (v) => set('sourceId', v), 'Paid from', 'tx-src')}
            {nameInput(f.destName, (v) => set('destName', v), 'Paid to', 'tx-dst', expenseNames, 'Merchant or payee')}
          </>
        )}
        {f.type === 'deposit' && (
          <>
            {nameInput(f.sourceName, (v) => set('sourceName', v), 'Received from', 'tx-src', revenueNames, 'Employer, client, refund…')}
            {ownSelect(f.destId, (v) => set('destId', v), 'Into account', 'tx-dst')}
          </>
        )}
        {f.type === 'transfer' && (
          <div className="row2">
            {ownSelect(f.sourceId, (v) => set('sourceId', v), 'From account', 'tx-src')}
            {ownSelect(f.destId, (v) => set('destId', v), 'To account', 'tx-dst')}
          </div>
        )}

        {f.type !== 'transfer' && (
          <div className="field">
            <label htmlFor="tx-cat">Category</label>
            <select id="tx-cat" className="inp" value={f.categoryId} onChange={(e) => set('categoryId', e.target.value)}>
              <option value="">Uncategorised</option>
              <CategoryOptions categories={categories.data ?? []} kind={kindFor(f.type)} keep={f.categoryId} />
            </select>
          </div>
        )}
        {f.type === 'withdrawal' && (
          <div className="row2">
          <div className="field">
            <label htmlFor="tx-budget">Budget</label>
            <select id="tx-budget" className="inp" value={f.budgetId} onChange={(e) => set('budgetId', e.target.value)}>
              <option value="">No budget</option>
              {(budgets.data?.budgets ?? [])
                .filter((b) => b.active || String(b.id) === f.budgetId)
                .map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="tx-bill">Bill</label>
            <select id="tx-bill" className="inp" value={f.billId} onChange={(e) => set('billId', e.target.value)}>
              {!txn && <option value="auto">Match automatically</option>}
              <option value="none">Not a bill</option>
              {(bills.data ?? [])
                .filter((b) => b.active || String(b.id) === f.billId)
                .map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
            </select>
          </div>
          </div>
        )}
        <div className="field">
          <label htmlFor="tx-tags">Tags</label>
          <input id="tx-tags" className="inp" list="tx-tags-list" value={f.tags} onChange={(e) => set('tags', e.target.value)} placeholder="Comma-separated, e.g. trip, goa" />
          <datalist id="tx-tags-list">
            {(tags.data ?? []).map((t) => (
              <option key={t.id} value={f.tags.includes(',') ? f.tags.replace(/[^,]*$/, ' ' + t.name) : t.name} />
            ))}
          </datalist>
        </div>
        <div className="field">
          <label htmlFor="tx-notes">Notes</label>
          <textarea id="tx-notes" className="inp" value={f.notes} onChange={(e) => set('notes', e.target.value)} />
        </div>
      </div>
      <div className="drawer-foot">
        {txn && (
          <Button variant={confirmDelete ? 'primary' : 'ghost'} icon="trash-2" onClick={remove} disabled={saving} className={confirmDelete ? 'btn-danger' : ''}>
            {confirmDelete ? 'Confirm delete' : 'Delete'}
          </Button>
        )}
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>
          Cancel
        </Button>
        <Button variant="primary" type="submit" disabled={saving}>
          {saving ? 'Saving…' : txn ? 'Save changes' : 'Add transaction'}
        </Button>
      </div>
    </form>
  );
}
