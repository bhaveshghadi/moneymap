'use client';
import { useState, type FormEvent } from 'react';
import { api } from '../lib/api';
import { useApi, useShell } from '../contexts/ShellCtx';
import type { Account, Piggy, PiggyEvent } from '../lib/types';
import { fmtDate, paiseToInput, rs, toPaise, todayIso } from '../lib/format';
import { Button } from '../primitives/Button';
import { Money } from '../primitives/Money';
import { StatCard } from '../primitives/StatCard';
import { Skeleton } from '../primitives/Skeleton';
import { EmptyState } from '../primitives/EmptyState';
import { ErrorState } from '../primitives/ErrorState';
import { SegmentedControl } from '../primitives/SegmentedControl';
import { Icon } from '../primitives/Icon';
import { Dialog, useDialogClose } from '../primitives/Dialog';
import { DrawerHead } from '../shared/DrawerHead';
import { Progress } from '../shared/Progress';
import { EmergencyFundCard } from '../shared/EmergencyFundCard';
import { PageHelp } from '../shared/PageHelp';

export function PiggyBanksPage() {
  const { data, error, reload } = useApi<Piggy[]>('/piggy-banks');
  const [editing, setEditing] = useState<{ piggy?: Piggy } | null>(null);
  const [moving, setMoving] = useState<{ piggy: Piggy; dir: 'add' | 'remove' } | null>(null);
  // The emergency fund's piggy bank has its own card at the top.
  const goals = (data ?? []).filter((p) => !p.is_emergency);
  const active = goals.filter((p) => p.active);
  const saved = active.reduce((s, p) => s + p.saved, 0);
  const target = active.reduce((s, p) => s + p.target_amount, 0);

  return (
    <div className="content-wrap fade-in">
      <div className="page-head">
        <div>
          <h1>Piggy banks <PageHelp id="piggy-banks" /></h1>
          <p>Savings goals. Money you set aside stays in its account; it&apos;s just earmarked for the goal.</p>
        </div>
        <div className="actions">
          <Button variant="primary" icon="plus" onClick={() => setEditing({})}>Add piggy bank</Button>
        </div>
      </div>

      <EmergencyFundCard onMove={(piggy, dir) => setMoving({ piggy, dir })} />

      {error ? (
        <div className="card"><ErrorState message={error} onRetry={reload} /></div>
      ) : !data ? (
        <>
          <div className="grid-3 stat-grid"><Skeleton variant="stat" count={3} /></div>
          <div className="grid-3"><Skeleton variant="block" height={190} count={3} /></div>
        </>
      ) : goals.length === 0 ? (
        <div className="card">
          <EmptyState
            icon="piggy-bank"
            title="No piggy banks yet"
            body="Create a goal — a trip, a new phone, a wedding — link it to a savings account and set money aside as you go."
            action={{ label: 'Add piggy bank', onClick: () => setEditing({}) }}
          />
        </div>
      ) : (
        <>
          <div className="grid-3 stat-grid">
            <StatCard lbl="Saved" icon="piggy-bank" val={<Money amount={rs(saved)} compact pos />} sub={`${active.length} active goal${active.length === 1 ? '' : 's'}`} />
            <StatCard lbl="Targets" icon="target" val={<Money amount={rs(target)} compact />} />
            <StatCard lbl="Still to save" icon="hourglass" val={<Money amount={rs(Math.max(0, target - saved))} compact />} sub={target ? `${Math.round((saved / target) * 100)}% of the way` : undefined} />
          </div>
          <div className="grid-3">
            {goals.map((p) => (
              <PiggyCard key={p.id} p={p} onEdit={() => setEditing({ piggy: p })} onMove={(dir) => setMoving({ piggy: p, dir })} />
            ))}
          </div>
        </>
      )}

      {editing && <PiggyForm piggy={editing.piggy} onClose={() => setEditing(null)} />}
      {moving && <MoveMoney piggy={moving.piggy} dir={moving.dir} onClose={() => setMoving(null)} />}
    </div>
  );
}

