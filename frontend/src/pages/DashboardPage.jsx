import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  FolderOpen, Database, AlertTriangle, CheckCircle, FileText, Bot, Clock,
  MessageSquare, Plus, Upload
} from 'lucide-react'
import { ResponsiveContainer, PieChart, Pie, Cell } from 'recharts'
import api, { apiErrorMessage } from '../api/client'
import { useAuth } from '../context/AuthContext'
import toast from 'react-hot-toast'

// Relative time, from a real timestamp. The previous footer read a hardcoded
// "Last updated: 10 min ago" and the insight cards read "10 min ago" /
// "25 min ago" / "1 hour ago" / "2 hours ago" that never changed.
function timeAgo(iso) {
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return null
  const s = Math.max(0, Math.round((Date.now() - t) / 1000))
  if (s < 60) return `${s}s ago`
  const m = Math.round(s / 60)
  if (m < 60) return `${m} min ago`
  const h = Math.round(m / 60)
  if (h < 24) return `${h} hour${h === 1 ? '' : 's'} ago`
  const d = Math.round(h / 24)
  return `${d} day${d === 1 ? '' : 's'} ago`
}

// Human label for an audit action_type, e.g. QUERY_MADE -> "Query made".
function actionLabel(action) {
  if (!action) return 'Activity'
  return String(action).replace(/_/g, ' ').toLowerCase()
    .replace(/^./, c => c.toUpperCase())
}

