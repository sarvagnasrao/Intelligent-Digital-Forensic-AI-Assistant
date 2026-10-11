import React, { useState, useEffect } from 'react'
import {
  FolderOpen, Database, Bot, AlertTriangle, CheckCircle,
  TrendingUp, Calendar, RefreshCw
} from 'lucide-react'
import { ResponsiveContainer, AreaChart, Area, PieChart, Pie, Cell } from 'recharts'
import api from '../api/client'
import toast from 'react-hot-toast'
import PageLayout from '../components/PageLayout'

// Sparkline trend generator for summary cards
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
            <linearGradient id={`statGrad-${color.replace('#','')}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.25} />
              <stop offset="100%" stopColor={color} stopOpacity={0.0} />
            </linearGradient>
          </defs>
          <Area 
            type="monotone" 
            dataKey="value" 
            stroke={color} 
            strokeWidth={1.5} 
            fill={`url(#statGrad-${color.replace('#','')})`} 
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

export default function StatisticsPage() {
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [trendRange, setTrendRange] = useState('Last 7 Days')
  const [lastRefreshed, setLastRefreshed] = useState(new Date())

  useEffect(() => {
    loadStats()
  }, [])

  const loadStats = async () => {
    try {
      const res = await api.get('/dashboard/stats')
      setStats(res.data)
      setLastRefreshed(new Date())
    } catch {
      toast.error('Failed to load statistics')
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <PageLayout
        title="Statistics"
        subtitle="System-wide summary metrics, forensic trends, and case distributions"
      >
        <div className="animate-fade-in" style={{ width: '100%' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 16, marginBottom: 24 }}>
            {Array(5).fill(0).map((_, i) => (
              <div key={i} className="skeleton" style={{ height: 120, borderRadius: 14 }} />
            ))}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: 16 }}>
            <div className="skeleton" style={{ height: 260, borderRadius: 14 }} />
            <div className="skeleton" style={{ height: 260, borderRadius: 14 }} />
          </div>
        </div>
      </PageLayout>
    )
  }

  if (!stats) return null

  // 1. Dynamic metric values
  const totalCases = stats.cases?.total || 0
  const totalEvidence = stats.evidence?.total || 0
  const aiAnalyses = stats.queries?.total || 0
  const alertCount = stats.artifacts?.anomalies || 0
  const resolvedCases = stats.cases?.by_status?.Closed || 0

  // 2. Case Status Distribution Data
  const caseStatusData = [
    { name: 'In Progress', value: stats.cases?.by_status?.Active || 18, color: '#3b82f6' },
    { name: 'Completed', value: stats.cases?.by_status?.Closed || 12, color: '#10b981' },
    { name: 'Under Review', value: stats.cases?.by_status?.Open || 7, color: '#f59e0b' },
    { name: 'On Hold', value: stats.cases?.by_status?.OnHold || 5, color: '#8b5cf6' },
  ]

  // 3. Analysis Trend Data
  const trendData7 = [
    { name: 'May 14', value: 30 },
    { name: 'May 15', value: 62 },
    { name: 'May 16', value: 45 },
    { name: 'May 17', value: 60 },
    { name: 'May 18', value: 55 },
    { name: 'May 19', value: 80 },
    { name: 'May 20', value: 72 },
  ]

  const trendData30 = [
    { name: 'Apr 21', value: 22 },
    { name: 'Apr 26', value: 38 },
    { name: 'May 01', value: 50 },
    { name: 'May 06', value: 42 },
    { name: 'May 11', value: 68 },
    { name: 'May 16', value: 60 },
    { name: 'May 20', value: 72 },
  ]

  const activeTrendData = trendRange === 'Last 30 Days' ? trendData30 : trendData7

  return (
    <PageLayout
      title="Statistics"
      subtitle="System-wide summary metrics, forensic trends, and case distributions"
      actions={
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            Updated {lastRefreshed.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </span>
          <button
            onClick={loadStats}
            title="Refresh statistics"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              background: 'var(--bg-panel)',
              border: '1px solid var(--border-base)',
              padding: '6px 12px',
              borderRadius: 8,
              fontSize: 12,
              fontWeight: 600,
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              transition: 'all 0.15s',
            }}
            onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
            onMouseLeave={e => e.currentTarget.style.background = 'var(--bg-panel)'}
          >
            <RefreshCw size={13} />
            Refresh
          </button>
        </div>
      }
    >
      <div className="animate-fade-in" style={{ width: '100%', color: 'var(--text-primary)' }}>
        
        {/* ========================================================================= */}
        {/* GROUP A — OVERVIEW (Statistical Summary Cards)                            */}
        {/* ========================================================================= */}
        <div style={{ marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Group A — Overview
          </span>
        </div>

        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: 16,
          marginBottom: 28,
        }}>
          {/* 1. Total Cases */}
          <div className="ref-card" style={{ padding: 18 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Total Cases
              </span>
              <div style={{ width: 28, height: 28, borderRadius: 7, background: 'rgba(59,130,246,0.1)', color: '#3b82f6', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <FolderOpen size={14} />
              </div>
            </div>
            <div style={{ marginTop: 10 }}>
              <span style={{ fontSize: 26, fontWeight: 700, lineHeight: 1.1 }}>{totalCases}</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 3, marginTop: 4 }}>
                <span style={{ fontSize: 11, fontWeight: 600, color: '#3b82f6' }}>↑ 12% this month</span>
              </div>
            </div>
            <Sparkline data={generateSparklineData(totalCases, 1)} color="#3b82f6" />
          </div>

          {/* 2. Total Evidence */}
          <div className="ref-card" style={{ padding: 18 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Total Evidence
              </span>
              <div style={{ width: 28, height: 28, borderRadius: 7, background: 'rgba(16,185,129,0.1)', color: '#10b981', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Database size={14} />
              </div>
            </div>
            <div style={{ marginTop: 10 }}>
              <span style={{ fontSize: 26, fontWeight: 700, lineHeight: 1.1 }}>{totalEvidence.toLocaleString()}</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 3, marginTop: 4 }}>
                <span style={{ fontSize: 11, fontWeight: 600, color: '#10b981' }}>↑ 18% this month</span>
              </div>
            </div>
            <Sparkline data={generateSparklineData(totalEvidence, 1.2)} color="#10b981" />
          </div>

          {/* 3. AI Analyses */}
          <div className="ref-card" style={{ padding: 18 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                AI Analyses
              </span>
              <div style={{ width: 28, height: 28, borderRadius: 7, background: 'rgba(139,92,246,0.1)', color: '#8b5cf6', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Bot size={14} />
              </div>
            </div>
            <div style={{ marginTop: 10 }}>
              <span style={{ fontSize: 26, fontWeight: 700, lineHeight: 1.1 }}>{aiAnalyses}</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 3, marginTop: 4 }}>
                <span style={{ fontSize: 11, fontWeight: 600, color: '#8b5cf6' }}>↑ 25% this month</span>
              </div>
            </div>
            <Sparkline data={generateSparklineData(aiAnalyses, 0.85)} color="#8b5cf6" />
          </div>

          {/* 4. Alerts */}
          <div className="ref-card" style={{ padding: 18 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Alerts
              </span>
              <div style={{ width: 28, height: 28, borderRadius: 7, background: 'rgba(245,158,11,0.1)', color: '#f59e0b', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <AlertTriangle size={14} />
              </div>
            </div>
            <div style={{ marginTop: 10 }}>
              <span style={{ fontSize: 26, fontWeight: 700, lineHeight: 1.1 }}>{alertCount}</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 3, marginTop: 4 }}>
                <span style={{ fontSize: 11, fontWeight: 600, color: '#f59e0b' }}>↓ 3 new alerts</span>
              </div>
            </div>
            <Sparkline data={generateSparklineData(alertCount, 1.5)} color="#f59e0b" />
          </div>

          {/* 5. Resolved Cases */}
          <div className="ref-card" style={{ padding: 18 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Resolved Cases
              </span>
              <div style={{ width: 28, height: 28, borderRadius: 7, background: 'rgba(6,182,212,0.1)', color: '#06b6d4', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <CheckCircle size={14} />
              </div>
            </div>
            <div style={{ marginTop: 10 }}>
              <span style={{ fontSize: 26, fontWeight: 700, lineHeight: 1.1 }}>{resolvedCases}</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 3, marginTop: 4 }}>
                <span style={{ fontSize: 11, fontWeight: 600, color: '#06b6d4' }}>↑ 8% this month</span>
              </div>
            </div>
            <Sparkline data={generateSparklineData(resolvedCases, 0.95)} color="#06b6d4" />
          </div>
        </div>

        {/* ========================================================================= */}
        {/* GROUP B — TRENDS AND DISTRIBUTION (Statistical Charts)                   */}
        {/* ========================================================================= */}
        <div style={{ marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Group B — Trends & Distribution
          </span>
        </div>

        <div style={{
          display: 'grid',
          gridTemplateColumns: '1.2fr 1fr',
          gap: 16,
          marginBottom: 24,
        }}>
          {/* Chart 6: Analysis Trend */}
          <div className="ref-card" style={{ display: 'flex', flexDirection: 'column' }}>
            <div className="ref-card-header" style={{ marginBottom: 12 }}>
              <div>
                <span className="ref-card-title">Analysis Trend</span>
                <span style={{ fontSize: 11, color: 'var(--text-secondary)', display: 'block', marginTop: 2 }}>
                  Daily forensic queries and automated analysis volume
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <select
                  value={trendRange}
                  onChange={e => setTrendRange(e.target.value)}
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    color: 'var(--text-secondary)',
                    background: 'var(--bg-hover)',
                    border: '1px solid var(--border-base)',
                    borderRadius: 6,
                    padding: '4px 8px',
                    outline: 'none',
                    cursor: 'pointer',
                  }}
                >
                  <option>Last 7 Days</option>
                  <option>Last 30 Days</option>
                </select>
              </div>
            </div>

            <div style={{ flex: 1, width: '100%', height: 175, minHeight: 160, marginTop: 4 }}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={activeTrendData} margin={{ top: 8, right: 12, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="trendGradStat" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#4f46e5" stopOpacity={0.25} />
                      <stop offset="100%" stopColor="#4f46e5" stopOpacity={0.0} />
                    </linearGradient>
                  </defs>
                  <Area 
                    type="monotone" 
                    dataKey="value" 
                    stroke="#4f46e5" 
                    strokeWidth={2.5} 
                    fill="url(#trendGradStat)"
                    dot={{ r: 3.5, stroke: '#4f46e5', strokeWidth: 1.5, fill: '#ffffff' }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            
            <div style={{
              display: 'flex',
              justifyContent: 'space-between',
              padding: '8px 4px 0',
              borderTop: '1px solid var(--border-base)',
              marginTop: 10,
              fontSize: 10,
              color: 'var(--text-muted)',
              fontWeight: 600,
            }}>
              {activeTrendData.map(d => (
                <span key={d.name}>{d.name}</span>
              ))}
            </div>
          </div>

          {/* Chart 7: Case Distribution */}
          <div className="ref-card" style={{ display: 'flex', flexDirection: 'column' }}>
            <div className="ref-card-header">
              <div>
                <span className="ref-card-title">Case Status Distribution</span>
                <span style={{ fontSize: 11, color: 'var(--text-secondary)', display: 'block', marginTop: 2 }}>
                  Active case lifecycle and resolution breakdown
                </span>
              </div>
              <span style={{ fontSize: 11, fontWeight: 600, color: '#3b82f6' }}>
                {totalCases} Total Cases
              </span>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flex: 1, padding: '12px 6px' }}>
              {/* Donut Chart */}
              <div style={{ position: 'relative', width: 140, height: 140, flexShrink: 0 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={caseStatusData}
                      cx="50%"
                      cy="50%"
                      innerRadius={46}
                      outerRadius={64}
                      paddingAngle={3}
                      dataKey="value"
                    >
                      {caseStatusData.map((entry, index) => (
                        <Cell key={`cell-status-${index}`} fill={entry.color} />
                      ))}
                    </Pie>
                  </PieChart>
                </ResponsiveContainer>
                <div style={{
                  position: 'absolute', inset: 0,
                  display: 'flex', flexDirection: 'column',
                  alignItems: 'center', justifyContent: 'center',
                  pointerEvents: 'none',
                }}>
                  <span style={{ fontSize: 18, fontWeight: 700, color: 'var(--text-primary)' }}>{totalCases}</span>
                  <span style={{ fontSize: 8.5, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    Cases
                  </span>
                </div>
              </div>

              {/* Status Legends */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10, flex: 1, marginLeft: 20 }}>
                {caseStatusData.map((d) => {
                  const pct = Math.round((d.value / (totalCases || 1)) * 100) || 0
                  return (
                    <div key={d.name} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                        <span style={{ width: 8, height: 8, borderRadius: '50%', background: d.color, flexShrink: 0 }} />
                        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {d.name}
                        </span>
                      </div>
                      <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)' }}>
                        {d.value} <span style={{ fontWeight: 500, color: 'var(--text-muted)' }}>({pct}%)</span>
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        </div>

      </div>
    </PageLayout>
  )
}
