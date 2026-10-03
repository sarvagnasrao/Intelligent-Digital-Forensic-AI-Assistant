/**
 * StoragePage — overall storage management, per-case, with every ingested file
 * visible.
 *
 * The rule this page is built around is AGENTS.md §16's, which by now has been
 * applied in nine places: **a value that could not be measured is an em dash
 * with a reason, never a plausible 0.**
 *
 * It matters more here than anywhere else. The other pages that got the same
 * treatment report on services (is the database up) or on one job (is the ETA
 * known). This one reports *capacity*, and the failure mode of a fabricated 0
 * runs in a specific direction: "0 MB" for a case that holds a 635 MB disk
 * image reads as "this case costs nothing", and the operator re-acquires
 * evidence into a disk that is already full. So:
 *
 *   * a section the backend could not walk shows "—" and its `reason`, in the
 *     words the backend used — not an empty table and not a zero;
 *   * sizes come in two columns, `recorded` (what the database says) and
 *     `on disk` (what was just measured), because they genuinely disagree: a
 *     `file_size_bytes` column written at upload is never re-measured, so a row
 *     whose file was deleted outside the app carries its size for ever. The
 *     difference between the columns IS the finding, so the page states it
 *     rather than picking one;
 *   * a request that failed is shown as a failure to ask, never as an empty
 *     result (the shape §25/§31 found in EvidencePage's queue and history);
 *   * nothing here deletes anything. Reclamation needs an audit trail and a
 *     decision, and this page exists so that decision can be made on evidence.
 */
import React, { useState, useEffect, useCallback } from 'react'
import {
  HardDrive, Folder, Database, AlertCircle, RefreshCw, ChevronRight,
  FileText, Archive, Search, Layers,
} from 'lucide-react'
import {
  getStorageOverview, getCaseStorage, getCaseStorageFiles, apiErrorMessage,
} from '../api/client'
import PageLayout from '../components/PageLayout'

/** The one thing that may stand in for a measurement we do not have. */
const NOT_MEASURED = '—'

const TONE = {
  ok:          { color: '#10b981' },
  error:       { color: '#ef4444' },
  unavailable: { color: '#f59e0b' },
  unknown:     { color: 'var(--ink-2)' },
}
const toneFor = (s) => TONE[s] || TONE.unknown

/** `== null` rather than `||`: 0 bytes is a real measurement here. */
const showSize = (v) =>
  (typeof v === 'number' && Number.isFinite(v)
    ? (v === 0 ? '0 B' : humanBytes(v))
    : NOT_MEASURED)

function humanBytes(n) {
  if (typeof n !== 'number' || !Number.isFinite(n)) return NOT_MEASURED
  let v = Number(n)
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  let i = 0
  while (Math.abs(v) >= 1024 && i < units.length - 1) { v /= 1024; i += 1 }
  return i === 0 ? `${v} B` : `${v.toFixed(1)} ${units[i]}`
}

const PROVENANCE_LABEL = {
  match: 'verified',
  mismatch: 'will be refused',
  unattributed: 'unvouched',
  never_indexed: 'never indexed',
}

// ── small building blocks ──────────────────────────────────────────────────

const card = {
  background: 'var(--surface-1)',
  border: '1px solid var(--line-DEFAULT)',
  borderRadius: 12,
  padding: '18px 20px',
}

const smallLabel = {
  fontSize: 10,
  color: 'var(--ink-3)',
  textTransform: 'uppercase',
  letterSpacing: '0.08em',
}

function Dot({ state, label }) {
  const tone = toneFor(state)
  return (
    <span
      role="img"
      aria-label={state || 'not measured'}
      title={label || state || 'not measured'}
      style={{
        display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
        background: tone.color, marginRight: 8, flexShrink: 0,
      }}
    />
  )
}

/**
 * A stat with its measurement state beside it. When the backend could not
 * measure, the value is the em dash and the reason is printed underneath — the
 * two come from the same backend object for the same reason, so they cannot
 * disagree (AGENTS.md §21, TRAP 9).
 */
