'use client';
import { useEffect, useRef, useState, type DragEvent, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import type { Account, Loan, LoanFirstInterest, LoanMethod, LoanStatementDiff, LoanStatementEvent, LoanStatementResult } from '../lib/types';
import { api, ApiError } from '../lib/api';
import { fmtDate, rs } from '../lib/format';
import { useApi, useShell } from '../contexts/ShellCtx';
import { useMask } from '../contexts/MaskCtx';
import { Dialog, useDialogClose } from '../primitives/Dialog';
import { Button } from '../primitives/Button';
import { CategoryGlyph } from '../primitives/CategoryGlyph';
import { Icon } from '../primitives/Icon';
import { Money } from '../primitives/Money';
import { DrawerHead } from './DrawerHead';
import { FIRST_INTEREST_LABEL, LoanFormBody, METHOD_LABEL, kindLabel } from './LoanForm';
import { useStay } from '../contexts/StayCtx';

const MAX_MB = 15;

function toBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(',')[1] ?? '');
    r.onerror = () => reject(new Error('The file could not be read.'));
    r.readAsDataURL(file);
  });
}

/** Read a lender's loan statement / repayment schedule:
 * - no matching loan → the Add-loan form, filled in from it;
 * - a loan you have (opened from it, or the same loan number) → what differs, a tick box each. */
export function LoanStatementDialog({
  onClose,
  accountId,
  attachmentId,
  fileRef,
}: {
  onClose: () => void;
  accountId?: number;
  attachmentId?: number;
  fileRef?: string;
}) {
  return (
    <Dialog onClose={onClose} label="Loan statement" width={600}>
      <Body accountId={accountId} attachmentId={attachmentId} fileRef={fileRef} />
    </Dialog>
  );
}

type Source = { attachment_id: number } | { file_ref: string } | { filename: string; content_b64: string };