function PiggyCard({ p, onEdit, onMove }: { p: Piggy; onEdit: () => void; onMove: (dir: 'add' | 'remove') => void }) {
  const pct = Math.min(100, Math.round((p.saved / p.target_amount) * 100));
  const done = p.saved >= p.target_amount;
  return (
    <div className="card card-pad card-hover" style={{ display: 'flex', flexDirection: 'column', gap: 12, opacity: p.active ? 1 : 0.6, cursor: 'pointer' }} onClick={onEdit} role="button" tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && onEdit()}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'flex-start' }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontFamily: 'var(--font-display)', fontWeight: 650, fontSize: 15.5 }}>{p.name}</div>
          <div className="muted" style={{ fontSize: 12.5 }}>{p.account.name}</div>
        </div>
        {done ? <span className="badge mint">Reached</span> : <span className="badge neutral">{pct}%</span>}
      </div>
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 7 }}>
          <span className="fig" style={{ fontSize: 17 }}><Money amount={rs(p.saved)} pos interactive={false} /></span>
          <span className="muted">of <Money amount={rs(p.target_amount)} interactive={false} /></span>
        </div>
        <Progress value={p.saved} max={p.target_amount} savings />
      </div>
      <div className="muted" style={{ fontSize: 12.5, minHeight: 18 }}>
        {p.target_date ? (
          done ? `Target date ${fmtDate(p.target_date)}` : (
            <>By {fmtDate(p.target_date)}{p.monthly_needed ? <> · <Money amount={rs(p.monthly_needed)} interactive={false} />/month</> : null}</>
          )
        ) : 'No target date'}
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }} onClick={(e) => e.stopPropagation()}>
        <Button variant="secondary" size="sm" icon="plus" onClick={() => onMove('add')} disabled={!p.active}>Add money</Button>
        <Button variant="ghost" size="sm" icon="minus" onClick={() => onMove('remove')} disabled={p.saved <= 0}>Take out</Button>
      </div>
    </div>
  );
}

function MoveMoney({ piggy, dir, onClose }: { piggy: Piggy; dir: 'add' | 'remove'; onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label={dir === 'add' ? `Add money to ${piggy.name}` : `Take money out of ${piggy.name}`} width={440}>
      <MoveMoneyBody piggy={piggy} initialDir={dir} />
    </Dialog>
  );
}

function MoveMoneyBody({ piggy, initialDir }: { piggy: Piggy; initialDir: 'add' | 'remove' }) {
  const close = useDialogClose();
  const { bump } = useShell();
  const [dir, setDir] = useState(initialDir);
  const [amount, setAmount] = useState('');
  const [date, setDate] = useState(todayIso());
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const max = dir === 'add' ? Math.max(0, piggy.account_available) : piggy.saved;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const p = toPaise(amount);
    if (p === null || p <= 0) return setError('Enter an amount greater than zero');
    setSaving(true);
    try {
      await api(`/piggy-banks/${piggy.id}/events`, { method: 'POST', body: { amount: dir === 'add' ? p : -p, date, note: note || null } });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead title={piggy.name} sub={<>Saved <Money amount={rs(piggy.saved)} interactive={false} /> of <Money amount={rs(piggy.target_amount)} interactive={false} /></>} />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        <div className="field">
          <SegmentedControl aria-label="Direction" value={dir} onChange={(v) => setDir(v as 'add' | 'remove')} options={[{ value: 'add', label: 'Add money' }, { value: 'remove', label: 'Take out' }]} />
        </div>
        <div className="field">
          <label htmlFor="pm-amt">Amount (₹)</label>
          <input id="pm-amt" className="inp" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} required placeholder="0.00" autoFocus />
          <div className="hint">
            {dir === 'add' ? (
              <>Up to <Money amount={rs(max)} interactive={false} /> — what {piggy.account.name} has that isn&apos;t already set aside.{' '}
                {dir === 'add' && piggy.saved < piggy.target_amount && max > 0 && (
                  <button type="button" className="prov" style={{ display: 'inline' }} onClick={() => setAmount(paiseToInput(Math.min(max, piggy.target_amount - piggy.saved)))}>Fill to target</button>
                )}
              </>
            ) : (
              <>Up to <Money amount={rs(max)} interactive={false} /> (everything saved).</>
            )}
          </div>
        </div>
        <div className="field">
          <label htmlFor="pm-date">Date</label>
          <input id="pm-date" type="date" className="inp" value={date} onChange={(e) => setDate(e.target.value)} required />
        </div>
        <div className="field">
          <label htmlFor="pm-note">Note <span className="muted" style={{ fontWeight: 400 }}>(optional)</span></label>
          <input id="pm-note" className="inp" value={note} onChange={(e) => setNote(e.target.value)} maxLength={255} />
        </div>
      </div>
      <div className="drawer-foot">
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        <Button variant="primary" type="submit" disabled={saving}>{dir === 'add' ? 'Add money' : 'Take out'}</Button>
      </div>
    </form>
  );
}

