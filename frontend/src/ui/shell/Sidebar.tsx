'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Icon } from '../primitives/Icon';
import { useApi } from '../contexts/ShellCtx';

interface NavItem {
  href: string;
  label: string;
  icon: string;
  count?: number;
}

// Each feature adds its pages here.
const MAIN: NavItem[] = [
  { href: '/', label: 'Overview', icon: 'layout-dashboard' },
  { href: '/transactions', label: 'Transactions', icon: 'arrow-left-right' },
  { href: '/accounts', label: 'Accounts', icon: 'landmark' },
  { href: '/credit-cards', label: 'Credit cards', icon: 'credit-card' },
  { href: '/loans', label: 'Loans', icon: 'hand-coins' },
  { href: '/investments', label: 'Investments', icon: 'trending-up' },
  { href: '/budgets', label: 'Budgets', icon: 'gauge' },
  { href: '/bills', label: 'Bills', icon: 'receipt-text' },
  { href: '/piggy-banks', label: 'Piggy banks', icon: 'piggy-bank' },
];

// Gmail import: fetched emails and the statements read from them (or uploaded).
const IMPORT: NavItem[] = [
  { href: '/inbox', label: 'Inbox', icon: 'inbox' },
  { href: '/statements', label: 'Statements', icon: 'file-spreadsheet' },
];

const TOOLS: NavItem[] = [
  { href: '/categories', label: 'Categories & tags', icon: 'tags' },
  { href: '/rules', label: 'Rules', icon: 'zap' },
  { href: '/settings', label: 'Settings', icon: 'settings' },
];

export function Sidebar() {
  const pathname = usePathname();
  // the Inbox shows how many fetched emails are still to deal with
  const inbox = useApi<{ new: number }>('/inbox/counts');
  const imports = IMPORT.map((t) => (t.href === '/inbox' && inbox.data?.new ? { ...t, count: inbox.data.new } : t));

  const renderItem = (it: NavItem) => {
    const active = it.href === '/' ? pathname === '/' : pathname === it.href || pathname.startsWith(`${it.href}/`);
    return (
      <Link
        key={it.href}
        href={it.href}
        className={`sb-item ${active ? 'active' : ''}`}
        aria-current={active ? 'page' : undefined}
        title={it.label}
      >
        <Icon name={it.icon} size={18} />
        <span>{it.label}</span>
        {it.count != null && <span className="sb-count alert">{it.count}</span>}
      </Link>
    );
  };

  return (
    <nav className="sidebar">
      <div className="sb-logo">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img className="logo-light" src="/assets/logo-wordmark.svg" alt="MoneyMap" style={{ height: 26 }} />
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img className="logo-dark" src="/assets/logo-wordmark-dark.svg" alt="MoneyMap" style={{ height: 26 }} />
      </div>
      <div className="sb-nav">{MAIN.map(renderItem)}</div>
      <div className="sb-section">Import</div>
      <div className="sb-nav">{imports.map(renderItem)}</div>
      <div className="sb-section">Setup</div>
      <div className="sb-nav">{TOOLS.map(renderItem)}</div>
      <div className="sb-foot">
        <div className="sb-card">
          <div className="row">
            <Icon name="hard-drive" size={14} color="var(--mint-600)" />
            <b style={{ color: 'var(--fg-1)', fontWeight: 600 }}>Stored on your server</b>
          </div>
          <div className="row" style={{ fontSize: 11.5, marginTop: 6 }}>
            Self-hosted · amounts hidden until you reveal them
          </div>
        </div>
      </div>
    </nav>
  );
}
