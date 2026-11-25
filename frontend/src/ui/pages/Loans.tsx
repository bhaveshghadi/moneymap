'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname, useSearchParams } from 'next/navigation';
import { api, replaceQuery } from '../lib/api';
import { useApi, useShell } from '../contexts/ShellCtx';
import type { Loan } from '../lib/types';
import { dueText, fmtDate, rs } from '../lib/format';
import { Button } from '../primitives/Button';
import { Money } from '../primitives/Money';
import { StatCard } from '../primitives/StatCard';
import { Skeleton } from '../primitives/Skeleton';
import { EmptyState } from '../primitives/EmptyState';
import { ErrorState } from '../primitives/ErrorState';
import { CategoryGlyph } from '../primitives/CategoryGlyph';
import { Progress } from '../shared/Progress';
import { LoanForm, kindLabel } from '../shared/LoanForm';
import { LoanStatementDialog } from '../shared/LoanStatement';
import { PageHelp } from '../shared/PageHelp';

export function LoansPage() {
  const { data, error, reload } = useApi<Loan[]>('/loans');
  const [adding, setAdding] = useState(false);
  const [statement, setStatement] = useState<{ attachmentId?: number; fileRef?: string } | null>(null);
  const sp = useSearchParams();
  const pathname = usePathname();
  // /loans?attachment=12 or ?file=<ref>: a loan statement opened from the Inbox or a statement upload.
  // Applied while rendering, once per new URL (as on the Accounts page).
  const search = sp.toString();
  const [seenSearch, setSeenSearch] = useState<string | null>(null);
  if (search !== seenSearch) {
    setSeenSearch(search);
    const att = Number(sp.get('attachment')) || undefined;
    const file = sp.get('file') || undefined;
    if (att || file) setStatement({ attachmentId: att, fileRef: file });
  }
  // …then drop it from the address bar so a reload doesn't open it again
  useEffect(() => {
    if (sp.get('attachment') || sp.get('file')) replaceQuery(pathname, '');
  }, [sp, pathname]);
  const active = (data ?? []).filter((l) => l.status === 'active');
  const owed = active.reduce((s, l) => s + l.outstanding, 0);
  const monthly = active.reduce((s, l) => s + l.emi, 0);
  const overdue = active.filter((l) => l.next?.overdue);

  return (
    <div className="content-wrap fade-in">
      <div className="page-head">
        <div>
          <h1>Loans <PageHelp id="loans" /></h1>
          <p>What&apos;s left on each loan, the next EMI, and the full repayment schedule.</p>
        </div>
        <div className="actions">
          <Button variant="secondary" icon="file-search" onClick={() => setStatement({})}>Add from statement</Button>
          <Button variant="primary" icon="plus" onClick={() => setAdding(true)}>Add loan</Button>
        </div>
      </div>

      {error ? (
        <div className="card"><ErrorState message={error} onRetry={reload} /></div>
      ) : !data ? (
        <>
          <div className="grid-3 stat-grid"><Skeleton variant="stat" count={3} /></div>
          <Skeleton variant="block" height={200} />
        </>
      ) : data.length === 0 ? (
        <div className="card">
          <EmptyState
            icon="hand-coins"
            title="No loans yet"
            body="Add a home, car, personal or any other loan. MoneyMap shows what's left, the next EMI and the full schedule — and counts it in your net worth and emergency fund."
            action={{ label: 'Add loan', onClick: () => setAdding(true) }}
          />
        </div>
      ) : (
        <>
          <div className="grid-3 stat-grid">
            <StatCard lbl="Left to pay" icon="hand-coins" val={<Money amount={rs(owed)} compact />} sub={`${active.length} active loan${active.length === 1 ? '' : 's'}`} />
            <StatCard lbl="EMIs a month" icon="calendar-range" val={<Money amount={rs(monthly)} compact />} sub="Counted as an essential cost in the emergency fund" />
            <StatCard
              lbl="Overdue"
              icon="triangle-alert"
              val={String(overdue.length)}
              accent={overdue.length ? 'var(--red-600)' : undefined}
              sub={overdue.length ? overdue.map((l) => l.name).join(', ') : 'No EMI waiting to be recorded'}
            />
          </div>
          <div className="grid-2e">
            {data.map((l) => (
              <LoanCard key={l.id} l={l} />
            ))}
          </div>
        </>
      )}
      {adding && <LoanForm onClose={() => setAdding(false)} />}
      {statement && <LoanStatementDialog attachmentId={statement.attachmentId} fileRef={statement.fileRef} onClose={() => setStatement(null)} />}
    </div>
  );
}

function LoanCard({ l }: { l: Loan }) {
  const { bump } = useShell();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const borrowed = l.principal ?? l.total_payable;
  const record = async () => {
    setBusy(true);
    setError(null);
    try {
      await api(`/loans/${l.id}/pay`, { method: 'POST', body: {} });
      bump();
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(false);
  };
  return (
    <div className="card card-pad" style={{ display: 'flex', flexDirection: 'column', gap: 12, opacity: l.status === 'active' ? 1 : 0.6 }}>
      <Link href={`/loans/${l.id}`} style={{ display: 'flex', gap: 12, alignItems: 'center', color: 'inherit', textDecoration: 'none' }}>
        <CategoryGlyph icon="hand-coins" color="coral" size={40} />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontFamily: 'var(--font-display)', fontWeight: 650, fontSize: 16 }}>{l.name}</div>
          <div className="muted" style={{ fontSize: 12.5 }}>{[kindLabel(l.kind), l.lender].filter(Boolean).join(' · ')}</div>
        </div>
        {l.status === 'closed' ? <span className="badge mint">Closed</span> : l.next?.overdue ? <span className="badge red">EMI overdue</span> : null}
      </Link>
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, marginBottom: 6 }}>
          <span>
            <span className="fig" style={{ fontSize: 20 }}><Money amount={rs(l.outstanding)} /></span>
            <span className="muted" style={{ fontSize: 12.5 }}> left</span>
          </span>
          <span className="muted" style={{ fontSize: 12.5 }}>{l.paid_count} of {l.tenure} EMIs paid</span>
        </div>
        <Progress value={borrowed - l.outstanding} max={borrowed} savings />
      </div>
      <div style={{ fontSize: 13, display: 'flex', flexDirection: 'column', gap: 3 }}>
        {l.next ? (
          <span>
            Next EMI <b><Money amount={rs(l.next.emi)} interactive={false} /></b> · {fmtDate(l.next.date)} ·{' '}
            <span style={{ color: l.next.overdue ? 'var(--red-600)' : undefined }}>{dueText(l.next.date)}</span>
          </span>
        ) : (
          <span className="muted">No EMIs left</span>
        )}
        <span className="muted">Ends {fmtDate(l.end_date)} · {l.count_mode === 'whole_emi' ? 'whole EMI counts as spending' : 'only interest counts as spending'}</span>
      </div>
      {error && <div className="form-error" role="alert">{error}</div>}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {l.next && (
          <Button variant="secondary" size="sm" icon="check" onClick={record} disabled={busy || !l.pay_from_id} title={l.pay_from_id ? undefined : 'Set the account the EMI is paid from on the loan page'}>
            {busy ? 'Recording…' : `Record EMI ${l.next.n}`}
          </Button>
        )}
        <span className="spacer" style={{ flex: 1 }} />
        <Link href={`/loans/${l.id}`} className="btn btn-ghost btn-sm" style={{ textDecoration: 'none' }}>Schedule</Link>
      </div>
    </div>
  );
}
