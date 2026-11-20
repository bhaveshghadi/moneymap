'use client';
import { Fragment, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useApi, useShell } from '../contexts/ShellCtx';
import type { Account, CasAction, CasDetail, CasFund, CasImportMode, CasRow, Investment } from '../lib/types';
import { api } from '../lib/api';
import { fmtDate, fmtNav, fmtUnits, rs } from '../lib/format';
import { Button } from '../primitives/Button';
import { ErrorState } from '../primitives/ErrorState';
import { Icon } from '../primitives/Icon';
import { Money } from '../primitives/Money';
import { Skeleton } from '../primitives/Skeleton';

const ACTION_LABEL: Record<CasAction, string> = {
  link: 'Already recorded — link it',
  convert: 'Turn the bank entry into a transfer',
  transfer: 'New transfer with',
  switch: 'Transfer between the two funds',
  before: 'Older than my records (adds to what was put in)',
  units: 'Units only — no money moved',
  skip: 'Leave out',
};

type FundChoice = CasImportMode | 'out';
const CHOICE_LABEL: Record<FundChoice, string> = {
  both: 'Fund and transactions',
  fund: 'Fund only',
  txns: 'Transactions only',
  out: 'Leave out',
};
const choiceOf = (f: CasFund): FundChoice => (f.skip ? 'out' : f.mode);
/** "Transactions only" adds rows to a fund you already have — not to a new one. */
const canTxns = (f: CasFund) => !f.skip && f.account_id !== null;

function actionsFor(r: CasRow): CasAction[] {
  if (r.existing) return ['skip'];
  const out: CasAction[] = [];
  if (r.match) out.push(r.match.type === 'transfer' ? 'link' : 'convert');
  if (r.pair_row_id && r.kind === 'switch_out') out.push('switch');
  if (r.amount !== 0) out.push('transfer', 'before');
  out.push('units', 'skip');
  return out;
}

