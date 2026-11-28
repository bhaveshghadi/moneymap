'use client';
import { useState, type FormEvent } from 'react';
import { api } from '../lib/api';
import type { AuthStatus } from '../lib/types';
import { Icon } from '../primitives/Icon';

/** First sign-in with the temporary password the admin gave: choose your own before anything else. */
export function ChoosePassword({ status, onDone }: { status: AuthStatus; onDone: (s: AuthStatus) => void }) {
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (next !== confirm) return setError('The passwords do not match');
    setBusy(true);
    try {
      await api('/auth/password', { method: 'POST', body: { new_password: next } });
      onDone(await api<AuthStatus>('/auth/status'));
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  const signOut = async () => {
    await api('/auth/logout', { method: 'POST' }).catch(() => {});
    window.location.href = '/login';
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
        <h2>Choose your password</h2>
        <p className="lead">
          Hi {status.display_name || status.username} — you signed in with a temporary password. Choose your own; only you will know it.
        </p>
        {error && <div className="form-error" role="alert">{error}</div>}
        <div className="field">
          <label htmlFor="np">New password</label>
          <input id="np" type="password" className="inp" autoComplete="new-password" minLength={8} value={next} onChange={(e) => setNext(e.target.value)} required autoFocus />
          <div className="hint">At least 8 characters.</div>
        </div>
        <div className="field">
          <label htmlFor="nc">Confirm new password</label>
          <input id="nc" type="password" className="inp" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
        </div>
        <button className="btn btn-primary btn-lg" type="submit" disabled={busy} style={{ width: '100%', marginTop: 6 }}>
          {busy ? 'Please wait…' : 'Save and continue'}
        </button>
        <button type="button" className="btn btn-ghost" onClick={signOut} style={{ width: '100%', marginTop: 8 }}>
          Sign out
        </button>
        <div className="onb-note">
          <Icon name="shield-check" size={14} color="var(--mint-600)" />
          Your money is yours alone — other people on this server can&apos;t see it
        </div>
      </form>
    </div>
  );
}
