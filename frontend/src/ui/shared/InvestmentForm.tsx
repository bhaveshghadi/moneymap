'use client';
import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '../lib/api';
import { useApi, useShell } from '../contexts/ShellCtx';
import type { Account, Investment, InvestmentDetail, InvestmentDue, InvestmentKind, PropertyStatus, Scheme } from '../lib/types';
import { fmtDate, fmtNav, paiseToInput, toPaise, todayIso } from '../lib/format';
import { Dialog, useDialogClose } from '../primitives/Dialog';
import { Button } from '../primitives/Button';
import { CategoryGlyph } from '../primitives/CategoryGlyph';
import { SegmentedControl } from '../primitives/SegmentedControl';
import { DrawerHead } from './DrawerHead';
import { useStay } from '../contexts/StayCtx';

// ---------------------------------------------------------------- labels shared by the pages

export const KIND_META: Record<InvestmentKind, { label: string; icon: string; color: string; blurb: string }> = {
  mf: { label: 'Mutual fund', icon: 'chart-pie', color: 'mint', blurb: 'Units × the latest NAV, updated every evening' },
  fd: { label: 'Fixed deposit', icon: 'landmark', color: 'indigo', blurb: 'Bank FD — interest worked out to today' },
  rd: { label: 'Recurring deposit', icon: 'repeat', color: 'blue', blurb: 'A fixed amount every month' },
  post_office: { label: 'Post Office', icon: 'mailbox', color: 'coral', blurb: 'NSC, KVP, SCSS, MIS, TD, RD' },
  retirement: { label: 'PPF / EPF / NPS', icon: 'sprout', color: 'mint', blurb: 'Also Sukanya Samriddhi — enter the balance' },
  insurance: { label: 'Insurance', icon: 'shield-check', color: 'purple', blurb: 'LIC, endowment, money-back, ULIP, term' },
  lent: { label: 'Money lent', icon: 'handshake', color: 'amber', blurb: 'To family or friends, with or without interest' },
  chit: { label: 'Chit fund', icon: 'users', color: 'blue', blurb: 'Monthly instalments and the payout' },
  gold: { label: 'Gold & silver', icon: 'gem', color: 'amber', blurb: 'Jewellery, coins, SGB, digital gold, silver' },
  stocks: { label: 'Stocks & shares', icon: 'chart-candlestick', color: 'indigo', blurb: 'Shares, ETFs, ESOPs, RSUs, startup shares' },
  crypto: { label: 'Crypto', icon: 'bitcoin', color: 'amber', blurb: 'Coins — you enter the price' },
  property: { label: 'Property', icon: 'house', color: 'slate', blurb: 'Land, flat, shop — your estimate' },
  bond: { label: 'Bond', icon: 'scroll-text', color: 'blue', blurb: 'NCDs and bonds from Wint, GoldenPi, Grip, RBI …' },
  other: { label: 'Other', icon: 'package', color: 'slate', blurb: 'Anything else you own' },
};
export const KIND_ORDER = Object.keys(KIND_META) as InvestmentKind[];

export const SUBTYPES: Partial<Record<InvestmentKind, [string, string][]>> = {
  post_office: [['nsc', 'NSC'], ['kvp', 'KVP'], ['scss', 'SCSS'], ['mis', 'Monthly Income (MIS)'], ['td', 'Time Deposit'], ['rd', 'Recurring Deposit']],
  retirement: [['ppf', 'PPF'], ['epf', 'EPF'], ['nps', 'NPS'], ['ssy', 'Sukanya Samriddhi']],
  insurance: [['endowment', 'Endowment / LIC'], ['money_back', 'Money-back'], ['ulip', 'ULIP'], ['term', 'Term insurance']],
  gold: [['jewellery', 'Jewellery'], ['coin', 'Coins / bars'], ['sgb', 'Sovereign Gold Bond'], ['digital', 'Digital gold'], ['silver', 'Silver']],
  stocks: [['stock', 'Shares'], ['etf', 'ETF'], ['esop', 'ESOP'], ['rsu', 'RSU'], ['startup', 'Startup shares']],
  bond: [['ncd', 'Corporate bond / NCD'], ['govt', 'Government (G-Sec, SDL, T-bill)'], ['tax_free', 'Tax-free bond'], ['rbi_frb', 'RBI Floating Rate Bond'], ['securitised', 'Securitised debt']],
};
export const subtypeLabel = (kind: InvestmentKind, sub: string | null): string | null =>
  sub ? (SUBTYPES[kind]?.find(([v]) => v === sub)?.[1] ?? sub) : null;

