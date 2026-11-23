'use client';
import { useState, type FormEvent, type ReactNode } from 'react';
import Link from 'next/link';
import { api } from '../lib/api';
import { useApi, useShell } from '../contexts/ShellCtx';
import { useTxn } from '../contexts/TxnCtx';
import type { Account, InvestmentDetail, InvestmentLinkable, InvestmentSummary } from '../lib/types';
import { fmtDate, paiseToInput, rs, toPaise, todayIso } from '../lib/format';
import { Button } from '../primitives/Button';
import { Money } from '../primitives/Money';
import { StatCard } from '../primitives/StatCard';
import { Skeleton } from '../primitives/Skeleton';
import { ErrorState } from '../primitives/ErrorState';
import { CategoryGlyph } from '../primitives/CategoryGlyph';
import { Icon } from '../primitives/Icon';
import { Dialog, useDialogClose } from '../primitives/Dialog';
import { DrawerHead } from '../shared/DrawerHead';
import { Progress } from '../shared/Progress';
import { TxnRow } from '../shared/TxnRow';
import { COMPOUNDING_LABEL, FREQUENCY_LABEL, InvestmentForm, KIND_META, subtypeLabel } from '../shared/InvestmentForm';
import { GainText, RatesDialog, dueWhen } from './Investments';
import { PropertySection } from '../shared/PropertyPurchase';

type Dlg = null | 'edit' | 'in' | 'out' | 'value' | 'close' | 'rates' | 'link';

const money = (p: number | null | undefined) => (p != null ? <Money amount={rs(p)} interactive={false} /> : null);

