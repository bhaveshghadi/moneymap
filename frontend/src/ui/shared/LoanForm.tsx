'use client';
import { useState, type FormEvent, type ReactNode } from 'react';
import { useRouter } from 'next/navigation';
import type { Account, Category, LoanCountMode, LoanDetail, LoanFirstInterest, LoanInterestBasis, LoanKind, LoanLinkable, LoanMethod, LoanStatementResult } from '../lib/types';
import { api, qs } from '../lib/api';
import { fmtDate, inr, paiseToInput, rs, toPaise, todayIso } from '../lib/format';
import { useApi, useShell } from '../contexts/ShellCtx';
import { useMask } from '../contexts/MaskCtx';
import { Dialog, useDialogClose } from '../primitives/Dialog';
import { Button } from '../primitives/Button';
import { Money } from '../primitives/Money';
import { SegmentedControl } from '../primitives/SegmentedControl';
import { Icon } from '../primitives/Icon';
import { DrawerHead } from './DrawerHead';
import { CategoryOptions } from './CategoryOptions';
import { CheckNote, StatementEvents, applyEvents, initialPicks, type EventPick } from './LoanStatement';
import { useStay } from '../contexts/StayCtx';

export const LOAN_KINDS: { value: LoanKind; label: string }[] = [
  { value: 'home', label: 'Home loan' },
  { value: 'car', label: 'Car loan' },
  { value: 'two_wheeler', label: 'Two-wheeler loan' },
  { value: 'personal', label: 'Personal loan' },
  { value: 'education', label: 'Education loan' },
  { value: 'gold', label: 'Gold loan' },
  { value: 'property', label: 'Loan against property' },
  { value: 'consumer', label: 'Consumer / product loan' },
  { value: 'other', label: 'Other loan' },
];

export function kindLabel(k: string): string {
  return LOAN_KINDS.find((x) => x.value === k)?.label ?? 'Loan';
}

export const METHOD_LABEL: Record<LoanMethod, string> = {
  reducing: 'Reducing balance',
  flat: 'Flat rate',
  emi_only: 'EMI only',
};

export const COUNT_LABEL: Record<LoanCountMode, string> = {
  whole_emi: 'Whole EMI counts as spending',
  interest_only: 'Only the interest counts as spending',
};

export const INTEREST_BASIS_LABEL: Record<LoanInterestBasis, string> = {
  month: '1/12 of the yearly rate (usual)',
  days365: 'Actual days in the month — 365-day year',
};

export const FIRST_INTEREST_LABEL: Record<LoanFirstInterest, string> = {
  month: 'One month’s interest (usual)',
  days365: 'Days since taken on — 365-day year',
  days360: 'Days since taken on — 360-day year',
};

/** Same formulas as the server (loans/maths.py), for the live preview only. */
function roundRupee(paise: number): number {
  return Math.round(paise / 100) * 100;
}

export function daysBetween(fromIso: string, toIso: string): number {
  return Math.round((Date.parse(toIso) - Date.parse(fromIso)) / 86_400_000);
}

/** EMI 1's interest counted by days from the loan being paid out (maths.first_emi_interest); null = a normal month. */
export function firstEmiInterest(principal: number, rateBp: number, firstEmi: string, takenOn: string, mode: LoanFirstInterest): number | null {
  if (mode === 'month' || !takenOn || !firstEmi || !principal || takenOn >= firstEmi) return null;
  const den = 10_000 * (mode === 'days365' ? 365 : 360);
  return Math.floor((principal * rateBp * daysBetween(takenOn, firstEmi) + den / 2) / den);
}

export function calcEmi(principal: number, rateBp: number, months: number, firstInterest: number | null = null): number {
  if (months <= 0 || principal <= 0) return 0;
  if (rateBp === 0) return roundRupee(principal / months);
  const r = rateBp / 120_000;
  if (firstInterest !== null && months > 1) {
    const annuity = (1 - Math.pow(1 + r, -(months - 1))) / r;
    return roundRupee((principal + firstInterest) / (1 + annuity));
  }
  const f = Math.pow(1 + r, months);
  return roundRupee((principal * r * f) / (f - 1));
}
export function flatEmi(principal: number, rateBp: number, months: number): number {
  if (months <= 0 || principal <= 0) return 0;
  return roundRupee((principal + (principal * rateBp * months) / 120_000) / months);
}