export const COMPOUNDING_LABEL: Record<string, string> = {
  monthly: 'Monthly',
  quarterly: 'Quarterly',
  half_yearly: 'Half-yearly',
  yearly: 'Yearly',
  payout: 'Interest paid out',
  simple: 'Simple interest',
};
export const FREQUENCY_LABEL: Record<string, string> = {
  monthly: 'Monthly',
  quarterly: 'Quarterly',
  half_yearly: 'Half-yearly',
  yearly: 'Yearly',
  single: 'Single premium',
};
export const DUE_LABEL: Record<InvestmentDue['what'], string> = {
  matures: 'Matures',
  premium: 'Premium due',
  due_back: 'Due back',
  instalment: 'Chit instalment',
  payout: 'Bond payout',
  balance: 'Payment due',
};
export const BOND_FREQUENCY_LABEL: Record<string, string> = {
  monthly: 'Monthly',
  quarterly: 'Quarterly',
  half_yearly: 'Half-yearly',
  yearly: 'Yearly',
  single: 'All at maturity',
};
export const REPAYMENT_LABEL: Record<string, string> = {
  bullet: 'All at maturity (interest only until then)',
  amortising: 'Part with every payout (principal + interest)',
};
const PO_COMPOUNDING: Record<string, string> = { nsc: 'yearly', kvp: 'yearly', td: 'quarterly', rd: 'quarterly', scss: 'payout', mis: 'payout' };

const isSchedule = (kind: InvestmentKind, sub: string) => kind === 'rd' || kind === 'insurance' || kind === 'chit' || (kind === 'post_office' && sub === 'rd');

type Key =
  | 'institution' | 'number' | 'person' | 'amount' | 'instalment' | 'rate' | 'compounding' | 'frequency' | 'start'
  | 'maturity' | 'months' | 'years' | 'sum_assured' | 'maturity_amount' | 'quantity' | 'purity' | 'unit_price'
  | 'current_value' | 'value_date' | 'payout_on' | 'payout_amount' | 'platform' | 'rating' | 'face_value' | 'repayment';

/** The fields each kind asks for, in order. */
function fieldsFor(kind: InvestmentKind, sub: string, editing: boolean): Key[] {
  switch (kind) {
    case 'mf':
      return ['number', 'quantity', 'amount', 'start'];
    case 'fd':
      return ['institution', 'number', 'amount', 'rate', 'compounding', 'start', 'maturity', 'maturity_amount'];
    case 'rd':
      return ['institution', 'number', 'instalment', 'rate', 'start', 'months', 'maturity_amount'];
    case 'post_office':
      return sub === 'rd'
        ? ['number', 'instalment', 'rate', 'start', 'months', 'maturity_amount']
        : ['number', 'amount', 'rate', 'start', 'maturity', 'maturity_amount'];
    case 'retirement':
      return ['number', 'current_value', 'value_date', 'amount'];
    case 'insurance':
      return sub === 'term'
        ? ['institution', 'number', 'instalment', 'frequency', 'start', 'years', 'sum_assured']
        : ['institution', 'number', 'instalment', 'frequency', 'start', 'years', 'maturity', 'sum_assured', 'maturity_amount', 'current_value'];
    case 'lent':
      return ['person', 'amount', 'start', 'rate', 'maturity'];
    case 'chit':
      return editing
        ? ['institution', 'instalment', 'months', 'start', 'payout_on', 'payout_amount']
        : ['institution', 'instalment', 'months', 'start'];
    case 'gold':
      return sub === 'sgb'
        ? ['quantity', 'amount', 'start', 'maturity']
        : sub === 'digital'
          ? ['institution', 'quantity', 'amount', 'start']
          : ['quantity', 'purity', 'amount', 'start'];
    case 'stocks':
      return ['institution', 'quantity', 'amount', 'start', 'unit_price'];
    case 'crypto':
      return ['institution', 'quantity', 'amount', 'start', 'unit_price'];
    case 'property':
      return ['institution', 'amount', 'start', 'current_value'];
    case 'bond':
      return ['institution', 'number', 'platform', 'rating', 'quantity', 'face_value', 'amount', 'rate', 'frequency', 'repayment', 'start', 'maturity'];
    default:
      return ['institution', 'amount', 'start', 'current_value'];
  }
}

