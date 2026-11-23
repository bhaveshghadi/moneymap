'use client';
import { useState, type FormEvent } from 'react';
import Link from 'next/link';
import { api } from '../lib/api';
import { useApi, useShell } from '../contexts/ShellCtx';
import type { Account, InvestmentDetail, PropertyCostKind, PropertyPurchase, PropertyStatus } from '../lib/types';
import { fmtDate, paiseToInput, rs, toPaise, todayIso } from '../lib/format';
import { Button } from '../primitives/Button';
import { Icon } from '../primitives/Icon';
import { Money } from '../primitives/Money';
import { Dialog, useDialogClose } from '../primitives/Dialog';
import { DrawerHead } from './DrawerHead';
import { Progress } from './Progress';

export const STATUS_LABEL: Record<PropertyStatus, string> = {
  booked: 'Booked',
  agreement: 'Agreement made',
  registration_pending: 'Registration pending',
  registered: 'Registered',
};
const STATUS_BADGE: Record<PropertyStatus, string> = {
  booked: 'neutral',
  agreement: 'brand',
  registration_pending: 'cau',
  registered: 'mint',
};
const COST_LABEL: Record<PropertyCostKind, string> = {
  stamp_duty: 'Stamp duty',
  registration: 'Registration fee',
  legal: 'Lawyer / legal',
  broker: 'Broker',
  other: 'Other cost',
};
const PLAN_BADGE = { paid: ['mint', 'Paid'], part: ['cau', 'Part paid'], due: ['neutral', 'Due'], overdue: ['red', 'Overdue'] } as const;

