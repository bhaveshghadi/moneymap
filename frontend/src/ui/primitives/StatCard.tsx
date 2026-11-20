'use client';
import type { ReactNode, CSSProperties } from 'react';
import { Icon } from './Icon';

interface StatCardProps {
  lbl: string;
  icon?: string;
  val: ReactNode;
  delta?: string;
  dir?: 'up' | 'down' | 'flat';
  /** Colour of the delta when "up" isn't automatically good (e.g. spending going up is bad). */
  tone?: 'good' | 'bad' | 'flat';
  sub?: ReactNode;
  accent?: string;
  /** Characters in the value: a long one (₹11,11,11,111.00) shrinks to fit the card. */
  fit?: number;
}

export function StatCard({ lbl, icon, val, delta, dir, tone, sub, accent, fit }: StatCardProps) {
  const valStyle = {
    ...(accent ? { color: accent } : {}),
    ...(fit ? { '--chars': fit } : {}),
  } as CSSProperties;
  return (
    <div className="card card-pad stat">
      <div className="lbl">
        {icon && <Icon name={icon} size={13} />}
        {lbl}
      </div>
      <div className={fit ? 'val fit' : 'val'} style={valStyle}>
        {val}
      </div>
      {delta && (
        <span className={`delta ${tone ? { good: 'up', bad: 'down', flat: 'flat' }[tone] : (dir ?? 'flat')}`}>
          {dir === 'up' ? <Icon name="trending-up" size={14} /> : dir === 'down' ? <Icon name="trending-down" size={14} /> : null}
          {delta}
        </span>
      )}
      {sub && (
        <span className="muted" style={{ fontSize: 12.5, display: 'block' }}>
          {sub}
        </span>
      )}
    </div>
  );
}
