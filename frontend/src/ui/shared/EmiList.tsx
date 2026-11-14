'use client';
import { useState } from 'react';
import type { CardDetail, Emi } from '../lib/types';
import { api, qs } from '../lib/api';
import { fmtDate, rs, todayIso } from '../lib/format';
import { useShell } from '../contexts/ShellCtx';
import Link from 'next/link';
import { Button } from '../primitives/Button';
import { Money } from '../primitives/Money';
import { Progress } from './Progress';
import { EmiForm } from './EmiForm';

const KIND_LABEL: Record<Emi['kind'], string> = {
  converted: 'Converted purchase',
  checkout: 'EMI at checkout',
  existing: 'EMI',
};

/** The card's EMIs: progress, what's left, next instalment, interest paid. */
export function EmiList({ card }: { card: CardDetail }) {
  const [adding, setAdding] = useState(false);
  const active = card.emis.filter((e) => e.status === 'active');
  const closed = card.emis.filter((e) => e.status === 'closed');
  return (
    <div className="card card-pad" style={{ marginBottom: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontFamily: 'var(--font-display)', fontWeight: 650, fontSize: 16 }}>EMIs</div>
          <div className="muted" style={{ fontSize: 12.5 }}>
            {active.length > 0 ? (
              <>
                <Money amount={rs(card.emi_outstanding)} interactive={false} /> still to pay over {active.length} EMI
                {active.length === 1 ? '' : 's'} — the bank holds it back from your limit. Purchases count as spending once, in full.
              </>
            ) : (
              'Purchases you pay back in monthly instalments. Each purchase counts as spending once, in full; instalments are repayments.'
            )}
          </div>
        </div>
        <Button variant="secondary" size="sm" icon="plus" onClick={() => setAdding(true)} disabled={!card.active}>Add EMI</Button>
      </div>
      {active.map((e) => (
        <EmiRow key={e.id} e={e} cardId={card.id} />
      ))}
      {closed.length > 0 && (
        <details>
          <summary className="muted" style={{ fontSize: 13, cursor: 'pointer' }}>Finished EMIs ({closed.length})</summary>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 10 }}>
            {closed.map((e) => (
              <EmiRow key={e.id} e={e} cardId={card.id} />
            ))}
          </div>
        </details>
      )}
      {adding && <EmiForm card={card} onClose={() => setAdding(false)} />}
    </div>
  );
}

function EmiRow({ e, cardId }: { e: Emi; cardId: number }) {
  const { bump } = useShell();
  const [confirm, setConfirm] = useState<'close' | 'delete' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const act = async (what: 'close' | 'delete') => {
    if (confirm !== what) return setConfirm(what);
    setBusy(true);
    setError(null);
    try {
      if (what === 'close') await api(`/cards/${cardId}/emis/${e.id}/close`, { method: 'POST', body: { date: todayIso() } });
      else await api(`/cards/${cardId}/emis/${e.id}`, { method: 'DELETE' });
      bump();
    } catch (err) {
      setError((err as Error).message);
    }
    setBusy(false);
    setConfirm(null);
  };

  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', padding: 12, display: 'flex', flexDirection: 'column', gap: 8, opacity: e.status === 'closed' ? 0.7 : 1 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', alignItems: 'baseline' }}>
        <div>
          <b>{e.name}</b>{' '}
          <span className="muted" style={{ fontSize: 12.5 }}>
            · {KIND_LABEL[e.kind]} · <Money amount={rs(e.principal)} interactive={false} /> over {e.tenure} months
            {e.interest_rate !== null ? ` at ${e.interest_rate}%` : ''}
            {e.no_cost ? ' · no-cost' : ''}
          </span>
        </div>
        <span style={{ fontSize: 13 }}>
          {e.status === 'closed' ? (
            <span className="badge mint">{e.closed_on ? `Closed early ${fmtDate(e.closed_on)}` : 'Finished'}</span>
          ) : (
            <>
              <b>{e.paid_count}</b> of {e.tenure} paid
            </>
          )}
        </span>
      </div>
      <Progress value={e.principal_paid} max={e.principal} savings />
      <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', fontSize: 13 }}>
        <span>
          <span className="muted">Left to pay </span>
          <b><Money amount={rs(e.outstanding)} interactive={false} /></b>
        </span>
        {e.next_date && (
          <span>
            <span className="muted">Next instalment </span>
            {fmtDate(e.next_date)}
            {e.instalment ? <> · <Money amount={rs(e.instalment)} interactive={false} /></> : null}
          </span>
        )}
        <span>
          <span className="muted">Ends </span>
          {fmtDate(e.finish_date)}
        </span>
        <span>
          <span className="muted">Interest &amp; GST paid </span>
          <Money amount={rs(e.interest_paid)} interactive={false} />
        </span>
      </div>
      {error && <div className="form-error" role="alert">{error}</div>}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <Link href={`/transactions${qs({ account: e.account_id })}`} style={{ fontSize: 13 }}>Instalments</Link>
        <span className="spacer" style={{ flex: 1 }} />
        {e.status === 'active' && (
          <Button variant={confirm === 'close' ? 'primary' : 'ghost'} size="sm" onClick={() => act('close')} disabled={busy}>
            {confirm === 'close' ? `Confirm: move ₹${(e.outstanding / 100).toLocaleString('en-IN')} onto the card bill` : 'Paid off early'}
          </Button>
        )}
        <Button variant={confirm === 'delete' ? 'primary' : 'ghost'} size="sm" icon="trash-2" onClick={() => act('delete')} disabled={busy} className={confirm === 'delete' ? 'btn-danger' : ''}>
          {confirm === 'delete' ? 'Confirm remove' : 'Remove'}
        </Button>
      </div>
    </div>
  );
}
