'use client';
import { useState, type FormEvent } from 'react';
import Link from 'next/link';
import { api, qs } from '../lib/api';
import { useApi, useShell } from '../contexts/ShellCtx';
import type { BudgetMode, Budget, BudgetMonth, Category } from '../lib/types';
import { currentMonth, monthLabel, monthRange, paiseToInput, rs, shiftMonth, toPaise } from '../lib/format';
import { Button } from '../primitives/Button';
import { Money } from '../primitives/Money';
import { StatCard } from '../primitives/StatCard';
import { SectionCard } from '../primitives/SectionCard';
import { Skeleton } from '../primitives/Skeleton';
import { EmptyState } from '../primitives/EmptyState';
import { ErrorState } from '../primitives/ErrorState';
import { SegmentedControl } from '../primitives/SegmentedControl';
import { Icon } from '../primitives/Icon';
import { Dialog, useDialogClose } from '../primitives/Dialog';
import { DrawerHead } from '../shared/DrawerHead';
import { Progress } from '../shared/Progress';

const MODE_LABEL: Record<BudgetMode, string> = {
  manual: 'Set by hand',
  fixed: 'Same every month',
  rollover: 'Rolls over',
};

export function BudgetsPage() {
  const [month, setMonth] = useState(currentMonth());
  const { data, error, reload } = useApi<BudgetMonth>(`/budgets?month=${month}`);
  const categories = useApi<Category[]>('/categories');
  const catName = new Map((categories.data ?? []).map((c) => [c.id, c.name]));
  const [editing, setEditing] = useState<{ budget?: Budget } | null>(null);
  const range = monthRange(month);
  const active = (data?.budgets ?? []).filter((b) => b.active);
  const inactive = (data?.budgets ?? []).filter((b) => !b.active);
  const left = data ? data.budgeted - data.spent : 0;

  return (
    <div className="content-wrap fade-in">
      <div className="page-head">
        <div>
          <h1>Budgets</h1>
          <p>How much you plan to spend per budget each month, and how it&apos;s going.</p>
        </div>
        <div className="actions">
          <div className="month-nav">
            <button className="icon-btn" aria-label="Previous month" onClick={() => setMonth(shiftMonth(month, -1))}>
              <Icon name="chevron-left" size={18} />
            </button>
            <span className="lbl">{monthLabel(month)}</span>
            <button className="icon-btn" aria-label="Next month" onClick={() => setMonth(shiftMonth(month, 1))}>
              <Icon name="chevron-right" size={18} />
            </button>
          </div>
          <Button variant="primary" icon="plus" onClick={() => setEditing({})}>
            Add budget
          </Button>
        </div>
      </div>

      {error ? (
        <div className="card"><ErrorState message={error} onRetry={reload} /></div>
      ) : !data ? (
        <>
          <div className="grid-3 stat-grid"><Skeleton variant="stat" count={3} /></div>
          <Skeleton variant="block" height={280} />
        </>
      ) : data.budgets.length === 0 ? (
        <div className="card">
          <EmptyState
            icon="gauge"
            title="No budgets yet"
            body="Create budgets like Groceries, Eating out or Fun money, give each a monthly amount, then pick the budget when you record an expense."
            action={{ label: 'Add budget', onClick: () => setEditing({}) }}
          />
        </div>
      ) : (
        <>
          <div className="grid-3 stat-grid">
            <StatCard lbl="Budgeted" icon="gauge" val={<Money amount={rs(data.budgeted)} compact />} sub={monthLabel(month)} />
            <StatCard lbl="Spent from budgets" icon="arrow-up-from-line" val={<Money amount={rs(data.spent)} compact />} />
            <StatCard lbl="Left" icon="piggy-bank" val={<Money amount={rs(left)} compact sign={left < 0} pos={left >= 0} />} sub={left < 0 ? 'Over budget overall' : 'Across all budgets'} />
          </div>

          <SectionCard title={`Budgets · ${monthLabel(month)}`}>
            {active.map((b) => (
              <BudgetRow key={b.id} b={b} range={range} catName={catName} onClick={() => setEditing({ budget: b })} />
            ))}
            <Link
              href={`/transactions${qs({ type: 'withdrawal', no_budget: 1, from: range.from, to: range.to })}`}
              className="catrow"
              style={{ display: 'block', textDecoration: 'none' }}
            >
              <div className="top" style={{ marginBottom: 0 }}>
                <span className="nm" style={{ color: 'var(--fg-2)' }}>
                  <Icon name="circle-dashed" size={16} /> Spent without a budget
                </span>
                <span className="fig"><Money amount={rs(data.unbudgeted_spent)} interactive={false} /></span>
              </div>
            </Link>
          </SectionCard>

          {inactive.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <SectionCard title="Inactive">
                {inactive.map((b) => (
                  <BudgetRow key={b.id} b={b} range={range} catName={catName} onClick={() => setEditing({ budget: b })} />
                ))}
              </SectionCard>
            </div>
          )}
        </>
      )}

      {editing && <BudgetForm budget={editing.budget} month={month} onClose={() => setEditing(null)} />}
    </div>
  );
}

