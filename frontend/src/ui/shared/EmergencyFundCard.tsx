'use client';
import { useState, type FormEvent } from 'react';
import Link from 'next/link';
import { api } from '../lib/api';
import { useApi, useShell } from '../contexts/ShellCtx';
import type { Account, Emergency, EmergencyStatus, Piggy } from '../lib/types';
import { inr, monthLabel, paiseToInput, rs, toPaise } from '../lib/format';
import { useMask } from '../contexts/MaskCtx';
import { Button } from '../primitives/Button';
import { Money } from '../primitives/Money';
import { Icon } from '../primitives/Icon';
import { Skeleton } from '../primitives/Skeleton';
import { ErrorState } from '../primitives/ErrorState';
import { SegmentedControl } from '../primitives/SegmentedControl';
import { Dialog, useDialogClose } from '../primitives/Dialog';
import { DrawerHead } from './DrawerHead';
import { Progress } from './Progress';

const STATUS: Record<EmergencyStatus, [string, string]> = {
  not_set_up: ['neutral', 'Not set up'],
  no_data: ['neutral', 'Needs spending data'],
  low: ['red', 'Low'],
  building: ['cau', 'Building'],
  safe: ['mint', 'Safe'],
  done: ['mint', 'Target reached'],
};

export function EmergencyBadge({ status }: { status: EmergencyStatus }) {
  const [cls, label] = STATUS[status];
  return <span className={`badge ${cls}`}>{label}</span>;
}

/** Months of cover choices: up to 5 years. */
export const COVER_OPTIONS: { value: number; label: string }[] = [
  { value: 3, label: '3 months' },
  { value: 6, label: '6 months (recommended)' },
  { value: 9, label: '9 months' },
  { value: 12, label: '12 months (1 year)' },
  { value: 18, label: '18 months' },
  { value: 24, label: '2 years' },
  { value: 36, label: '3 years' },
  { value: 48, label: '4 years' },
  { value: 60, label: '5 years' },
];

/** "6 months", "3 years" */
export function coverLabel(months: number): string {
  return months >= 24 && months % 12 === 0 ? `${months / 12} years` : `${months} months`;
}

/** "3.8 of 6 months covered" — how long the saved money would cover essential spending. */
export function coverText(covered: number | null, months: number): string {
  const total = months >= 24 && months % 12 === 0 ? `${months} months (${months / 12} years)` : `${months} months`;
  return covered === null ? `${coverLabel(months)} of cover` : `${covered.toLocaleString('en-IN')} of ${total} covered`;
}

/** Emergency fund card at the top of the Piggy banks page. Money is moved with the
 * page's own add / take out dialog (`onMove`). */
