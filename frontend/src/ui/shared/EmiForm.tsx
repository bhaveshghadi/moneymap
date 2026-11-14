'use client';
import { useState, type FormEvent } from 'react';
import type { CardDetail, Category, Emi, TxnPage } from '../lib/types';
import { api, qs } from '../lib/api';
import { fmtDate, paiseToInput, rs, toPaise, todayIso } from '../lib/format';
import { useApi, useShell } from '../contexts/ShellCtx';
import { Dialog, useDialogClose } from '../primitives/Dialog';
import { Button } from '../primitives/Button';
import { Money } from '../primitives/Money';
import { SegmentedControl } from '../primitives/SegmentedControl';
import { Icon } from '../primitives/Icon';
import { DrawerHead } from './DrawerHead';
import { CategoryOptions } from './CategoryOptions';

type Kind = 'converted' | 'checkout' | 'existing';

const KIND_HELP: Record<Kind, string> = {
  converted: 'You bought something on the card and then converted it to EMI. The purchase stays as spending, once; the EMI takes the amount off this bill and adds back one instalment each month.',
  checkout: 'You chose EMI when paying (e.g. "Pay with EMI" on Flipkart). The full purchase is recorded once, as spending; each month an instalment comes on the bill.',
  existing: 'An EMI that started before you tracked it here. Enter what is left; past instalment rows already imported from statements are moved onto it.',
};

const TENURES = [3, 6, 9, 12, 18, 24, 36];

