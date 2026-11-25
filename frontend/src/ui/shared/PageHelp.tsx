'use client';
import { useEffect, useId, useRef, useState } from 'react';
import Link from 'next/link';
import { Icon } from '../primitives/Icon';

type Help = { what: string; how: string[] };

/** What each section is for and how to use it — shown from the ⓘ next to the page title. */
const HELP: Record<string, Help> = {
  overview: {
    what: 'Your money at a glance: net worth, this month’s income and spending, where it went, and what’s due soon.',
    how: [
      'Use the arrows to look at another month.',
      'Click a category to see its expenses, or a card / loan / bill to open it.',
      'Amounts are hidden until you press the eye at the top.',
    ],
  },
  transactions: {
    what: 'Every expense, income and transfer, from statements, Gmail alerts or added by hand.',
    how: [
      'Add one with “Add transaction” (or + Add at the top).',
      'Filter by account, category, budget, tag or dates; search the description or notes.',
      'Click a row to see or edit it; “Select” deletes several at once.',
      'Transfers between your own accounts (card bills, SIPs) are never spending.',
    ],
  },
  accounts: {
    what: 'Your bank accounts, wallets and cash — what you have in each.',
    how: [
      'Add each with its balance on your start date and the last 4 digits of the account number, so statements find it.',
      'Click an account to see its transactions.',
    ],
  },
  'credit-cards': {
    what: 'Your credit cards: what you owe, each statement, due dates and card EMIs.',
    how: [
      'Add a card with its limit, statement day, due day and last 4 digits.',
      'Import its statements; paying the bill from your bank is a transfer, not spending.',
      'Open a card to see each cycle, what’s due and its EMIs.',
    ],
  },
  card: {
    what: 'One credit card: its statements cycle by cycle, what’s due and when, and its EMIs.',
    how: [
      'Each cycle shows its spending, the statement total, the minimum and what you’ve paid.',
      'Convert a big purchase into an EMI plan, or move old bill payments here as transfers.',
    ],
  },
  loans: {
    what: 'Your loans: EMI, what’s left, interest paid and the full repayment schedule.',
    how: [
      '“Add from statement” reads the lender’s statement or schedule and fills everything in.',
      'Set the bank the EMI is paid from so EMIs link to the loan.',
      'Open a loan for its schedule, part-payments, rate changes and a what-if.',
    ],
  },
  loan: {
    what: 'One loan: its schedule, EMIs paid, what’s left and what a part-payment would save.',
    how: [
      '“Pay EMI” records the next EMI; past EMI payments can be moved onto the loan.',
      'Record a part-payment or a rate change; choose a lower EMI or a shorter loan.',
      '“Update from statement” checks it against the lender’s latest statement.',
    ],
  },
  investments: {
    what: 'Everything you own besides cash: mutual funds, deposits, PPF / EPF / NPS, gold, stocks, property and more — what you put in and what it’s worth.',
    how: [
      '“Import CAS” brings in all your mutual funds; add others with “Add investment”.',
      'Money in and out are transfers from your bank, never spending or income.',
      'Fund prices update every evening; for others, update the value now and then.',
    ],
  },
  investment: {
    what: 'One investment: what you put in, its value today, the gain, and its money in and out.',
    how: [
      '“Add money” / “Take money out” record transfers with your bank.',
      '“Update value” for kinds you value by hand; “Mark closed / sold” when it’s over.',
      'For property bought in parts: the purchase, payment plan and costs are under Purchase.',
    ],
  },
  'savings-plan': {
    what: 'How your income splits into needs, wants and savings, compared with a rule like 50/30/20.',
    how: [
      'Pick the rule and the income to use with the Rule button.',
      'Needs are your Essential categories plus EMIs; the rest of spending is wants.',
      'Follow “What to do”, or make budgets from the rule.',
    ],
  },
  budgets: {
    what: 'How much you plan to spend each month, and how it’s going.',
    how: [
      'Add a budget with an amount per month; pick the categories it counts, or choose the budget on each expense.',
      '“Rolls over” carries what’s left (or overspent) into next month.',
    ],
  },
  bills: {
    what: 'Regular payments — rent, phone, internet, subscriptions, premiums — and whether this month’s is paid.',
    how: ['Add a bill with its usual amount and due day.', 'Matching expenses are linked to the bill by themselves.'],
  },
  'piggy-banks': {
    what: 'Savings goals and your emergency fund. The money stays in your bank; a goal only earmarks part of it.',
    how: [
      'Add a goal with a target and a date; set money aside or take it out as you go.',
      'The emergency fund target is worked out from your Essential spending and EMIs.',
    ],
  },
  inbox: {
    what: 'Emails fetched from Gmail: statements to read and transaction alerts to save.',
    how: [
      '“Fetch from Gmail” finds emails, shows them, and downloads only the ones you tick.',
      'Open a statement to review and import it; save an alert as a transaction, or ignore it.',
    ],
  },
  statements: {
    what: 'Bank, card and loan statements from Gmail or uploaded — read into rows for you to review.',
    how: [
      'Upload a PDF; password-protected ones ask for the password (it can be remembered).',
      'Nothing is saved until you review and import a statement.',
    ],
  },
  'statement-review': {
    what: 'The rows read from one statement, before anything is saved.',
    how: [
      'Check each row’s category, or turn it into a transfer (card bills, SIPs, moving money).',
      'Duplicates and rows already in MoneyMap are skipped; tick “Rule for next time” to remember a category.',
      'Import when it looks right.',
    ],
  },
  'cas-review': {
    what: 'The funds and transactions read from your mutual fund CAS, before anything is saved.',
    how: [
      'For each fund choose Fund and transactions, Fund only, Transactions only or Leave out.',
      'Purchases already paid from your bank are linked; old ones are “Older than my records”.',
      'See Guide → Common questions on avoiding double counting.',
    ],
  },
  categories: {
    what: 'The categories and tags your transactions are sorted into.',
    how: [
      'Mark Essential the costs you can’t avoid — they’re your needs.',
      'Add, rename or recolour categories; tags label anything across categories (e.g. #trip).',
    ],
  },
  rules: {
    what: 'Automatic categorising: “when the description contains swiggy, set Food Delivery”.',
    how: [
      'Rules run on new transactions, Gmail alerts and statement rows, top to bottom.',
      'Accept the suggested rules, or tick “Rule for next time” while reviewing a statement.',
      '“Apply” runs a rule over transactions you already have.',
    ],
  },
  guide: {
    what: 'Setting MoneyMap up step by step, and how it works.',
    how: ['Getting started ticks itself as you add things.', 'How MoneyMap works ends with common questions.'],
  },
  settings: {
    what: 'Gmail connection, appearance, password and app details.',
    how: ['Connect Gmail (read-only) to fetch statements.', 'Choose Light, Dark or Match system.', 'Change your password.'],
  },
};

