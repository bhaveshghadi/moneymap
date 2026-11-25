'use client';
import { useRef, useState, type RefObject } from 'react';
import Link from 'next/link';
import { useApi } from '../contexts/ShellCtx';
import { useTxn } from '../contexts/TxnCtx';
import type { CardCycle, CardDetail, Txn, TxnPage } from '../lib/types';
import { daysUntil, dueText, fmtDate, fmtDayHead, rs, todayIso } from '../lib/format';
import { qs } from '../lib/api';
import { Button } from '../primitives/Button';
import { Money } from '../primitives/Money';
import { StatCard } from '../primitives/StatCard';
import { Skeleton } from '../primitives/Skeleton';
import { ErrorState } from '../primitives/ErrorState';
import { EmptyState } from '../primitives/EmptyState';
import { CategoryGlyph } from '../primitives/CategoryGlyph';
import { Icon } from '../primitives/Icon';
import { TxnRow } from '../shared/TxnRow';
import { CardForm, CycleBadge, cycleText, networkLabel, shortRange } from '../shared/CardForm';
import { UsageBar, payDefaults } from './CreditCards';
import { EmiList } from '../shared/EmiList';
import { PageHelp } from '../shared/PageHelp';

function statementIn(iso: string): string {
  const n = daysUntil(iso);
  return n <= 0 ? 'today' : n === 1 ? 'tomorrow' : `in ${n} days`;
}

/** "This cycle" / "Last statement" / "2 statements ago" by position (newest first). */
function cycleName(i: number): string {
  return i === 0 ? 'This cycle (not billed yet)' : i === 1 ? 'Last statement' : `${i} statements ago`;
}

function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function DayGroups({ items, onOpen }: { items: Txn[]; onOpen: (t: Txn) => void }) {
  const groups: { date: string; items: Txn[] }[] = [];
  for (const t of items) {
    const g = groups[groups.length - 1];
    if (g && g.date === t.date) g.items.push(t);
    else groups.push({ date: t.date, items: [t] });
  }
  return (
    <div>
      {groups.map((g) => (
        <div key={g.date}>
          <div className="day-head">{fmtDayHead(g.date)}</div>
          {g.items.map((t) => (
            <TxnRow key={t.id} t={t} onClick={() => onOpen(t)} showDate={false} />
          ))}
        </div>
      ))}
    </div>
  );
}

/** One billing cycle at a time: which statement it is, what it means in plain words,
 * its spends, and (for a billed cycle) the payments made towards it. */