function PiggyForm({ piggy, onClose }: { piggy?: Piggy; onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label={piggy ? `Piggy bank: ${piggy.name}` : 'Add piggy bank'} width={500}>
      <PiggyFormBody piggy={piggy} />
    </Dialog>
  );
}

function PiggyFormBody({ piggy }: { piggy?: Piggy }) {
  const close = useDialogClose();
  const { bump } = useShell();
  const accounts = useApi<Account[]>('/accounts?type=asset&type=cash&include_inactive=false');
  const events = useApi<PiggyEvent[]>(piggy ? `/piggy-banks/${piggy.id}/events` : null);
  const [name, setName] = useState(piggy?.name ?? '');
  const [accountId, setAccountId] = useState(piggy ? String(piggy.account.id) : '');
  const [target, setTarget] = useState(piggy ? paiseToInput(piggy.target_amount) : '');
  const [targetDate, setTargetDate] = useState(piggy?.target_date ?? '');
  const [active, setActive] = useState(piggy?.active ?? true);
  const [notes, setNotes] = useState(piggy?.notes ?? '');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const t = toPaise(target);
    if (t === null || t <= 0) return setError('Target must be an amount greater than zero');
    const body = { name, account_id: Number(accountId), target_amount: t, target_date: targetDate || null, active, notes: notes || null };
    setSaving(true);
    try {
      if (piggy) await api(`/piggy-banks/${piggy.id}`, { method: 'PATCH', body });
      else await api('/piggy-banks', { method: 'POST', body });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!piggy) return;
    if (!confirmDelete) return setConfirmDelete(true);
    setSaving(true);
    try {
      await api(`/piggy-banks/${piggy.id}`, { method: 'DELETE' });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead title={piggy ? piggy.name : 'Add piggy bank'} sub="Amounts are in ₹" lead={<span className="ico" style={{ background: 'var(--mint-50)', color: 'var(--mint-600)' }}><Icon name="piggy-bank" size={20} /></span>} />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        <div className="field">
          <label htmlFor="pg-name">Name</label>
          <input id="pg-name" className="inp" value={name} onChange={(e) => setName(e.target.value)} required maxLength={120} placeholder="e.g. Emergency fund" />
        </div>
        <div className="field">
          <label htmlFor="pg-acc">Saved in</label>
          <select id="pg-acc" className="inp" value={accountId} onChange={(e) => setAccountId(e.target.value)} required>
            <option value="">Choose an account…</option>
            {(accounts.data ?? []).map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
          {accounts.data && accounts.data.length === 0 && <div className="hint">Add a bank or cash account first.</div>}
        </div>
        <div className="row2">
          <div className="field">
            <label htmlFor="pg-target">Target (₹)</label>
            <input id="pg-target" className="inp" inputMode="decimal" value={target} onChange={(e) => setTarget(e.target.value)} required placeholder="0.00" />
          </div>
          <div className="field">
            <label htmlFor="pg-date">Target date <span className="muted" style={{ fontWeight: 400 }}>(optional)</span></label>
            <input id="pg-date" type="date" className="inp" value={targetDate} onChange={(e) => setTargetDate(e.target.value)} />
          </div>
        </div>
        <div className="field">
          <label htmlFor="pg-notes">Notes</label>
          <textarea id="pg-notes" className="inp" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </div>
        {piggy && (
          <>
            <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 14, marginBottom: 18 }}>
              <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
              Active
            </label>
            <div className="sb-section" style={{ padding: '4px 0 6px' }}>History</div>
            {events.data && events.data.length === 0 && <div className="muted" style={{ fontSize: 13 }}>No money set aside yet.</div>}
            {(events.data ?? []).map((ev) => (
              <div className="kv" key={ev.id}>
                <span className="k">{fmtDate(ev.date)}{ev.note ? ` · ${ev.note}` : ''}</span>
                <span className="v fig">
                  {ev.amount > 0 ? '+' : '−'}
                  <Money amount={rs(Math.abs(ev.amount))} pos={ev.amount > 0} interactive={false} />
                </span>
              </div>
            ))}
          </>
        )}
      </div>
      <div className="drawer-foot">
        {piggy && (
          <Button variant={confirmDelete ? 'primary' : 'ghost'} icon="trash-2" onClick={remove} disabled={saving} className={confirmDelete ? 'btn-danger' : ''}>
            {confirmDelete ? 'Confirm delete' : 'Delete'}
          </Button>
        )}
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        <Button variant="primary" type="submit" disabled={saving}>{saving ? 'Saving…' : piggy ? 'Save changes' : 'Add piggy bank'}</Button>
      </div>
    </form>
  );
}
