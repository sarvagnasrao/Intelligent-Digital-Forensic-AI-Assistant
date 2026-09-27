import React, { useState, useEffect, useRef, useCallback } from 'react'
import {
  Layers, RefreshCw, CheckCircle, XCircle,
  Clock, Trash2, HardDrive, Cpu,
  SlidersHorizontal, Zap, Square,
} from 'lucide-react'
import {
  getQueueList, deleteQueueJob, addToQueue,
  updateJobSettings, forceStartJob, stopJob, cancelJob,
} from '../api/client'
import PageLayout from '../components/PageLayout'
import ResourceMonitor from '../components/ResourceMonitor'
import useSystemInfo from '../hooks/useSystemInfo'
import toast from 'react-hot-toast'
import { formatDistanceToNow, intervalToDuration } from 'date-fns'
import { fromUtc } from '../utils/time'
import useWebSocket from '../hooks/useWebSocket'

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
  // A graceful stop. Not an error and not a success, so it shares the neutral
  // slate of Cancelled but keeps its own icon: Cancelled never started,
  // Stopped ran partway and was halted on request. The row keeps showing the
  // percent it reached, which is the fact that distinguishes the two.
  Stopped: {
    color: '#94a3b8',
    bg: 'rgba(148,163,184,0.1)',
    border: 'rgba(148,163,184,0.2)',
    icon: Square,
    spin: false,
    label: 'Stopped',
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

// ─── Job settings panel ───────────────────────────────────────────────────────

/**
 * Per-job ingestion controls.
 *
 * Rendered inline beneath a job row rather than as a floating popover: a
 * popover inside a grid row gets clipped by the scroll container and has to
 * fight z-index against the sidebar, and this way the panel cannot overlap the
 * thing it is editing.
 *
 * ── Why the profile is disabled on a running job ──
 * The profile is resolved once, when the worker picks the job up, and is never
 * re-read. It fixes chunk size and embedding batch size, so honouring a change
 * mid-run would leave the case half-indexed at mixed granularity - retrieval
 * results would then depend on which part of the document happened to be
 * ingested under which profile. The backend refuses it for the same reason;
 * the control is disabled rather than hidden so the reason stays visible.
 *
 * CPU ceiling and RAM floor are genuinely live: the governor is told the new
 * limits and applies them at the next batch check. Those two say "live" and
 * mean it.
 */
function JobSettingsPanel({ job, modes, ramMaxMb, onSave, onClose, saving }) {
  const running = job.status === 'Running'
  const [cpu, setCpu] = useState(job.cpu_throttle_percent ?? 100)
  const [ram, setRam] = useState(job.min_free_ram_mb ?? 2048)
  const [mode, setMode] = useState(job.ingestion_mode || 'normal')

  // Re-seed from the row whenever it changes underneath us. The 3 s poll
  // replaces the job object constantly, and without this the panel would keep
  // showing a stale value after a save, or after another operator changed it.
  useEffect(() => {
    setCpu(job.cpu_throttle_percent ?? 100)
    setRam(job.min_free_ram_mb ?? 2048)
    setMode(job.ingestion_mode || 'normal')
  }, [job.cpu_throttle_percent, job.min_free_ram_mb, job.ingestion_mode])

  const dirty =
    cpu !== (job.cpu_throttle_percent ?? 100) ||
    ram !== (job.min_free_ram_mb ?? 2048) ||
    (!running && mode !== (job.ingestion_mode || 'normal'))

  const label = { fontSize: 10, color: 'rgba(255,255,255,0.45)', marginBottom: 5 }
  const value = { fontSize: 11, color: '#e2e4f0', fontFamily: 'monospace' }

  return (
    <div
      style={{
        gridColumn: '1 / -1',
        marginTop: 10,
        padding: 14,
        borderRadius: 8,
        background: 'rgba(255,255,255,0.02)',
        border: '1px solid rgba(255,255,255,0.06)',
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))',
        gap: 18,
        alignItems: 'start',
      }}
    >
      {/* Profile */}
      <div>
        <p style={label}>
          Ingestion profile{' '}
          {running ? (
            <span style={{ color: 'rgba(245,158,11,0.9)' }}>· locked while running</span>
          ) : (
            <span style={{ color: 'rgba(255,255,255,0.25)' }}>· applies at start</span>
          )}
        </p>
        {modes.length === 0 ? (
          <p style={{ fontSize: 11, color: 'rgba(255,255,255,0.25)' }}>
            Reading the available profiles…
          </p>
        ) : (
          <div style={{ display: 'flex', gap: 4 }}>
            {modes.map(m => {
              const on = m.key === mode
              return (
                <button
                  key={m.key}
                  type="button"
                  disabled={running}
                  title={running
                    ? 'The profile sets the chunk size and embedding batch, so it is fixed once the job starts.'
                    : m.description}
                  onClick={() => setMode(m.key)}
                  style={{
                    flex: 1,
                    padding: '5px 4px',
                    borderRadius: 6,
                    cursor: running ? 'not-allowed' : 'pointer',
                    opacity: running ? 0.4 : 1,
                    fontSize: 11,
                    fontWeight: on ? 600 : 400,
                    color: on ? '#c7d2fe' : 'rgba(255,255,255,0.5)',
                    background: on ? 'rgba(99,102,241,0.15)' : 'rgba(255,255,255,0.03)',
                    border: `1px solid ${on ? 'rgba(99,102,241,0.4)' : 'rgba(255,255,255,0.07)'}`,
                  }}
                >
                  {m.label}
                </button>
              )
            })}
          </div>
        )}
        {modes.length > 0 && (
          <p style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)', marginTop: 6 }}>
            {modes.find(m => m.key === mode)?.description || '—'}
          </p>
        )}
      </div>

      {/* CPU ceiling */}
      <div>
        <p style={label}>
          CPU ceiling{' '}
          {running && <span style={{ color: 'rgba(16,185,129,0.9)' }}>· live</span>}
        </p>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <input
            type="range" min="10" max="100" step="5"
            value={cpu}
            onChange={e => setCpu(Number(e.target.value))}
            style={{ flex: 1, accentColor: '#6366f1' }}
          />
          <span style={{ ...value, minWidth: 34, textAlign: 'right' }}>{cpu}%</span>
        </div>
        <p style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)', marginTop: 6 }}>
          The worker sleeps between batches to stay under this. 100% is full speed.
        </p>
      </div>

      {/* RAM floor */}
      <div>
        <p style={label}>
          Pause below free RAM{' '}
          {running && <span style={{ color: 'rgba(16,185,129,0.9)' }}>· live</span>}
        </p>
        {/* Deliberately disabled until the device budget arrives. The queue
            form used to hardcode a 0-8 GB range, which on a 16 GB machine
            offered a ceiling the hardware could never reach and hid seven
            gigabytes of usable headroom (B8). Guessing a fallback maximum here
            would reintroduce exactly that. */}
        {ramMaxMb == null ? (
          <p style={{ fontSize: 11, color: 'rgba(255,255,255,0.25)' }}>
            Reading this machine's memory…
          </p>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <input
              type="range" min="0" max={ramMaxMb} step="128"
              value={Math.min(ram, ramMaxMb)}
              onChange={e => setRam(Number(e.target.value))}
              style={{ flex: 1, accentColor: '#6366f1' }}
            />
            <span style={{ ...value, minWidth: 52, textAlign: 'right' }}>
              {ram} MB
            </span>
          </div>
        )}
        <p style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)', marginTop: 6 }}>
          {ram === 0
            ? 'No floor — the job may consume all free memory.'
            : 'Ingestion waits until this much RAM is free.'}
          {ramMaxMb ? ` Bounded by this machine (${ramMaxMb} MB).` : ''}
        </p>
      </div>

      {/* Actions */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', gridColumn: '1 / -1' }}>
        <button
          type="button"
          disabled={!dirty || saving}
          onClick={() => onSave({ cpu, ram, mode })}
          style={{
            padding: '7px 14px',
            borderRadius: 6,
            fontSize: 11,
            fontWeight: 500,
            cursor: !dirty || saving ? 'default' : 'pointer',
            opacity: !dirty || saving ? 0.4 : 1,
            color: '#c7d2fe',
            background: 'rgba(99,102,241,0.15)',
            border: '1px solid rgba(99,102,241,0.35)',
          }}
        >
          {saving ? 'Saving…' : 'Apply'}
        </button>
        <button
          type="button"
          onClick={onClose}
          style={{
            padding: '7px 12px',
            borderRadius: 6,
            fontSize: 11,
            cursor: 'pointer',
            color: 'rgba(255,255,255,0.45)',
            background: 'none',
            border: '1px solid rgba(255,255,255,0.1)',
          }}
        >
          Close
        </button>
        {!dirty && (
          <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.25)' }}>
            No changes yet.
          </span>
        )}
      </div>
    </div>
  )
}

