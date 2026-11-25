'use client';
import { useEffect, useState, type ReactNode } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useApi } from '../contexts/ShellCtx';
import { useTxn } from '../contexts/TxnCtx';
import type { Guide, Overview, SavingsPlan } from '../lib/types';
import { ACCOUNT_TYPE_ICON, ACCOUNT_TYPE_LABEL, currentMonth, dueText, fmtDate, monthLabel, monthRange, rs, shiftMonth } from '../lib/format';
import { qs } from '../lib/api';
import { Money } from '../primitives/Money';
import { StatCard } from '../primitives/StatCard';
import { SectionCard } from '../primitives/SectionCard';
import { RULE_LABEL } from './SavingsPlan';
import { Skeleton } from '../primitives/Skeleton';
import { EmptyState } from '../primitives/EmptyState';
import { ErrorState } from '../primitives/ErrorState';
import { CategoryGlyph, PALETTE } from '../primitives/CategoryGlyph';
import { Icon } from '../primitives/Icon';
import { TxnRow } from '../shared/TxnRow';
import { BillBadge, Progress } from '../shared/Progress';
import { EmergencyBadge, coverText } from '../shared/EmergencyFundCard';
import { CycleBadge } from '../shared/CardForm';
import { KIND_META } from '../shared/InvestmentForm';
import { GainText, dueWhen } from './Investments';
import { PageHelp } from '../shared/PageHelp';

function Row({ href, glyph, title, sub, right }: { href: string; glyph: ReactNode; title: ReactNode; sub: ReactNode; right: ReactNode }) {
  return (
    <Link href={href} className="txn click" style={{ textDecoration: 'none' }}>
      {glyph}
      <div className="txn-mid">
        <div className="mer">{title}</div>
        <div className="cat">{sub}</div>
      </div>
      <div className="amt" style={{ flexShrink: 0 }}>
        {right}
      </div>
    </Link>
  );
}

