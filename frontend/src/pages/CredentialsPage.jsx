import React, { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { Key, Shield, Eye, EyeOff } from 'lucide-react'
import { getCredentials, confirmCredential, markFalsePositive, apiErrorMessage } from '../api/client'
import PageLayout from '../components/PageLayout'
import toast from 'react-hot-toast'

// ── Severity palette ─────────────────────────────────────────────────────────
const SEVERITY_CONFIG = {
  critical: {
    color: '#f87171',
    bg: 'rgba(239,68,68,0.1)',
    border: 'rgba(239,68,68,0.25)',
    label: 'Critical',
  },
  high: {
    color: '#fb923c',
    bg: 'rgba(249,115,22,0.1)',
    border: 'rgba(249,115,22,0.25)',
    label: 'High',
  },
  medium: {
    color: '#fbbf24',
    bg: 'rgba(245,158,11,0.1)',
    border: 'rgba(245,158,11,0.25)',
    label: 'Medium',
  },
  low: {
    color: '#94a3b8',
    bg: 'rgba(100,116,139,0.1)',
    border: 'rgba(100,116,139,0.2)',
    label: 'Low',
  },
}

// ── Emoji icons per credential type ─────────────────────────────────────────
const TYPE_ICONS = {
  private_key_rsa: '🔑',
  ssh_private_key: '🔑',
  aws_access_key: '☁️',
  aws_secret_key: '☁️',
  github_token: '🐙',
  google_api_key: '🔍',
  slack_token: '💬',
  credit_card: '💳',
  password_assignment: '🔒',
  api_key_generic: '🗝️',
  jwt_token: '🎫',
  connection_string: '🔗',
  private_ip_cred: '🌐',
}

// ── Severity summary card ────────────────────────────────────────────────────
function SeverityCard({ severity, count, cfg, active, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: '14px 16px',
        borderRadius: 10,
        background: active ? cfg.bg : 'var(--color-white-03)',
        border: active
          ? `1px solid ${cfg.border}`
          : '1px solid rgba(255,255,255,0.06)',
        cursor: 'pointer',
        textAlign: 'left',
        transition: 'all 0.15s',
      }}
    >
      <p style={{
        fontSize: 10, fontWeight: 700,
        color: cfg.color,
        textTransform: 'uppercase',
        letterSpacing: '0.1em',
        marginBottom: 8,
      }}>
        {cfg.label}
      </p>
      <p style={{ fontSize: 30, fontWeight: 700, color: cfg.color, lineHeight: 1 }}>
        {count}
      </p>
    </button>
  )
}

