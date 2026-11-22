'use client';
import { useState, type ReactNode } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { api } from '../lib/api';
import { useApi, useShell } from '../contexts/ShellCtx';
import { StayProvider } from '../contexts/StayCtx';
import type { Account, Card, Category, Guide, Investment, Loan } from '../lib/types';
import { rs } from '../lib/format';
import { Button } from '../primitives/Button';
import { Icon } from '../primitives/Icon';
import { Money } from '../primitives/Money';
import { CategoryGlyph } from '../primitives/CategoryGlyph';
import { AccountForm } from '../shared/AccountForm';
import { CardForm } from '../shared/CardForm';
import { LoanForm } from '../shared/LoanForm';
import { LoanStatementDialog } from '../shared/LoanStatement';
import { InvestmentForm, KIND_META } from '../shared/InvestmentForm';
import { UploadStatement } from '../shared/UploadStatement';
import { GmailCard } from '../shared/GmailCard';

type StepKey = 'welcome' | 'banks' | 'cards' | 'loans' | 'funds' | 'investments' | 'essentials' | 'statements' | 'done';

const STEPS: { key: StepKey; title: string; sub: string; icon: string }[] = [
  { key: 'welcome', title: 'Welcome', sub: 'What MoneyMap does', icon: 'sparkles' },
  { key: 'banks', title: 'Bank accounts & cash', sub: 'Where your money is', icon: 'landmark' },
  { key: 'cards', title: 'Credit cards', sub: 'Limits, due dates, dues', icon: 'credit-card' },
  { key: 'loans', title: 'Loans', sub: 'EMIs and what’s left', icon: 'hand-coins' },
  { key: 'funds', title: 'Mutual funds', sub: 'From your CAS', icon: 'trending-up' },
  { key: 'investments', title: 'Other investments', sub: 'Deposits, PPF, gold, land…', icon: 'gem' },
  { key: 'essentials', title: 'Essential spending', sub: 'Your needs', icon: 'house' },
  { key: 'statements', title: 'Statements', sub: 'Gmail or upload', icon: 'file-search' },
  { key: 'done', title: 'All set', sub: 'Open MoneyMap', icon: 'circle-check' },
];

/** The full-screen setup page a brand-new install sees after creating the account. */
export function SetupPage() {
  const router = useRouter();
  const params = useSearchParams();
  const { bump } = useShell();
  const first = (params.get('step') as StepKey | null) ?? 'welcome';
  const [step, setStep] = useState<StepKey>(STEPS.some((s) => s.key === first) ? first : 'welcome');
  const guide = useApi<Guide>('/guide');
  const [leaving, setLeaving] = useState(false);
  const done = new Set((guide.data?.steps ?? []).filter((s) => s.done).map((s) => s.key));
  const detail = Object.fromEntries((guide.data?.steps ?? []).map((s) => [s.key, s.detail]));
  const i = STEPS.findIndex((s) => s.key === step);
  const go = (k: StepKey) => {
    setStep(k);
    if (typeof window !== 'undefined') window.history.replaceState(null, '', `/welcome?step=${k}`);
  };
  const next = () => go(STEPS[Math.min(i + 1, STEPS.length - 1)].key);
  const back = () => go(STEPS[Math.max(i - 1, 0)].key);

  /** "Set up later" and "Open MoneyMap": the setup page doesn't come back; the Guide has the rest. */
  const finish = async () => {
    setLeaving(true);
    try {
      await api('/guide', { method: 'POST', body: { action: 'setup_done' } });
      try {
        sessionStorage.setItem('mm-guide-opened', '1'); // not straight into the Guide as well
      } catch {
        /* private window */
      }
      bump();
      router.replace('/');
    } catch {
      setLeaving(false);
    }
  };

  return (
    <StayProvider>
      <div className="setup-wrap">
        <div className="quest-shell setup-shell">
          <nav className="quest-rail" aria-label="Setup steps">
            <div className="onb-logo setup-logo">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/assets/logo-wordmark-dark.svg" alt="MoneyMap" style={{ height: 26 }} />
            </div>
            {STEPS.map((s, n) => {
              const ok = s.key === 'welcome' ? i > 0 : s.key === 'done' ? false : done.has(s.key);
              return (
                <button key={s.key} type="button" className={`quest-step ${s.key === step ? 'on' : ''} ${ok ? 'done' : ''}`} onClick={() => go(s.key)} aria-current={s.key === step ? 'step' : undefined}>
                  <span>{ok ? <Icon name="check" size={14} /> : n + 1}</span>
                  <span className="setup-step-text">
                    <b>{s.title}</b>
                    <em>{s.key in detail && s.key !== 'essentials' ? detail[s.key] : s.sub}</em>
                  </span>
                  <i />
                </button>
              );
            })}
            <div className="quest-privacy">
              <Icon name="shield-check" size={14} /> Everything stays on your server.
            </div>
          </nav>

          <main className="quest-main">
            <div className="setup-top">
              <span className="muted" style={{ fontSize: 12.5 }}>Step {i + 1} of {STEPS.length}</span>
              {step !== 'done' && (
                <Button variant="ghost" size="sm" onClick={finish} disabled={leaving}>Set up later</Button>
              )}
            </div>
            <Step k={step} detail={detail} done={done} />
            <div className="quest-actions">
              {i > 0 && <Button variant="ghost" icon="arrow-left" onClick={back}>Back</Button>}
              <span className="spacer" style={{ flex: 1 }} />
              {step === 'done' ? (
                <Button variant="primary" icon="arrow-right" onClick={finish} disabled={leaving}>{leaving ? 'Opening…' : 'Open MoneyMap'}</Button>
              ) : step === 'welcome' ? (
                <Button variant="primary" icon="arrow-right" onClick={next}>Let&apos;s start</Button>
              ) : step === 'essentials' ? (
                <Button
                  variant="primary"
                  icon="arrow-right"
                  onClick={async () => {
                    await api('/guide', { method: 'POST', body: { action: 'check', step: 'essentials' } });
                    guide.reload();
                    next();
                  }}
                >
                  Looks right
                </Button>
              ) : (
                <>
                  {!done.has(step) && <Button variant="secondary" onClick={next}>Skip for now</Button>}
                  {done.has(step) && <Button variant="primary" icon="arrow-right" onClick={next}>Next</Button>}
                </>
              )}
            </div>
          </main>
        </div>
      </div>
    </StayProvider>
  );
}