export interface SchedulePreview {
  months: number; // EMIs actually needed
  totalInterest: number;
  totalPayable: number;
  lastEmi: number;
}

/** Days from the EMI before to EMI n+1 (0-based n), the first EMI on `first` (YYYY-MM-DD). */
function periodDays(first: string, n: number): number {
  const [y, m, d] = first.split('-').map(Number);
  const due = (k: number) => {
    const last = new Date(Date.UTC(y, m - 1 + k + 1, 0)).getUTCDate(); // days in that month
    return Date.UTC(y, m - 1 + k, Math.min(d, last));
  };
  return Math.round((due(n) - due(n - 1)) / 86_400_000);
}

/** Walk the reducing-balance schedule like maths.build (null if the EMI doesn't cover the interest). */
export function reducingPreview(
  principal: number,
  rateBp: number,
  emi: number,
  months: number,
  firstInterest: number | null,
  daily: { first: string } | null = null, // each month's interest on its actual days (365-day year)
): SchedulePreview | null {
  let balance = principal;
  let totalInterest = 0;
  let totalPayable = 0;
  let lastEmi = 0;
  let n = 0;
  while (balance > 0 && n < Math.min(months, 600)) {
    const interest =
      n === 0 && firstInterest !== null
        ? firstInterest
        : daily
          ? Math.floor((balance * rateBp * periodDays(daily.first, n) + 1_825_000) / 3_650_000)
          : Math.floor((balance * rateBp + 60_000) / 120_000);
    const last = n === months - 1;
    let prin = emi - interest;
    if (prin <= 0 && !last) return null;
    if (last || prin >= balance) prin = balance;
    balance -= prin;
    totalInterest += interest;
    lastEmi = prin + interest;
    totalPayable += lastEmi;
    n += 1;
  }
  return { months: n, totalInterest, totalPayable, lastEmi };
}

export function LoanForm({ onClose }: { onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label="Add loan" width={600}>
      <LoanFormBody />
    </Dialog>
  );
}

const FIELD_NAMES: Record<string, string> = {
  principal: 'loan amount',
  rate: 'interest rate',
  tenure: 'number of EMIs',
  emi: 'EMI',
  first_emi_date: 'first EMI date',
  loan_number: 'loan number',
  lender: 'lender',
};

/** The form's starting values: empty, or filled in from a loan statement. */
function startValues(st?: LoanStatementResult) {
  const v = <T,>(k: keyof LoanStatementResult['fields']) => (st?.fields[k]?.value ?? null) as T | null;
  const kind = (v<string>('kind') ?? 'personal') as LoanKind;
  const lender = v<string>('lender') ?? '';
  const first = v<string>('first_emi_date') ?? '';
  const paid = v<number>('emis_paid');
  const money = (k: keyof LoanStatementResult['fields']) => {
    const p = v<number>(k);
    return p ? paiseToInput(p) : '';
  };
  return {
    name: st ? [lender, kindLabel(kind).toLowerCase()].filter(Boolean).join(' ') : '',
    lender,
    kind,
    loanNumber: (v<string>('loan_number') ?? '').slice(-32),
    method: (v<string>('method') ?? 'reducing') as LoanMethod,
    countMode: 'whole_emi' as LoanCountMode,
    principal: money('principal'),
    rate: v<number>('rate') !== null ? String(v<number>('rate')) : '',
    tenure: v<number>('tenure') !== null ? String(v<number>('tenure')) : '',
    emi: money('emi'),
    firstEmi: first,
    disbursed: v<string>('disbursed_date') ?? '',
    firstInterest: (v<string>('first_interest') ?? 'month') as LoanFirstInterest,
    interestBasis: (v<string>('interest_basis') ?? 'month') as LoanInterestBasis,
    payFrom: '',
    start: (st && ((paid ?? 0) > 0 || (first && first <= todayIso())) ? 'existing' : 'new') as 'new' | 'existing',
    money: 'none' as 'received' | 'seller' | 'none',
    receivedInto: '',
    charges: '',
    seller: '',
    categoryId: '',
    paidBefore: paid !== null ? String(paid) : '',
    notes: '',
  };
}