/** Dashboard: balances right now + how the chosen month is going. */
export function OverviewPage() {
  const [month, setMonth] = useState(currentMonth());
  const { data, error, loading, reload } = useApi<Overview>(`/overview?month=${month}`);
  const plan = useApi<SavingsPlan>(`/savings-plan?month=${month}`);
  const guide = useApi<Guide>('/guide');
  const router = useRouter();
  // first sign-in: open the start-up guide (once per browser session, until it's hidden or finished)
  useEffect(() => {
    if (guide.data?.setup_page) {
      router.replace('/welcome'); // a new install that hasn't finished (or put off) the setup page
      return;
    }
    if (!guide.data?.show_first) return;
    try {
      if (sessionStorage.getItem('mm-guide-opened')) return;
      sessionStorage.setItem('mm-guide-opened', '1');
    } catch {
      return;
    }
    router.replace('/guide');
  }, [guide.data, router]);
  const { openTxn, newTxn } = useTxn();
  const range = monthRange(month);
  const inMonth = { from: range.from, to: range.to };

  const head = (
    <div className="page-head">
      <div>
        <h1>Overview <PageHelp id="overview" /></h1>
        <p>Balances right now, and how {monthLabel(month)} is going.</p>
      </div>
      <div className="actions">
        <div className="month-nav">
          <button className="icon-btn" aria-label="Previous month" onClick={() => setMonth(shiftMonth(month, -1))}>
            <Icon name="chevron-left" size={18} />
          </button>
          <span className="lbl">{monthLabel(month)}</span>
          <button className="icon-btn" aria-label="Next month" onClick={() => setMonth(shiftMonth(month, 1))} disabled={month >= currentMonth()}>
            <Icon name="chevron-right" size={18} />
          </button>
        </div>
      </div>
    </div>
  );

  if (error) {
    return (
      <div className="content-wrap fade-in">
        {head}
        <div className="card">
          <ErrorState message={error} onRetry={reload} />
        </div>
      </div>
    );
  }

  if (!data || (loading && !data)) {
    return (
      <div className="content-wrap">
        {head}
        <div className="grid-4 stat-grid">
          <Skeleton variant="stat" count={4} />
        </div>
        <div className="grid-2">
          <Skeleton variant="block" height={260} count={2} />
        </div>
      </div>
    );
  }

  if (data.accounts.length === 0 && data.transaction_count === 0) {
    return (
      <div className="content-wrap fade-in">
        {head}
        <div className="card">
          <EmptyState
            icon="landmark"
            title="Start by adding an account"
            body="Add your bank accounts and cash with what's in them today. Then record transactions against them."
            action={{ label: 'Add an account', href: '/accounts?new=asset' }}
          />
        </div>
      </div>
    );
  }

  const left = data.income - data.spending;
  const maxCat = Math.max(1, ...data.by_category.map((c) => c.amount));
  const savingsRate = data.income > 0 ? Math.round((left / data.income) * 100) : null;

  return (
    <div className="content-wrap fade-in">
      {head}

      <div className="grid-4 stat-grid">
        <StatCard
          lbl="Net worth"
          icon="scale"
          val={<Money amount={rs(data.net_worth)} precise pos={data.net_worth >= 0} sign={data.net_worth < 0} />}
          fit={rs(Math.abs(data.net_worth)).toLocaleString('en-IN', { minimumFractionDigits: 2 }).length + 2}
          sub={
            data.cards_owed + data.loans_owed > 0 ? (
              <>
                {data.investments_count > 0 ? 'Bank, cash and investments' : 'Bank and cash'} minus{' '}
                <Money amount={rs(data.cards_owed + data.loans_owed)} interactive={false} /> owed on
                {data.cards_owed > 0 && data.loans_owed > 0 ? ' cards and loans' : data.loans_owed > 0 ? ' loans' : ' cards'}
              </>
            ) : data.investments_count > 0 ? (
              'Bank, cash and investments today'
            ) : (
              'Bank and cash today'
            )
          }
        />
        <StatCard
          lbl="Income"
          icon="arrow-down-to-line"
          val={<Money amount={rs(data.income)} compact pos />}
          sub={monthLabel(month)}
        />
        <StatCard
          lbl="Spending"
          icon="arrow-up-from-line"
          val={<Money amount={rs(data.spending)} compact />}
          sub={monthLabel(month)}
        />
        <StatCard
          lbl="Left over"
          icon="piggy-bank"
          val={<Money amount={rs(left)} compact sign pos={left >= 0} />}
          sub={
            savingsRate === null
              ? 'No income this month'
              : left >= 0
                ? `You kept ${savingsRate}% of your income`
                : 'Spent more than earned'
          }
        />
      </div>

      <div className="grid-2" style={{ marginBottom: 16 }}>
        <SectionCard title="Where it went" action={{ label: 'All spending', href: `/transactions${qs({ type: 'withdrawal', ...inMonth })}` }}>
          {data.by_category.length === 0 ? (
            <EmptyState icon="shopping-bag" title={`No spending in ${monthLabel(month)}`} body="Expenses you record will be grouped by category here." />
          ) : (
            data.by_category.map((c) => (
              <Link
                key={c.id ?? 'none'}
                className="catrow"
                style={{ display: 'block', textDecoration: 'none' }}
                href={`/transactions${qs({ type: 'withdrawal', category: c.id ?? undefined, uncategorised: c.id === null ? 1 : undefined, ...inMonth })}`}
              >
                <div className="top">
                  <span className="nm">
                    <CategoryGlyph icon={c.icon} color={c.color} size={26} />
                    {c.name}
                  </span>
                  <span className="fig">
                    <Money amount={rs(c.amount)} interactive={false} />
                    <span className="muted" style={{ fontSize: 11.5, fontWeight: 500, marginLeft: 6 }}>
                      {Math.round((c.amount / Math.max(1, data.spending)) * 100)}%
                    </span>
                  </span>
                </div>
                <div className="track">
                  <i style={{ width: `${(c.amount / maxCat) * 100}%`, background: PALETTE[c.color] ?? PALETTE.indigo }} />
                </div>
              </Link>
            ))
          )}
        </SectionCard>

        <SectionCard title="Accounts" action={{ label: 'Manage', href: '/accounts' }}>
          {data.accounts.length === 0 ? (
            <EmptyState icon="landmark" title="No accounts" action={{ label: 'Add an account', href: '/accounts?new=asset' }} />
          ) : (
            data.accounts.map((a) => {
              const g = ACCOUNT_TYPE_ICON[a.type];
              return (
                <Row
                  key={a.id}
                  href={`/transactions?account=${a.id}`}
                  glyph={<CategoryGlyph icon={g.icon} color={g.color} size={34} />}
                  title={a.name}
                  sub={ACCOUNT_TYPE_LABEL[a.type]}
                  right={<Money amount={rs(a.balance)} precise interactive={false} sign={a.balance < 0} />}
                />
              );
            })
          )}
        </SectionCard>
      </div>

      {plan.data && plan.data.income_used > 0 && <SavingsCard p={plan.data} />}

      {data.emergency && (
        <div style={{ marginBottom: 16 }}>
          <SectionCard title="Emergency fund" action={{ label: 'Open', href: '/piggy-banks' }}>
            <div className="catrow" style={{ display: 'block' }}>
              <div className="top">
                <span className="nm">
                  {coverText(data.emergency.covered_months, data.emergency.months_cover)}{' '}
                  <EmergencyBadge status={data.emergency.status} />
                </span>
                <span style={{ fontSize: 13 }}>
                  <span className="fig">
                    <Money amount={rs(data.emergency.saved)} interactive={false} />
                  </span>
                  <span className="muted">
                    {' '}
                    of <Money amount={rs(data.emergency.target)} interactive={false} />
                  </span>
                </span>
              </div>
              <Progress value={data.emergency.saved} max={data.emergency.target} savings />
            </div>
          </SectionCard>
        </div>
      )}

      {data.investments_count > 0 && (
        <div style={{ marginBottom: 16 }}>
          <SectionCard title="Investments" action={{ label: 'Open', href: '/investments' }}>
            <div className="catrow" style={{ display: 'block' }}>
              <div className="top">
                <span className="nm">
                  <span className="fig"><Money amount={rs(data.investments_value)} interactive={false} /></span>
                  <span className="muted" style={{ fontSize: 13, fontWeight: 500 }}>
                    value today · {data.investments_count} investment{data.investments_count === 1 ? '' : 's'}
                  </span>
                </span>
                <span style={{ fontSize: 13 }}>
                  <GainText
                    gain={data.investments_value - data.investments_invested}
                    pct={data.investments_invested > 0 ? ((data.investments_value - data.investments_invested) * 100) / data.investments_invested : null}
                  />
                </span>
              </div>
            </div>
            {data.investment_dues.map((d) => (
              <Row
                key={`${d.account_id}-${d.what}-${d.date}`}
                href={`/investments/${d.account_id}`}
                glyph={<CategoryGlyph icon={KIND_META[d.kind].icon} color={d.overdue ? 'red' : KIND_META[d.kind].color} size={34} />}
                title={d.name}
                sub={`${dueWhen(d)} · ${fmtDate(d.date)}`}
                right={<Money amount={rs(d.amount)} interactive={false} />}
              />
            ))}
          </SectionCard>
        </div>
      )}

      {data.loan_dues.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <SectionCard title="Loan EMIs due" action={{ label: 'All loans', href: '/loans' }}>
            {data.loan_dues.map((d) => (
              <Row
                key={d.loan_id}
                href={`/loans/${d.loan_id}`}
                glyph={<CategoryGlyph icon="hand-coins" color={d.overdue ? 'red' : 'coral'} size={34} />}
                title={d.name}
                sub={`EMI ${d.n} of ${d.tenure} · ${fmtDate(d.date)} · ${dueText(d.date)}`}
                right={
                  <span style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 3 }}>
                    <Money amount={rs(d.amount)} interactive={false} />
                    <span className={`badge ${d.overdue ? 'red' : 'cau'}`}>{d.overdue ? 'Not recorded' : 'Due'}</span>
                  </span>
                }
              />
            ))}
          </SectionCard>
        </div>
      )}

      {data.card_dues.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <SectionCard title="Card payments due" action={{ label: 'All cards', href: '/credit-cards' }}>
            {data.card_dues.map((d) => (
              <Row
                key={d.card_id}
                href={`/credit-cards/${d.card_id}`}
                glyph={<CategoryGlyph icon="credit-card" color={d.status === 'overdue' ? 'red' : 'purple'} size={34} />}
                title={`${d.name}${d.last4 ? ` ··${d.last4}` : ''}`}
                sub={
                  <>
                    {fmtDate(d.due_date)} · {dueText(d.due_date)}
                    {d.min_due > 0 && <> · minimum <Money amount={rs(d.min_due)} interactive={false} /></>}
                  </>
                }
                right={
                  <span style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 3 }}>
                    <Money amount={rs(d.amount)} interactive={false} />
                    <CycleBadge status={d.status} />
                  </span>
                }
              />
            ))}
          </SectionCard>
        </div>
      )}

      {data.upcoming_bills.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <SectionCard title="Upcoming bills" action={{ label: 'All bills', href: '/bills' }}>
            {data.upcoming_bills.map((u) => (
              <Row
                key={u.bill_id}
                href={`/transactions?bill=${u.bill_id}`}
                glyph={<CategoryGlyph icon="receipt-text" color={u.status === 'overdue' ? 'red' : 'coral'} size={34} />}
                title={u.name}
                sub={`${fmtDate(u.due)} · ${dueText(u.due)}`}
                right={
                  <span style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 3 }}>
                    <Money amount={rs(u.expected)} interactive={false} />
                    <BillBadge status={u.status} />
                  </span>
                }
              />
            ))}
          </SectionCard>
        </div>
      )}

      {data.budgets.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <SectionCard title="Budgets" action={{ label: 'All budgets', href: '/budgets' }}>
            {data.budgets.slice(0, 6).map((b) => (
              <Link
                key={b.id}
                href={`/transactions${qs({ budget: b.id, ...inMonth })}`}
                className="catrow"
                style={{ display: 'block', textDecoration: 'none' }}
              >
                <div className="top">
                  <span className="nm">{b.name}</span>
                  <span style={{ fontSize: 13 }}>
                    <span className="fig">
                      <Money amount={rs(b.spent)} interactive={false} />
                    </span>
                    {b.limit !== null && (
                      <span className="muted">
                        {' '}
                        of <Money amount={rs(b.limit)} interactive={false} />
                      </span>
                    )}
                  </span>
                </div>
                {b.limit !== null && <Progress value={b.spent} max={b.limit} />}
              </Link>
            ))}
          </SectionCard>
        </div>
      )}

      <SectionCard title="Recent activity" action={{ label: 'All transactions', href: '/transactions' }}>
        {data.recent.length === 0 ? (
          <EmptyState icon="arrow-left-right" title="No transactions yet" body="Record your first expense, income or transfer." action={{ label: 'Add transaction', onClick: () => newTxn() }} />
        ) : (
          data.recent.map((t) => <TxnRow key={t.id} t={t} onClick={() => openTxn(t)} />)
        )}
      </SectionCard>
    </div>
  );
}

