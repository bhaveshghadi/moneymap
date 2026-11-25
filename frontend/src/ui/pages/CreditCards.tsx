'use client';
import { useState } from 'react';
import Link from 'next/link';
import { useApi } from '../contexts/ShellCtx';
import { useTxn } from '../contexts/TxnCtx';
import type { Card } from '../lib/types';
import { dueText, fmtDate, rs } from '../lib/format';
import { Button } from '../primitives/Button';
import { Money } from '../primitives/Money';
import { StatCard } from '../primitives/StatCard';
import { Skeleton } from '../primitives/Skeleton';
import { EmptyState } from '../primitives/EmptyState';
import { ErrorState } from '../primitives/ErrorState';
import { CategoryGlyph } from '../primitives/CategoryGlyph';
import { CardForm, CycleBadge, networkLabel, ruleText, shortRange } from '../shared/CardForm';
import { ConvertCardBillsNote } from '../shared/ConvertCardBills';
import { PageHelp } from '../shared/PageHelp';

/** Limit-used bar: amber above 30%, red above 75%. */
export function UsageBar({ pct }: { pct: number }) {
  const color = pct > 75 ? 'var(--red-500)' : pct > 30 ? 'var(--amber-500)' : 'var(--mint-500)';
  return (
    <div className="track" style={{ height: 8, borderRadius: 999, background: 'var(--bg-sunken)', overflow: 'hidden' }}>
      <i style={{ display: 'block', height: '100%', borderRadius: 999, width: `${Math.min(100, pct)}%`, background: color }} />
    </div>
  );
}

export function payDefaults(c: Card) {
  return {
    type: 'transfer' as const,
    destination_id: c.id,
    amount: c.due_now > 0 ? c.due_now : c.owed > 0 ? c.owed : undefined,
    description: `${c.name} bill payment`,
  };
}