function addMonthsIso(iso: string, n: number): string {
  const d = new Date(`${iso}T00:00:00`);
  const day = d.getDate();
  d.setDate(1);
  d.setMonth(d.getMonth() + n);
  d.setDate(Math.min(day, new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate()));
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export function EmiForm({ card, onClose }: { card: CardDetail; onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label="Add EMI" width={560}>
      <Body card={card} />
    </Dialog>
  );
}

function Body({ card }: { card: CardDetail }) {
  const close = useDialogClose();
  const { bump } = useShell();
  const purchases = useApi<TxnPage>(`/transactions${qs({ account_id: card.id, type: 'withdrawal', limit: 100 })}`);
  const categories = useApi<Category[]>('/categories');
  const [kind, setKind] = useState<Kind>('converted');
  const [f, setF] = useState({
    purchaseId: '',
    name: '',
    principal: '',
    tenure: '6',
    instalment: '',
    rate: '',
    fee: '',
    noCost: false,
    startDate: card.current.statement_date, // the first instalment usually comes on the next statement
    convertedOn: todayIso(),
    purchaseDate: todayIso(),
    categoryId: '',
    outstanding: '',
    paidBefore: '',
    linkPast: true,
  });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState<{ emi: Emi; linked_instalments: number; linked_charges: number } | null>(null);
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((p) => ({ ...p, [k]: v }));

  // ₹1,000+ purchases, not EMI instalment / interest rows
  const choices = (purchases.data?.items ?? []).filter((t) => t.amount >= 100_000 && !/amorti[sz]ation|principal|emi/i.test(t.description));
  const pickPurchase = (id: string) => {
    const t = choices.find((x) => String(x.id) === id);
    setF((p) => ({
      ...p,
      purchaseId: id,
      name: t ? t.destination.name : p.name,
      principal: t ? paiseToInput(t.amount) : p.principal,
    }));
  };
  const tenure = Number(f.tenure) || 0;
  const principal = toPaise(f.principal);
  const finish = f.startDate && tenure ? addMonthsIso(f.startDate, tenure - 1) : null;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (kind === 'converted' && !f.purchaseId) return setError('Choose the purchase that was converted.');
    if (!f.name.trim()) return setError('Enter what was bought or the merchant.');
    if (principal === null || principal <= 0) return setError('Enter the amount, e.g. 34934');
    if (!tenure || tenure > 120) return setError('Enter the number of monthly instalments.');
    const outstanding = f.outstanding ? toPaise(f.outstanding) : null;
    if (kind === 'existing' && (outstanding === null || outstanding < 0)) return setError('Enter how much is still left to pay.');
    const body = {
      kind,
      name: f.name.trim(),
      principal,
      tenure,
      start_date: f.startDate,
      instalment: f.instalment ? toPaise(f.instalment) : null,
      interest_rate: f.rate ? Number(f.rate) : null,
      processing_fee: f.fee ? toPaise(f.fee) : null,
      no_cost: f.noCost,
      purchase_txn_id: kind === 'converted' ? Number(f.purchaseId) : null,
      converted_on: kind === 'converted' ? f.convertedOn : null,
      purchase_date: kind === 'checkout' ? f.purchaseDate : null,
      category_id: kind === 'checkout' && f.categoryId ? Number(f.categoryId) : null,
      outstanding: kind === 'existing' ? outstanding : null,
      paid_before: kind === 'existing' && f.paidBefore ? Number(f.paidBefore) : null,
      link_past: f.linkPast,
    };
    setSaving(true);
    try {
      const res = await api<{ emi: Emi; linked_instalments: number; linked_charges: number }>(`/cards/${card.id}/emis`, { method: 'POST', body });
      bump();
      if (res.linked_instalments || res.linked_charges) setDone(res);
      else close();
    } catch (err) {
      setError((err as Error).message);
    }
    setSaving(false);
  };

  if (done) {
    return (
      <>
        <DrawerHead title={done.emi.name} sub="EMI added" lead={<span className="ico" style={{ background: 'var(--mint-50)', color: 'var(--mint-700)' }}><Icon name="circle-check" size={20} /></span>} />
        <div className="drawer-body">
          <p style={{ marginTop: 0 }}>
            Moved {done.linked_instalments} past instalment{done.linked_instalments === 1 ? '' : 's'} onto this EMI (they no
            longer count as spending) and linked {done.linked_charges} interest / GST row{done.linked_charges === 1 ? '' : 's'} to it.
          </p>
        </div>
        <div className="drawer-foot">
          <span className="spacer" />
          <Button variant="primary" onClick={close}>Done</Button>
        </div>
      </>
    );
  }

  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead title="Add EMI" sub={card.name} lead={<span className="ico" style={{ background: 'var(--indigo-50)', color: 'var(--indigo-600)' }}><Icon name="calendar-range" size={20} /></span>} />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        <div className="field">
          <SegmentedControl
            aria-label="Kind of EMI"
            value={kind}
            onChange={(v) => setKind(v as Kind)}
            options={[
              { value: 'converted', label: 'Converted a purchase' },
              { value: 'checkout', label: 'EMI at checkout' },
              { value: 'existing', label: 'Already running' },
            ]}
          />
          <div className="hint">{KIND_HELP[kind]}</div>
        </div>

        {kind === 'converted' && (
          <>
            <div className="field">
              <label htmlFor="emi-buy">Purchase converted</label>
              <select id="emi-buy" className="inp" value={f.purchaseId} onChange={(e) => pickPurchase(e.target.value)}>
                <option value="">{purchases.data ? 'Choose the purchase…' : 'Loading…'}</option>
                {choices.map((t) => (
                  <option key={t.id} value={t.id}>
                    {fmtDate(t.date)} · {t.destination.name} · ₹{(t.amount / 100).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                  </option>
                ))}
              </select>
              {purchases.data && choices.length === 0 && <div className="hint">No card purchases of ₹1,000 or more yet — add or import the purchase first.</div>}
            </div>
            <div className="field">
              <label htmlFor="emi-conv">Converted on</label>
              <input id="emi-conv" className="inp" type="date" value={f.convertedOn} onChange={(e) => set('convertedOn', e.target.value)} />
            </div>
          </>
        )}

        <div className="row2">
          <div className="field">
            <label htmlFor="emi-name">{kind === 'converted' ? 'Name' : 'Merchant / what you bought'}</label>
            <input id="emi-name" className="inp" value={f.name} onChange={(e) => set('name', e.target.value)} maxLength={120} placeholder="e.g. Croma — iPhone" />
          </div>
          <div className="field">
            <label htmlFor="emi-amt">{kind === 'existing' ? 'Original amount (₹)' : 'Amount (₹)'}</label>
            <input id="emi-amt" className="inp" inputMode="decimal" value={f.principal} onChange={(e) => set('principal', e.target.value)} placeholder="e.g. 34934" />
          </div>
        </div>

        {kind === 'checkout' && (
          <div className="row2">
            <div className="field">
              <label htmlFor="emi-pdate">Bought on</label>
              <input id="emi-pdate" className="inp" type="date" value={f.purchaseDate} onChange={(e) => set('purchaseDate', e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="emi-cat">Category</label>
              <select id="emi-cat" className="inp" value={f.categoryId} onChange={(e) => set('categoryId', e.target.value)}>
                <option value="">Uncategorised</option>
                <CategoryOptions categories={categories.data ?? []} kind="expense" markEssential />
              </select>
            </div>
          </div>
        )}

        {kind === 'existing' && (
          <div className="row2">
            <div className="field">
              <label htmlFor="emi-left">Still left to pay (₹)</label>
              <input id="emi-left" className="inp" inputMode="decimal" value={f.outstanding} onChange={(e) => set('outstanding', e.target.value)} placeholder="Outstanding on the statement" />
            </div>
            <div className="field">
              <label htmlFor="emi-paid">Instalments already paid</label>
              <input id="emi-paid" className="inp" inputMode="numeric" value={f.paidBefore} onChange={(e) => set('paidBefore', e.target.value.replace(/\D/g, ''))} placeholder="worked out if empty" />
            </div>
          </div>
        )}

        <div className="row2">
          <div className="field">
            <label htmlFor="emi-ten">Months</label>
            <select id="emi-ten" className="inp" value={TENURES.includes(tenure) ? f.tenure : 'other'} onChange={(e) => e.target.value !== 'other' && set('tenure', e.target.value)}>
              {TENURES.map((n) => (
                <option key={n} value={n}>{n} months</option>
              ))}
              {!TENURES.includes(tenure) && <option value="other">{tenure} months</option>}
            </select>
          </div>
          <div className="field">
            <label htmlFor="emi-start">First instalment</label>
            <input id="emi-start" className="inp" type="date" value={f.startDate} onChange={(e) => set('startDate', e.target.value)} />
          </div>
        </div>
        <div className="row3" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 12 }}>
          <div className="field">
            <label htmlFor="emi-inst">Monthly EMI (₹)</label>
            <input id="emi-inst" className="inp" inputMode="decimal" value={f.instalment} onChange={(e) => set('instalment', e.target.value)} placeholder="optional" />
          </div>
          <div className="field">
            <label htmlFor="emi-rate">Interest % a year</label>
            <input id="emi-rate" className="inp" inputMode="decimal" value={f.rate} onChange={(e) => set('rate', e.target.value)} placeholder="optional" />
          </div>
          <div className="field">
            <label htmlFor="emi-fee">Processing fee (₹)</label>
            <input id="emi-fee" className="inp" inputMode="decimal" value={f.fee} onChange={(e) => set('fee', e.target.value)} placeholder="optional" />
          </div>
        </div>
        <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 14, marginBottom: 8 }}>
          <input type="checkbox" checked={f.noCost} onChange={(e) => set('noCost', e.target.checked)} />
          No-cost EMI (the interest is given back as a discount)
        </label>
        <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 14 }}>
          <input type="checkbox" checked={f.linkPast} onChange={(e) => set('linkPast', e.target.checked)} />
          Move past instalment rows from imported statements onto this EMI
        </label>
        {principal && tenure && finish ? (
          <div className="note info" style={{ marginTop: 12 }}>
            <span>
              <Money amount={rs(principal)} interactive={false} /> over {tenure} months — about{' '}
              <Money amount={rs(Math.round(principal / tenure))} interactive={false} /> principal a month, from {fmtDate(f.startDate)} to{' '}
              {fmtDate(finish)}. Interest and GST on it come as Card Fees &amp; Interest.
            </span>
          </div>
        ) : null}
      </div>
      <div className="drawer-foot">
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        <Button variant="primary" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Add EMI'}</Button>
      </div>
    </form>
  );
}
