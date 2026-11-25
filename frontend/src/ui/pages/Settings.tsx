'use client';
import { useState, type FormEvent } from 'react';
import { api } from '../lib/api';
import { useApi, useShell } from '../contexts/ShellCtx';
import { Button } from '../primitives/Button';
import { SectionCard } from '../primitives/SectionCard';
import { Icon } from '../primitives/Icon';
import { ResetCard } from '../shared/ResetCard';
import { GmailCard } from '../shared/GmailCard';
import { useTheme, type ThemeChoice } from '../lib/theme';
import { PageHelp } from '../shared/PageHelp';

export function SettingsPage() {
  const { username } = useShell();
  const health = useApi<{ status: string; version: string }>('/health');
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const changePassword = async (e: FormEvent) => {
    e.preventDefault();
    if (next !== confirm) return setMsg({ ok: false, text: 'New passwords do not match' });
    setBusy(true);
    try {
      await api('/auth/password', { method: 'POST', body: { current_password: current, new_password: next } });
      setMsg({ ok: true, text: 'Password changed. Other sessions were signed out.' });
      setCurrent('');
      setNext('');
      setConfirm('');
    } catch (err) {
      setMsg({ ok: false, text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const logout = async () => {
    await api('/auth/logout', { method: 'POST' }).catch(() => {});
    window.location.href = '/login';
  };

  return (
    <div className="content-wrap fade-in">
      <div className="page-head">
        <div>
          <h1>Settings <PageHelp id="settings" /></h1>
          <p>Signed in as {username}.</p>
        </div>
        <div className="actions">
          <Button variant="secondary" icon="log-out" onClick={logout}>Sign out</Button>
        </div>
      </div>

      <div style={{ marginBottom: 18 }}>
        <GmailCard />
      </div>

      <div className="grid-2e">
        <SectionCard title="Change password" pad>
          <form onSubmit={changePassword}>
            {msg && (
              <div className={msg.ok ? 'note privacy' : 'form-error'} role="status" style={{ marginBottom: 14 }}>
                {msg.text}
              </div>
            )}
            <div className="field">
              <label htmlFor="pw-cur">Current password</label>
              <input id="pw-cur" type="password" className="inp" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
            </div>
            <div className="field">
              <label htmlFor="pw-new">New password</label>
              <input id="pw-new" type="password" className="inp" autoComplete="new-password" minLength={8} value={next} onChange={(e) => setNext(e.target.value)} required />
              <div className="hint">At least 8 characters.</div>
            </div>
            <div className="field">
              <label htmlFor="pw-conf">Confirm new password</label>
              <input id="pw-conf" type="password" className="inp" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
            </div>
            <Button variant="primary" type="submit" disabled={busy}>Change password</Button>
          </form>
        </SectionCard>

        <div className="stack">
          <AppearanceCard />
          <SectionCard title="About" pad>
            <div className="kv"><span className="k">App</span><span className="v">MoneyMap {health.data?.version ?? '…'}</span></div>
            <div className="kv"><span className="k">Currency</span><span className="v">INR (₹)</span></div>
            <div className="kv"><span className="k">Data</span><span className="v">SQLite in the <span className="t-mono">moneymap_data</span> volume</span></div>
            <div className="kv">
              <span className="k">API docs</span>
              <span className="v"><a href="/api/docs" target="_blank" rel="noreferrer">/api/docs</a></span>
            </div>
          </SectionCard>
          <div className="note info">
            <Icon name="info" size={15} />
            <span>
              Forgot your password? Run <span className="t-mono">docker exec -it moneymap python -m app.cli reset-password {username ?? '<user>'}</span>
            </span>
          </div>
        </div>
      </div>

      <div style={{ marginTop: 18 }}>
        <ResetCard />
      </div>
    </div>
  );
}

const THEMES: { value: ThemeChoice; label: string; icon: string }[] = [
  { value: 'light', label: 'Light', icon: 'sun' },
  { value: 'dark', label: 'Dark', icon: 'moon' },
  { value: 'system', label: 'Match system', icon: 'monitor' },
];

function AppearanceCard() {
  const [theme, setTheme] = useTheme();
  return (
    <SectionCard title="Appearance" pad>
      <div className="seg" role="radiogroup" aria-label="Theme">
        {THEMES.map((t) => (
          <button key={t.value} type="button" role="radio" aria-checked={theme === t.value} className={theme === t.value ? 'on' : ''} onClick={() => setTheme(t.value)}>
            <Icon name={t.icon} size={14} /> {t.label}
          </button>
        ))}
      </div>
      <div className="hint" style={{ marginTop: 10 }}>
        {theme === 'system' ? 'Follows your device: dark when it is in dark mode.' : 'Saved on this device only.'}
      </div>
    </SectionCard>
  );
}