/** A property bought in parts: price paid vs agreed, the plan for the balance, costs, goal. */
export function PropertySection({ inv, onPay }: { inv: InvestmentDetail; onPay: (amount: number) => void }) {
  const p = inv.property;
  const [dlg, setDlg] = useState<null | 'deal' | 'cost' | 'goal'>(null);
  const { bump } = useShell();
  const [busy, setBusy] = useState(false);

  const removeCost = async (id: number) => {
    setBusy(true);
    try {
      await api(`/investments/${inv.id}/property/costs/${id}`, { method: 'DELETE' });
      bump();
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      {!p || p.price === null ? (
        <div className="card card-pad" style={{ marginBottom: 16, display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
          <Icon name="map" size={20} />
          <div style={{ flex: 1, minWidth: 220 }}>
            <b>Bought in parts, or not registered yet?</b>
            <div className="muted" style={{ fontSize: 13 }}>Add the agreed price and the plan for the balance — MoneyMap shows what&apos;s paid, what&apos;s left and when it&apos;s due.</div>
          </div>
          <Button variant="primary" icon="plus" onClick={() => setDlg('deal')}>Add purchase details</Button>
        </div>
      ) : (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="card-head">
            <h3 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              Purchase <span className={`badge ${STATUS_BADGE[p.status]}`}>{STATUS_LABEL[p.status]}</span>
            </h3>
            <Button variant="ghost" size="sm" icon="pencil" onClick={() => setDlg('deal')}>Edit</Button>
          </div>
          <div className="card-pad" style={{ paddingTop: 0 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', fontSize: 14, marginBottom: 8 }}>
              <span>
                <b><Money amount={rs(p.price_paid)} interactive={false} /></b> <span className="muted">paid of</span> <b><Money amount={rs(p.price ?? 0)} interactive={false} /></b>
              </span>
              <span style={{ color: p.balance ? 'var(--amber-700)' : 'var(--mint-700)', fontWeight: 600 }}>
                {p.balance ? <><Money amount={rs(p.balance)} interactive={false} /> to pay</> : 'Fully paid'}
              </span>
            </div>
            <Progress value={p.price_paid} max={p.price ?? 0} savings />
            <div style={{ display: 'flex', gap: '6px 20px', flexWrap: 'wrap', fontSize: 13, marginTop: 12 }}>
              {(
                [
                  ['Size', p.size],
                  ['Where', p.location],
                  ['Survey / gat no.', p.survey_no],
                  ['Seller', p.seller],
                  ['Agreement', p.agreement_date && fmtDate(p.agreement_date)],
                  ['Registered', p.registered_on && fmtDate(p.registered_on)],
                ] as [string, string | null][]
              )
                .filter(([, v]) => v)
                .map(([k, v]) => (
                  <span key={k}><span className="muted">{k} </span><b>{v}</b></span>
                ))}
            </div>
            {p.status !== 'registered' && (
              <div className="note info" style={{ marginTop: 12, marginBottom: 0 }}>
                <Icon name="info" size={15} />
                <span>Until it&apos;s registered in your name it counts in your net worth as what you&apos;ve paid. Once registered: its full value.</span>
              </div>
            )}
          </div>

          <div className="inv-group-head"><span>Payment plan</span></div>
          {p.plan.length === 0 ? (
            <div className="muted" style={{ padding: '0 18px 14px', fontSize: 13 }}>No plan for the balance yet — add the dates under Edit.</div>
          ) : (
            <div style={{ padding: '0 8px 8px' }}>
              {p.plan.map((x) => {
                const [cls, label] = PLAN_BADGE[x.status];
                const left = x.amount - x.paid;
                return (
                  <div key={x.id} className="prop-row">
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <b>{fmtDate(x.due_date)}</b>
                      {x.note && <span className="muted"> · {x.note}</span>}
                      <div style={{ marginTop: 3 }}><span className={`badge ${cls}`}>{label}</span></div>
                    </div>
                    <span className="fig" style={{ whiteSpace: 'nowrap' }}>
                      <Money amount={rs(x.amount)} interactive={false} />
                      {x.status === 'part' && <div className="muted" style={{ fontSize: 12 }}><Money amount={rs(left)} interactive={false} /> left</div>}
                    </span>
                    {left > 0 && <Button variant={x.status === 'overdue' ? 'primary' : 'secondary'} size="sm" onClick={() => onPay(left)}>Pay</Button>}
                  </div>
                );
              })}
              {p.unplanned ? (
                <div className="muted" style={{ fontSize: 12.5, padding: '6px 10px' }}>
                  <Money amount={rs(p.unplanned)} interactive={false} /> of the balance has no date yet.
                </div>
              ) : null}
            </div>
          )}

          <div className="inv-group-head" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>Costs on top</span>
            <Button variant="ghost" size="sm" icon="plus" onClick={() => setDlg('cost')}>Add cost</Button>
          </div>
          <div style={{ padding: '0 8px 8px' }}>
            {p.costs.length === 0 ? (
              <div className="muted" style={{ padding: '0 10px 8px', fontSize: 13 }}>Stamp duty, registration fee, lawyer, broker — add them so the real cost is known.</div>
            ) : (
              <>
                {p.costs.map((c) => (
                  <div key={c.id} className="prop-row">
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <b>{COST_LABEL[c.kind]}</b>
                      <span className="muted"> · {fmtDate(c.date)}{c.note ? ` · ${c.note}` : ''}{c.transaction_id ? '' : ' · paid before'}</span>
                    </div>
                    <span className="fig"><Money amount={rs(c.amount)} interactive={false} /></span>
                    <Button variant="ghost" size="sm" icon="trash-2" aria-label={`Remove ${COST_LABEL[c.kind]}`} onClick={() => removeCost(c.id)} disabled={busy} />
                  </div>
                ))}
                <div className="kv" style={{ padding: '6px 10px 0' }}>
                  <span className="k">Cost so far (price paid + costs)</span>
                  <span className="v fig"><Money amount={rs(p.total_cost)} interactive={false} /></span>
                </div>
              </>
            )}
          </div>

          {p.balance ? (
            <div className="card-pad" style={{ borderTop: '1px solid var(--border)', display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
              <Icon name="piggy-bank" size={18} />
              {p.goal_id ? (
                <span style={{ fontSize: 13.5, flex: 1 }}>
                  Saving for the balance: <b><Money amount={rs(p.goal_saved ?? 0)} interactive={false} /></b> set aside of{' '}
                  <Money amount={rs(p.balance)} interactive={false} />. <Link href="/piggy-banks">Open the goal</Link>
                </span>
              ) : (
                <>
                  <span style={{ fontSize: 13.5, flex: 1, minWidth: 200 }}>Put money aside for the balance as a goal — the Savings plan then counts it.</span>
                  <Button variant="secondary" size="sm" onClick={() => setDlg('goal')}>Save for the balance</Button>
                </>
              )}
            </div>
          ) : null}
        </div>
      )}

      {dlg === 'deal' && <DealDialog inv={inv} p={p} onClose={() => setDlg(null)} />}
      {dlg === 'cost' && <CostDialog inv={inv} onClose={() => setDlg(null)} />}
      {dlg === 'goal' && <GoalDialog inv={inv} onClose={() => setDlg(null)} />}
    </>
  );
}

function useBanks() {
  return useApi<Account[]>('/accounts?type=asset&type=cash&include_inactive=false');
}

// ---------------------------------------------------------------- the deal

type Row = { due_date: string; amount: string; note: string };

function DealDialog({ inv, p, onClose }: { inv: InvestmentDetail; p: PropertyPurchase | null; onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label="Purchase details" width={600}>
      <DealBody inv={inv} p={p} />
    </Dialog>
  );
}

function DealBody({ inv, p }: { inv: InvestmentDetail; p: PropertyPurchase | null }) {
  const close = useDialogClose();
  const { bump } = useShell();
  const [price, setPrice] = useState(p?.price ? paiseToInput(p.price) : '');
  const [size, setSize] = useState(p?.size ?? '');
  const [location, setLocation] = useState(p?.location ?? '');
  const [survey, setSurvey] = useState(p?.survey_no ?? '');
  const [seller, setSeller] = useState(p?.seller ?? '');
  const [agreement, setAgreement] = useState(p?.agreement_date ?? '');
  const [status, setStatus] = useState<PropertyStatus>(p?.status ?? 'agreement');
  const [registered, setRegistered] = useState(p?.registered_on ?? '');
  const [rows, setRows] = useState<Row[]>((p?.plan ?? []).map((x) => ({ due_date: x.due_date, amount: paiseToInput(x.amount), note: x.note ?? '' })));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const priceP = toPaise(price || '0') ?? 0;
  const planned = rows.reduce((a, r) => a + (toPaise(r.amount || '0') ?? 0), 0);
  const balance = priceP ? Math.max(0, priceP - inv.money_in + inv.money_out) : 0;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!priceP) return setError('Enter the total agreed price.');
    if (status === 'registered' && !registered) return setError('Enter the date it was registered in your name.');
    const plan = [];
    for (const r of rows) {
      const a = toPaise(r.amount);
      if (!r.due_date || a === null || a <= 0) return setError('Each planned payment needs a date and an amount.');
      plan.push({ due_date: r.due_date, amount: a, note: r.note || null });
    }
    setSaving(true);
    try {
      await api(`/investments/${inv.id}/property`, {
        method: 'PUT',
        body: {
          price: priceP, size: size || null, location: location || null, survey_no: survey || null, seller: seller || null,
          agreement_date: agreement || null, status, registered_on: status === 'registered' ? registered : null, plan,
        },
      });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  const setRow = (i: number, u: Partial<Row>) => setRows((rs_) => rs_.map((r, k) => (k === i ? { ...r, ...u } : r)));

  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead title="Purchase details" sub={inv.name} />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        <div className="row2">
          <div className="field">
            <label htmlFor="pp-price">Total agreed price (₹)</label>
            <input id="pp-price" className="inp" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} required placeholder="e.g. 2000000" />
          </div>
          <div className="field">
            <label htmlFor="pp-status">Status</label>
            <select id="pp-status" className="inp" value={status} onChange={(e) => setStatus(e.target.value as PropertyStatus)}>
              {(Object.keys(STATUS_LABEL) as PropertyStatus[]).map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
            </select>
          </div>
        </div>
        {status === 'registered' && (
          <div className="field">
            <label htmlFor="pp-reg">Registered in your name on</label>
            <input id="pp-reg" className="inp" type="date" value={registered} onChange={(e) => setRegistered(e.target.value)} required />
          </div>
        )}
        <div className="hint" style={{ marginTop: -6, marginBottom: 12 }}>
          Paid so far: <Money amount={rs(inv.money_in - inv.money_out)} interactive={false} /> (money put into this property).
          {priceP > 0 && <> Balance: <Money amount={rs(balance)} interactive={false} />.</>}
        </div>
        <div className="row2">
          <div className="field">
            <label htmlFor="pp-size">Size</label>
            <input id="pp-size" className="inp" value={size} onChange={(e) => setSize(e.target.value)} maxLength={60} placeholder="e.g. 2 guntha, 1,200 sq ft" />
          </div>
          <div className="field">
            <label htmlFor="pp-agr">Agreement date</label>
            <input id="pp-agr" className="inp" type="date" value={agreement} onChange={(e) => setAgreement(e.target.value)} />
          </div>
        </div>
        <div className="field">
          <label htmlFor="pp-loc">Village / address</label>
          <input id="pp-loc" className="inp" value={location} onChange={(e) => setLocation(e.target.value)} maxLength={200} />
        </div>
        <div className="row2">
          <div className="field">
            <label htmlFor="pp-sur">Survey / gat / plot no.</label>
            <input id="pp-sur" className="inp" value={survey} onChange={(e) => setSurvey(e.target.value)} maxLength={60} />
          </div>
          <div className="field">
            <label htmlFor="pp-sel">Seller</label>
            <input id="pp-sel" className="inp" value={seller} onChange={(e) => setSeller(e.target.value)} maxLength={120} />
          </div>
        </div>

        <div className="field">
          <label>Plan for the balance</label>
          {rows.map((r, i) => (
            <div key={i} className="prop-plan-row">
              <input className="inp" type="date" aria-label="Due date" value={r.due_date} onChange={(e) => setRow(i, { due_date: e.target.value })} />
              <input className="inp" inputMode="decimal" aria-label="Amount" placeholder="Amount ₹" value={r.amount} onChange={(e) => setRow(i, { amount: e.target.value })} />
              <input className="inp" aria-label="Note" placeholder="Note (e.g. on registration)" value={r.note} onChange={(e) => setRow(i, { note: e.target.value })} maxLength={120} />
              <Button variant="ghost" size="sm" icon="x" aria-label="Remove this payment" onClick={() => setRows((xs) => xs.filter((_, k) => k !== i))} />
            </div>
          ))}
          <Button variant="secondary" size="sm" icon="plus" onClick={() => setRows((xs) => [...xs, { due_date: '', amount: balance && !xs.length ? paiseToInput(balance) : '', note: '' }])}>
            Add a planned payment
          </Button>
          {rows.length > 0 && priceP > 0 && (
            <div className="hint" style={{ color: planned !== balance ? 'var(--amber-700)' : undefined }}>
              Planned <Money amount={rs(planned)} interactive={false} /> of the <Money amount={rs(balance)} interactive={false} /> balance
              {planned !== balance ? ' — they don’t have to match, but the plan usually covers the balance.' : '.'}
            </div>
          )}
        </div>
      </div>
      <div className="drawer-foot">
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        <Button variant="primary" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save'}</Button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------- a cost

function CostDialog({ inv, onClose }: { inv: InvestmentDetail; onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label="Add a cost" width={480}>
      <CostBody inv={inv} />
    </Dialog>
  );
}

function CostBody({ inv }: { inv: InvestmentDetail }) {
  const close = useDialogClose();
  const { bump } = useShell();
  const banks = useBanks();
  const [kind, setKind] = useState<PropertyCostKind>('stamp_duty');
  const [amount, setAmount] = useState('');
  const [date, setDate] = useState(todayIso());
  const [bank, setBank] = useState(inv.pay_from_id ? String(inv.pay_from_id) : '');
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const a = toPaise(amount);
    if (!a || a <= 0) return setError('Enter the amount.');
    setSaving(true);
    try {
      await api(`/investments/${inv.id}/property/costs`, { method: 'POST', body: { kind, amount: a, date, bank_id: bank ? Number(bank) : null, note: note || null } });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };
  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead title="Add a cost" sub={inv.name} />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        <div className="field">
          <label htmlFor="pc-kind">What</label>
          <select id="pc-kind" className="inp" value={kind} onChange={(e) => setKind(e.target.value as PropertyCostKind)}>
            {(Object.keys(COST_LABEL) as PropertyCostKind[]).map((k) => <option key={k} value={k}>{COST_LABEL[k]}</option>)}
          </select>
        </div>
        <div className="row2">
          <div className="field">
            <label htmlFor="pc-amt">Amount (₹)</label>
            <input id="pc-amt" className="inp" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} required placeholder="0.00" />
          </div>
          <div className="field">
            <label htmlFor="pc-date">Date</label>
            <input id="pc-date" className="inp" type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
          </div>
        </div>
        <div className="field">
          <label htmlFor="pc-bank">Paid from</label>
          <select id="pc-bank" className="inp" value={bank} onChange={(e) => setBank(e.target.value)}>
            <option value="">Paid already — just note it</option>
            {(banks.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
          <div className="hint">From a bank: recorded as a transfer into the property (not spending). &ldquo;Paid already&rdquo;: only added to what the property cost you.</div>
        </div>
        <div className="field">
          <label htmlFor="pc-note">Note</label>
          <input id="pc-note" className="inp" value={note} onChange={(e) => setNote(e.target.value)} maxLength={120} />
        </div>
      </div>
      <div className="drawer-foot">
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        <Button variant="primary" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Add cost'}</Button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------- goal for the balance

function GoalDialog({ inv, onClose }: { inv: InvestmentDetail; onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label="Save for the balance" width={460}>
      <GoalBody inv={inv} />
    </Dialog>
  );
}

function GoalBody({ inv }: { inv: InvestmentDetail }) {
  const close = useDialogClose();
  const { bump } = useShell();
  const banks = useBanks();
  const [bank, setBank] = useState(inv.pay_from_id ? String(inv.pay_from_id) : '');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const last = inv.property?.plan.at(-1)?.due_date;
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api(`/investments/${inv.id}/property/goal`, { method: 'POST', body: { account_id: Number(bank) } });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };
  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead title="Save for the balance" sub={inv.name} />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        <p style={{ marginTop: 0, fontSize: 13.5, lineHeight: 1.55, color: 'var(--fg-2)' }}>
          A piggy bank for the <b><Money amount={rs(inv.property?.balance ?? 0)} interactive={false} /></b> still to pay
          {last ? <> by <b>{fmtDate(last)}</b></> : null}. Its target follows the balance as you pay, and the Savings plan counts what you set aside.
        </p>
        <div className="field">
          <label htmlFor="pg-bank">Kept in</label>
          <select id="pg-bank" className="inp" value={bank} onChange={(e) => setBank(e.target.value)} required>
            <option value="">Choose…</option>
            {(banks.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
          <div className="hint">The money stays in this account; the goal only earmarks part of it.</div>
        </div>
      </div>
      <div className="drawer-foot">
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        <Button variant="primary" type="submit" disabled={saving || !bank}>{saving ? 'Saving…' : 'Make the goal'}</Button>
      </div>
    </form>
  );
}