export function EmergencyFundCard({ onMove }: { onMove: (piggy: Piggy, dir: 'add' | 'remove') => void }) {
  const { data, error, reload } = useApi<Emergency>('/emergency-fund');
  const [settings, setSettings] = useState(false);
  const [showHow, setShowHow] = useState(false);

  if (error) return <div className="card" style={{ marginBottom: 18 }}><ErrorState message={error} onRetry={reload} /></div>;
  if (!data) return <div style={{ marginBottom: 18 }}><Skeleton variant="block" height={150} /></div>;

  const head = (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'flex-start', flexWrap: 'wrap' }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
        <span className="ico" style={{ background: 'var(--coral-50)', color: 'var(--coral-600)', width: 40, height: 40, borderRadius: 12, display: 'grid', placeItems: 'center' }}>
          <Icon name="life-buoy" size={20} />
        </span>
        <div>
          <div style={{ fontFamily: 'var(--font-display)', fontWeight: 650, fontSize: 16 }}>Emergency fund</div>
          <div className="muted" style={{ fontSize: 12.5 }}>
            {data.configured && data.piggy ? `In ${data.piggy.account.name}` : 'Months of essential spending kept aside for job loss, medical bills, repairs'}
          </div>
        </div>
      </div>
      {data.configured && <EmergencyBadge status={data.status} />}
    </div>
  );

  if (!data.configured || !data.piggy) {
    return (
      <div className="card card-pad" style={{ marginBottom: 18, display: 'flex', flexDirection: 'column', gap: 12 }}>
        {head}
        <p className="muted" style={{ margin: 0, fontSize: 13.5 }}>
          MoneyMap works out a typical month of your <b>essential</b> spending (rent, groceries, utilities, EMIs …) from your
          transactions and suggests keeping <b>6 months</b> of it aside. The money stays in a bank or cash account you choose.
        </p>
        <div>
          <Button variant="primary" icon="life-buoy" onClick={() => setSettings(true)}>Set up emergency fund</Button>
        </div>
        {settings && <EmergencyForm data={data} onClose={() => setSettings(false)} />}
      </div>
    );
  }

  const p = data.piggy;
  const pct = data.target > 0 ? Math.min(100, Math.round((data.saved / data.target) * 100)) : 0;
  const typical =
    data.monthly_source === 'override'
      ? 'the monthly amount you set'
      : data.monthly_source === 'none'
        ? 'no essential spending recorded yet'
        : `typical month over the last ${data.months_of_data} month${data.months_of_data === 1 ? '' : 's'}${data.monthly_source === 'estimate' ? ' (estimate — little history)' : ''}`;
  const maxMonth = Math.max(1, ...data.history.map((h) => h.amount));

  return (
    <div className="card card-pad" style={{ marginBottom: 18, display: 'flex', flexDirection: 'column', gap: 14 }}>
      {head}
      {data.status === 'no_data' ? (
        <div className="note info">
          <Icon name="info" size={15} />
          <span>
            No essential spending in the last complete months yet. Record expenses with essential categories, or set the
            monthly amount yourself in the settings.
          </span>
        </div>
      ) : (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
            <span>
              <span className="fig" style={{ fontSize: 22 }}><Money amount={rs(data.saved)} pos /></span>
              <span className="muted" style={{ fontSize: 13 }}> of <Money amount={rs(data.target)} /> · {pct}%</span>
            </span>
            <b style={{ fontSize: 14 }}>{coverText(data.covered_months, data.months_cover)}</b>
          </div>
          <Progress value={data.saved} max={data.target} savings />
          <div className="muted" style={{ fontSize: 12.5, marginTop: 8 }}>
            Target = {coverLabel(data.months_cover)} × <Money amount={rs(data.monthly_essential)} interactive={false} /> ({typical})
            {data.monthly_to_save ? <> · save <Money amount={rs(data.monthly_to_save)} interactive={false} />/month to reach it by the target date</> : null}
          </div>
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <Button variant="secondary" size="sm" icon="plus" onClick={() => onMove(p, 'add')}>Add money</Button>
        <Button variant="ghost" size="sm" icon="minus" onClick={() => onMove(p, 'remove')} disabled={data.saved <= 0}>Take out</Button>
        <span className="spacer" style={{ flex: 1 }} />
        <Button variant="ghost" size="sm" icon={showHow ? 'chevron-up' : 'chevron-down'} onClick={() => setShowHow((v) => !v)}>
          How it&apos;s worked out
        </Button>
        <Button variant="ghost" size="sm" icon="settings" onClick={() => setSettings(true)}>Settings</Button>
      </div>

      {showHow && (
        <div style={{ borderTop: '1px solid var(--border)', paddingTop: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
          {data.history.length > 0 ? (
            <div>
              <div className="muted" style={{ fontSize: 12.5, marginBottom: 8 }}>
                Essential spending in each complete month{data.monthly_source === 'override' ? ' (not used — you set the amount)' : ' — the middle month (median) is the typical month, so one unusual month doesn’t inflate it'}:
              </div>
              {data.history.map((h) => (
                <div key={h.month} style={{ display: 'grid', gridTemplateColumns: '110px 1fr auto', gap: 10, alignItems: 'center', fontSize: 13, marginBottom: 6 }}>
                  <span>{monthLabel(h.month)}</span>
                  <div className="track" style={{ height: 6, borderRadius: 999, background: 'var(--bg-sunken)', overflow: 'hidden' }}>
                    <i style={{ display: 'block', height: '100%', width: `${(h.amount / maxMonth) * 100}%`, background: 'var(--indigo-500)' }} />
                  </div>
                  <span className="fig"><Money amount={rs(h.amount)} interactive={false} /></span>
                </div>
              ))}
            </div>
          ) : (
            <div className="muted" style={{ fontSize: 13 }}>No complete months of history yet.</div>
          )}
          <div className="muted" style={{ fontSize: 12.5 }}>
            Essential categories ({data.essential_categories.length}): {data.essential_categories.join(', ') || 'none'} ·{' '}
            <Link href="/categories">change on Categories</Link>
          </div>
        </div>
      )}

      {settings && <EmergencyForm data={data} onClose={() => setSettings(false)} />}
    </div>
  );
}

function EmergencyForm({ data, onClose }: { data: Emergency; onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label="Emergency fund settings" width={480}>
      <EmergencyFormBody data={data} />
    </Dialog>
  );
}

function EmergencyFormBody({ data }: { data: Emergency }) {
  const close = useDialogClose();
  const { bump } = useShell();
  const accounts = useApi<Account[]>('/accounts?type=asset&type=cash&include_inactive=false');
  const [accountId, setAccountId] = useState(data.piggy ? String(data.piggy.account.id) : '');
  const [months, setMonths] = useState(String(data.months_cover || 6));
  const [average, setAverage] = useState(String(data.average_months || 6));
  const [ownAmount, setOwnAmount] = useState(data.monthly_override !== null && data.monthly_override !== undefined);
  const [amount, setAmount] = useState(data.monthly_override ? paiseToInput(data.monthly_override) : '');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmOff, setConfirmOff] = useState(false);
  const { masked } = useMask();

  // Live preview: the typical month for the current choices, and the target for every length.
  const estimate = data.estimates.find((x) => String(x.average_months) === average);
  const ownPaise = ownAmount ? toPaise(amount) : null;
  const monthly = ownAmount ? (ownPaise && ownPaise > 0 ? ownPaise : 0) : (estimate?.monthly ?? 0);
  const money = (paise: number) => (masked ? '₹•••' : inr(rs(paise)));
  const coverOptions = COVER_OPTIONS.some((o) => String(o.value) === months)
    ? COVER_OPTIONS
    : [...COVER_OPTIONS, { value: Number(months), label: coverLabel(Number(months)) }];

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!accountId) return setError('Choose the account that holds the money.');
    let override: number | null = null;
    if (ownAmount) {
      const v = toPaise(amount);
      if (v === null || v <= 0) return setError('Enter the monthly amount, e.g. 40000');
      override = v;
    }
    setSaving(true);
    try {
      await api('/emergency-fund', {
        method: 'PUT',
        body: { account_id: Number(accountId), months_cover: Number(months), average_months: Number(average), monthly_override: override },
      });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  const switchOff = async () => {
    if (!confirmOff) return setConfirmOff(true);
    setSaving(true);
    try {
      await api('/emergency-fund', { method: 'DELETE' });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead title="Emergency fund" sub={data.configured ? 'Settings' : 'Set up'} />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        <div className="field">
          <label htmlFor="ef-acc">Kept in account</label>
          <select id="ef-acc" className="inp" value={accountId} onChange={(e) => setAccountId(e.target.value)} required>
            <option value="">Choose an account…</option>
            {(accounts.data ?? []).map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
          <div className="hint">The money stays in this account; the fund just sets it aside, like a piggy bank.</div>
        </div>
        <div className="field">
          <label htmlFor="ef-months">How long should it cover you?</label>
          <select id="ef-months" className="inp" value={months} onChange={(e) => setMonths(e.target.value)}>
            {coverOptions.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
                {monthly > 0 ? ` — ${money(monthly * o.value)}` : ''}
              </option>
            ))}
          </select>
          <div className="hint">
            3 months with a stable salary and two incomes · 6 for most people · 9–12 for freelancers or a single income with
            dependents · 2–5 years if you plan a career break or want to be fully independent of your income for a while.
          </div>
        </div>
        <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 14, marginBottom: 12 }}>
          <input type="checkbox" checked={ownAmount} onChange={(e) => setOwnAmount(e.target.checked)} />
          I&apos;ll set the monthly amount myself
        </label>
        {ownAmount ? (
          <div className="field">
            <label htmlFor="ef-amt">Essential spending per month (₹)</label>
            <input id="ef-amt" className="inp" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="e.g. 40000" />
          </div>
        ) : (
          <div className="field">
            <label>Work out the typical month from the last</label>
            <SegmentedControl
              aria-label="Months to average over"
              value={average}
              onChange={setAverage}
              options={[
                { value: '3', label: '3 months' },
                { value: '6', label: '6 months' },
                { value: '12', label: '12 months' },
              ]}
            />
            <div className="hint">Only expenses in essential categories count. The current month is left out until it ends.</div>
          </div>
        )}
        <div className="card card-pad" style={{ background: 'var(--bg-subtle)' }} aria-live="polite">
          {monthly > 0 ? (
            <>
              <div className="muted" style={{ fontSize: 12.5 }}>Target with these settings</div>
              <div className="fig" style={{ fontSize: 24, margin: '2px 0 4px' }}>
                <Money amount={rs(monthly * Number(months))} />
              </div>
              <div className="muted" style={{ fontSize: 12.5 }}>
                {coverLabel(Number(months))} × <Money amount={rs(monthly)} interactive={false} /> a month
                {ownAmount
                  ? ' (your amount)'
                  : estimate
                    ? ` (typical month over the last ${estimate.months_of_data} month${estimate.months_of_data === 1 ? '' : 's'}${estimate.source === 'estimate' ? ', estimate' : ''})`
                    : ''}
                {data.saved > 0 && (
                  <>
                    {' '}· you have <Money amount={rs(data.saved)} interactive={false} /> saved ={' '}
                    {(data.saved / monthly).toLocaleString('en-IN', { maximumFractionDigits: 1 })} months
                  </>
                )}
              </div>
            </>
          ) : (
            <div className="muted" style={{ fontSize: 13 }}>
              {ownAmount
                ? 'Enter your monthly amount to see the target.'
                : 'No essential spending in these months yet — the target appears once you record some, or set the monthly amount yourself.'}
            </div>
          )}
        </div>
      </div>
      <div className="drawer-foot">
        {data.configured && (
          <Button variant={confirmOff ? 'primary' : 'ghost'} icon="power" onClick={switchOff} disabled={saving} className={confirmOff ? 'btn-danger' : ''}>
            {confirmOff ? 'Confirm switch off' : 'Switch off'}
          </Button>
        )}
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        <Button variant="primary" type="submit" disabled={saving}>{saving ? 'Saving…' : data.configured ? 'Save' : 'Set up'}</Button>
      </div>
    </form>
  );
}
