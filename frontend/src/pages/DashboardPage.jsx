import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  FolderOpen, Database, Cpu, AlertTriangle, CheckCircle, FileText, Bot, Clock, 
  Search, MessageSquare, Plus, Upload, UserCheck, ArrowUpRight, TrendingUp, Sparkles, HelpCircle
} from 'lucide-react'
import { ResponsiveContainer, PieChart, Pie, Cell } from 'recharts'
import api from '../api/client'
import { useAuth } from '../context/AuthContext'
import toast from 'react-hot-toast'

// Mock sparkline trends for the metric cards
const generateSparklineData = (value, multiplier = 1) => {
  const seed = value || 10
  return [
    { value: seed * 0.7 * multiplier },
    { value: seed * 0.9 * multiplier },
    { value: seed * 0.75 * multiplier },
    { value: seed * 1.1 * multiplier },
    { value: seed * 0.85 * multiplier },
    { value: seed * 1.2 * multiplier },
    { value: seed * 1.1 * multiplier },
  ]
}

// Sparkline Mini-Chart Component
function Sparkline({ data, color }) {
  return (
    <div style={{ width: '100%', height: 28, marginTop: 10 }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 2, right: 2, left: 2, bottom: 2 }}>
          <defs>
            <linearGradient id={`sparkGrad-${color.replace('#','')}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.25} />
              <stop offset="100%" stopColor={color} stopOpacity={0.0} />
            </linearGradient>
          </defs>
          <Area 
            type="monotone" 
            dataKey="value" 
            stroke={color} 
            strokeWidth={1.5} 
            fill={`url(#sparkGrad-${color.replace('#','')})`} 
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

export default function DashboardPage({ activeCaseId, setActiveCaseId }) {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => { loadStats() }, [])

  const loadStats = async () => {
    try {
      const res = await api.get('/dashboard/stats')
      setStats(res.data)
      
      // Auto-set active case if none is set and cases exist
      if (!activeCaseId && res.data.recent_cases?.length > 0) {
        setActiveCaseId(res.data.recent_cases[0].id)
      }
    } catch {
      toast.error('Failed to load stats')
    } finally {
      setLoading(false)
    }
  }

  if (loading) return (
    <div className="animate-fade-in" style={{ width: '100%' }}>
      <div className="skeleton" style={{ height: 34, width: 280, borderRadius: 8, marginBottom: 8 }} />
      <div className="skeleton" style={{ height: 16, width: 220, borderRadius: 6, marginBottom: 28 }} />
      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1.1fr 1.1fr', gap: 16, marginBottom: 24 }}>
        <div className="skeleton" style={{ height: 260, borderRadius: 14 }} />
        <div className="skeleton" style={{ height: 260, borderRadius: 14 }} />
        <div className="skeleton" style={{ height: 260, borderRadius: 14 }} />
      </div>
    </div>
  )

  if (!stats) return null

  // 1. Calculations for dynamic metric values
  const totalCases = stats.cases?.total || 0
  const totalEvidence = stats.evidence?.total || 0
  const aiAnalyses = stats.queries?.total || 0
  const alertCount = stats.artifacts?.anomalies || 0
  const resolvedCases = stats.cases?.by_status?.Closed || 0

  // 2. Evidence Overview Donut Chart Data (proportional to total evidence)
  const evTotal = totalEvidence || 1248
  const evidenceOverviewData = [
    { name: 'Images', value: Math.round(evTotal * 0.36), color: '#3b82f6' },
    { name: 'Documents', value: Math.round(evTotal * 0.24), color: '#10b981' },
    { name: 'Videos', value: Math.round(evTotal * 0.15), color: '#8b5cf6' },
    { name: 'Audio', value: Math.round(evTotal * 0.10), color: '#fbbf24' },
    { name: 'Archives', value: Math.round(evTotal * 0.09), color: '#06b6d4' },
    { name: 'Others', value: Math.round(evTotal * 0.06), color: '#ec4899' },
  ]

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
            <span>Evidence size: <strong>256.7 GB</strong></span>
            <span>Last updated: 10 min ago</span>
          </div>
        </div>

        {/* Card 3: AI Insights */}
        <div className="ref-card">
          <div className="ref-card-header">
            <span className="ref-card-title">AI Insights</span>
            <button onClick={() => handleToolClick('investigate')} style={{ fontSize: 11, color: '#4f46e5', border: 'none', background: 'none', cursor: 'pointer', fontWeight: 600 }}>View All</button>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {/* Insight 1: Potential Match Found */}
            <div style={{
              display: 'flex', gap: 10, padding: 10, borderRadius: 8,
              background: 'rgba(16,185,129,0.04)', borderLeft: '3px solid #10b981'
            }}>
              <div style={{ color: '#10b981', flexShrink: 0, marginTop: 1 }}>
                <UserCheck size={14} />
              </div>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 11, fontWeight: 700, color: '#10b981' }}>Potential Match Found</span>
                  <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>10 min ago</span>
                </div>
                <p style={{ fontSize: 10, color: 'var(--text-secondary)', margin: '2px 0 0 0', lineHeight: 1.3 }}>
                  AI found 3 potential matches in case Cyber Fraud Investigation
                </p>
              </div>
            </div>

            {/* Insight 2: Anomaly Detected */}
            <div style={{
              display: 'flex', gap: 10, padding: 10, borderRadius: 8,
              background: 'rgba(245,158,11,0.04)', borderLeft: '3px solid #f59e0b'
            }}>
              <div style={{ color: '#f59e0b', flexShrink: 0, marginTop: 1 }}>
                <AlertTriangle size={14} />
              </div>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 11, fontWeight: 700, color: '#f59e0b' }}>Anomaly Detected</span>
                  <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>25 min ago</span>
                </div>
                <p style={{ fontSize: 10, color: 'var(--text-secondary)', margin: '2px 0 0 0', lineHeight: 1.3 }}>
                  Unusual file behavior detected in Malware Incident Response
                </p>
              </div>
            </div>

            {/* Insight 3: Keyword Alert */}
            <div style={{
              display: 'flex', gap: 10, padding: 10, borderRadius: 8,
              background: 'rgba(59,130,246,0.04)', borderLeft: '3px solid #3b82f6'
            }}>
              <div style={{ color: '#3b82f6', flexShrink: 0, marginTop: 1 }}>
                <Search size={14} />
              </div>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 11, fontWeight: 700, color: '#3b82f6' }}>Keyword Alert</span>
                  <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>1 hour ago</span>
                </div>
                <p style={{ fontSize: 10, color: 'var(--text-secondary)', margin: '2px 0 0 0', lineHeight: 1.3 }}>
                  Keyword "confidential" found in 12 new documents
                </p>
              </div>
            </div>

            {/* Insight 4: Similar Case Recommendation */}
            <div style={{
              display: 'flex', gap: 10, padding: 10, borderRadius: 8,
              background: 'rgba(139,92,246,0.04)', borderLeft: '3px solid #8b5cf6'
            }}>
              <div style={{ color: '#8b5cf6', flexShrink: 0, marginTop: 1 }}>
                <TrendingUp size={14} />
              </div>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 11, fontWeight: 700, color: '#8b5cf6' }}>Similar Case Recommendation</span>
                  <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>2 hours ago</span>
                </div>
                <p style={{ fontSize: 10, color: 'var(--text-secondary)', margin: '2px 0 0 0', lineHeight: 1.3 }}>
                  AI recommends 2 similar cases for reference
                </p>
              </div>
            </div>
          </div>
        </div>

      </div>

      {/* Tools & Modules Panel */}
      <div className="ref-card" style={{ marginBottom: 16 }}>
        <div className="ref-card-header" style={{ marginBottom: 14 }}>
          <div>
            <span className="ref-card-title">Tools & Modules</span>
            <span style={{ fontSize: 11, color: 'var(--text-secondary)', marginLeft: 10 }}>Quick access to forensic tool suite</span>
          </div>
        </div>

        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
          gap: 12,
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
              <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-primary)' }}>File Carver</span>
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
              <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-primary)' }}>Hash Analyzer</span>
            </button>

            {/* Tool 3: Metadata Extractor */}
            <button
              onClick={() => handleToolClick('artifacts')}
              style={{
                display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                padding: '10px 4px', borderRadius: 8, border: 'none', background: 'rgba(139,92,246,0.06)',
                color: '#8b5cf6', cursor: 'pointer', transition: 'all 0.15s'
              }}
              onMouseEnter={e => e.currentTarget.style.filter = 'brightness(0.95)'}
              onMouseLeave={e => e.currentTarget.style.filter = 'none'}
            >
              <FileText size={15} style={{ marginBottom: 4 }} />
              <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-primary)' }}>Metadata Ext.</span>
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
              <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-primary)' }}>Malware Scan</span>
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
              <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-primary)' }}>Timeline Bld.</span>
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
              <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-primary)' }}>Chat with AI</span>
            </button>
          </div>
        </div>

      {/* Footer timezone indicator */}
      <div style={{ display: 'flex', justifyContent: 'center', marginTop: 24, fontSize: 10, color: 'var(--text-muted)', fontWeight: 600 }}>
        All times are in IST (UTC +05:30)
      </div>

    </div>
  )
}
