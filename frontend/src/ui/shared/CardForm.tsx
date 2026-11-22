'use client';
import { useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import type { Card, CardDetail, CycleStatus, DueMode } from '../lib/types';
import { api } from '../lib/api';
import { fmtDate, paiseToInput, toPaise } from '../lib/format';
import { useShell } from '../contexts/ShellCtx';
import { Dialog, useDialogClose } from '../primitives/Dialog';
import { Button } from '../primitives/Button';
import { SegmentedControl } from '../primitives/SegmentedControl';
import { CategoryGlyph, PALETTE } from '../primitives/CategoryGlyph';
import { DrawerHead } from './DrawerHead';
import { useStay } from '../contexts/StayCtx';

const CYCLE_STATUS: Record<CycleStatus, [string, string]> = {
  unbilled: ['neutral', 'Unbilled'],
  nothing_due: ['neutral', 'Nothing due'],
  billed: ['cau', 'Due'],
  partly_paid: ['cau', 'Partly paid'],
  paid: ['mint', 'Paid'],
  overdue: ['red', 'Overdue'],
};

export function CycleBadge({ status, minPaid = false }: { status: CycleStatus; minPaid?: boolean }) {
  const [cls, label] = CYCLE_STATUS[status];
  return <span className={`badge ${cls}`}>{status === 'overdue' && minPaid ? 'Overdue · min paid' : label}</span>;
}

export const NETWORKS: { value: string; label: string }[] = [
  { value: 'visa', label: 'Visa' },
  { value: 'mastercard', label: 'Mastercard' },
  { value: 'rupay', label: 'RuPay' },
  { value: 'amex', label: 'American Express' },
  { value: 'diners', label: 'Diners Club' },
  { value: 'other', label: 'Other' },
];

export function networkLabel(n: string | null): string {
  return NETWORKS.find((x) => x.value === n)?.label ?? '';
}

/** "12th" */
export function ordinal(n: number): string {
  const s = n % 100 >= 11 && n % 100 <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] ?? 'th';
  return `${n}${s}`;
}

/** "Statement on the 12th · due 20 days later" */
export function ruleText(c: Pick<Card, 'statement_day' | 'due_mode' | 'due_value'>): string {
  const sd = c.statement_day === 31 ? 'last day of the month' : `${ordinal(c.statement_day)}`;
  const due = c.due_mode === 'days_after' ? `due ${c.due_value} days later` : `due on the ${ordinal(c.due_value)}`;
  return `Statement on the ${sd} · ${due}`;
}

/** "19 Oct – 18 Nov" */
export function shortRange(from: string, to: string): string {
  const f = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
  return `${f(from)} – ${f(to)}`;
}