export default function DashboardPage({ activeCaseId, setActiveCaseId }) {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const [loadedAt, setLoadedAt] = useState(null)

  useEffect(() => { loadStats() }, [])

  const loadStats = async () => {
    try {
      const res = await api.get('/dashboard/stats')
      setStats(res.data)
      setLoadedAt(new Date().toISOString())
      setLoadError(null)

      // Auto-set active case if none is set and cases exist
      if (!activeCaseId && res.data.recent_cases?.length > 0) {
        setActiveCaseId(res.data.recent_cases[0].id)
      }
    } catch (e) {
      // Previously this was `catch { toast.error(...) }` followed by
      // `if (!stats) return null`, which rendered the entire main panel
      // blank with no explanation - indistinguishable from a hang.
      setLoadError(apiErrorMessage(e, 'Could not load dashboard statistics'))
      toast.error('Failed to load stats')
    } finally {
      setLoading(false)
    }
  }

  if (loading) return (
    <div className="animate-fade-in" style={{ width: '100%' }}>
      <div className="skeleton" style={{ height: 34, width: 280, borderRadius: 8, marginBottom: 8 }} />
      <div className="skeleton" style={{ height: 16, width: 220, borderRadius: 6, marginBottom: 28 }} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12, marginBottom: 12 }}>
        {Array(5).fill(0).map((_, i) => (
          <div key={i} className="skeleton" style={{ height: 110, borderRadius: 14 }} />
        ))}
      </div>
    </div>
  )

  if (!stats) {
    // Was `return null` - a blank page on failure, which reads as a broken
    // app rather than a failed request. The distinction matters most here,
    // because every other number on this page is a measurement.
    return (
      <div className="animate-fade-in" style={{ width: '100%', color: 'var(--text-primary)' }}>
        <div className="ref-card" style={{ padding: 24, textAlign: 'center' }}>
          <h2 style={{ fontSize: 16, fontWeight: 700, margin: '0 0 6px 0' }}>
            Dashboard statistics unavailable
          </h2>
          <p style={{ fontSize: 12, color: 'var(--text-secondary)', margin: '0 0 14px 0' }}>
            {loadError || 'The statistics request did not return a result.'}
          </p>
          <button
            onClick={() => { setLoading(true); loadStats() }}
            style={{
              padding: '7px 14px', borderRadius: 8, border: 'none',
              background: '#4f46e5', color: '#fff', fontSize: 12,
              fontWeight: 600, cursor: 'pointer',
            }}
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  // 1. Calculations for dynamic metric values.
  //    Every figure below is read from /dashboard/stats. This page previously
  //    carried hardcoded deltas ("+12% this month"), a hardcoded total
  //    ("|| 1248"), fixed donut proportions and a fake evidence size, which
  //    contradicted the real counters printed beside them. Where a number
  //    cannot be measured it is now omitted rather than invented.
  const totalCases = stats.cases?.total || 0
  const totalEvidence = stats.evidence?.total || 0
  const aiAnalyses = stats.queries?.total || 0
  const resolvedCases = stats.cases?.by_status?.Closed || 0

  // `stats.alerts` always carries at least one entry - the backend appends an
  // "All Systems Operational" info row when nothing is wrong. Counting the
  // array would therefore report 1 alert on a completely clean system, so
  // count the ones that actually describe a problem.
  const activeAlerts = (stats.alerts || []).filter(a => a.level !== 'info')
  const alertCount = activeAlerts.length

  // 2. Evidence Overview - the real ingestion state of every evidence row.
  //    Drawn from measured counts, so the slices always sum to the total
  //    printed in the middle of the donut.
  const evTotal = totalEvidence
  const evIndexed = stats.evidence?.indexed || 0
  const evFailed = stats.evidence?.failed || 0
  const evPending = Math.max(0, evTotal - evIndexed - evFailed)
  const evidenceOverviewData = [
    { name: 'Indexed', value: evIndexed, color: '#10b981' },
    { name: 'Awaiting ingest', value: evPending, color: '#3b82f6' },
    { name: 'Failed', value: evFailed, color: '#ef4444' },
  ].filter(d => d.value > 0)

  // 3. Case Status Distribution - real counts only. The old version used
  //    `|| 18` / `|| 12` fallbacks, which rendered a genuine zero as 18 and
  //    produced a legend reading "Completed 12 (400%)" under a centre that
  //    said "3 Total Cases".
  const STATUS_COLOURS = {
    Active: '#3b82f6', Open: '#f59e0b', Closed: '#10b981',
    'Under Review': '#8b5cf6', OnHold: '#6b7280', Archived: '#9ca3af',
  }
  const STATUS_LABELS = {
    Active: 'In Progress', Open: 'Open', Closed: 'Closed',
    'Under Review': 'Under Review', OnHold: 'On Hold', Archived: 'Archived',
  }
  const caseStatusData = Object.entries(stats.cases?.by_status || {})
    .filter(([, v]) => v > 0)
    .map(([k, v]) => ({
      name: STATUS_LABELS[k] || k,
      value: v,
      color: STATUS_COLOURS[k] || '#6b7280',
    }))

  // 4. Real activity, for the activity feed. The previous "Analysis Trend"
  //    was seven hardcoded points dated 14-20 May that never changed and had
  //    a period selector wired to nothing. There is no time series behind
  //    /dashboard/stats, so the card shows the audit trail that does exist.
  const recentActivity = (stats.recent_activity || []).slice(0, 6)
  const lastUpdated = loadedAt

  // Entity types, largest first, as bars against the largest type.
  const entityTotal = stats.entities?.total || 0
  const entityTypeRows = Object.entries(stats.entities?.by_type || {})
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([k, v]) => ({
      name: k,
      value: v,
      pct: entityTotal > 0 ? Math.round((v / entityTotal) * 100) : 0,
    }))

  // Tool Click Handler
  const handleToolClick = (path) => {
    if (!activeCaseId) {
      toast.error('Please select or create a case first')
      navigate('/cases')
    } else {
      navigate(`/cases/${activeCaseId}/${path}`)
    }
  }

  return (
    <div className="animate-fade-in" style={{ width: '100%', color: 'var(--text-primary)' }}>
      
      {/* Dashboard Top Header & Actions */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: 24,
      }}>
        <div>
          <h1 style={{
            fontSize: 24,
            fontWeight: 700,
            letterSpacing: '-0.02em',
            margin: 0,
            lineHeight: 1.2,
          }}>
            Dashboard
          </h1>
          <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 4 }}>
            Overview of your forensic investigations and AI insights
          </p>
        </div>

        {/* Action Buttons */}
        <div style={{ display: 'flex', gap: 10 }}>
          <button
            onClick={() => navigate('/cases')}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              background: '#4f46e5',
              color: '#ffffff',
              border: 'none',
              padding: '8px 16px',
              borderRadius: 8,
              fontSize: 13,
              fontWeight: 600,
              cursor: 'pointer',
              boxShadow: '0 2px 8px rgba(79,70,229,0.25)',
              transition: 'all 0.15s',
            }}
            onMouseEnter={e => e.currentTarget.style.filter = 'brightness(1.1)'}
            onMouseLeave={e => e.currentTarget.style.filter = 'none'}
          >
            <Plus size={15} />
            New Case
          </button>
          <button
            onClick={() => handleToolClick('evidence')}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              background: 'var(--bg-panel)',
              color: 'var(--text-primary)',
              border: '1px solid var(--border-base)',
              padding: '8px 16px',
              borderRadius: 8,
              fontSize: 13,
              fontWeight: 600,
              cursor: 'pointer',
              transition: 'all 0.15s',
            }}
            onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
            onMouseLeave={e => e.currentTarget.style.background = 'var(--bg-panel)'}
          >
            <Upload size={15} />
            Import Data
          </button>
        </div>
      </div>

      {/* 5-Column Metric Cards Row */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(5, 1fr)',
        gap: 16,
        marginBottom: 24,
      }}>
        {/* Metric 1: Total Cases */}
        <div className="ref-card" style={{ padding: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Total Cases</span>
            <div style={{ width: 26, height: 26, borderRadius: 6, background: 'rgba(59,130,246,0.1)', color: '#3b82f6', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <FolderOpen size={13} />
            </div>
          </div>
          <div style={{ marginTop: 8 }}>
            <span style={{ fontSize: 24, fontWeight: 700, lineHeight: 1.1 }}>{totalCases}</span>
          </div>
        </div>

        {/* Metric 2: Total Evidence */}
        <div className="ref-card" style={{ padding: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Total Evidence</span>
            <div style={{ width: 26, height: 26, borderRadius: 6, background: 'rgba(16,185,129,0.1)', color: '#10b981', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Database size={13} />
            </div>
          </div>
          <div style={{ marginTop: 8 }}>
            <span style={{ fontSize: 24, fontWeight: 700, lineHeight: 1.1 }}>{totalEvidence.toLocaleString()}</span>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>
              {evIndexed} indexed · {evPending} queued · {evFailed} failed
            </div>
          </div>
        </div>

        {/* Metric 3: AI Analyses */}
        <div className="ref-card" style={{ padding: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>AI Analyses</span>
            <div style={{ width: 26, height: 26, borderRadius: 6, background: 'rgba(139,92,246,0.1)', color: '#8b5cf6', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Bot size={13} />
            </div>
          </div>
          <div style={{ marginTop: 8 }}>
            <span style={{ fontSize: 24, fontWeight: 700, lineHeight: 1.1 }}>{aiAnalyses}</span>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>
              questions asked of the assistant
            </div>
          </div>
        </div>

        {/* Metric 4: Alerts */}
        <div className="ref-card" style={{ padding: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Alerts</span>
            <div style={{ width: 26, height: 26, borderRadius: 6, background: 'rgba(245,158,11,0.1)', color: '#f59e0b', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <AlertTriangle size={13} />
            </div>
          </div>
          <div style={{ marginTop: 8 }}>
            <span style={{ fontSize: 24, fontWeight: 700, lineHeight: 1.1 }}>{alertCount}</span>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>
              {/* Was a hardcoded "↓ 3 new alerts" directly beneath a counter
                  that rendered 0 - a self-contradiction on one card. Now it
                  says what is actually true, including when that is nothing. */}
              {alertCount === 0
                ? 'no integrity, lock or ingestion problems'
                : activeAlerts.map(a => a.title).join(', ')}
            </div>
          </div>
        </div>

        {/* Metric 5: Resolved Cases */}
        <div className="ref-card" style={{ padding: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Resolved Cases</span>
            <div style={{ width: 26, height: 26, borderRadius: 6, background: 'rgba(6,182,212,0.1)', color: '#06b6d4', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <CheckCircle size={13} />
            </div>
          </div>
          <div style={{ marginTop: 8 }}>
            <span style={{ fontSize: 24, fontWeight: 700, lineHeight: 1.1 }}>{resolvedCases}</span>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>
              {/* Was a hardcoded "↑ 8% this month" under a counter that
                  renders 0 - growth claimed from nothing. */}
              of {totalCases} case{totalCases === 1 ? '' : 's'} closed
            </div>
          </div>
        </div>
      </div>

      {/* Middle Row (Recent Cases, Evidence Donut, AI Insights) */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '1.2fr 1.1fr 1.1fr',
        gap: 16,
        marginBottom: 24,
      }}>
        
        {/* Card 1: Recent Cases */}
        <div className="ref-card">
          <div className="ref-card-header">
            <div>
              <span className="ref-card-title">Recent Cases</span>
            </div>
            <button onClick={() => navigate('/cases')} style={{ fontSize: 11, color: '#4f46e5', border: 'none', background: 'none', cursor: 'pointer', fontWeight: 600 }}>View All</button>
          </div>
          
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {(stats.recent_cases || []).slice(0, 5).map(c => {
              let badgeColor = '#6b7280'
              let badgeBg = '#f3f4f6'
              if (c.status === 'Active' || c.status === 'Open') {
                badgeColor = '#8b5cf6'
                badgeBg = '#f3e8ff'
              } else if (c.status === 'Closed') {
                badgeColor = '#10b981'
                badgeBg = '#d1fae5'
              } else if (c.status === 'Under Review') {
                badgeColor = '#f59e0b'
                badgeBg = '#fef3c7'
              }

              return (
                <div
                  key={c.id}
                  onClick={() => {
                    setActiveCaseId(c.id)
                    navigate(`/cases/${c.id}`)
                  }}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '8px 10px',
                    borderRadius: 8,
                    cursor: 'pointer',
                    background: activeCaseId === c.id ? 'var(--bg-hover)' : 'transparent',
                    transition: 'background 0.15s',
                  }}
                  onMouseEnter={e => { if (activeCaseId !== c.id) e.currentTarget.style.background = 'var(--bg-hover)' }}
                  onMouseLeave={e => { if (activeCaseId !== c.id) e.currentTarget.style.background = 'transparent' }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
                    <div style={{
                      width: 28, height: 28, borderRadius: '50%',
                      background: 'rgba(79,70,229,0.06)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      color: '#4f46e5', flexShrink: 0
                    }}>
                      <FolderOpen size={13} />
                    </div>
                    <div style={{ minWidth: 0 }}>
                      <p style={{ fontSize: 12, fontWeight: 600, margin: 0, textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>
                        {c.case_name}
                      </p>
                      <p style={{ fontSize: 10, color: 'var(--text-muted)', margin: 0 }}>
                        Case ID: {c.case_number || `CS-${c.id.slice(0,4)}`}
                      </p>
                    </div>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
                    <span style={{
                      padding: '2px 8px', borderRadius: 12, fontSize: 9, fontWeight: 700,
                      color: badgeColor, background: badgeBg
                    }}>
                      {c.status === 'Active' || c.status === 'Open' ? 'In Progress' : c.status}
                    </span>
                    <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>
                      {new Date(c.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
                    </span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* Card 2: Evidence Overview */}
        <div className="ref-card" style={{ display: 'flex', flexDirection: 'column' }}>
          <div className="ref-card-header">
            <span className="ref-card-title">Evidence Overview</span>
            <button onClick={() => handleToolClick('evidence')} style={{ fontSize: 11, color: '#4f46e5', border: 'none', background: 'none', cursor: 'pointer', fontWeight: 600 }}>View All</button>
          </div>
          
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flex: 1 }}>
            {/* Pie Chart container */}
            <div style={{ position: 'relative', width: 130, height: 130, flexShrink: 0 }}>
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={evidenceOverviewData}
                    cx="50%"
                    cy="50%"
                    innerRadius={44}
                    outerRadius={58}
                    paddingAngle={3}
                    dataKey="value"
                  >
                    {evidenceOverviewData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
              {/* Total label inside donut */}
              <div style={{
                position: 'absolute', inset: 0,
                display: 'flex', flexDirection: 'column',
                alignItems: 'center', justifyContent: 'center',
                pointerEvents: 'none'
              }}>
                <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-primary)' }}>{evTotal.toLocaleString()}</span>
                <span style={{ fontSize: 8, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Total</span>
              </div>
            </div>

            {/* Legend list */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: 1, marginLeft: 16 }}>
              {evidenceOverviewData.map((d, i) => {
                const pct = Math.round((d.value / evTotal) * 100) || 0
                return (
                  <div key={d.name} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                      <span style={{ width: 6, height: 6, borderRadius: '50%', background: d.color, flexShrink: 0 }} />
                      <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {d.name}
                      </span>
                    </div>
                    <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-primary)' }}>
                      {d.value} <span style={{ fontWeight: 500, color: 'var(--text-muted)' }}>({pct}%)</span>
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
          
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderTop: '1px solid var(--border-base)', paddingTop: 10, marginTop: 10, fontSize: 10, color: 'var(--text-muted)' }}>
            {/* Was hardcoded: "Evidence size: 256.7 GB" and "Last updated:
                10 min ago". /dashboard/stats carries no byte total, so the
                size claim had no measurement behind it at all - claiming
                256.7 GB for a corpus of a few hundred MB. Removed rather
                than guessed; the timestamp below is the real fetch time. */}
            <span>
              {evTotal === 0
                ? 'No evidence ingested yet'
                : `${evIndexed} of ${evTotal} indexed and searchable`}
            </span>
            <span>
              {lastUpdated
                ? `Updated ${timeAgo(lastUpdated) || 'just now'}`
                : 'Updated —'}
            </span>
          </div>
        </div>

        {/* Card 3: Activity & Alerts */}
        <div className="ref-card">
          <div className="ref-card-header">
            <span className="ref-card-title">Activity &amp; Alerts</span>
            <button onClick={() => navigate('/activity')} style={{ fontSize: 11, color: '#4f46e5', border: 'none', background: 'none', cursor: 'pointer', fontWeight: 600 }}>View All</button>
          </div>

          {/* The four cards this replaces were static JSX claiming
              "AI found 3 potential matches in case Cyber Fraud
              Investigation", "Unusual file behavior detected in Malware
              Incident Response", 'Keyword "confidential" found in 12 new
              documents' and "AI recommends 2 similar cases". Neither named
              case exists in the database, the keyword alert was not wired to
              the watchlist, the "recommendation" was not produced by
              anything, and the four timestamps never changed. All of it is
              now read from /dashboard/stats. */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {activeAlerts.map((a, i) => {
              const colour = a.level === 'critical' ? '#ef4444' : '#f59e0b'
              const tint = a.level === 'critical'
                ? 'rgba(239,68,68,0.04)' : 'rgba(245,158,11,0.04)'
              return (
                <div key={`alert-${i}`} style={{
                  display: 'flex', gap: 10, padding: 10, borderRadius: 8,
                  background: tint, borderLeft: `3px solid ${colour}`
                }}>
                  <div style={{ color: colour, flexShrink: 0, marginTop: 1 }}>
                    <AlertTriangle size={14} />
                  </div>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 11, fontWeight: 700, color: colour }}>{a.title}</span>
                      {a.action && (
                        <button
                          onClick={() => navigate(a.action)}
                          style={{ fontSize: 9, fontWeight: 700, color: colour, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
                        >
                          Review
                        </button>
                      )}
                    </div>
                    <p style={{ fontSize: 10, color: 'var(--text-secondary)', margin: '2px 0 0 0', lineHeight: 1.3 }}>
                      {a.message}
                    </p>
                  </div>
                </div>
              )
            })}

            {recentActivity.slice(0, activeAlerts.length === 0 ? 4 : 2).map((a, i) => (
              <div key={`act-${i}`} style={{
                display: 'flex', gap: 10, padding: 10, borderRadius: 8,
                background: 'rgba(59,130,246,0.04)', borderLeft: '3px solid #3b82f6'
              }}>
                <div style={{ color: '#3b82f6', flexShrink: 0, marginTop: 1 }}>
                  <Clock size={14} />
                </div>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 11, fontWeight: 700, color: '#3b82f6' }}>
                      {actionLabel(a.action)}
                    </span>
                    <span style={{ fontSize: 9, color: 'var(--text-muted)', flexShrink: 0 }}>
                      {timeAgo(a.at) || '—'}
                    </span>
                  </div>
                  <p style={{ fontSize: 10, color: 'var(--text-secondary)', margin: '2px 0 0 0', lineHeight: 1.3 }}>
                    {a.by ? `by ${a.by}` : 'system'}
                    {a.case_id ? ` · case ${a.case_id.slice(0, 8)}` : ''}
                  </p>
                </div>
              </div>
            ))}

            {activeAlerts.length === 0 && recentActivity.length === 0 && (
              <p style={{ fontSize: 11, color: 'var(--text-muted)', margin: 0, lineHeight: 1.4 }}>
                No recorded activity yet. An entry appears here when an
                integrity check fails, an account locks, or evidence fails to
                ingest.
              </p>
            )}
          </div>
        </div>

      </div>

      {/* Bottom Row (Case Status Distribution, Analysis Trend, Tools & Modules) */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '1.1fr 1.2fr 1.1fr',
        gap: 16,
      }}>

        {/* Card 1: Case Status Distribution */}
        <div className="ref-card" style={{ display: 'flex', flexDirection: 'column' }}>
          <div className="ref-card-header">
            <span className="ref-card-title">Case Status Distribution</span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flex: 1 }}>
            {/* Donut Chart */}
            <div style={{ position: 'relative', width: 120, height: 120, flexShrink: 0 }}>
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={caseStatusData}
                    cx="50%"
                    cy="50%"
                    innerRadius={40}
                    outerRadius={54}
                    paddingAngle={3}
                    dataKey="value"
                  >
                    {caseStatusData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
              <div style={{
                position: 'absolute', inset: 0,
                display: 'flex', flexDirection: 'column',
                alignItems: 'center', justifyContent: 'center',
                pointerEvents: 'none'
              }}>
                <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-primary)' }}>{totalCases}</span>
                <span style={{ fontSize: 8, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Total Cases</span>
              </div>
            </div>

            {/* Legends */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, flex: 1, marginLeft: 16 }}>
              {caseStatusData.map((d, i) => {
                // Was `Math.round((d.value / (totalCases || 1)) * 100) || 0`,
                // which was not clamped - with the old `|| 18` fallbacks the
                // seeded database rendered "Completed 12 (400%)" directly
                // under a donut reading "3 Total Cases". Slices are now
                // derived from the same by_status dict the donut centre is
                // summed from, but the clamp is kept so a total that ever
                // disagrees cannot print an impossible percentage.
                const pct = totalCases > 0
                  ? Math.min(100, Math.round((d.value / totalCases) * 100))
                  : 0
                return (
                  <div key={d.name} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                      <span style={{ width: 6, height: 6, borderRadius: '50%', background: d.color, flexShrink: 0 }} />
                      <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {d.name}
                      </span>
                    </div>
                    <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-primary)' }}>
                      {d.value} <span style={{ fontWeight: 500, color: 'var(--text-muted)' }}>({pct}%)</span>
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        </div>

        {/* Card 2: Analysis Trend */}
        <div className="ref-card" style={{ display: 'flex', flexDirection: 'column' }}>
          <div className="ref-card-header" style={{ marginBottom: 12 }}>
            <span className="ref-card-title">Entities Extracted</span>
            <span style={{ fontSize: 10, color: 'var(--text-muted)', fontWeight: 600 }}>
              {(stats.entities?.total || 0).toLocaleString()} total
            </span>
          </div>

          {/* Replaces the "Analysis Trend" area chart: seven hardcoded points
              dated 14-20 May, with a "Last 7 Days / Last 30 Days" select
              that had no onChange and so changed nothing. There is no time
              series behind /dashboard/stats to plot, so rather than invent
              one this shows the entity-type breakdown, which is measured. */}
          {entityTypeRows.length === 0 ? (
            <p style={{ fontSize: 11, color: 'var(--text-muted)', margin: 0, lineHeight: 1.4 }}>
              No entities extracted yet. They appear here once evidence has
              been ingested and named-entity recognition has run over it.
            </p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 9, flex: 1, justifyContent: 'center' }}>
              {entityTypeRows.map(e => (
                <div key={e.name}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                    <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-secondary)' }}>{e.name}</span>
                    <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-primary)' }}>{e.value}</span>
                  </div>
                  <div style={{ height: 5, background: 'var(--bg-hover)', borderRadius: 3, overflow: 'hidden' }}>
                    <div style={{
                      width: `${e.pct}%`, height: '100%',
                      background: '#4f46e5', borderRadius: 3,
                    }} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Card 3: Tools & Modules Grid */}
        <div className="ref-card">
          <div className="ref-card-header" style={{ marginBottom: 12 }}>
            <span className="ref-card-title">Tools & Modules</span>
          </div>

          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 1fr)',
            gap: 10,
          }}>
            {/* Tool 1: File Carver */}
            <button
              onClick={() => handleToolClick('artifacts')}
              style={{
                display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                padding: '10px 4px', borderRadius: 8, border: 'none', background: 'rgba(59,130,246,0.06)',
                color: '#3b82f6', cursor: 'pointer', transition: 'all 0.15s'
              }}
              onMouseEnter={e => e.currentTarget.style.filter = 'brightness(0.95)'}
              onMouseLeave={e => e.currentTarget.style.filter = 'none'}
            >
              <Database size={15} style={{ marginBottom: 4 }} />
              <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-primary)' }}>Artifacts</span>
            </button>

            {/* Tool 2: Hash Analyzer */}
            <button
              onClick={() => handleToolClick('evidence')}
              style={{
                display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                padding: '10px 4px', borderRadius: 8, border: 'none', background: 'rgba(16,185,129,0.06)',
                color: '#10b981', cursor: 'pointer', transition: 'all 0.15s'
              }}
              onMouseEnter={e => e.currentTarget.style.filter = 'brightness(0.95)'}
              onMouseLeave={e => e.currentTarget.style.filter = 'none'}
            >
              <span style={{ fontSize: 13, fontWeight: 800, marginBottom: 4, fontFamily: 'monospace', lineHeight: 1.15 }}>#</span>
              <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-primary)' }}>Evidence</span>
            </button>

            {/* Tool 3: Entity Graph. This was labelled "Metadata
                Extractor" and pointed at `artifacts` - the same destination as
                the card above it. There is no metadata-extraction module in
                this product and no malware scanner either; both names
                advertised capabilities that do not exist. Repointed at a
                page that does, and named after what it actually opens. */}
            <button
              onClick={() => handleToolClick('entities')}
              style={{
                display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                padding: '10px 4px', borderRadius: 8, border: 'none', background: 'rgba(139,92,246,0.06)',
                color: '#8b5cf6', cursor: 'pointer', transition: 'all 0.15s'
              }}
              onMouseEnter={e => e.currentTarget.style.filter = 'brightness(0.95)'}
              onMouseLeave={e => e.currentTarget.style.filter = 'none'}
            >
              <FileText size={15} style={{ marginBottom: 4 }} />
              <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-primary)' }}>Entity Graph</span>
            </button>

            {/* Tool 4: Malware Scanner */}
            <button
              onClick={() => handleToolClick('anomalies')}
              style={{
                display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                padding: '10px 4px', borderRadius: 8, border: 'none', background: 'rgba(245,158,11,0.06)',
                color: '#f59e0b', cursor: 'pointer', transition: 'all 0.15s'
              }}
              onMouseEnter={e => e.currentTarget.style.filter = 'brightness(0.95)'}
              onMouseLeave={e => e.currentTarget.style.filter = 'none'}
            >
              <AlertTriangle size={15} style={{ marginBottom: 4 }} />
              <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-primary)' }}>Anomalies</span>
            </button>

            {/* Tool 5: Timeline Builder */}
            <button
              onClick={() => handleToolClick('timeline')}
              style={{
                display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                padding: '10px 4px', borderRadius: 8, border: 'none', background: 'rgba(6,182,212,0.06)',
                color: '#06b6d4', cursor: 'pointer', transition: 'all 0.15s'
              }}
              onMouseEnter={e => e.currentTarget.style.filter = 'brightness(0.95)'}
              onMouseLeave={e => e.currentTarget.style.filter = 'none'}
            >
              <Clock size={15} style={{ marginBottom: 4 }} />
              <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-primary)' }}>Timeline</span>
            </button>

            {/* Tool 6: Chat with AI */}
            <button
              onClick={() => handleToolClick('investigate')}
              style={{
                display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                padding: '10px 4px', borderRadius: 8, border: 'none', background: 'rgba(236,72,153,0.06)',
                color: '#ec4899', cursor: 'pointer', transition: 'all 0.15s'
              }}
              onMouseEnter={e => e.currentTarget.style.filter = 'brightness(0.95)'}
              onMouseLeave={e => e.currentTarget.style.filter = 'none'}
            >
              <MessageSquare size={15} style={{ marginBottom: 4 }} />
              <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-primary)' }}>Ask AI</span>
            </button>
          </div>
        </div>

      </div>
      
      {/* Footer */}
      <div style={{ display: 'flex', justifyContent: 'center', marginTop: 24, fontSize: 10, color: 'var(--text-muted)', fontWeight: 600 }}>
        {/* Was hardcoded to "All times are in IST (UTC +05:30)", which is
            wrong anywhere else and was not a timezone this app ever
            configured. Timestamps render in the viewer's own locale. */}
        Times shown in your local timezone
      </div>

    </div>
  )
}
