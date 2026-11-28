'use client';
import { useState, type FormEvent } from 'react';
import { api } from '../lib/api';
import { useApi, useShell } from '../contexts/ShellCtx';
import type { ManagedUser } from '../lib/types';
import { fmtDate } from '../lib/format';
import { Button } from '../primitives/Button';
import { Icon } from '../primitives/Icon';
import { Dialog, useDialogClose } from '../primitives/Dialog';
import { DrawerHead } from './DrawerHead';

type Dlg = null | { kind: 'add' } | { kind: 'password'; user: ManagedUser; password: string; added: boolean } | { kind: 'delete'; user: ManagedUser };

const when = (iso: string | null) => (iso ? fmtDate(iso.slice(0, 10)) : '—');

function statusOf(u: ManagedUser): [string, string] {
  if (u.disabled) return ['red', 'Turned off'];
  if (u.locked) return ['red', 'Locked (wrong passwords)'];
  if (u.must_change_password) return ['neutral', 'Waiting for first sign-in'];
  return ['brand', 'Active'];
}

/** Settings → Users (admins only). Like Immich: the admin adds everyone; there is no sign-up page. */
export function UsersCard() {
  const { username: me } = useShell();
  const { bump } = useShell();
  const users = useApi<ManagedUser[]>('/users');
  const [dlg, setDlg] = useState<Dlg>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  const act = async (u: ManagedUser, fn: () => Promise<void>) => {
    setMsg(null);
    setBusy(u.id);
    try {
      await fn();
      bump();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const patch = (u: ManagedUser, body: Partial<Pick<ManagedUser, 'disabled' | 'is_admin'>>) =>
    act(u, async () => {
      await api(`/users/${u.id}`, { method: 'PATCH', body });
    });
  const resetPassword = (u: ManagedUser) =>
    act(u, async () => {
      const r = await api<{ user: ManagedUser; temporary_password: string }>(`/users/${u.id}/reset-password`, { method: 'POST' });
      setDlg({ kind: 'password', user: r.user, password: r.temporary_password, added: false });
    });

  return (
    <div className="card">
      <div className="card-head">
        <h3>Users</h3>
        <Button variant="secondary" size="sm" icon="user-plus" onClick={() => setDlg({ kind: 'add' })}>Add user</Button>
      </div>
      <div className="hint" style={{ padding: '0 18px 10px' }}>
        Each person signs in with their own login and sees only their own money — you manage logins here, you can&apos;t open their data.
        There is no sign-up page: people get a login only when you add them.
      </div>
      {msg && <div className="form-error" role="alert" style={{ margin: '0 18px 10px' }}>{msg}</div>}
      <div className="tbl-wrap" style={{ padding: '0 6px 8px' }}>
        <table className="tbl" style={{ fontSize: 13 }}>
          <thead>
            <tr><th>User</th><th>Status</th><th className="hide-sm">Last sign-in</th><th className="hide-sm">Added</th></tr>
          </thead>
          <tbody>
            {(users.data ?? []).map((u) => {
              const [tone, label] = statusOf(u);
              const self = u.username === me;
              return (
                <tr key={u.id}>
                  <td>
                    <b>{u.display_name || u.username}</b>
                    {u.is_admin && <span className="badge brand" style={{ marginLeft: 6 }}>Admin</span>}
                    {self && <span className="muted"> (you)</span>}
                    {u.display_name && <div className="muted" style={{ fontSize: 12 }}>{u.username}</div>}
                    {!self && (
                      <div style={{ display: 'flex', gap: 2, flexWrap: 'wrap', margin: '6px 0 0 -8px' }}>
                        <Button variant="ghost" size="sm" icon="key-round" onClick={() => resetPassword(u)} disabled={busy === u.id}>Reset password</Button>
                        <Button variant="ghost" size="sm" icon={u.is_admin ? 'shield-off' : 'shield'} onClick={() => patch(u, { is_admin: !u.is_admin })} disabled={busy === u.id}>
                          {u.is_admin ? 'Remove admin' : 'Make admin'}
                        </Button>
                        <Button variant="ghost" size="sm" icon={u.disabled ? 'user-check' : 'user-x'} onClick={() => patch(u, { disabled: !u.disabled })} disabled={busy === u.id}>
                          {u.disabled ? 'Turn on' : 'Turn off'}
                        </Button>
                        <Button variant="ghost" size="sm" icon="trash-2" onClick={() => setDlg({ kind: 'delete', user: u })} disabled={busy === u.id}>Delete</Button>
                      </div>
                    )}
                  </td>
                  <td><span className={`badge ${tone}`}>{label}</span></td>
                  <td className="hide-sm" style={{ whiteSpace: 'nowrap' }}>{when(u.last_login_at)}</td>
                  <td className="hide-sm" style={{ whiteSpace: 'nowrap' }}>{when(u.created_at)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {dlg?.kind === 'add' && (
        <Dialog onClose={() => setDlg(null)} label="Add user" width={460}>
          <AddBody onAdded={(user, password) => setDlg({ kind: 'password', user, password, added: true })} />
        </Dialog>
      )}
      {dlg?.kind === 'password' && (
        <Dialog onClose={() => setDlg(null)} label="Temporary password" width={460}>
          <PasswordBody user={dlg.user} password={dlg.password} added={dlg.added} />
        </Dialog>
      )}
      {dlg?.kind === 'delete' && (
        <Dialog onClose={() => setDlg(null)} label="Delete user" width={460}>
          <DeleteBody user={dlg.user} />
        </Dialog>
      )}
    </div>
  );
}

function AddBody({ onAdded }: { onAdded: (u: ManagedUser, password: string) => void }) {
  const close = useDialogClose();
  const { bump } = useShell();
  const [username, setUsername] = useState('');
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [isAdmin, setIsAdmin] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const r = await api<{ user: ManagedUser; temporary_password: string }>('/users', {
        method: 'POST',
        body: { username: username.trim(), display_name: name.trim() || null, password: password || null, is_admin: isAdmin },
      });
      bump();
      onAdded(r.user, r.temporary_password);
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };
  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead title="Add user" sub="They get their own, empty MoneyMap" />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        <div className="field">
          <label htmlFor="nu-user">Username</label>
          <input id="nu-user" className="inp" value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus autoComplete="off" pattern="[A-Za-z0-9._@\-]+" title="Letters, numbers and . _ @ - (no spaces)" />
          <div className="hint">What they type to sign in. Letters, numbers and . _ @ - (no spaces).</div>
        </div>
        <div className="field">
          <label htmlFor="nu-name">Name <span className="muted" style={{ fontWeight: 400 }}>(optional)</span></label>
          <input id="nu-name" className="inp" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Priya" />
        </div>
        <div className="field">
          <label htmlFor="nu-pw">Temporary password <span className="muted" style={{ fontWeight: 400 }}>(optional)</span></label>
          <input id="nu-pw" className="inp" type="text" value={password} onChange={(e) => setPassword(e.target.value)} minLength={8} autoComplete="off" placeholder="Leave blank — MoneyMap makes one" />
          <div className="hint">They choose their own password the first time they sign in.</div>
        </div>
        <label className="chk" style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13.5 }}>
          <input type="checkbox" checked={isAdmin} onChange={(e) => setIsAdmin(e.target.checked)} />
          Admin — can add and manage users too (still can&apos;t see others&apos; money)
        </label>
      </div>
      <div className="drawer-foot">
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        <Button variant="primary" type="submit" disabled={saving}>{saving ? 'Adding…' : 'Add user'}</Button>
      </div>
    </form>
  );
}

function PasswordBody({ user, password, added }: { user: ManagedUser; password: string; added: boolean }) {
  const close = useDialogClose();
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(password);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };
  return (
    <>
      <DrawerHead title={added ? 'User added' : 'Password reset'} sub={user.display_name || user.username} />
      <div className="drawer-body">
        <p style={{ marginTop: 0, fontSize: 13.5 }}>
          Give <b>{user.username}</b> this temporary password. It is shown only now. When they sign in, MoneyMap asks them to choose their own.
        </p>
        <div className="card card-pad" style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          <span className="t-mono" style={{ fontSize: 18, letterSpacing: 1, flex: 1, userSelect: 'all' }}>{password}</span>
          <Button variant="secondary" size="sm" icon={copied ? 'check' : 'copy'} onClick={copy}>{copied ? 'Copied' : 'Copy'}</Button>
        </div>
        <div className="note info">
          <Icon name="info" size={15} />
          <span>Username: <b>{user.username}</b>. Send the password a safe way (in person or a private message).</span>
        </div>
      </div>
      <div className="drawer-foot">
        <span className="spacer" />
        <Button variant="primary" onClick={close}>Done</Button>
      </div>
    </>
  );
}

function DeleteBody({ user }: { user: ManagedUser }) {
  const close = useDialogClose();
  const { bump } = useShell();
  const [word, setWord] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api(`/users/${user.id}/delete`, { method: 'POST', body: { confirm: word } });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };
  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead title="Delete user" sub={user.display_name || user.username} />
      <div className="drawer-body">
        {error && <div className="form-error" role="alert">{error}</div>}
        <div className="note warn" style={{ marginBottom: 14 }}>
          <Icon name="triangle-alert" size={15} />
          <span>
            Their login is removed and they can&apos;t sign in. Their data isn&apos;t erased: it moves to <span className="t-mono">deleted-users/</span> in the
            data volume, where you can restore or remove it by hand. To only stop them signing in, use <b>Turn off</b> instead.
          </span>
        </div>
        <div className="field">
          <label htmlFor="du-word">Type <b>{user.username}</b> to confirm</label>
          <input id="du-word" className="inp" value={word} onChange={(e) => setWord(e.target.value)} autoComplete="off" required />
        </div>
      </div>
      <div className="drawer-foot">
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>Cancel</Button>
        <Button variant="primary" type="submit" className="btn-danger" disabled={saving || word.trim() !== user.username}>
          {saving ? 'Deleting…' : 'Delete user'}
        </Button>
      </div>
    </form>
  );
}