export function InvestmentDetailPage({ id }: { id: number }) {
  const { data, error, reload } = useApi<InvestmentDetail>(`/investments/${id}`);
  const sum = useApi<InvestmentSummary>('/investments/summary');
  const { bump } = useShell();
  const { openTxn } = useTxn();
  const [dlg, setDlg] = useState<Dlg>(null);
  const [preset, setPreset] = useState<number | undefined>(undefined); // a planned property payment
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (error) return <div className="content-wrap"><div className="card"><ErrorState message={error} onRetry={reload} /></div></div>;
  if (!data) return <div className="content-wrap"><Skeleton variant="block" height={120} /><div style={{ height: 16 }} /><Skeleton variant="block" height={300} /></div>;

  const i = data;
  const meta = KIND_META[i.kind];
  const term = i.kind === 'insurance' && i.subtype === 'term';
  const canValue = ['stocks', 'crypto', 'retirement', 'property', 'other'].includes(i.kind) || (i.kind === 'insurance' && !term);
  const active = i.status === 'active';
  const reopen = async () => {
    setMsg(null);
    try {
      await api(`/investments/${i.id}/reopen`, { method: 'POST' });
      bump();
    } catch (e) {
      setMsg((e as Error).message);
    }
  };

  const updatePrices = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const st = await api<{ error: string | null; not_found: string[] }>('/investments/nav/refresh', { method: 'POST' });
      if (st.error) setMsg(st.error);
      else if (st.not_found.includes(i.fund?.scheme ?? '')) setMsg('AMFI has no price for this fund’s ISIN.');
      bump();
    } catch (e) {
      setMsg((e as Error).message);
    }
    setBusy(false);
  };

  const facts: [string, ReactNode][] = [];
  const add = (k: string, v: ReactNode) => v !== null && v !== undefined && v !== '' && facts.push([k, v]);
  if (i.fund) {
    const f = i.fund;
    add('Units', f.units.toLocaleString('en-IN', { maximumFractionDigits: 3 }));
    add('NAV', f.nav !== null ? `₹${f.nav.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}${f.nav_date ? ` on ${fmtDate(f.nav_date)}` : ''}${f.nav_source === 'amfi' ? ' (AMFI)' : f.nav_source === 'cas' ? ' (CAS)' : ''}` : 'not known yet');
    add('Fund house', f.amc);
    add('ISIN', f.isin);
    add('Cost in the CAS', f.cost !== null ? money(f.cost) : null);
  }
  add(i.kind === 'mf' ? 'Folio' : 'Number', i.number);
  add('Rate', i.rate !== null ? `${i.rate}% a year` : null);
  add('Interest', i.rate !== null && i.compounding ? COMPOUNDING_LABEL[i.compounding] : null);
  add(i.kind === 'lent' ? 'Lent on' : ['gold', 'stocks', 'crypto', 'property'].includes(i.kind) ? 'Bought on' : 'Started', i.start_date ? fmtDate(i.start_date) : null);
  add(i.kind === 'lent' ? 'Due back on' : 'Matures', i.maturity_date ? fmtDate(i.maturity_date) : null);
  add('Maturity amount', i.maturity_value ? money(i.maturity_value) : null);
  add(i.kind === 'insurance' ? 'Premium' : 'Instalment', i.instalment ? <>{money(i.instalment)}{i.kind === 'insurance' && i.frequency ? ` · ${FREQUENCY_LABEL[i.frequency].toLowerCase()}` : ' · monthly'}</> : null);
  add('Sum assured', money(i.sum_assured));
  add(i.kind === 'gold' ? (i.subtype === 'sgb' ? 'Units' : 'Grams') : 'Quantity', i.quantity !== null ? i.quantity.toLocaleString('en-IN') : null);
  add('Purity', i.kind === 'gold' && !['sgb', 'digital'].includes(i.subtype ?? '') ? i.purity : null);
  add('Price', i.unit_price !== null ? <>{money(i.unit_price)} each</> : null);
  add('Payout', i.payout_on ? <>{money(i.payout_amount)} on {fmtDate(i.payout_on)}</> : null);
  add('Already invested before tracking', i.opening ? money(i.opening) : null);

  const gold = i.kind === 'gold';
  const valueSub = term
    ? 'Term cover has no value'
    : i.no_price
      ? gold ? 'No gold rate yet — shown at cost' : i.kind === 'mf' ? 'No NAV yet — shown at cost' : 'No price yet — shown at cost'
      : i.value_date
        ? `as of ${fmtDate(i.value_date)}`
        : undefined;

  return (
    <div className="content-wrap fade-in">
      <div className="page-head">
        <div style={{ display: 'flex', gap: 14, alignItems: 'center', minWidth: 0 }}>
          <CategoryGlyph icon={meta.icon} color={meta.color} size={46} />
          <div style={{ minWidth: 0 }}>
            <div className="muted" style={{ fontSize: 12.5 }}><Link href="/investments">Investments</Link> /</div>
            <h1 style={{ margin: 0 }}>{i.name}</h1>
            <p style={{ margin: 0 }}>{[meta.label, subtypeLabel(i.kind, i.subtype), i.person, i.institution].filter(Boolean).join(' · ')}</p>
          </div>
        </div>
        <div className="actions">
          <Button variant="ghost" icon="settings" onClick={() => setDlg('edit')}>Edit</Button>
          {active ? (
            <>
              {canValue && <Button variant="secondary" icon="refresh-cw" onClick={() => setDlg('value')}>{['stocks', 'crypto'].includes(i.kind) ? 'Update price' : 'Update value'}</Button>}
              {gold && <Button variant="secondary" icon="gem" onClick={() => setDlg('rates')}>Gold rate</Button>}
              {!term && <Button variant="secondary" icon="link" onClick={() => setDlg('link')}>Move past payments here</Button>}
              {!term && <Button variant="secondary" icon="arrow-down-to-line" onClick={() => setDlg('in')}>{i.kind === 'insurance' ? 'Record premium' : i.kind === 'chit' ? 'Record instalment' : 'Add money'}</Button>}
              {!term && <Button variant="secondary" icon="arrow-up-from-line" onClick={() => setDlg('out')}>{i.kind === 'lent' ? 'Repayment' : i.kind === 'chit' && !i.payout_on ? 'Take payout' : 'Take money out'}</Button>}
              <Button variant="primary" icon="circle-check" onClick={() => setDlg('close')}>
                {i.kind === 'lent' ? 'Mark repaid' : i.kind === 'mf' ? 'Mark redeemed' : ['stocks', 'crypto', 'gold', 'property'].includes(i.kind) ? 'Mark sold' : 'Mark closed'}
              </Button>
            </>
          ) : (
            <Button variant="secondary" icon="undo-2" onClick={reopen}>Reopen</Button>
          )}
        </div>
      </div>
      {msg && <div className="form-error" role="alert" style={{ marginBottom: 12 }}>{msg}</div>}
      {!active && (
        <div className="note" style={{ marginBottom: 16 }}>
          <Icon name="circle-check" size={15} />
          <span>Closed on {i.closed_on ? fmtDate(i.closed_on) : '—'}. It no longer counts in your net worth.</span>
        </div>
      )}
      {i.next_due?.overdue && active && i.next_due.what !== 'balance' && (
        <div className="note warn" style={{ marginBottom: 16 }}>
          <Icon name="triangle-alert" size={15} />
          <span>
            {dueWhen(i.next_due)} ({fmtDate(i.next_due.date)}). When the money is back in your bank, use “
            {i.kind === 'lent' ? 'Mark repaid' : 'Mark closed'}” and enter the amount received.
          </span>
        </div>
      )}
      {i.stale && active && (
        <div className="note warn" style={{ marginBottom: 16 }}>
          <Icon name="clock" size={15} />
          {i.kind === 'mf' ? (
            <span>
              The price (NAV) is from {i.value_date ? fmtDate(i.value_date) : 'a while ago'}. Prices come from AMFI every evening; if this stays
              old, AMFI may not list this fund under its ISIN ({i.fund?.isin ?? 'none'}).{' '}
              <Button variant="secondary" size="sm" onClick={updatePrices} disabled={busy}>{busy ? 'Getting prices…' : 'Update prices now'}</Button>
            </span>
          ) : (
            <span>
              The value is from {i.value_date ? fmtDate(i.value_date) : 'a while ago'} — over 90 days old.{' '}
              <Button variant="secondary" size="sm" onClick={() => setDlg(gold ? 'rates' : 'value')}>Update it</Button>
            </span>
          )}
        </div>
      )}

      <div className="grid-3 stat-grid">
        {i.owed > 0 ? (
          <StatCard lbl="Still to pay" icon="hand-coins" val={<Money amount={rs(i.owed)} compact />} accent="var(--red-600)" sub="Instalments left after the payout — taken off your net worth" />
        ) : (
          <StatCard lbl={active ? 'Value today' : 'Value'} icon="trending-up" val={term ? money(i.sum_assured) ?? '—' : <Money amount={rs(i.value)} compact />} sub={term ? 'Cover (sum assured) — not counted' : valueSub} />
        )}
        <StatCard
          lbl="Put in"
          icon="arrow-down-to-line"
          val={<Money amount={rs(i.money_in)} compact />}
          sub={
            i.paid_count !== null && i.total_count ? (
              <span style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <span>{i.paid_count} of {i.total_count} {i.kind === 'insurance' ? 'premiums' : 'instalments'} so far</span>
                <Progress value={i.paid_count} max={i.total_count} savings />
              </span>
            ) : i.money_out ? (
              <>Taken out <Money amount={rs(i.money_out)} interactive={false} /></>
            ) : undefined
          }
        />
        <StatCard
          lbl={active ? 'Gain' : 'Gain made'}
          icon="percent"
          val={term ? '—' : <GainText gain={i.gain} pct={i.gain_pct} />}
          sub={i.next_due && active ? `${dueWhen(i.next_due)} · ${fmtDate(i.next_due.date)}` : undefined}
        />
      </div>

      {facts.length > 0 && (
        <div className="card card-pad" style={{ marginBottom: 16, display: 'flex', gap: '10px 22px', flexWrap: 'wrap', fontSize: 13.5 }}>
          {facts.map(([k, v]) => (
            <span key={k}><span className="muted">{k} </span><b>{v}</b></span>
          ))}
        </div>
      )}
      {i.notes && <div className="card card-pad" style={{ marginBottom: 16, fontSize: 13.5, whiteSpace: 'pre-wrap' }}>{i.notes}</div>}

      {i.kind === 'property' && active && (
        <PropertySection
          inv={i}
          onPay={(amount) => {
            setPreset(amount);
            setDlg('in');
          }}
        />
      )}

      <div className="card">
        <div className="inv-group-head"><span>Money in and out</span></div>
        {i.moves.length === 0 ? (
          <div className="muted" style={{ padding: '6px 18px 18px', fontSize: 13.5 }}>
            {term
              ? 'Term insurance premiums are spending — record them as expenses.'
              : ['rd', 'insurance', 'chit'].includes(i.kind) || i.subtype === 'rd'
                ? 'Instalments are counted from the schedule. Record them from your bank here if you want your bank balance to show them.'
                : 'Nothing recorded from your bank yet.'}
          </div>
        ) : (
          <div style={{ padding: '0 8px 8px' }}>
            {i.moves.map((t) => <TxnRow key={t.id} t={t} onClick={() => openTxn(t)} />)}
          </div>
        )}
      </div>

      {i.fund_txns.length > 0 && (
        <div className="card" style={{ marginTop: 16 }}>
          <div className="inv-group-head"><span>From your CAS</span></div>
          <div className="tbl-wrap" style={{ padding: '0 6px 6px' }}>
            <table className="tbl" style={{ fontSize: 13 }}>
              <thead>
                <tr><th>Date</th><th>Transaction</th><th className="r">Amount</th><th className="r hide-sm">Units</th><th className="r hide-sm">NAV</th></tr>
              </thead>
              <tbody>
                {i.fund_txns.map((t) => (
                  <tr key={t.id}>
                    <td style={{ whiteSpace: 'nowrap' }}>{fmtDate(t.date)}</td>
                    <td><b>{t.kind_label}</b><div className="muted" style={{ fontSize: 12 }}>{t.description}</div></td>
                    <td className="r figure">{t.amount !== 0 ? money(Math.abs(t.amount)) : '—'}</td>
                    <td className="r t-mono hide-sm">{t.units.toLocaleString('en-IN', { minimumFractionDigits: 3, maximumFractionDigits: 3 })}</td>
                    <td className="r hide-sm">₹{t.nav.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {dlg === 'edit' && <InvestmentForm investment={i} onClose={() => setDlg(null)} />}
      {(dlg === 'in' || dlg === 'out') && (
        <MoveDialog
          inv={i}
          direction={dlg}
          amount={dlg === 'in' ? preset : undefined}
          onClose={() => {
            setDlg(null);
            setPreset(undefined);
          }}
        />
      )}
      {dlg === 'value' && <ValueDialog inv={i} onClose={() => setDlg(null)} />}
      {dlg === 'link' && <LinkDialog inv={i} onClose={() => setDlg(null)} />}
      {dlg === 'close' && <CloseDialog inv={i} onClose={() => setDlg(null)} />}
      {dlg === 'rates' && sum.data && <RatesDialog rates={sum.data.rates} onClose={() => setDlg(null)} />}
    </div>
  );
}

// ---------------------------------------------------------------- dialogs

function useBanks() {
  return useApi<Account[]>('/accounts?type=asset&type=cash&include_inactive=false');
}

function BankSelect({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  const banks = useBanks();
  return (
    <div className="field">
      <label htmlFor="mv-bank">{label}</label>
      <select id="mv-bank" className="inp" value={value} onChange={(e) => onChange(e.target.value)} required>
        <option value="">Choose…</option>
        {(banks.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
      </select>
    </div>
  );
}

function MoveDialog({ inv, direction, onClose, amount }: { inv: InvestmentDetail; direction: 'in' | 'out'; onClose: () => void; amount?: number }) {
  const title = direction === 'in' ? 'Put money in' : inv.kind === 'lent' ? 'Repayment received' : 'Take money out';
  return (
    <Dialog onClose={onClose} label={title} width={460}>
      <MoveBody inv={inv} direction={direction} title={title} preset={amount} />
    </Dialog>
  );
}

function MoveBody({ inv, direction, title, preset }: { inv: InvestmentDetail; direction: 'in' | 'out'; title: string; preset?: number }) {
  const close = useDialogClose();
  const { bump } = useShell();
  const suggested = preset ? paiseToInput(preset) : direction === 'in' && inv.instalment ? paiseToInput(inv.instalment) : '';
  const [amount, setAmount] = useState(suggested);
  const [date, setDate] = useState(todayIso());
  const [bank, setBank] = useState(inv.pay_from_id ? String(inv.pay_from_id) : '');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const p = toPaise(amount);
    if (!p || p <= 0) return setError('Enter the amount, e.g. 5000');
    setSaving(true);
    try {
      await api(`/investments/${inv.id}/move`, { method: 'POST', body: { direction, amount: p, date, bank_id: Number(bank) } });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };
  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead title={title} sub={inv.name} />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        <div className="row2">
          <div className="field">
            <label htmlFor="mv-amt">Amount (₹)</label>
            <input id="mv-amt" className="inp" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} required placeholder="0.00" />
          </div>
          <div className="field">
            <label htmlFor="mv-date">Date</label>
            <input id="mv-date" className="inp" type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
          </div>
        </div>
        <BankSelect value={bank} onChange={setBank} label={direction === 'in' ? 'From account' : 'Into account'} />
        <div className="hint">
          Recorded as a transfer {direction === 'in' ? 'from your bank to this investment' : 'from this investment to your bank'} — not
          {direction === 'in' ? ' spending' : ' income'}.
          {inv.kind === 'chit' && direction === 'out' && !inv.payout_on && ' This is the chit payout; the instalments left show as money you still owe.'}
        </div>
      </div>
      <div className="drawer-foot">
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        <Button variant="primary" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Record'}</Button>
      </div>
    </form>
  );
}

function ValueDialog({ inv, onClose }: { inv: InvestmentDetail; onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label="Update value" width={440}>
      <ValueBody inv={inv} />
    </Dialog>
  );
}

function ValueBody({ inv }: { inv: InvestmentDetail }) {
  const close = useDialogClose();
  const { bump } = useShell();
  const priced = inv.kind === 'stocks' || inv.kind === 'crypto';
  const current = priced ? inv.unit_price : inv.current_value;
  const [amount, setAmount] = useState(current != null ? paiseToInput(current) : '');
  const [date, setDate] = useState(todayIso());
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const label = priced
    ? `Price of one ${inv.kind === 'crypto' ? 'coin' : 'share'} today (₹)`
    : inv.kind === 'retirement'
      ? 'Balance (₹)'
      : inv.kind === 'insurance'
        ? 'Surrender value (₹)'
        : 'Value today (₹)';
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const p = toPaise(amount);
    if (p === null) return setError('Enter a number, e.g. 25000');
    setSaving(true);
    try {
      await api(`/investments/${inv.id}`, { method: 'PATCH', body: { [priced ? 'unit_price' : 'current_value']: p, value_date: date } });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };
  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead title={priced ? 'Update price' : 'Update value'} sub={inv.name} />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        <div className="row2">
          <div className="field">
            <label htmlFor="vl-amt">{label}</label>
            <input id="vl-amt" className="inp" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="vl-date">As of</label>
            <input id="vl-date" className="inp" type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
          </div>
        </div>
        {priced && inv.quantity !== null && (
          <div className="hint">{inv.quantity.toLocaleString('en-IN')} × this price = the value today.</div>
        )}
      </div>
      <div className="drawer-foot">
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        <Button variant="primary" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save'}</Button>
      </div>
    </form>
  );
}

function CloseDialog({ inv, onClose }: { inv: InvestmentDetail; onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label="Close investment" width={460}>
      <CloseBody inv={inv} />
    </Dialog>
  );
}

function CloseBody({ inv }: { inv: InvestmentDetail }) {
  const close = useDialogClose();
  const { bump } = useShell();
  const expected = inv.kind === 'chit' || inv.kind === 'insurance' && inv.subtype === 'term' ? null : inv.maturity_value ?? (inv.value > 0 ? inv.value : null);
  const [amount, setAmount] = useState(expected ? paiseToInput(expected) : '');
  const [date, setDate] = useState(inv.maturity_date && inv.maturity_date <= todayIso() ? inv.maturity_date : todayIso());
  const [bank, setBank] = useState(inv.pay_from_id ? String(inv.pay_from_id) : '');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    let p: number | null = null;
    if (amount.trim()) {
      p = toPaise(amount);
      if (!p || p <= 0) return setError('Enter the amount received, or leave it empty.');
      if (!bank) return setError('Choose the account the money went into.');
    }
    setSaving(true);
    try {
      await api(`/investments/${inv.id}/close`, { method: 'POST', body: { date, amount: p, bank_id: p ? Number(bank) : null } });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };
  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead title="Close" sub={inv.name} />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        <div className="row2">
          <div className="field">
            <label htmlFor="cl-amt">Money received (₹) <span className="muted" style={{ fontWeight: 400 }}>(optional)</span></label>
            <input id="cl-amt" className="inp" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" />
          </div>
          <div className="field">
            <label htmlFor="cl-date">Date</label>
            <input id="cl-date" className="inp" type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
          </div>
        </div>
        {amount.trim() && <BankSelect value={bank} onChange={setBank} label="Into account" />}
        <div className="hint">
          The money received is a transfer to your bank. Leave it empty if it&apos;s already recorded. Once closed, this
          investment no longer counts in your net worth; you can reopen it.
        </div>
      </div>
      <div className="drawer-foot">
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        <Button variant="primary" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Close it'}</Button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------- move past payments here

function LinkDialog({ inv, onClose }: { inv: InvestmentDetail; onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label="Move past payments here" width={640}>
      <LinkBody inv={inv} />
    </Dialog>
  );
}

function LinkBody({ inv }: { inv: InvestmentDetail }) {
  const close = useDialogClose();
  const { bump } = useShell();
  const { data, error: loadError } = useApi<InvestmentLinkable[]>(`/investments/${inv.id}/linkable`);
  const [picked, setPicked] = useState<Set<number> | null>(null); // null = the suggested ones
  const [lower, setLower] = useState(inv.opening > 0);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const rows = data ?? [];
  const chosen = picked ?? new Set(rows.filter((r) => r.suggested).map((r) => r.transaction_id));
  const toggle = (id: number) => {
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setPicked(next);
  };
  const putIn = rows.filter((r) => chosen.has(r.transaction_id)).reduce((s, r) => s + (r.direction === 'in' ? r.amount : -r.amount), 0);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!chosen.size) return setError('Tick the payments to move.');
    setSaving(true);
    try {
      await api(`/investments/${inv.id}/link`, { method: 'POST', body: { ids: [...chosen], lower_opening: lower && inv.opening > 0 } });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };
  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead title="Move past payments here" sub={inv.name} />
      <div className="drawer-body">
        {(error || loadError) && <div className="form-error" role="alert">{error || loadError}</div>}
        <div className="hint" style={{ marginBottom: 12 }}>
          Payments from your bank statements that look like money into this investment (or back from it). The ones you tick become
          transfers — they stop counting as spending or income. Ticked: the description has its name, number or kind
          {inv.instalment ? ' and the amount fits' : ''}.
        </div>
        {!data ? (
          <Skeleton variant="block" height={120} />
        ) : rows.length === 0 ? (
          <div className="muted" style={{ fontSize: 13.5, padding: '12px 0' }}>
            No payment looks like this investment. To move one anyway, open it in Transactions and change it to a transfer to “{inv.name}”.
          </div>
        ) : (
          <div className="card" style={{ marginBottom: 14 }}>
            {rows.map((r) => (
              <label key={r.transaction_id} className="inv-link-row">
                <input type="checkbox" checked={chosen.has(r.transaction_id)} onChange={() => toggle(r.transaction_id)} />
                <span className="mid">
                  <span className="nm">{r.description}</span>
                  <span className="muted">
                    {fmtDate(r.date)} · {r.direction === 'in' ? `from ${r.account}` : `into ${r.account}`}
                    {r.category ? ` · ${r.category}` : ''}
                    {r.why ? ` · ${r.why}` : ''}
                  </span>
                </span>
                <span className="figure" style={{ color: r.direction === 'out' ? 'var(--mint-700)' : undefined }}>
                  {r.direction === 'out' ? '+' : ''}{money(r.amount)}
                </span>
              </label>
            ))}
          </div>
        )}
        {inv.opening > 0 && rows.length > 0 && (
          <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 13.5 }}>
            <input type="checkbox" checked={lower} onChange={(e) => setLower(e.target.checked)} style={{ marginTop: 3 }} />
            <span>
              These payments are part of the {money(inv.opening)} you entered as already invested — take them off it, so they don&apos;t count
              twice.
            </span>
          </label>
        )}
      </div>
      <div className="drawer-foot">
        <span className="muted" style={{ fontSize: 13 }}>{chosen.size} ticked{putIn ? <> · {money(Math.abs(putIn))} {putIn > 0 ? 'in' : 'out'}</> : null}</span>
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        <Button variant="primary" type="submit" disabled={saving || !chosen.size}>{saving ? 'Moving…' : 'Move them here'}</Button>
      </div>
    </form>
  );
}
