'use client';
import Link from 'next/link';
import type { Txn } from '../lib/types';
import { ACCOUNT_TYPE_LABEL, fmtDate } from '../lib/format';
import { Dialog } from '../primitives/Dialog';
import { Button } from '../primitives/Button';
import { DrawerHead } from './DrawerHead';
import { TxnAmount, TxnGlyph } from './TxnRow';

const TYPE_LABEL = { withdrawal: 'Expense', deposit: 'Income', transfer: 'Transfer' } as const;

/** Read-only transaction detail. */
export function TxnDrawer({ txn: t, onClose, onEdit }: { txn: Txn; onClose: () => void; onEdit: () => void }) {
  return (
    <Dialog onClose={onClose} label={`Transaction: ${t.description}`}>
      <DrawerHead title={t.description} sub={`${TYPE_LABEL[t.type]} · ${fmtDate(t.date)}`} lead={<TxnGlyph t={t} size={42} />} />
      <div className="drawer-body">
        <div className="card card-pad" style={{ marginBottom: 16, textAlign: 'center' }}>
          <div className="muted" style={{ fontSize: 12, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Amount
          </div>
          <div className="doc-amt" style={{ marginTop: 6 }}>
            <TxnAmount t={t} size={26} />
          </div>
        </div>
        <div>
          <div className="kv">
            <span className="k">From</span>
            <span className="v">
              <Link href={`/transactions?account=${t.source.id}`} onClick={onClose}>{t.source.name}</Link>
              <div className="muted" style={{ fontWeight: 400, fontSize: 12 }}>{ACCOUNT_TYPE_LABEL[t.source.type]}</div>
            </span>
          </div>
          <div className="kv">
            <span className="k">To</span>
            <span className="v">
              <Link href={`/transactions?account=${t.destination.id}`} onClick={onClose}>{t.destination.name}</Link>
              <div className="muted" style={{ fontWeight: 400, fontSize: 12 }}>{ACCOUNT_TYPE_LABEL[t.destination.type]}</div>
            </span>
          </div>
          <div className="kv">
            <span className="k">Category</span>
            <span className="v">
              {t.category ? (
                <Link href={`/transactions?category=${t.category.id}`} onClick={onClose}>{t.category.name}</Link>
              ) : (
                <span className="muted">—</span>
              )}
            </span>
          </div>
          <div className="kv">
            <span className="k">Tags</span>
            <span className="v" style={{ display: 'flex', gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
              {t.tags.length ? (
                t.tags.map((tag) => (
                  <Link key={tag} href={`/transactions?tag=${encodeURIComponent(tag)}`} onClick={onClose} className="badge neutral" style={{ textDecoration: 'none' }}>
                    #{tag}
                  </Link>
                ))
              ) : (
                <span className="muted">—</span>
              )}
            </span>
          </div>
          <div className="kv">
            <span className="k">Date</span>
            <span className="v">{fmtDate(t.date)}</span>
          </div>
        </div>
        {t.notes && (
          <div className="note info" style={{ marginTop: 16, whiteSpace: 'pre-wrap' }}>
            {t.notes}
          </div>
        )}
      </div>
      <div className="drawer-foot">
        <span className="spacer" />
        <Button variant="primary" icon="pencil" onClick={onEdit}>
          Edit
        </Button>
      </div>
    </Dialog>
  );
}
