'use client';

/** `.catrow .track` style bar. Colour shifts amber near the limit, red over it
 * (or stays mint for savings, where more is better). */
export function Progress({ value, max, savings = false }: { value: number; max: number; savings?: boolean }) {
  const pct = max > 0 ? (value / max) * 100 : value > 0 ? 100 : 0;
  const color = savings
    ? 'var(--mint-500)'
    : pct > 100
      ? 'var(--red-500)'
      : pct >= 85
        ? 'var(--amber-500)'
        : 'var(--mint-500)';
  return (
    <div className="track" style={{ height: 8, borderRadius: 999, background: 'var(--bg-sunken)', overflow: 'hidden' }}>
      <i style={{ display: 'block', height: '100%', borderRadius: 999, width: `${Math.min(100, pct)}%`, background: color, transition: 'width var(--dur-slow) var(--ease-out)' }} />
    </div>
  );
}

