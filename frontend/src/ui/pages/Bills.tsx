'use client';
import { useState, type FormEvent } from 'react';
import Link from 'next/link';
import { api } from '../lib/api';
import { useApi, useShell } from '../contexts/ShellCtx';
import type { Bill, BillRepeat } from '../lib/types';
import { dueText, fmtDate, paiseToInput, repeatText, rs, toPaise, todayIso } from '../lib/format';
import { Button } from '../primitives/Button';
import { Money } from '../primitives/Money';
import { StatCard } from '../primitives/StatCard';
import { Skeleton } from '../primitives/Skeleton';
import { EmptyState } from '../primitives/EmptyState';
import { ErrorState } from '../primitives/ErrorState';
import { Icon } from '../primitives/Icon';
import { Dialog, useDialogClose } from '../primitives/Dialog';
import { DrawerHead } from '../shared/DrawerHead';
import { BillBadge } from '../shared/Progress';
import { PageHelp } from '../shared/PageHelp';

function AmountRange({ b }: { b: Pick<Bill, 'amount_min' | 'amount_max'> }) {
  if (b.amount_min === b.amount_max) return <Money amount={rs(b.amount_min)} interactive={false} />;
  return (
    <>
      <Money amount={rs(b.amount_min)} interactive={false} /> – <Money amount={rs(b.amount_max)} interactive={false} />
    </>
  );
}