export function PageHelp({ id }: { id: keyof typeof HELP | string }) {
  const help = HELP[id];
  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState(false); // opened by click / tap: stays until closed
  const ref = useRef<HTMLSpanElement | null>(null);
  const tipId = useId();

  useEffect(() => {
    if (!open) return;
    const outside = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
        setPinned(false);
      }
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false);
        setPinned(false);
      }
    };
    document.addEventListener('pointerdown', outside);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('pointerdown', outside);
      document.removeEventListener('keydown', esc);
    };
  }, [open]);

  if (!help) return null;
  return (
    <span
      ref={ref}
      className="page-help"
      onMouseEnter={(e) => {
        if (e.nativeEvent instanceof MouseEvent && !pinned) setOpen(true);
      }}
      onMouseLeave={() => {
        if (!pinned) setOpen(false);
      }}
    >
      <button
        type="button"
        className="page-help-btn"
        aria-label="What this section is for"
        aria-expanded={open}
        aria-describedby={open ? tipId : undefined}
        onClick={() => {
          const next = !(open && pinned);
          setOpen(next);
          setPinned(next);
        }}
      >
        <Icon name="info" size={17} />
      </button>
      {open && (
        <span id={tipId} role="tooltip" className="page-help-pop">
          <span className="page-help-what">{help.what}</span>
          <span className="page-help-how">How to use it</span>
          <ul>
            {help.how.map((h) => (
              <li key={h}>{h}</li>
            ))}
          </ul>
          <Link href="/guide" className="page-help-more">More in the Guide →</Link>
        </span>
      )}
    </span>
  );
}