export function CasReviewPage({ id }: { id: number }) {
  const router = useRouter();
  const { bump } = useShell();
  const { data, error, reload } = useApi<CasDetail>(`/investments/cas/${id}`);
  const accounts = useApi<Account[]>('/accounts?type=asset&type=cash&include_inactive=false');
  const investments = useApi<Investment[]>('/investments');
  const [cas, setCas] = useState<CasDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [bulkBank, setBulkBank] = useState('');
  const c = cas && cas.id === data?.id ? cas : data;

  const banks = accounts.data ?? [];
  const funds = useMemo(() => (investments.data ?? []).filter((i) => i.kind === 'mf'), [investments.data]);

  const call = async (path: string, method: string, body?: unknown) => {
    setBusy(true);
    setMsg(null);
    try {
      setCas(await api<CasDetail>(path, { method, body }));
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  if (error) return <div className="content-wrap"><div className="card"><ErrorState message={error} onRetry={reload} /></div></div>;
  if (!c) return <div className="content-wrap"><Skeleton variant="block" height={120} /><Skeleton variant="block" height={300} /></div>;

  const draft = c.status === 'draft';
  const fundOnly = new Set(c.funds.filter((f) => !f.skip && f.mode === 'fund').map((f) => f.id));
  const toImport = c.rows.filter((r) => !r.existing && r.action !== 'skip' && !fundOnly.has(r.fund_id)).length;
  const included = c.funds.filter((f) => !f.skip).length;
  const choose = (f: CasFund, choice: FundChoice) =>
    choice === 'out'
      ? call(`/investments/cas/${c.id}/funds/${f.id}`, 'PATCH', { skip: true })
      : call(`/investments/cas/${c.id}/funds/${f.id}/mode`, 'PATCH', { mode: choice });
  const setAll = async (choice: FundChoice) => {
    for (const f of c.funds) {
      if (choiceOf(f) === choice || (choice === 'txns' && !canTxns(f))) continue;
      await choose(f, choice);
    }
  };

  const doImport = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api<{ cas: CasDetail; accounts_created: number; opening_replaced?: number; funds_skipped?: number; funds_only?: number; linked?: number; converted?: number; created?: number; before?: number }>(
        `/investments/cas/${c.id}/import`,
        { method: 'POST' },
      );
      setCas(r.cas);
      bump();
      const parts = [
        r.accounts_created ? `${r.accounts_created} fund${r.accounts_created === 1 ? '' : 's'} added` : '',
        r.linked ? `${r.linked} linked` : '',
        r.converted ? `${r.converted} bank entr${r.converted === 1 ? 'y' : 'ies'} turned into transfers` : '',
        r.created ? `${r.created} transfer${r.created === 1 ? '' : 's'} added` : '',
        r.before ? `${r.before} older than your records` : '',
        r.funds_only ? `${r.funds_only} fund${r.funds_only === 1 ? '' : 's'} without transactions` : '',
        r.funds_skipped ? `${r.funds_skipped} fund${r.funds_skipped === 1 ? '' : 's'} left out` : '',
        r.opening_replaced ? 'an amount entered by hand replaced by the CAS history' : '',
      ].filter(Boolean);
      setMsg({ ok: true, text: `Imported. ${parts.join(', ')}.` });
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const discard = async () => {
    if (!confirmDiscard) return setConfirmDiscard(true);
    await api(`/investments/cas/${c.id}`, { method: 'DELETE' });
    bump();
    router.push('/investments');
  };

  return (
    <div className="content-wrap fade-in" style={{ maxWidth: 1180 }}>
      <div className="page-head">
        <div style={{ minWidth: 0 }}>
          <div className="muted" style={{ fontSize: 12.5 }}><Link href="/investments">Investments</Link> /</div>
          <h1>Mutual fund statement (CAS)</h1>
          <p>
            {c.filename}
            {c.period_from && c.period_to && <> · {fmtDate(c.period_from)} – {fmtDate(c.period_to)}</>}
            {c.gmail_message_id && <> · <Link href={`/inbox?open=${encodeURIComponent(c.gmail_message_id)}`}>source email</Link></>}
          </p>
        </div>
        <div className="actions">
          {draft && (
            <Button variant={confirmDiscard ? 'primary' : 'ghost'} className={confirmDiscard ? 'btn-danger' : ''} icon="trash-2" onClick={discard} disabled={busy}>
              {confirmDiscard ? 'Confirm discard' : 'Discard'}
            </Button>
          )}
          {draft && (
            <Button variant="primary" icon="download" onClick={doImport} disabled={busy || (toImport === 0 && fundOnly.size === 0)}>
              {busy
                ? 'Working…'
                : toImport || fundOnly.size
                  ? `Import ${included} fund${included === 1 ? '' : 's'}${toImport ? ` · ${toImport} row${toImport === 1 ? '' : 's'}` : ''}`
                  : 'Nothing new to import'}
            </Button>
          )}
        </div>
      </div>

      {msg && (
        <div className={msg.ok ? 'note privacy' : 'form-error'} role="status" style={{ marginBottom: 14 }}>
          {msg.ok && <Icon name="check" size={15} />} {msg.text}
          {msg.ok && <> <Link href="/investments"><b>See investments</b></Link></>}
        </div>
      )}
      {!draft && !msg && (
        <div className="note privacy" style={{ marginBottom: 14 }}>
          <Icon name="check" size={15} /> <span>Imported{c.imported_at ? ` on ${fmtDate(c.imported_at.slice(0, 10))}` : ''}.</span>
        </div>
      )}
      {c.funds.length === 0 && (
        <div className="note warn" style={{ marginBottom: 14 }}>
          <Icon name="triangle-alert" size={15} />
          <span>No funds could be read from this PDF. Ask for a <b>detailed</b> CAS (with transactions) from CAMS or KFintech.</span>
        </div>
      )}
      {(c.counts.existing ?? 0) > 0 && (
        <div className="note info" style={{ marginBottom: 14 }}>
          <Icon name="copy-check" size={15} />
          <span>{c.counts.existing} of {c.counts.rows} transactions were imported from an earlier CAS and are skipped.</span>
        </div>
      )}

      {c.funds.length > 0 && (
        <div className="card card-pad" style={{ marginBottom: 14 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', alignItems: 'baseline' }}>
            <h3 style={{ margin: '0 0 4px', fontSize: 15 }}>Funds in this CAS · importing {included} of {c.funds.length}</h3>
            {draft && c.funds.length > 1 && (
              <select
                className="inp"
                style={{ width: 'auto', padding: '5px 10px', fontSize: 13 }}
                aria-label="Set every fund to"
                value=""
                disabled={busy}
                onChange={(e) => e.target.value && setAll(e.target.value as FundChoice)}
              >
                <option value="">Set all to…</option>
                {(Object.keys(CHOICE_LABEL) as FundChoice[]).map((k) => (
                  <option key={k} value={k}>{CHOICE_LABEL[k]}{k === 'txns' ? ' (funds you have)' : ''}</option>
                ))}
              </select>
            )}
          </div>
          <p className="muted" style={{ margin: '0 0 12px', fontSize: 13 }}>
            For each fund choose what to bring in: the fund with its transactions, the <b>fund only</b> (today&apos;s units and value, no history),
            or the <b>transactions only</b> into a fund you already have. A fund you already have is joined, never added twice.
          </p>
          <div className="tbl-wrap">
            <table className="tbl" style={{ fontSize: 13 }}>
              <thead>
                <tr><th style={{ width: 190 }}>Import</th><th>Fund</th><th className="r hide-sm">Units</th><th className="r hide-sm">Value</th><th>Goes to</th></tr>
              </thead>
              <tbody>
                {c.funds.map((f) => (
                  <tr key={f.id} style={f.skip ? { opacity: 0.55 } : undefined}>
                    <td>
                      <select
                        className="inp"
                        style={{ padding: '6px 9px', fontSize: 13, minWidth: 150 }}
                        value={choiceOf(f)}
                        disabled={!draft || busy}
                        onChange={(e) => choose(f, e.target.value as FundChoice)}
                        aria-label={`What to import for ${f.scheme}`}
                      >
                        {(Object.keys(CHOICE_LABEL) as FundChoice[]).map((k) => (
                          <option key={k} value={k} disabled={k === 'txns' && !canTxns(f)}>
                            {CHOICE_LABEL[k]}{k === 'txns' && !canTxns(f) ? ' (pick your fund under Goes to)' : ''}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <div style={{ fontWeight: 600 }}>
                        {f.scheme}
                        {f.closing_units === 0 && <span className="badge neutral" style={{ marginLeft: 6 }}>No units left</span>}
                      </div>
                      <div className="muted" style={{ fontSize: 12 }}>{[f.amc, f.folio && `Folio ${f.folio}`, f.isin].filter(Boolean).join(' · ')} · {f.rows} rows</div>
                      {!f.skip && f.mode === 'fund' && (
                        <div style={{ fontSize: 12, color: 'var(--fg-3)', marginTop: 3 }}>
                          Fund only: today&apos;s {f.closing_units !== null ? `${fmtUnits(f.closing_units)} units` : 'units'} and value
                          {f.cost !== null && <>; what you paid, <Money amount={rs(f.cost)} interactive={false} />, counts as already invested</>}. Its {f.rows}{' '}
                          transactions and their bank payments aren&apos;t imported.
                        </div>
                      )}
                      {!f.skip && f.mode === 'txns' && (
                        <div style={{ fontSize: 12, color: 'var(--fg-3)', marginTop: 3 }}>
                          Transactions only: the rows are added to “{f.account_name}”; its name, units and price stay as they are.
                        </div>
                      )}
                      {!f.skip && f.mode !== 'fund' && f.already_imported > 0 && (
                        <div style={{ fontSize: 12, color: 'var(--fg-3)', marginTop: 3 }}>
                          {f.already_imported === f.rows ? 'All' : `${f.already_imported} of ${f.rows}`} transactions already imported from an earlier CAS — skipped.
                        </div>
                      )}
                      {!f.skip && f.account_id !== null && f.replaces_opening !== null && (
                        <div style={{ fontSize: 12, color: 'var(--amber-700)', marginTop: 3 }}>
                          Joins your fund “{f.account_name}”. The <Money amount={rs(f.replaces_opening)} interactive={false} /> you entered as already
                          invested is replaced by this CAS&apos;s older purchases, so it isn&apos;t counted twice.
                        </div>
                      )}
                      {!f.skip && f.mode === 'both' && f.account_id !== null && f.replaces_opening === null && f.already_imported < f.rows && (
                        <div style={{ fontSize: 12, color: 'var(--fg-3)', marginTop: 3 }}>
                          Joins your fund “{f.account_name}”{f.units_now !== null ? ` (${f.units_now.toLocaleString('en-IN')} units now)` : ''}.
                        </div>
                      )}
                      {f.opening_units > 0 && (
                        <div style={{ fontSize: 12, color: 'var(--amber-700)', marginTop: 3 }}>
                          Already had {fmtUnits(f.opening_units)} units on {c.period_from ? fmtDate(c.period_from) : 'the start date'} — their purchases aren&apos;t in
                          this CAS. For the full history, ask for a CAS from your first investment.
                        </div>
                      )}
                    </td>
                    <td className="r t-mono hide-sm">{f.closing_units !== null ? fmtUnits(f.closing_units) : '—'}</td>
                    <td className="r figure hide-sm">
                      {f.market_value !== null ? <Money amount={rs(f.market_value)} interactive={false} /> : '—'}
                      {f.nav !== null && <div className="muted" style={{ fontSize: 11.5 }}>NAV {fmtNav(f.nav)}</div>}
                    </td>
                    <td style={{ minWidth: 220 }}>
                      <select
                        className="inp"
                        aria-label={`Where ${f.scheme} goes`}
                        value={f.skip ? '' : (f.account_id ?? '')}
                        disabled={!draft || busy || f.skip}
                        onChange={(e) =>
                          call(`/investments/cas/${c.id}/funds/${f.id}`, 'PATCH', { account_id: e.target.value ? Number(e.target.value) : null })
                        }
                      >
                        <option value="">{f.skip ? 'Not imported' : `New fund “${f.scheme.slice(0, 40)}${f.scheme.length > 40 ? '…' : ''}”`}</option>
                        {funds.map((i) => (
                          <option key={i.id} value={i.id} disabled={c.funds.some((x) => x.id !== f.id && !x.skip && x.account_id === i.id)}>
                            {i.name}
                          </option>
                        ))}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {draft && c.rows.length > 0 && (
        <div className="card card-pad" style={{ marginBottom: 14, display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontSize: 13.5 }}>
            <b>Rows with no match</b> ({(c.counts.transfer ?? 0) + (c.counts.before ?? 0)}):
          </span>
          <Button variant="secondary" size="sm" disabled={busy} onClick={() => call(`/investments/cas/${c.id}/bulk`, 'POST', { action: 'before' })}>
            All older than my records
          </Button>
          <span className="muted" style={{ fontSize: 13 }}>or transfers with</span>
          <select className="inp" style={{ width: 'auto', minWidth: 160, padding: '5px 10px', fontSize: 13 }} value={bulkBank} onChange={(e) => setBulkBank(e.target.value)} aria-label="Bank account for all unmatched rows">
            <option value="">Choose account…</option>
            {banks.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
          <Button variant="secondary" size="sm" disabled={busy || !bulkBank} onClick={() => call(`/investments/cas/${c.id}/bulk`, 'POST', { action: 'transfer', bank_account_id: Number(bulkBank) })}>
            Apply
          </Button>
          <span className="muted" style={{ fontSize: 12.5, flexBasis: '100%' }}>
            “Older than my records” is for purchases from before your bank statements are in MoneyMap: they only add to what you put in, and your bank
            balance isn&apos;t touched. Matched rows already have their bank side recorded.
          </span>
        </div>
      )}

      {c.rows.length > 0 && (
        <div className="card">
          <div className="tbl-wrap" style={{ padding: '10px 6px 6px' }}>
            <table className="tbl cas-tbl">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Transaction</th>
                  <th className="r">Amount</th>
                  <th className="r hide-sm">Units</th>
                  <th className="r hide-sm">NAV</th>
                  <th>Money side</th>
                </tr>
              </thead>
              <tbody>
                {c.funds.map((f) => (
                  <Fragment key={f.id}>
                    <tr className="cat-group">
                      <td colSpan={6}>
                        {f.scheme}
                        {(f.skip || f.mode === 'fund') && (
                          <span className="muted" style={{ fontWeight: 500, textTransform: 'none', letterSpacing: 0 }}>
                            {f.skip ? ' · not imported' : ' · fund only: these transactions are not imported'}
                          </span>
                        )}
                      </td>
                    </tr>
                    {c.rows.filter((r) => r.fund_id === f.id).map((r) => (
                      <Row key={r.id} r={r} banks={banks} draft={draft && !f.skip && f.mode !== 'fund'} busy={busy} muted={f.mode === 'fund'}
                           onSet={(action, bank) => call(`/investments/cas/${c.id}/rows/${r.id}`, 'PATCH', { action, bank_account_id: bank ?? null })} />
                    ))}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {c.unparsed.length > 0 && (
        <details style={{ marginTop: 14 }}>
          <summary className="muted" style={{ cursor: 'pointer', fontSize: 13 }}>{c.unparsed.length} line(s) that couldn&apos;t be read</summary>
          <pre className="t-mono" style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}>{c.unparsed.join('\n')}</pre>
        </details>
      )}
    </div>
  );
}

function Row({ r, banks, draft, busy, muted = false, onSet }: {
  r: CasRow; banks: Account[]; draft: boolean; busy: boolean; muted?: boolean; onSet: (a: CasAction, bank?: number | null) => void;
}) {
  const status = r.existing ? ['neutral', 'Already imported'] : r.action === 'link' || r.action === 'convert' ? ['mint', 'Matched'] : r.action === 'skip' ? ['neutral', 'Left out'] : null;
  return (
    <tr className={muted || r.existing || r.action === 'skip' ? 'muted-row' : ''}>
      <td className="t-mono" style={{ whiteSpace: 'nowrap' }}>{fmtDate(r.date)}</td>
      <td style={{ maxWidth: 300 }}>
        <div style={{ fontWeight: 600 }}>{r.kind_label}</div>
        <div className="muted" style={{ fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis' }} title={r.description}>{r.description}</div>
      </td>
      <td className="r figure" style={{ whiteSpace: 'nowrap' }}>
        {r.amount !== 0 ? <Money amount={rs(Math.abs(r.amount) + (r.amount > 0 ? r.stamp_duty : 0))} interactive={false} /> : '—'}
        {r.stamp_duty > 0 && <div className="muted" style={{ fontSize: 11 }}>incl. ₹{(r.stamp_duty / 100).toFixed(2)} stamp duty</div>}
      </td>
      <td className="r t-mono hide-sm">{fmtUnits(r.units)}</td>
      <td className="r hide-sm">{fmtNav(r.nav)}</td>
      <td style={{ minWidth: 250 }}>
        {status && <span className={`badge ${status[0]}`} style={{ marginBottom: 6 }}>{status[1]}</span>}
        {draft && !r.existing ? (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            <select className="inp" style={{ width: 'auto', maxWidth: 260, padding: '5px 8px', fontSize: 12.5 }} value={r.action} disabled={busy}
                    aria-label="What to do with the money" onChange={(e) => onSet(e.target.value as CasAction, r.bank_account_id ?? banks[0]?.id)}>
              {actionsFor(r).map((a) => <option key={a} value={a}>{ACTION_LABEL[a]}{a === 'transfer' ? '…' : ''}</option>)}
            </select>
            {r.action === 'transfer' && (
              <select className="inp" style={{ width: 'auto', padding: '5px 8px', fontSize: 12.5 }} value={r.bank_account_id ?? ''} disabled={busy}
                      aria-label="Bank account" onChange={(e) => onSet('transfer', Number(e.target.value))}>
                {r.bank_account_id === null && <option value="">Choose…</option>}
                {banks.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            )}
          </div>
        ) : (
          !r.existing && <span style={{ fontSize: 12.5 }}>{ACTION_LABEL[r.action]}</span>
        )}
        {r.match && (r.action === 'link' || r.action === 'convert') && (
          <div className="muted" style={{ fontSize: 11.5, marginTop: 4 }}>
            {fmtDate(r.match.date)} · {r.match.description.slice(0, 48)}
          </div>
        )}
      </td>
    </tr>
  );
}
