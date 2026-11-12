'use client';
import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { api, qs } from '../lib/api';
import type { Txn, TxnPage } from '../lib/types';
import { counterparty, fmtDate } from '../lib/format';
import { TxnAmount } from '../shared/TxnRow';
import { useMask } from '../contexts/MaskCtx';
import { useShell } from '../contexts/ShellCtx';
import { useTxn } from '../contexts/TxnCtx';
import { Icon } from '../primitives/Icon';

/** Top bar: quick search (words in the description, notes or payee), Add, hide amounts, settings. */
export function Topbar() {
  const { masked, setMasked } = useMask();
  const { username } = useShell();
  const { openTxn, newTxn } = useTxn();
  const router = useRouter();
  const initials = username ? username.slice(0, 2).toUpperCase() : null;

  const [q, setQ] = useState('');
  const [results, setResults] = useState<Txn[] | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [total, setTotal] = useState(0);
  const openSearch = () => {
    setOpen(false);
    router.push(`/transactions${qs({ q: q.trim() })}`);
  };
  const boxRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  // Debounced quick search; Enter opens the Transactions page with the same search.
  useEffect(() => {
    const query = q.trim();
    if (query.length < 2) {
      setResults(null);
      setSearchError(null);
      setOpen(false);
      return;
    }
    const t = setTimeout(async () => {
      try {
        const data = await api<TxnPage>(`/transactions${qs({ q: query, limit: 8 })}`);
        setResults(data.items);
        setTotal(data.total);
        setSearchError(null);
        setOpen(true);
      } catch {
        setResults(null);
        setSearchError('Search failed — try again.');
        setOpen(true);
      }
    }, 250);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener('mousedown', onDown);
    return () => window.removeEventListener('mousedown', onDown);
  }, []);


  return (
    <header className="topbar">
      <div className="search" ref={boxRef} style={{ position: 'relative' }}>
        <Icon name="search" size={16} />
        <input
          ref={inputRef}
          aria-label="Search transactions"
          placeholder="Search transactions…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onFocus={() => (results || searchError) && setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              setOpen(false);
              (e.target as HTMLInputElement).blur();
            }
            if (e.key === 'Enter' && q.trim()) openSearch();
          }}
        />
        {open && (searchError || results) && (
          <div
            className="card"
            style={{
              position: 'absolute',
              top: 'calc(100% + 6px)',
              left: 0,
              right: 0,
              zIndex: 60,
              maxHeight: 380,
              overflowY: 'auto',
              boxShadow: 'var(--shadow-lg)',
            }}
          >
            {searchError ? (
              <div className="muted" style={{ padding: 14, fontSize: 13 }}>{searchError}</div>
            ) : results && results.length === 0 ? (
              <div className="muted" style={{ padding: 14, fontSize: 13 }}>
                No transactions match &ldquo;{q.trim()}&rdquo;.
              </div>
            ) : (
              results!.map((r) => (
                <button
                  key={r.id}
                  type="button"
                  className="txn click rowbtn"
                  style={{ padding: '9px 14px', margin: 0 }}
                  onClick={() => {
                    setOpen(false);
                    openTxn(r);
                  }}
                >
                  <div className="txn-mid" style={{ minWidth: 0 }}>
                    <div className="mer" style={{ fontSize: 13.5 }}>{r.description}</div>
                    <div className="cat" style={{ fontSize: 12 }}>
                      {counterparty(r)}
                      {r.category ? ' · ' + r.category.name : ''}
                    </div>
                  </div>
                  <div style={{ textAlign: 'right', flexShrink: 0 }}>
                    <TxnAmount t={r} size={13} />
                    <div className="muted" style={{ fontSize: 11 }}>{fmtDate(r.date)}</div>
                  </div>
                </button>
              ))
            )}
            {results && results.length > 0 && (
              <button type="button" className="rowbtn" onClick={openSearch} style={{ padding: '10px 14px', borderTop: '1px solid var(--border)', fontSize: 13, fontWeight: 600, color: 'var(--brand)' }}>
                {total > results.length ? `See all ${total.toLocaleString('en-IN')} results` : 'Open in Transactions'} →
              </button>
            )}
          </div>
        )}
      </div>
      <div className="topbar-right">
        <button className="btn btn-primary btn-sm" type="button" onClick={() => newTxn()}>
          <Icon name="plus" size={15} />
          Add
        </button>
        <button
          className={`icon-btn ${masked ? 'on' : ''}`}
          title={masked ? 'Reveal all amounts' : 'Hide all amounts'}
          aria-pressed={masked}
          aria-label={masked ? 'Reveal all amounts' : 'Hide all amounts'}
          onClick={() => setMasked((m) => !m)}
        >
          <Icon name={masked ? 'eye-off' : 'eye'} size={18} />
        </button>
        <div className="ondevice">
          <Icon name="shield-check" size={14} />
          Self-hosted
        </div>
        <button
          type="button"
          className="avatar"
          style={{ border: 0 }}
          title={username ? `${username} — settings` : 'Settings'}
          onClick={() => router.push('/settings')}
        >
          {initials ?? <Icon name="user-round" size={16} />}
        </button>
      </div>
    </header>
  );
}