function Head({ icon, title, children }: { icon: string; title: string; children: ReactNode }) {
  return (
    <div className="quest-head">
      <span className="quest-emblem"><Icon name={icon} size={22} /></span>
      <div>
        <h2 style={{ margin: '2px 0 6px', fontSize: 22 }}>{title}</h2>
        <p className="muted" style={{ margin: 0, fontSize: 14, lineHeight: 1.55 }}>{children}</p>
      </div>
    </div>
  );
}

function Step({ k, detail, done }: { k: StepKey; detail: Record<string, string>; done: Set<string> }) {
  switch (k) {
    case 'welcome':
      return <Welcome />;
    case 'banks':
      return <Banks />;
    case 'cards':
      return <Cards />;
    case 'loans':
      return <Loans />;
    case 'funds':
      return <Funds />;
    case 'investments':
      return <Others />;
    case 'essentials':
      return <Essentials />;
    case 'statements':
      return <Statements />;
    default:
      return <Done detail={detail} done={done} />;
  }
}

function Welcome() {
  const points: [string, string, string][] = [
    ['landmark', 'Everything in one place', 'Banks, cash, credit cards, loans, mutual funds, deposits, gold and property — with your real balances.'],
    ['file-search', 'Statements do the typing', 'Upload a PDF or let Gmail fetch it; you review every row before anything is saved.'],
    ['chart-pie', 'Know where it goes', 'Needs, wants and savings each month, budgets, bills, EMIs and your emergency fund.'],
    ['shield-check', 'Private', 'It runs on your own server. Nothing is sent anywhere, and amounts stay hidden until you reveal them.'],
  ];
  return (
    <>
      <Head icon="sparkles" title="Welcome to MoneyMap">
        A few minutes now and MoneyMap knows what you have. Add what you can — every step can be skipped and done later from the Guide.
      </Head>
      <div className="setup-points">
        {points.map(([icon, t, b]) => (
          <div key={t} className="setup-point">
            <CategoryGlyph icon={icon} color="indigo" size={34} />
            <div>
              <b>{t}</b>
              <p>{b}</p>
            </div>
          </div>
        ))}
      </div>
      <div className="note info" style={{ marginTop: 18 }}>
        <Icon name="calendar-check" size={15} />
        <span>
          <b>Tip:</b> enter every balance and amount owed as on the same day — the 1st of this month is easiest — then bring in statements from
          that day on. That way nothing is counted twice.
        </span>
      </div>
    </>
  );
}