// ── Individual finding card ──────────────────────────────────────────────────
function FindingCard({ finding, onConfirm, onFP }) {
  const [showContext, setShowContext] = useState(false)
  const cfg = SEVERITY_CONFIG[finding.severity] || SEVERITY_CONFIG.low
  const icon = TYPE_ICONS[finding.credential_type] || '🔐'

  const typeName = finding.credential_type
    .replace(/_/g, ' ')
    .replace(/^\w/, c => c.toUpperCase())

  return (
    <div style={{
      background: finding.is_confirmed
        ? 'rgba(239,68,68,0.05)'
        : 'rgba(255,255,255,0.025)',
      border: finding.is_confirmed
        ? '1px solid rgba(239,68,68,0.2)'
        : '1px solid rgba(255,255,255,0.07)',
      borderRadius: 12,
      padding: '16px 20px',
      opacity: finding.is_false_positive ? 0.45 : 1,
      transition: 'opacity 0.2s',
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14 }}>
        {/* Emoji icon */}
        <span style={{ fontSize: 22, lineHeight: 1, marginTop: 1, flexShrink: 0 }}>
          {icon}
        </span>

        {/* Main body */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {/* Title row */}
          <div style={{
            display: 'flex', alignItems: 'center',
            gap: 8, flexWrap: 'wrap', marginBottom: 8,
          }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
              {typeName}
            </span>
            <span style={{
              fontSize: 10, fontWeight: 700,
              padding: '2px 8px', borderRadius: 4,
              background: cfg.bg,
              border: `1px solid ${cfg.border}`,
              color: cfg.color,
              textTransform: 'uppercase',
              letterSpacing: '0.07em',
            }}>
              {cfg.label}
            </span>
            {finding.is_confirmed && (
              <span style={{
                fontSize: 10, color: '#f87171',
                background: 'rgba(239,68,68,0.1)',
                border: '1px solid rgba(239,68,68,0.2)',
                padding: '2px 8px', borderRadius: 4,
              }}>
                ✓ Confirmed
              </span>
            )}
            {finding.is_false_positive && (
              <span style={{ fontSize: 10, color: 'var(--color-white-3)' }}>
                False positive
              </span>
            )}
          </div>

          {/* Redacted value */}
          <div style={{ marginBottom: 8 }}>
            <code style={{
              fontSize: 12,
              fontFamily: '"JetBrains Mono", "Fira Code", monospace',
              color: cfg.color,
              background: cfg.bg,
              padding: '3px 10px',
              borderRadius: 5,
            }}>
              {finding.matched_value}
            </code>
          </div>

          {/* Source file */}
          {finding.source_file && (
            <p style={{
              fontSize: 11,
              color: 'var(--color-white-3)',
              fontFamily: 'monospace',
              marginBottom: 6,
              wordBreak: 'break-all',
            }}>
              {finding.source_file}
              {finding.internal_path && finding.internal_path !== finding.source_file
                && ` › ${finding.internal_path}`}
            </p>
          )}

          {/* Context block */}
          {showContext && finding.context && (
            <div style={{
              background: 'rgba(0,0,0,0.3)',
              borderRadius: 6,
              padding: '8px 12px',
              fontSize: 11,
              fontFamily: 'monospace',
              color: 'rgba(255,255,255,0.45)',
              marginTop: 8,
              wordBreak: 'break-all',
              lineHeight: 1.7,
            }}>
              {finding.context}
            </div>
          )}
        </div>

        {/* Action buttons */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, flexShrink: 0 }}>
          <button
            onClick={() => setShowContext(s => !s)}
            style={{
              fontSize: 11, padding: '4px 10px', borderRadius: 6,
              background: 'var(--color-white-04)',
              border: '1px solid rgba(255,255,255,0.08)',
              color: 'var(--color-white-4)',
              cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4,
            }}
          >
            {showContext ? <><EyeOff size={10} />Hide</> : <><Eye size={10} />Context</>}
          </button>
          <button
            onClick={() => onConfirm(finding.id)}
            style={{
              fontSize: 11, padding: '4px 10px', borderRadius: 6,
              background: finding.is_confirmed
                ? 'rgba(239,68,68,0.15)' : 'var(--color-white-04)',
              border: finding.is_confirmed
                ? '1px solid rgba(239,68,68,0.3)' : '1px solid rgba(255,255,255,0.08)',
              color: finding.is_confirmed ? '#f87171' : 'var(--color-white-4)',
              cursor: 'pointer',
            }}
          >
            {finding.is_confirmed ? '✓ Confirmed' : 'Confirm'}
          </button>
          <button
            onClick={() => onFP(finding.id)}
            style={{
              fontSize: 11, padding: '4px 10px', borderRadius: 6,
              background: 'var(--color-white-04)',
              border: '1px solid rgba(255,255,255,0.08)',
              color: 'var(--color-white-3)',
              cursor: 'pointer',
            }}
          >
            {finding.is_false_positive ? 'Restore' : 'False +'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main Page ────────────────────────────────────────────────────────────────
export default function CredentialsPage() {
  const { caseId } = useParams()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const [filterSeverity, setFilterSeverity] = useState('')
  const [hideFP, setHideFP] = useState(true)

  useEffect(() => { load() }, [caseId])

  const load = async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const res = await getCredentials(caseId, {
        is_false_positive: hideFP ? false : undefined,
      })
      setData(res.data)
    } catch (e) {
      // This used to be a bare `catch { toast.error(...) }` which left
      // `data` null - and null data renders as `filtered.length === 0`,
      // which drew the green "No credentials found / All findings are
      // marked as false positives" shield below. A failed request was
      // therefore displayed as a clean bill of health on the evidence.
      setData(null)
      setLoadError(apiErrorMessage(e, 'Could not load credential findings'))
      toast.error('Failed to load credential findings')
    } finally {
      setLoading(false)
    }
  }

  const handleConfirm = async (id) => {
    try {
      const res = await confirmCredential(caseId, id)
      setData(prev => ({
        ...prev,
        findings: prev.findings.map(f =>
          f.id === id ? { ...f, is_confirmed: res.data.is_confirmed } : f
        ),
      }))
    } catch {
      toast.error('Failed to update')
    }
  }

  const handleFP = async (id) => {
    try {
      const res = await markFalsePositive(caseId, id)
      setData(prev => ({
        ...prev,
        findings: prev.findings.map(f =>
          f.id === id ? { ...f, is_false_positive: res.data.is_false_positive } : f
        ),
      }))
    } catch {
      toast.error('Failed to update')
    }
  }

  // Client-side filter
  const filtered = (data?.findings || []).filter(f => {
    if (hideFP && f.is_false_positive) return false
    if (filterSeverity && f.severity !== filterSeverity) return false
    return true
  })

  const headerInfo = data
    ? `${filtered.length} finding${filtered.length !== 1 ? 's' : ''}`
    : null

  return (
    <PageLayout
      title="Credential Scanner"
      subtitle={
        'Passwords, API keys, private keys, and sensitive secrets found in evidence' +
        (headerInfo ? ` — ${headerInfo}` : '')
      }
    >
      {/* Severity summary cards */}
      {data && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: 10, marginBottom: 20,
        }}>
          {Object.entries(SEVERITY_CONFIG).map(([sev, cfg]) => (
            <SeverityCard
              key={sev}
              severity={sev}
              count={data.by_severity[sev] || 0}
              cfg={cfg}
              active={filterSeverity === sev}
              onClick={() => setFilterSeverity(prev => prev === sev ? '' : sev)}
            />
          ))}
        </div>
      )}

      {/* Filter bar */}
      <div style={{
        display: 'flex', alignItems: 'center',
        gap: 16, marginBottom: 16,
      }}>
        <label style={{
          display: 'flex', alignItems: 'center', gap: 8,
          fontSize: 12, color: 'var(--color-white-4)', cursor: 'pointer',
        }}>
          <input
            type="checkbox"
            checked={hideFP}
            onChange={e => {
              setHideFP(e.target.checked)
              setTimeout(load, 0)
            }}
            style={{ accentColor: '#6366f1' }}
          />
          Hide false positives
        </label>
        {filterSeverity && (
          <button
            onClick={() => setFilterSeverity('')}
            style={{
              fontSize: 11, padding: '3px 10px', borderRadius: 5,
              background: 'var(--color-white-06)',
              border: '1px solid rgba(255,255,255,0.1)',
              color: 'var(--color-white-5)', cursor: 'pointer',
            }}
          >
            × Clear filter
          </button>
        )}
        <span style={{ fontSize: 12, color: 'var(--color-white-2)', marginLeft: 'auto' }}>
          {filtered.length} finding{filtered.length !== 1 ? 's' : ''} shown
        </span>
      </div>

      {/* Findings list */}
      {loading ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {Array(5).fill(0).map((_, i) => (
            <div key={i} className="skeleton" style={{
              height: 90, borderRadius: 12,
              animationDelay: `${i * 80}ms`,
            }} />
          ))}
        </div>
      ) : loadError ? (
        /* A failure to load must never look like a clean result. This is the
           single most misleading state in the product: a reviewer shown this
           would conclude the evidence contains no exposed credentials. */
        <div style={{
          textAlign: 'center', padding: '70px 20px',
          background: 'rgba(239,68,68,0.04)',
          border: '1px solid rgba(239,68,68,0.22)',
          borderRadius: 14,
        }}>
          <div style={{
            width: 64, height: 64, borderRadius: 18,
            background: 'rgba(239,68,68,0.08)',
            border: '1px solid rgba(239,68,68,0.25)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            margin: '0 auto 16px',
          }}>
            <Shield size={28} color="rgba(248,113,113,0.7)" />
          </div>
          <p style={{ fontSize: 15, fontWeight: 600, color: '#f87171', marginBottom: 8 }}>
            Credential scan could not be loaded
          </p>
          <p style={{ fontSize: 12, color: 'var(--color-white-2)', marginBottom: 14 }}>
            {loadError} This is a request failure, not a finding - the
            credential state of this evidence is unknown.
          </p>
          <button
            onClick={load}
            style={{
              padding: '7px 14px', borderRadius: 8, border: 'none',
              background: '#4f46e5', color: '#fff', fontSize: 12,
              fontWeight: 600, cursor: 'pointer',
            }}
          >
            Retry scan
          </button>
        </div>
      ) : filtered.length === 0 ? (
        <div style={{
          textAlign: 'center', padding: '70px 20px',
          background: 'var(--color-white-03)',
          border: '1px solid rgba(255,255,255,0.06)',
          borderRadius: 14,
        }}>
          <div style={{
            width: 64, height: 64, borderRadius: 18,
            background: 'rgba(16,185,129,0.08)',
            border: '1px solid rgba(16,185,129,0.2)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            margin: '0 auto 16px',
          }}>
            <Shield size={28} color="rgba(52,211,153,0.6)" />
          </div>
          <p style={{ fontSize: 15, fontWeight: 600, color: '#34d399', marginBottom: 8 }}>
            No credentials found
          </p>
          <p style={{ fontSize: 12, color: 'var(--color-white-2)' }}>
            {data?.total === 0
              ? 'Credential scan runs automatically during evidence ingestion.'
              : 'All findings are marked as false positives or filtered out.'}
          </p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {filtered.map((f, i) => (
            <div
              key={f.id}
              className="animate-fade-up"
              style={{ animationDelay: `${i * 25}ms` }}
            >
              <FindingCard
                finding={f}
                onConfirm={handleConfirm}
                onFP={handleFP}
              />
            </div>
          ))}
        </div>
      )}
    </PageLayout>
  )
}