function labelFor(k: Key, kind: InvestmentKind, sub: string): string {
  const L: Record<Key, string> = {
    institution:
      kind === 'bond' ? 'Issuer' : kind === 'insurance' ? 'Insurer' : kind === 'chit' ? 'Organiser' : kind === 'property' ? 'Place' : kind === 'stocks' || kind === 'crypto' ? 'Broker / exchange' : kind === 'gold' ? 'App / provider' : kind === 'other' ? 'Where' : 'Bank',
    number:
      kind === 'bond' ? 'ISIN' : kind === 'mf' ? 'Folio number' : kind === 'insurance' ? 'Policy number' : sub === 'epf' ? 'UAN' : sub === 'nps' ? 'PRAN' : kind === 'retirement' || kind === 'post_office' ? 'Account / certificate no.' : kind === 'fd' ? 'FD number' : 'Account number',
    person: 'Lent to',
    amount:
      kind === 'bond' ? 'Amount paid (₹)' : kind === 'lent' ? 'Amount lent (₹)' : kind === 'mf' ? 'Put in (₹)' : kind === 'retirement' ? 'Put in so far (₹)' : kind === 'property' ? 'Paid so far (₹)' : ['gold', 'stocks', 'crypto'].includes(kind) ? 'Bought for (₹)' : 'Amount (₹)',
    instalment: kind === 'insurance' ? 'Premium (₹)' : 'Every month (₹)',
    rate: kind === 'lent' ? 'Interest % a year' : kind === 'bond' ? 'Coupon rate (% a year)' : 'Interest rate (% a year)',
    compounding: 'Interest added',
    frequency: kind === 'bond' ? 'Pays interest' : 'Premium paid',
    start: kind === 'bond' ? 'Bought on' : kind === 'mf' ? 'Invested since' : kind === 'lent' ? 'Lent on' : kind === 'insurance' ? 'Policy start / first premium' : ['gold', 'stocks', 'crypto', 'property'].includes(kind) ? 'Bought on' : 'Start date',
    maturity: kind === 'lent' ? 'Due back on' : 'Maturity date',
    months: 'Months',
    years: 'Premium-paying years',
    sum_assured: 'Sum assured (₹)',
    maturity_amount: 'Maturity amount (₹)',
    quantity: kind === 'mf' || kind === 'bond' ? 'Units' : kind === 'gold' ? (sub === 'sgb' ? 'Units (1 unit = 1 gram)' : 'Grams') : kind === 'crypto' ? 'Coins' : 'Quantity (shares / units)',
    purity: 'Purity',
    unit_price: kind === 'crypto' ? 'Price of one coin today (₹)' : 'Price of one share today (₹)',
    current_value: kind === 'retirement' ? 'Balance (₹)' : kind === 'insurance' ? 'Surrender value today (₹)' : 'Value today (₹)',
    value_date: 'Balance as of',
    payout_on: 'Payout taken on',
    payout_amount: 'Payout received (₹)',
    platform: 'Bought through (app / broker)',
    rating: 'Credit rating',
    face_value: 'Face value of one unit (₹) — if you know it',
    repayment: 'Principal comes back',
  };
  return L[k];
}

const OPTIONAL: Key[] = ['platform', 'rating', 'face_value', 'institution', 'number', 'maturity_amount', 'sum_assured', 'current_value', 'unit_price', 'value_date', 'payout_on', 'payout_amount'];
const MONEY: Key[] = ['face_value', 'amount', 'instalment', 'sum_assured', 'maturity_amount', 'unit_price', 'current_value', 'payout_amount'];

type Values = Record<Key, string>;

