import React, { useState, useEffect, useRef } from 'react'
import {
  Layers, RefreshCw, CheckCircle, XCircle,
  Clock, Trash2, HardDrive, Cpu,
} from 'lucide-react'
import { getQueueList, deleteQueueJob, addToQueue } from '../api/client'
import PageLayout from '../components/PageLayout'
import ResourceMonitor from '../components/ResourceMonitor'
import toast from 'react-hot-toast'
import { formatDistanceToNow, intervalToDuration } from 'date-fns'
import { fromUtc } from '../utils/time'

// ─── Status config ────────────────────────────────────────────────────────────
const STATUS_CONFIG = {
  Running: {
    color: '#6366f1',
    bg: 'rgba(99,102,241,0.1)',
    border: 'rgba(99,102,241,0.25)',
    icon: RefreshCw,
    spin: true,
    label: 'Processing',
  },
  Queued: {
    color: '#f59e0b',
    bg: 'rgba(245,158,11,0.1)',
    border: 'rgba(245,158,11,0.25)',
    icon: Clock,
    spin: false,
    label: 'Queued',
  },
  Completed: {
    color: '#10b981',
    bg: 'rgba(16,185,129,0.1)',
    border: 'rgba(16,185,129,0.2)',
    icon: CheckCircle,
    spin: false,
    label: 'Completed',
  },
  Failed: {
    color: '#ef4444',
    bg: 'rgba(239,68,68,0.1)',
    border: 'rgba(239,68,68,0.2)',
    icon: XCircle,
    spin: false,
    label: 'Failed',
  },
  Cancelled: {
    color: '#64748b',
    bg: 'rgba(100,116,139,0.1)',
    border: 'rgba(100,116,139,0.2)',
    icon: XCircle,
    spin: false,
    label: 'Cancelled',
  },
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function elapsed(seconds) {
  if (!seconds || seconds < 1) return '—'
  const d = intervalToDuration({ start: 0, end: seconds * 1000 })
  if (d.hours > 0) return `${d.hours}h ${d.minutes}m`
  if (d.minutes > 0) return `${d.minutes}m ${d.seconds}s`
  return `${d.seconds}s`
}

function timeAgo(dateStr) {
  if (!dateStr) return '—'
  try {
    return formatDistanceToNow(fromUtc(dateStr), { addSuffix: true })
  } catch {
    return '—'
  }
}

// ─── Spin keyframe injected once ─────────────────────────────────────────────
const style = document.createElement('style')
style.textContent = `
  @keyframes spin { to { transform: rotate(360deg); } }
  @keyframes pulse-glow {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }
  .queue-row { transition: background 0.15s; }
  .queue-row:hover { background: rgba(255,255,255,0.02) !important; }
`
if (!document.getElementById('queue-styles')) {
  style.id = 'queue-styles'
  document.head.appendChild(style)
}

// ─── JobRow ───────────────────────────────────────────────────────────────────
function JobRow({ job, onRetry, onDelete }) {
  const cfg = STATUS_CONFIG[job.status] || STATUS_CONFIG.Queued
  const Icon = cfg.icon

  const name = job.original_filename || job.filename || 'Unknown file'
  const progress = job.progress_percent ?? job.progress

  return (
    <div
      className="queue-row"
      style={{
        display: 'grid',
        gridTemplateColumns: '2.2fr 1fr 1fr 0.7fr 0.7fr 0.8fr auto',
        gap: 12,
        alignItems: 'center',
        padding: '13px 20px',
        borderBottom: '1px solid rgba(255,255,255,0.04)',
      }}
    >
      {/* File name */}
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 2 }}>
          <HardDrive size={11} style={{ color: 'rgba(255,255,255,0.2)', flexShrink: 0 }} />
          <span style={{
            fontSize: 13,
            fontWeight: 500,
            color: '#e2e4f0',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}>
            {name}
          </span>
        </div>
        <div style={{ display: 'flex', gap: 10, paddingLeft: 18 }}>
          <span style={{ fontSize: 10, fontFamily: 'monospace', color: 'rgba(255,255,255,0.18)' }}>
            {job.case_id?.slice(0, 8)}…
          </span>
          {job.current_step && job.status === 'Running' && (
            <span style={{ fontSize: 10, color: 'rgba(99,102,241,0.7)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 220 }}>
              {job.current_step}
            </span>
          )}
          {job.error_message && job.status === 'Failed' && (
            <span style={{ fontSize: 10, color: 'rgba(239,68,68,0.7)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 220 }} title={job.error_message}>
              {job.error_message}
            </span>
          )}
        </div>
      </div>

      {/* Status badge */}
      <div>
        <span style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 5,
          padding: '3px 10px',
          borderRadius: 6,
          background: cfg.bg,
          border: `1px solid ${cfg.border}`,
          fontSize: 11,
          fontWeight: 500,
          color: cfg.color,
        }}>
          <Icon size={10} style={cfg.spin ? { animation: 'spin 1.2s linear infinite' } : {}} />
          {cfg.label}
        </span>
      </div>

      {/* Progress bar */}
      <div>
        {job.status === 'Running' && progress != null ? (
          <div>
            <div style={{
              height: 4,
              borderRadius: 2,
              background: 'rgba(255,255,255,0.08)',
              overflow: 'hidden',
              marginBottom: 4,
            }}>
              <div style={{
                height: '100%',
                width: `${progress}%`,
                background: 'linear-gradient(90deg, #6366f1, #8b5cf6)',
                borderRadius: 2,
                transition: 'width 0.5s ease',
              }} />
            </div>
            <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)' }}>{progress}%</span>
          </div>
        ) : (
          <span style={{ fontSize: 12, color: 'rgba(255,255,255,0.2)' }}>
            {job.status === 'Completed' ? '100%'
              : job.status === 'Queued' ? `#${job.queue_position ?? '—'} in queue`
              : '—'}
          </span>
        )}
      </div>

      {/* Chunks */}
      <span style={{ fontSize: 12, color: 'rgba(255,255,255,0.35)', fontFamily: 'monospace' }}>
        {job.chunk_count != null ? job.chunk_count.toLocaleString() : '—'}
      </span>

      {/* Entities */}
      <span style={{ fontSize: 12, color: 'rgba(255,255,255,0.35)', fontFamily: 'monospace' }}>
        {job.entity_count != null ? job.entity_count : '—'}
      </span>

      {/* Time */}
      <div style={{ textAlign: 'right' }}>
        <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.28)' }}>
          {job.status === 'Running' || job.status === 'Queued'
            ? elapsed(job.elapsed_seconds)
            : timeAgo(job.completed_at)}
        </div>
        {job.status === 'Queued' && job.estimated_seconds && (
          <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.18)', marginTop: 2 }}>
            est. {elapsed(job.estimated_seconds)}
          </div>
        )}
      </div>

      {/* Actions */}
      <div style={{ display: 'flex', gap: 4 }}>
        {job.status === 'Failed' && (
          <button
            onClick={() => onRetry(job.evidence_id, job.case_id)}
            title="Retry ingestion"
            style={{
              padding: '4px 10px',
              borderRadius: 6,
              background: 'rgba(99,102,241,0.1)',
              border: '1px solid rgba(99,102,241,0.25)',
              color: '#818cf8',
              fontSize: 11,
              cursor: 'pointer',
              whiteSpace: 'nowrap',
            }}
          >
            Retry
          </button>
        )}
        {['Completed', 'Failed', 'Cancelled'].includes(job.status) && (
          <button
            onClick={() => onDelete(job.id)}
            title="Remove from history"
            style={{
              padding: 5,
              borderRadius: 6,
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              color: 'rgba(255,255,255,0.15)',
              display: 'flex',
              alignItems: 'center',
              transition: 'color 0.15s',
            }}
            onMouseEnter={e => { e.currentTarget.style.color = '#f87171' }}
            onMouseLeave={e => { e.currentTarget.style.color = 'rgba(255,255,255,0.15)' }}
          >
            <Trash2 size={12} />
          </button>
        )}
      </div>
    </div>
  )
}

