'use client';
import { useState, type FormEvent } from 'react';
import Link from 'next/link';
import { api } from '../lib/api';
import { useApi, useShell } from '../contexts/ShellCtx';
import type {
  BudgetProposals,
  SavingsBasis,
  SavingsLine,
  SavingsPlan,
  SavingsRule,
  SavingsSettings,
  SavingsShare,
  SavingsSuggestion,
} from '../lib/types';
import { currentMonth, monthLabel, paiseToInput, rs, shiftMonth, toPaise } from '../lib/format';
import { Button } from '../primitives/Button';
import { Money } from '../primitives/Money';
import { SectionCard } from '../primitives/SectionCard';
import { Skeleton } from '../primitives/Skeleton';
import { ErrorState } from '../primitives/ErrorState';
import { SegmentedControl } from '../primitives/SegmentedControl';
import { Icon } from '../primitives/Icon';
import { CategoryGlyph } from '../primitives/CategoryGlyph';
import { Dialog, useDialogClose } from '../primitives/Dialog';
import { DrawerHead } from '../shared/DrawerHead';
import { PageHelp } from '../shared/PageHelp';

export const RULES: { value: SavingsRule; label: string; hint: string }[] = [
  { value: '50_30_20', label: '50/30/20', hint: 'Needs 50% · wants 30% · savings 20% — the usual starting point' },
  { value: '60_20_20', label: '60/20/20', hint: 'Needs 60% · wants 20% · savings 20% — for a city with high rent' },
  { value: '70_20_10', label: '70/20/10', hint: 'Needs 70% · wants 20% · savings 10% — for tight months' },
  { value: '80_20', label: '80/20 · pay yourself first', hint: 'Save 20% first; how the other 80% splits isn’t judged' },
  { value: 'custom', label: 'Custom', hint: 'Your own needs / wants / savings percentages' },
];
export const RULE_LABEL = Object.fromEntries(RULES.map((r) => [r.value, r.label])) as Record<SavingsRule, string>;
const BASIS_LABEL: Record<SavingsBasis, string> = {
  actual: 'income in the period',
  avg3: '3-month average income',
  fixed: 'your take-home pay',
};
const COLORS = { needs: 'var(--indigo-500)', wants: 'var(--coral-400)', savings: 'var(--mint-500)' };

export function SavingsPlanPage() {
  const [month, setMonth] = useState(currentMonth());
  const [avg, setAvg] = useState(false);
  const { data, error, reload } = useApi<SavingsPlan>(`/savings-plan?month=${avg ? 'avg3' : month}`);
  const [dialog, setDialog] = useState<'rule' | 'budgets' | null>(null);

  return (
    <div className="content-wrap fade-in">
      <div className="page-head">
        <div>
          <h1>Savings plan <PageHelp id="savings-plan" /></h1>
          <p>Where your income goes — needs, wants and savings — against the rule you pick.</p>
        </div>
        <div className="actions">
          <SegmentedControl
            aria-label="Period"
            value={avg ? 'avg' : 'month'}
            onChange={(v) => setAvg(v === 'avg')}
            options={[
              { value: 'month', label: 'Month' },
              { value: 'avg', label: '3-month average' },
            ]}
          />
          {!avg && (
            <div className="month-nav">
              <button className="icon-btn" aria-label="Previous month" onClick={() => setMonth(shiftMonth(month, -1))}>
                <Icon name="chevron-left" size={18} />
              </button>
              <span className="lbl">{monthLabel(month)}</span>
              <button className="icon-btn" aria-label="Next month" onClick={() => setMonth(shiftMonth(month, 1))}>
                <Icon name="chevron-right" size={18} />
              </button>
            </div>
          )}
          <Button variant="secondary" icon="sliders-horizontal" onClick={() => setDialog('rule')}>
            {data ? `Rule: ${RULE_LABEL[data.settings.rule]}` : 'Rule'}
          </Button>
        </div>
      </div>

      {error ? (
        <div className="card"><ErrorState message={error} onRetry={reload} /></div>
      ) : !data ? (
        <>
          <div className="grid-3 stat-grid"><Skeleton variant="stat" count={3} /></div>
          <Skeleton variant="block" height={260} />
        </>
      ) : (
        <Plan p={data} onBudgets={() => setDialog('budgets')} />
      )}

      {dialog === 'rule' && data && <RuleDialog settings={data.settings} onClose={() => setDialog(null)} />}
      {dialog === 'budgets' && <BudgetsDialog onClose={() => setDialog(null)} />}
    </div>
  );
}

