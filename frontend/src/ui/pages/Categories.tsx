'use client';
import { Fragment, useState, type FormEvent } from 'react';
import Link from 'next/link';
import { api } from '../lib/api';
import { useApi, useShell } from '../contexts/ShellCtx';
import type { Category, CategoryKind, Tag } from '../lib/types';
import { rs } from '../lib/format';
import { Tabs } from '../primitives/Tabs';
import { Button } from '../primitives/Button';
import { Money } from '../primitives/Money';
import { Skeleton } from '../primitives/Skeleton';
import { EmptyState } from '../primitives/EmptyState';
import { ErrorState } from '../primitives/ErrorState';
import { Icon } from '../primitives/Icon';
import { CategoryGlyph, PALETTE } from '../primitives/CategoryGlyph';
import { Dialog, useDialogClose } from '../primitives/Dialog';
import { DrawerHead } from '../shared/DrawerHead';
import { PageHelp } from '../shared/PageHelp';

const ICONS = [
  'shopping-basket',
  'utensils',
  'utensils-crossed',
  'coffee',
  'bike',
  'car',
  'car-taxi-front',
  'fuel',
  'plane',
  'bed-double',
  'train-front',
  'shopping-bag',
  'shirt',
  'smartphone',
  'zap',
  'plug-zap',
  'droplets',
  'flame',
  'wifi',
  'house',
  'key',
  'building-2',
  'house-plug',
  'hand-helping',
  'heart-pulse',
  'pill',
  'dumbbell',
  'sparkles',
  'shield-check',
  'clapperboard',
  'tv',
  'gamepad-2',
  'music',
  'repeat',
  'graduation-cap',
  'book-open',
  'baby',
  'paw-print',
  'users',
  'gift',
  'heart-handshake',
  'landmark',
  'scale',
  'receipt',
  'receipt-text',
  'wrench',
  'trending-up',
  'briefcase',
  'wallet',
  'percent',
  'coins',
  'key-round',
  'badge-percent',
  'rotate-ccw',
  'arrow-down-to-line',
  'banknote',
  'piggy-bank',
  'circle',
];

const KIND_GROUPS: [CategoryKind, string][] = [
  ['expense', 'Expense'],
  ['income', 'Income'],
];