const BOND_PLACEHOLDER: Partial<Record<Key, string>> = {
  institution: 'e.g. the NBFC / company',
  number: 'e.g. INE…',
  platform: 'e.g. Wint',
  rating: 'e.g. A+ (CRISIL)',
  face_value: 'blank = amount paid ÷ units',
  rate: 'e.g. 10.5',
  amount: 'incl. any accrued interest you paid',
};

function initial(inv?: Investment): Values {
  const m = (v: number | null | undefined) => (v != null ? paiseToInput(v) : '');
  return {
    institution: inv?.institution ?? '',
    number: inv?.number ?? '',
    person: inv?.person ?? '',
    amount: inv && inv.opening ? paiseToInput(inv.opening) : '',
    instalment: m(inv?.instalment),
    rate: inv?.rate != null ? String(inv.rate) : '',
    compounding: inv?.compounding ?? 'quarterly',
    frequency: inv?.frequency ?? 'yearly',
    start: inv?.start_date ?? '',
    maturity: inv?.maturity_date ?? '',
    months: inv?.months != null ? String(inv.months) : '',
    years: inv?.months != null ? String(inv.months / 12) : '',
    sum_assured: m(inv?.sum_assured),
    maturity_amount: m(inv?.maturity_amount),
    quantity: inv?.fund ? String(inv.fund.units) : inv?.quantity != null ? String(inv.quantity) : '',
    purity: inv?.purity ?? '',
    unit_price: m(inv?.unit_price),
    current_value: m(inv?.current_value),
    value_date: inv?.value_date ?? '',
    payout_on: inv?.payout_on ?? '',
    payout_amount: m(inv?.payout_amount),
    platform: inv?.platform ?? '',
    rating: inv?.rating ?? '',
    face_value: m(inv?.face_value),
    repayment: inv?.repayment ?? 'bullet',
  };
}

// ---------------------------------------------------------------- the form

export function InvestmentForm({
  investment,
  onClose,
  onImportCas,
}: {
  investment?: InvestmentDetail;
  onClose: () => void;
  onImportCas?: () => void;
}) {
  return (
    <Dialog onClose={onClose} label={investment ? `Investment: ${investment.name}` : 'Add investment'} width={580}>
      <Body investment={investment} onImportCas={onImportCas} />
    </Dialog>
  );
}

