'use client';
import { useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { api, ApiError } from '../lib/api';
import { useApi, useShell } from '../contexts/ShellCtx';
import type { Account, BudgetMonth, CardFigures, Category, StatementDetail, StatementRow, StatementRowStatus } from '../lib/types';
import { fmtDate, paiseToInput, rs, toPaise } from '../lib/format';
import { Button } from '../primitives/Button';
import { Money } from '../primitives/Money';
import { Skeleton } from '../primitives/Skeleton';
import { ErrorState } from '../primitives/ErrorState';
import { EmptyState } from '../primitives/EmptyState';
import { Icon } from '../primitives/Icon';
import { Dialog, useDialogClose } from '../primitives/Dialog';
import { DrawerHead } from '../shared/DrawerHead';
import { useTxn } from '../contexts/TxnCtx';
import type { Txn } from '../lib/types';
import { CategoryOptions, kindFor } from '../shared/CategoryOptions';
import { BackToSetup } from '../shared/BackToSetup';
import { PageHelp } from '../shared/PageHelp';

type Filter = 'all' | 'needs' | 'ready' | 'duplicate' | 'skipped' | 'imported';
const FILTERS: { id: Filter; label: string; match: (s: StatementRowStatus) => boolean }[] = [
  { id: 'all', label: 'All', match: () => true },
  { id: 'needs', label: 'Needs you', match: (s) => s === 'needs_category' || s === 'needs_account' },
  { id: 'ready', label: 'Ready', match: (s) => s === 'ready' || s === 'link' },
  { id: 'duplicate', label: 'Already in MoneyMap', match: (s) => s === 'duplicate' },
  { id: 'skipped', label: 'Skipped', match: (s) => s === 'skipped' },
  { id: 'imported', label: 'Imported', match: (s) => s === 'imported' },
];

const STATUS_BADGE: Record<StatementRowStatus, [string, string]> = {
  ready: ['mint', 'Ready'],
  link: ['mint', 'Ready · links'],
  needs_category: ['cau', 'Needs category'],
  needs_account: ['cau', 'Needs account'],
  duplicate: ['neutral', 'Already in MoneyMap'],
  skipped: ['neutral', 'Skipped'],
  imported: ['brand', 'Imported'],
};

export function StatementReviewPage({ id }: { id: number }) {
  const router = useRouter();
  const existing = useSearchParams().get('existing');
  const { bump } = useShell();
  const { data, error, reload } = useApi<StatementDetail>(`/statements/${id}`);
  const accounts = useApi<Account[]>('/accounts?type=asset&type=cash&type=credit_card&type=emi_plan&type=investment&include_inactive=false');
  const categories = useApi<Category[]>('/categories');
  const budgets = useApi<BudgetMonth>('/budgets');
  const [st, setSt] = useState<StatementDetail | null>(null);
  const [filter, setFilter] = useState<Filter>('all');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string; link?: boolean } | null>(null);
  const [editing, setEditing] = useState<StatementRow | null>(null);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [pdfPassword, setPdfPassword] = useState('');
  const [rememberPw, setRememberPw] = useState(false);
  const [showReread, setShowReread] = useState(false);

  const rereadPdf = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const fresh = await api<StatementDetail>(`/statements/${id}/reread-pdf`, {
        method: 'POST',
        body: { password: pdfPassword || null, remember_password: rememberPw },
      });
      setSt(fresh);
      setPdfPassword('');
      setShowReread(false);
      setMsg({ ok: true, text: `Read the PDF again: ${fresh.rows.length} row${fresh.rows.length === 1 ? '' : 's'} found.` });
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  // Local copy of the statement so row edits show at once; replaced whenever it's loaded again.
  const [seenData, setSeenData] = useState<StatementDetail | null>(null);
  if (data !== seenData) {
    setSeenData(data);
    if (data) setSt(data);
  }

  const counts = useMemo(() => {
    const c: Record<StatementRowStatus, number> = { ready: 0, link: 0, needs_category: 0, needs_account: 0, duplicate: 0, skipped: 0, imported: 0 };
    for (const r of st?.rows ?? []) c[r.status] += 1;
    return c;
  }, [st]);
  const needs = counts.needs_category + counts.needs_account;
  const toImport = counts.ready + counts.link;
  const rows = (st?.rows ?? []).filter((r) => FILTERS.find((f) => f.id === filter)!.match(r.status));
  const all = accounts.data ?? [];
  const own = all.filter((a) => a.type !== 'emi_plan' && a.type !== 'investment'); // a statement belongs to a bank, cash or card account
  const otherAccounts = all.filter((a) => a.id !== st?.account_id && (a.type !== 'emi_plan' || own.find((o) => o.id === st?.account_id)?.type === 'credit_card'));
  const draft = st?.status === 'draft' || (st && toImport > 0);

  // Rows with the same payee and type that you haven't set yourself (mirrors the API's _similar)
  const payeeKey = (p: string) => p.toLowerCase().replace(/[^a-z0-9@.]+/g, ' ').trim();
  const similarCount = (row: StatementRow) => {
    const decided = row.kind === 'transfer' ? row.transfer_account_id !== null : row.category_id !== null || row.leave_uncategorised;
    if (!decided || row.transaction_id || !row.include || !payeeKey(row.payee)) return 0;
    return (st?.rows ?? []).filter(
      (o) =>
        o.id !== row.id &&
        !o.transaction_id &&
        o.include &&
        !o.user_set &&
        o.kind === row.kind &&
        payeeKey(o.payee) === payeeKey(row.payee) &&
        (row.kind === 'transfer'
          ? o.transfer_account_id !== row.transfer_account_id
          : o.category_id !== row.category_id || o.leave_uncategorised !== row.leave_uncategorised),
    ).length;
  };
  const applySimilar = async (row: StatementRow) => {
    setMsg(null);
    try {
      const n = similarCount(row);
      setSt(await api<StatementDetail>(`/statements/${id}/rows/${row.id}/apply-similar`, { method: 'POST' }));
      setMsg({ ok: true, text: `Applied to ${n} more “${row.payee}” row${n === 1 ? '' : 's'}.` });
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    }
  };

  const patchRow = async (row: StatementRow, body: Partial<StatementRow>) => {
    setMsg(null);
    try {
      const updated = await api<StatementRow>(`/statements/${id}/rows/${row.id}`, { method: 'PATCH', body });
      setSt((s) => (s ? { ...s, rows: s.rows.map((r) => (r.id === row.id ? { ...r, ...updated, duplicate: r.duplicate, link: updated.link_txn_id ? r.link : null } : r)) } : s));
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    }
  };

  const setAccount = async (accountId: string) => {
    setBusy(true);
    try {
      setSt(await api<StatementDetail>(`/statements/${id}`, { method: 'PATCH', body: { account_id: accountId ? Number(accountId) : null } }));
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const doImport = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const res = await api<{ imported: number; rules_created: number; statement: StatementDetail }>(`/statements/${id}/import`, { method: 'POST' });
      setSt(res.statement);
      setFilter('all');
      setMsg({
        ok: true,
        link: true,
        text: `Imported ${res.imported} transaction${res.imported === 1 ? '' : 's'}${res.rules_created ? ` and made ${res.rules_created} rule${res.rules_created === 1 ? '' : 's'} for next time` : ''}.`,
      });
      bump();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
      if (e instanceof ApiError && e.code === 'unresolved') setFilter('needs');
    } finally {
      setBusy(false);
    }
  };

  const reread = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const fresh = await api<StatementDetail>(`/statements/${id}/reparse`, { method: 'POST' });
      setSt(fresh);
      setMsg({ ok: true, text: `Read the statement again: ${fresh.rows.length} row${fresh.rows.length === 1 ? '' : 's'} found.` });
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const discard = async () => {
    if (!confirmDiscard) return setConfirmDiscard(true);
    await api(`/statements/${id}`, { method: 'DELETE' });
    bump();
    router.push('/statements');
  };

  if (error) return <div className="content-wrap"><div className="card"><ErrorState message={error} onRetry={reload} /></div></div>;
  if (!st) return <div className="content-wrap"><Skeleton variant="block" height={80} /><div style={{ height: 16 }} /><Skeleton variant="row" count={8} /></div>;

  const importDisabledReason = !st.account_id
    ? 'Choose the account first'
    : needs > 0
      ? `${needs} row${needs === 1 ? '' : 's'} still need you`
      : toImport === 0
        ? 'Nothing left to import'
        : null;

  return (
    <div className="content-wrap fade-in" style={{ maxWidth: 1180 }}>
      <BackToSetup step="statements" />
      <div className="page-head">
        <div style={{ minWidth: 0 }}>
          <h1>Review statement <PageHelp id="statement-review" /></h1>
          <p>
            {st.filename} · {st.doc_type === 'card_statement' ? 'Credit card statement' : 'Bank statement'}
            {st.account_last4 && <> · ending {st.account_last4}</>}
            {st.gmail_message_id && <> · <Link href={`/inbox?open=${encodeURIComponent(st.gmail_message_id)}`}>source email</Link></>}
            {st.upload_path && <> · uploaded</>}
          </p>
        </div>
        <div className="actions">
          {st.status === 'draft' && (
            <Button variant="ghost" icon="refresh-cw" onClick={reread} disabled={busy} title="Read the saved statement text again — no password needed">
              Re-read
            </Button>
          )}
          {st.status === 'draft' && st.rows.length > 0 && (
            <Button variant="ghost" icon="file-search" onClick={() => setShowReread((v) => !v)} title="Extract the PDF's text again (needs the PDF password)">
              Read PDF again
            </Button>
          )}
          {st.status === 'draft' && (
            <Button variant={confirmDiscard ? 'primary' : 'ghost'} className={confirmDiscard ? 'btn-danger' : ''} icon="trash-2" onClick={discard}>
              {confirmDiscard ? 'Confirm discard' : 'Discard'}
            </Button>
          )}
          {draft && (
            <Button variant="primary" icon="download" onClick={doImport} disabled={busy || importDisabledReason !== null} title={importDisabledReason ?? undefined}>
              {busy ? 'Working…' : `Import ${toImport} transaction${toImport === 1 ? '' : 's'}`}
            </Button>
          )}
        </div>
      </div>

      {msg && (
        <div className={msg.ok ? 'note privacy' : 'form-error'} role="status" style={{ marginBottom: 14 }}>
          {msg.ok && <Icon name="check" size={15} />} {msg.text}
          {msg.link && <> <Link href="/transactions"><b>View transactions</b></Link></>}
        </div>
      )}

      {existing && (
        <div className="note info" role="status" style={{ marginBottom: 14 }}>
          <Icon name="info" size={15} />
          <span>
            {existing === 'email'
              ? 'This is the same PDF that was fetched from Gmail, so it opened as that email’s statement — no second copy was made.'
              : 'You’d already opened this exact PDF, so here is that statement — nothing new was added.'}
          </span>
        </div>
      )}

      {st.overlaps.length > 0 && (
        <div className="note warn" role="status" style={{ marginBottom: 14, flexDirection: 'column', alignItems: 'stretch', gap: 6 }}>
          <div style={{ display: 'flex', gap: 11 }}>
            <Icon name="copy" size={15} />
            <b>Looks like the same statement is already here</b>
          </div>
          {st.overlaps.map((o) => (
            <span key={o.id}>
              <Link href={`/statements/${o.id}`}><b>{o.filename}</b></Link> ({o.source === 'email' ? 'from email' : 'uploaded'},{' '}
              {o.status === 'imported' ? 'already imported' : 'draft'}) has {o.shared_rows} of the same transactions.
            </span>
          ))}
          <span className="muted" style={{ fontSize: 12.5 }}>
            {st.overlaps.some((o) => o.status === 'imported')
              ? 'Rows already imported from it show as possible duplicates below — skip those, or discard this copy.'
              : 'Import only one of them and discard the other, otherwise every transaction is added twice.'}
          </span>
        </div>
      )}

      <div className="card card-pad" style={{ marginBottom: 14, display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
        <label htmlFor="st-acct" style={{ fontWeight: 600, fontSize: 14 }}>Statement account</label>
        <select id="st-acct" className="inp" style={{ width: 'auto', minWidth: 220 }} value={st.account_id ?? ''} onChange={(e) => setAccount(e.target.value)} disabled={busy || st.status === 'imported'}>
          <option value="">Choose an account…</option>
          {own.filter((a) => a.type !== 'credit_card').map((a) => <option key={a.id} value={a.id}>{a.name}{a.account_number ? ` (${a.account_number})` : ''}</option>)}
          {own.some((a) => a.type === 'credit_card') && (
            <optgroup label="Credit cards">
              {own.filter((a) => a.type === 'credit_card').map((a) => <option key={a.id} value={a.id}>{a.name}{a.account_number ? ` (··${a.account_number})` : ''}</option>)}
            </optgroup>
          )}
        </select>
        <span className="muted" style={{ fontSize: 12.5 }}>
          {st.account_id
            ? st.account_suggested
              ? `Picked automatically: the account number ends in ${st.account_last4}.`
              : 'Duplicates are checked against this account.'
            : st.account_last4
              ? `No account's number ends in ${st.account_last4} — choose one (or add the number to the account so it's picked next time).`
              : 'Choose which of your accounts this statement is for.'}
        </span>
      </div>

      {st.figures && <FiguresPanel f={st.figures} cardId={st.account_id} onCardUpdated={reload} />}

      {(st.rows.length === 0 || showReread) && st.status === 'draft' && (
        <div className="note warn" style={{ marginBottom: 14, flexDirection: 'column', alignItems: 'stretch', gap: 10 }}>
          <div style={{ display: 'flex', gap: 11 }}>
            <Icon name="triangle-alert" size={15} />
            <span>
              {st.rows.length === 0
                ? <>No transaction rows were found in the saved text. If this statement was opened with an earlier version of MoneyMap, read the PDF again — MoneyMap now tries several ways of extracting the text and keeps the one whose balances add up.</>
                : <>Read the PDF again with the latest reader. Rows you&apos;ve already imported are kept; the others are rebuilt.</>}
            </span>
          </div>
          <form
            style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}
            onSubmit={(e) => {
              e.preventDefault();
              rereadPdf();
            }}
          >
            <input type="password" className="inp" style={{ width: 220, padding: '6px 10px', fontSize: 13 }} placeholder="PDF password" aria-label="PDF password" autoComplete="off" value={pdfPassword} onChange={(e) => setPdfPassword(e.target.value)} />
            <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 12.5 }}>
              <input type="checkbox" checked={rememberPw} onChange={(e) => setRememberPw(e.target.checked)} /> Remember for this sender
            </label>
            <Button variant="primary" size="sm" type="submit" icon="file-search" disabled={busy}>Read PDF again</Button>
          </form>
        </div>
      )}

      <div className="chips" style={{ marginBottom: 12 }} role="radiogroup" aria-label="Filter rows">
        {FILTERS.map((f) => {
          const n = (st.rows ?? []).filter((r) => f.match(r.status)).length;
          if (f.id !== 'all' && n === 0) return null;
          return (
            <button key={f.id} type="button" role="radio" aria-checked={filter === f.id} className={`chip ${filter === f.id ? 'on' : ''}`} onClick={() => setFilter(f.id)}>
              {f.label} <span className="n" style={{ marginLeft: 4, opacity: 0.8 }}>{n}</span>
            </button>
          );
        })}
      </div>

      <div className="card">
        {rows.length === 0 ? (
          <EmptyState icon="check" title={filter === 'needs' ? 'Nothing needs you' : 'No rows here'} />
        ) : (
          <div className="tbl-wrap" style={{ padding: '12px 6px 6px' }}>
            <table className="tbl st-tbl">
              <thead>
                <tr>
                  <th style={{ width: 34 }} aria-label="Include" />
                  <th>Date</th>
                  <th>Payee &amp; description</th>
                  <th className="r">Amount</th>
                  <th>Type</th>
                  <th>Category / account</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <Row
                    key={r.id}
                    r={r}
                    categories={categories.data ?? []}
                    otherAccounts={otherAccounts}
                    allAccounts={all}
                    onPatch={(b) => patchRow(r, b)}
                    onEdit={() => setEditing(r)}
                    similar={similarCount(r)}
                    onApplySimilar={() => applySimilar(r)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {st.unparsed.length > 0 && (
        <details style={{ marginTop: 14 }}>
          <summary className="muted" style={{ cursor: 'pointer', fontSize: 13 }}>
            Lines MoneyMap didn&apos;t read as transactions ({st.unparsed.length}) — balances, headers, summaries. Check here if a transaction is missing.
          </summary>
          <div className="imp-log" style={{ height: 'auto', maxHeight: 260, marginTop: 8 }}>
            {st.unparsed.map((u, i) => <div key={i} className="dim" style={{ color: 'rgba(255,255,255,0.75)' }}>{u}</div>)}
          </div>
        </details>
      )}

      {editing && (
        <RowEditor
          row={editing}
          budgets={(budgets.data?.budgets ?? []).filter((b) => b.active)}
          onSave={async (b) => {
            await patchRow(editing, b);
          }}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}

/** Card statement: the bank's summary box and whether the rows add up to it. */
function FiguresPanel({ f, cardId, onCardUpdated }: { f: CardFigures; cardId: number | null; onCardUpdated: () => void }) {
  const { bump } = useShell();
  const [fixing, setFixing] = useState(false);
  const [fixError, setFixError] = useState<string | null>(null);
  const mismatch = cardId !== null && (f.suggest_statement_day !== null || f.suggest_due_days !== null);
  const fixCard = async () => {
    setFixing(true);
    setFixError(null);
    const body: Record<string, number> = {};
    if (f.suggest_statement_day !== null) body.statement_day = f.suggest_statement_day;
    if (f.suggest_due_days !== null) body.due_value = f.suggest_due_days;
    try {
      await api(`/cards/${cardId}`, { method: 'PATCH', body });
      bump();
      onCardUpdated();
    } catch (e) {
      setFixError((e as Error).message);
    }
    setFixing(false);
  };
  const item = (label: string, value: React.ReactNode) => (
    <div style={{ minWidth: 110 }}>
      <div className="muted" style={{ fontSize: 11.5, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</div>
      <div className="fig" style={{ fontSize: 15 }}>{value}</div>
    </div>
  );
  const money = (v: number | null) => (v === null ? <span className="muted">—</span> : <Money amount={rs(v)} interactive={false} />);
  const found = f.total_due !== null || f.due_date !== null || f.statement_date !== null;
  return (
    <div className="card card-pad" style={{ marginBottom: 14, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ fontWeight: 650 }}>Card statement summary</div>
      {found ? (
        <div style={{ display: 'flex', gap: 22, flexWrap: 'wrap' }}>
          {item('Statement date', f.statement_date ? fmtDate(f.statement_date) : '—')}
          {item('Due date', f.due_date ? fmtDate(f.due_date) : '—')}
          {item('Previous balance', money(f.previous_balance))}
          {item('Total due', money(f.total_due))}
          {item('Minimum due', money(f.min_due))}
        </div>
      ) : (
        <div className="muted" style={{ fontSize: 13 }}>The summary box (total due, due date) couldn’t be read from this PDF — the rows can still be imported.</div>
      )}
      {f.adds_up === true && (
        <div className="note privacy">
          <Icon name="circle-check" size={15} />
          <span>
            Adds up: previous balance + purchases <Money amount={rs(f.debits)} interactive={false} /> − payments and refunds{' '}
            <Money amount={rs(f.credits)} interactive={false} /> = total due. Every row was read.
          </span>
        </div>
      )}
      {f.adds_up === false && f.difference !== null && (
        <div className="note warn">
          <Icon name="triangle-alert" size={15} />
          <span>
            Doesn’t add up: the rows give <Money amount={rs(f.expected_total ?? 0)} interactive={false} /> but the statement says{' '}
            <Money amount={rs(f.total_due ?? 0)} interactive={false} /> (a difference of{' '}
            <Money amount={rs(Math.abs(f.difference))} interactive={false} />). A row may have been missed or misread — check
            the rows against the PDF before importing.
          </span>
        </div>
      )}
      {mismatch && (
        <div className="note warn" style={{ alignItems: 'center' }}>
          <Icon name="calendar-clock" size={15} />
          <span style={{ flex: 1 }}>
            {f.suggest_statement_day !== null && (
              <>This statement is dated the <b>{f.suggest_statement_day}</b>, but the card is set to statement day {f.card_statement_day}. </>
            )}
            {f.suggest_due_days !== null && (
              <>Payment is due <b>{f.suggest_due_days} days</b> after the statement, but the card is set to {f.card_due_value} days. </>
            )}
            Update the card so its statement and due dates match the bank&apos;s.
            {fixError && <span style={{ color: 'var(--red-600)' }}> {fixError}</span>}
          </span>
          <Button variant="secondary" size="sm" onClick={fixCard} disabled={fixing}>{fixing ? 'Updating…' : 'Update card'}</Button>
        </div>
      )}
      {f.total_due !== null && (
        <div className="muted" style={{ fontSize: 12 }}>
          After import, the card&apos;s statement for this cycle uses these figures instead of the worked-out ones.
        </div>
      )}
    </div>
  );
}

function Row({
  r,
  categories,
  otherAccounts,
  allAccounts,
  onPatch,
  onEdit,
  similar,
  onApplySimilar,
}: {
  r: StatementRow;
  categories: Category[];
  otherAccounts: Account[];
  allAccounts: Account[];
  onPatch: (b: Partial<StatementRow>) => void;
  onEdit: () => void;
  similar: number;
  onApplySimilar: () => void;
}) {
  const locked = r.status === 'imported';
  const [cls, label] = STATUS_BADGE[r.status];
  const needs = r.status === 'needs_category' || r.status === 'needs_account';

  const catValue = r.leave_uncategorised ? '__none' : r.category_id ?? '';
  const { openTxn } = useTxn();
  const openImported = async () => {
    if (r.transaction_id) openTxn(await api<Txn>(`/transactions/${r.transaction_id}`));
  };
  const kindLabel = { expense: 'Expense', income: 'Income', transfer: 'Transfer' }[r.kind];
  const targetLabel =
    r.kind === 'transfer'
      ? allAccounts.find((a) => a.id === r.transfer_account_id)?.name ?? '—'
      : r.leave_uncategorised
        ? 'Uncategorised'
        : categories.find((c) => c.id === r.category_id)?.name ?? '—';

  return (
    <tr className={needs ? 'st-needs' : ''} style={{ opacity: r.include || locked ? 1 : 0.55 }}>
      <td>
        <input
          type="checkbox"
          aria-label={`Include ${r.payee}`}
          checked={r.include}
          disabled={locked}
          onChange={(e) => onPatch({ include: e.target.checked })}
        />
      </td>
      <td className="t-mono" style={{ whiteSpace: 'nowrap' }}>{fmtDate(r.date)}</td>
      <td style={{ minWidth: 180, maxWidth: 320 }}>
        <button type="button" className="rowbtn" onClick={onEdit} disabled={locked} title={locked ? undefined : 'Edit details'}>
          <div style={{ fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6 }}>
            {r.payee} {!locked && <Icon name="pencil" size={12} color="var(--fg-3)" />}
          </div>
          <div className="muted" style={{ fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={r.raw}>{r.description}</div>
        </button>
        {r.duplicate && r.status === 'duplicate' && (
          <div className="muted" style={{ fontSize: 11.5, marginTop: 3 }}>
            Matches “{r.duplicate.description}” on {fmtDate(r.duplicate.date)}
          </div>
        )}
        {r.link && r.status === 'link' && (
          <div style={{ fontSize: 11.5, marginTop: 3, color: 'var(--indigo-700)' }}>
            Already saved as an expense “{r.link.description}” on {fmtDate(r.link.date)} — importing turns it into this
            transfer instead of adding it twice.{' '}
            <button type="button" className="link-btn" onClick={() => onPatch({ link_txn_id: null })} style={{ fontSize: 11.5 }}>
              Import as a new transfer instead
            </button>
          </div>
        )}
        {r.flag === 'emi' && !locked && (
          <div style={{ fontSize: 11.5, marginTop: 3 }}>
            <span className="badge cau">EMI?</span>{' '}
            <span className="muted">An EMI row with no EMI to match — add the EMI on the card&apos;s page, then Re-read; or untick to skip.</span>
          </div>
        )}
        {r.loan_id && !locked && (
          <div style={{ fontSize: 11.5, marginTop: 3 }}>
            <span className="badge coral">{r.loan_action === 'emi' ? 'Loan EMI' : 'Part-payment?'}</span>{' '}
            <span className="muted">{r.suggestion}</span>{' '}
            <button type="button" className="link-btn" style={{ fontSize: 11.5 }} onClick={() => onPatch({ loan_id: null })}>
              Not this loan
            </button>
          </div>
        )}
        {r.emi_id && r.suggestion_kind === 'emi' && !locked && (
          <div style={{ fontSize: 11.5, marginTop: 3 }}>
            <span className="badge brand">EMI</span> <span className="muted">{r.suggestion} — paying back the EMI, not new spending.</span>
          </div>
        )}
      </td>
      <td className="r figure" style={{ whiteSpace: 'nowrap' }}>
        {r.amount > 0 ? '+' : '−'}
        <Money amount={rs(Math.abs(r.amount))} pos={r.amount > 0} precise interactive={false} />
      </td>
      <td>
        {locked ? <span style={{ fontSize: 13 }}>{kindLabel}</span> : (
        <select
          className="inp st-sel"
          aria-label="Type"
          value={r.kind}
          disabled={locked}
          onChange={(e) => onPatch({ kind: e.target.value as StatementRow['kind'] })}
        >
          {r.amount < 0 ? <option value="expense">Expense</option> : <option value="income">Income</option>}
          <option value="transfer">Transfer</option>
        </select>
        )}
      </td>
      <td style={{ minWidth: 170 }}>
        {locked ? (
          <span style={{ fontSize: 13 }}>{r.kind === 'transfer' ? `${r.amount < 0 ? 'To' : 'From'} ${targetLabel}` : targetLabel}</span>
        ) : r.kind === 'transfer' ? (
          <select
            className="inp st-sel"
            aria-label={r.amount < 0 ? 'Transfer to account' : 'Transfer from account'}
            value={r.transfer_account_id ?? ''}
            disabled={locked}
            onChange={(e) => onPatch({ transfer_account_id: e.target.value ? Number(e.target.value) : null })}
          >
            <option value="">{r.amount < 0 ? 'To which account?' : 'From which account?'}</option>
            {otherAccounts.map((a) => <option key={a.id} value={a.id}>{a.name}{a.type === 'credit_card' ? ' (card)' : a.type === 'investment' ? ' (investment)' : ''}</option>)}
          </select>
        ) : (
          <select
            className="inp st-sel"
            aria-label="Category"
            value={catValue}
            disabled={locked}
            onChange={(e) =>
              e.target.value === '__none'
                ? onPatch({ leave_uncategorised: true })
                : onPatch({ category_id: e.target.value ? Number(e.target.value) : null, leave_uncategorised: false })
            }
          >
            <option value="">Choose a category…</option>
            <CategoryOptions categories={categories} kind={kindFor(r.kind)} keep={r.category_id} markEssential />
            <option value="__none">— Leave uncategorised —</option>
          </select>
        )}
        {!locked && r.user_set && r.kind !== 'transfer' && r.category_id !== null && r.suggestion_kind !== 'rule' && (
          <div className="rule-next">
            <label>
              <input type="checkbox" checked={!!r.create_rule} onChange={(e) => onPatch({ create_rule: e.target.checked })} />
              Rule for next time
            </label>
            {r.create_rule && (
              <span>
                payee contains{' '}
                <input
                  className="inp"
                  key={r.rule_keyword ?? r.payee}
                  defaultValue={r.rule_keyword ?? r.payee}
                  aria-label="Rule word"
                  onBlur={(e) => e.target.value.trim() && e.target.value.trim() !== r.rule_keyword && onPatch({ rule_keyword: e.target.value.trim() })}
                />
              </span>
            )}
          </div>
        )}
        {!locked && similar > 0 && (
          <div style={{ marginTop: 6 }}>
            <Button
              variant="secondary"
              size="sm"
              icon="copy-check"
              onClick={onApplySimilar}
              title={`Use the same ${r.kind === 'transfer' ? 'account' : 'category'} on the other rows with this payee that you haven't set yourself`}
            >
              Apply to {similar} more “{r.payee}” row{similar === 1 ? '' : 's'}
            </Button>
          </div>
        )}
      </td>
      <td style={{ minWidth: 120 }}>
        {locked ? (
          <button type="button" className="badge brand" style={{ border: 0, cursor: 'pointer' }} onClick={openImported} title="Open the transaction">
            Imported <Icon name="arrow-up-right" size={11} />
          </button>
        ) : (
          <span className={`badge ${cls}`}>{label}</span>
        )}
        {r.suggestion && r.status !== 'imported' && (
          <div className="muted" style={{ fontSize: 11.5, marginTop: 3, display: 'flex', alignItems: 'center', gap: 4 }}>
            <Icon name={r.suggestion_kind === 'rule' ? 'zap' : 'history'} size={11} /> {r.suggestion}
          </div>
        )}
      </td>
    </tr>
  );
}

function RowEditor({
  row,
  budgets,
  onSave,
  onClose,
}: {
  row: StatementRow;
  budgets: { id: number; name: string }[];
  onSave: (b: Partial<StatementRow>) => Promise<void>;
  onClose: () => void;
}) {
  return (
    <Dialog onClose={onClose} label="Edit statement row" width={500}>
      <RowEditorBody row={row} budgets={budgets} onSave={onSave} />
    </Dialog>
  );
}

function RowEditorBody({ row, budgets, onSave }: { row: StatementRow; budgets: { id: number; name: string }[]; onSave: (b: Partial<StatementRow>) => Promise<void> }) {
  const close = useDialogClose();
  const [payee, setPayee] = useState(row.payee);
  const [description, setDescription] = useState(row.description);
  const [date, setDate] = useState(row.date);
  const [amount, setAmount] = useState(paiseToInput(Math.abs(row.amount)));
  const [direction, setDirection] = useState(row.amount < 0 ? 'out' : 'in');
  const [budgetId, setBudgetId] = useState(row.budget_id ? String(row.budget_id) : '');
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    const p = toPaise(amount);
    if (p === null || p <= 0) return setError('Enter an amount greater than zero');
    const signed = direction === 'out' ? -p : p;
    const body: Partial<StatementRow> = { payee, description, date, budget_id: budgetId ? Number(budgetId) : null };
    if (signed !== row.amount) body.amount = signed;
    await onSave(body);
    close();
  };

  return (
    <>
      <DrawerHead title="Edit row" sub="Fix anything the statement reader got wrong" />
      <div className="drawer-body">
        {error && <div className="form-error">{error}</div>}
        <div className="field">
          <label>Original statement line</label>
          <div className="t-mono" style={{ fontSize: 12, background: 'var(--bg-subtle)', padding: '9px 11px', borderRadius: 'var(--radius-sm)', wordBreak: 'break-word' }}>{row.raw}</div>
        </div>
        <div className="field">
          <label htmlFor="sr-payee">Payee</label>
          <input id="sr-payee" className="inp" value={payee} onChange={(e) => setPayee(e.target.value)} maxLength={120} />
          <div className="hint">MoneyMap remembers the category you pick for this payee and suggests it next time.</div>
        </div>
        <div className="field">
          <label htmlFor="sr-desc">Description</label>
          <input id="sr-desc" className="inp" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={255} />
        </div>
        <div className="row3">
          <div className="field">
            <label htmlFor="sr-date">Date</label>
            <input id="sr-date" type="date" className="inp" value={date} onChange={(e) => setDate(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="sr-amt">Amount (₹)</label>
            <input id="sr-amt" className="inp" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="sr-dir">Direction</label>
            <select id="sr-dir" className="inp" value={direction} onChange={(e) => setDirection(e.target.value)}>
              <option value="out">Money out</option>
              <option value="in">Money in</option>
            </select>
          </div>
        </div>
        {row.kind === 'expense' && direction === 'out' && (
          <div className="field">
            <label htmlFor="sr-bud">Budget</label>
            <select id="sr-bud" className="inp" value={budgetId} onChange={(e) => setBudgetId(e.target.value)}>
              <option value="">No budget</option>
              {budgets.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
          </div>
        )}
      </div>
      <div className="drawer-foot">
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        <Button variant="primary" onClick={save}>Save</Button>
      </div>
    </>
  );
}
