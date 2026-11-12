'use client';
import { useState, type FormEvent } from 'react';
import Link from 'next/link';
import type { Account, AccountType } from '../lib/types';
import { api } from '../lib/api';
import { ACCOUNT_TYPE_ICON, ACCOUNT_TYPE_LABEL, fmtDate, paiseToInput, rs, toPaise } from '../lib/format';
import { useShell } from '../contexts/ShellCtx';
import { Dialog, useDialogClose } from '../primitives/Dialog';
import { Button } from '../primitives/Button';
import { Money } from '../primitives/Money';
import { CategoryGlyph } from '../primitives/CategoryGlyph';
import { DrawerHead } from './DrawerHead';

const HAS_BALANCE: AccountType[] = ['asset', 'cash'];

export function AccountForm({ account, type, onClose }: { account?: Account; type: AccountType; onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label={account ? `Account: ${account.name}` : 'Add account'} width={560}>
      <Body account={account} type={account?.type ?? type} />
    </Dialog>
  );
}

const optional = (
  <span className="muted" style={{ fontWeight: 400 }}>
    (optional)
  </span>
);

function Body({ account, type: initialType }: { account?: Account; type: AccountType }) {
  const close = useDialogClose();
  const { bump } = useShell();
  // Bank and Cash can be switched on an existing account; its transactions stay as they are.
  const [type, setType] = useState<AccountType>(initialType);
  const hasBalance = HAS_BALANCE.includes(type);

  const [name, setName] = useState(account?.name ?? '');
  const [number, setNumber] = useState(account?.account_number ?? '');
  const [opening, setOpening] = useState(account ? paiseToInput(account.opening_balance) : '');
  const [openingDate, setOpeningDate] = useState(account?.opening_date ?? '');
  const [active, setActive] = useState(account?.active ?? true);
  const [notes, setNotes] = useState(account?.notes ?? '');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    let openingPaise = 0;
    if (hasBalance && opening.trim()) {
      const v = toPaise(opening);
      if (v === null) return setError('Opening balance must be a number, e.g. 25000 or 25000.50');
      openingPaise = v;
    }
    const body = {
      name,
      ...(account && type !== account.type ? { type } : {}),
      account_number: number || null,
      opening_balance: openingPaise,
      opening_date: openingDate || null,
      active,
      notes: notes || null,
    };
    setSaving(true);
    try {
      if (account) await api(`/accounts/${account.id}`, { method: 'PATCH', body });
      else await api<Account>('/accounts', { method: 'POST', body: { ...body, type } });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!account) return;
    if (!confirmDelete) return setConfirmDelete(true);
    setSaving(true);
    try {
      await api(`/accounts/${account.id}`, { method: 'DELETE' });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
      setConfirmDelete(false);
      setSaving(false);
    }
  };

  const g = ACCOUNT_TYPE_ICON[type];

  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead
        title={account ? account.name : `Add ${ACCOUNT_TYPE_LABEL[type].toLowerCase()}`}
        sub={account ? ACCOUNT_TYPE_LABEL[type] : 'Amounts are in ₹'}
        lead={<CategoryGlyph icon={g.icon} color={g.color} size={42} />}
      />
      <div className="drawer-body">
        {error && (
          <div className="form-error" role="alert">
            {error}
          </div>
        )}
        {account && (
          <div className="card card-pad" style={{ marginBottom: 18 }}>
            <div className="kv">
              <span className="k">
                {hasBalance
                  ? 'Current balance'
                  : type === 'expense'
                    ? 'Total spent here'
                    : 'Total received'}
              </span>
              <span className="v fig">
                <Money amount={rs(account.balance)} />
              </span>
            </div>
            <div className="kv">
              <span className="k">Transactions</span>
              <span className="v">
                <Link href={`/transactions?account=${account.id}`} onClick={close}>
                  {account.transaction_count} · view all
                </Link>
              </span>
            </div>
            <div className="kv">
              <span className="k">Last activity</span>
              <span className="v">{account.last_activity ? fmtDate(account.last_activity) : '—'}</span>
            </div>
          </div>
        )}
        <div className="field">
          <label htmlFor="ac-name">Name</label>
          <input
            id="ac-name"
            className="inp"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            maxLength={120}
            placeholder={type === 'cash' ? 'e.g. Wallet' : hasBalance ? 'e.g. SBI Savings' : ''}
          />
        </div>
        {account && HAS_BALANCE.includes(account.type) && (
          <div className="field">
            <label htmlFor="ac-type">Type</label>
            <select
              id="ac-type"
              className="inp"
              value={type}
              onChange={(e) => setType(e.target.value as AccountType)}
            >
              {HAS_BALANCE.map((t) => (
                <option key={t} value={t}>
                  {ACCOUNT_TYPE_LABEL[t]}
                </option>
              ))}
            </select>
            {type !== account.type && (
              <div className="hint">
                All {account.transaction_count} transaction{account.transaction_count === 1 ? '' : 's'} stay as they
                are.
              </div>
            )}
          </div>
        )}

        {hasBalance && (
          <>
            <div className="field">
              <label htmlFor="ac-num">Account number {optional}</label>
              <input
                id="ac-num"
                className="inp"
                value={number}
                onChange={(e) => setNumber(e.target.value)}
                maxLength={64}
                placeholder="Last 4 digits are enough"
              />
            </div>
            <div className="row2">
              <div className="field">
                <label htmlFor="ac-open">Opening balance (₹)</label>
                <input
                  id="ac-open"
                  className="inp"
                  inputMode="decimal"
                  value={opening}
                  onChange={(e) => setOpening(e.target.value)}
                  placeholder="0.00"
                />
              </div>
              <div className="field">
                <label htmlFor="ac-od">As of</label>
                <input
                  id="ac-od"
                  type="date"
                  className="inp"
                  value={openingDate}
                  onChange={(e) => setOpeningDate(e.target.value)}
                />
              </div>
            </div>
            <div className="hint" style={{ marginTop: -8, marginBottom: 16, fontSize: 12, color: 'var(--fg-3)' }}>
              The balance on that date. Transactions add to or subtract from it.
            </div>
          </>
        )}
        <div className="field">
          <label htmlFor="ac-notes">Notes</label>
          <textarea id="ac-notes" className="inp" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </div>
        {account && (
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 14 }}>
            <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
            Active{' '}
            <span className="muted" style={{ fontSize: 12.5 }}>
              — inactive accounts are hidden from the transaction form
            </span>
          </label>
        )}
      </div>
      <div className="drawer-foot">
        {account && (
          <Button
            variant={confirmDelete ? 'primary' : 'ghost'}
            icon="trash-2"
            onClick={remove}
            disabled={saving}
            className={confirmDelete ? 'btn-danger' : ''}
          >
            {confirmDelete ? 'Confirm delete' : 'Delete'}
          </Button>
        )}
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>
          Cancel
        </Button>
        <Button variant="primary" type="submit" disabled={saving}>
          {saving ? 'Saving…' : account ? 'Save changes' : 'Add account'}
        </Button>
      </div>
    </form>
  );
}
