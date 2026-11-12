'use client';
import { createContext, useContext, useState, type ReactNode } from 'react';
import type { Txn } from '../lib/types';
import { TxnDrawer } from '../shared/TxnDrawer';
import { TxnForm, type TxnDefaults } from '../shared/TxnForm';

interface TxnCtxValue {
  /** Open the read-only detail drawer. */
  openTxn: (t: Txn) => void;
  /** Open the editor for a new transaction (optionally prefilled). */
  newTxn: (defaults?: TxnDefaults) => void;
  /** Open the editor for an existing transaction. */
  editTxn: (t: Txn) => void;
}

const TxnCtx = createContext<TxnCtxValue>({ openTxn: () => {}, newTxn: () => {}, editTxn: () => {} });

/** One place that owns the
 * transaction detail drawer and the add/edit form. */
export function TxnProvider({ children }: { children: ReactNode }) {
  const [viewing, setViewing] = useState<Txn | null>(null);
  const [editing, setEditing] = useState<{ txn?: Txn; defaults?: TxnDefaults; key: number } | null>(null);

  const value: TxnCtxValue = {
    openTxn: (t) => setViewing(t),
    newTxn: (defaults) => setEditing({ defaults, key: Date.now() }),
    editTxn: (t) => {
      setViewing(null);
      setEditing({ txn: t, key: Date.now() });
    },
  };

  return (
    <TxnCtx.Provider value={value}>
      {children}
      {viewing && <TxnDrawer txn={viewing} onClose={() => setViewing(null)} onEdit={() => value.editTxn(viewing)} />}
      {editing && (
        <TxnForm key={editing.key} txn={editing.txn} defaults={editing.defaults} onClose={() => setEditing(null)} />
      )}
    </TxnCtx.Provider>
  );
}

export function useTxn(): TxnCtxValue {
  return useContext(TxnCtx);
}
