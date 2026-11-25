'use client';
import { useEffect, useState } from 'react';
import { usePathname, useSearchParams } from 'next/navigation';
import { replaceQuery } from '../lib/api';
import { useApi } from '../contexts/ShellCtx';
import type { Account, AccountType } from '../lib/types';
import { ACCOUNT_TYPE_ICON, fmtDate, rs } from '../lib/format';
import { Tabs } from '../primitives/Tabs';
import { Button } from '../primitives/Button';
import { Money } from '../primitives/Money';
import { StatCard } from '../primitives/StatCard';
import { Skeleton } from '../primitives/Skeleton';
import { EmptyState } from '../primitives/EmptyState';
import { ErrorState } from '../primitives/ErrorState';
import { CategoryGlyph } from '../primitives/CategoryGlyph';
import { AccountForm } from '../shared/AccountForm';
import { PageHelp } from '../shared/PageHelp';

type TabId = 'own' | 'expense' | 'revenue';

const TABS: { id: TabId; label: string; types: AccountType[]; addAs: AccountType; addLabel: string; empty: string }[] = [
  { id: 'own', label: 'Bank & cash', types: ['asset', 'cash'], addAs: 'asset', addLabel: 'Add bank account', empty: 'Savings and current accounts, wallets and cash you hold.' },
  { id: 'expense', label: 'Expense accounts', types: ['expense'], addAs: 'expense', addLabel: 'Add expense account', empty: 'Merchants and payees. They are created automatically when you record an expense.' },
  { id: 'revenue', label: 'Revenue accounts', types: ['revenue'], addAs: 'revenue', addLabel: 'Add revenue account', empty: 'Employers, clients and other sources of income. Created automatically from income you record.' },
];

export function AccountsPage() {
  const sp = useSearchParams();
  const pathname = usePathname();
  const { data, error, reload } = useApi<Account[]>('/accounts');
  const [tab, setTab] = useState<TabId>('own');
  const [editing, setEditing] = useState<{ account?: Account; type: AccountType } | null>(null);

  // Links into this page: /accounts?tab=expense opens that tab, /accounts?new=asset
  // opens the add form. Applied while rendering, once per new URL (React's
  // "adjust state when a prop changes" pattern) instead of in an effect.
  const search = sp.toString();
  const [seenSearch, setSeenSearch] = useState<string | null>(null);
  if (search !== seenSearch) {
    setSeenSearch(search);
    const t = sp.get('tab');
    if (t && TABS.some((x) => x.id === t)) setTab(t as TabId);
    const n = sp.get('new') as AccountType | null;
    if (n && ['asset', 'cash', 'expense', 'revenue'].includes(n)) {
      setTab(n === 'expense' ? 'expense' : n === 'revenue' ? 'revenue' : 'own');
      setEditing({ type: n });
    }
  }
  // …then drop ?new= from the address bar so a reload doesn't open the form again.
  useEffect(() => {
    if (sp.get('new')) replaceQuery(pathname, '');
  }, [sp, pathname]);

  const current = TABS.find((t) => t.id === tab)!;
  const rows = (data ?? []).filter((a) => current.types.includes(a.type));
  const own = (data ?? []).filter((a) => a.active && (a.type === 'asset' || a.type === 'cash'));
  const assetsTotal = own.reduce((s, a) => s + a.balance, 0);
  const banks = own.filter((a) => a.type === 'asset');
  const cash = own.filter((a) => a.type === 'cash');
  const isBalance = tab === 'own';

  return (
    <div className="content-wrap fade-in">
      <div className="page-head">
        <div>
          <h1>Accounts <PageHelp id="accounts" /></h1>
          <p>Where your money sits, and who you pay or get paid by.</p>
        </div>
        <div className="actions">
          {tab === 'own' && (
            <Button variant="secondary" icon="banknote" onClick={() => setEditing({ type: 'cash' })}>
              Add cash
            </Button>
          )}
          <Button variant="primary" icon="plus" onClick={() => setEditing({ type: current.addAs })}>
            {current.addLabel}
          </Button>
        </div>
      </div>

      {data && (
        <div className="grid-3 stat-grid">
          <StatCard lbl="Net worth" icon="scale" val={<Money amount={rs(assetsTotal)} precise pos={assetsTotal >= 0} sign={assetsTotal < 0} />} sub="Bank and cash today" />
          <StatCard lbl="Bank accounts" icon="landmark" val={<Money amount={rs(banks.reduce((s, a) => s + a.balance, 0))} precise pos />} sub={`${banks.length} active account${banks.length === 1 ? '' : 's'}`} />
          <StatCard lbl="Cash" icon="banknote" val={<Money amount={rs(cash.reduce((s, a) => s + a.balance, 0))} precise pos />} sub={`${cash.length} active wallet${cash.length === 1 ? '' : 's'}`} />
        </div>
      )}

      <Tabs tabs={TABS.map((t) => ({ id: t.id, label: t.label }))} active={tab} onChange={(id) => setTab(id as TabId)} aria-label="Account types" />

      <div className="card">
        {error ? (
          <ErrorState message={error} onRetry={reload} />
        ) : !data ? (
          <div className="card-pad stack" style={{ gap: 8 }}>
            <Skeleton variant="row" count={4} />
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            icon={ACCOUNT_TYPE_ICON[current.addAs].icon}
            title={`No ${current.label.toLowerCase()} yet`}
            body={current.empty}
            action={{ label: current.addLabel, onClick: () => setEditing({ type: current.addAs }) }}
          />
        ) : (
          <div className="tbl-wrap" style={{ padding: '16px 6px 6px' }}>
            <table className="tbl">
              <thead>
                <tr>
                  <th>Name</th>
                  <th className="r">{isBalance ? 'Balance' : tab === 'expense' ? 'Total spent' : 'Total received'}</th>
                  <th className="r hide-sm">Transactions</th>
                  <th className="r hide-sm">Last activity</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => {
                  const g = ACCOUNT_TYPE_ICON[a.type];
                  const value = a.balance;
                  return (
                    <tr key={a.id} className="click" onClick={() => setEditing({ account: a, type: a.type })} style={{ opacity: a.active ? 1 : 0.55 }}>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
                          <CategoryGlyph icon={g.icon} color={g.color} size={32} />
                          <div>
                            <div style={{ fontWeight: 600 }}>
                              {a.name} {!a.active && <span className="badge neutral">Inactive</span>}
                            </div>
                            {a.account_number && <div className="t-mono" style={{ fontSize: 12 }}>{a.account_number}</div>}
                            {a.type === 'cash' && <div className="muted" style={{ fontSize: 12 }}>Cash</div>}
                          </div>
                        </div>
                      </td>
                      <td className="r figure">
                        <Money amount={rs(value)} precise interactive={false} sign={isBalance && value < 0} pos={tab === 'own' && value > 0} />
                      </td>
                      <td className="r t-mono hide-sm">{a.transaction_count}</td>
                      <td className="r muted hide-sm">{a.last_activity ? fmtDate(a.last_activity) : '—'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {editing && <AccountForm key={editing.account?.id ?? editing.type} account={editing.account} type={editing.type} onClose={() => setEditing(null)} />}
    </div>
  );
}