function Plan({ p, onBudgets }: { p: SavingsPlan; onBudgets: () => void }) {
  const combined = p.settings.needs === null;
  const per = p.months > 1 ? ' a month' : '';
  return (
    <>
      <div className="note info" style={{ marginBottom: 14 }}>
        <Icon name="info" size={15} />
        <span>
          {p.period_label} · shares are of <b><Money amount={rs(p.income_used)} interactive={false} /></b>
          {per} ({BASIS_LABEL[p.settings.basis]})
          {p.settings.basis !== 'actual' && (
            <> — income in the period was <Money amount={rs(p.income)} interactive={false} />{per}</>
          )}
          .
        </span>
      </div>

      <div className={`${combined ? 'grid-2' : 'grid-3'} stat-grid`}>
        {combined ? (
          <ShareCard label="Spending" icon="shopping-bag" s={p.spending} kind="over" color={COLORS.needs} sub="Needs and wants together" />
        ) : (
          <>
            <ShareCard label="Needs" icon="house" s={p.needs} kind="over" color={COLORS.needs} sub="Essentials and loan EMIs" />
            <ShareCard label="Wants" icon="sparkles" s={p.wants} kind="over" color={COLORS.wants} sub="Everything else you spent" />
          </>
        )}
        <ShareCard label="Savings" icon="piggy-bank" s={p.savings} kind="under" color={COLORS.savings} sub="Income left after spending" />
      </div>

      <div className="card card-pad" style={{ marginBottom: 16 }}>
        <SplitBar p={p} />
      </div>

      {p.suggestions.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <SectionCard title="What to do" action={p.settings.wants !== null ? { label: 'Make budgets from this rule', onClick: onBudgets } : undefined}>
            {p.suggestions.map((s, i) => (
              <SuggestionRow key={i} s={s} />
            ))}
          </SectionCard>
        </div>
      )}

      <div className="grid-2" style={{ marginBottom: 16 }}>
        <SectionCard title="Needs">
          <Lines lines={p.needs_lines} income={p.income_used} empty="No essential spending in this period." />
        </SectionCard>
        <SectionCard title="Wants">
          <Lines lines={p.wants_lines} income={p.income_used} empty="No other spending in this period." />
          {p.uncategorised > 0 && (
            <div className="muted" style={{ fontSize: 12, padding: '0 20px 14px' }}>
              Uncategorised spending counts as wants until you give it a category.
            </div>
          )}
        </SectionCard>
      </div>

      <SectionCard title="Where the savings went" pad>
        <div className="kv"><span className="k">Moved to investments</span><span className="v fig"><Money amount={rs(p.savings_split.to_investments)} sign={p.savings_split.to_investments < 0} /></span></div>
        <div className="kv"><span className="k">Set aside in piggy banks / emergency fund</span><span className="v fig"><Money amount={rs(p.savings_split.to_goals)} sign={p.savings_split.to_goals < 0} /></span></div>
        <div className="kv">
          <span className="k">{p.savings_split.left_in_bank < 0 ? 'Taken from what you had' : 'Left in the bank'}</span>
          <span className="v fig"><Money amount={rs(p.savings_split.left_in_bank)} sign={p.savings_split.left_in_bank < 0} /></span>
        </div>
        <div className="hint" style={{ marginTop: 8 }}>
          Investments count SIPs and transfers into your funds and deposits (less money taken out), and spending in the “Investment” category.
        </div>
      </SectionCard>
    </>
  );
}