export function LoanFormBody({ initial, banner }: { initial?: LoanStatementResult; banner?: ReactNode } = {}) {
  const close = useDialogClose();
  const router = useRouter();
  const stay = useStay();
  const { bump } = useShell();
  const { masked } = useMask();
  const banks = useApi<Account[]>('/accounts?type=asset&type=cash&include_inactive=false');
  const categories = useApi<Category[]>('/categories');
  const [f, setF] = useState(() => startValues(initial));
  const [picks, setPicks] = useState<EventPick[]>(() => initialPicks(initial?.events ?? []));
  const [picked, setPicked] = useState<Record<number, boolean> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [createdId, setCreatedId] = useState<number | null>(null);
  /** "from statement" / "worked out" next to a label filled in from the statement. */
  const tag = (k: keyof LoanStatementResult['fields']) => {
    const src = initial?.fields[k]?.source;
    if (!src) return null;
    return <span className={`ls-tag ${src}`}>{src === 'statement' ? 'from statement' : 'worked out'}</span>;
  };
  const missing = initial
    ? (['principal', 'rate', 'tenure', 'emi', 'first_emi_date'] as const).filter((k) => !initial.fields[k]).map((k) => FIELD_NAMES[k])
    : [];
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((p) => ({ ...p, [k]: v }));
  const money = (p: number) => (masked ? '₹•••' : inr(rs(p)));

  const principal = toPaise(f.principal) ?? 0;
  const rateBp = f.rate ? Math.round(Number(f.rate) * 100) : 0;
  const tenure = Number(f.tenure) || 0;
  const ownEmi = f.emi ? toPaise(f.emi) ?? 0 : 0;
  const bpi = f.method === 'reducing' ? firstEmiInterest(principal, rateBp, f.firstEmi, f.disbursed, f.firstInterest) : null;
  const bpiDays = bpi !== null ? daysBetween(f.disbursed, f.firstEmi) : 0;
  const workedEmi = f.method === 'reducing' ? calcEmi(principal, rateBp, tenure, bpi) : f.method === 'flat' ? flatEmi(principal, rateBp, tenure) : 0;
  const emi = ownEmi || workedEmi;
  // the same totals the loan page will show (reducing: the schedule walked month by month)
  let preview: SchedulePreview | null = null;
  if (f.method === 'reducing') {
    if (principal && emi && tenure)
      preview = reducingPreview(principal, rateBp, emi, tenure, bpi, f.interestBasis === 'days365' && f.firstEmi ? { first: f.firstEmi } : null);
  } else if (f.method === 'flat') {
    if (principal && tenure) {
      // an EMI you enter (the lender's) sets the total, like maths.build_flat
      const own = ownEmi && ownEmi !== flatEmi(principal, rateBp, tenure) && ownEmi * tenure >= principal;
      const interest = own ? ownEmi * tenure - principal : Math.round((principal * rateBp * tenure) / 120_000);
      preview = { months: tenure, totalInterest: interest, totalPayable: principal + interest, lastEmi: 0 };
    }
  } else if (emi && tenure) {
    preview = { months: tenure, totalInterest: principal ? Math.max(0, emi * tenure - principal) : 0, totalPayable: emi * tenure, lastEmi: 0 };
  }
  const lastDiffers = preview !== null && preview.lastEmi > 0 && Math.abs(preview.lastEmi - emi) >= 100_00;

  // past EMI expenses to move onto the loan (once the EMI is known)
  const candidates = useApi<LoanLinkable[]>(
    f.start === 'existing' && emi > 0 ? `/loans/candidates${qs({ emi, loan_number: f.loanNumber || undefined, lender: f.lender || undefined })}` : null,
  );
  const isPicked = (c: LoanLinkable) => (picked && c.transaction_id in picked ? picked[c.transaction_id] : c.suggested);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!f.name.trim()) return setError('Give the loan a name, e.g. "HDFC home loan".');
    if (!tenure) return setError('Enter the number of EMIs (months).');
    if (!f.firstEmi) return setError('Enter the date of the first EMI.');
    if (f.method !== 'emi_only' && (!principal || !f.rate)) return setError('Enter the loan amount and the interest rate.');
    if (f.method === 'emi_only' && !ownEmi) return setError('Enter the EMI.');
    if (f.method === 'reducing' && f.firstInterest !== 'month' && !f.disbursed) return setError('Enter the date the loan was taken on — the first EMI’s interest is counted from it.');
    if (f.start === 'new' && f.money === 'received' && !f.receivedInto) return setError('Choose the account the loan money came into.');
    const charges = f.start === 'new' && f.money === 'received' && f.charges ? toPaise(f.charges) : null;
    if (charges !== null && (charges < 0 || (principal > 0 && charges >= principal))) return setError('The charges must be less than the loan amount.');
    const link_ids = f.start === 'existing' ? (candidates.data ?? []).filter((c) => c.emi_like && isPicked(c)).map((c) => c.transaction_id) : [];
    const body = {
      name: f.name.trim(),
      lender: f.lender || null,
      kind: f.kind,
      loan_number: f.loanNumber || null,
      method: f.method,
      count_mode: f.countMode,
      principal: principal || null,
      rate: f.rate ? Number(f.rate) : null,
      tenure,
      emi: ownEmi || null,
      first_emi_date: f.firstEmi,
      disbursed_date: f.disbursed || null,
      first_interest: f.method === 'reducing' ? f.firstInterest : 'month',
      interest_basis: f.method === 'reducing' ? f.interestBasis : 'month',
      pay_from_id: f.payFrom ? Number(f.payFrom) : null,
      start: f.start,
      money: f.start === 'new' ? f.money : 'none',
      received_into_id: f.money === 'received' && f.receivedInto ? Number(f.receivedInto) : null,
      charges: charges || null,
      seller_name: f.seller || null,
      category_id: f.categoryId ? Number(f.categoryId) : null,
      paid_before: f.start === 'existing' && f.paidBefore ? Number(f.paidBefore) : null,
      link_ids,
      notes: f.notes || null,
    };
    setSaving(true);
    let id: number | null = null;
    try {
      const res = await api<LoanDetail>('/loans', { method: 'POST', body });
      id = res.id;
      if (initial) await applyEvents(res.id, initial.events, picks); // ticked part-payments / rate changes
      bump();
      close();
      if (!stay) router.push(`/loans/${res.id}`);
    } catch (err) {
      if (id !== null) {
        bump();
        setCreatedId(id);
        setError(`The loan was added, but a part-payment or rate change couldn’t be recorded: ${(err as Error).message} Add it on the loan page.`);
      } else {
        setError((err as Error).message);
      }
      setSaving(false);
    }
  };

  const bankOptions = (banks.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>);

  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead
        title={initial ? 'Add loan from statement' : 'Add loan'}
        sub={initial ? initial.filename : 'Amounts are in ₹'}
        lead={<span className="ico" style={{ background: 'var(--coral-50)', color: 'var(--coral-600)' }}><Icon name={initial ? 'file-search' : 'hand-coins'} size={20} /></span>}
      />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        {initial && (
          <>
            {banner}
            <div className="note info" style={{ marginBottom: 12 }}>
              <Icon name="file-check" size={15} />
              <span>
                Filled in from the statement — check each value. Ones marked <i>worked out</i> come from the repayment schedule or the other figures.
                {missing.length > 0 && <> <b>Not found:</b> {missing.join(', ')} — fill {missing.length === 1 ? 'it' : 'them'} in.</>}
              </span>
            </div>
            <CheckNote result={initial} />
          </>
        )}
        <div className="row2">
          <div className="field">
            <label htmlFor="ln-name">Name</label>
            <input id="ln-name" className="inp" value={f.name} onChange={(e) => set('name', e.target.value)} maxLength={120} placeholder="e.g. HDFC home loan" />
          </div>
          <div className="field">
            <label htmlFor="ln-kind">Type {tag('kind')}</label>
            <select id="ln-kind" className="inp" value={f.kind} onChange={(e) => set('kind', e.target.value as LoanKind)}>
              {LOAN_KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
            </select>
          </div>
        </div>
        <div className="row2">
          <div className="field">
            <label htmlFor="ln-lender">Lender {tag('lender')}</label>
            <input id="ln-lender" className="inp" value={f.lender} onChange={(e) => set('lender', e.target.value)} maxLength={120} placeholder="e.g. HDFC Bank" />
          </div>
          <div className="field">
            <label htmlFor="ln-no">Loan account number (or last digits) {tag('loan_number')}</label>
            <input id="ln-no" className="inp" value={f.loanNumber} onChange={(e) => set('loanNumber', e.target.value)} maxLength={32} placeholder="helps match EMIs in bank statements" />
          </div>
        </div>

        <div className="card card-pad" style={{ background: 'var(--bg-subtle)', marginBottom: 14 }}>
          <div style={{ fontWeight: 650, marginBottom: 8 }}>Repayment</div>
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
            <div className="hint">
              {f.method === 'reducing'
                ? 'Most bank loans (home, car, personal): interest on what is still owed each month.'
                : f.method === 'flat'
                  ? 'Interest on the full amount for the whole term, spread evenly (some consumer, two-wheeler and gold loans).'
                  : 'You know the EMI and the number of months. Add the amount too and the interest rate is worked out.'}
            </div>
          </div>
          <div className="row2">
            <div className="field">
              <label htmlFor="ln-amt">Loan amount (₹){f.method === 'emi_only' ? ' — optional' : ''} {tag('principal')}</label>
              <input id="ln-amt" className="inp" inputMode="decimal" value={f.principal} onChange={(e) => set('principal', e.target.value)} placeholder="e.g. 500000" />
            </div>
            {f.method !== 'emi_only' ? (
              <div className="field">
                <label htmlFor="ln-rate">Interest % a year{f.method === 'flat' ? ' (flat)' : ''} {tag('rate')}</label>
                <input id="ln-rate" className="inp" inputMode="decimal" value={f.rate} onChange={(e) => set('rate', e.target.value)} placeholder="e.g. 10.5" />
              </div>
            ) : (
              <div className="field">
                <label htmlFor="ln-emi">EMI (₹) {tag('emi')}</label>
                <input id="ln-emi" className="inp" inputMode="decimal" value={f.emi} onChange={(e) => set('emi', e.target.value)} placeholder="e.g. 13462" />
              </div>
            )}
          </div>
          <div className="row2">
            <div className="field">
              <label htmlFor="ln-ten">Number of EMIs (months) {tag('tenure')}</label>
              <input id="ln-ten" className="inp" inputMode="numeric" value={f.tenure} onChange={(e) => set('tenure', e.target.value.replace(/\D/g, ''))} placeholder="e.g. 60" />
            </div>
            <div className="field">
              <label htmlFor="ln-first">First EMI date {tag('first_emi_date')}</label>
              <input id="ln-first" className="inp" type="date" value={f.firstEmi} onChange={(e) => set('firstEmi', e.target.value)} />
            </div>
          </div>
          {f.method === 'reducing' && (
            <div className="row2">
              <div className="field">
                <label htmlFor="ln-taken">Loan taken on (paid out) — optional {tag('disbursed_date')}</label>
                <input id="ln-taken" className="inp" type="date" value={f.disbursed} onChange={(e) => set('disbursed', e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="ln-firstint">Interest in the first EMI {tag('first_interest')}</label>
                <select id="ln-firstint" className="inp" value={f.firstInterest} onChange={(e) => set('firstInterest', e.target.value as LoanFirstInterest)}>
                  {(Object.keys(FIRST_INTEREST_LABEL) as LoanFirstInterest[]).map((k) => <option key={k} value={k}>{FIRST_INTEREST_LABEL[k]}</option>)}
                </select>
              </div>
            </div>
          )}
          {f.method === 'reducing' && (
            <div className="field">
              <label htmlFor="ln-basis">Interest each month {tag('interest_basis')}</label>
              <select id="ln-basis" className="inp" value={f.interestBasis} onChange={(e) => set('interestBasis', e.target.value as LoanInterestBasis)}>
                {(Object.keys(INTEREST_BASIS_LABEL) as LoanInterestBasis[]).map((k) => <option key={k} value={k}>{INTEREST_BASIS_LABEL[k]}</option>)}
              </select>
              <div className="hint">Most lenders charge 1/12 of the yearly rate. Some (e.g. Bandhan) count the actual days, so February costs less than March — read it from the lender&apos;s schedule.</div>
            </div>
          )}
          {f.method === 'reducing' && f.firstInterest !== 'month' && (
            <div className="hint" style={{ marginTop: -6, marginBottom: 10 }}>
              Many lenders charge the first EMI the interest for the actual days from the loan being paid out to the first EMI — check the first row of the lender’s schedule.
            </div>
          )}
          {f.method !== 'emi_only' && (
            <div className="field">
              <label htmlFor="ln-emi2">EMI as the lender charges it (₹) — optional {tag('emi')}</label>
              <input id="ln-emi2" className="inp" inputMode="decimal" value={f.emi} onChange={(e) => set('emi', e.target.value)} placeholder={workedEmi ? `worked out: ${money(workedEmi)}` : 'worked out from the above'} />
            </div>
          )}
          {f.method === 'reducing' && principal > 0 && emi > 0 && tenure > 0 && preview === null && (
            <div className="note warn" aria-live="polite">
              <span>That EMI doesn’t cover the monthly interest — check the EMI and the interest rate.</span>
            </div>
          )}
          {preview !== null && (
            <div className="note info" aria-live="polite">
              <span>
                EMI <b><Money amount={rs(emi)} interactive={false} /></b>
                {preview.months !== tenure ? ` for ${preview.months} months` : ` × ${tenure}`}
                {lastDiffers && <> (last one <Money amount={rs(preview.lastEmi)} interactive={false} />)</>}: <Money amount={rs(preview.totalPayable)} interactive={false} /> to pay back
                {principal ? <> — <Money amount={rs(preview.totalInterest)} interactive={false} /> of it interest</> : null}.
                {bpi !== null && <> The first EMI carries <Money amount={rs(bpi)} interactive={false} /> interest for {bpiDays} days.</>}
              </span>
            </div>
          )}
        </div>

        <div className="field">
          <label>How should it count as spending?</label>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {(['whole_emi', 'interest_only'] as LoanCountMode[]).map((m) => (
              <label key={m} className="card card-pad" style={{ display: 'flex', gap: 10, alignItems: 'flex-start', padding: 12, cursor: 'pointer', borderColor: f.countMode === m ? 'var(--brand)' : undefined }}>
                <input type="radio" name="ln-count" checked={f.countMode === m} onChange={() => set('countMode', m)} style={{ marginTop: 3 }} />
                <span>
                  <b>{COUNT_LABEL[m]}</b>
                  <span className="muted" style={{ display: 'block', fontSize: 12.5 }}>
                    {m === 'whole_emi'
                      ? 'Each EMI is one expense ("Loan / EMI"). Best when you don’t record what the loan paid for — a home or car loan paid to the seller, a product loan, an older loan.'
                      : 'Each EMI is split: the principal part is paying back (a transfer to the loan), only the interest is an expense. Best when the loan money came into your bank and you record what you spent it on.'}
                  </span>
                </span>
              </label>
            ))}
          </div>
          {f.countMode === 'whole_emi' && f.start === 'new' && f.money === 'received' && (
            <div className="note warn" style={{ marginTop: 8 }}>
              <span>The loan money comes into your bank and every EMI counts as spending — if you also record what you spend that money on, it counts twice. “Only the interest” avoids that.</span>
            </div>
          )}
        </div>

        <div className="field">
          <label>Is this loan new or already running?</label>
          <SegmentedControl
            aria-label="New or running"
            value={f.start}
            onChange={(v) => set('start', v as 'new' | 'existing')}
            options={[
              { value: 'new', label: 'New loan' },
              { value: 'existing', label: 'Already running' },
            ]}
          />
        </div>

        {f.start === 'new' ? (
          <div className="field">
            <label htmlFor="ln-money">The loan money</label>
            <select id="ln-money" className="inp" value={f.money} onChange={(e) => set('money', e.target.value as typeof f.money)}>
              <option value="received">Came into my bank account</option>
              <option value="seller">Was paid straight to the seller / builder / dealer</option>
              <option value="none">Don’t record it</option>
            </select>
            {f.money === 'received' && (
              <div className="row2" style={{ marginTop: 8 }}>
                <select className="inp" aria-label="Came into" value={f.receivedInto} onChange={(e) => set('receivedInto', e.target.value)}>
                  <option value="">Into which account?</option>
                  {bankOptions}
                </select>
                {f.method === 'reducing' ? (
                  <span className="muted" style={{ alignSelf: 'center', fontSize: 12.5 }}>On the “taken on” date above</span>
                ) : (
                  <input className="inp" type="date" aria-label="Received on" value={f.disbursed} onChange={(e) => set('disbursed', e.target.value)} />
                )}
              </div>
            )}
            {f.money === 'received' && (
              <div style={{ marginTop: 8 }}>
                <input
                  className="inp"
                  inputMode="decimal"
                  aria-label="Charges deducted by the lender"
                  placeholder="Charges deducted by the lender (₹, optional)"
                  value={f.charges}
                  onChange={(e) => set('charges', e.target.value)}
                />
                <div className="hint">
                  {principal > 0 && f.charges && (toPaise(f.charges) ?? 0) > 0 && (toPaise(f.charges) ?? 0) < principal ? (
                    <>
                      {money(principal - (toPaise(f.charges) ?? 0))} reaches your bank; {money(toPaise(f.charges) ?? 0)}{' '}is recorded as a
                      “Bank Charges &amp; Fees” expense. You still owe the full {money(principal)}.
                    </>
                  ) : (
                    'Processing fee, GST, insurance … that the lender kept: the loan amount minus what reached your bank.'
                  )}
                </div>
              </div>
            )}
            {f.money === 'seller' && f.countMode === 'interest_only' && (
              <div className="row2" style={{ marginTop: 8 }}>
                <input className="inp" aria-label="Paid to" value={f.seller} onChange={(e) => set('seller', e.target.value)} placeholder="Paid to (e.g. the builder)" />
                <select className="inp" aria-label="Category" value={f.categoryId} onChange={(e) => set('categoryId', e.target.value)}>
                  <option value="">Category of the purchase…</option>
                  <CategoryOptions categories={categories.data ?? []} kind="expense" />
                </select>
              </div>
            )}
            <div className="hint">
              {f.money === 'received'
                ? 'Recorded as a transfer from the loan into that account — not income.'
                : f.money === 'seller'
                  ? f.countMode === 'interest_only'
                    ? 'The purchase is recorded once, in full, as spending.'
                    : 'Nothing is recorded now — the spending comes month by month as whole EMIs.'
                  : 'Only the EMIs are recorded.'}
            </div>
          </div>
        ) : (
          <div className="field">
            <label htmlFor="ln-paid">EMIs already paid {tag('emis_paid')}</label>
            <input id="ln-paid" className="inp" inputMode="numeric" value={f.paidBefore} onChange={(e) => set('paidBefore', e.target.value.replace(/\D/g, ''))} placeholder="empty = every EMI dated before today" />
            {candidates.data && candidates.data.length > 0 && (
              <div style={{ marginTop: 10 }}>
                <div style={{ fontWeight: 600, fontSize: 13.5, marginBottom: 6 }}>Past EMI payments to move onto this loan</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 220, overflowY: 'auto' }}>
                  {candidates.data.map((c) => (
                    <label key={c.transaction_id} style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13, opacity: c.emi_like ? 1 : 0.55 }}>
                      <input
                        type="checkbox"
                        disabled={!c.emi_like}
                        checked={c.emi_like && isPicked(c)}
                        onChange={(e) => setPicked((p) => ({ ...(p ?? {}), [c.transaction_id]: e.target.checked }))}
                      />
                      <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={c.description}>
                        {fmtDate(c.date)} · {c.description}
                      </span>
                      <Money amount={rs(c.amount)} interactive={false} />
                    </label>
                  ))}
                </div>
                <div className="hint">Only payments of the EMI amount can be moved here; part-payments go on the loan page.</div>
              </div>
            )}
          </div>
        )}

        {initial && initial.events.length > 0 && (
          <StatementEvents
            events={initial.events}
            picks={picks}
            onChange={(i, p) => setPicks((all) => all.map((x, j) => (j === i ? { ...x, ...p } : x)))}
            canChange={f.method === 'reducing' || (f.method === 'emi_only' && principal > 0)}
          />
        )}

        <div className="field">
          <label htmlFor="ln-from">EMI is paid from</label>
          <select id="ln-from" className="inp" value={f.payFrom} onChange={(e) => set('payFrom', e.target.value)}>
            <option value="">Choose an account…</option>
            {bankOptions}
          </select>
        </div>
      </div>
      <div className="drawer-foot">
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        {createdId !== null ? (
          <Button variant="primary" onClick={() => { close(); router.push(`/loans/${createdId}`); }}>Open the loan</Button>
        ) : (
          <Button variant="primary" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Add loan'}</Button>
        )}
      </div>
    </form>
  );
}
