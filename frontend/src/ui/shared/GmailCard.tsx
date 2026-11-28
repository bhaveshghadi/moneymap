'use client';
import { useEffect, useState, type FormEvent } from 'react';
import Link from 'next/link';
import { usePathname, useSearchParams } from 'next/navigation';
import { api, replaceQuery } from '../lib/api';
import { useApi, useShell } from '../contexts/ShellCtx';
import type { GmailConnectOut, GmailStatus } from '../lib/types';
import { Button } from '../primitives/Button';
import { Icon } from '../primitives/Icon';
import { ErrorState } from '../primitives/ErrorState';

/** Settings card: own OAuth client → connect (read-only) → status. */
export function GmailCard() {
  const { bump } = useShell();
  const { data: st, reload, error: loadError } = useApi<GmailStatus>('/gmail/status');
  const [jsonText, setJsonText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState<GmailConnectOut | null>(null);
  const [pasted, setPasted] = useState('');
  const [busy, setBusy] = useState(false);
  const [replacing, setReplacing] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [confirmBox, setConfirmBox] = useState<number | null>(null);

  // Result of Google's redirect back to /settings?gmail=… — shown once per new URL, then the
  // query is dropped from the address bar.
  const sp = useSearchParams();
  const pathname = usePathname();
  const search = sp.toString();
  const [seenSearch, setSeenSearch] = useState<string | null>(null);
  if (search !== seenSearch) {
    setSeenSearch(search);
    const g = sp.get('gmail');
    if (g === 'connected') setNotice('Gmail account connected. You can fetch emails from the Inbox page.');
    else if (g) setError(`Gmail connection failed: ${sp.get('reason') ?? 'unknown error'}`);
  }
  useEffect(() => {
    if (sp.get('gmail')) replaceQuery(pathname, '');
  }, [sp, pathname]);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await fn();
      reload();
      bump();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const saveClient = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      await api('/gmail/client', { method: 'PUT', body: { json_text: jsonText } });
      setJsonText('');
      setReplacing(false);
    });
  };

  const connect = () =>
    run(async () => {
      const r = await api<GmailConnectOut>('/gmail/connect', { method: 'POST', body: { origin: window.location.origin } });
      if (r.direct) {
        window.location.href = r.url; // Google redirects back to /api/gmail/callback
      } else {
        setPending(r); // browser isn't on the server: open Google in a new tab, paste the URL back
        window.open(r.url, '_blank', 'noopener');
      }
    });

  const submitPasted = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      await api('/gmail/callback-url', { method: 'POST', body: { url: pasted } });
      setPending(null);
      setPasted('');
      setNotice('Gmail connected.');
    });
  };

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="card-head">
        <h3 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Icon name="mail" size={17} /> Gmail import
          {st?.connected && <span className="badge mint">Connected</span>}
        </h3>
        {st?.connected && <Link className="link" href="/inbox">Open Inbox <Icon name="arrow-right" size={13} /></Link>}
      </div>
      <div className="card-pad" style={{ paddingTop: 4 }}>
        {error && <div className="form-error" role="alert">{error}</div>}
        {notice && <div className="note privacy" style={{ marginBottom: 14 }}><Icon name="check" size={15} /> {notice}</div>}
        {st?.client_env_error && (
          <div className="form-error" role="alert">{st.client_env_error} — fix it in the server&apos;s .env and restart MoneyMap.</div>
        )}

        {loadError && !st ? (
          <ErrorState message={loadError} onRetry={reload} />
        ) : !st ? (
          <div className="muted" style={{ fontSize: 13 }}>Loading…</div>
        ) : !st.client_configured || (replacing && !st.client_from_env) ? (
          <form onSubmit={saveClient}>
            <p style={{ margin: '0 0 12px', fontSize: 13.5, lineHeight: 1.55, color: 'var(--fg-2)' }}>
              MoneyMap reads bank, card and loan statement emails (and, if you choose, transaction alerts) with <b>your own</b> Google OAuth client, so no third party ever sees your mail.
              Access is <b>read-only</b> — it can never send, delete or change anything.
            </p>
            <ol style={{ margin: '0 0 14px', paddingLeft: 20, fontSize: 13, lineHeight: 1.7, color: 'var(--fg-2)' }}>
              <li>In <a href="https://console.cloud.google.com/apis/library/gmail.googleapis.com" target="_blank" rel="noreferrer">Google Cloud Console</a>, create a project and enable the <b>Gmail API</b>.</li>
              <li>Under <i>OAuth consent screen</i>, choose <b>External</b>, and add your Gmail address as a <b>test user</b>.</li>
              <li>Under <i>Credentials → Create credentials → OAuth client ID</i>, pick <b>Desktop app</b> and download the JSON.</li>
              <li>Paste the whole file below.</li>
            </ol>
            <div className="field">
              <label htmlFor="gm-json">OAuth client JSON</label>
              <textarea id="gm-json" className="inp t-mono" style={{ minHeight: 110, fontSize: 12.5 }} value={jsonText} onChange={(e) => setJsonText(e.target.value)} placeholder='{"installed":{"client_id":"…","client_secret":"…",…}}' required />
              <div className="hint">
                Stored encrypted in MoneyMap&apos;s database on your server, together with the Gmail token. Or keep it out of the database: put it in
                the server&apos;s <span className="t-mono">.env</span> as <span className="t-mono">MONEYMAP_GOOGLE_CLIENT_JSON</span> and restart.
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <Button variant="primary" type="submit" disabled={busy}>Save client</Button>
              {replacing && <Button variant="ghost" onClick={() => setReplacing(false)}>Cancel</Button>}
            </div>
          </form>
        ) : (
          <>
            {st.mailboxes.length > 0 && (
              <div className="gm-boxes" style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 14 }}>
                {st.mailboxes.map((m) => (
                  <div key={m.id} className="card-pad" style={{ border: '1px solid var(--border)', borderRadius: 10, padding: '10px 12px', display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                    <Icon name="mail" size={16} color={m.connected ? 'var(--red-500)' : 'var(--fg-3)'} />
                    <div style={{ flex: 1, minWidth: 180 }}>
                      <div style={{ fontWeight: 600, overflowWrap: 'anywhere' }}>
                        {m.email ?? 'Gmail account'}{' '}
                        {m.connected ? <span className="badge mint">Connected</span> : <span className="badge neutral">Not connected</span>}
                      </div>
                      <div className="muted" style={{ fontSize: 12.5 }}>
                        {m.emails} email{m.emails === 1 ? '' : 's'} in the Inbox · {m.last_fetch_to ? `fetched up to ${m.last_fetch_to}` : 'nothing fetched yet'}
                      </div>
                    </div>
                    {m.connected ? (
                      <Button variant="ghost" size="sm" icon="unplug" disabled={busy} onClick={() => run(() => api('/gmail/disconnect', { method: 'POST', body: { mailbox_id: m.id } }))}>
                        Disconnect
                      </Button>
                    ) : (
                      <>
                        <Button variant="secondary" size="sm" disabled={busy} onClick={connect}>Reconnect</Button>
                        <Button
                          variant={confirmBox === m.id ? 'primary' : 'ghost'}
                          size="sm"
                          className={confirmBox === m.id ? 'btn-danger' : ''}
                          disabled={busy}
                          onClick={() => (confirmBox === m.id ? run(() => api(`/gmail/mailboxes/${m.id}`, { method: 'DELETE' })) : setConfirmBox(m.id))}
                        >
                          {confirmBox === m.id ? 'Confirm remove' : 'Remove'}
                        </Button>
                      </>
                    )}
                  </div>
                ))}
              </div>
            )}
            {!st.connected && (
              <p style={{ fontSize: 13.5, color: 'var(--fg-2)', lineHeight: 1.55 }}>
                {st.mailboxes.length ? 'Connect again, or ' : 'Next, '}sign in with Google and allow <b>read-only</b> Gmail access. Google may warn that the
                app isn&apos;t verified — that&apos;s expected for your own client; choose <i>Continue</i>.
              </p>
            )}
            {pending ? (
              <form onSubmit={submitPasted}>
                <div className="note info" style={{ marginBottom: 12 }}>
                  <Icon name="info" size={15} />
                  <span>
                    Google opened in a new tab. After you allow access it will try to load <span className="t-mono">{pending.redirect_uri}</span>,
                    which won&apos;t open on this device — that&apos;s fine. Copy the <b>whole address</b> from that tab and paste it here.
                    {' '}<a href={pending.url} target="_blank" rel="noreferrer">Open Google again</a>
                  </span>
                </div>
                <div className="field">
                  <label htmlFor="gm-paste">Address from the Google tab</label>
                  <input id="gm-paste" className="inp t-mono" value={pasted} onChange={(e) => setPasted(e.target.value)} placeholder="http://127.0.0.1:…/api/gmail/callback?state=…&code=…" required />
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <Button variant="primary" type="submit" disabled={busy}>Finish connecting</Button>
                  <Button variant="ghost" onClick={() => setPending(null)}>Cancel</Button>
                </div>
              </form>
            ) : (
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <button type="button" className="gbtn" onClick={connect} disabled={busy}>
                  <Icon name="mail" size={18} color="var(--red-500)" /> {st.connected ? 'Connect another Gmail' : 'Connect Gmail (read-only)'}
                </button>
                {!st.connected && !st.client_from_env && <Button variant="ghost" size="sm" onClick={() => setReplacing(true)}>Use a different client</Button>}
              </div>
            )}
            {st.connected && (
              <div className="hint" style={{ marginTop: 8 }}>
                Sign in with the other address when Google asks. If your Google app is in <i>Testing</i>, add that address under{' '}
                <i>OAuth consent screen → Test users</i> first.
              </div>
            )}
            <div style={{ marginTop: 16 }}>
              <div className="kv"><span className="k">Access</span><span className="v">Read-only (gmail.readonly)</span></div>
              <div className="kv">
                <span className="k">OAuth client</span>
                <span className="v">
                  {st.client_from_env ? 'From the server (MONEYMAP_GOOGLE_CLIENT_JSON)' : <span className="t-mono">{st.client_id_hint}</span>}
                </span>
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8, marginTop: 14, flexWrap: 'wrap' }}>
              {st.mailboxes.filter((m) => m.connected).length > 1 && (
                <Button variant="ghost" size="sm" icon="unplug" onClick={() => run(() => api('/gmail/disconnect', { method: 'POST', body: {} }))} disabled={busy}>
                  Disconnect all
                </Button>
              )}
              {st.connected && !st.client_from_env && (
              <Button
                variant={confirmRemove ? 'primary' : 'ghost'}
                size="sm"
                className={confirmRemove ? 'btn-danger' : ''}
                onClick={() => (confirmRemove ? run(() => api('/gmail/client', { method: 'DELETE' })) : setConfirmRemove(true))}
                disabled={busy}
              >
                {confirmRemove ? 'Confirm: forget client & disconnect' : 'Remove OAuth client'}
              </Button>
              )}
            </div>
            <p className="muted" style={{ fontSize: 12.5, marginBottom: 0 }}>Disconnecting also revokes MoneyMap&apos;s access to that account at Google. Emails already fetched stay in the Inbox.</p>
          </>
        )}
      </div>
    </div>
  );
}