function CycleViewer({
  card,
  selected,
  onSelect,
  viewerRef,
}: {
  card: CardDetail;
  selected: string | null;
  onSelect: (sd: string) => void;
  viewerRef: RefObject<HTMLDivElement | null>;
}) {
  const { openTxn } = useTxn();
  const cycles = card.cycles; // newest first; [0] is the open cycle
  const idx = Math.max(0, cycles.findIndex((c) => c.statement_date === (selected ?? card.current.statement_date)));
  const c: CardCycle = cycles[idx] ?? card.current;
  const billed = c.status !== 'unbilled';
  const newer = idx > 0 ? cycles[idx - 1] : null;
  // the cycle's transactions (a charge posted late is listed with the statement it's printed on)
  const spends = useApi<{ items: Txn[] }>(`/cards/${card.id}/cycle${qs({ start: c.start, end: c.statement_date })}`);
  // payments towards a billed statement: money into the card after its statement date, until the next statement
  const payWindowEnd = newer ? newer.statement_date : todayIso();
  const after = useApi<TxnPage>(
    billed ? `/transactions${qs({ account_id: card.id, date_from: addDays(c.statement_date, 1), date_to: payWindowEnd, limit: 200 })}` : null,
  );
  const isPayment = (t: Txn) => t.type === 'transfer' && t.destination.id === card.id;
  const payments = (after.data?.items ?? []).filter(isPayment);
  // bill payments made during this cycle paid the previous statement: they're listed there
  const cycleItems = (spends.data?.items ?? []).filter((t) => !isPayment(t));
  const older = cycles.slice(2);

  const chip = (i: number, label: string) =>
    cycles[i] ? (
      <button type="button" role="radio" aria-checked={idx === i} className={`chip ${idx === i ? 'on' : ''}`} onClick={() => onSelect(cycles[i].statement_date)}>
        {label}
      </button>
    ) : null;

  return (
    <div ref={viewerRef} className="card card-pad" style={{ marginBottom: 16, display: 'flex', flexDirection: 'column', gap: 14, scrollMarginTop: 80 }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }} role="radiogroup" aria-label="Billing cycle">
        {chip(0, 'This cycle')}
        {chip(1, 'Last statement')}
        {older.length > 0 && (
          <select
            className="inp"
            aria-label="Older statements"
            style={{ width: 'auto' }}
            value={idx >= 2 ? c.statement_date : ''}
            onChange={(e) => e.target.value && onSelect(e.target.value)}
          >
            <option value="">Older statements…</option>
            {older.map((o) => (
              <option key={o.statement_date} value={o.statement_date}>{shortRange(o.start, o.statement_date)}</option>
            ))}
          </select>
        )}
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontFamily: 'var(--font-display)', fontWeight: 650, fontSize: 18, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            {shortRange(c.start, c.statement_date)} <CycleBadge status={c.status} minPaid={c.min_paid} />
          </div>
          <div className="muted" style={{ fontSize: 13.5, marginTop: 4, maxWidth: 620 }}>
            {billed ? (
              <>
                Spends from <b>{fmtDate(c.start)}</b> to <b>{fmtDate(c.statement_date)}</b> were billed on {fmtDate(c.statement_date)}
                {c.total_due > 0 ? (
                  <>
                    {' '}— <b><Money amount={rs(c.total_due)} interactive={false} /></b> to pay by <b>{fmtDate(c.due_date)}</b>
                    {c.status === 'paid' && c.paid_on ? `, paid in full on ${fmtDate(c.paid_on)}.` : '.'}
                  </>
                ) : (
                  ' — nothing to pay.'
                )}
              </>
            ) : (
              <>
                Spends from <b>{fmtDate(c.start)}</b> until <b>{fmtDate(c.statement_date)}</b>. They&apos;ll be billed on{' '}
                {fmtDate(c.statement_date)} ({statementIn(c.statement_date)}) and are due by <b>{fmtDate(c.due_date)}</b>.
              </>
            )}
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 22, flexWrap: 'wrap' }}>
        {[
          ['Spent', c.spent],
          ...(billed
            ? ([
                ['Total due', c.total_due],
                ['Minimum due', c.min_due],
                ['Paid towards it', c.paid],
              ] as [string, number][])
            : []),
        ].map(([label, v]) => (
          <div key={label as string}>
            <div className="muted" style={{ fontSize: 11.5, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</div>
            <div className="fig" style={{ fontSize: 16 }}><Money amount={rs(v as number)} interactive={false} /></div>
          </div>
        ))}
      </div>

      <div>
        <div style={{ fontWeight: 650, marginBottom: 4 }}>
          Spends and refunds in this cycle{spends.data ? ` (${cycleItems.length})` : ''}
        </div>
        {!spends.data ? (
          <Skeleton variant="row" count={3} />
        ) : cycleItems.length === 0 ? (
          <EmptyState icon="receipt" title="No transactions in this cycle" body={billed ? 'Import this statement to add its spends.' : 'Add card spends as they happen, or import the card statement later.'} />
        ) : (
          <DayGroups items={cycleItems} onOpen={openTxn} />
        )}
      </div>

      {billed && (
        <div>
          <div style={{ fontWeight: 650, marginBottom: 4 }}>Payments towards this statement</div>
          <div className="muted" style={{ fontSize: 12.5, marginBottom: 6 }}>
            Money paid into the card after {fmtDate(c.statement_date)}
            {newer ? ` and before the next statement (${fmtDate(newer.statement_date)})` : ''}.
          </div>
          {!after.data ? (
            <Skeleton variant="row" count={1} />
          ) : payments.length === 0 ? (
            <div className="muted" style={{ fontSize: 13 }}>No payments yet.</div>
          ) : (
            <DayGroups items={payments} onOpen={openTxn} />
          )}
        </div>
      )}
    </div>
  );
}