function Body({ accountId, attachmentId, fileRef }: { accountId?: number; attachmentId?: number; fileRef?: string }) {
  const close = useDialogClose();
  const fileInput = useRef<HTMLInputElement | null>(null);
  const pwRef = useRef<HTMLInputElement | null>(null);
  const given: Source | null = attachmentId ? { attachment_id: attachmentId } : fileRef ? { file_ref: fileRef } : null;
  const [source, setSource] = useState<Source | null>(given);
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(false);
  const [needPw, setNeedPw] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(!!given);
  const [result, setResult] = useState<LoanStatementResult | null>(null);
  const [target, setTarget] = useState<number | undefined>(accountId);

  const read = async (src: Source, forLoan: number | undefined, pw?: string) => {
    setBusy(true);
    setError(null);
    try {
      const res = await api<LoanStatementResult>('/loans/statement/read', {
        method: 'POST',
        body: { ...src, password: pw || null, remember_password: remember && !!pw, account_id: forLoan ?? null },
      });
      // later reads (another loan chosen) use the stored file, not a second upload
      setSource(res.attachment_id ? { attachment_id: res.attachment_id } : res.file_ref ? { file_ref: res.file_ref } : src);
      setResult(res);
      setTarget(forLoan ?? res.match?.account_id);
      setNeedPw(false);
    } catch (err) {
      const code = err instanceof ApiError ? err.code : undefined;
      if (code === 'password_required' || code === 'wrong_password') {
        setNeedPw(true);
        setTimeout(() => pwRef.current?.focus(), 50);
        setError(code === 'password_required' && !pw ? 'This PDF is password-protected — enter its password.' : (err as Error).message);
      } else {
        setError((err as Error).message);
      }
    }
    setBusy(false);
  };

  // opened from the Inbox / a statement upload: read it straight away
  useEffect(() => {
    if (!given) return;
    let live = true;
    api<LoanStatementResult>('/loans/statement/read', { method: 'POST', body: { ...given, account_id: accountId ?? null } })
      .then((res) => {
        if (!live) return;
        setResult(res);
        setTarget(accountId ?? res.match?.account_id);
      })
      .catch((err) => {
        if (!live) return;
        const code = err instanceof ApiError ? err.code : undefined;
        if (code === 'password_required' || code === 'wrong_password') setNeedPw(true);
        else setError((err as Error).message);
      })
      .finally(() => live && setBusy(false));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pick = (f: File | undefined | null) => {
    if (!f) return;
    setError(null);
    if (!f.name.toLowerCase().endsWith('.pdf') && f.type !== 'application/pdf') return setError('Choose a PDF.');
    if (f.size > MAX_MB * 1024 * 1024) return setError(`That file is over ${MAX_MB} MB.`);
    setFile(f);
    setSource(null);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    let src = source;
    if (!src) {
      if (!file) return setError('Choose the loan statement PDF first.');
      src = { filename: file.name, content_b64: await toBase64(file) };
    }
    await read(src, accountId, password);
  };

  if (result && !target) return <NewLoan result={result} onPickLoan={(id) => source && read(source, id, password)} />;
  if (result && target) return <UpdateLoan result={result} accountId={target} />;

  const auto = !!given;
  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead
        title={accountId ? 'Update from statement' : 'Add from statement'}
        sub="A loan statement or repayment schedule (PDF) from your lender"
        lead={<CategoryGlyph icon="file-search" color="coral" size={42} />}
      />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        {auto ? (
          busy && <div className="muted">Reading the statement…</div>
        ) : (
          <div
            className={`dropzone ${drag ? 'over' : ''} ${file ? 'has-file' : ''}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDrag(true);
            }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e: DragEvent) => {
              e.preventDefault();
              setDrag(false);
              pick(e.dataTransfer.files?.[0]);
            }}
            onClick={() => fileInput.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), fileInput.current?.click())}
            aria-label="Choose the loan statement PDF"
          >
            <Icon name={file ? 'file-check' : 'upload'} size={26} />
            {file ? (
              <>
                <b>{file.name}</b>
                <span className="muted">{(file.size / 1024).toFixed(0)} KB · click to choose another</span>
              </>
            ) : (
              <>
                <b>Drop the PDF here, or click to choose</b>
                <span className="muted">Statement of account or repayment schedule · up to {MAX_MB} MB</span>
              </>
            )}
            <input ref={fileInput} type="file" accept="application/pdf,.pdf" hidden onChange={(e) => pick(e.target.files?.[0])} />
          </div>
        )}
        {(!auto || needPw) && (
          <div className="field" style={{ marginTop: 16 }}>
            <label htmlFor="ls-pw">
              PDF password {!needPw && <span className="muted" style={{ fontWeight: 400 }}>(only if it&apos;s protected)</span>}
            </label>
            <input ref={pwRef} id="ls-pw" type="password" className="inp" autoComplete="off" value={password} onChange={(e) => setPassword(e.target.value)} />
            <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13, marginTop: 8 }}>
              <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
              {given && 'attachment_id' in given ? 'Remember it for this sender’s PDFs' : 'Remember it for my next loan statements'}
            </label>
          </div>
        )}
        <div className="note info" style={{ marginTop: 4 }}>
          <Icon name="info" size={15} />
          <span>Nothing is saved yet — you’ll see what was read and choose what to use.</span>
        </div>
      </div>
      <div className="drawer-foot">
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        {(!auto || needPw) && (
          <Button variant="primary" type="submit" icon="file-search" disabled={busy || (!file && !source)}>
            {busy ? 'Reading…' : 'Read statement'}
          </Button>
        )}
      </div>
    </form>
  );
}

// ---------------------------------------------------------------- new loan

function NewLoan({ result, onPickLoan }: { result: LoanStatementResult; onPickLoan: (accountId: number) => void }) {
  const loans = useApi<Loan[]>('/loans');
  const others = (loans.data ?? []).filter((l) => l.status === 'active');
  return (
    <LoanFormBody
      initial={result}
      banner={
        others.length > 0 ? (
          <div className="field" style={{ marginBottom: 12 }}>
            <label htmlFor="ls-for">This statement is for</label>
            <select id="ls-for" className="inp" value="" onChange={(e) => e.target.value && onPickLoan(Number(e.target.value))}>
              <option value="">A new loan (add it)</option>
              {others.map((l) => (
                <option key={l.id} value={l.id}>Update {l.name}</option>
              ))}
            </select>
          </div>
        ) : null
      }
    />
  );
}

// ---------------------------------------------------------------- part-payments / rate changes

export interface EventPick {
  on: boolean;
  date: string;
  mode: 'reduce_tenure' | 'reduce_emi';
  pay: string; // 'txn' (the matched bank payment) | 'none' (only the change) | an account id
}

export function initialPicks(events: LoanStatementEvent[]): EventPick[] {
  return events.map((e) => ({
    on: !e.already_recorded && !e.date_unknown,
    date: e.date,
    mode: e.mode,
    pay: e.transaction_id ? 'txn' : 'none',
  }));
}

export function StatementEvents({
  events,
  picks,
  onChange,
  canChange,
}: {
  events: LoanStatementEvent[];
  picks: EventPick[];
  onChange: (i: number, p: Partial<EventPick>) => void;
  canChange: boolean;
}) {
  const banks = useApi<Account[]>('/accounts?type=asset&type=cash&include_inactive=false');
  const { masked } = useMask(); // the statement's own line has amounts in it
  if (!events.length) return null;
  return (
    <div className="field">
      <label>Part-payments and rate changes in the statement</label>
      {!canChange && (
        <div className="note warn" style={{ marginBottom: 8 }}>
          <span>These need a reducing-balance loan with an amount and a rate.</span>
        </div>
      )}
      <div className="ls-events">
        {events.map((e, i) => {
          const p = picks[i];
          return (
            <div key={i} className={`ls-event ${p.on ? 'on' : ''}`}>
              <label className="ls-event-head">
                <input
                  type="checkbox"
                  checked={p.on && canChange && !e.already_recorded}
                  disabled={!canChange || e.already_recorded}
                  onChange={(ev) => onChange(i, { on: ev.target.checked })}
                />
                <span style={{ flex: 1 }}>
                  {e.kind === 'prepay' ? (
                    <>Part-payment <b><Money amount={rs(e.amount ?? 0)} interactive={false} /></b></>
                  ) : (
                    <>Rate changed to <b>{e.rate}%</b></>
                  )}{' '}
                  {e.date_unknown ? '' : <>on {fmtDate(e.date)}</>}
                  {e.source === 'schedule' && <span className="muted"> · seen in the schedule (before the next EMI)</span>}
                </span>
                {e.already_recorded && <span className="badge mint">Already recorded</span>}
              </label>
              {e.text && (!masked || e.kind === 'rate') && <div className="muted ls-event-text">{e.text}</div>}
              {p.on && canChange && !e.already_recorded && (
                <div className="ls-event-opts">
                  {e.date_unknown && (
                    <input className="inp" type="date" aria-label="Changed on" value={p.date} onChange={(ev) => onChange(i, { date: ev.target.value })} />
                  )}
                  <select className="inp" aria-label="What it changed" value={p.mode} onChange={(ev) => onChange(i, { mode: ev.target.value as EventPick['mode'] })}>
                    <option value="reduce_tenure">EMI stays, loan ends sooner{e.kind === 'rate' ? ' / later' : ''}</option>
                    <option value="reduce_emi">End date stays, EMI changes</option>
                  </select>
                  {e.kind === 'prepay' && (
                    <select className="inp" aria-label="The payment" value={p.pay} onChange={(ev) => onChange(i, { pay: ev.target.value })}>
                      {e.transaction_id && <option value="txn">Your payment: {e.transaction}</option>}
                      <option value="none">Only the change to the loan (payment already counted, or before you tracked it)</option>
                      {(banks.data ?? []).map((a) => (
                        <option key={a.id} value={a.id}>Record the payment from {a.name}</option>
                      ))}
                    </select>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Record the ticked part-payments / rate changes on a loan, oldest first. */
export async function applyEvents(accountId: number, events: LoanStatementEvent[], picks: EventPick[]): Promise<number> {
  const todo = events.map((e, i) => ({ e, p: picks[i] })).filter(({ e, p }) => p.on && !e.already_recorded);
  todo.sort((a, b) => a.p.date.localeCompare(b.p.date));
  for (const { e, p } of todo) {
    if (e.kind === 'rate') {
      await api(`/loans/${accountId}/rate`, { method: 'POST', body: { date: p.date, rate: e.rate, mode: p.mode } });
    } else {
      const body: Record<string, unknown> = { date: p.date, amount: e.amount, mode: p.mode };
      if (p.pay === 'txn' && e.transaction_id) body.transaction_id = e.transaction_id;
      else if (p.pay === 'none') body.record_payment = false;
      else body.from_account_id = Number(p.pay);
      await api(`/loans/${accountId}/prepay`, { method: 'POST', body });
    }
  }
  return todo.length;
}

// ---------------------------------------------------------------- a loan you have

function UpdateLoan({ result, accountId }: { result: LoanStatementResult; accountId: number }) {
  const close = useDialogClose();
  const router = useRouter();
  const stay = useStay();
  const { bump } = useShell();
  const loan = useApi<Loan>(`/loans/${accountId}`);
  const diffs = result.match?.differences ?? [];
  const [ticked, setTicked] = useState<boolean[]>(() => diffs.map((d) => d.patch !== null));
  const [picks, setPicks] = useState<EventPick[]>(() => initialPicks(result.events));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const name = result.match?.name ?? loan.data?.name ?? 'this loan';

  const apply = async () => {
    setSaving(true);
    setError(null);
    try {
      const patch = diffs.reduce<Record<string, unknown>>((acc, d, i) => (ticked[i] && d.patch ? { ...acc, ...d.patch } : acc), {});
      if (Object.keys(patch).length) await api(`/loans/${accountId}`, { method: 'PATCH', body: patch });
      await applyEvents(accountId, result.events, picks);
      bump();
      close();
      if (!stay) router.push(`/loans/${accountId}`);
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  const anything = ticked.some(Boolean) || picks.some((p, i) => p.on && !result.events[i].already_recorded);
  return (
    <>
      <DrawerHead title={`Update ${name}`} sub={result.filename} lead={<CategoryGlyph icon="file-search" color="coral" size={42} />} />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        <CheckNote result={result} />
        {diffs.length === 0 && result.events.length === 0 ? (
          <div className="note info">
            <Icon name="check" size={15} />
            <span>The statement agrees with {name} — nothing to change.</span>
          </div>
        ) : (
          <>
            {diffs.length > 0 && (
              <div className="field">
                <label>What the statement says differently</label>
                <div className="ls-diffs">
                  {diffs.map((d, i) => (
                    <label key={d.field} className={`ls-diff ${d.patch ? '' : 'info'}`}>
                      {d.patch ? (
                        <input type="checkbox" checked={ticked[i]} onChange={(e) => setTicked((t) => t.map((x, j) => (j === i ? e.target.checked : x)))} />
                      ) : (
                        <Icon name="info" size={15} />
                      )}
                      <span className="ls-diff-label">{d.label}</span>
                      <span className="ls-diff-vals">
                        <s className="muted"><DiffValue d={d} v={d.current} /></s> <Icon name="arrow-right" size={12} /> <b><DiffValue d={d} v={d.statement} /></b>
                      </span>
                      {d.note && <span className="muted ls-diff-note">{d.note}</span>}
                    </label>
                  ))}
                </div>
              </div>
            )}
            <StatementEvents
              events={result.events}
              picks={picks}
              onChange={(i, p) => setPicks((all) => all.map((x, j) => (j === i ? { ...x, ...p } : x)))}
              canChange={loan.data?.supports_changes ?? true}
            />
          </>
        )}
      </div>
      <div className="drawer-foot">
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        <Button variant="primary" icon="check" onClick={apply} disabled={saving || !anything}>{saving ? 'Applying…' : 'Apply ticked'}</Button>
      </div>
    </>
  );
}

/** A value in "what differs": amounts go through <Money> so they stay hidden when amounts are. */
function DiffValue({ d, v }: { d: LoanStatementDiff; v: string | number | null }) {
  if (v === null || v === '') return <>—</>;
  switch (d.kind) {
    case 'money':
      return <Money amount={rs(Number(v))} interactive={false} />;
    case 'date':
      return <>{fmtDate(String(v))}</>;
    case 'rate':
      return <>{Number(v)}%</>;
    case 'kind':
      return <>{kindLabel(String(v))}</>;
    case 'first_interest':
      return <>{FIRST_INTEREST_LABEL[v as LoanFirstInterest] ?? String(v)}</>;
    case 'method':
      return <>{METHOD_LABEL[v as LoanMethod] ?? String(v)}</>;
    default:
      return <>{String(v)}</>;
  }
}

export function CheckNote({ result }: { result: LoanStatementResult }) {
  const c = result.check;
  if (!result.schedule_rows) return null;
  if (!c) {
    return (
      <div className="note info" style={{ marginBottom: 12 }}>
        <Icon name="table" size={15} />
        <span>Read {result.schedule_rows} rows of the repayment schedule.</span>
      </div>
    );
  }
  return c.matches ? (
    <div className="note info" style={{ marginBottom: 12 }}>
      <Icon name="check" size={15} />
      <span>
        The lender’s schedule ({c.rows} EMIs) matches MoneyMap’s maths for these terms
        {c.max_diff > 0 ? <> (within <Money amount={rs(c.max_diff)} interactive={false} />)</> : ' to the paisa'}.
      </span>
    </div>
  ) : (
    <div className="note warn" style={{ marginBottom: 12 }}>
      <Icon name="triangle-alert" size={15} />
      <span>
        The lender’s schedule differs from MoneyMap’s maths by up to <Money amount={rs(c.max_diff)} interactive={false} /> — check the
        rate, the EMI and the first EMI’s interest below.
      </span>
    </div>
  );
}