function BudgetRow({ b, range, catName, onClick }: { b: Budget; range: { from: string; to: string }; catName: Map<number, string>; onClick: () => void }) {
  const over = b.left !== null && b.left < 0;
  return (
    <div className="catrow" role="button" tabIndex={0} onClick={onClick} onKeyDown={(e) => e.key === 'Enter' && onClick()} style={{ opacity: b.active ? 1 : 0.6 }}>
      <div className="top">
        <span className="nm">
          {b.name}
          {b.mode !== 'manual' && <span className="badge brand">{MODE_LABEL[b.mode]}</span>}
          {b.limit !== null && !b.limit_is_auto && b.mode !== 'manual' && <span className="badge neutral">Edited this month</span>}
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13 }}>
          <span>
            <span className="fig"><Money amount={rs(b.spent)} interactive={false} /></span>
            {b.limit !== null && (
              <span className="muted"> of <Money amount={rs(b.limit)} interactive={false} /></span>
            )}
          </span>
          <Link
            href={`/transactions${qs({ budget: b.id, from: range.from, to: range.to })}`}
            className="prov"
            onClick={(e) => e.stopPropagation()}
            title="View expenses in this budget"
          >
            <Icon name="list" size={13} />
          </Link>
        </span>
      </div>
      {b.category_ids.length > 0 && (
        <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
          Counts {b.category_ids.map((id) => catName.get(id) ?? '…').join(', ')}
        </div>
      )}
      {b.limit !== null ? (
        <>
          <Progress value={b.spent} max={b.limit} />
          <div className="muted" style={{ fontSize: 12, marginTop: 6, color: over ? 'var(--red-600)' : undefined }}>
            {over ? (
              <>Over by <Money amount={rs(-b.left!)} interactive={false} /></>
            ) : (
              <><Money amount={rs(b.left ?? 0)} interactive={false} /> left</>
            )}
          </div>
        </>
      ) : (
        <div className="muted" style={{ fontSize: 12 }}>No amount set for this month — click to set one.</div>
      )}
    </div>
  );
}

function BudgetForm({ budget, month, onClose }: { budget?: Budget; month: string; onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label={budget ? `Budget: ${budget.name}` : 'Add budget'} width={500}>
      <BudgetFormBody budget={budget} month={month} />
    </Dialog>
  );
}

