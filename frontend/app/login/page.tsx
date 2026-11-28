'use client';
import { useEffect, useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/ui/lib/api';
import type { AuthStatus } from '@/ui/lib/types';
import { Icon } from '@/ui/primitives/Icon';

export default function LoginPage() {
  const router = useRouter();
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<AuthStatus>('/auth/status')
      .then((s) => (s.authenticated ? router.replace('/') : setStatus(s)))
      .catch(() => setError('Cannot reach the server. Is the backend running?'));
  }, [router]);

  const setup = status?.setup_required ?? false;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (setup && password !== confirm) return setError('Passwords do not match');
    setBusy(true);
    try {
      await api(setup ? '/auth/setup' : '/auth/login', { method: 'POST', body: { username, password } });
      router.replace(setup ? '/welcome' : '/'); // a new install: the setup page first
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="onb">
      <form className="onb-card fade-in" onSubmit={submit}>
        <div className="onb-logo">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img className="logo-light" src="/assets/logo-wordmark.svg" alt="MoneyMap" style={{ height: 34 }} />
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img className="logo-dark" src="/assets/logo-wordmark-dark.svg" alt="MoneyMap" style={{ height: 34 }} />
        </div>
        <h2>{setup ? 'Set up MoneyMap' : 'Welcome back'}</h2>
        <p className="lead">
          {setup
            ? 'Create the admin login. You can add other people later in Settings → Users; each person sees only their own money.'
            : 'Sign in to your self-hosted expense tracker.'}
        </p>
        {error && <div className="form-error" role="alert">{error}</div>}
        <div className="field">
          <label htmlFor="u">Username</label>
          <input id="u" className="inp" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
        </div>
        <div className="field">
          <label htmlFor="p">Password</label>
          <input
            id="p"
            type="password"
            className="inp"
            autoComplete={setup ? 'new-password' : 'current-password'}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={setup ? 8 : undefined}
            required
          />
          {setup && <div className="hint">At least 8 characters.</div>}
        </div>
        {setup && (
          <div className="field">
            <label htmlFor="c">Confirm password</label>
            <input id="c" type="password" className="inp" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
          </div>
        )}
        <button className="btn btn-primary btn-lg" type="submit" disabled={busy || !status} style={{ width: '100%', marginTop: 6 }}>
          {busy ? 'Please wait…' : setup ? 'Create admin login' : 'Sign in'}
        </button>
        <div className="onb-note">
          <Icon name="shield-check" size={14} color="var(--mint-600)" />
          Self-hosted — your data stays on your server
        </div>
      </form>
    </div>
  );
}