// ─── Stat card ────────────────────────────────────────────────────────────────
function StatCard({ label, value, color, active, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: '14px 16px',
        borderRadius: 10,
        background: active ? `${color}18` : 'rgba(255,255,255,0.025)',
        border: active ? `1px solid ${color}40` : '1px solid rgba(255,255,255,0.07)',
        cursor: 'pointer',
        textAlign: 'left',
        transition: 'all 0.15s',
        width: '100%',
      }}
    >
      <p style={{
        fontSize: 10,
        color: color,
        textTransform: 'uppercase',
        letterSpacing: '0.08em',
        fontWeight: 600,
        marginBottom: 6,
      }}>
        {label}
      </p>
      <p style={{ fontSize: 28, fontWeight: 700, color: color, lineHeight: 1 }}>
        {value}
      </p>
    </button>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────
export default function QueuePage() {
  const [jobs, setJobs] = useState([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('all')
  const pollRef = useRef(null)

  const load = async () => {
    try {
      const res = await getQueueList()
      setJobs(res.data || [])
    } catch {
      // silent on poll failure
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    pollRef.current = setInterval(load, 3000)
    return () => clearInterval(pollRef.current)
  }, [])

  const handleRetry = async (evidenceId, caseId) => {
    try {
      await addToQueue({ evidence_id: evidenceId, case_id: caseId })
      toast.success('Job re-queued successfully')
      load()
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Retry failed')
    }
  }

  const handleDelete = async (jobId) => {
    try {
      await deleteQueueJob(jobId)
      setJobs(prev => prev.filter(j => j.id !== jobId))
      toast.success('Job removed from history')
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Delete failed')
    }
  }

  // ── Derived counts ──────────────────────────────────────────────────────────
  const running   = jobs.filter(j => j.status === 'Running').length
  const queued    = jobs.filter(j => j.status === 'Queued').length
  const completed = jobs.filter(j => j.status === 'Completed').length
  const failed    = jobs.filter(j => j.status === 'Failed').length

  const filtered = filter === 'all'
    ? jobs
    : jobs.filter(j => j.status.toLowerCase() === filter)

  // Sort: active first, then by queue_position / completed_at desc
  const sorted = [...filtered].sort((a, b) => {
    const order = { Running: 0, Queued: 1, Paused: 2, Failed: 3, Cancelled: 4, Completed: 5 }
    const diff = (order[a.status] ?? 9) - (order[b.status] ?? 9)
    if (diff !== 0) return diff
    return (a.queue_position ?? 0) - (b.queue_position ?? 0)
  })

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <PageLayout
      title="Ingestion Queue"
      subtitle={
        running > 0
          ? `${running} job(s) actively processing — auto-refreshes every 3 s`
          : 'Monitor background file processing jobs — auto-refreshes every 3 s'
      }
      actions={
        <button
          onClick={load}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            padding: '8px 14px',
            borderRadius: 8,
            background: 'rgba(255,255,255,0.04)',
            border: '1px solid rgba(255,255,255,0.09)',
            color: 'rgba(255,255,255,0.4)',
            fontSize: 12,
            cursor: 'pointer',
          }}
        >
          <RefreshCw size={12} />
          Refresh
        </button>
      }
    >

      {/* System info row */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        marginBottom: 20,
        padding: '10px 16px',
        borderRadius: 8,
        background: 'rgba(255,255,255,0.02)',
        border: '1px solid rgba(255,255,255,0.06)',
      }}>
        <Cpu size={12} style={{ color: 'rgba(255,255,255,0.25)' }} />
        <span style={{ fontSize: 12, color: 'rgba(255,255,255,0.3)' }}>
          {running > 0
            ? `${running} job(s) actively processing — the page updates automatically`
            : jobs.length === 0
            ? 'No jobs yet — upload evidence files to start ingestion'
            : 'All jobs are idle — upload new evidence to queue more work'}
        </span>
      </div>

      {/* Stat cards */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(4, 1fr)',
        gap: 10,
        marginBottom: 20,
      }}>
        <StatCard
          label="Running"
          value={running}
          color="#6366f1"
          active={filter === 'running'}
          onClick={() => setFilter(f => f === 'running' ? 'all' : 'running')}
        />
        <StatCard
          label="Queued"
          value={queued}
          color="#f59e0b"
          active={filter === 'queued'}
          onClick={() => setFilter(f => f === 'queued' ? 'all' : 'queued')}
        />
        <StatCard
          label="Completed"
          value={completed}
          color="#10b981"
          active={filter === 'completed'}
          onClick={() => setFilter(f => f === 'completed' ? 'all' : 'completed')}
        />
        <StatCard
          label="Failed"
          value={failed}
          color="#ef4444"
          active={filter === 'failed'}
          onClick={() => setFilter(f => f === 'failed' ? 'all' : 'failed')}
        />
      </div>

      {/* Live hardware + device inventory. Same component the Evidence
          page uses, so both surfaces agree, and hidden when the operator
          turns system resource monitoring off in Settings > Preferences. */}
      <ResourceMonitor
        className="mb-5"
        extra={(
          <div className="grid grid-cols-3 gap-4 border-t border-line mt-4 pt-4">
            <div>
              <p className="text-xs text-ink-2 mb-1">Running</p>
              <p className="text-xl font-bold text-ink-0">{running}</p>
            </div>
            <div>
              <p className="text-xs text-ink-2 mb-1">Queued</p>
              <p className="text-xl font-bold text-ink-0">{queued}</p>
            </div>
            <div>
              <p className="text-xs text-ink-2 mb-1">Failed</p>
              <p className="text-xl font-bold text-ink-0">{failed}</p>
            </div>
          </div>
        )}
      />

      {/* Table */}
      <div style={{
        background: 'rgba(255,255,255,0.025)',
        border: '1px solid rgba(255,255,255,0.07)',
        borderRadius: 14,
        overflow: 'hidden',
      }}>
        {/* Column headers */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: '2.2fr 1fr 1fr 0.7fr 0.7fr 0.8fr auto',
          gap: 12,
          padding: '10px 20px',
          borderBottom: '1px solid rgba(255,255,255,0.06)',
          background: 'rgba(255,255,255,0.02)',
        }}>
          {['File', 'Status', 'Progress', 'Chunks', 'Entities', 'Time', ''].map(h => (
            <span key={h} style={{
              fontSize: 10,
              fontWeight: 600,
              color: 'rgba(255,255,255,0.3)',
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
            }}>
              {h}
            </span>
          ))}
        </div>

        {/* Rows */}
        {loading ? (
          Array(4).fill(0).map((_, i) => (
            <div
              key={i}
              className="skeleton"
              style={{
                height: 60,
                margin: 12,
                borderRadius: 8,
                animationDelay: `${i * 80}ms`,
              }}
            />
          ))
        ) : sorted.length === 0 ? (
          <div style={{ padding: '60px 20px', textAlign: 'center' }}>
            <Layers size={40} style={{ margin: '0 auto 12px', color: 'rgba(255,255,255,0.1)' }} />
            <p style={{ fontSize: 13, color: 'rgba(255,255,255,0.3)' }}>
              {filter === 'all'
                ? 'No jobs yet. Upload evidence files to start ingestion.'
                : `No ${filter} jobs`}
            </p>
          </div>
        ) : (
          sorted.map(job => (
            <JobRow
              key={job.id}
              job={job}
              onRetry={handleRetry}
              onDelete={handleDelete}
            />
          ))
        )}
      </div>

      {/* Live processing indicator */}
      {running > 0 && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          marginTop: 12,
          padding: '8px 16px',
          background: 'rgba(99,102,241,0.06)',
          border: '1px solid rgba(99,102,241,0.15)',
          borderRadius: 8,
        }}>
          <span style={{
            width: 6,
            height: 6,
            borderRadius: '50%',
            background: '#6366f1',
            boxShadow: '0 0 6px #6366f1',
            animation: 'pulse-glow 2s infinite',
            flexShrink: 0,
          }} />
          <span style={{ fontSize: 12, color: '#818cf8' }}>
            {running} job(s) actively processing forensic evidence — page updates automatically every 3 s
          </span>
        </div>
      )}
    </PageLayout>
  )
}
