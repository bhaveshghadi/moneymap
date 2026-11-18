'use client';
import { useState, type FormEvent } from 'react';
import Link from 'next/link';
import { api } from '../lib/api';
import { useApi, useShell } from '../contexts/ShellCtx';
import type { CasSummary, Investment, InvestmentDue, InvestmentKind, InvestmentSummary, MetalRates, NavStatus } from '../lib/types';
import { daysUntil, fmtDate, fromUtc, paiseToInput, rs, toPaise } from '../lib/format';
import { Button } from '../primitives/Button';
import { Money } from '../primitives/Money';
import { StatCard } from '../primitives/StatCard';
import { Skeleton } from '../primitives/Skeleton';
import { EmptyState } from '../primitives/EmptyState';
import { ErrorState } from '../primitives/ErrorState';
import { CategoryGlyph, PALETTE } from '../primitives/CategoryGlyph';
import { Dialog, useDialogClose } from '../primitives/Dialog';
import { DrawerHead } from '../shared/DrawerHead';
import { DUE_LABEL, InvestmentForm, KIND_META, KIND_ORDER, subtypeLabel } from '../shared/InvestmentForm';
import { UploadStatement } from '../shared/UploadStatement';
import { Icon } from '../primitives/Icon';

/** "Matures in 20 days", "Premium due tomorrow", "Matured 3 days ago". */
export function dueWhen(d: InvestmentDue): string {
  const n = daysUntil(d.date);
  const what = DUE_LABEL[d.what];
  if (n === 0) return `${what} today`;
  if (n > 0) return `${what} ${n === 1 ? 'tomorrow' : `in ${n} days`}`;
  const ago = -n === 1 ? '1 day ago' : `${-n} days ago`;
  return d.what === 'matures' ? `Matured ${ago}` : `${what} ${ago}`;
}

export function GainText({ gain, pct }: { gain: number; pct: number | null }) {
  if (gain === 0) return <span className="muted">no gain yet</span>;
  return (
    <span style={{ color: gain > 0 ? 'var(--mint-700)' : 'var(--red-600)' }}>
      {gain > 0 ? '+' : '−'}
      <Money amount={rs(Math.abs(gain))} interactive={false} />
      {pct !== null && ` (${gain > 0 ? '+' : ''}${pct.toFixed(1)}%)`}
    </span>
  );
}

