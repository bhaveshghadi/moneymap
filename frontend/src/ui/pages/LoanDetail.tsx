'use client';
import { useState, type FormEvent } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { api, qs } from '../lib/api';
import { useApi, useShell } from '../contexts/ShellCtx';
import type { Account, LoanCountMode, LoanDetail, LoanFirstInterest, LoanKind, LoanLinkable, LoanMethod } from '../lib/types';
import { dueText, fmtDate, paiseToInput, rs, toPaise, todayIso } from '../lib/format';
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
import { COUNT_LABEL, FIRST_INTEREST_LABEL, LOAN_KINDS, METHOD_LABEL, kindLabel } from '../shared/LoanForm';
import { LoanChangesList, PrepayDialog, RateDialog } from '../shared/LoanChanges';
import { LoanStatementDialog } from '../shared/LoanStatement';
import { SegmentedControl } from '../primitives/SegmentedControl';

export function LoanDetailPage({ id }: { id: number }) {
  const { data, error, reload } = useApi<LoanDetail>(`/loans/${id}`);
  const { bump } = useShell();
  const [editing, setEditing] = useState(false);
  const [linking, setLinking] = useState(false);
  const [prepaying, setPrepaying] = useState(false);
  const [rating, setRating] = useState(false);
  const [fromStatement, setFromStatement] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  if (error) return <div className="content-wrap"><div className="card"><ErrorState message={error} onRetry={reload} /></div></div>;
  if (!data) return <div className="content-wrap"><Skeleton variant="block" height={120} /><div style={{ height: 16 }} /><Skeleton variant="block" height={300} /></div>;

  const l = data;
  const borrowed = l.principal ?? l.total_payable;
  const record = async () => {
    setBusy(true);
    setMsg(null);
    try {
      await api(`/loans/${l.id}/pay`, { method: 'POST', body: { date: l.next && l.next.date > todayIso() ? todayIso() : undefined } });
      bump();
    } catch (e) {
      setMsg((e as Error).message);
    }
    setBusy(false);
  };
  const applyFirstInterest = async (mode: LoanFirstInterest) => {
    setBusy(true);
    setMsg(null);
    try {
      await api(`/loans/${l.id}`, { method: 'PATCH', body: { first_interest: mode } }); // keeps the EMI
      bump();
    } catch (e) {
      setMsg((e as Error).message);
    }
    setBusy(false);
  };
  const lastEmi = l.schedule.length ? l.schedule[l.schedule.length - 1].emi : 0;
  // the schedule around the next EMI (all rows on request)
  const nextIdx = l.next ? l.schedule.findIndex((r) => r.n === l.next!.n) : l.schedule.length;
  const rows = showAll ? l.schedule : l.schedule.slice(Math.max(0, nextIdx - 3), nextIdx + 9);

  return (
    <div className="content-wrap fade-in">
      <div className="page-head">
        <div style={{ display: 'flex', gap: 14, alignItems: 'center', minWidth: 0 }}>
          <CategoryGlyph icon="hand-coins" color="coral" size={46} />
          <div style={{ minWidth: 0 }}>
            <div className="muted" style={{ fontSize: 12.5 }}><Link href="/loans">Loans</Link> /</div>
            <h1 style={{ margin: 0 }}>{l.name}</h1>
            <p style={{ margin: 0 }}>
              {[kindLabel(l.kind), l.lender, l.loan_number ? `No. ${l.loan_number}` : null].filter(Boolean).join(' · ')}
            </p>
          </div>
        </div>
        <div className="actions">
          <Button variant="ghost" icon="settings" onClick={() => setEditing(true)}>Edit</Button>
          <Button variant="secondary" icon="link" onClick={() => setLinking(true)}>Move past EMIs</Button>
          <Button variant="ghost" icon="file-search" onClick={() => setFromStatement(true)}>Update from statement</Button>
          {l.supports_changes && l.status === 'active' && (
            <>
              <Button variant="secondary" icon="piggy-bank" onClick={() => setPrepaying(true)}>Part-payment</Button>
              <Button variant="ghost" icon="percent" onClick={() => setRating(true)}>Rate change</Button>
            </>
          )}
          {l.next && (
            <Button variant="primary" icon="check" onClick={record} disabled={busy || !l.pay_from_id} title={l.pay_from_id ? undefined : 'Set “EMI is paid from” in Edit first'}>
              {busy ? 'Recording…' : `Record EMI ${l.next.n}`}
            </Button>
          )}
        </div>
      </div>
      {msg && <div className="form-error" role="alert" style={{ marginBottom: 12 }}>{msg}</div>}
      {l.next?.overdue && (
        <div className="note warn" style={{ marginBottom: 16 }}>
          <Icon name="triangle-alert" size={15} />
          <span>
            EMI {l.next.n} was due on <b>{fmtDate(l.next.date)}</b> and isn&apos;t recorded yet. Record it, or move the payment
            from your bank statement onto this loan with “Move past EMIs”.
          </span>
        </div>
      )}

      <div className="grid-3 stat-grid">
        <StatCard
          lbl="Left to pay"
          icon="hand-coins"
          val={<Money amount={rs(l.outstanding)} compact />}
          sub={
            <span style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span>{l.paid_count} of {l.tenure} EMIs paid · ends {fmtDate(l.end_date)}</span>
              <Progress value={borrowed - l.outstanding} max={borrowed} savings />
            </span>
          }
        />
        <StatCard
          lbl="Next EMI"
          icon="calendar-clock"
          val={l.next ? <Money amount={rs(l.next.emi)} compact /> : '—'}
          accent={l.next?.overdue ? 'var(--red-600)' : undefined}
          sub={
            l.next ? (
              <>
                {fmtDate(l.next.date)} · {dueText(l.next.date)}
                {l.next.interest > 0 && (
                  <> · <Money amount={rs(l.next.principal)} interactive={false} /> principal + <Money amount={rs(l.next.interest)} interactive={false} /> interest</>
                )}
              </>
            ) : (
              'All EMIs paid'
            )
          }
        />
        <StatCard
          lbl="Interest"
          icon="percent"
          val={<Money amount={rs(l.interest_paid)} compact />}
          sub={
            <>
              paid so far, of <Money amount={rs(l.total_interest)} interactive={false} /> over the loan
              {l.current_rate !== null && ` · ${l.current_rate}% a year${l.rate_worked_out ? ' (worked out)' : ''}`}
            </>
          }
        />
      </div>

      <div className="card card-pad" style={{ marginBottom: 16, display: 'flex', gap: 22, flexWrap: 'wrap', fontSize: 13.5 }}>
        <span><span className="muted">Borrowed </span><b>{l.principal ? <Money amount={rs(l.principal)} interactive={false} /> : '—'}</b></span>
        <span>
          <span className="muted">EMI </span><b><Money amount={rs(l.current_emi)} interactive={false} /></b>
          {l.current_emi !== l.emi && <span className="muted"> (was <Money amount={rs(l.emi)} interactive={false} />)</span>}
        </span>
        {l.prepaid > 0 && <span><span className="muted">Part-payments </span><b><Money amount={rs(l.prepaid)} interactive={false} /></b></span>}
        <span><span className="muted">Total to pay back </span><b><Money amount={rs(l.total_payable)} interactive={false} /></b></span>
        <span><span className="muted">Repayment </span>{METHOD_LABEL[l.method]}</span>
        {l.first_interest_days !== null && (
          <span>
            <span className="muted">First EMI interest </span>
            {l.first_interest_days} days ({l.first_interest === 'days360' ? '360' : '365'}-day year)
          </span>
        )}
        <span><span className="muted">Spending </span>{COUNT_LABEL[l.count_mode]}</span>
        <span><span className="muted">Paid from </span>{l.pay_from_name ?? <i>not set</i>}</span>
        <Link href={`/transactions${qs({ loan: l.loan_id })}`}>See its transactions</Link>
      </div>

      {l.last_emi_off && (
        <div className="note warn" style={{ marginBottom: 16 }}>
          <span>
            The last EMI comes out at <b><Money amount={rs(lastEmi)} interactive={false} /></b>, not <Money amount={rs(l.emi)} interactive={false} /> — the lender
            probably charges the first EMI the interest for the actual days since the loan was paid out.{' '}
            {l.first_interest_suggestion ? (
              <>
                With “{FIRST_INTEREST_LABEL[l.first_interest_suggestion]}” it fits.{' '}
                <Button variant="secondary" size="sm" onClick={() => applyFirstInterest(l.first_interest_suggestion!)} disabled={busy}>
                  Use it
                </Button>
              </>
            ) : (
              <>Add the date the loan was taken on and choose how the first EMI’s interest is counted (Edit).</>
            )}
          </span>
        </div>
      )}

      <LoanChangesList loan={l} />

      <div className="card">
        <div style={{ padding: '16px 18px 0', display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', alignItems: 'baseline' }}>
          <div>
            <div style={{ fontFamily: 'var(--font-display)', fontWeight: 650, fontSize: 16 }}>Repayment schedule</div>
            <div className="muted" style={{ fontSize: 12.5 }}>
              {l.method === 'emi_only' && !l.principal
                ? 'Only the EMI is known, so there is no principal / interest split.'
                : 'Each EMI pays that month’s interest first; the rest reduces what you owe.'}
            </div>
          </div>
          <Button variant="ghost" size="sm" onClick={() => setShowAll((v) => !v)}>{showAll ? 'Show around the next EMI' : `Show all ${l.schedule.length}`}</Button>
        </div>
        <div className="tbl-wrap" style={{ padding: '10px 6px 6px' }}>
          <table className="tbl">
            <thead>
              <tr>
                <th>#</th>
                <th>Date</th>
                <th className="r">EMI</th>
                <th className="r hide-sm">Principal</th>
                <th className="r hide-sm">Interest</th>
                <th className="r">Left after</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => [
                ...l.events
                  .filter((ev) => ev.before_n === r.n)
                  .map((ev) => (
                    <tr key={`ev${ev.id}`}>
                      <td colSpan={7} className="muted" style={{ fontSize: 12.5 }}>
                        ↳ {fmtDate(ev.date)}: {ev.kind === 'prepay' ? `part-payment ₹${((ev.amount ?? 0) / 100).toLocaleString('en-IN')}` : `rate ${ev.rate}%`}
                        {ev.emi_after ? ` — EMI from here ₹${(ev.emi_after / 100).toLocaleString('en-IN')}` : ''}
                      </td>
                    </tr>
                  )),
                <tr key={r.n} style={r.n === l.next?.n ? { background: 'var(--bg-subtle)' } : undefined}>
                  <td>{r.n}</td>
                  <td>{fmtDate(r.date)}</td>
                  <td className="r figure"><Money amount={rs(r.emi)} interactive={false} /></td>
                  <td className="r figure hide-sm"><Money amount={rs(r.principal)} interactive={false} /></td>
                  <td className="r figure hide-sm"><Money amount={rs(r.interest)} interactive={false} /></td>
                  <td className="r figure"><Money amount={rs(r.balance)} interactive={false} /></td>
                  <td>
                    {r.paid ? <span className="badge mint">Paid</span> : r.n === l.next?.n ? <span className={`badge ${l.next.overdue ? 'red' : 'cau'}`}>{l.next.overdue ? 'Overdue' : 'Next'}</span> : null}
                  </td>
                </tr>,
              ])}
            </tbody>
          </table>
        </div>
      </div>

      {editing && <EditLoan loan={l} onClose={() => setEditing(false)} />}
      {linking && <LinkPast loan={l} onClose={() => setLinking(false)} />}
      {prepaying && <PrepayDialog loan={l} onClose={() => setPrepaying(false)} />}
      {fromStatement && <LoanStatementDialog accountId={l.id} onClose={() => setFromStatement(false)} />}
      {rating && <RateDialog loan={l} onClose={() => setRating(false)} />}
    </div>
  );
}