export function CreditCardsPage() {
  const { data, error, reload } = useApi<Card[]>('/cards');
  const { newTxn } = useTxn();
  const [adding, setAdding] = useState(false);
  const active = (data ?? []).filter((c) => c.active);
  const owed = active.reduce((s, c) => s + c.owed, 0);
  const limit = active.reduce((s, c) => s + c.credit_limit, 0);
  const due = active.filter((c) => c.due_now > 0);
  const overdue = due.filter((c) => c.due_status === 'overdue');

  return (
    <div className="content-wrap fade-in">
      <div className="page-head">
        <div>
          <h1>Credit cards <PageHelp id="credit-cards" /></h1>
          <p>Spending on a card counts when you swipe; paying the bill is a transfer from your bank, not spending.</p>
        </div>
        <div className="actions">
          <Button variant="primary" icon="plus" onClick={() => setAdding(true)}>Add card</Button>
        </div>
      </div>

      {error ? (
        <div className="card"><ErrorState message={error} onRetry={reload} /></div>
      ) : !data ? (
        <>
          <div className="grid-3 stat-grid"><Skeleton variant="stat" count={3} /></div>
          <Skeleton variant="block" height={220} />
        </>
      ) : data.length === 0 ? (
        <div className="card">
          <EmptyState
            icon="credit-card"
            title="No credit cards yet"
            body="Add a card with its statement day and due date. MoneyMap works out each billing cycle, what's due and when, and what you've paid."
            action={{ label: 'Add card', onClick: () => setAdding(true) }}
          />
        </div>
      ) : (
        <>
          <ConvertCardBillsNote cards={data} />
          <div className="grid-3 stat-grid">
            <StatCard
              lbl="Owed on cards"
              icon="credit-card"
              val={<Money amount={rs(owed)} compact />}
              sub={limit ? `${Math.round((owed * 100) / limit)}% of your total limit used` : `${active.length} active card${active.length === 1 ? '' : 's'}`}
            />
            <StatCard
              lbl="To pay now"
              icon="calendar-clock"
              val={<Money amount={rs(due.reduce((s, c) => s + c.due_now, 0))} compact />}
              sub={due.length ? due.map((c) => `${c.name} ${fmtDate(c.next_due_date!)}`).join(' · ') : 'No statement waiting to be paid'}
            />
            <StatCard
              lbl="Overdue"
              icon="triangle-alert"
              val={String(overdue.length)}
              accent={overdue.length ? 'var(--red-600)' : undefined}
              sub={overdue.length ? overdue.map((c) => c.name).join(', ') : 'All caught up'}
            />
          </div>

          <div className="grid-2e">
            {data.map((c) => (
              <div key={c.id} className="card card-pad" style={{ display: 'flex', flexDirection: 'column', gap: 12, opacity: c.active ? 1 : 0.55 }}>
                <Link href={`/credit-cards/${c.id}`} style={{ display: 'flex', gap: 12, alignItems: 'center', color: 'inherit', textDecoration: 'none' }}>
                  <CategoryGlyph icon="credit-card" color={c.color} size={40} />
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ fontFamily: 'var(--font-display)', fontWeight: 650, fontSize: 16 }}>{c.name}</div>
                    <div className="muted" style={{ fontSize: 12.5 }}>
                      {[c.bank, networkLabel(c.network), c.last4 ? `•••• ${c.last4}` : null].filter(Boolean).join(' · ') || ruleText(c)}
                    </div>
                  </div>
                  {c.due_status ? <CycleBadge status={c.due_status} /> : !c.active && <span className="badge neutral">Inactive</span>}
                </Link>
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, marginBottom: 6 }}>
                    <span>
                      <span className="fig" style={{ fontSize: 20 }}><Money amount={rs(c.owed)} /></span>
                      <span className="muted" style={{ fontSize: 12.5 }}> owed</span>
                    </span>
                    {c.credit_limit > 0 && (
                      <span className="muted" style={{ fontSize: 12.5 }}>
                        <Money amount={rs(c.available ?? 0)} interactive={false} /> available
                      </span>
                    )}
                  </div>
                  {c.utilisation !== null && <UsageBar pct={c.utilisation} />}
                </div>
                <div style={{ fontSize: 13, display: 'flex', flexDirection: 'column', gap: 3 }}>
                  {c.due_status === 'overdue' && c.next_due_date ? (
                    <span style={{ color: 'var(--red-600)' }}>
                      <b><Money amount={rs(c.due_now)} interactive={false} /></b> overdue — a payment was due {fmtDate(c.next_due_date)} (
                      {dueText(c.next_due_date)})
                    </span>
                  ) : c.last_statement && (
                    <span>
                      <span className="muted">Last statement ({shortRange(c.last_statement.start, c.last_statement.statement_date)}): </span>
                      {c.due_now > 0 && c.next_due_date ? (
                        <>
                          <b><Money amount={rs(c.due_now)} interactive={false} /></b> to pay by {fmtDate(c.next_due_date)} ·{' '}
                          <span style={{ color: c.due_status === 'overdue' ? 'var(--red-600)' : undefined }}>{dueText(c.next_due_date)}</span>
                        </>
                      ) : (
                        <span className="muted">nothing left to pay</span>
                      )}
                    </span>
                  )}
                  {c.emi_count > 0 && (
                    <span>
                      <span className="muted">EMIs: </span>
                      <Money amount={rs(c.emi_outstanding)} interactive={false} /> left on {c.emi_count} EMI{c.emi_count === 1 ? '' : 's'}
                    </span>
                  )}
                  <span>
                    <span className="muted">This cycle ({shortRange(c.current.start, c.current.statement_date)}): </span>
                    <Money amount={rs(c.current.spent)} interactive={false} /> spent so far
                    <span className="muted"> · billed {fmtDate(c.current.statement_date)}</span>
                  </span>
                </div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <Button variant="secondary" size="sm" icon="banknote" onClick={() => newTxn(payDefaults(c))} disabled={!c.active}>Pay</Button>
                  <Button variant="ghost" size="sm" icon="plus" onClick={() => newTxn({ type: 'withdrawal', source_id: c.id })} disabled={!c.active}>Add spend</Button>
                  <span className="spacer" style={{ flex: 1 }} />
                  <Link href={`/credit-cards/${c.id}`} className="btn btn-ghost btn-sm" style={{ textDecoration: 'none' }}>Details</Link>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {adding && <CardForm onClose={() => setAdding(false)} />}
    </div>
  );
}