export function InvestmentsPage() {
  const list = useApi<Investment[]>('/investments');
  const sum = useApi<InvestmentSummary>('/investments/summary');
  const [adding, setAdding] = useState(false);
  const [rates, setRates] = useState(false);
  const [showClosed, setShowClosed] = useState(false);
  const [importing, setImporting] = useState(false);
  const cas = useApi<CasSummary[]>('/investments/cas');
  const drafts = (cas.data ?? []).filter((c) => c.status === 'draft');
  const data = list.data;
  const s = sum.data;
  const active = (data ?? []).filter((i) => i.status === 'active');
  const closed = (data ?? []).filter((i) => i.status === 'closed');
  const hasGold = active.some((i) => i.kind === 'gold');
  const hasFunds = active.some((i) => i.kind === 'mf');

  return (
    <div className="content-wrap fade-in">
      <div className="page-head">
        <div>
          <h1>Investments</h1>
          <p>What you own, what you put in, what it&apos;s worth today and what&apos;s coming up.</p>
        </div>
        <div className="actions">
          {(hasGold || s?.rates.gold_24k) && (
            <Button variant="ghost" icon="gem" onClick={() => setRates(true)}>Gold rate</Button>
          )}
          <Button variant="secondary" icon="file-up" onClick={() => setImporting(true)}>Import CAS</Button>
          <Button variant="primary" icon="plus" onClick={() => setAdding(true)}>Add investment</Button>
        </div>
      </div>
      {drafts.map((c) => (
        <div key={c.id} className="note info" style={{ marginBottom: 12 }}>
          <Icon name="file-search" size={15} />
          <span>
            A mutual fund statement is waiting for review: <b>{c.filename}</b> ({c.funds} fund{c.funds === 1 ? '' : 's'}, {c.rows} transactions).{' '}
            <Link href={`/investments/cas/${c.id}`}><b>Review it</b></Link>
          </span>
        </div>
      ))}
      {hasFunds && <NavLine />}

      {list.error || sum.error ? (
        <div className="card"><ErrorState message={(list.error || sum.error)!} onRetry={() => { list.reload(); sum.reload(); }} /></div>
      ) : !data || !s ? (
        <>
          <div className="grid-3 stat-grid"><Skeleton variant="stat" count={3} /></div>
          <Skeleton variant="block" height={260} />
        </>
      ) : data.length === 0 ? (
        <div className="card">
          <EmptyState
            icon="trending-up"
            title="No investments yet"
            body="Add FDs, RDs, Post Office schemes, PPF / EPF / NPS, insurance policies, money lent, chits, gold, shares, crypto or property. Each one counts in your net worth."
            action={{ label: 'Add investment', onClick: () => setAdding(true) }}
          />
        </div>
      ) : (
        <>
          <div className="grid-3 stat-grid">
            <StatCard
              lbl="Value today"
              icon="trending-up"
              val={<Money amount={rs(s.value)} compact />}
              sub={`${s.count} active investment${s.count === 1 ? '' : 's'} · counted in net worth`}
            />
            <StatCard
              lbl="Put in"
              icon="arrow-down-to-line"
              val={<Money amount={rs(s.invested)} compact />}
              sub={<>Gain <GainText gain={s.gain} pct={s.invested > 0 ? (s.gain * 100) / s.invested : null} /></>}
            />
            <StatCard
              lbl="Coming up"
              icon="calendar-clock"
              val={String(s.dues.length)}
              sub={s.dues.length ? s.dues.slice(0, 2).map((d) => `${d.name}: ${dueWhen(d).toLowerCase()}`).join(' · ') : 'Nothing in the next 30 days'}
            />
          </div>

          {s.by_kind.length > 1 && <Split s={s} />}

          {s.dues.length > 0 && (
            <div className="card" style={{ marginBottom: 16 }}>
              <div className="inv-group-head"><span>Coming up · next 30 days</span></div>
              {s.dues.map((d) => (
                <Link key={`${d.account_id}-${d.what}-${d.date}`} href={`/investments/${d.account_id}`} className="inv-row">
                  <CategoryGlyph icon={KIND_META[d.kind].icon} color={KIND_META[d.kind].color} size={34} />
                  <div className="mid">
                    <div className="nm">{d.name}</div>
                    <div className="sub" style={{ color: d.overdue ? 'var(--red-600)' : undefined }}>{dueWhen(d)} · {fmtDate(d.date)}</div>
                  </div>
                  <div className="fig-r figure"><Money amount={rs(d.amount)} interactive={false} /></div>
                </Link>
              ))}
            </div>
          )}

          <div className="card">
            {KIND_ORDER.filter((k) => active.some((i) => i.kind === k)).map((k) => (
              <Group key={k} kind={k} items={active.filter((i) => i.kind === k)} />
            ))}
            {active.length === 0 && <div className="muted" style={{ padding: 18 }}>All your investments are closed.</div>}
          </div>

          {closed.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <Button variant="ghost" size="sm" onClick={() => setShowClosed((x) => !x)}>
                {showClosed ? 'Hide' : 'Show'} {closed.length} closed
              </Button>
              {showClosed && (
                <div className="card" style={{ marginTop: 8, opacity: 0.8 }}>
                  {closed.map((i) => <Row key={i.id} i={i} />)}
                </div>
              )}
            </div>
          )}
        </>
      )}
      {adding && <InvestmentForm onClose={() => setAdding(false)} onImportCas={() => setImporting(true)} />}
      {importing && <UploadStatement cas onClose={() => setImporting(false)} />}
      {rates && s && <RatesDialog rates={s.rates} onClose={() => setRates(false)} />}
    </div>
  );
}

