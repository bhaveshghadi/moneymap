'use client';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { api, ApiError, qs, replaceQuery } from '../lib/api';
import { useApi, useShell } from '../contexts/ShellCtx';
import { useTxn } from '../contexts/TxnCtx';
import type { Account, GmailProvider, GmailRun, GmailStatus, InboxDetail, InboxItem, InboxPage as InboxPageT } from '../lib/types';
import { fmtDate, rs, todayIso } from '../lib/format';
import { Button } from '../primitives/Button';
import { Money } from '../primitives/Money';
import { Tabs } from '../primitives/Tabs';
import { Skeleton } from '../primitives/Skeleton';
import { EmptyState } from '../primitives/EmptyState';
import { ErrorState } from '../primitives/ErrorState';
import { Icon } from '../primitives/Icon';
import { Dialog, useDialogClose } from '../primitives/Dialog';
import { DrawerHead } from '../shared/DrawerHead';
import { TxnRow } from '../shared/TxnRow';
import type { TxnDefaults } from '../shared/TxnForm';

type Status = 'new' | 'handled' | 'ignored';
const PAGE = 50;
// v2: statements first; alert templates are optional and never remembered as pre-selected.
const SEL_KEY = 'moneymap.gmailTemplates.v2';
const CUSTOM_KEY = 'moneymap.gmailCustom';

/** "HDFC Bank <alerts@hdfcbank.net>" -> "HDFC Bank" (or the domain). */
export function senderName(from: string | null): string {
  if (!from) return 'Unknown sender';
  const m = /^\s*"?([^"<]+?)"?\s*<([^>]+)>/.exec(from);
  if (m) return m[1].trim();
  const at = from.split('@')[1];
  return at ? at.replace(/>$/, '') : from;
}

function fmtWhen(iso: string | null): string {
  if (!iso) return '';
  return new Date(iso).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
}

function fileSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function readLocal<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    return v ? (JSON.parse(v) as T) : fallback;
  } catch {
    return fallback;
  }
}
function writeLocal(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* convenience only */
  }
}