function Body({ investment, onImportCas }: { investment?: InvestmentDetail; onImportCas?: () => void }) {
  const close = useDialogClose();
  const router = useRouter();
  const stay = useStay();
  const { bump } = useShell();
  const banks = useApi<Account[]>('/accounts?type=asset&type=cash&include_inactive=false');
  const editing = !!investment;
  const [kind, setKind] = useState<InvestmentKind | null>(investment?.kind ?? null);
  const [sub, setSub] = useState(investment?.subtype ?? '');
  const [name, setName] = useState(investment?.name ?? '');
  const [init] = useState<Values>(() => initial(investment));
  const [v, setV] = useState<Values>(init);
  const [money, setMoney] = useState<'already' | 'bank'>('already');
  const [payFrom, setPayFrom] = useState(investment?.pay_from_id ? String(investment.pay_from_id) : '');
  const [notes, setNotes] = useState(investment?.notes ?? '');
  // property bought in parts: the agreed price and how far the purchase is (the plan is on its page)
  const [dealPrice, setDealPrice] = useState('');
  const [dealStatus, setDealStatus] = useState<PropertyStatus>('agreement');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const set = (k: Key, val: string) => setV((p) => ({ ...p, [k]: val }));
  const [scheme, setScheme] = useState<Scheme | null>(null); // mutual fund picked from AMFI's list
  const [schemeText, setSchemeText] = useState('');

  const pickKind = (k: InvestmentKind) => {
    setKind(k);
    const first = SUBTYPES[k]?.[0]?.[0] ?? '';
    setSub(first);
    setV((p) => ({ ...p, compounding: k === 'lent' ? 'simple' : 'quarterly', frequency: k === 'bond' ? 'monthly' : p.frequency }));
  };

  if (!kind) {
    return (
      <>
        <DrawerHead title="Add investment" sub="What kind is it?" />
        <div className="drawer-body">
          <div className="inv-kinds">
            {KIND_ORDER.map((k) => (
              <button key={k} type="button" className="inv-kind" onClick={() => pickKind(k)}>
                <CategoryGlyph icon={KIND_META[k].icon} color={KIND_META[k].color} size={36} />
                <span>
                  <b>{KIND_META[k].label}</b>
                  <span className="muted">{KIND_META[k].blurb}</span>
                </span>
              </button>
            ))}
          </div>
        </div>
        <div className="drawer-foot">
          <span className="spacer" />
          <Button variant="secondary" onClick={close}>Cancel</Button>
        </div>
      </>
    );
  }

  const meta = KIND_META[kind];
  const fields = fieldsFor(kind, sub, editing);
  const schedule = isSchedule(kind, sub);
  const hasAmount = fields.includes('amount');
  const subs = SUBTYPES[kind];
  const purities = sub === 'silver' ? [['999', 'Fine silver (999)'], ['925', 'Sterling (925)']] : [['24k', '24 carat'], ['22k', '22 carat'], ['18k', '18 carat'], ['14k', '14 carat']];

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const body: Record<string, unknown> = { name: name.trim() || null, notes: notes.trim() || null };
    if (!editing) body.kind = kind;
    if (subs) body.subtype = sub;
    for (const k of fields) {
      const raw = v[k].trim();
      if (editing && raw === init[k].trim()) continue; // only what you changed
      if (MONEY.includes(k)) {
        if (!raw) {
          if (editing || k !== 'amount') body[k] = null;
          continue;
        }
        const p = toPaise(raw);
        if (p === null) return setError(`${labelFor(k, kind, sub)} must be a number, e.g. 25000 or 25000.50`);
        body[k] = p;
      } else if (k === 'rate' || k === 'quantity') {
        body[k] = raw ? Number(raw) : null;
        if (raw && Number.isNaN(Number(raw))) return setError(`${labelFor(k, kind, sub)} must be a number`);
      } else if (k === 'months') {
        body.months = raw ? Number(raw) : null;
      } else if (k === 'years') {
        body.months = raw ? Math.round(Number(raw) * 12) : null;
      } else if (k === 'start') {
        body.start_date = raw || null;
      } else if (k === 'maturity') {
        body.maturity_date = raw || null;
      } else if (k === 'compounding' && kind === 'post_office') {
        // the scheme's own rule
      } else {
        body[k] = raw || null;
      }
    }
    if (editing && 'amount' in body && body.amount === null) body.amount = 0;
    if (kind === 'mf' && !editing) {
      const typed = schemeText.trim();
      if (!scheme && !typed) return setError('Search for the fund and pick it from the list.');
      body.fund = scheme
        ? { scheme: scheme.name, isin: scheme.isin, amc: scheme.amc, amfi_code: scheme.code, nav: scheme.nav, nav_date: scheme.nav_date, folio: v.number.trim() || null }
        : { scheme: typed, folio: v.number.trim() || null };
    }
    if (payFrom) body.pay_from_id = Number(payFrom);
    if (!editing && hasAmount && body.amount) {
      body.money = money;
      if (money === 'bank' && !payFrom) return setError('Choose the bank account the money came from.');
    }
    if (!editing && kind === 'retirement' && body.current_value && !body.value_date) body.value_date = todayIso();
    setSaving(true);
    try {
      if (editing) {
        await api(`/investments/${investment.id}`, { method: 'PATCH', body });
        bump();
        close();
      } else {
        const made = await api<InvestmentDetail>('/investments', { method: 'POST', body });
        if (kind === 'property' && dealPrice.trim()) {
          const price = toPaise(dealPrice);
          if (price && price > 0) await api(`/investments/${made.id}/property`, { method: 'PUT', body: { price, status: dealStatus } });
        }
        bump();
        close();
        if (!stay) router.push(`/investments/${made.id}`);
      }
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!investment) return;
    if (!confirmDelete) return setConfirmDelete(true);
    setSaving(true);
    try {
      await api(`/investments/${investment.id}`, { method: 'DELETE' });
      bump();
      close();
      router.push('/investments');
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  const input = (k: Key) => {
    const id = `inv-${k}`;
    const opt =
      OPTIONAL.includes(k) ||
      (k === 'rate' && kind === 'lent') ||
      (k === 'maturity' && (kind === 'lent' || kind === 'insurance')) ||
      (k === 'years' && v.frequency === 'single') ||
      (kind === 'property' && (k === 'amount' || k === 'start')); // payments can be recorded from the bank later
    const text = editing && k === 'amount' ? 'Already invested before tracking (₹)' : labelFor(k, kind, sub);
    const label = (
      <label htmlFor={id}>
        {text} {opt && <span className="muted" style={{ fontWeight: 400 }}>(optional)</span>}
      </label>
    );
    if (k === 'compounding') {
      if (kind === 'post_office') return null;
      const opts = kind === 'lent' ? ['simple', 'yearly'] : ['monthly', 'quarterly', 'half_yearly', 'yearly', 'payout'];
      return (
        <div className="field" key={k}>
          {label}
          <select id={id} className="inp" value={v.compounding} onChange={(e) => set('compounding', e.target.value)}>
            {opts.map((o) => <option key={o} value={o}>{COMPOUNDING_LABEL[o]}</option>)}
          </select>
        </div>
      );
    }
    if (k === 'frequency') {
      return (
        <div className="field" key={k}>
          {label}
          <select id={id} className="inp" value={v.frequency} onChange={(e) => set('frequency', e.target.value)}>
            {Object.entries(kind === 'bond' ? BOND_FREQUENCY_LABEL : FREQUENCY_LABEL).map(([o, l]) => <option key={o} value={o}>{l}</option>)}
          </select>
        </div>
      );
    }
    if (k === 'repayment') {
      return (
        <div className="field" key={k}>
          {label}
          <select id={id} className="inp" value={v.repayment} onChange={(e) => set('repayment', e.target.value)}>
            {Object.entries(REPAYMENT_LABEL).map(([o, l]) => <option key={o} value={o}>{l}</option>)}
          </select>
        </div>
      );
    }
    if (k === 'purity') {
      return (
        <div className="field" key={k}>
          {label}
          <select id={id} className="inp" value={v.purity || purities[sub === 'silver' ? 0 : sub === 'coin' ? 0 : 1][0]} onChange={(e) => set('purity', e.target.value)}>
            {purities.map(([o, l]) => <option key={o} value={o}>{l}</option>)}
          </select>
        </div>
      );
    }
    const isDate = ['start', 'maturity', 'value_date', 'payout_on'].includes(k);
    const numeric = MONEY.includes(k) || ['rate', 'quantity', 'months', 'years'].includes(k);
    const hint = kind === 'bond' ? BOND_PLACEHOLDER[k] : undefined;
    return (
      <div className="field" key={k}>
        {label}
        <input
          id={id}
          className="inp"
          type={isDate ? 'date' : 'text'}
          inputMode={numeric ? 'decimal' : undefined}
          value={v[k]}
          onChange={(e) => set(k, e.target.value)}
          required={!opt && !['amount', 'current_value'].includes(k) && !(kind === 'retirement') && !(isDate && ['mf', 'gold', 'stocks', 'crypto', 'property', 'other'].includes(kind))}
          placeholder={hint ?? (MONEY.includes(k) ? '0.00' : k === 'rate' ? 'e.g. 7.1' : undefined)}
        />
      </div>
    );
  };

  // purity defaults are chosen by the backend when left empty; keep the select showing it
  const shown = fields.map(input).filter(Boolean);
  const pairs: ReactNode[] = [];
  for (let i = 0; i < shown.length; i += 2) {
    pairs.push(
      <div className="row2" key={i}>
        {shown[i]}
        {shown[i + 1] ?? <div />}
      </div>,
    );
  }

  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead
        title={editing ? investment.name : `Add ${meta.label.toLowerCase()}`}
        sub={editing ? meta.label : meta.blurb}
        lead={<CategoryGlyph icon={meta.icon} color={meta.color} size={42} />}
      />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        {!editing && (
          <button type="button" className="btn btn-ghost btn-sm" style={{ marginBottom: 12 }} onClick={() => setKind(null)}>
            ← Another kind
          </button>
        )}
        {subs && (
          <div className="field">
            <label htmlFor="inv-sub">Type</label>
            <select id="inv-sub" className="inp" value={sub} onChange={(e) => setSub(e.target.value)}>
              {subs.map(([o, l]) => <option key={o} value={o}>{l}</option>)}
            </select>
          </div>
        )}
        {kind === 'bond' && !editing && (
          <div className="note info" style={{ marginBottom: 14 }}>
            From your app&apos;s order or holdings page: the units, the amount you paid, the coupon rate (not the
            yield / XIRR) and the maturity date. Face value can stay blank — MoneyMap uses amount paid ÷ units.
          </div>
        )}
        {kind === 'insurance' && sub === 'term' && (
          <div className="note" style={{ marginBottom: 14 }}>
            Term insurance has no value — it is listed for its premium dates only. Record its premiums as spending (e.g.
            category Insurance).
          </div>
        )}
        {kind === 'mf' && !editing && (
          <>
            {onImportCas && (
              <div className="note info" style={{ marginBottom: 14 }}>
                <span>
                  Have a CAS from CAMS / KFintech? It adds all your funds with their full history.{' '}
                  <Button variant="secondary" size="sm" onClick={() => { close(); onImportCas(); }}>Import CAS</Button>
                </span>
              </div>
            )}
            <SchemePicker picked={scheme} onPick={setScheme} text={schemeText} onText={setSchemeText} />
          </>
        )}
        <div className="field">
          <label htmlFor="inv-name">
            Name <span className="muted" style={{ fontWeight: 400 }}>{editing ? '' : '(optional — made from the details)'}</span>
          </label>
          <input
            id="inv-name"
            className="inp"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={120}
            required={editing}
            placeholder={kind === 'stocks' ? 'e.g. Infosys' : kind === 'crypto' ? 'e.g. Bitcoin' : kind === 'property' ? 'e.g. Plot in Nashik' : ''}
          />
        </div>
        {pairs}
        {kind === 'post_office' && (
          <div className="hint" style={{ marginTop: -8, marginBottom: 14 }}>
            Interest: {COMPOUNDING_LABEL[PO_COMPOUNDING[sub] ?? 'quarterly'].toLowerCase()}, as the scheme adds it.
          </div>
        )}
        {schedule && !editing && (
          <div className="hint" style={{ marginTop: -8, marginBottom: 14 }}>
            {kind === 'insurance' ? 'Premiums' : 'Instalments'} are counted as paid on their dates up to today. Record them
            from your bank with “Add money” if you want them in your bank balance.
          </div>
        )}
        {!editing && hasAmount && (
          <div className="field">
            <label>The money</label>
            <SegmentedControl
              aria-label="The money"
              value={money}
              onChange={(x) => setMoney(x as 'already' | 'bank')}
              options={[
                { value: 'already', label: 'Already invested' },
                { value: 'bank', label: 'Paid from my bank now' },
              ]}
            />
            <div className="hint">
              {money === 'already'
                ? 'Your bank balance stays as it is — the payment is already there or is older than your records.'
                : 'Records a transfer from the bank to this investment on the date above. It is not spending.'}
            </div>
          </div>
        )}
        {(money === 'bank' || editing || schedule) && (
          <div className="field">
            <label htmlFor="inv-bank">
              {kind === 'insurance' ? 'Premium paid from' : 'Money comes from'}{' '}
              {money !== 'bank' && <span className="muted" style={{ fontWeight: 400 }}>(optional)</span>}
            </label>
            <select id="inv-bank" className="inp" value={payFrom} onChange={(e) => setPayFrom(e.target.value)}>
              <option value="">—</option>
              {(banks.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </div>
        )}
        {kind === 'property' && !editing && (
          <div className="card card-pad" style={{ marginBottom: 14, background: 'var(--bg-subtle)' }}>
            <b style={{ fontSize: 13.5 }}>Paid only part of it, or not registered yet?</b>
            <div className="row2" style={{ marginTop: 10 }}>
              <div className="field" style={{ marginBottom: 0 }}>
                <label htmlFor="inv-deal-price">Total agreed price (₹) <span className="muted" style={{ fontWeight: 400 }}>(optional)</span></label>
                <input id="inv-deal-price" className="inp" inputMode="decimal" value={dealPrice} onChange={(e) => setDealPrice(e.target.value)} placeholder="0.00" />
              </div>
              <div className="field" style={{ marginBottom: 0 }}>
                <label htmlFor="inv-deal-status">Status</label>
                <select id="inv-deal-status" className="inp" value={dealStatus} onChange={(e) => setDealStatus(e.target.value as PropertyStatus)} disabled={!dealPrice.trim()}>
                  <option value="booked">Booked</option>
                  <option value="agreement">Agreement made</option>
                  <option value="registration_pending">Registration pending</option>
                </select>
              </div>
            </div>
            <div className="hint" style={{ marginTop: 8 }}>
              MoneyMap then shows what&apos;s paid and the balance. Add the dates for the balance, costs like stamp duty and a savings goal on the
              property&apos;s page under <b>Purchase</b>. Until it&apos;s registered it counts as what you&apos;ve paid.
            </div>
          </div>
        )}
        {kind === 'property' && editing && (
          <div className="hint" style={{ marginBottom: 12 }}>Agreed price, payment plan, status and costs are under <b>Purchase</b> on this property&apos;s page.</div>
        )}
        <div className="field">
          <label htmlFor="inv-notes">Notes</label>
          <textarea id="inv-notes" className="inp" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </div>
        {editing && investment.moves.length > 0 && confirmDelete && (
          <div className="note warn">Its {investment.moves.length} money in / out entr{investment.moves.length === 1 ? 'y is' : 'ies are'} deleted too, so your bank balance changes back.</div>
        )}
      </div>
      <div className="drawer-foot">
        {editing && (
          <Button variant={confirmDelete ? 'primary' : 'ghost'} icon="trash-2" onClick={remove} disabled={saving} className={confirmDelete ? 'btn-danger' : ''}>
            {confirmDelete ? 'Confirm delete' : 'Delete'}
          </Button>
        )}
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        <Button variant="primary" type="submit" disabled={saving}>
          {saving ? 'Saving…' : editing ? 'Save changes' : 'Add investment'}
        </Button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------- mutual fund search (AMFI list)

function SchemePicker({ picked, onPick, text, onText }: { picked: Scheme | null; onPick: (s: Scheme | null) => void; text: string; onText: (t: string) => void }) {
  const [hits, setHits] = useState<Scheme[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  useEffect(() => {
    if (picked || text.trim().length < 3) return;
    const t = setTimeout(async () => {
      setSearching(true);
      try {
        setHits(await api<Scheme[]>(`/investments/schemes?q=${encodeURIComponent(text.trim())}`));
        setError(null);
      } catch (e) {
        setError((e as Error).message);
      }
      setSearching(false);
    }, 350);
    return () => clearTimeout(t);
  }, [text, picked]);

  if (picked) {
    return (
      <div className="field">
        <label>Fund</label>
        <div className="card card-pad" style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 600 }}>{picked.name}</div>
            <div className="muted" style={{ fontSize: 12 }}>
              {[picked.amc, picked.isin, picked.nav !== null ? `NAV ${fmtNav(picked.nav)}${picked.nav_date ? ` on ${fmtDate(picked.nav_date)}` : ''}` : null].filter(Boolean).join(' · ')}
            </div>
          </div>
          <Button variant="ghost" size="sm" onClick={() => onPick(null)}>Change</Button>
        </div>
      </div>
    );
  }
  const shown = text.trim().length >= 3 ? hits : [];
  return (
    <div className="field">
      <label htmlFor="inv-scheme">Fund</label>
      <input id="inv-scheme" className="inp" value={text} onChange={(e) => onText(e.target.value)} placeholder="Type part of the name, e.g. flexi cap direct" autoComplete="off" />
      {error && <div className="hint" style={{ color: 'var(--red-600)' }}>{error}</div>}
      {searching && <div className="hint">Searching…</div>}
      {shown.length > 0 && (
        <div className="inv-scheme-list" role="listbox" aria-label="Funds">
          {shown.map((s) => (
            <button key={s.code} type="button" role="option" aria-selected={false} className="inv-scheme-opt" onClick={() => onPick(s)}>
              <b>{s.name}</b>
              <span className="muted">{[s.amc, s.nav !== null ? `NAV ${fmtNav(s.nav)}` : null].filter(Boolean).join(' · ')}</span>
            </button>
          ))}
        </div>
      )}
      <div className="hint">From the AMFI list of funds; its price then updates every evening.</div>
    </div>
  );
}
