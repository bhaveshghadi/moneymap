'use client';
import { useState } from 'react';
import Link from 'next/link';
import type { Card } from '../lib/types';
import { api } from '../lib/api';
import { fmtDate, rs } from '../lib/format';
import { useApi, useShell } from '../contexts/ShellCtx';
import { Dialog, useDialogClose } from '../primitives/Dialog';
import { Button } from '../primitives/Button';
import { Money } from '../primitives/Money';
import { Icon } from '../primitives/Icon';
import { DrawerHead } from './DrawerHead';

export interface Convertible {
  transaction_id: number;
  date: string;
  amount: number;
  description: string;
  paid_from: string;
  payee: string;
  category: string | null;
  suggested_card_id: number | null;
  why: string | null;
}

interface ConvertOut {
  converted: number;
  empty_categories: { id: number; name: string }[];
}

/** Note on the Credit cards page while card bill payments are still saved as expenses. */
export function ConvertCardBillsNote({ cards }: { cards: Card[] }) {
  const { data } = useApi<Convertible[]>('/cards/convertible');
  // The list as it was when the dialog opened: it stays open on its "done" step even
  // after the conversion empties the list.
  const [open, setOpen] = useState<Convertible[] | null>(null);
  const active = cards.filter((c) => c.active);
  const showNote = !!data && data.length > 0 && active.length > 0;
  const total = (data ?? []).reduce((s, x) => s + x.amount, 0);
  return (
    <>
      {showNote && (
      <div className="note warn" style={{ marginBottom: 16, alignItems: 'center' }}>
        <Icon name="repeat" size={15} />
        <span style={{ flex: 1 }}>
          <b>{data!.length} card bill payment{data!.length === 1 ? ' is' : 's are'} saved as expenses</b> (
          <Money amount={rs(total)} interactive={false} />
          ). Paying a card is a transfer to the card, not spending — as expenses they count twice once the card&apos;s own
          spends are in.
        </span>
        <Button variant="secondary" size="sm" onClick={() => setOpen(data)}>Review</Button>
      </div>
      )}
      {open && (
        <Dialog onClose={() => setOpen(null)} label="Card bill payments" width={640}>
          <Body items={open} cards={active} />
        </Dialog>
      )}
    </>
  );
}

function Body({ items, cards }: { items: Convertible[]; cards: Card[] }) {
  const close = useDialogClose();
  const { bump } = useShell();
  const [pick, setPick] = useState<Record<number, { on: boolean; card: string }>>(() =>
    Object.fromEntries(
      items.map((i) => [i.transaction_id, { on: i.suggested_card_id !== null, card: i.suggested_card_id ? String(i.suggested_card_id) : '' }]),
    ),
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<ConvertOut | null>(null);
  const [deleted, setDeleted] = useState<number[]>([]);

  const chosen = items.filter((i) => pick[i.transaction_id]?.on);
  const missingCard = chosen.some((i) => !pick[i.transaction_id].card);

  const submit = async () => {
    setError(null);
    if (chosen.length === 0) return setError('Tick at least one payment.');
    if (missingCard) return setError('Choose the card for every ticked payment.');
    setBusy(true);
    try {
      const res = await api<ConvertOut>('/cards/convert', {
        method: 'POST',
        body: { items: chosen.map((i) => ({ transaction_id: i.transaction_id, card_id: Number(pick[i.transaction_id].card) })) },
      });
      setDone(res);
      bump();
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(false);
  };

  const deleteCategory = async (id: number) => {
    setError(null);
    try {
      await api(`/categories/${id}`, { method: 'DELETE' });
      setDeleted((d) => [...d, id]);
      bump();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (done) {
    return (
      <>
        <DrawerHead title="Card bill payments" sub="Done" lead={<span className="ico" style={{ background: 'var(--mint-50)', color: 'var(--mint-700)' }}><Icon name="circle-check" size={20} /></span>} />
        <div className="drawer-body">
          {error && <div className="form-error" role="alert">{error}</div>}
          <p style={{ marginTop: 0 }}>
            {done.converted} payment{done.converted === 1 ? '' : 's'} changed into transfers to the card. They no longer count
            as spending (budgets, the emergency fund and the Overview update straight away).
          </p>
          {done.empty_categories.map((c) =>
            deleted.includes(c.id) ? (
              <p key={c.id} className="muted">Category “{c.name}” deleted.</p>
            ) : (
              <div key={c.id} className="note info" style={{ alignItems: 'center' }}>
                <span style={{ flex: 1 }}>The category “{c.name}” has no transactions left. Delete it?</span>
                <Button variant="secondary" size="sm" icon="trash-2" onClick={() => deleteCategory(c.id)}>Delete “{c.name}”</Button>
              </div>
            ),
          )}
        </div>
        <div className="drawer-foot">
          <span className="spacer" />
          <Button variant="primary" onClick={close}>Close</Button>
        </div>
      </>
    );
  }

  return (
    <>
      <DrawerHead title="Card bill payments saved as expenses" sub="Tick the ones to change into a transfer to the card" lead={<span className="ico" style={{ background: 'var(--amber-50)', color: 'var(--amber-700)' }}><Icon name="repeat" size={20} /></span>} />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {items.map((i) => {
            const p = pick[i.transaction_id];
            return (
              <div key={i.transaction_id} className="card card-pad" style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: 10, alignItems: 'start', padding: 12 }}>
                <input
                  type="checkbox"
                  aria-label={`Change ${i.description}`}
                  checked={p.on}
                  onChange={(e) => setPick((s) => ({ ...s, [i.transaction_id]: { ...s[i.transaction_id], on: e.target.checked } }))}
                  style={{ marginTop: 4 }}
                />
                <div style={{ minWidth: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
                    <b style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 360 }} title={i.description}>{i.description}</b>
                    <span className="fig"><Money amount={rs(i.amount)} interactive={false} /></span>
                  </div>
                  <div className="muted" style={{ fontSize: 12.5 }}>
                    {fmtDate(i.date)} · from {i.paid_from} · to {i.payee}
                    {i.category ? ` · ${i.category}` : ''}
                  </div>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                    <select
                      className="inp"
                      aria-label="Card paid"
                      style={{ width: 'auto', minWidth: 200 }}
                      value={p.card}
                      onChange={(e) => setPick((s) => ({ ...s, [i.transaction_id]: { on: true, card: e.target.value } }))}
                    >
                      <option value="">Which card?</option>
                      {cards.map((c) => (
                        <option key={c.id} value={c.id}>{c.name}{c.last4 ? ` ··${c.last4}` : ''}</option>
                      ))}
                    </select>
                    {i.why && p.card === String(i.suggested_card_id) && <span className="muted" style={{ fontSize: 12 }}>{i.why}</span>}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
        <p className="muted" style={{ fontSize: 12.5, marginBottom: 0 }}>
          The date, amount and description stay the same; the category is removed (transfers have none). Not a card payment?
          Leave it unticked. You can also <Link href="/transactions">edit any of them</Link> by hand.
        </p>
      </div>
      <div className="drawer-foot">
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        <Button variant="primary" onClick={submit} disabled={busy || chosen.length === 0}>
          {busy ? 'Changing…' : `Change ${chosen.length} into transfer${chosen.length === 1 ? '' : 's'}`}
        </Button>
      </div>
    </>
  );
}
