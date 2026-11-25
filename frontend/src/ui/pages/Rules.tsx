'use client';
import { useEffect, useState, type FormEvent } from 'react';
import { api } from '../lib/api';
import { useApi, useShell } from '../contexts/ShellCtx';
import type {
  Account,
  Bill,
  BudgetMonth,
  Category,
  Rule,
  RuleActionType,
  RuleConditionType,
  RuleItem,
  RuleSuggestion,
  RuleTestResult,
} from '../lib/types';
import { fmtDate, inr2, toPaise } from '../lib/format';
import { Button } from '../primitives/Button';
import { Skeleton } from '../primitives/Skeleton';
import { EmptyState } from '../primitives/EmptyState';
import { ErrorState } from '../primitives/ErrorState';
import { Icon } from '../primitives/Icon';
import { CategoryGlyph } from '../primitives/CategoryGlyph';
import { SegmentedControl } from '../primitives/SegmentedControl';
import { Dialog, useDialogClose } from '../primitives/Dialog';
import { DrawerHead } from '../shared/DrawerHead';
import { CategoryOptions } from '../shared/CategoryOptions';
import { PageHelp } from '../shared/PageHelp';

// ---------------------------------------------------------------- vocabulary

type Kind = 'text' | 'amount' | 'type' | 'account' | 'category' | 'budget' | 'bill' | 'none';

const CONDITIONS: { type: RuleConditionType; label: string; kind: Kind }[] = [
  { type: 'description_contains', label: 'Description contains', kind: 'text' },
  { type: 'description_starts', label: 'Description starts with', kind: 'text' },
  { type: 'description_is', label: 'Description is exactly', kind: 'text' },
  { type: 'payee_contains', label: 'Payee contains', kind: 'text' },
  { type: 'amount_is', label: 'Amount is', kind: 'amount' },
  { type: 'amount_more', label: 'Amount more than', kind: 'amount' },
  { type: 'amount_less', label: 'Amount less than', kind: 'amount' },
  { type: 'type_is', label: 'Type is', kind: 'type' },
  { type: 'account_is', label: 'Account is', kind: 'account' },
  { type: 'no_category', label: 'Has no category', kind: 'none' },
  { type: 'has_tag', label: 'Has tag', kind: 'text' },
];
const ACTIONS: { type: RuleActionType; label: string; kind: Kind }[] = [
  { type: 'set_category', label: 'Set category', kind: 'category' },
  { type: 'set_budget', label: 'Set budget', kind: 'budget' },
  { type: 'set_bill', label: 'Link to bill', kind: 'bill' },
  { type: 'add_tag', label: 'Add tag', kind: 'text' },
  { type: 'remove_tag', label: 'Remove tag', kind: 'text' },
  { type: 'set_payee', label: 'Rename payee to', kind: 'text' },
  { type: 'set_description', label: 'Set description to', kind: 'text' },
  { type: 'add_note', label: 'Add note', kind: 'text' },
];
const TYPE_LABEL: Record<string, string> = { withdrawal: 'Expense', deposit: 'Income', transfer: 'Transfer' };
const kindOf = (type: string): Kind =>
  CONDITIONS.find((c) => c.type === type)?.kind ?? ACTIONS.find((a) => a.type === type)?.kind ?? 'text';
const labelOf = (type: string) => CONDITIONS.find((c) => c.type === type)?.label ?? ACTIONS.find((a) => a.type === type)?.label ?? type;

interface Lookups {
  accounts: Account[];
  categories: Category[];
  budgets: { id: number; name: string }[];
  bills: Bill[];
}

function useLookups(): Lookups {
  const accounts = useApi<Account[]>('/accounts?type=asset&type=cash&type=credit_card&type=investment');
  const categories = useApi<Category[]>('/categories');
  const budgets = useApi<BudgetMonth>('/budgets');
  const bills = useApi<Bill[]>('/bills');
  return {
    accounts: accounts.data ?? [],
    categories: categories.data ?? [],
    budgets: (budgets.data?.budgets ?? []).map((b) => ({ id: b.id, name: b.name })),
    bills: bills.data ?? [],
  };
}

