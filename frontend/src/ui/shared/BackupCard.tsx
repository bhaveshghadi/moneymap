'use client';
import { useRef, useState, type FormEvent } from 'react';
import { api } from '../lib/api';
import { useApi, useShell } from '../contexts/ShellCtx';
import { fmtDate } from '../lib/format';
import { Button } from '../primitives/Button';
import { Icon } from '../primitives/Icon';
import { Dialog, useDialogClose } from '../primitives/Dialog';
import { DrawerHead } from './DrawerHead';

interface BackupFile {
  name: string;
  size: number;
  saved_at: string;
  kind: 'user' | 'server';
  note: string;
  created: string | null;
  username: string | null;
  transactions: number | null;
  accounts: number | null;
  last_date: string | null;
  people: number | null;
  problem: string | null;
}

type Scope = 'mine' | 'server';
const BASE: Record<Scope, string> = { mine: '/backup', server: '/backup/server' };

const mb = (n: number) => (n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
const day = (iso: string | null) => (iso ? fmtDate(iso.slice(0, 10)) : '—');
const time = (iso: string) => new Date(iso).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });

/** The file goes as the raw request body (no form encoding). */
async function uploadFile(scope: Scope, file: File): Promise<BackupFile> {
  const res = await fetch(`/api${BASE[scope]}/upload?filename=${encodeURIComponent(file.name)}`, {
    method: 'POST',
    body: file,
    headers: { 'Content-Type': 'application/octet-stream' },
    credentials: 'same-origin',
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new Error(typeof body?.detail === 'string' ? body.detail : `Upload failed (HTTP ${res.status})`);
  return body as BackupFile;
}

function what(f: BackupFile): string {
  if (f.problem) return f.problem;
  if (f.kind === 'server') return `${f.people ?? 0} ${f.people === 1 ? 'person' : 'people'}`;
  const n = (k: number | null, one: string) => `${k ?? 0} ${one}${k === 1 ? '' : 's'}`;
  const bits = [n(f.transactions, 'transaction'), n(f.accounts, 'account')];
  if (f.last_date) bits.push(`latest ${day(f.last_date)}`);
  return bits.join(' · ');
}

function Section({ scope, title, blurb }: { scope: Scope; title: string; blurb: string }) {
  const files = useApi<BackupFile[]>(`${BASE[scope]}/files`);
  const { bump } = useShell();
  const input = useRef<HTMLInputElement | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [restoring, setRestoring] = useState<BackupFile | null>(null);
  const [making, setMaking] = useState(false);

  const pick = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    setMsg(null);
    try {
      const f = await uploadFile(scope, file);
      bump();
      setMsg({ ok: true, text: `Uploaded. It's in the list below — use Restore on it when you're ready.` });
      setRestoring(f);
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
      if (input.current) input.current.value = '';
    }
  };
  const remove = async (f: BackupFile) => {
    setMsg(null);
    try {
      await api(`${BASE[scope]}/files/${encodeURIComponent(f.name)}`, { method: 'DELETE' });
      bump();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    }
  };
  const download = () => {
    setMaking(true); // the browser shows the download; making the file can take a moment
    window.location.href = `/api${BASE[scope]}/download`;
    setTimeout(() => setMaking(false), 4000);
  };

  return (
    <div style={{ marginBottom: scope === 'mine' ? 18 : 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', padding: '0 18px' }}>
        <h4 style={{ margin: 0, flex: 1, minWidth: 160 }}>{title}</h4>
        <Button variant="primary" size="sm" icon="download" onClick={download} disabled={making}>{making ? 'Preparing…' : 'Download backup'}</Button>
        <Button variant="secondary" size="sm" icon="upload" onClick={() => input.current?.click()} disabled={busy}>{busy ? 'Uploading…' : 'Upload a backup'}</Button>
        <input ref={input} type="file" accept={scope === 'mine' ? '.zip,.db' : '.zip'} hidden onChange={(e) => pick(e.target.files?.[0])} />
      </div>
      <div className="hint" style={{ padding: '6px 18px 8px' }}>{blurb}</div>
      {msg && <div className={msg.ok ? 'note privacy' : 'form-error'} role="status" style={{ margin: '0 18px 8px' }}>{msg.text}</div>}
      {(files.data ?? []).length === 0 ? (
        <div className="muted" style={{ padding: '0 18px 10px', fontSize: 13 }}>No saved backups yet. MoneyMap saves one here before every reset or restore.</div>
      ) : (
        <div className="tbl-wrap" style={{ padding: '0 6px 6px' }}>
          <table className="tbl" style={{ fontSize: 13 }}>
            <thead>
              <tr><th>Saved</th><th>What&apos;s in it</th><th className="r hide-sm">Size</th></tr>
            </thead>
            <tbody>
              {(files.data ?? []).map((f) => (
                <tr key={f.name}>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    <b>{day(f.saved_at)}</b> <span className="muted">{time(f.saved_at)}</span>
                    <div className="muted" style={{ fontSize: 12 }}>{f.note}</div>
                  </td>
                  <td>
                    <span style={f.problem ? { color: 'var(--red-600)' } : undefined}>{what(f)}</span>
                    <div style={{ display: 'flex', gap: 2, flexWrap: 'wrap', margin: '4px 0 0 -8px' }}>
                      {!f.problem && <Button variant="ghost" size="sm" icon="history" onClick={() => setRestoring(f)}>Restore</Button>}
                      <a className="btn btn-ghost btn-sm" style={{ textDecoration: 'none' }} href={`/api${BASE[scope]}/files/${encodeURIComponent(f.name)}`} download>
                        <Icon name="download" size={14} /> Download
                      </a>
                      <Button variant="ghost" size="sm" icon="trash-2" onClick={() => remove(f)}>Delete</Button>
                    </div>
                  </td>
                  <td className="r hide-sm" style={{ whiteSpace: 'nowrap' }}>{mb(f.size)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {restoring && (
        <Dialog onClose={() => setRestoring(null)} label="Restore backup" width={480}>
          <RestoreBody scope={scope} file={restoring} />
        </Dialog>
      )}
    </div>
  );
}

function RestoreBody({ scope, file }: { scope: Scope; file: BackupFile }) {
  const close = useDialogClose();
  const { bump } = useShell();
  const [password, setPassword] = useState('');
  const [word, setWord] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const r = await api<{ signed_out: boolean }>(`${BASE[scope]}/restore`, { method: 'POST', body: { name: file.name, password, confirm: word } });
      if (r.signed_out) {
        window.location.href = '/login';
        return;
      }
      bump();
      close();
      window.location.href = '/'; // everything on screen is from the backup now
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };
  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead title={scope === 'server' ? 'Restore the whole server' : 'Restore your data'} sub={`${day(file.created ?? file.saved_at)} · ${what(file)}`} />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        <div className="note warn" style={{ marginBottom: 14 }}>
          <Icon name="triangle-alert" size={15} />
          {scope === 'server' ? (
            <span>
              Every person&apos;s data, all logins and the secret key are replaced by this backup, and everyone is signed out. Today&apos;s server is
              saved first as a server backup (and its files kept in <span className="t-mono">replaced-…</span> in the data volume).
            </span>
          ) : (
            <span>
              Your data is replaced by this backup{file.username ? ` (made by ${file.username})` : ''}. What you have now is saved first, so you
              can restore it again from this list. Other people aren&apos;t touched.
            </span>
          )}
        </div>
        <div className="field">
          <label htmlFor="rs-pw">Your password</label>
          <input id="rs-pw" type="password" className="inp" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required autoFocus />
        </div>
        <div className="field">
          <label htmlFor="rs-word">Type <b>RESTORE</b> to confirm</label>
          <input id="rs-word" className="inp" value={word} onChange={(e) => setWord(e.target.value)} autoComplete="off" required />
        </div>
      </div>
      <div className="drawer-foot">
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        <Button variant="primary" type="submit" disabled={saving || word.trim() !== 'RESTORE'}>{saving ? 'Restoring…' : 'Restore'}</Button>
      </div>
    </form>
  );
}

/** Settings → Backup & restore: your own data for everyone; the whole server for admins. */
export function BackupCard() {
  const { isAdmin } = useShell();
  return (
    <div className="card" style={{ paddingBottom: 10 }}>
      <div className="card-head"><h3>Backup &amp; restore</h3></div>
      <Section
        scope="mine"
        title="Your data"
        blurb="A .zip of your money data, uploaded statements and Gmail attachments. Keep it somewhere safe — it isn't encrypted. Restoring replaces only your data."
      />
      {isAdmin && (
        <>
          <hr style={{ border: 0, borderTop: '1px solid var(--border)', margin: '6px 0 14px' }} />
          <Section
            scope="server"
            title="Whole server (admin)"
            blurb="Everyone's data, the logins and the secret key (needed for saved Gmail connections) — for moving MoneyMap to another machine or recovering from a disaster."
          />
        </>
      )}
    </div>
  );
}