function ShareCard({ label, icon, s, kind, color, sub }: { label: string; icon: string; s: SavingsShare; kind: 'over' | 'under'; color: string; sub: string }) {
  const diff = s.diff ?? 0;
  const bad = s.target !== null && (kind === 'over' ? diff > 0 : diff < 0);
  return (
    <div className="card card-pad stat">
      <div className="lbl"><Icon name={icon} size={13} /> {label}</div>
      <div className="val" style={{ color }}>{s.pct !== null ? `${s.pct}%` : '—'}</div>
      <div style={{ fontSize: 13 }}>
        <Money amount={rs(s.amount)} sign={s.amount < 0} />
        {s.target_pct !== null && <span className="muted"> · target {s.target_pct}%</span>}
      </div>
      {s.target !== null ? (
        <div style={{ fontSize: 12.5, marginTop: 4, color: bad ? 'var(--red-600)' : 'var(--mint-700)', fontWeight: 600 }}>
          {diff === 0 ? (
            'Right on target'
          ) : kind === 'over' ? (
            <><Money amount={rs(Math.abs(diff))} interactive={false} /> {diff > 0 ? 'over' : 'under'}</>
          ) : (
            <>{diff < 0 ? 'Save ' : ''}<Money amount={rs(Math.abs(diff))} interactive={false} /> {diff < 0 ? 'more to reach it' : 'above target'}</>
          )}
        </div>
      ) : (
        <div className="muted" style={{ fontSize: 12.5, marginTop: 4 }}>{sub}</div>
      )}
    </div>
  );
}

/** The actual split as one bar, with the target split underneath. */
function SplitBar({ p }: { p: SavingsPlan }) {
  const combined = p.settings.needs === null;
  const actual = [
    { key: 'needs', pct: p.needs.pct ?? 0, color: COLORS.needs, label: 'Needs' },
    { key: 'wants', pct: p.wants.pct ?? 0, color: COLORS.wants, label: 'Wants' },
    { key: 'savings', pct: Math.max(0, p.savings.pct ?? 0), color: COLORS.savings, label: 'Savings' },
  ];
  const target = combined
    ? [
        { key: 'spend', pct: 100 - p.settings.savings, color: 'var(--neutral-400)', label: 'Spending' },
        { key: 'savings', pct: p.settings.savings, color: COLORS.savings, label: 'Savings' },
      ]
    : [
        { key: 'needs', pct: p.settings.needs ?? 0, color: COLORS.needs, label: 'Needs' },
        { key: 'wants', pct: p.settings.wants ?? 0, color: COLORS.wants, label: 'Wants' },
        { key: 'savings', pct: p.settings.savings, color: COLORS.savings, label: 'Savings' },
      ];
  const total = actual.reduce((a, b) => a + b.pct, 0);
  const bar = (parts: typeof actual, scale: number) => (
    <div style={{ display: 'flex', height: 14, borderRadius: 999, overflow: 'hidden', background: 'var(--bg-sunken)' }}>
      {parts.map((x) => (
        <i key={x.key} title={`${x.label} ${x.pct}%`} style={{ width: `${(x.pct * 100) / scale}%`, background: x.color }} />
      ))}
    </div>
  );
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, marginBottom: 6 }}>
        <b>Your split</b>
        {total > 100 && <span style={{ color: 'var(--red-600)' }}>Spent {Math.round(total - 100)}% more than the income</span>}
      </div>
      {bar(actual, Math.max(100, total))}
      <div style={{ fontSize: 12.5, margin: '12px 0 6px' }}><b>Target</b> · {RULE_LABEL[p.settings.rule]}</div>
      {bar(target, 100)}
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontSize: 12, marginTop: 10 }} className="muted">
        {actual.map((x) => (
          <span key={x.key} style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
            <i style={{ width: 10, height: 10, borderRadius: 3, background: x.color, display: 'inline-block' }} /> {x.label}
          </span>
        ))}
      </div>
    </div>
  );
}