/** One condition / action in words: "Payee contains “swiggy”", "Set category Dining". */
function itemText(it: RuleItem, lk: Lookups): string {
  const kind = kindOf(it.type);
  const v = it.value;
  const named = (list: { id: number; name: string }[]) => list.find((x) => x.id === Number(v))?.name ?? '(deleted)';
  const value =
    kind === 'none'
      ? ''
      : kind === 'text'
        ? `“${v}”`
        : kind === 'amount'
          ? inr2(Number(v) / 100)
          : kind === 'type'
            ? TYPE_LABEL[String(v)] ?? String(v)
            : kind === 'account'
              ? named(lk.accounts)
              : kind === 'category'
                ? named(lk.categories)
                : kind === 'budget'
                  ? named(lk.budgets)
                  : named(lk.bills);
  return `${labelOf(it.type)}${value ? ` ${value}` : ''}`;
}

const lower = (s: string) => s.charAt(0).toLowerCase() + s.slice(1);

// ---------------------------------------------------------------- page

export function RulesPage() {
  const { data, error, reload } = useApi<Rule[]>('/rules');
  const sugg = useApi<RuleSuggestion[]>('/rules/suggestions');
  const lk = useLookups();
  const { bump } = useShell();
  const [editing, setEditing] = useState<Rule | 'new' | null>(null);
  const [applying, setApplying] = useState<Rule | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const call = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      bump();
    } catch (e) {
      setMsg((e as Error).message);
    }
    setBusy(false);
  };
  const fromSuggestion = (s: RuleSuggestion) =>
    call(async () => {
      const made = await api<Rule>('/rules', {
        method: 'POST',
        body: {
          title: `${s.payee} → ${s.category}`.slice(0, 120),
          conditions: [{ type: 'payee_contains', value: s.payee }, { type: 'type_is', value: s.type }],
          actions: [{ type: 'set_category', value: s.category_id }],
        },
      });
      setApplying(made);
    });

  return (
    <div className="content-wrap fade-in">
      <div className="page-head">
        <div>
          <h1>Rules <PageHelp id="rules" /></h1>
          <p>Set the category, tags or payee name automatically — on transactions you add, from the Inbox and on statement import.</p>
        </div>
        <div className="actions">
          <Button variant="primary" icon="plus" onClick={() => setEditing('new')}>New rule</Button>
        </div>
      </div>
      {msg && <div className="form-error" role="alert" style={{ marginBottom: 12 }}>{msg}</div>}

      {(sugg.data ?? []).length > 0 && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="inv-group-head"><span>Suggested rules · from your history</span></div>
          {(sugg.data ?? []).map((s) => (
            <div key={`${s.type}-${s.payee}`} className="rule-sugg">
              <Icon name="zap" size={15} color="var(--amber-700)" />
              <span className="mid">
                <b>{s.payee}</b> → {s.category}
                <span className="muted"> · {s.count} of {s.total} {s.type === 'withdrawal' ? 'expenses' : 'income'} so far</span>
              </span>
              <Button variant="secondary" size="sm" disabled={busy} onClick={() => fromSuggestion(s)}>Create rule</Button>
            </div>
          ))}
        </div>
      )}

      {error ? (
        <div className="card"><ErrorState message={error} onRetry={reload} /></div>
      ) : !data ? (
        <Skeleton variant="block" height={200} />
      ) : data.length === 0 ? (
        <div className="card">
          <EmptyState
            icon="zap"
            title="No rules yet"
            body="A rule sets things for you — e.g. payee contains “swiggy” → category Dining, tag #delivery. On statements you can also tick “Rule for next time” after choosing a category."
            action={{ label: 'New rule', onClick: () => setEditing('new') }}
          />
        </div>
      ) : (
        <>
          <div className="muted" style={{ fontSize: 12.5, marginBottom: 8 }}>
            Rules run top to bottom. When two set the same thing, the higher one wins. On transactions you add, rules only fill what you left empty.
          </div>
          <div className="card">
            {data.map((r, i) => (
              <div key={r.id} className={`rule-row ${r.active ? '' : 'off'}`}>
                <span className="num">{i + 1}</span>
                <div className="mid">
                  <div className="nm">
                    {r.title}
                    {!r.active && <span className="badge neutral" style={{ marginLeft: 6 }}>Off</span>}
                    {r.stop && <span className="badge neutral" style={{ marginLeft: 6 }}>Stops here</span>}
                  </div>
                  <div className="sub">
                    <span>When {r.conditions.map((c) => lower(itemText(c, lk))).join(r.match_all ? ' and ' : ' or ')}</span>
                    <span>→ {r.actions.map((a) => itemText(a, lk)).join(', ')}</span>
                  </div>
                </div>
                <div className="acts">
                  <Button variant="ghost" size="sm" icon="chevron-up" aria-label="Move up" title="Move up" disabled={busy || i === 0}
                    onClick={() => call(() => api(`/rules/${r.id}/move`, { method: 'POST', body: { direction: 'up' } }))} />
                  <Button variant="ghost" size="sm" icon="chevron-down" aria-label="Move down" title="Move down" disabled={busy || i === data.length - 1}
                    onClick={() => call(() => api(`/rules/${r.id}/move`, { method: 'POST', body: { direction: 'down' } }))} />
                  <Button variant="ghost" size="sm" disabled={busy}
                    onClick={() => call(() => api(`/rules/${r.id}`, { method: 'PATCH', body: { active: !r.active } }))}>
                    {r.active ? 'Turn off' : 'Turn on'}
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => setApplying(r)}>Apply to past</Button>
                  <Button variant="secondary" size="sm" icon="pencil" onClick={() => setEditing(r)}>Edit</Button>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
      {editing && (
        <RuleEditor rule={editing === 'new' ? null : editing} lk={lk} onClose={() => setEditing(null)} onSaved={(r) => setApplying(r)} />
      )}
      {applying && <ApplyDialog rule={applying} onClose={() => setApplying(null)} />}
    </div>
  );
}

// ---------------------------------------------------------------- editor

type Draft = { type: string; value: string };

const toDraft = (it: RuleItem): Draft => ({
  type: it.type,
  value: it.value == null ? '' : kindOf(it.type) === 'amount' ? String(Number(it.value) / 100) : String(it.value),
});

function toItem(d: Draft): RuleItem | string {
  const kind = kindOf(d.type);
  if (kind === 'none') return { type: d.type };
  if (!d.value.trim()) return `Fill in “${labelOf(d.type)}”.`;
  if (kind === 'amount') {
    const p = toPaise(d.value);
    if (p === null || p < 0) return `“${labelOf(d.type)}” needs an amount, e.g. 500.`;
    return { type: d.type, value: p };
  }
  if (['account', 'category', 'budget', 'bill'].includes(kind)) return { type: d.type, value: Number(d.value) };
  return { type: d.type, value: d.value.trim() };
}

function RuleEditor({ rule, lk, onClose, onSaved }: { rule: Rule | null; lk: Lookups; onClose: () => void; onSaved: (r: Rule) => void }) {
  return (
    <Dialog onClose={onClose} label={rule ? `Rule: ${rule.title}` : 'New rule'} width={640}>
      <EditorBody rule={rule} lk={lk} onSaved={onSaved} />
    </Dialog>
  );
}

function EditorBody({ rule, lk, onSaved }: { rule: Rule | null; lk: Lookups; onSaved: (r: Rule) => void }) {
  const close = useDialogClose();
  const { bump } = useShell();
  const [title, setTitle] = useState(rule?.title ?? '');
  const [matchAll, setMatchAll] = useState(rule?.match_all ?? true);
  const [stop, setStop] = useState(rule?.stop ?? false);
  const [conds, setConds] = useState<Draft[]>(rule ? rule.conditions.map(toDraft) : [{ type: 'payee_contains', value: '' }]);
  const [acts, setActs] = useState<Draft[]>(rule ? rule.actions.map(toDraft) : [{ type: 'set_category', value: '' }]);
  const [test, setTest] = useState<RuleTestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  // an expense / income category list fits a "Type is" condition when there is one
  const typeCond = conds.find((c) => c.type === 'type_is')?.value;
  const catKind = typeCond === 'withdrawal' ? 'expense' : typeCond === 'deposit' ? 'income' : undefined;

  const body = (): Record<string, unknown> | string => {
    const c = conds.map(toItem);
    const a = acts.map(toItem);
    const bad = [...c, ...a].find((x) => typeof x === 'string');
    if (bad) return bad as string;
    if (!c.length || !a.length) return 'Add at least one condition and one action.';
    const first = c[0] as RuleItem;
    const auto = first.value ? `${labelOf(first.type)} ${first.value}` : labelOf(first.type);
    return { title: (title.trim() || auto).slice(0, 120), match_all: matchAll, stop, conditions: c, actions: a };
  };

  const runTest = async () => {
    const b = body();
    if (typeof b === 'string') return setError(b);
    setError(null);
    try {
      setTest(await api<RuleTestResult>('/rules/test', { method: 'POST', body: b }));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const b = body();
    if (typeof b === 'string') return setError(b);
    setSaving(true);
    try {
      const saved = rule
        ? await api<Rule>(`/rules/${rule.id}`, { method: 'PATCH', body: b })
        : await api<Rule>('/rules', { method: 'POST', body: b });
      bump();
      close();
      if (!rule) onSaved(saved); // offer to run the new rule on past transactions
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!rule) return;
    if (!confirmDelete) return setConfirmDelete(true);
    setSaving(true);
    try {
      await api(`/rules/${rule.id}`, { method: 'DELETE' });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  const valueInput = (d: Draft, set: (v: string) => void, label: string) => {
    const kind = kindOf(d.type);
    const common = { className: 'inp', 'aria-label': label, value: d.value, onChange: (e: { target: { value: string } }) => set(e.target.value) };
    if (kind === 'none') return <span />;
    if (kind === 'type')
      return (
        <select {...common}>
          <option value="">Choose…</option>
          {Object.entries(TYPE_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      );
    if (kind === 'account')
      return (
        <select {...common}>
          <option value="">Choose…</option>
          {lk.accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
      );
    if (kind === 'category')
      return (
        <select {...common}>
          <option value="">Choose…</option>
          <CategoryOptions categories={lk.categories} kind={catKind} keep={d.value ? Number(d.value) : null} />
        </select>
      );
    if (kind === 'budget' || kind === 'bill') {
      const list = kind === 'budget' ? lk.budgets : lk.bills;
      return (
        <select {...common}>
          <option value="">Choose…</option>
          {list.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
        </select>
      );
    }
    return <input {...common} inputMode={kind === 'amount' ? 'decimal' : undefined} placeholder={kind === 'amount' ? '₹' : ''} maxLength={255} />;
  };

  const list = (
    items: Draft[],
    setItems: (x: Draft[]) => void,
    vocab: { type: string; label: string }[],
    what: string,
  ) => (
    <div className="rule-items">
      {items.map((d, i) => (
        <div key={i} className="rule-item">
          <select
            className="inp"
            aria-label={`${what} ${i + 1}`}
            value={d.type}
            onChange={(e) => setItems(items.map((x, j) => (j === i ? { type: e.target.value, value: '' } : x)))}
          >
            {vocab.map((v) => <option key={v.type} value={v.type}>{v.label}</option>)}
          </select>
          {valueInput(d, (v) => setItems(items.map((x, j) => (j === i ? { ...x, value: v } : x))), `${what} ${i + 1} value`)}
          <Button variant="ghost" size="sm" icon="x" aria-label={`Remove ${what} ${i + 1}`} disabled={items.length === 1}
            onClick={() => setItems(items.filter((_, j) => j !== i))} />
        </div>
      ))}
      <Button variant="ghost" size="sm" icon="plus" onClick={() => setItems([...items, { type: vocab[0].type, value: '' }])}>
        Add {what}
      </Button>
    </div>
  );

  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead title={rule ? rule.title : 'New rule'} sub="When … then …" lead={<CategoryGlyph icon="zap" color="amber" size={42} />} />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        <div className="field">
          <label htmlFor="rule-title">Name <span className="muted" style={{ fontWeight: 400 }}>(optional)</span></label>
          <input id="rule-title" className="inp" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} placeholder="e.g. Swiggy → Dining" />
        </div>
        <div className="field">
          <label>When</label>
          <SegmentedControl
            aria-label="Match"
            value={matchAll ? 'all' : 'any'}
            onChange={(v) => setMatchAll(v === 'all')}
            options={[{ value: 'all', label: 'All of these match' }, { value: 'any', label: 'Any one matches' }]}
          />
        </div>
        {list(conds, (x) => { setConds(x); setTest(null); }, CONDITIONS, 'condition')}
        <div className="field" style={{ marginTop: 14 }}><label>Then</label></div>
        {list(acts, (x) => { setActs(x); setTest(null); }, ACTIONS, 'action')}
        <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13.5, marginTop: 14 }}>
          <input type="checkbox" checked={stop} onChange={(e) => setStop(e.target.checked)} />
          Stop here — rules below this one don&apos;t run when it matches
        </label>

        <div className="card card-pad" style={{ marginTop: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <Button variant="secondary" size="sm" icon="search" onClick={runTest}>Test against existing</Button>
            {test && (
              <span style={{ fontSize: 13 }}>
                Matches <b>{test.matched}</b> transaction{test.matched === 1 ? '' : 's'} · would change <b>{test.would_change}</b> (filling blanks)
              </span>
            )}
          </div>
          {test && test.items.length > 0 && (
            <div className="rule-test">
              {test.items.slice(0, 12).map(({ transaction: t, changes }) => (
                <div key={t.id}>
                  <span className="muted">{fmtDate(t.date)}</span> {t.description}{' '}
                  <span className="muted">· {inr2(t.amount / 100)}</span>
                  {changes.length ? <span className="chg"> → {changes.join(', ')}</span> : <span className="muted"> · already set</span>}
                </div>
              ))}
              {test.matched > 12 && <div className="muted">…and {test.matched - 12} more</div>}
            </div>
          )}
        </div>
      </div>
      <div className="drawer-foot">
        {rule && (
          <Button variant={confirmDelete ? 'primary' : 'ghost'} icon="trash-2" onClick={remove} disabled={saving} className={confirmDelete ? 'btn-danger' : ''}>
            {confirmDelete ? 'Confirm delete' : 'Delete'}
          </Button>
        )}
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        <Button variant="primary" type="submit" disabled={saving}>{saving ? 'Saving…' : rule ? 'Save rule' : 'Create rule'}</Button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------- apply to past transactions

function ApplyDialog({ rule, onClose }: { rule: Rule; onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label="Apply to past transactions" width={520}>
      <ApplyBody rule={rule} />
    </Dialog>
  );
}

function ApplyBody({ rule }: { rule: Rule }) {
  const close = useDialogClose();
  const { bump } = useShell();
  const [overwrite, setOverwrite] = useState(false);
  const [preview, setPreview] = useState<RuleTestResult | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const fetchPreview = (ow: boolean) =>
    api<RuleTestResult>(`/rules/test?overwrite=${ow}`, {
      method: 'POST',
      body: { title: rule.title, match_all: rule.match_all, conditions: rule.conditions, actions: rule.actions },
    });
  const look = async (ow: boolean) => {
    setOverwrite(ow);
    setPreview(null);
    try {
      setPreview(await fetchPreview(ow));
    } catch (e) {
      setError((e as Error).message);
    }
  };
  useEffect(() => {
    let live = true; // what "only fill blanks" would change
    fetchPreview(false)
      .then((p) => live && setPreview(p))
      .catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rule.id]);

  const apply = async () => {
    setBusy(true);
    try {
      const r = await api<{ matched: number; changed: number }>(`/rules/${rule.id}/apply`, { method: 'POST', body: { overwrite } });
      setDone(`Done — ${r.changed} of ${r.matched} matching transaction${r.matched === 1 ? '' : 's'} changed.`);
      bump();
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(false);
  };

  return (
    <>
      <DrawerHead title="Apply to past transactions" sub={rule.title} lead={<CategoryGlyph icon="zap" color="amber" size={42} />} />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        {done ? (
          <div className="note privacy"><Icon name="check" size={15} /> <span>{done}</span></div>
        ) : (
          <>
            <div className="field">
              <label>What may change</label>
              <SegmentedControl
                aria-label="What may change"
                value={overwrite ? 'over' : 'fill'}
                onChange={(v) => void look(v === 'over')}
                options={[{ value: 'fill', label: 'Only fill blanks' }, { value: 'over', label: 'Overwrite' }]}
              />
              <div className="hint">
                {overwrite
                  ? 'Replaces categories, budgets, payee names and descriptions you set before.'
                  : 'Only sets what is empty (e.g. no category yet) and adds tags and notes. Nothing you chose is changed.'}
              </div>
            </div>
            {!preview ? (
              <Skeleton variant="block" height={60} />
            ) : (
              <div style={{ fontSize: 13.5 }}>
                The rule matches <b>{preview.matched}</b> past transaction{preview.matched === 1 ? '' : 's'}; <b>{preview.would_change}</b> would change.
                {preview.items.filter((x) => x.changes.length).slice(0, 6).map(({ transaction: t, changes }) => (
                  <div key={t.id} className="muted" style={{ fontSize: 12.5, marginTop: 4 }}>
                    {fmtDate(t.date)} · {t.description} → {changes.join(', ')}
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
      <div className="drawer-foot">
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>{done ? 'Close' : 'Not now'}</Button>
        {!done && (
          <Button variant="primary" onClick={apply} disabled={busy || !preview || preview.would_change === 0}>
            {busy ? 'Applying…' : preview ? `Change ${preview.would_change}` : 'Apply'}
          </Button>
        )}
      </div>
    </>
  );
}
