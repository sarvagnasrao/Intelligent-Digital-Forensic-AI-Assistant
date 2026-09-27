/**
 * SystemHealthPage
 *
 * Live, MEASURED status of every backend service — polls GET /api/status
 * every 15 s and renders exactly what that endpoint measured.
 *
 * Why this page is written the way it is
 * -------------------------------------
 * It used to assert three things it had not measured. Two cards were string
 * literals: "Backend API — Running — FastAPI port 8000" and "Vector Store —
 * Qdrant — Local, data/qdrant_store". They were green on a machine where the
 * API was down, the backend was unreachable, or the vector store did not
 * exist, and the second one also cited a path that has never existed (per-case
 * Qdrant lives at data/cases/<case_id>/qdrant/ — AGENTS.md §2/§9). A third
 * card turned a failed request into per-service verdicts
 * (`database: 'error', ollama: 'offline'`), which is a claim about services
 * the page never managed to ask. That is the same silent-success defect class
 * as B1, B10, B11 and B16-B19, in the one surface an operator trusts when
 * something is wrong.
 *
 * So the rule here is AGENTS.md §16's: **a value that could not be measured is
 * a neutral em dash with a reason, never a plausible 0 or a coloured light.**
 * A service the backend reports as `state: null`, omits entirely, or answers
 * for at all shows "—" on a grey dot with no glow. Green means the backend
 * said `state: "ok"` and nothing else.
 *
 * The Ollama card deliberately carries three separate facts — is the daemon
 * answering, which model is configured, and is that model actually installed —
 * because "Ollama is running" and "the assistant can answer" are different
 * questions. Ollama answers /api/tags with 200 and an empty model list on a
 * machine that has never pulled a model, so a single green light here used to
 * sit next to an assistant that could not say a word.
 *
 * Styling is inline `style` + CSS variables (this branch's token namespace:
 * --surface-*, --ink-*, --line-* — see AGENTS.md §7). No Tailwind.
 */
import React, { useState, useEffect } from 'react'
import {
  Activity, AlertCircle, Cpu, Database, Folder, HardDrive, Layers,
} from 'lucide-react'
import { getStatus } from '../api/client'
import PageLayout from '../components/PageLayout'

/** The one thing that may stand in for a measurement we do not have. */
const NOT_MEASURED = '—'

/**
 * state -> colour. There is deliberately no default that looks like a verdict:
 * an unrecognised or absent state lands on `unknown` (neutral, no glow), not on
 * amber. "Unknown" and "warned" are different answers, and the old StatusDot
 * painted both of them amber.
 */
const TONE = {
  ok:          { color: '#10b981', glow: true },
  error:       { color: '#ef4444', glow: true },
  unavailable: { color: '#f59e0b', glow: true },
  unknown:     { color: 'var(--ink-2)', glow: false },
}

const toneFor = (state) => TONE[state] || TONE.unknown

/**
 * A measured number, or the em dash. `== null` rather than `||`, because 0 is
 * a real reading here (an empty model list, a 0.0 MB index) and must not be
 * dressed up as an unknown.
 */
const showNumber = (v, format) =>
  (typeof v === 'number' && Number.isFinite(v) ? format(v) : NOT_MEASURED)

const showMb = (v) => showNumber(v, (n) => `${n.toFixed(1)} MB`)
const showMs = (v) => showNumber(v, (n) => `${n.toFixed(1)} ms`)

/** The line under a card that is not ok. Null when the state is ok. */
function reasonFor(service) {
  const state = service?.state ?? null
  if (state === 'ok') return null
  if (service?.reason) return service.reason
  if (state == null) {
    return 'Not reported by the backend — nothing is known about this service.'
  }
  return null
}

function StatusDot({ state }) {
  const tone = toneFor(state)
  return (
    <span
      role="img"
      aria-label={state === 'ok' ? 'healthy' : state === 'error' ? 'failed' : state === 'unavailable' ? 'not verifiable' : 'not measured'}
      style={{
        display: 'inline-block',
        width: 8,
        height: 8,
        borderRadius: '50%',
        background: tone.color,
        boxShadow: tone.glow ? `0 0 6px ${tone.color}` : 'none',
        marginRight: 8,
        flexShrink: 0,
      }}
    />
  )
}

function FactRow({ label, value, alarm }) {
  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'baseline' }}>
      <span style={{ fontSize: 11, color: 'var(--ink-3)', flexShrink: 0, minWidth: 118 }}>{label}</span>
      <span style={{
        fontSize: 11,
        fontFamily: 'monospace',
        color: alarm ? '#ef4444' : 'var(--ink-1)',
        wordBreak: 'break-word',
      }}>
        {value}
      </span>
    </div>
  )
}

