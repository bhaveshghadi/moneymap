'use client';
import type { CategoryKind, CategoryRef } from '../lib/types';

const GROUPS: [CategoryKind, string][] = [
  ['expense', 'Expense'],
  ['income', 'Income'],
];

/** Which category type fits a transaction / statement row kind (none for transfers). */
export function kindFor(type: string | null | undefined): CategoryKind | undefined {
  if (type === 'withdrawal' || type === 'expense') return 'expense';
  if (type === 'deposit' || type === 'income') return 'income';
  return undefined;
}

/**
 * <option>s for a category <select>, grouped Expense / Income. With `kind`,
 * only that type is listed — plus the currently selected category (`keep`)
 * if it is of the other type, so an existing choice never disappears.
 */
export function CategoryOptions({
  categories,
  kind,
  keep,
}: {
  categories: CategoryRef[];
  kind?: CategoryKind;
  keep?: number | string | null;
}) {
  const keepId = keep === null || keep === undefined || keep === '' ? null : Number(keep);
  return (
    <>
      {GROUPS.map(([k, label]) => {
        const list = categories.filter((c) => c.kind === k && (!kind || k === kind || c.id === keepId));
        if (!list.length) return null;
        return (
          <optgroup key={k} label={label}>
            {list.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </optgroup>
        );
      })}
    </>
  );
}