// ─── JobRow ───────────────────────────────────────────────────────────────────
function JobRow({ job, onRetry, onDelete, onSaveSettings, onForceStart, onStop, onCancel, modes, ramMaxMb }) {
  const [showSettings, setShowSettings] = useState(false)
  const [saving, setSaving] = useState(false)
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
        <div style={{ display: 'flex', gap: 10, paddingLeft: 18, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 10, fontFamily: 'monospace', color: 'rgba(255,255,255,0.18)' }}>
            {job.case_id?.slice(0, 8)}…
          </span>
          {/* The profile the job is running under, so the queue always
              states which accuracy/time trade-off produced the result. */}
          {job.ingestion_mode && (
            <span
              title={`Ingestion profile: ${job.ingestion_mode}`}
              style={{
                fontSize: 10,
                fontWeight: 500,
                color: 'rgba(129,140,248,0.9)',
                background: 'rgba(99,102,241,0.1)',
                border: '1px solid rgba(99,102,241,0.25)',
                borderRadius: 4,
                padding: '0 5px',
              }}
            >
              {job.ingestion_mode}
            </span>
          )}
          {job.current_step && job.status === 'Running' && (
            <span style={{ fontSize: 10, color: 'rgba(99,102,241,0.7)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 220 }}>
              {job.current_step}
            </span>
          )}
          {/* A throttled job's percent is legitimately frozen. Say why,
              otherwise it is indistinguishable from a hung one. */}
          {job.status === 'Running' && job.governor?.reason && (
            <span
              title={
                `${job.governor.reason}` +
                (job.governor.ram_pauses > 0
                  ? ` · ${job.governor.ram_pauses} RAM wait(s)`
                  : '') +
                ` · ${job.governor.throttle_seconds || 0}s throttled`
              }
              style={{ fontSize: 10, color: 'rgba(245,158,11,0.85)' }}
            >
              throttled: {job.governor.reason}
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
      <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
        {/* Settings: the only row control that edits ingestion itself. Shown
            while the job can still be changed, and hidden once it is
            terminal - there is nothing left to configure. */}
        {['Queued', 'Running'].includes(job.status) && (
          <button
            type="button"
            onClick={() => setShowSettings(s => !s)}
            title="Ingestion profile, CPU ceiling and RAM floor"
            aria-expanded={showSettings}
            style={{
              padding: 5,
              borderRadius: 6,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              color: showSettings ? '#818cf8' : 'rgba(255,255,255,0.3)',
              background: showSettings ? 'rgba(99,102,241,0.12)' : 'none',
              border: `1px solid ${showSettings ? 'rgba(99,102,241,0.35)' : 'transparent'}`,
              transition: 'color 0.15s',
            }}
          >
            <SlidersHorizontal size={12} />
          </button>
        )}
        {/* Force-start bypasses the CPU and RAM limits entirely. Offered on a
            running job too, because the usual reason to want it is "this one
            is nearly done and I need the machine back". */}
        {['Queued', 'Running'].includes(job.status) && (
          <button
            type="button"
            onClick={() => onForceStart(job)}
            title="Run now at full speed, ignoring the CPU and RAM limits"
            style={{
              padding: 5,
              borderRadius: 6,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              color: 'rgba(245,158,11,0.75)',
              background: 'none',
              border: '1px solid transparent',
              transition: 'color 0.15s',
            }}
            onMouseEnter={e => { e.currentTarget.style.color = '#fbbf24' }}
            onMouseLeave={e => { e.currentTarget.style.color = 'rgba(245,158,11,0.75)' }}
          >
            <Zap size={12} />
          </button>
        )}
        {job.status === 'Running' && (
          <button
            type="button"
            onClick={() => onStop(job)}
            title="Stop gracefully — finishes the current step, leaves the case consistent"
            style={{
              padding: 5,
              borderRadius: 6,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              color: 'rgba(239,68,68,0.6)',
              background: 'none',
              border: '1px solid transparent',
              transition: 'color 0.15s',
            }}
            onMouseEnter={e => { e.currentTarget.style.color = '#f87171' }}
            onMouseLeave={e => { e.currentTarget.style.color = 'rgba(239,68,68,0.6)' }}
          >
            <Square size={12} />
          </button>
        )}
        {/* Cancel is offered only while the job has not started. The backend
            refuses to cancel a running job, and offering a control that is
            guaranteed to 400 is worse than not offering it: Stop is the right
            tool there, and the two would have looked interchangeable. */}
        {job.status === 'Queued' && (
          <button
            type="button"
            onClick={() => onCancel(job)}
            title="Cancel this job — it has not started, so nothing is discarded"
            style={{
              padding: 5,
              borderRadius: 6,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              color: 'rgba(255,255,255,0.2)',
              background: 'none',
              border: '1px solid transparent',
              transition: 'color 0.15s',
            }}
            onMouseEnter={e => { e.currentTarget.style.color = '#f87171' }}
            onMouseLeave={e => { e.currentTarget.style.color = 'rgba(255,255,255,0.2)' }}
          >
            <XCircle size={12} />
          </button>
        )}
        {/* Retry re-queues the evidence. Offered for a stopped job as well as
            a failed one: stopping is a pause, not a verdict, and the evidence
            reverts to Uploaded so it is re-ingestable. */}
        {['Failed', 'Stopped'].includes(job.status) && (
          <button
            onClick={() => onRetry(job)}
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
        {['Completed', 'Failed', 'Cancelled', 'Stopped'].includes(job.status) && (
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

      {showSettings && (
        <JobSettingsPanel
          job={job}
          modes={modes}
          ramMaxMb={ramMaxMb}
          saving={saving}
          onClose={() => setShowSettings(false)}
          onSave={async payload => {
            setSaving(true)
            try {
              await onSaveSettings(job, payload)
            } finally {
              setSaving(false)
            }
          }}
        />
      )}
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
  // The profile list and the device-derived RAM bound come from the backend, so
  // a label cannot drift from the code that implements it and the slider
  // cannot offer a ceiling this machine could never satisfy.
  const { modes, budget } = useSystemInfo()

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

  // Live progress over the WebSocket, so the bar moves as each batch lands
  // instead of jumping every 3 s. The poll above stays as a safety net: it
  // still owns everything the socket does not carry (chunk/entity counts,
  // the governor's throttle reason, the completed/failed rows).
  useWebSocket('/ws/global', useCallback((msg) => {
    if (msg.type === 'INGESTION_PROGRESS' && msg.job_id) {
      setJobs(prev => prev.map(j => (
        j.id === msg.job_id
          ? {
              ...j,
              progress_percent: msg.percent ?? j.progress_percent,
              progress:        msg.percent ?? j.progress,
              current_step:    msg.step    ?? j.current_step,
            }
          : j
      )))
    } else if (msg.type === 'INGESTION_COMPLETE' || msg.type === 'INGESTION_FAILED') {
      load()
    }
  }, []))

  // Retry re-queues the evidence. The settings are carried across deliberately:
  // POST /queue/add deletes any existing job row for the same evidence (it has
  // to, to satisfy the UNIQUE constraint on evidence_id) and rebuilds it from
  // the request body. Sending only the evidence and case ids therefore reset
  // the profile, CPU ceiling and RAM floor to the machine defaults - an
  // operator who deliberately chose `accurate` would silently get `normal` on
  // the retry. `ingestion_mode` is resolved again server-side, so a profile
  // this device cannot honour is still downgraded, with its warning.
  const handleRetry = async (job) => {
    try {
      const res = await addToQueue({
        evidence_id: job.evidence_id,
        case_id: job.case_id,
        ingestion_mode: job.ingestion_mode,
        cpu_throttle_percent: job.cpu_throttle_percent,
        min_free_ram_mb: job.min_free_ram_mb,
      })
      const warnings = res.data?.mode_warnings || []
      toast.success('Job re-queued successfully')
      warnings.forEach(w => toast(w, { icon: '⚠' }))
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

  // ── Per-job ingestion controls ─────────────────────────────────────────────
  // Every one of these reports what the backend actually did, rather than
  // assuming success. `applied_live` is false for a Queued job because there
  // is no governor to push to yet - the limit is stored and the worker reads
  // it at start. Saying "applied" for that would be a small lie of the same
  // family the repo keeps guarding against.

  const handleSaveSettings = async (job, { cpu, ram, mode }) => {
    const running = job.status === 'Running'
    // Only send the profile when it is actually changeable, so a Running job
    // never trips the backend's deliberate 400.
    const body = running
      ? { cpu_throttle_percent: cpu, min_free_ram_mb: ram }
      : { cpu_throttle_percent: cpu, min_free_ram_mb: ram, ingestion_mode: mode }
    try {
      const res = await updateJobSettings(job.id, body)
      const d = res.data || {}
      // Reflect the change locally at once: the 3 s poll would otherwise show
      // the old numbers for up to three seconds after a successful save.
      setJobs(prev => prev.map(j => (
        j.id === job.id
          ? {
              ...j,
              cpu_throttle_percent: d.cpu_throttle_percent ?? j.cpu_throttle_percent,
              min_free_ram_mb: d.min_free_ram_mb ?? j.min_free_ram_mb,
              ingestion_mode: d.ingestion_mode ?? j.ingestion_mode,
            }
          : j
      )))
      const warnings = (d.changed || []).filter(c => c.startsWith('!'))
      // `applied_live` is false for a Queued job because there is no governor
      // to push to yet — the limit is stored and the worker reads it at start.
      // Saying "applied" there would be a small lie of the same family the
      // repo keeps guarding against.
      toast.success(
        d.applied_live
          ? 'Limits applied to the running job'
          : 'Saved — takes effect when the job starts',
      )
      warnings.forEach(w => toast(w.replace(/^!\s*/, ''), { icon: '⚠' }))
      load()
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Could not update settings')
    }
  }

  const handleForceStart = async (job) => {
    try {
      await forceStartJob(job.id)
      toast.success('Override on — running at full speed, limits bypassed')
      load()
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Force-start failed')
    }
  }

  const handleStop = async (job) => {
    try {
      await stopJob(job.id)
      toast.success('Stopping — the current step finishes first')
      load()
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Stop failed')
    }
  }

  const handleCancel = async (job) => {
    try {
      await cancelJob(job.id)
      toast.success('Job cancelled')
      load()
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Cancel failed')
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
              onSaveSettings={handleSaveSettings}
              onForceStart={handleForceStart}
              onStop={handleStop}
              onCancel={handleCancel}
              modes={modes}
              ramMaxMb={budget?.ram_floor_max_mb}
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