function SuggestionRow({ s }: { s: SavingsSuggestion }) {
  const icon = s.tone === 'warn' ? 'triangle-alert' : s.tone === 'good' ? 'circle-check' : 'info';
  const color = s.tone === 'warn' ? 'var(--amber-700)' : s.tone === 'good' ? 'var(--mint-700)' : 'var(--indigo-600)';
  return (
    <div className="catrow" style={{ display: 'block' }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
        <span style={{ color, marginTop: 1 }}><Icon name={icon} size={17} /></span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }}>
            <b style={{ fontSize: 14 }}>{s.title}</b>
            {s.amount !== null && <span className="fig" style={{ fontSize: 13.5 }}><Money amount={rs(s.amount)} interactive={false} />{s.kind === 'save_more' || s.kind === 'emergency_first' ? ' a month' : ''}</span>}
          </div>
          {s.detail && <div className="muted" style={{ fontSize: 13, marginTop: 3 }}>{s.detail}</div>}
          {s.items.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
              {s.items.map((x) => (
                <div key={`${x.category_id}-${x.name}`} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
                  <CategoryGlyph icon={x.icon} color={x.color} size={22} />
                  <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{x.name}</span>
                  <span className="fig">
                    {s.kind === 'needs_over' ? '' : '− '}
                    <Money amount={rs(x.amount)} interactive={false} />
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Lines({ lines, income, empty }: { lines: SavingsLine[]; income: number; empty: string }) {
  if (lines.length === 0) return <div className="muted" style={{ padding: '14px 20px', fontSize: 13 }}>{empty}</div>;
  return (
    <>
      {lines.map((x) => (
        <div key={`${x.category_id}-${x.name}`} className="catrow" style={{ display: 'block' }}>
          <div className="top" style={{ marginBottom: 0 }}>
            <span className="nm" style={{ minWidth: 0 }}>
              <CategoryGlyph icon={x.icon} color={x.color} size={26} />
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{x.name}</span>
              {x.before !== null && x.before > 0 && x.amount > x.before * 1.2 && (
                <span className="badge cau" title="Compared with the average of the 3 months before">Up</span>
              )}
            </span>
            <span style={{ fontSize: 13, whiteSpace: 'nowrap' }}>
              <span className="fig"><Money amount={rs(x.amount)} interactive={false} /></span>
              {income > 0 && <span className="muted"> · {Math.round((x.amount * 1000) / income) / 10}%</span>}
            </span>
          </div>
        </div>
      ))}
    </>
  );
}

// ---------------------------------------------------------------- the rule

function RuleDialog({ settings, onClose }: { settings: SavingsSettings; onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label="Savings rule" width={520}>
      <RuleBody settings={settings} />
    </Dialog>
  );
}

function RuleBody({ settings }: { settings: SavingsSettings }) {
  const close = useDialogClose();
  const { bump } = useShell();
  const [rule, setRule] = useState<SavingsRule>(settings.rule);
  const [needs, setNeeds] = useState(String(settings.needs ?? 50));
  const [wants, setWants] = useState(String(settings.wants ?? 30));
  const [savings, setSavings] = useState(String(settings.savings));
  const [basis, setBasis] = useState<SavingsBasis>(settings.basis);
  const [income, setIncome] = useState(settings.fixed_income ? paiseToInput(settings.fixed_income) : '');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const sum = Number(needs || 0) + Number(wants || 0) + Number(savings || 0);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const body: Record<string, unknown> = { rule, basis };
    if (rule === 'custom') {
      if (sum !== 100) return setError('Needs, wants and savings must add up to 100%.');
      Object.assign(body, { needs: Number(needs), wants: Number(wants), savings: Number(savings) });
    }
    if (basis === 'fixed') {
      const p = toPaise(income);
      if (p === null || p <= 0) return setError('Enter your monthly take-home pay.');
      body.fixed_income = p;
    }
    setSaving(true);
    try {
      await api('/savings-plan/settings', { method: 'PUT', body });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead title="Savings rule" sub="How your income should split" lead={<CategoryGlyph icon="sliders-horizontal" color="indigo" size={42} />} />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        <div className="field">
          <label>Rule</label>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {RULES.map((r) => (
              <label key={r.value} className={`ls-event ${rule === r.value ? 'on' : ''}`} style={{ display: 'flex', gap: 10, alignItems: 'flex-start', cursor: 'pointer' }}>
                <input type="radio" name="rule" checked={rule === r.value} onChange={() => setRule(r.value)} style={{ marginTop: 3 }} />
                <span>
                  <b>{r.label}</b>
                  <div className="muted" style={{ fontSize: 12.5 }}>{r.hint}</div>
                </span>
              </label>
            ))}
          </div>
        </div>
        {rule === 'custom' && (
          <div className="field">
            <div className="row3" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 10 }}>
              {(
                [
                  ['Needs %', needs, setNeeds],
                  ['Wants %', wants, setWants],
                  ['Savings %', savings, setSavings],
                ] as const
              ).map(([label, value, set]) => (
                <div key={label}>
                  <label htmlFor={`sp-${label}`} style={{ fontSize: 12.5 }}>{label}</label>
                  <input id={`sp-${label}`} className="inp" inputMode="numeric" value={value} onChange={(e) => set(e.target.value.replace(/\D/g, '').slice(0, 3))} />
                </div>
              ))}
            </div>
            <div className="hint" style={{ color: sum === 100 ? undefined : 'var(--red-600)' }}>Adds up to {sum}% — it must be 100%.</div>
          </div>
        )}
        <div className="field">
          <label>Income the shares are of</label>
          <SegmentedControl
            aria-label="Income basis"
            value={basis}
            onChange={(v) => setBasis(v as SavingsBasis)}
            options={[
              { value: 'actual', label: 'That month' },
              { value: 'avg3', label: '3-month average' },
              { value: 'fixed', label: 'Fixed take-home' },
            ]}
          />
          <div className="hint">
            {basis === 'actual' && 'The income that came in during the month you look at.'}
            {basis === 'avg3' && 'Smooths out a bonus or a month without salary.'}
            {basis === 'fixed' && 'For irregular income: your usual monthly take-home pay.'}
          </div>
        </div>
        {basis === 'fixed' && (
          <div className="field">
            <label htmlFor="sp-income">Monthly take-home (₹)</label>
            <input id="sp-income" className="inp" inputMode="decimal" value={income} onChange={(e) => setIncome(e.target.value)} placeholder="0.00" />
          </div>
        )}
      </div>
      <div className="drawer-foot">
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        <Button variant="primary" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save'}</Button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------- budgets from the rule

function BudgetsDialog({ onClose }: { onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label="Make budgets from this rule" width={560}>
      <BudgetsBody />
    </Dialog>
  );
}

function BudgetsBody() {
  const close = useDialogClose();
  const { bump } = useShell();
  const { data, error } = useApi<BudgetProposals>('/savings-plan/budgets');
  const [picks, setPicks] = useState<Record<number, { on: boolean; amount: string }>>({});
  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState<number | null>(null);

  const pick = (id: number, fallback: number) => picks[id] ?? { on: true, amount: paiseToInput(fallback) };
  const ticked = (data?.items ?? []).filter((x) => pick(x.category_id, x.amount).on);
  const total = ticked.reduce((a, x) => a + (toPaise(pick(x.category_id, x.amount).amount) ?? 0), 0);

  const create = async () => {
    setErr(null);
    const items = [];
    for (const x of ticked) {
      const p = toPaise(pick(x.category_id, x.amount).amount);
      if (p === null || p <= 0) return setErr(`Enter an amount for ${x.name}.`);
      items.push({ category_id: x.category_id, amount: p });
    }
    setSaving(true);
    try {
      const r = await api<{ created: unknown[] }>('/savings-plan/budgets', { method: 'POST', body: { items } });
      setDone(r.created.length);
      bump();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <DrawerHead title="Make budgets from this rule" sub="One budget per want category, adding up to your wants share" lead={<CategoryGlyph icon="gauge" color="indigo" size={42} />} />
      <div className="drawer-body">
        {(error || err) && <div className="form-error" role="alert">{error ?? err}</div>}
        {done !== null ? (
          <div className="note privacy">
            <Icon name="check" size={15} />
            <span>
              {done} budget{done === 1 ? '' : 's'} made. Each counts its category by itself — you don&apos;t have to pick it on every expense.{' '}
              <Link href="/budgets"><b>See budgets</b></Link>
            </span>
          </div>
        ) : !data ? (
          !error && <Skeleton variant="block" height={160} />
        ) : (
          <>
            <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>
              Your wants share is <b><Money amount={rs(data.wants_target)} interactive={false} /></b> a month (3-month average income). Each
              category gets a part of it in line with what you usually spend there. Change any amount, or untick what you don&apos;t want.
            </p>
            {data.items.length === 0 ? (
              <div className="muted" style={{ fontSize: 13 }}>No want categories without a budget in the last 3 months.</div>
            ) : (
              <div className="tbl-wrap">
                <table className="tbl" style={{ fontSize: 13 }}>
                  <thead>
                    <tr><th style={{ width: 34 }} /><th>Category</th><th className="r">Usually</th><th className="r" style={{ width: 130 }}>Budget a month</th></tr>
                  </thead>
                  <tbody>
                    {data.items.map((x) => {
                      const v = pick(x.category_id, x.amount);
                      const set = (u: Partial<typeof v>) => setPicks((p) => ({ ...p, [x.category_id]: { ...v, ...u } }));
                      return (
                        <tr key={x.category_id} style={v.on ? undefined : { opacity: 0.55 }}>
                          <td><input type="checkbox" checked={v.on} onChange={(e) => set({ on: e.target.checked })} aria-label={`Make a budget for ${x.name}`} /></td>
                          <td>
                            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                              <CategoryGlyph icon={x.icon} color={x.color} size={22} /> {x.name}
                            </span>
                          </td>
                          <td className="r fig"><Money amount={rs(x.average)} interactive={false} /></td>
                          <td className="r">
                            <input className="inp" inputMode="decimal" style={{ padding: '6px 9px', textAlign: 'right' }} value={v.amount} disabled={!v.on} onChange={(e) => set({ amount: e.target.value })} aria-label={`Budget for ${x.name}`} />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            {data.taken.length > 0 && (
              <div className="muted" style={{ fontSize: 12.5, marginTop: 10 }}>
                Already in a budget: {data.taken.map((x) => `${x.name} (${x.budget_name})`).join(', ')}.
              </div>
            )}
            {ticked.length > 0 && (
              <div className="kv" style={{ marginTop: 12 }}>
                <span className="k">Total</span>
                <span className="v fig" style={{ color: total > data.wants_target ? 'var(--red-600)' : undefined }}>
                  <Money amount={rs(total)} interactive={false} /> of <Money amount={rs(data.wants_target)} interactive={false} />
                </span>
              </div>
            )}
          </>
        )}
      </div>
      <div className="drawer-foot">
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>{done !== null ? 'Close' : 'Cancel'}</Button>
        {done === null && (
          <Button variant="primary" icon="check" onClick={create} disabled={saving || ticked.length === 0}>
            {saving ? 'Making…' : `Make ${ticked.length} budget${ticked.length === 1 ? '' : 's'}`}
          </Button>
        )}
      </div>
    </>
  );
}
