import React, { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { Zap, RefreshCw, AlertTriangle, CheckCircle, Search } from 'lucide-react'
import { detectContradictions, getLatestContradictions, apiErrorMessage } from '../api/client'
import { formatDistanceToNow } from 'date-fns'
import { fromUtc } from '../utils/time'
import toast from 'react-hot-toast'
import PageLayout from '../components/PageLayout'

export default function ContradictionsPage() {
  const { caseId } = useParams()
  const [analysis, setAnalysis] = useState(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [meta, setMeta] = useState(null)
  // A failed check is not an absent finding. Held separately from `meta`
  // so the two can never render the same screen.
  const [loadError, setLoadError] = useState(null)

  useEffect(() => {
    loadExisting()
  }, [caseId])

  const loadExisting = async () => {
    try {
      const res = await getLatestContradictions(caseId)
      if (res.data.has_analysis) {
        setAnalysis(res.data.analysis)
        setMeta(res.data)
      }
      setLoadError(null)
    } catch (e) {
      /* Was `catch {}`. Both `analysis` and `meta` stay null, and the page
         renders its "No analysis yet" empty state. So a backend that was
         unreachable displayed the same screen as a case that has genuinely
         never been analysed - and on a page whose entire purpose is to
         tell an investigator whether the evidence contradicts itself, an
         unanswered question and a clean answer are the two most different
         things this app could show. */
      setLoadError(apiErrorMessage(e, 'Could not load the previous analysis'))
    } finally {
      setLoading(false)
    }
  }

  const handleRun = async () => {
    setRunning(true)
    try {
      const res = await detectContradictions(caseId)
      setAnalysis(res.data.analysis)
      setMeta({
        has_contradictions: res.data.has_contradictions,
        contradictions_found: res.data.contradictions_found,
        generated_at: res.data.generated_at,
        generated_by: res.data.generated_by || 'system'
      })
      if (res.data.contradictions_found > 0) {
        toast(`⚠ ${res.data.contradictions_found} contradiction(s) found!`, { duration: 6000 })
      } else {
        toast.success('No contradictions detected')
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Analysis failed')
    } finally {
      setRunning(false)
    }
  }

  const renderMarkdown = (text) => {
    if (!text) return ''
    return text
      .replace(/^## (.+)$/gm, '<h2 style="font-size:15px;font-weight:700;color:#e2e4f0;margin:20px 0 8px;padding-bottom:6px;border-bottom:1px solid rgba(255,255,255,0.06)">$1</h2>')
      .replace(/^### (.+)$/gm, '<h3 style="font-size:13px;font-weight:600;color:#fbbf24;margin:14px 0 6px">$1</h3>')
      .replace(/\*\*(.+?)\*\*/g, '<strong style="color:#e2e4f0">$1</strong>')
      .replace(/^- (.+)$/gm, '<div style="display:flex;gap:8px;margin:4px 0;padding-left:8px"><span style="color:#f87171;margin-top:2px;flex-shrink:0">•</span><span>$1</span></div>')
      .replace(/\n\n/g, '<br/>')
  }

  return (
    <PageLayout
      title="Contradiction Detector"
      subtitle="AI analysis for conflicting evidence and inconsistencies"
      actions={
        <button
          onClick={handleRun}
          disabled={running}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6, padding: '9px 18px',
            borderRadius: 9,
            background: running ? 'rgba(251,191,36,0.2)' : 'rgba(251,191,36,0.15)',
            border: '1px solid rgba(251,191,36,0.3)',
            color: '#fbbf24',
            fontSize: 13, fontWeight: 500,
            cursor: running ? 'not-allowed' : 'pointer',
          }}>
          {running
            ? <><RefreshCw size={13} className="animate-spin"/> Analysing...</>
            : <><Zap size={13} /> {analysis ? 'Re-analyse' : 'Run Analysis'}</>
          }
        </button>
      }
    >

      {/* Status badge */}
      {meta && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12, marginBottom: 16,
          padding: '10px 16px',
          background: meta.has_contradictions ? 'rgba(239,68,68,0.06)' : 'rgba(16,185,129,0.06)',
          border: meta.has_contradictions ? '1px solid rgba(239,68,68,0.15)' : '1px solid rgba(16,185,129,0.15)',
          borderRadius: 8,
        }}>
          {meta.has_contradictions
            ? <AlertTriangle size={14} color="#f87171" />
            : <CheckCircle size={14} color="#34d399" />}
          <span style={{
            fontSize: 12,
            color: meta.has_contradictions ? '#f87171' : '#34d399',
            fontWeight: 500,
          }}>
            {meta.has_contradictions
              ? `${meta.contradictions_found || ''} contradiction(s) detected`
              : 'No contradictions detected'}
          </span>
          {meta.generated_at && (
            <span style={{
              fontSize: 11,
              color: 'var(--color-white-2)',
              marginLeft: 'auto',
            }}>
              {formatDistanceToNow(fromUtc(meta.generated_at), { addSuffix: true })} by {meta.generated_by}
            </span>
          )}
        </div>
      )}

      {/* Analysis content */}
      {loading ? (
        Array(4).fill(0).map((_,i) => (
          <div key={i}
            className="skeleton"
            style={{
              height: i === 0 ? 24 : 16,
              borderRadius: 6,
              marginBottom: 10,
              width: ['40%','100%', '75%','90%'][i],
              animationDelay: `${i*80}ms`,
            }} />
        ))
      ) : loadError ? (
        <div style={{
          textAlign: 'center',
          padding: '40px 20px',
          background: 'rgba(239,68,68,0.05)',
          border: '1px solid rgba(239,68,68,0.2)',
          borderRadius: 14,
        }}>
          <AlertTriangle size={40} style={{
            margin: '0 auto 14px',
            color: 'rgba(239,68,68,0.5)',
          }} />
          <p style={{ fontSize: 14, fontWeight: 600, color: '#f87171', marginBottom: 6 }}>
            Could not check for a previous analysis
          </p>
          <p style={{ fontSize: 12, color: 'var(--color-white-3)', marginBottom: 14 }}>
            {loadError} — this is not the same as there being none.
          </p>
          <button onClick={loadExisting} style={{
            fontSize: 12, color: '#818cf8', background: 'none',
            border: '1px solid rgba(129,140,248,0.4)', borderRadius: 6,
            padding: '6px 14px', cursor: 'pointer',
          }}>
            Try again
          </button>
        </div>
      ) : analysis ? (
        <div style={{
          background: 'rgba(255,255,255,0.025)',
          border: '1px solid rgba(255,255,255,0.07)',
          borderRadius: 14,
          padding: '24px 28px',
        }}>
          <div
            style={{
              fontSize: 13,
              color: 'var(--color-white-6)',
              lineHeight: 1.8,
            }}
            dangerouslySetInnerHTML={{ __html: renderMarkdown(analysis) }}
          />
        </div>
      ) : (
        <div style={{
          textAlign: 'center',
          padding: '60px 20px',
          background: 'var(--color-white-03)',
          border: '1px dashed rgba(255,255,255,0.07)',
          borderRadius: 14,
        }}>
          <Search size={48} style={{
            margin: '0 auto 16px',
            color: 'rgba(251,191,36,0.2)',
          }} />
          <p style={{
            fontSize: 14,
            fontWeight: 600,
            color: 'var(--color-white-3)',
            marginBottom: 6,
          }}>
            No analysis yet
          </p>
          <p style={{
            fontSize: 12,
            color: 'var(--color-white-2)',
            maxWidth: 380,
            margin: '0 auto 24px',
          }}>
            Run the AI contradiction detector to find inconsistencies
            across all evidence, timestamps, and investigator findings.
          </p>
          <button
            onClick={handleRun}
            disabled={running}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 8, padding: '9px 22px',
              borderRadius: 9,
              background: 'rgba(251,191,36,0.15)',
              border: '1px solid rgba(251,191,36,0.3)',
              color: '#fbbf24',
              fontSize: 13,
              cursor: 'pointer',
            }}>
            <Zap size={14} />
            Run Contradiction Analysis
          </button>
        </div>
      )}
    </PageLayout>
  )
}