export function BillsPage() {
  const { data, error, reload } = useApi<Bill[]>('/bills');
  const [editing, setEditing] = useState<{ bill?: Bill } | null>(null);
  const active = (data ?? []).filter((b) => b.active);
  const perMonth = active.reduce((s, b) => s + b.monthly_cost, 0);
  const overdue = active.filter((b) => b.status === 'overdue');
  const soon = active.filter((b) => b.status === 'due_soon');

  return (
    <div className="content-wrap fade-in">
      <div className="page-head">
        <div>
          <h1>Bills <PageHelp id="bills" /></h1>
          <p>Recurring bills you expect to pay. New expenses that match a bill are linked to it automatically.</p>
        </div>
        <div className="actions">
          <Button variant="primary" icon="plus" onClick={() => setEditing({})}>Add bill</Button>
        </div>
      </div>

      {error ? (
        <div className="card"><ErrorState message={error} onRetry={reload} /></div>
      ) : !data ? (
        <>
          <div className="grid-3 stat-grid"><Skeleton variant="stat" count={3} /></div>
          <Skeleton variant="block" height={260} />
        </>
      ) : data.length === 0 ? (
        <div className="card">
          <EmptyState
            icon="receipt-text"
            title="No bills yet"
            body="Add rent, electricity, phone, subscriptions, insurance premiums… MoneyMap shows what's due and checks them off when a matching expense comes in."
            action={{ label: 'Add bill', onClick: () => setEditing({}) }}
          />
        </div>
      ) : (
        <>
          <div className="grid-3 stat-grid">
            <StatCard lbl="Per month" icon="calendar-range" val={<Money amount={rs(perMonth)} compact />} sub={`${active.length} active bill${active.length === 1 ? '' : 's'}, averaged`} />
            <StatCard lbl="Due this week" icon="calendar-clock" val={String(soon.length)} sub={soon.length ? soon.map((b) => b.name).join(', ') : 'Nothing due in the next 7 days'} />
            <StatCard lbl="Overdue" icon="triangle-alert" val={String(overdue.length)} accent={overdue.length ? 'var(--red-600)' : undefined} sub={overdue.length ? overdue.map((b) => b.name).join(', ') : 'All caught up'} />
          </div>

          <div className="card">
            <div className="tbl-wrap" style={{ padding: '16px 6px 6px' }}>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Bill</th>
                    <th className="r hide-sm">Amount</th>
                    <th>Next due</th>
                    <th>Status</th>
                    <th className="r hide-sm">Last paid</th>
                  </tr>
                </thead>
                <tbody>
                  {data.map((b) => (
                    <tr key={b.id} className="click" onClick={() => setEditing({ bill: b })} style={{ opacity: b.active ? 1 : 0.55 }}>
                      <td>
                        <div style={{ fontWeight: 600 }}>{b.name}</div>
                        <div className="muted" style={{ fontSize: 12 }}>{repeatText(b.repeat, b.skip)}</div>
                        <div className="only-sm figure" style={{ fontSize: 12 }}><AmountRange b={b} /></div>
                      </td>
                      <td className="r figure hide-sm"><AmountRange b={b} /></td>
                      <td>
                        {b.next_due ? (
                          <>
                            <div>{fmtDate(b.next_due)}</div>
                            {b.active && <div className="muted" style={{ fontSize: 12 }}>{b.status === 'paid' ? 'Next cycle' : dueText(b.next_due)}</div>}
                          </>
                        ) : '—'}
                      </td>
                      <td><BillBadge status={b.status} /></td>
                      <td className="r hide-sm">
                        {b.last_paid_date ? (
                          <>
                            <div className="figure"><Money amount={rs(b.last_paid_amount ?? 0)} interactive={false} /></div>
                            <div className="muted" style={{ fontSize: 12 }}>{fmtDate(b.last_paid_date)}</div>
                          </>
                        ) : <span className="muted">Never</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {editing && <BillForm bill={editing.bill} onClose={() => setEditing(null)} />}
    </div>
  );
}

function BillForm({ bill, onClose }: { bill?: Bill; onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label={bill ? `Bill: ${bill.name}` : 'Add bill'} width={520}>
      <BillFormBody bill={bill} />
    </Dialog>
  );
}

function BillFormBody({ bill }: { bill?: Bill }) {
  const close = useDialogClose();
  const { bump } = useShell();
  const [f, setF] = useState({
    name: bill?.name ?? '',
    min: bill ? paiseToInput(bill.amount_min) : '',
    max: bill ? paiseToInput(bill.amount_max) : '',
    firstDue: bill?.first_due ?? todayIso(),
    repeat: (bill?.repeat ?? 'monthly') as BillRepeat,
    skip: String(bill?.skip ?? 0),
    match: bill?.match ?? '',
    active: bill?.active ?? true,
    notes: bill?.notes ?? '',
  });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((p) => ({ ...p, [k]: v }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const min = toPaise(f.min);
    const max = toPaise(f.max || f.min);
    if (min === null || min <= 0 || max === null || max <= 0) return setError('Enter the amount (or a min–max range) in ₹');
    if (max < min) return setError('Maximum must be at least the minimum');
    const body = {
      name: f.name,
      amount_min: min,
      amount_max: max,
      first_due: f.firstDue,
      repeat: f.repeat,
      skip: Number(f.skip) || 0,
      match: f.match || null,
      active: f.active,
      notes: f.notes || null,
    };
    setSaving(true);
    try {
      if (bill) await api(`/bills/${bill.id}`, { method: 'PUT', body });
      else await api('/bills', { method: 'POST', body });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!bill) return;
    if (!confirmDelete) return setConfirmDelete(true);
    setSaving(true);
    try {
      await api(`/bills/${bill.id}`, { method: 'DELETE' });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead
        title={bill ? bill.name : 'Add bill'}
        sub={bill ? <>{repeatText(bill.repeat, bill.skip)} · <BillBadge status={bill.status} /></> : 'Amounts are in ₹'}
        lead={<span className="ico" style={{ background: 'var(--coral-50)', color: 'var(--coral-600)' }}><Icon name="receipt-text" size={20} /></span>}
      />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        {bill && (
          <div className="card card-pad" style={{ marginBottom: 18 }}>
            <div className="kv"><span className="k">Next due</span><span className="v">{bill.next_due ? `${fmtDate(bill.next_due)}${bill.status !== 'paid' ? ' · ' + dueText(bill.next_due) : ''}` : '—'}</span></div>
            <div className="kv"><span className="k">Last paid</span><span className="v">{bill.last_paid_date ? fmtDate(bill.last_paid_date) : 'Never'}</span></div>
            <div className="kv">
              <span className="k">Linked expenses</span>
              <span className="v"><Link href={`/transactions?bill=${bill.id}`}>{bill.transaction_count} · view all</Link></span>
            </div>
          </div>
        )}
        <div className="field">
          <label htmlFor="bi-name">Name</label>
          <input id="bi-name" className="inp" value={f.name} onChange={(e) => set('name', e.target.value)} required maxLength={120} placeholder="e.g. Electricity" />
        </div>
        <div className="row2">
          <div className="field">
            <label htmlFor="bi-min">Amount (₹)</label>
            <input id="bi-min" className="inp" inputMode="decimal" value={f.min} onChange={(e) => set('min', e.target.value)} required placeholder="Minimum" />
          </div>
          <div className="field">
            <label htmlFor="bi-max">Up to (₹) <span className="muted" style={{ fontWeight: 400 }}>(optional)</span></label>
            <input id="bi-max" className="inp" inputMode="decimal" value={f.max} onChange={(e) => set('max', e.target.value)} placeholder="Same as amount" />
          </div>
        </div>
        <div className="hint" style={{ marginTop: -8, marginBottom: 16, fontSize: 12, color: 'var(--fg-3)' }}>
          Use a range for bills that vary, like electricity. An expense only matches if its amount is inside the range.
        </div>
        <div className="row3">
          <div className="field">
            <label htmlFor="bi-first">First due date</label>
            <input id="bi-first" type="date" className="inp" value={f.firstDue} onChange={(e) => set('firstDue', e.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="bi-rep">Repeats</label>
            <select id="bi-rep" className="inp" value={f.repeat} onChange={(e) => set('repeat', e.target.value as BillRepeat)}>
              <option value="weekly">Weekly</option>
              <option value="monthly">Monthly</option>
              <option value="quarterly">Quarterly</option>
              <option value="half_yearly">Every 6 months</option>
              <option value="yearly">Yearly</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="bi-skip">Every</label>
            <select id="bi-skip" className="inp" value={f.skip} onChange={(e) => set('skip', e.target.value)}>
              {[0, 1, 2, 3, 5, 11].map((s) => (
                <option key={s} value={s}>{s === 0 ? 'period' : `${s + 1} periods`}</option>
              ))}
            </select>
          </div>
        </div>
        <div className="field">
          <label htmlFor="bi-match">Match words</label>
          <input id="bi-match" className="inp" value={f.match} onChange={(e) => set('match', e.target.value)} maxLength={255} placeholder={f.name ? `Defaults to "${f.name}"` : 'e.g. tata power, tpddl'} />
          <div className="hint">Comma-separated. A new expense is linked when one of these appears in its description or payee and the amount fits.</div>
        </div>
        <div className="field">
          <label htmlFor="bi-notes">Notes</label>
          <textarea id="bi-notes" className="inp" value={f.notes} onChange={(e) => set('notes', e.target.value)} />
        </div>
        {bill && (
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 14 }}>
            <input type="checkbox" checked={f.active} onChange={(e) => set('active', e.target.checked)} />
            Active <span className="muted" style={{ fontSize: 12.5 }}>— inactive bills aren&apos;t matched or shown as due</span>
          </label>
        )}
      </div>
      <div className="drawer-foot">
        {bill && (
          <Button variant={confirmDelete ? 'primary' : 'ghost'} icon="trash-2" onClick={remove} disabled={saving} className={confirmDelete ? 'btn-danger' : ''}>
            {confirmDelete ? 'Confirm delete' : 'Delete'}
          </Button>
        )}
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        <Button variant="primary" type="submit" disabled={saving}>{saving ? 'Saving…' : bill ? 'Save changes' : 'Add bill'}</Button>
      </div>
    </form>
  );
}
