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
import { PageHelp } from '../shared/PageHelp';

export function GuidePage() {
  const [tab, setTab] = useState<'start' | 'how'>('start');
  return (
    <div className="content-wrap fade-in" style={{ maxWidth: 940 }}>
      <div className="page-head">
        <div>
          <h1>Guide <PageHelp id="guide" /></h1>
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

/** Questions new users ask — mostly about not counting money twice. */
const FAQ: { q: string; a: React.ReactNode }[] = [
  {
    q: 'In which order should I bring things in?',
    a: (
      <>
        <ol>
          <li>Pick a <b>start date</b> (the 1st of a month is easiest) and add your accounts, cards and loans with their balances <i>on that date</i>.</li>
          <li>Import your <b>bank and card statements</b> from that date on.</li>
          <li>Then import your <b>mutual fund CAS</b> — its purchases are matched to the bank payments you already have.</li>
        </ol>
        Done the other way round it still works (see the next question), but this order needs the fewest fixes.
      </>
    ),
  },
  {
    q: 'I import the CAS and my bank statements — will my SIPs be counted twice?',
    a: (
      <>
        No, whichever you import first.
        <ul>
          <li>
            <b>Bank statement first:</b> each CAS purchase looks for a transfer into that fund with the same amount (with or without stamp duty),
            from 5 days before to 2 days after the allotment date, and is marked <b>“Already recorded — link it”</b>: only the units are added.
            A SIP still recorded as an <i>expense</i> is found too and offered as <b>“Turn the bank entry into a transfer”</b>.
          </li>
          <li>
            <b>CAS first:</b> when you later review the bank statement, a debit with the same amount as a transfer into an investment within ±6 days
            is marked <b>Duplicate</b> and isn&apos;t imported.
          </li>
          <li>One bank payment can only ever record one CAS purchase, across every CAS you import.</li>
        </ul>
        If the bank amount is different (charges, one debit for several funds) or far from the allotment date, nothing is matched — the CAS row
        shows “New transfer”; pick the right bank entry yourself.
      </>
    ),
  },
  {
    q: 'I invested in a fund years ago but my bank records start only recently. Will importing its whole history change my net worth?',
    a: (
      <>
        No. A fund counts in your net worth as <b>units × today&apos;s price (NAV)</b> — the same with or without its history. Importing the history
        only makes <b>“put in”</b> and the <b>gain</b> correct and lists every purchase.
        <ul>
          <li>
            CAS purchases dated <b>before your first bank transaction</b> are set to <b>“Older than my records”</b>: they add to what you put in but
            take no money out of any bank account — your bank&apos;s starting balance already reflects them. Leave them like that (the “All older
            than my records” button sets them all at once).
          </li>
          <li>
            Don&apos;t change an old row to <b>“New transfer with your bank”</b>: that takes the money out of your bank <i>again</i> today and lowers
            your net worth by mistake.
          </li>
          <li>Old purchases are history: they don&apos;t show up as savings in this month&apos;s savings plan.</li>
        </ul>
      </>
    ),
  },
  {
    q: '“Fund and transactions”, “Fund only” or “Transactions only” — which should I pick for a fund in the CAS?',
    a: (
      <ul>
        <li><b>Fund and transactions</b> (usual): today&apos;s units and value plus every purchase, linked to your bank payments.</li>
        <li>
          <b>Fund only</b>: just today&apos;s units and value; what you paid (the CAS cost) counts as “already invested”. Use it for a fund your bank
          statements <i>won&apos;t</i> show payments for — otherwise later SIPs from the bank would add on top of that cost.
        </li>
        <li><b>Transactions only</b>: adds the purchases to a fund you already have in MoneyMap, without changing its units or price.</li>
      </ul>
    ),
  },
  {
    q: 'When could money still be counted twice — and how do I avoid it?',
    a: (
      <ul>
        <li>
          You import <b>older</b> bank statements (from before your start date) after a CAS whose purchases were set to “Older than my records”:
          those SIP debits are already inside the fund&apos;s “already invested”. Don&apos;t import statements from before your start date — or
          skip those SIP rows on review.
        </li>
        <li>A fund imported as <b>Fund only</b> and then bank SIPs into it: use “Fund and transactions” for funds your bank statements cover.</li>
      </ul>
    ),
  },
  {
    q: 'Is paying my credit card bill, an EMI or a SIP counted as spending?',
    a: (
      <>
        <b>Card bill:</b> no — it&apos;s a transfer from your bank to the card; the spending was counted when you used the card. <b>Loan EMI:</b>{' '}
        yes, as a need (or only its interest, if you chose that on the loan). <b>SIP / money into an investment:</b> no — it&apos;s a transfer, and
        it counts as <b>savings</b> in the savings plan.
      </>
    ),
  },
  {
    q: 'I paid only part of a plot or flat, and it isn’t registered yet. How do I record it?',
    a: (
      <>
        Add it under Investments → <b>Property</b> with the <b>total agreed price</b>, and record each payment from your bank as you pay it. Until
        it&apos;s registered it counts in your net worth as <b>what you&apos;ve paid</b>; add the plan for the balance, stamp duty and other costs
        on its page.
      </>
    ),
  },
];

function HowItWorks() {
  return (
    <>
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
      <h2 style={{ fontSize: 18, margin: '26px 0 10px' }}>Common questions</h2>
      <div className="card guide-faq">
        {FAQ.map((f) => (
          <details key={f.q}>
            <summary>{f.q}</summary>
            <div className="guide-faq-a">{f.a}</div>
          </details>
        ))}
      </div>
    </>
  );
}