/** Needs / wants / savings against the rule, and the most important suggestion. */
function SavingsCard({ p }: { p: SavingsPlan }) {
  const combined = p.settings.needs === null;
  const rows = combined
    ? [{ label: 'Spending', s: p.spending, over: true }, { label: 'Savings', s: p.savings, over: false }]
    : [
        { label: 'Needs', s: p.needs, over: true },
        { label: 'Wants', s: p.wants, over: true },
        { label: 'Savings', s: p.savings, over: false },
      ];
  const top = p.suggestions[0];
  return (
    <div style={{ marginBottom: 16 }}>
      <SectionCard title={`Savings plan · ${RULE_LABEL[p.settings.rule]}`} action={{ label: 'Open', href: '/savings-plan' }}>
        <div className="catrow" style={{ display: 'block' }}>
          <div style={{ display: 'grid', gridTemplateColumns: `repeat(${rows.length}, minmax(0, 1fr))`, gap: 12 }}>
            {rows.map(({ label, s, over }) => {
              const bad = s.diff !== null && (over ? s.diff > 0 : s.diff < 0);
              return (
                <div key={label}>
                  <div className="muted" style={{ fontSize: 11.5, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</div>
                  <div style={{ fontFamily: 'var(--font-display)', fontWeight: 800, fontSize: 20, color: bad ? 'var(--red-600)' : 'var(--fg-1)' }}>
                    {s.pct !== null ? `${Math.round(s.pct)}%` : '—'}
                  </div>
                  {s.target_pct !== null && <div className="muted" style={{ fontSize: 12 }}>target {s.target_pct}%</div>}
                </div>
              );
            })}
          </div>
          {top && (
            <div style={{ fontSize: 13, marginTop: 10, color: top.tone === 'warn' ? 'var(--amber-700)' : top.tone === 'good' ? 'var(--mint-700)' : 'var(--fg-2)' }}>
              <Icon name={top.tone === 'warn' ? 'triangle-alert' : top.tone === 'good' ? 'circle-check' : 'info'} size={14} style={{ verticalAlign: '-2px' }} /> {top.title}
            </div>
          )}
        </div>
      </SectionCard>
    </div>
  );
}
