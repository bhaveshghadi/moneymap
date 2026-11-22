'use client';
import { useState } from 'react';
import Link from 'next/link';
import { api } from '../lib/api';
import { useApi, useShell } from '../contexts/ShellCtx';
import type { Guide, GuideStep } from '../lib/types';
import { Button } from '../primitives/Button';
import { Icon } from '../primitives/Icon';
import { Skeleton } from '../primitives/Skeleton';
import { ErrorState } from '../primitives/ErrorState';
import { Tabs } from '../primitives/Tabs';
import { CategoryGlyph } from '../primitives/CategoryGlyph';
import { Progress } from '../shared/Progress';

export function GuidePage() {
  const [tab, setTab] = useState<'start' | 'how'>('start');
  return (
    <div className="content-wrap fade-in" style={{ maxWidth: 940 }}>
      <div className="page-head">
        <div>
          <h1>Guide</h1>
          <p>Set MoneyMap up step by step, and see how it works.</p>
        </div>
      </div>
      <Tabs
        tabs={[
          { id: 'start', label: 'Getting started' },
          { id: 'how', label: 'How MoneyMap works' },
        ]}
        active={tab}
        onChange={(id) => setTab(id as 'start' | 'how')}
        aria-label="Guide"
      />
      <div style={{ marginTop: 16 }}>{tab === 'start' ? <Checklist /> : <HowItWorks />}</div>
    </div>
  );
}