/** "Billing cycle 19 Oct – 18 Nov · due 6 Dec" — the card's current cycle. */
export function cycleText(c: Pick<Card, 'current'>): string {
  const due = new Date(`${c.current.due_date}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
  return `Billing cycle ${shortRange(c.current.start, c.current.statement_date)} · due ${due}`;
}

function parseIso(iso: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return null;
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime()) ? null : d;
}

const DAY_MS = 86_400_000;

/** From one billing cycle (first day, last day = statement date) and its payment due
 * date: the statement day, and the due rule. */
export function ruleFromCycle(
  fromIso: string,
  toIso: string,
  dueIso: string,
  mode: DueMode,
): { statementDay: number; dueValue: number; error: string | null } {
  const from = parseIso(fromIso);
  const to = parseIso(toIso);
  const due = parseIso(dueIso);
  const none = { statementDay: 0, dueValue: 0 };
  if (!from || !to) return { ...none, error: 'Enter the billing cycle — the first and last day, as printed on a statement.' };
  const length = Math.round((to.getTime() - from.getTime()) / DAY_MS) + 1;
  if (length < 25 || length > 35) return { ...none, error: `That cycle is ${length} days — a billing cycle is about a month (e.g. 19 Oct – 18 Nov).` };
  if (!due) return { ...none, error: 'Enter the payment due date of that statement.' };
  const gap = Math.round((due.getTime() - to.getTime()) / DAY_MS);
  if (gap < 1 || gap > 60) return { ...none, error: 'The due date must be after the cycle ends (usually 15–25 days later).' };
  const lastOfMonth = new Date(to.getFullYear(), to.getMonth() + 1, 0).getDate() === to.getDate();
  const statementDay = lastOfMonth && from.getDate() === 1 ? 31 : to.getDate();
  return { statementDay, dueValue: mode === 'days_after' ? gap : due.getDate(), error: null };
}

// ---- next statement / due date preview (same rules as the server)
function clampDate(y: number, m: number, d: number): Date {
  return new Date(y, m, Math.min(d, new Date(y, m + 1, 0).getDate()));
}
function iso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
function previewDates(statementDay: number, mode: DueMode, value: number): { statement: string; due: string } {
  const t = new Date();
  const today = new Date(t.getFullYear(), t.getMonth(), t.getDate());
  let sd = clampDate(today.getFullYear(), today.getMonth(), statementDay);
  if (sd <= today) sd = clampDate(today.getFullYear(), today.getMonth() + 1, statementDay);
  let due: Date;
  if (mode === 'days_after') {
    due = new Date(sd.getFullYear(), sd.getMonth(), sd.getDate() + value);
  } else {
    due = clampDate(sd.getFullYear(), sd.getMonth(), value);
    if (due <= sd) due = clampDate(sd.getFullYear(), sd.getMonth() + 1, value);
  }
  return { statement: iso(sd), due: iso(due) };
}

export function CardForm({ card, onClose }: { card?: CardDetail; onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label={card ? `Card: ${card.name}` : 'Add credit card'} width={540}>
      <CardFormBody card={card} />
    </Dialog>
  );
}

function CardFormBody({ card }: { card?: CardDetail }) {
  const close = useDialogClose();
  const router = useRouter();
  const stay = useStay();
  const { bump } = useShell();
  const [f, setF] = useState({
    name: card?.name ?? '',
    bank: card?.bank ?? '',
    last4: card?.last4 ?? '',
    network: card?.network ?? '',
    limit: card?.credit_limit ? paiseToInput(card.credit_limit) : '',
    // one billing cycle as printed on a statement: the latest issued one, else the current one
    cycleFrom: (card?.last_statement ?? card?.current)?.start ?? '',
    cycleTo: (card?.last_statement ?? card?.current)?.statement_date ?? '',
    dueDate: (card?.last_statement ?? card?.current)?.due_date ?? '',
    dueMode: (card?.due_mode ?? 'days_after') as DueMode,
    minPct: String(card?.min_due_pct ?? 5),
    color: card?.color ?? 'indigo',
    owed: card?.opening_owed ? paiseToInput(card.opening_owed) : '',
    openingDate: card?.opening_date ?? '',
    active: card?.active ?? true,
    notes: card?.notes ?? '',
  });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((p) => ({ ...p, [k]: v }));

  const rule = ruleFromCycle(f.cycleFrom, f.cycleTo, f.dueDate, f.dueMode);
  const touched = !!(f.cycleFrom || f.cycleTo || f.dueDate);
  const preview = rule.error ? null : previewDates(rule.statementDay, f.dueMode, rule.dueValue);
  const cycleChanged =
    !!card &&
    !rule.error &&
    (rule.statementDay !== card.statement_day || f.dueMode !== card.due_mode || rule.dueValue !== card.due_value);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (rule.error) return setError(rule.error);
    if (f.last4 && !/^\d{4}$/.test(f.last4)) return setError('Last 4 digits must be 4 numbers.');
    const limit = f.limit ? toPaise(f.limit) : 0;
    if (limit === null || limit < 0) return setError('Enter the credit limit in ₹, e.g. 200000');
    const owed = f.owed ? toPaise(f.owed) : 0;
    if (owed === null || owed < 0) return setError('Enter what you owe in ₹ (0 if nothing).');
    const body = {
      name: f.name,
      bank: f.bank || null,
      last4: f.last4 || null,
      network: f.network || null,
      credit_limit: limit,
      statement_day: rule.statementDay,
      due_mode: f.dueMode,
      due_value: rule.dueValue,
      min_due_pct: Number(f.minPct) || 5,
      color: f.color,
      opening_owed: owed,
      opening_date: f.openingDate || null,
      active: f.active,
      notes: f.notes || null,
    };
    setSaving(true);
    try {
      if (card) {
        await api(`/cards/${card.id}`, { method: 'PATCH', body });
        bump();
        close();
      } else {
        const res = await api<CardDetail>('/cards', { method: 'POST', body });
        bump();
        close();
        if (!stay) router.push(`/credit-cards/${res.id}`);
      }
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!card) return;
    if (!confirmDelete) return setConfirmDelete(true);
    setSaving(true);
    try {
      await api(`/cards/${card.id}`, { method: 'DELETE' });
      bump();
      close();
      router.push('/credit-cards');
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
      setConfirmDelete(false);
    }
  };

  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead
        title={card ? card.name : 'Add credit card'}
        sub={card ? ruleText(card) : 'Amounts are in ₹'}
        lead={<CategoryGlyph icon="credit-card" color={f.color} size={42} />}
      />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        <div className="field">
          <label htmlFor="cc-name">Card name</label>
          <input id="cc-name" className="inp" value={f.name} onChange={(e) => set('name', e.target.value)} required maxLength={120} placeholder="e.g. HDFC Millennia" />
        </div>
        <div className="row2">
          <div className="field">
            <label htmlFor="cc-bank">Bank</label>
            <input id="cc-bank" className="inp" value={f.bank} onChange={(e) => set('bank', e.target.value)} maxLength={80} placeholder="e.g. HDFC Bank" />
          </div>
          <div className="field">
            <label htmlFor="cc-last4">Last 4 digits</label>
            <input id="cc-last4" className="inp" inputMode="numeric" maxLength={4} value={f.last4} onChange={(e) => set('last4', e.target.value.replace(/\D/g, ''))} placeholder="1234" />
          </div>
        </div>
        <div className="row2">
          <div className="field">
            <label htmlFor="cc-net">Network</label>
            <select id="cc-net" className="inp" value={f.network} onChange={(e) => set('network', e.target.value)}>
              <option value="">—</option>
              {NETWORKS.map((n) => (
                <option key={n.value} value={n.value}>{n.label}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="cc-limit">Credit limit (₹)</label>
            <input id="cc-limit" className="inp" inputMode="decimal" value={f.limit} onChange={(e) => set('limit', e.target.value)} placeholder="e.g. 200000" />
          </div>
        </div>

        <div className="card card-pad" style={{ background: 'var(--bg-subtle)', marginBottom: 14 }}>
          <div style={{ fontWeight: 650, marginBottom: 10 }}>Billing cycle</div>
          <div className="hint" style={{ marginTop: -4, marginBottom: 10 }}>
            Copy them from any statement of this card — MoneyMap works out the statement day and due date for every month.
          </div>
          <div className="row2">
            <div className="field">
              <label htmlFor="cc-from">Cycle from</label>
              <input id="cc-from" className="inp" type="date" value={f.cycleFrom} onChange={(e) => set('cycleFrom', e.target.value)} required />
            </div>
            <div className="field">
              <label htmlFor="cc-to">to (statement date)</label>
              <input id="cc-to" className="inp" type="date" value={f.cycleTo} onChange={(e) => set('cycleTo', e.target.value)} required />
            </div>
          </div>
          <div className="row2">
            <div className="field">
              <label htmlFor="cc-due">Payment due date</label>
              <input id="cc-due" className="inp" type="date" value={f.dueDate} onChange={(e) => set('dueDate', e.target.value)} required />
            </div>
            <div className="field">
              <label htmlFor="cc-min">Minimum due (%)</label>
              <input id="cc-min" className="inp" inputMode="numeric" value={f.minPct} onChange={(e) => set('minPct', e.target.value.replace(/\D/g, ''))} />
            </div>
          </div>
          <div className="field">
            <label>The due date each month is</label>
            <SegmentedControl
              aria-label="How the due date repeats"
              value={f.dueMode}
              onChange={(v) => set('dueMode', v as DueMode)}
              options={[
                { value: 'days_after', label: 'Same days after statement' },
                { value: 'fixed_day', label: 'Same day of month' },
              ]}
            />
          </div>
          {preview ? (
            <div className="note info" aria-live="polite">
              <span>
                Billing cycle <b>{ordinal(rule.statementDay === 31 ? 1 : rule.statementDay + 1)}</b> to{' '}
                <b>{rule.statementDay === 31 ? 'month end' : ordinal(rule.statementDay)}</b> ·{' '}
                {f.dueMode === 'days_after' ? `due ${rule.dueValue} days after the statement` : `due on the ${ordinal(rule.dueValue)}`}. Next
                statement <b>{fmtDate(preview.statement)}</b>, payment due <b>{fmtDate(preview.due)}</b>.
                {cycleChanged && ' Statements already issued keep their dates — the change applies from the current cycle.'}
              </span>
            </div>
          ) : (
            touched &&
            rule.error && (
              <div className="note warn" aria-live="polite">
                <span>{rule.error}</span>
              </div>
            )
          )}
        </div>

        <div className="row2">
          <div className="field">
            <label htmlFor="cc-owed">Owed when you start (₹)</label>
            <input id="cc-owed" className="inp" inputMode="decimal" value={f.owed} onChange={(e) => set('owed', e.target.value)} placeholder="0" />
          </div>
          <div className="field">
            <label htmlFor="cc-od">As of</label>
            <input id="cc-od" className="inp" type="date" value={f.openingDate} onChange={(e) => set('openingDate', e.target.value)} />
          </div>
        </div>
        <div className="field">
          <label>Colour</label>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {Object.keys(PALETTE).map((c) => (
              <button
                key={c}
                type="button"
                aria-label={c}
                aria-pressed={f.color === c}
                onClick={() => set('color', c)}
                style={{ width: 28, height: 28, borderRadius: 999, background: PALETTE[c], border: f.color === c ? '3px solid var(--fg-1)' : '3px solid transparent', cursor: 'pointer' }}
              />
            ))}
          </div>
        </div>
        <div className="field">
          <label htmlFor="cc-notes">Notes</label>
          <textarea id="cc-notes" className="inp" rows={2} value={f.notes} onChange={(e) => set('notes', e.target.value)} />
        </div>
        {card && (
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 14 }}>
            <input type="checkbox" checked={f.active} onChange={(e) => set('active', e.target.checked)} />
            Active (inactive cards are hidden from forms and the Overview)
          </label>
        )}
      </div>
      <div className="drawer-foot">
        {card && (
          <Button variant={confirmDelete ? 'primary' : 'ghost'} icon="trash-2" onClick={remove} disabled={saving} className={confirmDelete ? 'btn-danger' : ''}>
            {confirmDelete ? 'Confirm delete' : 'Delete'}
          </Button>
        )}
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        <Button variant="primary" type="submit" disabled={saving}>{saving ? 'Saving…' : card ? 'Save' : 'Add card'}</Button>
      </div>
    </form>
  );
}
