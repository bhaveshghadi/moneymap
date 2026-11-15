'use client';
import { useEffect, useState, type FormEvent } from 'react';
import type { Account, LoanDetail, LoanEvent, TxnPage } from '../lib/types';
import { api, qs } from '../lib/api';
import { fmtDate, rs, toPaise, todayIso } from '../lib/format';
import { useApi, useShell } from '../contexts/ShellCtx';
import { Dialog, useDialogClose } from '../primitives/Dialog';
import { Button } from '../primitives/Button';
import { Money } from '../primitives/Money';
import { SegmentedControl } from '../primitives/SegmentedControl';
import { Icon } from '../primitives/Icon';
import { DrawerHead } from './DrawerHead';

type Mode = 'reduce_tenure' | 'reduce_emi';

interface Plan {
  emi: number;
  months: number;
  interest: number;
  end_date: string | null;
}
interface WhatIf {
  outstanding: number;
  before: Plan;
  after: Plan;
  interest_saved: number;
  months_saved: number;
  paid_off: boolean;
}

export const MODE_LABEL: Record<Mode, string> = {
  reduce_tenure: 'Keep the EMI, change the end date',
  reduce_emi: 'Keep the end date, change the EMI',
};

/** Before / after of a part-payment or rate change, worked out by the server as you type. */
function useWhatIf(loanId: number, body: Record<string, unknown> | null) {
  const [res, setRes] = useState<{ key: string; data: WhatIf | null; error: string | null } | null>(null);
  const key = body ? JSON.stringify(body) : '';
  useEffect(() => {
    if (!body) return;
    let cancelled = false;
    const t = setTimeout(() => {
      api<WhatIf>(`/loans/${loanId}/what-if`, { method: 'POST', body })
        .then((d) => !cancelled && setRes({ key, data: d, error: null }))
        .catch((e: Error) => !cancelled && setRes({ key, data: null, error: e.message }));
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, loanId]);
  return body && res?.key === key ? res : null;
}

function Compare({ w }: { w: WhatIf }) {
  const cell = (p: Plan) => (
    <>
      <div className="fig" style={{ fontSize: 16 }}>{p.emi ? <Money amount={rs(p.emi)} interactive={false} /> : '—'}<span className="muted" style={{ fontSize: 12 }}> /month</span></div>
      <div className="muted" style={{ fontSize: 12.5 }}>
        {p.months} EMI{p.months === 1 ? '' : 's'} left{p.end_date ? ` · ends ${fmtDate(p.end_date)}` : ''}
      </div>
      <div className="muted" style={{ fontSize: 12.5 }}>
        interest still to pay <Money amount={rs(p.interest)} interactive={false} />
      </div>
    </>
  );
  return (
    <div className="card card-pad" style={{ background: 'var(--bg-subtle)' }} aria-live="polite">
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
        <div>
          <div className="muted" style={{ fontSize: 11.5, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Now</div>
          {cell(w.before)}
        </div>
        <div>
          <div className="muted" style={{ fontSize: 11.5, textTransform: 'uppercase', letterSpacing: '0.05em' }}>After</div>
          {w.paid_off ? <b>Loan paid off</b> : cell(w.after)}
        </div>
      </div>
      <div style={{ marginTop: 10, fontSize: 13.5 }}>
        {w.interest_saved >= 0 ? (
          <>
            You save <b><Money amount={rs(w.interest_saved)} interactive={false} /></b> in interest
            {w.months_saved > 0 && <> and finish <b>{w.months_saved} month{w.months_saved === 1 ? '' : 's'} earlier</b></>}.
          </>
        ) : (
          <>
            You pay <b><Money amount={rs(-w.interest_saved)} interactive={false} /></b> more interest
            {w.months_saved < 0 && <> and finish <b>{-w.months_saved} month{w.months_saved === -1 ? '' : 's'} later</b></>}.
          </>
        )}
      </div>
    </div>
  );
}

export function PrepayDialog({ loan, onClose }: { loan: LoanDetail; onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label="Part-payment" width={560}>
      <PrepayBody loan={loan} />
    </Dialog>
  );
}

function PrepayBody({ loan }: { loan: LoanDetail }) {
  const close = useDialogClose();
  const { bump } = useShell();
  const banks = useApi<Account[]>('/accounts?type=asset&type=cash&include_inactive=false');
  // existing expenses that could be this payment: from the paid-from account, not linked yet, bigger than the EMI
  const recent = useApi<TxnPage>(loan.pay_from_id ? `/transactions${qs({ account_id: loan.pay_from_id, type: 'withdrawal', limit: 200 })}` : null);
  const [f, setF] = useState({ amount: '', date: todayIso(), mode: 'reduce_tenure' as Mode, from: loan.pay_from_id ? String(loan.pay_from_id) : '', fee: '', existing: '' });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((p) => ({ ...p, [k]: v }));
  const options = (recent.data?.items ?? []).filter((t) => t.amount > loan.current_emi);
  const amount = toPaise(f.amount);
  const w = useWhatIf(loan.id, amount && amount > 0 ? { kind: 'prepay', amount, date: f.date, mode: f.mode } : null);

  const pickExisting = (id: string) => {
    const t = options.find((x) => String(x.id) === id);
    setF((p) => ({ ...p, existing: id, amount: t ? String(t.amount / 100) : p.amount, date: t ? t.date : p.date }));
  };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!amount || amount <= 0) return setError('Enter the amount paid.');
    setSaving(true);
    try {
      await api(`/loans/${loan.id}/prepay`, {
        method: 'POST',
        body: {
          date: f.date,
          amount,
          mode: f.mode,
          from_account_id: f.from ? Number(f.from) : null,
          transaction_id: f.existing ? Number(f.existing) : null,
          fee: f.fee ? toPaise(f.fee) : null,
        },
      });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead title="Part-payment" sub={`${loan.name} · ₹${(loan.outstanding / 100).toLocaleString('en-IN')} left`} lead={<span className="ico" style={{ background: 'var(--mint-50)', color: 'var(--mint-700)' }}><Icon name="piggy-bank" size={20} /></span>} />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        {options.length > 0 && (
          <div className="field">
            <label htmlFor="pp-ex">Already in your transactions?</label>
            <select id="pp-ex" className="inp" value={f.existing} onChange={(e) => pickExisting(e.target.value)}>
              <option value="">No — record a new payment</option>
              {options.map((t) => (
                <option key={t.id} value={t.id}>{fmtDate(t.date)} · {t.description.slice(0, 50)} · ₹{(t.amount / 100).toLocaleString('en-IN')}</option>
              ))}
            </select>
            <div className="hint">E.g. a “Payment against loan” row from a bank statement — it becomes this part-payment instead of a second entry.</div>
          </div>
        )}
        <div className="row2">
          <div className="field">
            <label htmlFor="pp-amt">Amount (₹)</label>
            <input id="pp-amt" className="inp" inputMode="decimal" value={f.amount} onChange={(e) => set('amount', e.target.value)} disabled={!!f.existing} placeholder="e.g. 100000" />
          </div>
          <div className="field">
            <label htmlFor="pp-date">Paid on</label>
            <input id="pp-date" className="inp" type="date" value={f.date} onChange={(e) => set('date', e.target.value)} disabled={!!f.existing} />
          </div>
        </div>
        {!f.existing && (
          <div className="row2">
            <div className="field">
              <label htmlFor="pp-from">Paid from</label>
              <select id="pp-from" className="inp" value={f.from} onChange={(e) => set('from', e.target.value)}>
                <option value="">Choose an account…</option>
                {(banks.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            </div>
            <div className="field">
              <label htmlFor="pp-fee">Lender&apos;s charge (₹)</label>
              <input id="pp-fee" className="inp" inputMode="decimal" value={f.fee} onChange={(e) => set('fee', e.target.value)} placeholder="optional" />
            </div>
          </div>
        )}
        <div className="field">
          <label>After the part-payment</label>
          <SegmentedControl aria-label="After the part-payment" value={f.mode} onChange={(v) => set('mode', v as Mode)} options={[{ value: 'reduce_tenure', label: 'Same EMI, end sooner' }, { value: 'reduce_emi', label: 'Same end date, lower EMI' }]} />
          <div className="hint">Ask your lender which one they applied — you can switch it later.</div>
        </div>
        {w?.data && <Compare w={w.data} />}
        {w?.error && <div className="note warn"><span>{w.error}</span></div>}
        <div className="muted" style={{ fontSize: 12.5, marginTop: 8 }}>
          {loan.count_mode === 'whole_emi'
            ? 'This loan counts whole EMIs as spending, so the part-payment counts as spending too (“Loan / EMI”).'
            : 'This loan counts only interest as spending, so the part-payment is a transfer to the loan.'}
        </div>
      </div>
      <div className="drawer-foot">
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        <Button variant="primary" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Record part-payment'}</Button>
      </div>
    </form>
  );
}

export function RateDialog({ loan, onClose }: { loan: LoanDetail; onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label="Interest rate change" width={540}>
      <RateBody loan={loan} />
    </Dialog>
  );
}

function RateBody({ loan }: { loan: LoanDetail }) {
  const close = useDialogClose();
  const { bump } = useShell();
  const [f, setF] = useState({ rate: '', date: todayIso(), mode: 'reduce_tenure' as Mode });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((p) => ({ ...p, [k]: v }));
  const rate = f.rate ? Number(f.rate) : null;
  const w = useWhatIf(loan.id, rate !== null && !Number.isNaN(rate) ? { kind: 'rate', rate, date: f.date, mode: f.mode } : null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (rate === null || Number.isNaN(rate)) return setError('Enter the new interest rate.');
    setSaving(true);
    try {
      await api(`/loans/${loan.id}/rate`, { method: 'POST', body: { rate, date: f.date, mode: f.mode } });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead title="Interest rate change" sub={`${loan.name} · now ${loan.current_rate ?? '—'}% a year`} lead={<span className="ico" style={{ background: 'var(--amber-50)', color: 'var(--amber-700)' }}><Icon name="percent" size={20} /></span>} />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        <div className="row2">
          <div className="field">
            <label htmlFor="rc-rate">New rate (% a year)</label>
            <input id="rc-rate" className="inp" inputMode="decimal" value={f.rate} onChange={(e) => set('rate', e.target.value)} placeholder="e.g. 8.75" />
          </div>
          <div className="field">
            <label htmlFor="rc-date">From</label>
            <input id="rc-date" className="inp" type="date" value={f.date} onChange={(e) => set('date', e.target.value)} />
          </div>
        </div>
        <div className="field">
          <label>The lender will</label>
          <SegmentedControl aria-label="The lender will" value={f.mode} onChange={(v) => set('mode', v as Mode)} options={[{ value: 'reduce_tenure', label: 'Keep the EMI' }, { value: 'reduce_emi', label: 'Change the EMI' }]} />
          <div className="hint">Banks usually keep the EMI and change the number of months; EMIs already due keep their figures.</div>
        </div>
        {w?.data && <Compare w={w.data} />}
        {w?.error && <div className="note warn"><span>{w.error}</span></div>}
      </div>
      <div className="drawer-foot">
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        <Button variant="primary" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save rate change'}</Button>
      </div>
    </form>
  );
}

/** The loan's part-payments and rate changes, newest first, with switch / remove. */
export function LoanChangesList({ loan }: { loan: LoanDetail }) {
  const { bump } = useShell();
  const [confirm, setConfirm] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (loan.events.length === 0) return null;
  const act = async (ev: LoanEvent, what: 'switch' | 'remove') => {
    setError(null);
    if (what === 'remove' && confirm !== ev.id) return setConfirm(ev.id);
    try {
      if (what === 'switch') {
        await api(`/loans/${loan.id}/events/${ev.id}`, { method: 'PATCH', body: { mode: ev.mode === 'reduce_tenure' ? 'reduce_emi' : 'reduce_tenure' } });
      } else {
        await api(`/loans/${loan.id}/events/${ev.id}`, { method: 'DELETE' });
      }
      bump();
    } catch (e) {
      setError((e as Error).message);
    }
    setConfirm(null);
  };
  return (
    <div className="card card-pad" style={{ marginBottom: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ fontFamily: 'var(--font-display)', fontWeight: 650, fontSize: 16 }}>Part-payments &amp; rate changes</div>
      {error && <div className="form-error" role="alert">{error}</div>}
      {[...loan.events].reverse().map((ev) => (
        <div key={ev.id} style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', fontSize: 13.5, borderTop: '1px solid var(--border)', paddingTop: 10 }}>
          <Icon name={ev.kind === 'prepay' ? 'piggy-bank' : 'percent'} size={16} />
          <span style={{ flex: 1, minWidth: 200 }}>
            <b>{fmtDate(ev.date)}</b> ·{' '}
            {ev.kind === 'prepay' ? (
              <>part-payment <Money amount={rs(ev.amount ?? 0)} interactive={false} /></>
            ) : (
              <>rate changed to <b>{ev.rate}%</b></>
            )}
            <span className="muted">
              {' '}· {MODE_LABEL[ev.mode as Mode].toLowerCase()}
              {ev.emi_after ? <> · EMI from then <Money amount={rs(ev.emi_after)} interactive={false} /></> : null}
            </span>
          </span>
          <Button variant="ghost" size="sm" onClick={() => act(ev, 'switch')}>Switch</Button>
          <Button variant={confirm === ev.id ? 'primary' : 'ghost'} size="sm" icon="trash-2" className={confirm === ev.id ? 'btn-danger' : ''} onClick={() => act(ev, 'remove')}>
            {confirm === ev.id ? 'Confirm remove' : 'Remove'}
          </Button>
        </div>
      ))}
    </div>
  );
}