/** When fund prices were last downloaded, with a button to get them now. */
function NavLine() {
  const { bump } = useShell();
  const st = useApi<NavStatus>('/investments/nav/status');
  const [busy, setBusy] = useState(false);
  const refresh = async () => {
    setBusy(true);
    try {
      await api('/investments/nav/refresh', { method: 'POST' });
    } catch {
      // the status line shows the error
    }
    bump();
    setBusy(false);
  };
  const s = st.data;
  return (
    <div className="muted" style={{ fontSize: 12.5, marginBottom: 12, display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
      <span>
        {s?.last_run
          ? `Fund prices from AMFI, last checked ${fromUtc(s.last_run).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}`
          : 'Fund prices come from AMFI every evening after 9 pm.'}
        {s?.error && <span style={{ color: 'var(--red-600)' }}> · {s.error}</span>}
        {s && s.not_found.length > 0 && ` · not found: ${s.not_found.join(', ')}`}
      </span>
      <Button variant="ghost" size="sm" icon="refresh-cw" onClick={refresh} disabled={busy}>{busy ? 'Getting prices…' : 'Update prices now'}</Button>
    </div>
  );
}

function Split({ s }: { s: InvestmentSummary }) {
  const parts = s.by_kind.filter((k) => k.value > 0);
  const total = parts.reduce((a, k) => a + k.value, 0);
  if (!total) return null;
  return (
    <div className="card card-pad" style={{ marginBottom: 16 }}>
      <div className="split-bar" role="img" aria-label="Value by type">
        {parts.map((k) => (
          <span key={k.kind} style={{ width: `${(k.value * 100) / total}%`, background: PALETTE[KIND_META[k.kind].color] }} title={KIND_META[k.kind].label} />
        ))}
      </div>
      <div className="split-legend">
        {parts.map((k) => (
          <span key={k.kind}>
            <i style={{ background: PALETTE[KIND_META[k.kind].color] }} />
            {KIND_META[k.kind].label} <b>{Math.round((k.value * 100) / total)}%</b>
          </span>
        ))}
      </div>
    </div>
  );
}

function Group({ kind, items }: { kind: InvestmentKind; items: Investment[] }) {
  const value = items.reduce((a, i) => a + i.value, 0);
  return (
    <>
      <div className="inv-group-head">
        <span>{KIND_META[kind].label}</span>
        <span className="figure"><Money amount={rs(value)} interactive={false} /></span>
      </div>
      {items.map((i) => <Row key={i.id} i={i} />)}
    </>
  );
}

function Row({ i }: { i: Investment }) {
  const meta = KIND_META[i.kind];
  const sub = [
    subtypeLabel(i.kind, i.subtype),
    i.person,
    i.institution,
    i.fund ? `${i.fund.units.toLocaleString('en-IN', { maximumFractionDigits: 3 })} units` : null,
  ].filter(Boolean).join(' · ');
  const due = i.next_due;
  return (
    <Link href={`/investments/${i.id}`} className="inv-row">
      <CategoryGlyph icon={meta.icon} color={meta.color} size={36} />
      <div className="mid">
        <div className="nm">{i.name}</div>
        <div className="sub">
          {sub && <span>{sub}</span>}
          {i.status === 'closed' && <span className="badge neutral">Closed {i.closed_on ? fmtDate(i.closed_on) : ''}</span>}
          {due && daysUntil(due.date) <= 30 && (
            <span className={`badge ${due.overdue ? 'red' : 'cau'}`}>{dueWhen(due)}</span>
          )}
          {i.stale && <span className="badge neutral">Value is old</span>}
          {i.no_price && <span className="badge neutral">{i.kind === 'gold' ? 'No gold rate yet' : 'No price yet'}</span>}
          {i.kind === 'insurance' && i.subtype === 'term' && <span className="badge neutral">Cover only</span>}
        </div>
      </div>
      <div className="fig-r">
        <div className="figure" style={{ fontWeight: 600, color: i.value < 0 ? 'var(--red-600)' : undefined }}>
          {i.value < 0 && '−'}
          <Money amount={rs(Math.abs(i.value))} interactive={false} />
        </div>
        <div style={{ fontSize: 12 }}>
          {i.owed > 0 ? <span className="muted">still to pay</span> : <GainText gain={i.gain} pct={i.gain_pct} />}
        </div>
      </div>
    </Link>
  );
}

// ---------------------------------------------------------------- gold / silver rate

export function RatesDialog({ rates, onClose }: { rates: MetalRates; onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label="Gold and silver rate" width={440}>
      <RatesBody rates={rates} />
    </Dialog>
  );
}

function RatesBody({ rates }: { rates: MetalRates }) {
  const close = useDialogClose();
  const { bump } = useShell();
  const [gold, setGold] = useState(rates.gold_24k != null ? paiseToInput(rates.gold_24k) : '');
  const [silver, setSilver] = useState(rates.silver != null ? paiseToInput(rates.silver) : '');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const g = gold.trim() ? toPaise(gold) : null;
    const sv = silver.trim() ? toPaise(silver) : null;
    if ((gold.trim() && g === null) || (silver.trim() && sv === null)) return setError('Rates must be numbers, e.g. 7250 or 7250.50');
    setSaving(true);
    try {
      await api('/investments/rates', { method: 'PUT', body: { gold_24k: g, silver: sv } });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };
  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead title="Gold and silver rate" sub={rates.date ? `Last updated ${fmtDate(rates.date)}` : 'Not entered yet'} lead={<CategoryGlyph icon="gem" color="amber" size={42} />} />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        <div className="field">
          <label htmlFor="rt-gold">Gold, 24 carat — ₹ per gram</label>
          <input id="rt-gold" className="inp" inputMode="decimal" value={gold} onChange={(e) => setGold(e.target.value)} placeholder="e.g. 7650" />
          <div className="hint">22k, 18k and 14k are worked out from it. SGBs and digital gold use the 24k rate.</div>
        </div>
        <div className="field">
          <label htmlFor="rt-silver">Silver (999) — ₹ per gram</label>
          <input id="rt-silver" className="inp" inputMode="decimal" value={silver} onChange={(e) => setSilver(e.target.value)} placeholder="e.g. 95" />
        </div>
        <div className="hint">Saved with today&apos;s date. MoneyMap doesn&apos;t look prices up on the internet.</div>
      </div>
      <div className="drawer-foot">
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        <Button variant="primary" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save rate'}</Button>
      </div>
    </form>
  );
}