export function InboxPage() {
  const sp = useSearchParams();
  const pathname = usePathname();
  const gmail = useApi<GmailStatus>('/gmail/status');
  const [status, setStatus] = useState<Status>('new');
  const [q, setQ] = useState('');
  const [query, setQuery] = useState('');
  const [limit, setLimit] = useState(PAGE);
  const [openId, setOpenId] = useState<string | null>(null);
  const [fetching, setFetching] = useState(false);
  const page = useApi<InboxPageT>(`/inbox${qs({ status, q: query, limit })}`);

  // /inbox?open=<id> (from a transaction's "Source email") — opened once per URL.
  const search = sp.toString();
  const [seenSearch, setSeenSearch] = useState<string | null>(null);
  if (search !== seenSearch) {
    setSeenSearch(search);
    const id = sp.get('open');
    if (id) setOpenId(id);
  }
  useEffect(() => {
    if (sp.get('open')) replaceQuery(pathname, '');
  }, [sp, pathname]);

  useEffect(() => {
    const t = setTimeout(() => {
      setQuery(q.trim());
      setLimit(PAGE);
    }, 250);
    return () => clearTimeout(t);
  }, [q]);

  const data = page.data;
  const counts = data?.counts ?? { new: 0, handled: 0, ignored: 0 };
  const notReady = gmail.data && !gmail.data.connected;

  return (
    <div className="content-wrap fade-in">
      <div className="page-head">
        <div>
          <h1>Inbox</h1>
          <p>Statement emails fetched from Gmail (and alerts, if you choose them). Record transactions from them, or ignore them.</p>
        </div>
        <div className="actions">
          <Button variant="primary" icon="mail-search" onClick={() => setFetching(true)} disabled={!gmail.data?.connected}>
            Fetch from Gmail
          </Button>
        </div>
      </div>

      {notReady && (
        <div className="note info" style={{ marginBottom: 16 }}>
          <Icon name="info" size={15} />
          <span>
            Gmail isn&apos;t connected yet. <Link href="/settings"><b>Set it up in Settings</b></Link> — it takes a few minutes and access is read-only.
          </span>
        </div>
      )}

      <Tabs
        tabs={[
          { id: 'new', label: `To do (${counts.new})` },
          { id: 'handled', label: `Recorded (${counts.handled})` },
          { id: 'ignored', label: `Ignored (${counts.ignored})` },
        ]}
        active={status}
        onChange={(id) => {
          setStatus(id as Status);
          setLimit(PAGE);
        }}
        aria-label="Inbox status"
      />

      <div className="filters">
        <input className="inp grow" placeholder="Filter by sender, subject or text…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filter emails" />
      </div>

      <div className="card">
        <div className="card-list" style={{ paddingTop: 10 }}>
          {page.error ? (
            <ErrorState message={page.error} onRetry={page.reload} />
          ) : !data ? (
            <div className="stack" style={{ gap: 8, padding: '6px 0 10px' }}><Skeleton variant="row" count={5} /></div>
          ) : data.items.length === 0 ? (
            query ? (
              <EmptyState icon="search-x" title="No emails match" />
            ) : status === 'new' ? (
              <EmptyState
                icon="inbox"
                title={counts.handled + counts.ignored > 0 ? 'All caught up' : 'No emails yet'}
                body={gmail.data?.connected ? 'Fetch bank, card and loan statements from Gmail to see them here.' : 'Connect Gmail in Settings, then fetch emails.'}
                action={gmail.data?.connected ? { label: 'Fetch from Gmail', onClick: () => setFetching(true) } : { label: 'Open Settings', href: '/settings' }}
              />
            ) : (
              <EmptyState icon="inbox" title={status === 'handled' ? 'Nothing recorded yet' : 'Nothing ignored'} />
            )
          ) : (
            <>
              {data.items.map((m) => (
                <EmailRow key={m.id} m={m} onClick={() => setOpenId(m.id)} />
              ))}
              {data.items.length < data.total && (
                <div className="load-more">
                  <Button variant="secondary" size="sm" onClick={() => setLimit((l) => l + PAGE)} disabled={page.loading}>
                    {page.loading ? 'Loading…' : `Load more (${data.total - data.items.length} left)`}
                  </Button>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {openId && <EmailDrawer id={openId} onClose={() => setOpenId(null)} />}
      {fetching && gmail.data && (
        <FetchDrawer
          status={gmail.data}
          onClose={() => {
            setFetching(false);
            page.reload(); // a fetch may still be finishing in the background
            gmail.reload();
          }}
        />
      )}
    </div>
  );
}

function EmailRow({ m, onClick }: { m: InboxItem; onClick: () => void }) {
  return (
    <button type="button" className="txn click rowbtn" onClick={onClick}>
      <span className="ico" style={{ background: m.is_alert ? 'var(--indigo-50)' : 'var(--red-50)', color: m.is_alert ? 'var(--indigo-600)' : 'var(--red-500)' }}>
        <Icon name={m.is_alert ? 'bell-ring' : m.attachments.length ? 'file-text' : 'mail'} size={18} />
      </span>
      <div className="txn-mid">
        <div className="mer" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m.subject || '(no subject)'}</div>
        <div className="cat" style={{ flexWrap: 'nowrap', overflow: 'hidden' }}>
          <span style={{ fontWeight: 600, color: 'var(--fg-2)', flexShrink: 0 }}>{senderName(m.from_addr)}</span>
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>· {m.snippet}</span>
        </div>
      </div>
      <div style={{ textAlign: 'right', flexShrink: 0, marginLeft: 'auto', display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
        <span className="muted" style={{ fontSize: 12 }}>{fmtWhen(m.sent_at)}</span>
        <span style={{ display: 'flex', gap: 4 }}>
          {m.is_alert && m.transaction_count === 0 && <span className="badge brand">Alert</span>}
          {m.attachments.length > 0 && <span className="badge neutral"><Icon name="paperclip" size={11} /> {m.attachments.length}</span>}
          {m.transaction_count > 0 && <span className="badge mint">{m.transaction_count} recorded</span>}
        </span>
      </div>
    </button>
  );
}

// ---------------------------------------------------------------- email drawer

function EmailDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label="Email" width={600}>
      <EmailBody id={id} />
    </Dialog>
  );
}

function localDate(iso: string | null): string {
  if (!iso) return todayIso();
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function EmailBody({ id }: { id: string }) {
  const close = useDialogClose();
  const router = useRouter();
  const { bump } = useShell();
  const [importing, setImporting] = useState<number | null>(null); // attachment id
  const [needPassword, setNeedPassword] = useState(false);
  const [pdfPassword, setPdfPassword] = useState('');
  const [remember, setRemember] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);

  /** Read a statement PDF into a draft import and open its review page. */
  const startImport = async (attachmentId: number, password?: string) => {
    setImporting(attachmentId);
    setImportError(null);
    try {
      const st = await api<{ id: number }>('/statements', {
        method: 'POST',
        body: { attachment_id: attachmentId, password: password || null, remember_password: remember },
      });
      close();
      router.push(`/statements/${st.id}`);
    } catch (e) {
      const code = e instanceof ApiError ? e.code : undefined;
      if (code === 'cas' && e instanceof ApiError && e.detail?.cas_id) {
        close(); // a mutual fund statement: its review is in Investments
        router.push(`/investments/cas/${e.detail.cas_id}`);
        return;
      }
      if (code === 'password_required' || code === 'wrong_password') {
        setNeedPassword(true);
        if (code === 'wrong_password' || password) setImportError((e as Error).message);
      } else {
        setImportError((e as Error).message);
        setImporting(null);
      }
    }
  };
  const { newTxn, openTxn } = useTxn();
  const { data: m, error, reload } = useApi<InboxDetail>(`/inbox/${encodeURIComponent(id)}`);
  const accounts = useApi<Account[]>('/accounts?type=asset&type=cash&type=credit_card');
  const [busy, setBusy] = useState(false);

  const setStatus = async (status: 'new' | 'ignored') => {
    setBusy(true);
    try {
      await api(`/inbox/${encodeURIComponent(id)}`, { method: 'PATCH', body: { status } });
      bump();
      if (status === 'ignored') close();
      else reload();
    } finally {
      setBusy(false);
    }
  };

  /** Open the transaction form, pre-filled from the alert (if recognised) or the email. */
  const record = (useSuggestion: boolean) => {
    if (!m) return;
    const s = useSuggestion ? m.suggestion : null;
    let defaults: TxnDefaults;
    if (s) {
      const name = s.payee ?? s.merchant ?? senderName(m.from_addr);
      defaults = {
        type: s.type,
        date: s.date,
        amount: s.amount,
        description: (s.merchant ?? m.subject ?? '').slice(0, 255),
        ...(s.type === 'withdrawal'
          ? { source_id: s.account_id ?? undefined, destination_name: name }
          : { source_name: name, destination_id: s.account_id ?? undefined }),
        ...(s.category_id ? { category_id: s.category_id } : {}),
        gmail_message_id: m.id,
        gmail_subject: m.subject ?? '',
      };
    } else {
      defaults = {
        date: localDate(m.sent_at),
        description: (m.subject || '').slice(0, 255),
        destination_name: senderName(m.from_addr),
        gmail_message_id: m.id,
        gmail_subject: m.subject ?? '',
      };
    }
    close();
    // Wait for this drawer's exit animation before opening the form drawer.
    setTimeout(() => newTxn(defaults), 260);
  };

  if (error) return <><DrawerHead title="Email" /><div className="drawer-body"><ErrorState message={error} onRetry={reload} /></div></>;
  if (!m) return <><DrawerHead title="Loading…" /><div className="drawer-body"><Skeleton variant="block" height={260} /></div></>;

  const s = m.suggestion;
  const account = s?.account_id ? accounts.data?.find((a) => a.id === s.account_id) : undefined;

  return (
    <>
      <DrawerHead
        title={m.subject || '(no subject)'}
        sub={`${senderName(m.from_addr)} · ${fmtWhen(m.sent_at)}`}
        lead={<span className="ico" style={{ background: 'var(--red-50)', color: 'var(--red-500)' }}><Icon name="mail" size={20} /></span>}
      />
      <div className="drawer-body">
        {m.status === 'ignored' && <div className="note warn" style={{ marginBottom: 14 }}><Icon name="eye-off" size={15} /> You ignored this email.</div>}
        {s && m.transactions.length === 0 && (
          <div className="card card-pad" style={{ marginBottom: 16, borderColor: 'var(--indigo-200)' }}>
            <div className="sb-section" style={{ padding: '0 0 6px' }}>Transaction alert — read from this email</div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
              <span style={{ fontWeight: 600 }}>
                {s.type === 'withdrawal' ? 'Expense' : 'Income'} · {s.merchant ?? 'Unknown payee'}
              </span>
              <span className="fig" style={{ fontSize: 18 }}>
                <Money amount={rs(s.type === 'withdrawal' ? -s.amount : s.amount)} sign pos={s.type === 'deposit'} />
              </span>
            </div>
            <div className="muted" style={{ fontSize: 12.5, marginTop: 4 }}>
              {fmtDate(s.date)}
              {s.account_last4 && <> · account ending {s.account_last4}{account ? ` (${account.name})` : ' — no matching account; add the number to an account to match it'}</>}
            </div>
            <div style={{ marginTop: 12 }}>
              <Button variant="primary" size="sm" icon="check" onClick={() => record(true)}>Record this transaction</Button>
            </div>
            <div className="hint" style={{ marginTop: 8 }}>Opens the form filled in — check it before saving.</div>
          </div>
        )}
        {m.transactions.length > 0 && (
          <div className="card card-pad" style={{ marginBottom: 16, paddingTop: 12, paddingBottom: 8 }}>
            <div className="sb-section" style={{ padding: '0 0 4px' }}>Recorded as</div>
            {m.transactions.map((t) => (
              <TxnRow key={t.id} t={t} onClick={() => { close(); setTimeout(() => openTxn(t), 260); }} />
            ))}
          </div>
        )}
        <div className="doc">
          <div className="doc-bar">
            <Icon name="mail" size={15} color="var(--red-500)" />
            <span>Gmail</span>
            <span style={{ marginLeft: 'auto' }}>{m.sent_at ? new Date(m.sent_at).toLocaleString('en-IN') : ''}</span>
          </div>
          <div className="doc-meta">
            <div className="from">{m.from_addr}</div>
            <div className="subj">{m.subject}</div>
          </div>
          <div className="doc-body" style={{ whiteSpace: 'pre-wrap', maxHeight: 360, overflowY: 'auto', wordBreak: 'break-word' }}>
            {m.body_text || m.snippet || '(empty)'}
          </div>
        </div>
        {m.attachments.length > 0 && (
          <div className="stack" style={{ gap: 8, marginTop: 14 }}>
            {m.attachments.map((a) => (
              <div key={a.id} className="pdf">
                <div className="thumb"><Icon name="file-text" size={20} /></div>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: 13.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.filename}</div>
                  <div className="muted" style={{ fontSize: 12 }}>{a.mime_type ?? 'file'} · {fileSize(a.size)}</div>
                </div>
                <a className="btn btn-secondary btn-sm" style={{ textDecoration: 'none' }} href={`/api/inbox/${encodeURIComponent(m.id)}/attachments/${a.id}`} target="_blank" rel="noreferrer">
                  <Icon name="external-link" size={14} /> Open
                </a>
                <a className="btn btn-ghost btn-sm" style={{ textDecoration: 'none' }} href={`/api/inbox/${encodeURIComponent(m.id)}/attachments/${a.id}?download=true`} title="Download">
                  <Icon name="download" size={14} />
                </a>
                {(a.mime_type === 'application/pdf' || a.filename.toLowerCase().endsWith('.pdf')) && (
                  <Button variant="primary" size="sm" icon="file-input" onClick={() => startImport(a.id)} disabled={importing !== null && !needPassword}>
                    Import statement
                  </Button>
                )}
              </div>
            ))}
            {importing !== null && needPassword && (
              <form
                className="card card-pad"
                onSubmit={(e) => {
                  e.preventDefault();
                  startImport(importing, pdfPassword);
                }}
              >
                <div className="field" style={{ marginBottom: 10 }}>
                  <label htmlFor="pdf-pass">PDF password</label>
                  <input id="pdf-pass" type="password" className="inp" autoComplete="off" value={pdfPassword} onChange={(e) => setPdfPassword(e.target.value)} autoFocus required />
                  <div className="hint">Banks usually use your date of birth (DDMMYYYY), part of your PAN, or your customer ID — check the email text.</div>
                </div>
                <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13, marginBottom: 12 }}>
                  <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
                  Remember for statements from this sender <span className="muted">(stored encrypted on your server)</span>
                </label>
                {importError && <div className="form-error">{importError}</div>}
                <div style={{ display: 'flex', gap: 8 }}>
                  <Button variant="primary" type="submit">Unlock &amp; read</Button>
                  <Button variant="ghost" onClick={() => { setImporting(null); setNeedPassword(false); setImportError(null); }}>Cancel</Button>
                </div>
              </form>
            )}
            {importError && !needPassword && <div className="form-error">{importError}</div>}
            <div className="muted" style={{ fontSize: 12 }}>
              <b>Import statement</b> reads the PDF into rows you review before anything is added. Bank PDFs are often
              password-protected (usually a date of birth or part of your PAN).
            </div>
          </div>
        )}
        {m.matched_query && <div className="muted t-mono" style={{ fontSize: 11.5, marginTop: 14, wordBreak: 'break-all' }}>Matched: {m.matched_query}</div>}
      </div>
      <div className="drawer-foot">
        {m.status === 'ignored' ? (
          <Button variant="secondary" icon="undo-2" onClick={() => setStatus('new')} disabled={busy}>Restore</Button>
        ) : (
          <Button variant="ghost" icon="eye-off" onClick={() => setStatus('ignored')} disabled={busy}>Ignore</Button>
        )}
        <span className="spacer" />
        <Button variant={s && m.transactions.length === 0 ? 'secondary' : 'primary'} icon="plus" onClick={() => record(false)}>
          {m.transactions.length ? 'Record another' : s ? 'Record by hand' : 'Create transaction'}
        </Button>
      </div>
    </>
  );
}