function StatusCard({ icon: Icon, label, value, state, detail, facts = [], reason, footnote }) {
  const tone = toneFor(state)
  // A card whose state we do not have shows the em dash whatever the caller
  // passed: the headline must never be a word we cannot back up.
  const headline = tone === TONE.unknown ? NOT_MEASURED : value

  return (
    <div style={{
      background: 'var(--surface-1)',
      border: '1px solid var(--line-DEFAULT)',
      borderRadius: 12,
      padding: '20px 24px',
      display: 'flex',
      alignItems: 'flex-start',
      gap: 16,
    }}>
      <div style={{
        width: 40,
        height: 40,
        borderRadius: 10,
        background: 'var(--brand-glow)',
        border: '1px solid rgba(99, 102, 241, 0.2)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
      }}>
        <Icon size={18} style={{ color: 'var(--brand-light)' }} />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{
          fontSize: 11,
          color: 'var(--ink-2)',
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          marginBottom: 4,
        }}>
          {label}
        </p>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
          <StatusDot state={state} />
          <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--ink-0)' }}>{headline}</span>
        </div>
        {detail && (
          <p style={{ fontSize: 12, color: 'var(--ink-1)', lineHeight: 1.5, marginTop: 2 }}>
            {detail}
          </p>
        )}
        {facts.length > 0 && (
          <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 3 }}>
            {facts.map((f) => (
              <FactRow key={f.label} label={f.label} value={f.value} alarm={f.alarm} />
            ))}
          </div>
        )}
        {reason && (
          <p style={{
            fontSize: 11,
            color: 'var(--ink-2)',
            fontFamily: 'monospace',
            lineHeight: 1.5,
            marginTop: 8,
            wordBreak: 'break-word',
          }}>
            {reason}
          </p>
        )}
        {footnote && (
          <p style={{ fontSize: 10, color: 'var(--ink-3)', fontFamily: 'monospace', marginTop: 6 }}>
            {footnote}
          </p>
        )}
      </div>
    </div>
  )
}

const gridStyle = { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }

/**
 * Transport failure. Deliberately NOT rendered as six per-service verdicts: a
 * request that did not complete says the page could not ask, not that the
 * database is broken. Amber, not red — nothing was measured, and this is a
 * degraded reading rather than a fault.
 */
function CannotReach({ error }) {
  return (
    <div style={{
      background: 'var(--surface-1)',
      border: '1px solid #f59e0b',
      borderRadius: 12,
      padding: '24px',
      display: 'flex',
      alignItems: 'flex-start',
      gap: 16,
    }}>
      <AlertCircle size={18} style={{ color: '#f59e0b', flexShrink: 0, marginTop: 2 }} />
      <div style={{ minWidth: 0 }}>
        <p style={{ fontSize: 15, fontWeight: 600, color: 'var(--ink-0)', marginBottom: 6 }}>
          Cannot reach the backend
        </p>
        <p style={{ fontSize: 12, color: 'var(--ink-1)', lineHeight: 1.6 }}>
          The status request did not complete, so no service was measured. This
          is not a verdict on the database, Ollama or the evidence store — it
          only says this page could not ask. It retries every 15 s.
        </p>
        {error?.message && (
          <p style={{ fontSize: 11, color: 'var(--ink-2)', fontFamily: 'monospace', marginTop: 8, wordBreak: 'break-word' }}>
            {error.message}
          </p>
        )}
      </div>
    </div>
  )
}