function EditLoan({ loan, onClose }: { loan: LoanDetail; onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label={`Loan: ${loan.name}`} width={520}>
      <EditBody loan={loan} />
    </Dialog>
  );
}

function EditBody({ loan }: { loan: LoanDetail }) {
  const close = useDialogClose();
  const router = useRouter();
  const { bump } = useShell();
  const banks = useApi<Account[]>('/accounts?type=asset&type=cash&include_inactive=false');
  const [f, setF] = useState({
    name: loan.name,
    lender: loan.lender ?? '',
    kind: loan.kind,
    loanNumber: loan.loan_number ?? '',
    payFrom: loan.pay_from_id ? String(loan.pay_from_id) : '',
    notes: loan.notes ?? '',
    closed: !!loan.closed_on,
    method: loan.method,
    countMode: loan.count_mode,
    principal: loan.principal ? paiseToInput(loan.principal) : '',
    rate: loan.method === 'emi_only' ? '' : loan.rate !== null ? String(loan.rate) : '',
    tenure: String(loan.tenure),
    emi: paiseToInput(loan.emi),
    firstEmi: loan.first_emi_date,
    disbursed: loan.disbursed_date ?? '',
    firstInterest: loan.first_interest,
    paidBefore: String(loan.paid_before),
  });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((p) => ({ ...p, [k]: v }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const body: Record<string, unknown> = {
      name: f.name,
      lender: f.lender || null,
      kind: f.kind,
      loan_number: f.loanNumber || null,
      pay_from_id: f.payFrom ? Number(f.payFrom) : null,
      notes: f.notes || null,
      closed_on: f.closed ? loan.closed_on ?? todayIso() : null,
    };
    // only the terms you changed are sent (the EMI is worked out again unless you change it yourself)
    const principal = f.principal ? toPaise(f.principal) : null;
    const emi = toPaise(f.emi);
    if (f.method !== loan.method) body.method = f.method;
    if (principal !== loan.principal) body.principal = principal;
    if (f.method !== 'emi_only' && f.rate !== (loan.rate !== null ? String(loan.rate) : '')) body.rate = f.rate ? Number(f.rate) : null;
    if (Number(f.tenure) !== loan.tenure) body.tenure = Number(f.tenure);
    if (f.firstEmi !== loan.first_emi_date) body.first_emi_date = f.firstEmi;
    if (f.disbursed !== (loan.disbursed_date ?? '')) body.disbursed_date = f.disbursed || null;
    if (f.firstInterest !== loan.first_interest) body.first_interest = f.firstInterest;
    if (f.method === 'reducing' && f.firstInterest !== 'month' && !f.disbursed) {
      return setError('Enter the date the loan was taken on — the first EMI’s interest is counted from it.');
    }
    if (emi !== loan.emi) body.emi = emi;
    else if (['method', 'principal', 'rate', 'tenure'].some((k) => k in body) && f.method !== 'emi_only') body.emi = null;
    if (Number(f.paidBefore) !== loan.paid_before) body.paid_before = Number(f.paidBefore) || 0;
    if (f.countMode !== loan.count_mode) body.count_mode = f.countMode;
    setSaving(true);
    try {
      await api(`/loans/${loan.id}`, { method: 'PATCH', body });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };
  const remove = async () => {
    if (!confirmDelete) return setConfirmDelete(true);
    setSaving(true);
    try {
      await api(`/loans/${loan.id}`, { method: 'DELETE' });
      bump();
      close();
      router.push('/loans');
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
      setConfirmDelete(false);
    }
  };

  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead title={loan.name} sub={`${METHOD_LABEL[loan.method]} · ${COUNT_LABEL[loan.count_mode]}`} lead={<CategoryGlyph icon="hand-coins" color="coral" size={42} />} />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        <div className="row2">
          <div className="field">
            <label htmlFor="le-name">Name</label>
            <input id="le-name" className="inp" value={f.name} onChange={(e) => set('name', e.target.value)} required maxLength={120} />
          </div>
          <div className="field">
            <label htmlFor="le-kind">Type</label>
            <select id="le-kind" className="inp" value={f.kind} onChange={(e) => set('kind', e.target.value as LoanKind)}>
              {LOAN_KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
            </select>
          </div>
        </div>
        <div className="row2">
          <div className="field">
            <label htmlFor="le-lender">Lender</label>
            <input id="le-lender" className="inp" value={f.lender} onChange={(e) => set('lender', e.target.value)} maxLength={120} />
          </div>
          <div className="field">
            <label htmlFor="le-no">Loan account number</label>
            <input id="le-no" className="inp" value={f.loanNumber} onChange={(e) => set('loanNumber', e.target.value)} maxLength={32} />
          </div>
        </div>
        <div className="field">
          <label htmlFor="le-from">EMI is paid from</label>
          <select id="le-from" className="inp" value={f.payFrom} onChange={(e) => set('payFrom', e.target.value)}>
            <option value="">Choose an account…</option>
            {(banks.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </div>
        <div className="card card-pad" style={{ background: 'var(--bg-subtle)', marginBottom: 14 }}>
          <div style={{ fontWeight: 650, marginBottom: 8 }}>Terms</div>
          <div className="field">
            <SegmentedControl
              aria-label="Repayment type"
              value={f.method}
              onChange={(v) => set('method', v as LoanMethod)}
              options={[
                { value: 'reducing', label: 'Reducing balance' },
                { value: 'flat', label: 'Flat rate' },
                { value: 'emi_only', label: 'EMI only' },
              ]}
            />
          </div>
          <div className="row2">
            <div className="field">
              <label htmlFor="le-amt">Loan amount (₹)</label>
              <input id="le-amt" className="inp" inputMode="decimal" value={f.principal} onChange={(e) => set('principal', e.target.value)} />
            </div>
            {f.method !== 'emi_only' ? (
              <div className="field">
                <label htmlFor="le-rate">Interest % a year (at the start)</label>
                <input id="le-rate" className="inp" inputMode="decimal" value={f.rate} onChange={(e) => set('rate', e.target.value)} />
              </div>
            ) : (
              <div className="field">
                <label htmlFor="le-emi1">EMI (₹)</label>
                <input id="le-emi1" className="inp" inputMode="decimal" value={f.emi} onChange={(e) => set('emi', e.target.value)} />
              </div>
            )}
          </div>
          <div className="row2">
            <div className="field">
              <label htmlFor="le-ten">Number of EMIs</label>
              <input id="le-ten" className="inp" inputMode="numeric" value={f.tenure} onChange={(e) => set('tenure', e.target.value.replace(/\D/g, ''))} />
            </div>
            <div className="field">
              <label htmlFor="le-first">First EMI date</label>
              <input id="le-first" className="inp" type="date" value={f.firstEmi} onChange={(e) => set('firstEmi', e.target.value)} />
            </div>
          </div>
          {f.method === 'reducing' && (
            <div className="row2">
              <div className="field">
                <label htmlFor="le-taken">Loan taken on (paid out)</label>
                <input id="le-taken" className="inp" type="date" value={f.disbursed} onChange={(e) => set('disbursed', e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="le-firstint">Interest in the first EMI</label>
                <select id="le-firstint" className="inp" value={f.firstInterest} onChange={(e) => set('firstInterest', e.target.value as LoanFirstInterest)}>
                  {(Object.keys(FIRST_INTEREST_LABEL) as LoanFirstInterest[]).map((k) => <option key={k} value={k}>{FIRST_INTEREST_LABEL[k]}</option>)}
                </select>
              </div>
            </div>
          )}
          <div className="row2">
            {f.method !== 'emi_only' && (
              <div className="field">
                <label htmlFor="le-emi">EMI (₹)</label>
                <input id="le-emi" className="inp" inputMode="decimal" value={f.emi} onChange={(e) => set('emi', e.target.value)} />
                <div className="hint">Change the amount, rate or months and the EMI is worked out again — unless you change it here.</div>
              </div>
            )}
            <div className="field">
              <label htmlFor="le-paid">EMIs paid before tracking</label>
              <input id="le-paid" className="inp" inputMode="numeric" value={f.paidBefore} onChange={(e) => set('paidBefore', e.target.value.replace(/\D/g, ''))} />
            </div>
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>How it counts as spending</label>
            <SegmentedControl
              aria-label="How it counts as spending"
              value={f.countMode}
              onChange={(v) => set('countMode', v as LoanCountMode)}
              options={[
                { value: 'whole_emi', label: 'Whole EMI' },
                { value: 'interest_only', label: 'Only the interest' },
              ]}
            />
            {f.countMode !== loan.count_mode && (
              <div className="hint">The EMIs already recorded are re-recorded the new way (split into principal + interest, or merged back).</div>
            )}
          </div>
        </div>
        <div className="field">
          <label htmlFor="le-notes">Notes</label>
          <textarea id="le-notes" className="inp" rows={2} value={f.notes} onChange={(e) => set('notes', e.target.value)} />
        </div>
        <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 14 }}>
          <input type="checkbox" checked={f.closed} onChange={(e) => set('closed', e.target.checked)} />
          This loan is closed (paid off)
        </label>
        <div className="hint" style={{ marginTop: 8 }}>
          For a part-payment or a floating-rate change, use those buttons on the loan page instead — they keep the EMIs already paid as they were.
        </div>
      </div>
      <div className="drawer-foot">
        <Button variant={confirmDelete ? 'primary' : 'ghost'} icon="trash-2" onClick={remove} disabled={saving} className={confirmDelete ? 'btn-danger' : ''}>
          {confirmDelete ? 'Confirm delete' : 'Delete'}
        </Button>
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        <Button variant="primary" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save'}</Button>
      </div>
    </form>
  );
}

function LinkPast({ loan, onClose }: { loan: LoanDetail; onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label="Move past EMIs" width={600}>
      <LinkBody loan={loan} />
    </Dialog>
  );
}

function LinkBody({ loan }: { loan: LoanDetail }) {
  const close = useDialogClose();
  const { bump } = useShell();
  const { data } = useApi<LoanLinkable[]>(`/loans/${loan.id}/linkable`);
  const [picked, setPicked] = useState<Record<number, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const on = (c: LoanLinkable) => (c.transaction_id in picked ? picked[c.transaction_id] : c.suggested);
  const chosen = (data ?? []).filter((c) => c.emi_like && on(c));

  const submit = async () => {
    setSaving(true);
    setError(null);
    try {
      await api(`/loans/${loan.id}/link`, { method: 'POST', body: { transaction_ids: chosen.map((c) => c.transaction_id) } });
      bump();
      close();
    } catch (e) {
      setError((e as Error).message);
      setSaving(false);
    }
  };

  return (
    <>
      <DrawerHead title="Move past EMIs onto this loan" sub={`EMI ₹${(loan.emi / 100).toLocaleString('en-IN')} · ${COUNT_LABEL[loan.count_mode]}`} />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        <p className="muted" style={{ marginTop: 0, fontSize: 13.5 }}>
          {loan.count_mode === 'whole_emi'
            ? 'Each payment stays an expense of the full EMI (category “Loan / EMI”), now linked to this loan and its schedule.'
            : 'Each payment is split as in the schedule: the principal becomes a transfer to the loan (paying back), the interest an expense.'}
        </p>
        {!data ? (
          <Skeleton variant="row" count={4} />
        ) : data.length === 0 ? (
          <div className="muted">No expenses look like this loan&apos;s EMI (the “Loan / EMI” category, the loan number or lender, or the EMI amount).</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {data.map((c) => (
              <label key={c.transaction_id} style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13.5, opacity: c.emi_like ? 1 : 0.55 }}>
                <input type="checkbox" disabled={!c.emi_like} checked={c.emi_like && on(c)} onChange={(e) => setPicked((p) => ({ ...p, [c.transaction_id]: e.target.checked }))} />
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={c.description}>{c.description}</span>
                  <span className="muted" style={{ fontSize: 12 }}>
                    {fmtDate(c.date)} · from {c.paid_from}{c.category ? ` · ${c.category}` : ''}{!c.emi_like ? ' · not the EMI amount (part-payment?)' : ''}
                  </span>
                </span>
                <Money amount={rs(c.amount)} interactive={false} />
              </label>
            ))}
          </div>
        )}
        <div className="hint" style={{ marginTop: 10 }}>Part-payments (other amounts) can be recorded in the next step.</div>
      </div>
      <div className="drawer-foot">
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        <Button variant="primary" onClick={submit} disabled={saving || chosen.length === 0}>
          {saving ? 'Moving…' : `Move ${chosen.length} EMI${chosen.length === 1 ? '' : 's'}`}
        </Button>
      </div>
    </>
  );
}