function BudgetFormBody({ budget, month }: { budget?: Budget; month: string }) {
  const close = useDialogClose();
  const { bump } = useShell();
  const [name, setName] = useState(budget?.name ?? '');
  const [mode, setMode] = useState<BudgetMode>(budget?.mode ?? 'fixed');
  const [amountText, setAmountText] = useState(budget && budget.amount ? paiseToInput(budget.amount) : '');
  const [limit, setLimit] = useState(budget?.limit != null ? paiseToInput(budget.limit) : '');
  const [active, setActive] = useState(budget?.active ?? true);
  const [cats, setCats] = useState<number[]>(budget?.category_ids ?? []);
  const categories = useApi<Category[]>('/categories');
  const all = useApi<BudgetMonth>(`/budgets?month=${month}`);
  // a category counts in one budget only
  const elsewhere = new Map(
    (all.data?.budgets ?? []).filter((x) => x.id !== budget?.id).flatMap((x) => x.category_ids.map((c) => [c, x.name] as const)),
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const auto = mode === 'manual' ? 0 : toPaise(amountText || '0');
    if (auto === null || auto < 0) return setError('Monthly amount must be a number');
    if (mode !== 'manual' && auto === 0) return setError('Enter the amount per month');
    setSaving(true);
    try {
      const body = { name, mode, amount: auto, active, category_ids: cats };
      let saved: Budget;
      if (budget) saved = await api<Budget>(`/budgets/${budget.id}?month=${month}`, { method: 'PATCH', body });
      else saved = await api<Budget>(`/budgets?month=${month}`, { method: 'POST', body });
      // This month's amount: only sent when changed by hand (or for a manual budget).
      const original = budget?.limit != null ? paiseToInput(budget.limit) : '';
      if (mode === 'manual' || (budget && limit !== original)) {
        if (limit.trim()) {
          const p = toPaise(limit);
          if (p === null || p < 0) throw new Error("This month's amount must be a number");
          await api(`/budgets/${saved.id}/limits/${month}`, { method: 'PUT', body: { amount: p } });
        } else if (budget && original) {
          await api(`/budgets/${saved.id}/limits/${month}`, { method: 'DELETE' });
        }
      }
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!budget) return;
    if (!confirmDelete) return setConfirmDelete(true);
    setSaving(true);
    try {
      await api(`/budgets/${budget.id}`, { method: 'DELETE' });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead title={budget ? budget.name : 'Add budget'} sub={`Amounts are in ₹ · ${monthLabel(month)}`} lead={<span className="ico" style={{ background: 'var(--indigo-50)', color: 'var(--indigo-600)' }}><Icon name="gauge" size={20} /></span>} />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        {budget && budget.limit !== null && (
          <div className="card card-pad" style={{ marginBottom: 18 }}>
            <div className="kv"><span className="k">Spent in {monthLabel(month)}</span><span className="v fig"><Money amount={rs(budget.spent)} /></span></div>
            <div className="kv"><span className="k">Available</span><span className="v fig"><Money amount={rs(budget.limit)} /></span></div>
            <div style={{ marginTop: 10 }}><Progress value={budget.spent} max={budget.limit} /></div>
          </div>
        )}
        <div className="field">
          <label htmlFor="bu-name">Name</label>
          <input id="bu-name" className="inp" value={name} onChange={(e) => setName(e.target.value)} required maxLength={80} placeholder="e.g. Groceries" />
        </div>
        <div className="field">
          <label>Monthly amount</label>
          <SegmentedControl
            aria-label="Budget mode"
            value={mode}
            onChange={(v) => setMode(v as BudgetMode)}
            options={[
              { value: 'fixed', label: 'Same every month' },
              { value: 'rollover', label: 'Rolls over' },
              { value: 'manual', label: 'Set by hand' },
            ]}
          />
          <div className="hint">
            {mode === 'fixed' && 'Each month starts with this amount.'}
            {mode === 'rollover' && "Each month gets this amount plus what was left last month (overspending reduces it)."}
            {mode === 'manual' && 'No automatic amount — you set it month by month.'}
          </div>
        </div>
        {mode !== 'manual' && (
          <div className="field">
            <label htmlFor="bu-auto">Amount per month (₹)</label>
            <input id="bu-auto" className="inp" inputMode="decimal" value={amountText} onChange={(e) => setAmountText(e.target.value)} placeholder="0.00" />
          </div>
        )}
        <div className="field">
          <label>Categories it counts</label>
          <div className="budget-cats">
            {(categories.data ?? [])
              .filter((c) => c.kind === 'expense')
              .map((c) => {
                const other = elsewhere.get(c.id);
                return (
                  <label key={c.id} className={`chip ${cats.includes(c.id) ? 'on' : ''}`} style={other ? { opacity: 0.45 } : undefined} title={other ? `Counts in “${other}”` : undefined}>
                    <input
                      type="checkbox"
                      hidden
                      checked={cats.includes(c.id)}
                      disabled={!!other}
                      onChange={(e) => setCats((xs) => (e.target.checked ? [...xs, c.id] : xs.filter((x) => x !== c.id)))}
                    />
                    {c.name}
                  </label>
                );
              })}
          </div>
          <div className="hint">Expenses in these categories count here by themselves — no need to pick the budget on each one. Optional.</div>
        </div>
        {(mode === 'manual' || budget) && (
          <div className="field">
            <label htmlFor="bu-limit">Amount for {monthLabel(month)} (₹)</label>
            <input id="bu-limit" className="inp" inputMode="decimal" value={limit} onChange={(e) => setLimit(e.target.value)} placeholder={mode === 'manual' ? '0.00' : 'Leave as is to use the monthly amount'} />
            {mode !== 'manual' && <div className="hint">Changing this sets this month by hand. Clear it to go back to the monthly amount.</div>}
          </div>
        )}
        {budget && (
          <>
            <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 14, marginBottom: 14 }}>
              <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
              Active <span className="muted" style={{ fontSize: 12.5 }}>— inactive budgets are hidden from the transaction form</span>
            </label>
            <Link href={`/transactions?budget=${budget.id}`} className="btn btn-secondary btn-sm" style={{ textDecoration: 'none' }}>
              <Icon name="arrow-left-right" size={15} /> All expenses in this budget
            </Link>
          </>
        )}
      </div>
      <div className="drawer-foot">
        {budget && (
          <Button variant={confirmDelete ? 'primary' : 'ghost'} icon="trash-2" onClick={remove} disabled={saving} className={confirmDelete ? 'btn-danger' : ''}>
            {confirmDelete ? 'Confirm delete' : 'Delete'}
          </Button>
        )}
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        <Button variant="primary" type="submit" disabled={saving}>{saving ? 'Saving…' : budget ? 'Save changes' : 'Add budget'}</Button>
      </div>
    </form>
  );
}