function Stat({ label, value, state, reason, alarm }) {
  return (
    <div>
      <p style={smallLabel}>{label}</p>
      <div style={{ display: 'flex', alignItems: 'center', marginTop: 6 }}>
        <Dot state={state} />
        <span style={{
          fontSize: 17, fontWeight: 600,
          color: alarm ? '#ef4444' : 'var(--ink-0)',
          fontFamily: 'monospace',
        }}>
          {state === 'unknown' || value == null ? NOT_MEASURED : value}
        </span>
      </div>
      {reason && (
        <p style={{
          fontSize: 10, color: 'var(--ink-3)', fontFamily: 'monospace',
          marginTop: 5, lineHeight: 1.5,
        }}>
          {reason}
        </p>
      )}
    </div>
  )
}

function Bar({ used, total }) {
  if (typeof used !== 'number' || typeof total !== 'number' || !total) {
    return <div style={{ height: 6, borderRadius: 3, background: 'var(--surface-3)' }} />
  }
  const pct = Math.max(0, Math.min(100, (used / total) * 100))
  const color = pct >= 90 ? '#ef4444' : pct >= 75 ? '#f59e0b' : 'var(--brand-light, #6366f1)'
  return (
    <div
      role="meter"
      aria-valuenow={Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuetext={`${pct.toFixed(1)}% used`}
      style={{ height: 6, borderRadius: 3, background: 'var(--surface-3)', overflow: 'hidden' }}
    >
      <div style={{ width: `${pct}%`, height: '100%', background: color }} />
    </div>
  )
}

/** A request that did not complete. Never rendered as an empty result. */
function LoadFailure({ error, what, onRetry }) {
  return (
    <div style={{ ...card, borderColor: '#f59e0b', display: 'flex', gap: 14 }}>
      <AlertCircle size={18} style={{ color: '#f59e0b', flexShrink: 0, marginTop: 2 }} />
      <div style={{ minWidth: 0 }}>
        <p style={{ fontSize: 14, fontWeight: 600, color: 'var(--ink-0)', marginBottom: 6 }}>
          Could not load {what}
        </p>
        <p style={{ fontSize: 12, color: 'var(--ink-1)', lineHeight: 1.6, margin: 0 }}>
          The request did not complete, so nothing here was measured. This is
          not a statement that storage is empty — it says only that the page
          could not ask.
        </p>
        {error && (
          <p style={{ fontSize: 11, color: 'var(--ink-2)', fontFamily: 'monospace', marginTop: 8, wordBreak: 'break-word' }}>
            {apiErrorMessage(error, 'No detail available.')}
          </p>
        )}
        {onRetry && (
          <button
            onClick={onRetry}
            style={{
              marginTop: 12, display: 'inline-flex', alignItems: 'center', gap: 6,
              background: 'var(--surface-2)', border: '1px solid var(--line-DEFAULT)',
              color: 'var(--ink-0)', borderRadius: 8, padding: '6px 12px',
              fontSize: 12, cursor: 'pointer',
            }}
          >
            <RefreshCw size={13} /> Retry
          </button>
        )}
      </div>
    </div>
  )
}

// ── volumes ────────────────────────────────────────────────────────────────

function VolumeRow({ v }) {
  const pct = typeof v.pct_used === 'number' ? v.pct_used : null
  return (
    <tr>
      <td style={{ padding: '9px 10px', borderBottom: '1px solid var(--line-DEFAULT)', fontFamily: 'monospace', fontSize: 11, color: 'var(--ink-1)' }}>
        {v.mountpoint}
        <div style={{ color: 'var(--ink-3)', fontSize: 10 }}>{v.fstype || 'unknown'}{v.device ? ` · ${v.device}` : ''}</div>
      </td>
      <td style={{ padding: '9px 10px', borderBottom: '1px solid var(--line-DEFAULT)', fontFamily: 'monospace', fontSize: 11, color: 'var(--ink-1)', whiteSpace: 'nowrap' }}>
        {humanBytes(v.used_human !== undefined ? parseHuman(v.used_human) : v.used_bytes)}
      </td>
      <td style={{ padding: '9px 10px', borderBottom: '1px solid var(--line-DEFAULT)', fontFamily: 'monospace', fontSize: 11, color: 'var(--ink-1)', whiteSpace: 'nowrap' }}>
        {showSize(v.free_bytes)}
      </td>
      <td style={{ padding: '9px 10px', borderBottom: '1px solid var(--line-DEFAULT)', fontFamily: 'monospace', fontSize: 11, color: 'var(--ink-1)', whiteSpace: 'nowrap' }}>
        {showSize(v.total_bytes)}
      </td>
      <td style={{ padding: '9px 10px', borderBottom: '1px solid var(--line-DEFAULT)', width: 140 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ flex: 1 }}><Bar used={v.used_bytes} total={v.total_bytes} /></div>
          <span style={{ fontSize: 10, fontFamily: 'monospace', color: 'var(--ink-2)', width: 42, textAlign: 'right' }}>
            {pct == null ? NOT_MEASURED : `${pct.toFixed(1)}%`}
          </span>
        </div>
      </td>
    </tr>
  )
}

/** The backend already sends human strings; prefer our own from raw bytes. */
function parseHuman(s) {
  if (typeof s !== 'string') return null
  const m = /^([\d.]+)\s*(B|KB|MB|GB|TB|PB)$/.exec(s.trim())
  if (!m) return null
  const mult = { B: 1, KB: 1024, MB: 1048576, GB: 1073741824, TB: 1099511627776, PB: 1125899906842624 }[m[2]]
  return parseFloat(m[1]) * mult
}

// ── per-case table ─────────────────────────────────────────────────────────

function CaseRow({ row, onOpen, expanded, onToggle }) {
  const prov = PROVENANCE_LABEL[row.index_provenance_state] || (row.index_provenance_state ? row.index_provenance_state : null)
  const mismatch = row.index_provenance_state === 'mismatch'
  return (
    <>
      <tr
        onClick={() => onToggle(row.case_id)}
        style={{ cursor: 'pointer', background: expanded ? 'var(--surface-2)' : 'transparent' }}
      >
        <td style={{ padding: '10px', borderBottom: '1px solid var(--line-DEFAULT)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <ChevronRight
              size={13}
              style={{
                color: 'var(--ink-3)', flexShrink: 0,
                transform: expanded ? 'rotate(90deg)' : 'none',
                transition: 'transform 120ms',
              }}
            />
            <span style={{ fontSize: 12, color: 'var(--ink-0)' }}>{row.case_name || row.case_id.slice(0, 8)}</span>
          </div>
          <div style={{ fontSize: 10, color: 'var(--ink-3)', fontFamily: 'monospace', marginLeft: 19 }}>
            {row.case_id.slice(0, 8)} · {row.status}
          </div>
        </td>
        <td style={{ padding: '10px', borderBottom: '1px solid var(--line-DEFAULT)', fontFamily: 'monospace', fontSize: 11, color: 'var(--ink-1)', whiteSpace: 'nowrap' }}>
          {showSize(row.evidence_disk_bytes)}
        </td>
        <td style={{ padding: '10px', borderBottom: '1px solid var(--line-DEFAULT)', fontFamily: 'monospace', fontSize: 11, color: 'var(--ink-1)', whiteSpace: 'nowrap' }}>
          {showSize(row.index_bytes)}
        </td>
        <td style={{ padding: '10px', borderBottom: '1px solid var(--line-DEFAULT)', fontFamily: 'monospace', fontSize: 11, color: 'var(--ink-1)', whiteSpace: 'nowrap' }}>
          {showSize((row.evidence_disk_bytes || 0) + (row.index_bytes || 0))}
        </td>
        <td style={{ padding: '10px', borderBottom: '1px solid var(--line-DEFAULT)', fontFamily: 'monospace', fontSize: 11, whiteSpace: 'nowrap' }}>
          <span style={{ color: row.evidence_missing ? '#ef4444' : 'var(--ink-2)' }}>
            {row.evidence_missing > 0 ? `${row.evidence_missing} missing` : 'all present'}
          </span>
        </td>
        <td style={{ padding: '10px', borderBottom: '1px solid var(--line-DEFAULT)', fontFamily: 'monospace', fontSize: 10, whiteSpace: 'nowrap' }}>
          <span style={{
            color: mismatch ? '#ef4444' : 'var(--ink-2)',
          }} title={row.index_provenance_reason || ''}>
            {prov || (row.index_bytes == null ? NOT_MEASURED : 'n/a')}
          </span>
        </td>
        <td style={{ padding: '10px', borderBottom: '1px solid var(--line-DEFAULT)', whiteSpace: 'nowrap' }}>
          <button
            onClick={(e) => { e.stopPropagation(); onOpen(row.case_id) }}
            style={{
              background: 'var(--surface-2)', border: '1px solid var(--line-DEFAULT)',
              color: 'var(--ink-1)', borderRadius: 6, padding: '4px 9px',
              fontSize: 10, cursor: 'pointer',
            }}
          >
            Files
          </button>
        </td>
      </tr>
    </>
  )
}

// ── file inventory ─────────────────────────────────────────────────────────

const th = {
  padding: '9px 10px', textAlign: 'left', fontSize: 10, color: 'var(--ink-3)',
  textTransform: 'uppercase', letterSpacing: '0.07em',
  borderBottom: '1px solid var(--line-DEFAULT)', whiteSpace: 'nowrap',
}
const td = {
  padding: '8px 10px', fontSize: 11, color: 'var(--ink-1)',
  borderBottom: '1px solid var(--line-DEFAULT)', verticalAlign: 'top',
}

function FileInventory({ caseId, onClose }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [kind, setKind] = useState('all')
  const [includeArchived, setIncludeArchived] = useState(false)
  const [filter, setFilter] = useState('')

  const load = useCallback(async () => {
    setError(null)
    try {
      const res = await getCaseStorageFiles(caseId, kind, includeArchived)
      setData(res.data)
    } catch (e) {
      setError(e)
      setData(null)
    }
  }, [caseId, kind, includeArchived])

  useEffect(() => { load() }, [load])

  const rows = (data?.files || []).filter((f) =>
    !filter || (f.name || '').toLowerCase().includes(filter.toLowerCase()))

  return (
    <div style={{ ...card, marginTop: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <p style={{ ...smallLabel, margin: 0 }}>File inventory · {caseId.slice(0, 8)}</p>
          <p style={{ fontSize: 11, color: 'var(--ink-2)', margin: '4px 0 0' }}>
            {data
              ? `${rows.length} shown of ${data.count} rows · ${humanBytes(data.disk_bytes)} on disk · ${data.missing_count} missing file(s)`
              : ' '}
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter by name"
            style={{
              background: 'var(--surface-2)', border: '1px solid var(--line-DEFAULT)',
              borderRadius: 6, padding: '5px 9px', fontSize: 11,
              color: 'var(--ink-0)', width: 150,
            }}
          />
          {['all', 'evidence', 'artifact'].map((k) => (
            <button
              key={k}
              onClick={() => setKind(k)}
              style={{
                background: kind === k ? 'var(--brand-glow)' : 'var(--surface-2)',
                border: '1px solid var(--line-DEFAULT)',
                color: kind === k ? 'var(--brand-light, #818cf8)' : 'var(--ink-2)',
                borderRadius: 6, padding: '5px 10px', fontSize: 10, cursor: 'pointer',
              }}
            >
              {k}
            </button>
          ))}
          <label style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 10, color: 'var(--ink-2)', cursor: 'pointer' }}>
            <input type="checkbox" checked={includeArchived} onChange={(e) => setIncludeArchived(e.target.checked)} />
            show archived
          </label>
          <button
            onClick={onClose}
            style={{
              background: 'transparent', border: '1px solid var(--line-DEFAULT)',
              color: 'var(--ink-2)', borderRadius: 6, padding: '5px 10px',
              fontSize: 10, cursor: 'pointer',
            }}
          >
            Close
          </button>
        </div>
      </div>

      {error ? (
        <div style={{ marginTop: 12 }}>
          <LoadFailure error={error} what="this case's file list" onRetry={load} />
        </div>
      ) : !data ? (
        <p style={{ fontSize: 11, color: 'var(--ink-3)', marginTop: 14, fontFamily: 'monospace' }}>
          Measuring…
        </p>
      ) : (
        <div style={{ overflowX: 'auto', marginTop: 12 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={th}>File</th>
                <th style={th}>Kind</th>
                <th style={th}>Status</th>
                <th style={th}>Recorded</th>
                <th style={th}>On disk</th>
                <th style={th}>Path</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr><td colSpan={6} style={{ ...td, color: 'var(--ink-3)' }}>
                  {filter ? `No file name matches "${filter}".` : 'The backend reported zero rows for this filter.'}
                </td></tr>
              ) : rows.map((f) => (
                <tr key={`${f.kind}-${f.id}`}>
                  <td style={{ ...td, color: 'var(--ink-0)' }}>{f.name}</td>
                  <td style={{ ...td, fontFamily: 'monospace', fontSize: 10 }}>{f.kind}</td>
                  <td style={{ ...td, fontFamily: 'monospace', fontSize: 10 }}>{f.status}</td>
                  <td style={{ ...td, fontFamily: 'monospace', fontSize: 10 }}>{showSize(f.db_bytes)}</td>
                  <td style={{ ...td, fontFamily: 'monospace', fontSize: 10, color: f.missing ? '#ef4444' : 'var(--ink-1)' }}>
                    {f.missing ? 'missing' : showSize(f.disk_bytes)}
                  </td>
                  <td style={{ ...td, fontFamily: 'monospace', fontSize: 9, color: 'var(--ink-3)', wordBreak: 'break-all', maxWidth: 320 }}>
                    {f.path || NOT_MEASURED}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && data.disk_bytes !== data.db_bytes && (
        <p style={{ fontSize: 10, color: 'var(--ink-2)', fontFamily: 'monospace', marginTop: 10, lineHeight: 1.6 }}>
          Recorded {humanBytes(data.db_bytes)} vs measured {humanBytes(data.disk_bytes)}.
          The difference is rows whose file is gone: `file_size_bytes` is written
          once at upload and never re-measured, so it keeps reporting a size for
          evidence that is no longer on disk.
        </p>
      )}
    </div>
  )
}

// ── the page ───────────────────────────────────────────────────────────────

export default function StoragePage() {
  const [overview, setOverview] = useState(null)
  const [error, setError] = useState(null)
  const [detail, setDetail] = useState(null)
  const [detailError, setDetailError] = useState(null)
  const [openCase, setOpenCase] = useState(null)
  const [expanded, setExpanded] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setError(null)
    try {
      const res = await getStorageOverview()
      setOverview(res.data)
    } catch (e) {
      setError(e)
      setOverview(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const openFiles = useCallback(async (caseId) => {
    setDetailError(null)
    setDetail(null)
    setOpenCase(caseId)
    try {
      const res = await getCaseStorage(caseId)
      setDetail(res.data)
    } catch (e) {
      setDetailError(e)
    }
  }, [])

  const refreshBtn = (
    <button
      onClick={load}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        background: 'var(--surface-2)', border: '1px solid var(--line-DEFAULT)',
        color: 'var(--ink-0)', borderRadius: 8, padding: '7px 13px',
        fontSize: 12, cursor: 'pointer',
      }}
    >
      <RefreshCw size={13} /> Re-measure
    </button>
  )

  if (error && !overview) {
    return (
      <PageLayout title="Storage" subtitle="Measured, not estimated" actions={refreshBtn}>
        <LoadFailure error={error} what="storage" onRetry={load} />
      </PageLayout>
    )
  }

  if (loading && !overview) {
    return (
      <PageLayout title="Storage" subtitle="Measured, not estimated">
        <p style={{ fontSize: 12, color: 'var(--ink-2)', fontFamily: 'monospace' }}>Measuring…</p>
      </PageLayout>
    )
  }

  const t = overview?.totals || {}
  const casesTree = overview?.cases_tree || {}
  const indexTree = overview?.index_tree || {}
  const orphans = overview?.orphan_case_dirs || {}
  const rows = overview?.cases?.items || []

  return (
    <PageLayout
      title="Storage"
      subtitle="Every figure below was measured on disk just now. A dash means it could not be measured — never a zero."
      actions={refreshBtn}
    >
      {/* ── headline figures ─────────────────────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 14, marginBottom: 14 }}>
        <div style={card}>
          <Stat
            label="Cases tree (measured)"
            value={humanBytes(casesTree.bytes)}
            state={casesTree.state}
            reason={casesTree.reason}
          />
        </div>
        <div style={card}>
          <Stat
            label="Vector index tree"
            value={humanBytes(indexTree.bytes)}
            state={indexTree.state}
            reason={indexTree.reason || indexTree.counted_in}
          />
        </div>
        <div style={card}>
          <Stat
            label="Evidence on disk"
            value={humanBytes(t.evidence_disk_bytes)}
            state={t.evidence_disk_bytes == null ? 'unknown' : 'ok'}
            reason={t.evidence_missing ? `${t.evidence_missing} row(s) point at a file that is gone` : null}
            alarm={t.evidence_missing > 0}
          />
        </div>
        <div style={card}>
          <Stat
            label="Measured total"
            value={humanBytes(t.total_disk_bytes)}
            state={t.total_disk_bytes == null ? 'unknown' : 'ok'}
            reason="Evidence files plus vector indexes"
          />
        </div>
      </div>

      {error && (
        <div style={{ marginBottom: 14 }}>
          <LoadFailure error={error} what="storage" onRetry={load} />
        </div>
      )}

      {/* ── volumes ──────────────────────────────────────────────────── */}
      <div style={{ ...card, marginBottom: 14 }}>
        <p style={{ ...smallLabel, margin: 0 }}>Volumes</p>
        {overview?.volumes?.state === 'ok' && overview.volumes.items.length > 0 ? (
          <div style={{ overflowX: 'auto', marginTop: 10 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={th}>Mount</th><th style={th}>Used</th><th style={th}>Free</th>
                  <th style={th}>Total</th><th style={th}>Utilisation</th>
                </tr>
              </thead>
              <tbody>
                {overview.volumes.items.map((v, i) => (
                  <VolumeRow key={`${v.mountpoint}-${i}`} v={v} />
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p style={{ fontSize: 11, color: 'var(--ink-2)', marginTop: 10, fontFamily: 'monospace' }}>
            {overview?.volumes?.reason
              ? `Not measured — ${overview.volumes.reason}`
              : 'No volume could be read.'}
          </p>
        )}
      </div>

      {/* ── per-case table ───────────────────────────────────────────── */}
      <div style={{ ...card }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
          <p style={{ ...smallLabel, margin: 0 }}>Per case</p>
          <p style={{ fontSize: 10, color: 'var(--ink-3)', fontFamily: 'monospace', margin: 0 }}>
            {rows.length} case(s) · {t.artifacts} artifact(s) · {t.evidence_missing} missing file(s)
          </p>
        </div>

        {t.scoped_to_your_cases && (
          <p style={{ fontSize: 11, color: '#f59e0b', marginTop: 10, lineHeight: 1.6 }}>
            <Dot state="unavailable" />{' '}
            {t.cases_hidden} case(s) exist that you are not assigned to. Every
            figure on this page covers only the {rows.length} case(s) listed
            below — these numbers are not the whole install.
          </p>
        )}

        {rows.length === 0 ? (
          <p style={{ fontSize: 11, color: 'var(--ink-3)', marginTop: 12 }}>
            {t.cases_hidden > 0
              ? `You have no access to any of the ${t.cases_hidden} case(s) in this installation. Nothing below was measured, which is not the same as there being nothing there.`
              : 'The database reports zero cases. That is a measurement, not a placeholder — the table above the volumes will say so if the cases directory itself could not be read.'}
          </p>
        ) : (
          <div style={{ overflowX: 'auto', marginTop: 10 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={th}>Case</th><th style={th}>Evidence on disk</th>
                  <th style={th}>Index</th><th style={th}>Total</th>
                  <th style={th}>Files</th><th style={th}>Provenance</th><th style={th} />
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <CaseRow
                    key={row.case_id}
                    row={row}
                    expanded={expanded === row.case_id}
                    onToggle={(id) => setExpanded((cur) => (cur === id ? null : id))}
                    onOpen={openFiles}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── per-case detail ──────────────────────────────────────────── */}
      {openCase && (
        <div style={{ ...card, marginTop: 14 }}>
          <p style={{ ...smallLabel, margin: 0 }}>
            Case breakdown · {detail?.case_name || openCase.slice(0, 8)}
          </p>
          {detailError ? (
            <div style={{ marginTop: 12 }}>
              <LoadFailure error={detailError} what="this case's breakdown" onRetry={() => openFiles(openCase)} />
            </div>
          ) : !detail ? (
            <p style={{ fontSize: 11, color: 'var(--ink-3)', marginTop: 12, fontFamily: 'monospace' }}>Measuring…</p>
          ) : (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 12, marginTop: 12 }}>
                <Stat label="Evidence on disk" value={humanBytes(detail.evidence.disk_bytes)} state="ok"
                      reason={detail.evidence.missing ? `${detail.evidence.missing} row(s) missing on disk` : null}
                      alarm={detail.evidence.missing > 0} />
                <Stat label="Recorded by DB" value={humanBytes(detail.evidence.db_bytes)} state="ok"
                      reason="Written at upload, never re-measured" />
                <Stat label="Extracted files" value={humanBytes(detail.extracted.bytes)}
                      state={detail.extracted.state}
                      reason={detail.extracted.reason} />
                <Stat label="Viewable artifacts" value={humanBytes(detail.artifacts.disk_bytes)} state="ok"
                      reason={`${detail.artifacts.count} row(s), ${detail.artifacts.missing} missing`} />
                <Stat label="Vector index" value={humanBytes(detail.index.bytes)}
                      state={detail.index.state}
                      reason={detail.index.reason ||
                        (detail.index.location === 'in_cases'
                          ? 'Indexed inside the cases directory, not at the canonical location'
                          : detail.index.location === 'absent'
                            ? 'No vector index for this case'
                            : null)} />
              </div>

              {detail.index.provenance?.state && (
                <p style={{ fontSize: 10, color: 'var(--ink-2)', fontFamily: 'monospace', marginTop: 10, lineHeight: 1.6 }}>
                  Index provenance: {PROVENANCE_LABEL[detail.index.provenance.state] || detail.index.provenance.state}
                  {detail.index.provenance.chunking_schemes?.length
                    ? ` · chunking ${detail.index.provenance.chunking_schemes.join(', ')}`
                    : ''}
                  {detail.index.provenance.reason ? ` · ${detail.index.provenance.reason}` : ''}
                </p>
              )}

              {Array.isArray(detail.evidence.unclaimed_files) && detail.evidence.unclaimed_files.length > 0 && (
                <p style={{ fontSize: 10, color: '#f59e0b', fontFamily: 'monospace', marginTop: 8, lineHeight: 1.6 }}>
                  {detail.evidence.unclaimed_files.length} file(s) sit in this case's evidence
                  directory with no database row claiming them. They are listed
                  below and are not deleted by this page.
                </p>
              )}
            </>
          )}
        </div>
      )}

      {openCase && <FileInventory caseId={openCase} onClose={() => { setOpenCase(null); setDetail(null); setDetailError(null) }} />}

      {/* ── orphan directories ───────────────────────────────────────── */}
      <div style={{ ...card, marginTop: 14 }}>
        <p style={{ ...smallLabel, margin: 0 }}>Case directories with no database row</p>
        {orphans.state === 'unavailable' && orphans.count === null ? (
          <p style={{ fontSize: 11, color: 'var(--ink-2)', marginTop: 10, fontFamily: 'monospace' }}>
            Not shown — {orphans.reason}
          </p>
        ) : orphans.state === 'ok' && orphans.count === 0 ? (
          <p style={{ fontSize: 11, color: 'var(--ink-2)', marginTop: 10 }}>
            None — every directory under the cases tree belongs to a case in the database.
          </p>
        ) : orphans.state === 'ok' ? (
          <>
            <p style={{ fontSize: 11, color: 'var(--ink-2)', marginTop: 8, lineHeight: 1.6 }}>
              {orphans.count} director{orphans.count === 1 ? 'y' : 'ies'} occupy{' '}
              <span style={{ fontFamily: 'monospace', color: 'var(--ink-1)' }}>{humanBytes(orphans.bytes)}</span>{' '}
              and correspond to no case row. They are measured here and left on
              disk — deleting evidence directories is an operator decision, not
              something a status page should do.
            </p>
            <details style={{ marginTop: 10 }}>
              <summary style={{ fontSize: 11, color: 'var(--brand-light, #818cf8)', cursor: 'pointer' }}>
                Show the {orphans.count} largest
              </summary>
              <div style={{ overflowX: 'auto', marginTop: 8 }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead><tr><th style={th}>Directory</th><th style={th}>Size</th><th style={th}>Files</th></tr></thead>
                  <tbody>
                    {orphans.items.slice(0, 50).map((o) => (
                      <tr key={o.case_id}>
                        <td style={{ ...td, fontFamily: 'monospace', fontSize: 10 }}>{o.case_id}</td>
                        <td style={{ ...td, fontFamily: 'monospace', fontSize: 10 }}>{showSize(o.bytes)}</td>
                        <td style={{ ...td, fontFamily: 'monospace', fontSize: 10 }}>
                          {o.files == null ? NOT_MEASURED : o.files}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </>
        ) : (
          <p style={{ fontSize: 11, color: 'var(--ink-2)', marginTop: 10, fontFamily: 'monospace' }}>
            Not measured — {orphans.reason || 'the cases tree could not be walked'}
          </p>
        )}
      </div>

      <p style={{ fontSize: 10, color: 'var(--ink-3)', fontFamily: 'monospace', marginTop: 14, lineHeight: 1.6 }}>
        This page only measures. It never deletes, moves or archives anything —
        storage reclamation needs a decision and an audit trail, and this exists
        so that decision can be made on numbers rather than on a guess.
      </p>
    </PageLayout>
  )
}