export default function SystemHealthPage() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const res = await getStatus()
        if (cancelled) return
        setData(res.data)
        setError(null)
      } catch (e) {
        if (cancelled) return
        // Drop the previous payload rather than leaving measured cards on
        // screen next to a failed check: they would be read as current.
        setData(null)
        setError(e)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    const t = setInterval(load, 15000)
    return () => {
      cancelled = true
      clearInterval(t)
    }
  }, [])

  const services = data?.services && typeof data.services === 'object' ? data.services : null
  const service = (key) => services?.[key] ?? null
  const state = (key) => service(key)?.state ?? null

  const database = service('database')
  const ollama = service('ollama')
  const vector = service('vector_store')
  const worker = service('worker')
  const casesDir = service('cases_dir')
  const embeddings = service('embeddings')

  // "Is the daemon answering" is not the same question as "is a model ready".
  // A non-null list is the proof that /api/tags answered; null means we never
  // got one, and the reason line says which of the several reasons it was.
  const daemonAnswering = Array.isArray(ollama?.installed_models)
  const modelReady = ollama?.model_ready ?? null
  const ollamaValue = modelReady === false
    ? 'Cannot answer'
    : state('ollama') === 'ok'
      ? 'Ready to answer'
      : state('ollama') === 'error'
        ? 'Not serving'
        : state('ollama') === 'unavailable'
          ? 'Not verifiable'
          : NOT_MEASURED

  return (
    <PageLayout
      title="System Health"
      subtitle="Live status of all backend services — refreshes every 15 s"
    >
      {loading ? (
        <div style={gridStyle}>
          {Array(6).fill(0).map((_, i) => (
            <div key={i} className="skeleton" style={{ height: 100, borderRadius: 12, animationDelay: `${i * 80}ms` }} />
          ))}
        </div>
      ) : error ? (
        <CannotReach error={error} />
      ) : (
        <>
          <div style={gridStyle}>
            <StatusCard
              icon={Database}
              label="Database"
              state={state('database')}
              value={
                state('database') === 'ok' ? 'Connected'
                : state('database') === 'error' ? 'Not answering'
                : state('database') === 'unavailable' ? 'Not verifiable'
                : NOT_MEASURED
              }
              detail={database?.detail}
              facts={[
                { label: 'Query time', value: showMs(database?.latency_ms) },
              ]}
              reason={reasonFor(database)}
            />

            <StatusCard
              icon={Activity}
              label="AI Engine (Ollama)"
              state={state('ollama')}
              value={ollamaValue}
              detail={ollama?.detail}
              facts={[
                {
                  label: 'Daemon',
                  value: daemonAnswering ? 'answering /api/tags' : NOT_MEASURED,
                },
                {
                  label: 'Configured model',
                  value: ollama?.model ? ollama.model : NOT_MEASURED,
                },
                {
                  label: 'Models installed',
                  value: Array.isArray(ollama?.installed_models)
                    ? String(ollama.installed_models.length)
                    : NOT_MEASURED,
                },
                {
                  label: 'Model installed',
                  value: modelReady === true ? 'yes'
                    : modelReady === false ? 'no — the assistant cannot answer'
                    : NOT_MEASURED,
                  alarm: modelReady === false,
                },
              ]}
              reason={reasonFor(ollama)}
            />

            <StatusCard
              icon={HardDrive}
              label="Vector Store"
              state={state('vector_store')}
              value={
                state('vector_store') === 'ok' ? 'Readable'
                : state('vector_store') === 'error' ? 'Not usable'
                : state('vector_store') === 'unavailable' ? 'Partly unverified'
                : NOT_MEASURED
              }
              detail={vector?.detail}
              facts={[
                {
                  label: 'Case indexes',
                  value: showNumber(vector?.case_collections, (n) => String(n)),
                },
                { label: 'On disk', value: showMb(vector?.total_size_mb) },
              ]}
              reason={reasonFor(vector)}
              footnote="data/cases/<case_id>/qdrant/"
            />

            <StatusCard
              icon={Folder}
              label="Evidence Directory"
              state={state('cases_dir')}
              value={
                state('cases_dir') === 'ok' ? 'Writable'
                : state('cases_dir') === 'error' ? 'Not writable'
                : state('cases_dir') === 'unavailable' ? 'Not verifiable'
                : NOT_MEASURED
              }
              detail={casesDir?.detail}
              reason={reasonFor(casesDir)}
            />

            <StatusCard
              icon={Cpu}
              label="Ingestion Worker"
              state={state('worker')}
              value={
                state('worker') === 'ok' ? 'Polling the queue'
                : state('worker') === 'error' ? 'Not draining the queue'
                : state('worker') === 'unavailable' ? 'Not verifiable'
                : NOT_MEASURED
              }
              detail={worker?.detail}
              reason={reasonFor(worker)}
            />

            <StatusCard
              icon={Layers}
              label="Embeddings"
              state={state('embeddings')}
              value={
                state('embeddings') === 'ok' ? 'Ready to embed'
                : state('embeddings') === 'error' ? 'Cannot embed evidence'
                : state('embeddings') === 'unavailable' ? 'Not verifiable'
                : NOT_MEASURED
              }
              detail={embeddings?.detail}
              reason={reasonFor(embeddings)}
            />
          </div>

          {!services && (
            <p style={{ fontSize: 11, color: 'var(--ink-2)', marginTop: 16, lineHeight: 1.6 }}>
              This backend answered /api/status without a{' '}
              <code style={{ fontFamily: 'monospace' }}>services</code> block, so no
              service was measured. Nothing above is inferred — restart the
              backend on a build that reports measured state.
            </p>
          )}
        </>
      )}
    </PageLayout>
  )
}