/** A list of what's been added, or a short empty line. */
function Added({ items, empty }: { items: { key: number | string; icon: string; color?: string; name: string; sub?: string; amount?: number; owe?: boolean }[] | null; empty: string }) {
  if (items === null) return <div className="muted" style={{ fontSize: 13, margin: '8px 0' }}>Loading…</div>;
  if (items.length === 0) return <div className="setup-empty">{empty}</div>;
  return (
    <div className="setup-list">
      {items.map((x) => (
        <div key={x.key} className="setup-item">
          <CategoryGlyph icon={x.icon} color={x.color ?? 'indigo'} size={30} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <b>{x.name}</b>
            {x.sub && <div className="muted" style={{ fontSize: 12 }}>{x.sub}</div>}
          </div>
          {x.amount !== undefined && (
            <span className="fig" style={{ fontSize: 13.5 }}>
              {x.owe && <span className="muted" style={{ fontSize: 12 }}>owed </span>}
              <Money amount={rs(x.amount)} interactive={false} />
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

function Banks() {
  const accounts = useApi<Account[]>('/accounts?type=asset&type=cash');
  const [form, setForm] = useState<'asset' | 'cash' | null>(null);
  return (
    <>
      <Head icon="landmark" title="Bank accounts & cash">
        Add each bank account with its balance on the day you start from, and the last 4 digits of the account number so its statements find it by
        themselves. Add cash or a wallet too if you track it.
      </Head>
      <Added
        items={accounts.data ? accounts.data.filter((a) => a.active).map((a) => ({ key: a.id, icon: a.type === 'cash' ? 'wallet' : 'landmark', name: a.name, sub: a.account_number ? `•••• ${a.account_number.slice(-4)}` : undefined, amount: a.balance })) : null}
        empty="No accounts yet."
      />
      <div className="setup-add">
        <Button variant="secondary" icon="plus" onClick={() => setForm('asset')}>Add bank account</Button>
        <Button variant="ghost" icon="plus" onClick={() => setForm('cash')}>Add cash / wallet</Button>
      </div>
      {form && <AccountForm type={form} onClose={() => setForm(null)} />}
    </>
  );
}

function Cards() {
  const cards = useApi<Card[]>('/cards');
  const [open, setOpen] = useState(false);
  return (
    <>
      <Head icon="credit-card" title="Credit cards">
        Limit, statement day, due day, last 4 digits and what you owed on your start day. Paying the card bill from your bank then shows as a transfer,
        not as spending — your spending is counted when you use the card.
      </Head>
      <Added items={cards.data ? cards.data.map((c) => ({ key: c.id, icon: 'credit-card', name: c.name, sub: [c.bank, c.last4 && `•••• ${c.last4}`].filter(Boolean).join(' · ') || undefined })) : null} empty="No cards yet — skip this if you don't have one." />
      <div className="setup-add">
        <Button variant="secondary" icon="plus" onClick={() => setOpen(true)}>Add credit card</Button>
      </div>
      {open && <CardForm onClose={() => setOpen(false)} />}
    </>
  );
}

function Loans() {
  const loans = useApi<Loan[]>('/loans');
  const [form, setForm] = useState<'statement' | 'hand' | null>(null);
  return (
    <>
      <Head icon="hand-coins" title="Loans">
        Home, car, personal or education loans. Easiest from the lender&apos;s statement or repayment schedule (PDF): the amount, rate, EMI and EMIs
        already paid are read for you. Pick the bank the EMI is paid from so each EMI links to the loan.
      </Head>
      <Added
        items={loans.data ? loans.data.map((l) => ({ key: l.id, icon: 'hand-coins', color: 'coral', name: l.name, sub: l.lender ?? undefined })) : null}
        empty="No loans yet — skip this if you don't have any."
      />
      <div className="setup-add">
        <Button variant="secondary" icon="file-up" onClick={() => setForm('statement')}>Add from statement</Button>
        <Button variant="ghost" icon="plus" onClick={() => setForm('hand')}>Add by hand</Button>
      </div>
      {form === 'statement' && <LoanStatementDialog onClose={() => setForm(null)} />}
      {form === 'hand' && <LoanForm onClose={() => setForm(null)} />}
    </>
  );
}

function Funds() {
  const list = useApi<Investment[]>('/investments');
  const [form, setForm] = useState<'cas' | 'hand' | null>(null);
  const funds = list.data?.filter((x) => x.kind === 'mf');
  return (
    <>
      <Head icon="trending-up" title="Mutual funds">
        Ask CAMS or KFintech for a <b>detailed CAS</b> (Consolidated Account Statement) — one PDF covers all your funds. MoneyMap reads it and lets
        you choose per fund: with its purchases and SIPs, or just today&apos;s units and value. Prices update every evening.
      </Head>
      <Added items={funds ? funds.map((f) => ({ key: f.id, icon: 'trending-up', color: 'mint', name: f.name, amount: f.value })) : null} empty="No funds yet." />
      <div className="setup-add">
        <Button variant="secondary" icon="file-up" onClick={() => setForm('cas')}>Import CAS</Button>
        <Button variant="ghost" icon="plus" onClick={() => setForm('hand')}>Add a fund by hand</Button>
      </div>
      <div className="hint" style={{ marginTop: 8 }}>The CAS opens its review page; a button there brings you back here.</div>
      {form === 'cas' && <UploadStatement cas onClose={() => setForm(null)} />}
      {form === 'hand' && <InvestmentForm onClose={() => setForm(null)} />}
    </>
  );
}

function Others() {
  const list = useApi<Investment[]>('/investments');
  const [open, setOpen] = useState(false);
  const others = list.data?.filter((x) => x.kind !== 'mf');
  return (
    <>
      <Head icon="gem" title="Other investments & property">
        Fixed and recurring deposits, post office schemes, PPF / EPF / NPS, insurance, gold, stocks, crypto, chits, money you lent — and{' '}
        <b>land or a house as Property</b>, with what you paid and what it&apos;s worth today.
      </Head>
      <Added
        items={others ? others.map((x) => ({ key: x.id, icon: KIND_META[x.kind]?.icon ?? 'gem', color: KIND_META[x.kind]?.color, name: x.name, sub: KIND_META[x.kind]?.label, amount: x.value })) : null}
        empty="Nothing yet."
      />
      <div className="setup-add">
        <Button variant="secondary" icon="plus" onClick={() => setOpen(true)}>Add investment or property</Button>
      </div>
      {open && <InvestmentForm onClose={() => setOpen(false)} />}
    </>
  );
}

function Essentials() {
  const { bump } = useShell();
  const cats = useApi<Category[]>('/categories');
  const [busy, setBusy] = useState<number | null>(null);
  const toggle = async (c: Category) => {
    setBusy(c.id);
    try {
      await api(`/categories/${c.id}`, { method: 'PATCH', body: { essential: !c.essential } });
      bump();
    } finally {
      setBusy(null);
    }
  };
  const expense = (cats.data ?? []).filter((c) => c.kind === 'expense');
  return (
    <>
      <Head icon="house" title="Essential spending">
        Which costs can&apos;t you avoid? These are your <b>needs</b> — the rest of your spending counts as wants. Your emergency fund target and the
        savings plan are worked out from them. The usual ones are already ticked; change what doesn&apos;t fit you.
      </Head>
      <div className="budget-cats" style={{ maxHeight: 'none' }}>
        {expense.map((c) => (
          <button key={c.id} type="button" className={`chip ${c.essential ? 'on' : ''}`} onClick={() => toggle(c)} disabled={busy === c.id} aria-pressed={c.essential}>
            {c.essential && <Icon name="check" size={13} />} {c.name}
          </button>
        ))}
      </div>
      <div className="hint" style={{ marginTop: 10 }}>{expense.filter((c) => c.essential).length} of {expense.length} marked Essential. You can change this any time under Categories &amp; tags.</div>
    </>
  );
}

function Statements() {
  const params = useSearchParams();
  const [upload, setUpload] = useState(false);
  const gmail = params.get('gmail');
  return (
    <>
      <Head icon="file-search" title="Statements">
        This is how transactions get in without typing. Connect Gmail (read-only, with your own Google client) and MoneyMap fetches bank, card,
        loan and CAS statements — or just upload the PDFs you download from your bank. You review every row before it&apos;s saved.
      </Head>
      {gmail === 'connected' && (
        <div className="note privacy" style={{ marginBottom: 12 }}><Icon name="check" size={15} /> <span>Gmail is connected.</span></div>
      )}
      {gmail === 'error' && (
        <div className="form-error" style={{ marginBottom: 12 }}>Gmail couldn&apos;t be connected: {params.get('reason') ?? 'unknown error'}.</div>
      )}
      <div style={{ marginBottom: 14 }}>
        <GmailCard />
      </div>
      <div className="setup-add">
        <Button variant="secondary" icon="file-up" onClick={() => setUpload(true)}>Upload a statement PDF</Button>
      </div>
      <div className="hint" style={{ marginTop: 8 }}>A statement opens its review page; a button there brings you back here.</div>
      {upload && <UploadStatement onClose={() => setUpload(false)} />}
    </>
  );
}

function Done({ detail, done }: { detail: Record<string, string>; done: Set<string> }) {
  const rows = STEPS.filter((s) => s.key !== 'welcome' && s.key !== 'done');
  return (
    <>
      <Head icon="circle-check" title="You're set">
        Here&apos;s what MoneyMap has. Anything you skipped is waiting in the <b>Guide</b> (in the sidebar), with the rest of the setup: rules, your
        emergency fund, bills, and a savings rule with budgets.
      </Head>
      <div className="setup-list">
        {rows.map((s) => (
          <div key={s.key} className="setup-item">
            <span style={{ color: done.has(s.key) ? 'var(--mint-600)' : 'var(--fg-3)' }}>
              <Icon name={done.has(s.key) ? 'circle-check' : 'circle-dashed'} size={20} />
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <b>{s.title}</b>
              <div className="muted" style={{ fontSize: 12 }}>{done.has(s.key) ? detail[s.key] : 'Skipped — in the Guide for later'}</div>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