export function CardDetailPage({ id }: { id: number }) {
  const { data, error, reload } = useApi<CardDetail>(`/cards/${id}`);
  const { newTxn } = useTxn();
  const [editing, setEditing] = useState(false);
  const [selected, setSelected] = useState<string | null>(null); // statement date of the cycle shown
  const viewerRef = useRef<HTMLDivElement | null>(null);
  const cur = data?.current;

  if (error) return <div className="content-wrap"><div className="card"><ErrorState message={error} onRetry={reload} /></div></div>;
  if (!data || !cur) {
    return (
      <div className="content-wrap">
        <Skeleton variant="block" height={120} />
        <div style={{ height: 16 }} />
        <Skeleton variant="block" height={260} />
      </div>
    );
  }
  const last = data.last_statement;

  return (
    <div className="content-wrap fade-in">
      <div className="page-head">
        <div style={{ display: 'flex', gap: 14, alignItems: 'center', minWidth: 0 }}>
          <CategoryGlyph icon="credit-card" color={data.color} size={46} />
          <div style={{ minWidth: 0 }}>
            <div className="muted" style={{ fontSize: 12.5 }}>
              <Link href="/credit-cards">Credit cards</Link> /
            </div>
            <h1 style={{ margin: 0 }}>{data.name} <PageHelp id="card" /></h1>
            <p style={{ margin: 0 }}>
              {[data.bank, networkLabel(data.network), data.last4 ? `•••• ${data.last4}` : null].filter(Boolean).join(' · ')}
              {data.bank || data.network || data.last4 ? ' · ' : ''}
              {cycleText(data)}
            </p>
          </div>
        </div>
        <div className="actions">
          <Button variant="ghost" icon="settings" onClick={() => setEditing(true)}>Edit</Button>
          <Button variant="secondary" icon="plus" onClick={() => newTxn({ type: 'withdrawal', source_id: data.id })} disabled={!data.active}>Add spend</Button>
          <Button variant="primary" icon="banknote" onClick={() => newTxn(payDefaults(data))} disabled={!data.active}>Pay bill</Button>
        </div>
      </div>

      {data.due_status === 'overdue' && data.next_due_date && (
        <div className="note warn" style={{ marginBottom: 16 }}>
          <Icon name="triangle-alert" size={15} />
          <span>
            A statement was due on <b>{fmtDate(data.next_due_date)}</b> and isn&apos;t fully paid —{' '}
            <b><Money amount={rs(data.due_now)} interactive={false} /></b> is still due. Banks charge interest and a late fee on
            overdue cards; paying at least the minimum avoids the late fee.
          </span>
        </div>
      )}

      <div className="grid-3 stat-grid">
        <StatCard
          lbl="Owed now"
          icon="credit-card"
          val={<Money amount={rs(data.owed)} compact />}
          sub={
            data.credit_limit > 0 ? (
              <span style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <span>
                  {data.utilisation}% of <Money amount={rs(data.credit_limit)} interactive={false} /> limit used ·{' '}
                  <Money amount={rs(data.available ?? 0)} interactive={false} /> available
                  {data.emi_outstanding > 0 && (
                    <> (including <Money amount={rs(data.emi_outstanding)} interactive={false} /> in EMIs)</>
                  )}
                </span>
                <UsageBar pct={data.utilisation ?? 0} />
              </span>
            ) : (
              'No credit limit set'
            )
          }
        />
        <StatCard
          lbl="To pay"
          icon="calendar-clock"
          val={<Money amount={rs(data.due_now)} compact />}
          accent={data.due_status === 'overdue' ? 'var(--red-600)' : undefined}
          sub={
            data.due_now > 0 && data.next_due_date ? (
              <>
                Due {fmtDate(data.next_due_date)} · {dueText(data.next_due_date)}
                {last && last.min_due > last.paid && (
                  <> · minimum <Money amount={rs(last.min_due - last.paid)} interactive={false} /></>
                )}
              </>
            ) : last
                ? `Statement of ${fmtDate(last.statement_date)} is settled`
                : 'No statement yet'
          }
        />
        <StatCard
          lbl="Best day to swipe"
          icon="sparkles"
          val={fmtDate(data.best_swipe_day)}
          sub={`Spends from this day are due ${data.interest_free_days} days later — the longest interest-free time`}
        />
      </div>

      <CycleViewer card={data} selected={selected} onSelect={setSelected} viewerRef={viewerRef} />

      <EmiList card={data} />

      <div className="card">
        <div style={{ padding: '16px 18px 0' }}>
          <div style={{ fontFamily: 'var(--font-display)', fontWeight: 650, fontSize: 16 }}>All statements</div>
          <div className="muted" style={{ fontSize: 12.5 }}>Click a statement to see its transactions above.</div>
        </div>
        <div className="tbl-wrap" style={{ padding: '10px 6px 6px' }}>
          <table className="tbl">
            <thead>
              <tr>
                <th>Billing cycle</th>
                <th className="r hide-sm">Spent</th>
                <th className="r">Total due</th>
                <th className="r hide-sm">Paid</th>
                <th>Pay by</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {data.cycles.map((c, i) => (
                <tr
                  key={c.statement_date}
                  className="click"
                  onClick={() => {
                    setSelected(c.statement_date);
                    viewerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                  }}
                  style={c.statement_date === (selected ?? data.current.statement_date) ? { background: 'var(--bg-subtle)' } : undefined}
                >
                  <td>
                    <div style={{ fontWeight: 600 }}>{shortRange(c.start, c.statement_date)}</div>
                    <div className="muted" style={{ fontSize: 12 }}>
                      {cycleName(i)}
                      {c.official && <span title="Total, minimum and due date from the imported statement"> · from statement</span>}
                    </div>
                  </td>
                  <td className="r figure hide-sm"><Money amount={rs(c.spent)} interactive={false} /></td>
                  <td className="r figure">{c.status === 'unbilled' ? <span className="muted">not billed yet</span> : <Money amount={rs(c.total_due)} interactive={false} />}</td>
                  <td className="r figure hide-sm">{c.status === 'unbilled' ? <span className="muted">—</span> : <Money amount={rs(c.paid)} interactive={false} />}</td>
                  <td>{fmtDate(c.due_date)}</td>
                  <td><CycleBadge status={c.status} minPaid={c.min_paid} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {editing && <CardForm card={data} onClose={() => setEditing(false)} />}
    </div>
  );
}