function Checklist() {
  const { bump } = useShell();
  const { data, error, reload } = useApi<Guide>('/guide');
  const [g, setG] = useState<Guide | null>(null);
  const [busy, setBusy] = useState(false);
  const guide = g ?? data;

  const act = async (action: string, step?: string) => {
    setBusy(true);
    try {
      setG(await api<Guide>('/guide', { method: 'POST', body: { action, step } }));
      bump();
    } finally {
      setBusy(false);
    }
  };

  if (error) return <div className="card"><ErrorState message={error} onRetry={reload} /></div>;
  if (!guide) return <Skeleton variant="block" height={420} />;
  const next = guide.steps.find((s) => !s.done && !s.skipped);

  return (
    <>
      <div className="card card-pad" style={{ marginBottom: 14 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
          <b style={{ fontSize: 15 }}>
            {guide.finished ? 'All set up — nice work.' : `${guide.done} of ${guide.total} steps done`}
          </b>
          {guide.hidden ? (
            <Button variant="ghost" size="sm" icon="bell" onClick={() => act('show')} disabled={busy}>Open it again on sign-in</Button>
          ) : (
            !guide.finished && <Button variant="ghost" size="sm" icon="bell-off" onClick={() => act('hide')} disabled={busy}>Don&apos;t open on sign-in</Button>
          )}
        </div>
        <Progress value={guide.done + guide.steps.filter((s) => s.skipped).length} max={guide.total} savings />
        <div className="note info" style={{ marginTop: 14, marginBottom: 0 }}>
          <Icon name="calendar-check" size={15} />
          <span>
            <b>First pick a start date</b> — say the 1st of a month. Enter balances and amounts owed <i>as on that date</i>, then bring in
            statements from that date on. That way nothing is counted twice.
          </span>
        </div>
      </div>

      <div className="card">
        {guide.steps.map((s, i) => (
          <StepRow key={s.key} s={s} n={i + 1} current={s.key === next?.key} busy={busy} act={act} />
        ))}
      </div>
    </>
  );
}

function StepRow({ s, n, current, busy, act }: { s: GuideStep; n: number; current: boolean; busy: boolean; act: (a: string, step?: string) => void }) {
  const state = s.done ? 'done' : s.skipped ? 'skipped' : current ? 'current' : 'todo';
  return (
    <div className={`guide-step ${state}`}>
      <span className="guide-n" aria-hidden>{s.done ? <Icon name="check" size={15} /> : s.skipped ? <Icon name="minus" size={15} /> : n}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
          <b style={{ fontSize: 14.5 }}>{s.title}</b>
          {s.optional && !s.done && <span className="badge neutral">If you have any</span>}
        </div>
        <div className="guide-detail">{s.skipped ? 'Skipped' : s.detail}</div>
        {(current || !s.done) && !s.skipped && <p className="guide-why">{s.why}</p>}
        <div className="guide-actions">
          <Link href={s.href} className={`btn btn-sm ${current ? 'btn-primary' : 'btn-secondary'}`} style={{ textDecoration: 'none' }}>
            {s.done ? 'Open' : 'Do this'} <Icon name="arrow-right" size={14} />
          </Link>
          {s.manual && !s.done && <Button variant="ghost" size="sm" disabled={busy} onClick={() => act('check', s.key)}>Looks right</Button>}
          {s.optional && !s.done && !s.skipped && <Button variant="ghost" size="sm" disabled={busy} onClick={() => act('skip', s.key)}>I don&apos;t have any</Button>}
          {(s.skipped || (s.manual && s.done)) && <Button variant="ghost" size="sm" disabled={busy} onClick={() => act('undo', s.key)}>Undo</Button>}
        </div>
      </div>
    </div>
  );
}

const HOW: { icon: string; color: string; title: string; body: React.ReactNode }[] = [
  {
    icon: 'landmark',
    color: 'indigo',
    title: 'Your accounts, and where money goes',
    body: (
      <>
        <b>Your accounts</b> hold money you own or owe: banks, cash, credit cards, loans and investments. Every transaction moves money
        between two places. An <b>expense</b> goes from your account to whoever you paid; <b>income</b> comes in from outside; a{' '}
        <b>transfer</b> moves money between your own accounts — paying the card bill, a SIP, moving to savings — and is never counted as
        spending or income.
      </>
    ),
  },
  {
    icon: 'file-search',
    color: 'mint',
    title: 'Statements: read, review, import',
    body: (
      <>
        Upload a PDF statement or let Gmail fetch it. MoneyMap reads every row and shows a <b>review</b> first — nothing is saved until you
        import. There you pick categories, and it suggests what it can: card payments become transfers, EMIs link to your loans, SIPs to your
        funds, and rows already in MoneyMap are marked as duplicates.
      </>
    ),
  },
  {
    icon: 'zap',
    color: 'amber',
    title: 'Rules do the categorising',
    body: (
      <>
        A rule says “when the description contains <i>swiggy</i>, set Food Delivery”. Rules fill in new transactions, Inbox alerts and
        statement rows. Accept the suggested rules, or tick <b>Rule for next time</b> while reviewing.
      </>
    ),
  },
  {
    icon: 'hand-coins',
    color: 'coral',
    title: 'Loans, cards and investments',
    body: (
      <>
        A <b>loan</b> knows its EMI schedule — paid EMIs, interest and what&apos;s left — and can be read from the lender&apos;s statement. A{' '}
        <b>credit card</b> tracks each statement, what&apos;s due and card EMIs. <b>Investments</b> show what you put in and what they&apos;re
        worth: mutual funds from your CAS with daily prices, deposits by their rate, gold by the price you enter, land and other property by the
        value you enter.
      </>
    ),
  },
  {
    icon: 'chart-pie',
    color: 'indigo',
    title: 'Needs, wants and savings',
    body: (
      <>
        Spending in <b>Essential</b> categories plus loan EMIs are your <b>needs</b>; everything else is <b>wants</b>; what&apos;s left of your
        income is <b>savings</b>. The Savings plan compares this with a rule like 50/30/20 and tells you what to change. Budgets, bills, piggy
        banks and the emergency fund help you stick to it.
      </>
    ),
  },
  {
    icon: 'shield-check',
    color: 'mint',
    title: 'Your data stays with you',
    body: (
      <>
        Everything lives in the database on your own server. Statement passwords and your Gmail access are stored encrypted, Gmail is read-only,
        and suggestions are worked out here — nothing is sent anywhere. Amounts stay hidden until you reveal them (the eye at the top).
      </>
    ),
  },
  {
    icon: 'calendar-sync',
    color: 'amber',
    title: 'Every month',
    body: (
      <>
        Fetch or upload the month&apos;s statements and review them, check the <b>Overview</b> for dues and the <b>Savings plan</b> for how the
        month went. It takes a few minutes once rules know your usual payees.
      </>
    ),
  },
];

function HowItWorks() {
  return (
    <div className="guide-how">
      {HOW.map((h) => (
        <div key={h.title} className="card card-pad" style={{ display: 'flex', gap: 14 }}>
          <CategoryGlyph icon={h.icon} color={h.color} size={40} />
          <div style={{ minWidth: 0 }}>
            <h3 style={{ margin: '2px 0 6px', fontSize: 15.5 }}>{h.title}</h3>
            <p style={{ margin: 0, fontSize: 13.5, lineHeight: 1.55, color: 'var(--fg-2)' }}>{h.body}</p>
          </div>
        </div>
      ))}
    </div>
  );
}
