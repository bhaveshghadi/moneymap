'use client';
import { useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { Button } from '../primitives/Button';
import { UploadStatement } from '../shared/UploadStatement';
import { useApi } from '../contexts/ShellCtx';
import type { Account, StatementSummary } from '../lib/types';
import { fromUtc } from '../lib/format';
import { Skeleton } from '../primitives/Skeleton';
import { EmptyState } from '../primitives/EmptyState';
import { ErrorState } from '../primitives/ErrorState';
import { Icon } from '../primitives/Icon';

export function StatementsPage() {
  const { data, error, reload } = useApi<StatementSummary[]>('/statements');
  const accounts = useApi<Account[]>('/accounts?type=asset&type=cash');
  const name = (id: number | null) => accounts.data?.find((a) => a.id === id)?.name ?? '—';
  const sp = useSearchParams();
  const [uploading, setUploading] = useState(sp.get('upload') === '1');

  return (
    <div className="content-wrap fade-in">
      <div className="page-head">
        <div>
          <h1>Statements</h1>
          <p>Statement PDFs you&apos;ve opened for import — upload one from your bank, or start from an email in the Inbox.</p>
        </div>
        <div className="actions">
          <Link href="/inbox" className="btn btn-secondary" style={{ textDecoration: 'none' }}>
            <Icon name="inbox" size={15} /> From Inbox
          </Link>
          <Button variant="primary" icon="upload" onClick={() => setUploading(true)}>Upload statement</Button>
        </div>
      </div>
      <div className="card">
        {error ? (
          <ErrorState message={error} onRetry={reload} />
        ) : !data ? (
          <div className="card-pad stack" style={{ gap: 8 }}><Skeleton variant="row" count={3} /></div>
        ) : data.length === 0 ? (
          <EmptyState
            icon="file-text"
            title="No statements yet"
            body="Upload a statement PDF downloaded from your bank's website, or open a statement email in the Inbox and click “Import statement” on its PDF."
            action={{ label: 'Upload statement', onClick: () => setUploading(true) }}
          />
        ) : (
          <div className="tbl-wrap" style={{ padding: '16px 6px 6px' }}>
            <table className="tbl">
              <thead>
                <tr>
                  <th>Statement</th>
                  <th>Account</th>
                  <th className="r">Rows</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {data.map((s) => {
                  const needs = s.counts.needs_category + s.counts.needs_account;
                  return (
                    <tr key={s.id}>
                      <td>
                        <Link href={`/statements/${s.id}`} style={{ fontWeight: 600 }}>{s.filename}</Link>
                        <div className="muted" style={{ fontSize: 12 }}>
                          {s.doc_type === 'card_statement' ? 'Credit card' : 'Bank'}{s.account_last4 ? ` · ending ${s.account_last4}` : ''} · {s.upload_path ? 'uploaded' : 'from email'} {fromUtc(s.created_at).toLocaleDateString('en-IN')}
                        </div>
                      </td>
                      <td>{name(s.account_id)}</td>
                      <td className="r t-mono">{s.row_count}</td>
                      <td>
                        {s.status === 'imported' ? (
                          <span className="badge brand">Imported {s.imported_count}</span>
                        ) : needs ? (
                          <span className="badge cau">{needs} need you</span>
                        ) : (
                          <span className="badge mint">Ready to import</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {uploading && <UploadStatement onClose={() => setUploading(false)} />}
    </div>
  );
}
