'use client';
import type { Txn } from '../lib/types';
import { counterparty, fmtDate, ownAccount, rs } from '../lib/format';
import { Money } from '../primitives/Money';
import { CategoryGlyph } from '../primitives/CategoryGlyph';

export function TxnGlyph({ t, size = 38 }: { t: Txn; size?: number }) {
  if (t.type === 'transfer') return <CategoryGlyph icon="arrow-left-right" color="slate" size={size} />;
  if (t.category) return <CategoryGlyph icon={t.category.icon} color={t.category.color} size={size} />;
  return (
    <CategoryGlyph
      icon={t.type === 'deposit' ? 'arrow-down-to-line' : 'circle-help'}
      color={t.type === 'deposit' ? 'mint' : 'slate'}
      size={size}
    />
  );
}

export function TxnAmount({ t, size = 14.5 }: { t: Txn; size?: number }) {
  const pos = t.type === 'deposit';
  const sign = t.type === 'deposit' ? '+' : t.type === 'withdrawal' ? '−' : '';
  return (
    <span className={`amt ${pos ? 'pos' : ''}`} style={{ fontSize: size }}>
      {sign}
      <Money amount={rs(t.amount)} pos={pos} precise interactive={false} />
    </span>
  );
}

/** One `.txn` list row. */
export function TxnRow({
  t,
  onClick,
  showDate = true,
}: {
  t: Txn;
  onClick: () => void;
  showDate?: boolean;
}) {
  const own = ownAccount(t);
  return (
    <button type="button" className="txn click rowbtn" onClick={onClick}>
      <TxnGlyph t={t} />
      <div className="txn-mid">
        <div className="mer" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {t.description}
        </div>
        <div className="cat">
          <span>{counterparty(t)}</span>
          {own && <span>· {own}</span>}
          {t.category ? <span>· {t.category.name}</span> : t.type !== 'transfer' && <span className="badge cau">Uncategorised</span>}
          {t.tags.map((tag) => (
            <span key={tag} className="badge neutral">
              #{tag}
            </span>
          ))}
        </div>
      </div>
      <div style={{ textAlign: 'right', flexShrink: 0, marginLeft: 'auto' }}>
        <TxnAmount t={t} />
        {showDate && (
          <div className="muted" style={{ fontSize: 11.5 }}>
            {fmtDate(t.date)}
          </div>
        )}
      </div>
    </button>
  );
}
