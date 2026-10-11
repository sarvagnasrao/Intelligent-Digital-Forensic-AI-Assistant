import React, { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import {
  Sparkles, RefreshCw, Download,
  CheckCircle, Bot, AlertCircle,
} from 'lucide-react'
import { generateCaseSummary, getLatestSummary } from '../api/client'
import PageLayout from '../components/PageLayout'
import toast from 'react-hot-toast'
import { formatDistanceToNow } from 'date-fns'
import { fromUtc } from '../utils/time'

// ── Simple markdown → HTML renderer ──────────────────────────────────────────
function renderMarkdown(text) {
  if (!text) return ''
  return text
    // Headings
    .replace(
      /^## (.+)$/gm,
      '<h2 style="font-size:15px;font-weight:700;color:#e2e4f0;margin:24px 0 10px;padding-bottom:8px;border-bottom:1px solid rgba(255,255,255,0.06)">$1</h2>'
    )
    .replace(
      /^### (.+)$/gm,
      '<h3 style="font-size:13px;font-weight:600;color:#c7d2fe;margin:16px 0 6px">$1</h3>'
    )
    // Bold
    .replace(
      /\*\*(.+?)\*\*/g,
      '<strong style="color:#e2e4f0;font-weight:600">$1</strong>'
    )
    // Bullet points
    .replace(
      /^- (.+)$/gm,
      '<div style="display:flex;gap:8px;margin:5px 0;padding-left:4px"><span style="color:#0284c7;flex-shrink:0;margin-top:3px">•</span><span>$1</span></div>'
    )
    // Numbered list items
    .replace(
      /^\d+\. (.+)$/gm,
      '<div style="display:flex;gap:8px;margin:5px 0;padding-left:4px"><span style="color:#38bdf8;flex-shrink:0;font-weight:600;min-width:16px">›</span><span>$1</span></div>'
    )
    // Paragraph breaks
    .replace(/\n\n/g, '<div style="height:8px"></div>')
    // Single line breaks → <br>
    .replace(/\n(?!<)/g, '<br/>')
}

// ── Stats chips shown when a summary has been generated ───────────────────────
function StatChip({ label, value, color }) {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      padding: '10px 16px',
      borderRadius: 10,
      background: `${color}10`,
      border: `1px solid ${color}25`,
      minWidth: 72,
      gap: 2,
    }}>
      <span style={{ fontSize: 20, fontWeight: 700, color, lineHeight: 1.2 }}>{value}</span>
      <span style={{ fontSize: 10, color: 'var(--color-white-3)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>{label}</span>
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────
export default function SummaryPage() {
  const { caseId } = useParams()
  const [summary, setSummary] = useState(null)
  const [stats, setStats] = useState(null)
  const [generating, setGenerating] = useState(false)
  const [loading, setLoading] = useState(true)
  const [meta, setMeta] = useState(null)

  useEffect(() => { loadExisting() }, [caseId])

  const loadExisting = async () => {
    try {
      const res = await getLatestSummary(caseId)
      if (res.data.has_summary) {
        setSummary(res.data.summary)
        setMeta({
          generated_at: res.data.generated_at,
          generated_by: res.data.generated_by,
        })
      }
    } catch {
      // No existing summary — that's fine
    } finally {
      setLoading(false)
    }
  }

  const handleGenerate = async () => {
    setGenerating(true)
    try {
      const res = await generateCaseSummary(caseId)
      setSummary(res.data.summary)
      setStats(res.data.stats)
      setMeta({
        generated_at: res.data.generated_at,
        generated_by: res.data.generated_by,
      })
      toast.success('Case summary generated')
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Generation failed — is Ollama running?')
    } finally {
      setGenerating(false)
    }
  }

  const handleDownload = () => {
    if (!summary) return
    const blob = new Blob([summary], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `case-summary-${caseId.slice(0, 8)}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  const headerActions = (
    <div style={{ display: 'flex', gap: 8 }}>
      {summary && (
        <button
          onClick={handleDownload}
          style={{
            display: 'flex', alignItems: 'center', gap: 6,
            padding: '8px 14px', borderRadius: 8,
            background: 'var(--color-white-04)',
            border: '1px solid rgba(255,255,255,0.08)',
            color: 'var(--color-white-5)', fontSize: 12, cursor: 'pointer',
          }}
        >
          <Download size={13} />
          Download .md
        </button>
      )}
      <button
        onClick={handleGenerate}
        disabled={generating}
        style={{
          display: 'flex', alignItems: 'center', gap: 6,
          padding: '8px 18px', borderRadius: 8,
          background: generating ? 'rgba(99,102,241,0.35)' : '#4f46e5',
          border: 'none', color: 'var(--color-white-full)', fontSize: 13, fontWeight: 500,
          cursor: generating ? 'not-allowed' : 'pointer',
          transition: 'background 0.15s',
        }}
      >
        {generating ? (
          <>
            <RefreshCw size={13} style={{ animation: 'spin 1s linear infinite' }} />
            Generating…
          </>
        ) : (
          <>
            <Sparkles size={13} />
            {summary ? 'Regenerate' : 'Generate Summary'}
          </>
        )}
      </button>
    </div>
  )

  return (
    <PageLayout
      title="AI Case Summary"
      subtitle="One-click executive summary synthesising all evidence, entities, and investigator findings"
      actions={headerActions}
    >
      {/* Generation banner */}
      {generating && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 12,
          marginBottom: 16, padding: '12px 18px',
          background: 'rgba(99,102,241,0.08)',
          border: '1px solid rgba(99,102,241,0.2)',
          borderRadius: 10,
        }}>
          <RefreshCw size={14} color="#818cf8" style={{ animation: 'spin 1s linear infinite', flexShrink: 0 }} />
          <div>
            <p style={{ fontSize: 13, fontWeight: 500, color: '#a5b4fc' }}>Generating executive summary…</p>
            <p style={{ fontSize: 11, color: 'var(--color-white-3)', marginTop: 2 }}>
              Analysing evidence, entities, queries, and notes. This may take 15–60 seconds.
            </p>
          </div>
        </div>
      )}

      {/* Meta info bar — shown when a summary exists */}
      {meta && !generating && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 12,
          marginBottom: 16, padding: '10px 16px',
          background: 'rgba(16,185,129,0.06)',
          border: '1px solid rgba(16,185,129,0.15)',
          borderRadius: 8,
        }}>
          <CheckCircle size={14} color="#34d399" style={{ flexShrink: 0 }} />
          <span style={{ fontSize: 12, color: '#34d399' }}>
            Generated{' '}
            {(() => {
              try {
                return formatDistanceToNow(fromUtc(meta.generated_at), { addSuffix: true })
              } catch {
                return 'recently'
              }
            })()}{' '}
            by <strong>{meta.generated_by}</strong>
          </span>
          <span style={{ fontSize: 11, color: 'var(--color-white-2)', marginLeft: 'auto' }}>
            Click Regenerate to refresh with latest evidence
          </span>
        </div>
      )}

      {/* Stats row — shown after a fresh generation with stats */}
      {stats && !generating && (
        <div style={{ display: 'flex', gap: 10, marginBottom: 20, flexWrap: 'wrap' }}>
          <StatChip label="Evidence"  value={stats.evidence_files}   color="#818cf8" />
          <StatChip label="Entities"  value={stats.entities}         color="#22d3ee" />
          <StatChip label="Flagged"   value={stats.flagged_entities} color="#f87171" />
          <StatChip label="Anomalies" value={stats.anomalies}        color="#fbbf24" />
          <StatChip label="Queries"   value={stats.queries}          color="#a78bfa" />
          <StatChip label="Notes"     value={stats.notes}            color="#34d399" />
        </div>
      )}

      {/* Content area */}
      {loading ? (
        /* Loading skeleton */
        <div style={{
          background: 'rgba(255,255,255,0.025)',
          border: '1px solid rgba(255,255,255,0.07)',
          borderRadius: 14, padding: '28px 32px',
        }}>
          {Array(8).fill(0).map((_, i) => (
            <div key={i} className="skeleton" style={{
              height: i % 4 === 0 ? 22 : 14,
              borderRadius: 6, marginBottom: 12,
              width: i % 4 === 0 ? '45%' : i % 3 === 0 ? '100%' : i % 3 === 1 ? '80%' : '65%',
              animationDelay: `${i * 80}ms`,
            }} />
          ))}
        </div>
      ) : summary ? (
        /* Rendered summary */
        <div style={{
          background: 'rgba(255,255,255,0.025)',
          border: '1px solid rgba(255,255,255,0.07)',
          borderRadius: 14, padding: '28px 32px',
        }}>
          <div
            style={{
              fontSize: 13,
              color: 'rgba(255,255,255,0.65)',
              lineHeight: 1.85,
            }}
            dangerouslySetInnerHTML={{ __html: renderMarkdown(summary) }}
          />
        </div>
      ) : (
        /* Empty state */
        <div style={{
          background: 'rgba(255,255,255,0.025)',
          border: '1px solid rgba(255,255,255,0.07)',
          borderRadius: 14, padding: '80px 40px',
          textAlign: 'center',
        }}>
          <div style={{
            width: 72, height: 72, borderRadius: 20,
            background: 'rgba(99,102,241,0.08)',
            border: '1px solid rgba(99,102,241,0.15)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            margin: '0 auto 20px',
          }}>
            <Bot size={32} color="rgba(99,102,241,0.6)" />
          </div>
          <p style={{ fontSize: 16, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 10 }}>
            No summary generated yet
          </p>
          <p style={{
            fontSize: 13, color: 'var(--color-white-3)',
            marginBottom: 28, maxWidth: 420, margin: '0 auto 28px',
            lineHeight: 1.6,
          }}>
            Generate an AI executive summary that synthesises all evidence files,
            extracted entities, investigator queries, and case notes into a
            professional forensic case report.
          </p>
          <button
            onClick={handleGenerate}
            disabled={generating}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 8,
              padding: '11px 28px', borderRadius: 10,
              background: '#4f46e5', border: 'none',
              color: 'var(--color-white-full)', fontSize: 13, fontWeight: 500,
              cursor: 'pointer',
            }}
          >
            <Sparkles size={15} />
            Generate Case Summary
          </button>
          <p style={{ fontSize: 11, color: 'var(--color-white-2)', marginTop: 16 }}>
            Requires Ollama to be running · Takes 15–60 seconds
          </p>
        </div>
      )}
    </PageLayout>
  )
}
