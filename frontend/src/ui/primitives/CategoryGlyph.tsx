'use client';
import { Icon } from './Icon';

/** Palette keys stored on categories (backend schemas.COLORS) -> design tokens. */
export const PALETTE: Record<string, string> = {
  indigo: 'var(--indigo-500)',
  mint: 'var(--mint-500)',
  coral: 'var(--coral-400)',
  amber: 'var(--glyph-amber)',
  blue: 'var(--glyph-blue)',
  purple: 'var(--glyph-purple)',
  red: 'var(--glyph-red)',
  slate: 'var(--glyph-slate)',
};

/**
 * Tinted icon tile. Here the
 * icon/colour come from the category row itself instead of a name lookup.
 */
export function CategoryGlyph({
  icon,
  color = 'indigo',
  name = '',
  size = 34,
}: {
  icon?: string | null;
  color?: string;
  name?: string;
  size?: number;
}) {
  const c = PALETTE[color] ?? PALETTE.indigo;
  return (
    <span
      aria-hidden
      style={{
        width: size,
        height: size,
        borderRadius: Math.max(8, size / 3.5),
        background: `color-mix(in srgb, ${c} 12.16%, transparent)`,
        color: c,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
        fontWeight: 700,
      }}
    >
      {icon ? <Icon name={icon} size={size * 0.5} /> : (name || '?').charAt(0).toUpperCase()}
    </span>
  );
}
