'use client';
import { useRef, useState, type DragEvent, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import type { Account } from '../lib/types';
import { api, ApiError } from '../lib/api';
import { useApi, useShell } from '../contexts/ShellCtx';
import { Dialog, useDialogClose } from '../primitives/Dialog';
import { Button } from '../primitives/Button';
import { CategoryGlyph } from '../primitives/CategoryGlyph';
import { Icon } from '../primitives/Icon';
import { DrawerHead } from './DrawerHead';

const MAX_MB = 15;

function toBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(',')[1] ?? '');
    r.onerror = () => reject(new Error('The file could not be read.'));
    r.readAsDataURL(file);
  });
}

/** Upload a statement PDF downloaded from the bank's website → review page.
 * (A mutual fund CAS is refused with a message — that comes with Investments.) */
export function UploadStatement({ onClose }: { onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label="Upload statement" width={500}>
      <Body />
    </Dialog>
  );
}

const cas = false; // CAS mode returns with the Investments feature

function Body() {
  const close = useDialogClose();
  const router = useRouter();
  const { bump } = useShell();
  const accounts = useApi<Account[]>('/accounts?type=asset&type=cash&type=credit_card');
  const fileRef = useRef<HTMLInputElement | null>(null);
  const pwRef = useRef<HTMLInputElement | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [accountId, setAccountId] = useState('');
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(false);
  const [needPw, setNeedPw] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const pick = (f: File | undefined | null) => {
    if (!f) return;
    setError(null);
    setNeedPw(false);
    if (!f.name.toLowerCase().endsWith('.pdf') && f.type !== 'application/pdf') return setError('Choose a PDF statement.');
    if (f.size > MAX_MB * 1024 * 1024) return setError(`That file is over ${MAX_MB} MB — statements are usually much smaller.`);
    setFile(f);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDrag(false);
    pick(e.dataTransfer.files?.[0]);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return setError(cas ? 'Choose the CAS PDF first.' : 'Choose the statement PDF first.');
    setBusy(true);
    setError(null);
    try {
      const content_b64 = await toBase64(file);
      {
        const res = await api<{ id: number; opened_existing: boolean; gmail_message_id: string | null }>('/statements/upload', {
          method: 'POST',
          body: {
            filename: file.name,
            content_b64,
            account_id: accountId ? Number(accountId) : null,
            password: password || null,
            remember_password: remember && !!accountId && !!password,
          },
        });
        bump();
        close();
        // Already opened (from the Inbox or an earlier upload) → say so on the review page.
        const note = res.opened_existing ? '?existing=1' : res.gmail_message_id ? '?existing=email' : '';
        router.push(`/statements/${res.id}${note}`);
      }
    } catch (err) {
      const code = err instanceof ApiError ? err.code : undefined;
      if (code === 'password_required' || code === 'wrong_password') {
        setNeedPw(true);
        setTimeout(() => pwRef.current?.focus(), 50);
      }
      setError(code === 'password_required' && !password ? 'This PDF is password-protected — enter its password.' : (err as Error).message);
      setBusy(false);
    }
  };

  const own = (accounts.data ?? []).filter((a) => a.active);

  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead
        title={cas ? 'Import CAS' : 'Upload statement'}
        sub={cas ? 'Consolidated Account Statement from CAMS / KFintech' : "A PDF from your bank's website or app"}
        lead={<CategoryGlyph icon={cas ? 'trending-up' : 'file-up'} color="indigo" size={42} />}
      />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        <div
          className={`dropzone ${drag ? 'over' : ''} ${file ? 'has-file' : ''}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={onDrop}
          onClick={() => fileRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), fileRef.current?.click())}
          aria-label="Choose a statement PDF"
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
              <span className="muted">{cas ? 'Detailed CAS PDF' : 'Bank or credit card statement'} · up to {MAX_MB} MB</span>
            </>
          )}
          <input ref={fileRef} type="file" accept="application/pdf,.pdf" hidden onChange={(e) => pick(e.target.files?.[0])} />
        </div>

        {!cas && (
        <div className="field" style={{ marginTop: 16 }}>
          <label htmlFor="up-acct">Account</label>
          <select id="up-acct" className="inp" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
            <option value="">Work it out from the statement</option>
            {own.map((a) => (
              <option key={a.id} value={a.id}>{a.name}{a.account_number ? ` (${a.account_number})` : ''}</option>
            ))}
          </select>
          <div className="hint">Picked automatically when the account number on the statement matches one of your accounts. You can change it on the next screen.</div>
        </div>
        )}

        <div className="field" style={cas ? { marginTop: 16 } : undefined}>
          <label htmlFor="up-pw">
            PDF password {!needPw && <span className="muted" style={{ fontWeight: 400 }}>(only if it&apos;s protected)</span>}
          </label>
          <input ref={pwRef} id="up-pw" type="password" className="inp" autoComplete="off" value={password} onChange={(e) => setPassword(e.target.value)} />
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13, marginTop: 8, opacity: cas || accountId ? 1 : 0.55 }}>
            <input type="checkbox" checked={remember} disabled={!cas && !accountId} onChange={(e) => setRemember(e.target.checked)} />
            {cas ? 'Remember it for my next CAS' : 'Remember it for this account’s next statements'}
          </label>
        </div>
        <div className="note info" style={{ marginTop: 4 }}>
          <Icon name="info" size={15} />
          <span>
            {cas
              ? 'Nothing is imported yet — you’ll match each fund to an account and check every transaction first.'
              : 'Nothing is imported yet — you’ll review every row first, just like statements from the Inbox.'}
          </span>
        </div>
      </div>
      <div className="drawer-foot">
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        <Button variant="primary" type="submit" icon="file-search" disabled={busy || !file}>{busy ? 'Reading…' : cas ? 'Read CAS' : 'Read statement'}</Button>
      </div>
    </form>
  );
}