export function CategoriesPage() {
  const [tab, setTab] = useState<'categories' | 'tags'>('categories');
  const cats = useApi<Category[]>('/categories');
  const tags = useApi<Tag[]>('/tags');
  const [editingCat, setEditingCat] = useState<{ cat?: Category } | null>(null);
  const [editingTag, setEditingTag] = useState<Tag | null>(null);

  return (
    <div className="content-wrap fade-in">
      <div className="page-head">
        <div>
          <h1>Categories &amp; tags <PageHelp id="categories" /></h1>
          <p>Categories say what money was for; tags group transactions across categories (a trip, a project).</p>
        </div>
        <div className="actions">
          {tab === 'categories' && (
            <Button variant="primary" icon="plus" onClick={() => setEditingCat({})}>
              Add category
            </Button>
          )}
        </div>
      </div>

      <Tabs
        tabs={[
          {
            id: 'categories',
            label: `Categories${cats.data ? ` (${cats.data.length})` : ''}`,
          },
          {
            id: 'tags',
            label: `Tags${tags.data ? ` (${tags.data.length})` : ''}`,
          },
        ]}
        active={tab}
        onChange={(id) => setTab(id as 'categories' | 'tags')}
        aria-label="Categories or tags"
      />

      {tab === 'categories' ? (
        <div className="card">
          {cats.error ? (
            <ErrorState message={cats.error} onRetry={cats.reload} />
          ) : !cats.data ? (
            <div className="card-pad stack" style={{ gap: 8 }}>
              <Skeleton variant="row" count={6} />
            </div>
          ) : cats.data.length === 0 ? (
            <EmptyState
              icon="tags"
              title="No categories"
              action={{
                label: 'Add category',
                onClick: () => setEditingCat({}),
              }}
            />
          ) : (
            <div className="tbl-wrap" style={{ padding: '16px 6px 6px' }}>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Category</th>
                    <th className="r">Spent this month</th>
                    <th className="r hide-sm">Transactions</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {KIND_GROUPS.map(([kind, label]) => {
                    const list = cats.data!.filter((c) => c.kind === kind);
                    if (!list.length) return null;
                    return (
                      <Fragment key={kind}>
                        <tr className="cat-group">
                          <td colSpan={4}>
                            {label} <span className="muted">· {list.length}</span>
                          </td>
                        </tr>
                        {list.map((c) => (
                          <tr key={c.id} className="click" onClick={() => setEditingCat({ cat: c })}>
                            <td>
                              <div
                                style={{
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: 11,
                                  fontWeight: 600,
                                }}
                              >
                                <CategoryGlyph icon={c.icon} color={c.color} size={30} />
                                {c.name}
                                {c.essential && <span className="badge brand">Essential</span>}
                              </div>
                            </td>
                            <td className="r figure">
                              {c.spent_this_month ? <Money amount={rs(c.spent_this_month)} interactive={false} /> : <span className="muted">—</span>}
                            </td>
                            <td className="r t-mono hide-sm">{c.transaction_count}</td>
                            <td className="r">
                              <Link href={`/transactions?category=${c.id}`} className="prov" onClick={(e) => e.stopPropagation()} title="View transactions">
                                View <Icon name="arrow-right" size={12} />
                              </Link>
                            </td>
                          </tr>
                        ))}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : (
        <div className="card card-pad">
          <TagAdder />
          {tags.error ? (
            <ErrorState message={tags.error} onRetry={tags.reload} />
          ) : !tags.data ? (
            <Skeleton variant="row" count={2} />
          ) : tags.data.length === 0 ? (
            <EmptyState icon="hash" title="No tags yet" body="Add tags here, or type them straight into a transaction." />
          ) : (
            <div className="chips" style={{ marginTop: 16 }}>
              {tags.data.map((t) => (
                <button key={t.id} type="button" className="chip tag-chip" onClick={() => setEditingTag(t)}>
                  #{t.name}
                  <span className="n">{t.transaction_count}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {editingCat && <CategoryForm cat={editingCat.cat} onClose={() => setEditingCat(null)} />}
      {editingTag && <TagForm tag={editingTag} onClose={() => setEditingTag(null)} />}
    </div>
  );
}

function TagAdder() {
  const { bump } = useShell();
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    try {
      await api('/tags', { method: 'POST', body: { name } });
      setName('');
      setError(null);
      bump();
    } catch (err) {
      setError((err as Error).message);
    }
  };
  return (
    <form onSubmit={submit} style={{ display: 'flex', gap: 10 }}>
      <input
        className="inp"
        placeholder="New tag, e.g. goa-trip"
        value={name}
        onChange={(e) => setName(e.target.value)}
        maxLength={64}
        aria-label="New tag name"
      />
      <Button variant="secondary" type="submit" icon="plus">
        Add tag
      </Button>
      {error && (
        <span className="muted" role="alert" style={{ alignSelf: 'center', color: 'var(--red-600)', fontSize: 13 }}>
          {error}
        </span>
      )}
    </form>
  );
}

function CategoryForm({ cat, onClose }: { cat?: Category; onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label={cat ? `Category: ${cat.name}` : 'Add category'} width={480}>
      <CategoryFormBody cat={cat} />
    </Dialog>
  );
}

function CategoryFormBody({ cat }: { cat?: Category }) {
  const close = useDialogClose();
  const { bump } = useShell();
  const [name, setName] = useState(cat?.name ?? '');
  const [kind, setKind] = useState<CategoryKind>(cat?.kind ?? 'expense');
  const [icon, setIcon] = useState(cat?.icon ?? 'circle');
  const [color, setColor] = useState(cat?.color ?? 'indigo');
  const [essential, setEssential] = useState(cat?.essential ?? false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const body = { name, kind, icon, color, essential: kind === 'expense' && essential };
      if (cat) await api(`/categories/${cat.id}`, { method: 'PATCH', body });
      else await api('/categories', { method: 'POST', body });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!cat) return;
    if (!confirmDelete) return setConfirmDelete(true);
    setSaving(true);
    try {
      await api(`/categories/${cat.id}`, { method: 'DELETE' });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead
        title={cat ? 'Edit category' : 'Add category'}
        sub={cat ? `${cat.transaction_count} transaction${cat.transaction_count === 1 ? '' : 's'}` : undefined}
        lead={<CategoryGlyph icon={icon} color={color} size={42} />}
      />
      <div className="drawer-body">
        {error && (
          <div className="form-error" role="alert">
            {error}
          </div>
        )}
        <div className="field">
          <label htmlFor="cat-name">Name</label>
          <input id="cat-name" className="inp" value={name} onChange={(e) => setName(e.target.value)} required maxLength={80} />
        </div>
        <div className="field">
          <label htmlFor="cat-kind">Type</label>
          <select id="cat-kind" className="inp" value={kind} onChange={(e) => setKind(e.target.value as CategoryKind)}>
            <option value="expense">Expense — money going out</option>
            <option value="income">Income — money coming in</option>
          </select>
        </div>
        {kind === 'expense' && (
          <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 14, marginBottom: 16 }}>
            <input type="checkbox" checked={essential} onChange={(e) => setEssential(e.target.checked)} style={{ marginTop: 3 }} />
            <span>
              Essential spending
              <span className="muted" style={{ display: 'block', fontSize: 12.5 }}>
                Spending you couldn&apos;t cut in an emergency (rent, groceries, bills). The emergency fund is based on it.
              </span>
            </span>
          </label>
        )}
        <div className="field">
          <label>Colour</label>
          <div className="swatches" role="radiogroup" aria-label="Colour">
            {Object.entries(PALETTE).map(([key, css]) => (
              <button
                key={key}
                type="button"
                role="radio"
                aria-checked={color === key}
                aria-label={key}
                className={color === key ? 'on' : ''}
                style={{ background: css }}
                onClick={() => setColor(key)}
              />
            ))}
          </div>
        </div>
        <div className="field">
          <label>Icon</label>
          <div className="icon-grid" role="radiogroup" aria-label="Icon">
            {ICONS.map((i) => (
              <button
                key={i}
                type="button"
                role="radio"
                aria-checked={icon === i}
                aria-label={i}
                title={i}
                className={icon === i ? 'on' : ''}
                onClick={() => setIcon(i)}
              >
                <Icon name={i} size={17} />
              </button>
            ))}
          </div>
        </div>
        {cat && cat.transaction_count > 0 && (
          <div className="note warn">
            <Icon name="info" size={15} />
            <span>Deleting this category leaves its {cat.transaction_count} transaction(s) uncategorised.</span>
          </div>
        )}
      </div>
      <div className="drawer-foot">
        {cat && (
          <Button variant={confirmDelete ? 'primary' : 'ghost'} icon="trash-2" onClick={remove} disabled={saving} className={confirmDelete ? 'btn-danger' : ''}>
            {confirmDelete ? 'Confirm delete' : 'Delete'}
          </Button>
        )}
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>
          Cancel
        </Button>
        <Button variant="primary" type="submit" disabled={saving}>
          {cat ? 'Save changes' : 'Add category'}
        </Button>
      </div>
    </form>
  );
}

function TagForm({ tag, onClose }: { tag: Tag; onClose: () => void }) {
  return (
    <Dialog onClose={onClose} label={`Tag: ${tag.name}`} width={440}>
      <TagFormBody tag={tag} />
    </Dialog>
  );
}

function TagFormBody({ tag }: { tag: Tag }) {
  const close = useDialogClose();
  const { bump } = useShell();
  const [name, setName] = useState(tag.name);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api(`/tags/${tag.id}`, { method: 'PATCH', body: { name } });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
    }
  };
  const remove = async () => {
    if (!confirmDelete) return setConfirmDelete(true);
    try {
      await api(`/tags/${tag.id}`, { method: 'DELETE' });
      bump();
      close();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <form onSubmit={submit} style={{ display: 'contents' }}>
      <DrawerHead title={`#${tag.name}`} sub={`${tag.transaction_count} transaction${tag.transaction_count === 1 ? '' : 's'}`} />
      <div className="drawer-body">
        {error && (
          <div className="form-error" role="alert">
            {error}
          </div>
        )}
        <div className="field">
          <label htmlFor="tag-name">Name</label>
          <input id="tag-name" className="inp" value={name} onChange={(e) => setName(e.target.value)} required maxLength={64} />
        </div>
        <Link href={`/transactions?tag=${encodeURIComponent(tag.name)}`} className="btn btn-secondary btn-sm" style={{ textDecoration: 'none' }}>
          <Icon name="arrow-left-right" size={15} /> View transactions
        </Link>
        {tag.transaction_count > 0 && (
          <p className="muted" style={{ fontSize: 13 }}>
            Deleting the tag removes it from its transactions; the transactions stay.
          </p>
        )}
      </div>
      <div className="drawer-foot">
        <Button variant={confirmDelete ? 'primary' : 'ghost'} icon="trash-2" onClick={remove} className={confirmDelete ? 'btn-danger' : ''}>
          {confirmDelete ? 'Confirm delete' : 'Delete'}
        </Button>
        <span className="spacer" />
        <Button variant="secondary" onClick={close}>
          Cancel
        </Button>
        <Button variant="primary" type="submit">
          Rename
        </Button>
      </div>
    </form>
  );
}