// ---------------------------------------------------------------- fetch drawer

function FetchDrawer({ status, onClose }: { status: GmailStatus; onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label="Fetch from Gmail" width={560}>
      <FetchBody status={status} />
    </Dialog>
  );
}

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

const KIND_ORDER = ['bank_statement', 'credit_card_statement', 'loan_statement', 'mf_statement', 'transaction_alert'];

function FetchBody({ status }: { status: GmailStatus }) {
  const close = useDialogClose();
  const { bump } = useShell();
  const providers = useApi<GmailProvider[]>('/gmail/providers');
  const [from, setFrom] = useState(status.last_fetch_to ?? daysAgo(30));
  const [to, setTo] = useState(todayIso());
  const [selected, setSelected] = useState<string[]>(() => readLocal<string[]>(SEL_KEY, []));
  const [custom, setCustom] = useState<string>(() => readLocal<string>(CUSTOM_KEY, ''));
  const [run, setRun] = useState<GmailRun | null>(null);
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(
    () => () => {
      if (timer.current) clearInterval(timer.current);
    },
    [],
  );

  const toggle = (id: string) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  const doEstimate = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    const alertIds = new Set((providers.data ?? []).filter((p) => p.kind === 'transaction_alert').map((p) => p.id));
    writeLocal(SEL_KEY, selected.filter((id) => !alertIds.has(id)));
    writeLocal(CUSTOM_KEY, custom);
    try {
      setRun(
        await api<GmailRun>('/gmail/estimate', {
          method: 'POST',
          body: { template_ids: selected, custom: custom.split('\n'), date_from: from, date_to: to },
        }),
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const poll = (id: number) => {
    timer.current = setInterval(async () => {
      try {
        const r = await api<GmailRun>(`/gmail/runs/${id}`);
        setRun(r);
        if (!['running', 'cancelling'].includes(r.status)) {
          if (timer.current) clearInterval(timer.current);
          bump();
        }
      } catch {
        /* keep polling */
      }
    }, 1000);
  };

  const start = async () => {
    if (!run) return;
    setError(null);
    setBusy(true);
    try {
      const r = await api<GmailRun>(`/gmail/runs/${run.id}/start`, { method: 'POST', body: { consent } });
      setRun(r);
      if (['running', 'cancelling'].includes(r.status)) poll(r.id);
      else bump();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    if (run) setRun(await api<GmailRun>(`/gmail/runs/${run.id}/cancel`, { method: 'POST' }));
  };

  const groups = new Map<string, { label: string; list: GmailProvider[] }>();
  for (const p of [...(providers.data ?? [])].sort((a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind))) {
    if (!groups.has(p.kind)) groups.set(p.kind, { label: p.doc_type, list: [] });
    groups.get(p.kind)!.list.push(p);
  }
  const active = run && ['running', 'cancelling'].includes(run.status);
  const finished = run && ['done', 'cancelled', 'error'].includes(run.status);
  const pct = run && run.new_count ? Math.round((run.message_count / run.new_count) * 100) : 0;

  return (
    <>
      <DrawerHead title="Fetch from Gmail" sub={`Read-only · ${status.email ?? ''}`} lead={<span className="ico" style={{ background: 'var(--red-50)', color: 'var(--red-500)' }}><Icon name="mail-search" size={20} /></span>} />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}

        {!run && (
          <form id="gm-fetch" onSubmit={doEstimate}>
            <div className="row2">
              <div className="field">
                <label htmlFor="gm-from">Emails from</label>
                <input id="gm-from" type="date" className="inp" value={from} onChange={(e) => setFrom(e.target.value)} required />
              </div>
              <div className="field">
                <label htmlFor="gm-to">To</label>
                <input id="gm-to" type="date" className="inp" value={to} onChange={(e) => setTo(e.target.value)} required />
              </div>
            </div>
            {status.last_fetch_to && <div className="hint" style={{ marginTop: -8, marginBottom: 14, fontSize: 12, color: 'var(--fg-3)' }}>Starts where your last fetch ended. Emails already in the Inbox are skipped.</div>}

            {[...groups.entries()].map(([kind, g]) => (
              <div key={kind} className="field" style={kind === 'transaction_alert' ? { borderTop: '1px solid var(--border)', paddingTop: 14 } : undefined}>
                <label>
                  {g.label}
                  {kind === 'transaction_alert' && (
                    <span className="muted" style={{ fontWeight: 400 }}>
                      {' '}— optional: one email per transaction (can be many), read into transactions for you
                    </span>
                  )}
                </label>
                <div className="chips">
                  {g.list.map((p) => (
                    <button key={p.id} type="button" className={`chip ${selected.includes(p.id) ? 'on' : ''}`} aria-pressed={selected.includes(p.id)} onClick={() => toggle(p.id)}>
                      {p.name}
                    </button>
                  ))}
                </div>
              </div>
            ))}
            <div className="field">
              <label htmlFor="gm-custom">Custom Gmail searches <span className="muted" style={{ fontWeight: 400 }}>(one per line, optional)</span></label>
              <textarea id="gm-custom" className="inp t-mono" style={{ fontSize: 12.5 }} value={custom} onChange={(e) => setCustom(e.target.value)} placeholder={'from:swiggy.in subject:order\nfrom:yourbank.com debited'} />
              <div className="hint">Any Gmail search — another bank&apos;s alerts, receipts, insurance… Don&apos;t add dates; the range above is applied.</div>
            </div>
          </form>
        )}

        {run && (
          <div className="stack" style={{ gap: 14 }}>
            <div className="card card-pad">
              <div className="kv"><span className="k">Range</span><span className="v">{fmtDate(run.date_from)} – {fmtDate(run.date_to)}</span></div>
              <div className="kv"><span className="k">Matching emails</span><span className="v">{run.matched_count}</span></div>
              <div className="kv"><span className="k">New (not in Inbox yet)</span><span className="v">{run.new_count}</span></div>
              <div className="kv"><span className="k">Estimated download</span><span className="v">{run.bytes_human}</span></div>
            </div>
            {run.status === 'estimated' && run.new_count === 0 && <div className="note privacy"><Icon name="check" size={15} /> Nothing new to fetch for this range.</div>}
            {run.status === 'estimated' && run.consent_required && (
              <label className="note warn" style={{ cursor: 'pointer' }}>
                <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
                <span>This is more than {status.consent_threshold_mb >= 1000 ? `${status.consent_threshold_mb / 1000} GB` : `${status.consent_threshold_mb} MB`}. I understand about <b>{run.bytes_human}</b> will be downloaded to the server.</span>
              </label>
            )}
            {(active || finished) && (
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
                  <span>{run.progress}</span>
                  <span className="muted">{pct}%</span>
                </div>
                <div className="imp-bar"><i style={{ width: `${pct}%` }} /></div>
                {run.status === 'done' && <div className="note privacy" style={{ marginTop: 10 }}><Icon name="check" size={15} /> Done — {run.message_count} email(s) and {run.attachment_count} attachment(s) added to the Inbox.</div>}
                {run.status === 'cancelled' && <div className="note warn" style={{ marginTop: 10 }}>Stopped. {run.message_count} email(s) were fetched and kept.</div>}
                {run.status === 'error' && <div className="form-error" style={{ marginTop: 10 }}>{run.error}</div>}
              </div>
            )}
            <details>
              <summary className="muted" style={{ fontSize: 12.5, cursor: 'pointer' }}>Gmail searches used ({run.queries.length})</summary>
              <div className="imp-log" style={{ height: 'auto', maxHeight: 180, marginTop: 8 }}>
                {run.queries.map((qq, i) => <div key={i}><span className="ok">{qq.label}</span> <span className="dim">{qq.query}</span></div>)}
              </div>
            </details>
          </div>
        )}
      </div>
      <div className="drawer-foot">
        {run?.status === 'estimated' && <Button variant="ghost" onClick={() => setRun(null)}>Back</Button>}
        {active && <Button variant="ghost" icon="square" onClick={cancel} disabled={run?.status === 'cancelling'}>Stop</Button>}
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>{finished ? 'Close' : 'Cancel'}</Button>
        {!run && <Button variant="primary" type="submit" form="gm-fetch" disabled={busy}>{busy ? 'Searching Gmail…' : 'Check what’s there'}</Button>}
        {run?.status === 'estimated' && run.new_count > 0 && (
          <Button variant="primary" icon="download" onClick={start} disabled={busy || (run.consent_required && !consent)}>
            Fetch {run.new_count} email{run.new_count === 1 ? '' : 's'}
          </Button>
        )}
      </div>
    </>
  );
}
