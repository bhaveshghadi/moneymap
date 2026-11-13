'use client';
import { useState, type FormEvent } from 'react';
import { api } from '../lib/api';
import { useShell } from '../contexts/ShellCtx';
import { Button } from '../primitives/Button';
import { SectionCard } from '../primitives/SectionCard';
import { Icon } from '../primitives/Icon';

type Mode = 'data' | 'everything';

const MODES: Record<Mode, { title: string; button: string; deletes: string[]; keeps: string[] }> = {
  data: {
    title: 'Reset data',
    button: 'Reset data…',
    deletes: [
      'All transactions',
      'Accounts, budgets, payees and payers',
      'Tags',
      'Your categories (the starter list comes back)',
    ],
    keeps: ['Your login and settings'],
  },
  everything: {
    title: 'Reset everything',
    button: 'Reset everything…',
    deletes: ['Everything in “Reset data”', 'Your login and settings — you set up a new login afterwards'],
    keeps: [],
  },
};

interface ResetOut {
  mode: Mode;
  backup_file: string | null;
  signed_out: boolean;
}

export function ResetCard() {
  const { bump } = useShell();
  const [mode, setMode] = useState<Mode | null>(null);
  const [password, setPassword] = useState('');
  const [word, setWord] = useState('');
  const [backup, setBackup] = useState(true);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const open = (m: Mode) => {
    setMode(m);
    setPassword('');
    setWord('');
    setBackup(true);
    setMsg(null);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!mode) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await api<ResetOut>('/reset', { method: 'POST', body: { mode, password, confirm: word, backup } });
      if (r.signed_out) {
        window.location.href = '/login';
        return;
      }
      setMode(null);
      setMsg({
        ok: true,
        text: `Data reset.${r.backup_file ? ` A copy of the old data was saved as backups/${r.backup_file} in the data volume.` : ''}`,
      });
      bump();
    } catch (err) {
      setMsg({ ok: false, text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const m = mode ? MODES[mode] : null;

  return (
    <SectionCard title="Reset" pad>
      {msg && (
        <div className={msg.ok ? 'note privacy' : 'form-error'} role="status" style={{ marginBottom: 14 }}>
          {msg.ok && <Icon name="check" size={15} />} {msg.text}
        </div>
      )}
      {!m ? (
        <div className="reset-options">
          {(Object.keys(MODES) as Mode[]).map((k) => (
            <div key={k} className="reset-option">
              <div>
                <b>{MODES[k].title}</b>
                <p className="muted">
                  {k === 'data'
                    ? 'Start your books again; keep your login.'
                    : 'Back to a fresh install, including your login.'}
                </p>
              </div>
              <Button variant="secondary" icon="rotate-ccw" onClick={() => open(k)}>
                {MODES[k].button}
              </Button>
            </div>
          ))}
        </div>
      ) : (
        <form onSubmit={submit}>
          <div className="note warn" style={{ marginBottom: 14, flexDirection: 'column', alignItems: 'stretch', gap: 8 }}>
            <b>{m.title}: this deletes</b>
            <ul className="reset-list">
              {m.deletes.map((d) => <li key={d}>{d}</li>)}
            </ul>
            {m.keeps.length > 0 && (
              <>
                <b>Kept</b>
                <ul className="reset-list">
                  {m.keeps.map((d) => <li key={d}>{d}</li>)}
                </ul>
              </>
            )}
          </div>
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13, marginBottom: 14 }}>
            <input type="checkbox" checked={backup} onChange={(e) => setBackup(e.target.checked)} />
            Save a backup copy of the database first (in the data volume, under <span className="t-mono">backups/</span>)
          </label>
          <div className="row2">
            <div className="field">
              <label htmlFor="rs-pw">Your password</label>
              <input id="rs-pw" type="password" className="inp" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </div>
            <div className="field">
              <label htmlFor="rs-word">Type RESET to confirm</label>
              <input id="rs-word" className="inp" autoComplete="off" value={word} onChange={(e) => setWord(e.target.value)} required />
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <Button variant="secondary" onClick={() => setMode(null)} disabled={busy}>Cancel</Button>
            <Button variant="primary" className="btn-danger" type="submit" icon="trash-2" disabled={busy || word.trim() !== 'RESET' || !password}>
              {mode === 'everything' ? 'Reset everything' : 'Reset data'}
            </Button>
          </div>
        </form>
      )}
    </SectionCard>
  );
}
