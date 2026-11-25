'use client';
import { useEffect, useMemo, useState } from 'react';
import { usePathname, useSearchParams } from 'next/navigation';
import { api, qs, replaceQuery } from '../lib/api';
import { useApi, useShell } from '../contexts/ShellCtx';
import { useTxn } from '../contexts/TxnCtx';
import type { Account, Bill, BudgetMonth, Category, Tag, Txn, TxnPage } from '../lib/types';
import { fmtDayHead, rs } from '../lib/format';
import { Money } from '../primitives/Money';
import { Button } from '../primitives/Button';
import { Skeleton } from '../primitives/Skeleton';
import { EmptyState } from '../primitives/EmptyState';
import { ErrorState } from '../primitives/ErrorState';
import { Icon } from '../primitives/Icon';
import { TxnRow } from '../shared/TxnRow';
import { CategoryOptions } from '../shared/CategoryOptions';
import { PageHelp } from '../shared/PageHelp';

const PAGE = 50;
const TYPES = [
  { value: '', label: 'All' },
  { value: 'withdrawal', label: 'Expenses' },
  { value: 'deposit', label: 'Income' },
  { value: 'transfer', label: 'Transfers' },
];

export function TransactionsPage() {
  const pathname = usePathname();
  const sp = useSearchParams();
  const { version, bump } = useShell();
  const { openTxn, newTxn } = useTxn();

  // The URL is the filter state, so every view is deep-linkable.
  const filters = {
    type: sp.get('type') ?? '',
    account: sp.get('account') ?? '',
    category: sp.get('category') ?? '',
    uncategorised: sp.get('uncategorised') ?? '',
    essential: sp.get('essential') ?? '', // '1' essential, '0' non-essential spending
    budget: sp.get('budget') ?? '',
    no_budget: sp.get('no_budget') ?? '',
    bill: sp.get('bill') ?? '',
    loan: sp.get('loan') ?? '', // a loan's EMIs (loan id)
    tag: sp.get('tag') ?? '',
    from: sp.get('from') ?? '',
    to: sp.get('to') ?? '',
    q: sp.get('q') ?? '',
  };
  const setFilter = (patch: Partial<typeof filters>) => {
    const next = { ...filters, ...patch };
    replaceQuery(pathname, qs(next));
  };

  // The search box follows the URL's ?q= when it changes from outside (a link,
  // Clear filters); typing updates the URL after a short pause.
  const [text, setText] = useState(filters.q);
  const [seenQ, setSeenQ] = useState(filters.q);
  if (filters.q !== seenQ) {
    setSeenQ(filters.q);
    setText(filters.q);
  }
  useEffect(() => {
    if (text === filters.q) return;
    const t = setTimeout(() => setFilter({ q: text }), 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);

  const accounts = useApi<Account[]>('/accounts');
  const categories = useApi<Category[]>('/categories');
  const tags = useApi<Tag[]>('/tags');
  const budgets = useApi<BudgetMonth>('/budgets');
  const bills = useApi<Bill[]>('/bills');

  const query = qs({
    type: filters.type,
    account_id: filters.account,
    category_id: filters.category,
    uncategorised: filters.uncategorised ? true : undefined,
    essential: filters.essential === '1' ? true : filters.essential === '0' ? false : undefined,
    budget_id: filters.budget,
    no_budget: filters.no_budget ? true : undefined,
    bill_id: filters.bill,
    loan_id: filters.loan,
    tag: filters.tag,
    date_from: filters.from,
    date_to: filters.to,
    q: filters.q,
  });

  // The loaded list remembers which filters (+ data version) it belongs to; when
  // they change, the stale list is hidden (skeleton) until the new one arrives.
  const [loadingMore, setLoadingMore] = useState(false);
  const [nonce, setNonce] = useState(0);
  const key = `${query}#${version}#${nonce}`;
  const [loaded, setLoaded] = useState<{ key: string; page: TxnPage | null; error: string | null }>({
    key: '',
    page: null,
    error: null,
  });
  const page = loaded.key === key ? loaded.page : null;
  const error = loaded.key === key ? loaded.error : null;

  useEffect(() => {
    let cancelled = false;
    api<TxnPage>(`/transactions${query}${query ? '&' : '?'}limit=${PAGE}`)
      .then((p) => !cancelled && setLoaded({ key, page: p, error: null }))
      .catch((e: Error) => !cancelled && setLoaded({ key, page: null, error: e.message }));
    return () => {
      cancelled = true;
    };
  }, [query, key]);

  const loadMore = async () => {
    if (!page) return;
    setLoadingMore(true);
    try {
      const more = await api<TxnPage>(`/transactions${query}${query ? '&' : '?'}limit=${PAGE}&offset=${page.items.length}`);
      setLoaded((prev) =>
        prev.key === key && prev.page ? { ...prev, page: { ...more, items: [...prev.page.items, ...more.items] } } : prev,
      );
    } catch (e) {
      setLoaded((prev) => (prev.key === key ? { ...prev, page: null, error: (e as Error).message } : prev));
    } finally {
      setLoadingMore(false);
    }
  };

  // Select mode: tick rows, then delete them together. The selection is cleared
  // whenever the list changes (filters, a save elsewhere, after deleting).
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(() => new Set());
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [selError, setSelError] = useState<string | null>(null);
  const [selKey, setSelKey] = useState(key);
  if (selKey !== key) {
    setSelKey(key);
    setSelected(new Set());
    setConfirmDelete(false);
  }
  const toggle = (id: number) => {
    setConfirmDelete(false);
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };
  const loadedIds = (page?.items ?? []).map((t) => t.id);
  const allSelected = loadedIds.length > 0 && loadedIds.every((id) => selected.has(id));
  const stopSelecting = () => {
    setSelecting(false);
    setSelected(new Set());
    setConfirmDelete(false);
    setSelError(null);
  };
  const deleteSelected = async () => {
    if (!confirmDelete) return setConfirmDelete(true);
    setDeleting(true);
    setSelError(null);
    try {
      await api('/transactions/delete', { method: 'POST', body: { ids: [...selected] } });
      stopSelecting();
      bump();
    } catch (e) {
      setSelError((e as Error).message);
      setConfirmDelete(false);
    } finally {
      setDeleting(false);
    }
  };

  const groups = useMemo(() => {
    const out: { date: string; items: Txn[] }[] = [];
    for (const t of page?.items ?? []) {
      const last = out[out.length - 1];
      if (last && last.date === t.date) last.items.push(t);
      else out.push({ date: t.date, items: [t] });
    }
    return out;
  }, [page]);


  const ownAccounts = (accounts.data ?? []).filter((a) => ['asset', 'cash', 'credit_card', 'emi_plan', 'loan'].includes(a.type));
  const activeFilters = Object.entries(filters).some(([k, v]) => v && k !== 'type');
  const selectedAccount = accounts.data?.find((a) => String(a.id) === filters.account);

  return (
    <div className="content-wrap fade-in">
      <div className="page-head">
        <div>
          <h1>{selectedAccount ? selectedAccount.name : 'Transactions'} <PageHelp id="transactions" /></h1>
          <p>
            {page
              ? `${page.total.toLocaleString('en-IN')} transaction${page.total === 1 ? '' : 's'}`
              : 'Loading…'}
            {page && (page.sum_in > 0 || page.sum_out > 0) && (
              <>
                {' · in '}
                <Money amount={rs(page.sum_in)} pos interactive={false} />
                {' · out '}
                <Money amount={rs(page.sum_out)} interactive={false} />
              </>
            )}
          </p>
        </div>
        <div className="actions">
          {page && page.items.length > 0 && (
            <Button variant="secondary" icon={selecting ? 'x' : 'list-checks'} onClick={() => (selecting ? stopSelecting() : setSelecting(true))}>
              {selecting ? 'Done' : 'Select'}
            </Button>
          )}
          <Button
            variant="primary"
            icon="plus"
            onClick={() =>
              newTxn(
                selectedAccount && ['asset', 'cash', 'credit_card'].includes(selectedAccount.type)
                  ? { source_id: selectedAccount.id }
                  : undefined,
              )
            }
          >
            Add transaction
          </Button>
        </div>
      </div>

      <div className="filters">
        <div className="chips" role="radiogroup" aria-label="Transaction type">
          {TYPES.map((t) => (
            <button
              key={t.value}
              type="button"
              role="radio"
              aria-checked={filters.type === t.value}
              className={`chip ${filters.type === t.value ? 'on' : ''}`}
              onClick={() => setFilter({ type: t.value })}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>
      <div className="filters">
        <input className="inp grow" placeholder="Search description or notes…" value={text} onChange={(e) => setText(e.target.value)} aria-label="Search" />
        <select className="inp" aria-label="Account" value={filters.account} onChange={(e) => setFilter({ account: e.target.value })}>
          <option value="">All accounts</option>
          <optgroup label="Your accounts">
            {ownAccounts.map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </optgroup>
        </select>
        <select
          className="inp"
          aria-label="Category"
          value={
            filters.uncategorised
              ? 'none'
              : filters.essential === '1'
                ? 'essential'
                : filters.essential === '0'
                  ? 'non-essential'
                  : filters.category
          }
          onChange={(e) => {
            const v = e.target.value;
            if (v === 'none') setFilter({ category: '', uncategorised: '1', essential: '' });
            else if (v === 'essential') setFilter({ category: '', uncategorised: '', essential: '1' });
            else if (v === 'non-essential') setFilter({ category: '', uncategorised: '', essential: '0' });
            else setFilter({ category: v, uncategorised: '', essential: '' });
          }}
        >
          <option value="">All categories</option>
          <option value="none">Uncategorised</option>
          <option value="essential">Essential spending</option>
          <option value="non-essential">Non-essential spending</option>
          <CategoryOptions categories={categories.data ?? []} />
        </select>
        <select
          className="inp"
          aria-label="Budget"
          value={filters.no_budget ? 'none' : filters.budget}
          onChange={(e) =>
            e.target.value === 'none'
              ? setFilter({ budget: '', no_budget: '1' })
              : setFilter({ budget: e.target.value, no_budget: '' })
          }
        >
          <option value="">All budgets</option>
          <option value="none">No budget</option>
          {(budgets.data?.budgets ?? []).map((b) => (
            <option key={b.id} value={b.id}>
              {b.name}
            </option>
          ))}
        </select>
        <select className="inp" aria-label="Tag" value={filters.tag} onChange={(e) => setFilter({ tag: e.target.value })}>
          <option value="">All tags</option>
          {filters.tag && !(tags.data ?? []).some((t) => t.name.toLowerCase() === filters.tag.toLowerCase()) && (
            <option value={filters.tag}>#{filters.tag}</option>
          )}
          {(tags.data ?? []).map((t) => (
            <option key={t.id} value={t.name}>
              #{t.name}
            </option>
          ))}
        </select>
        <input className="inp" type="date" aria-label="From date" value={filters.from} onChange={(e) => setFilter({ from: e.target.value })} />
        <input className="inp" type="date" aria-label="To date" value={filters.to} onChange={(e) => setFilter({ to: e.target.value })} />
        {filters.loan && (
          <span className="badge coral" style={{ fontSize: 12.5, padding: '6px 10px' }}>
            Loan EMIs
            <button type="button" aria-label="Remove loan filter" onClick={() => setFilter({ loan: '' })} style={{ all: 'unset', cursor: 'pointer', marginLeft: 6 }}>
              ×
            </button>
          </span>
        )}
        {filters.bill && (
          <span className="badge coral" style={{ fontSize: 12.5, padding: '6px 10px' }}>
            Bill · {bills.data?.find((b) => String(b.id) === filters.bill)?.name ?? filters.bill}
            <button
              type="button"
              aria-label="Remove bill filter"
              onClick={() => setFilter({ bill: '' })}
              style={{ border: 0, background: 'none', color: 'inherit', padding: 0, lineHeight: 0 }}
            >
              <Icon name="x" size={13} />
            </button>
          </span>
        )}
        {activeFilters && (
          <Button variant="ghost" size="sm" icon="x" onClick={() => replaceQuery(pathname, '')}>
            Clear filters
          </Button>
        )}
      </div>

      {selecting && page && (
        <div className="card card-pad select-bar" role="region" aria-label="Selected transactions">
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={allSelected}
              onChange={() => {
                setConfirmDelete(false);
                setSelected(allSelected ? new Set() : new Set(loadedIds));
              }}
            />
            {allSelected ? 'Unselect all' : `Select all ${loadedIds.length}${page.total > loadedIds.length ? ' shown' : ''}`}
          </label>
          <span className="muted" style={{ fontSize: 13.5 }} aria-live="polite">
            {selected.size} selected
          </span>
          <span className="spacer" style={{ flex: 1 }} />
          {selError && <span className="form-error" role="alert" style={{ margin: 0 }}>{selError}</span>}
          {selected.size > 0 && (
            <Button variant="ghost" size="sm" onClick={() => { setSelected(new Set()); setConfirmDelete(false); }}>
              Clear
            </Button>
          )}
          <Button
            variant={confirmDelete ? 'primary' : 'secondary'}
            size="sm"
            icon="trash-2"
            onClick={deleteSelected}
            disabled={selected.size === 0 || deleting}
            className={confirmDelete ? 'btn-danger' : ''}
          >
            {deleting ? 'Deleting…' : confirmDelete ? `Confirm: delete ${selected.size}` : `Delete selected (${selected.size})`}
          </Button>
        </div>
      )}

      <div className="card">
        <div className="card-list" style={{ paddingTop: 10 }}>
          {error ? (
            <ErrorState message={error} onRetry={() => setNonce((n) => n + 1)} />
          ) : !page ? (
            <div className="stack" style={{ gap: 8, padding: '6px 0 10px' }}>
              <Skeleton variant="row" count={6} />
            </div>
          ) : page.items.length === 0 ? (
            activeFilters || filters.type ? (
              <EmptyState icon="search-x" title="Nothing matches these filters" body="Try a wider date range or clear the filters." />
            ) : (
              <EmptyState
                icon="arrow-left-right"
                title="No transactions yet"
                body="Record expenses, income and transfers between your accounts."
                action={{ label: 'Add transaction', onClick: () => newTxn() }}
              />
            )
          ) : (
            <>
              {groups.map((g) => (
                <div key={g.date}>
                  <div className="day-head">{fmtDayHead(g.date)}</div>
                  {g.items.map((t) =>
                    selecting ? (
                      <div key={t.id} className={`txn-select ${selected.has(t.id) ? 'on' : ''}`}>
                        <input type="checkbox" aria-label={`Select ${t.description}`} checked={selected.has(t.id)} onChange={() => toggle(t.id)} />
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <TxnRow t={t} onClick={() => toggle(t.id)} showDate={false} />
                        </div>
                      </div>
                    ) : (
                      <TxnRow key={t.id} t={t} onClick={() => openTxn(t)} showDate={false} />
                    ),
                  )}
                </div>
              ))}
              {page.items.length < page.total && (
                <div className="load-more">
                  <Button variant="secondary" size="sm" onClick={loadMore} disabled={loadingMore}>
                    {loadingMore ? 'Loading…' : `Load more (${page.total - page.items.length} left)`}
                  </Button>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
