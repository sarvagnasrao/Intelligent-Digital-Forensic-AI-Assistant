import React, { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Upload, Bot, Network, StickyNote,
  ShieldCheck, HardDrive, Clock,
  FileText, AlertTriangle, UserSearch,
  Users, MapPin, Wifi, Crosshair, Globe,
  Sparkles, Key, GitCompare, Settings2, Download, Zap,
} from 'lucide-react'
import { getCase, getEvidence, getEntities, exportCase } from '../api/client'
import Badge from '../components/Badge'
import AnimStatCard from '../components/AnimStatCard'
import TiltActionCard from '../components/TiltActionCard'
import toast from 'react-hot-toast'

const STATS_CONFIG = [
  { key: 'evidence',  label: 'Evidence',  icon: FileText, color: '#818cf8' },
  { key: 'queries',   label: 'Queries',   icon: Bot,      color: '#a78bfa' },
  { key: 'persons',   label: 'Persons',   icon: Users,    color: '#f87171' },
  { key: 'locations', label: 'Locations', icon: MapPin,   color: '#34d399' },
  { key: 'ips',       label: 'IPs',       icon: Wifi,     color: '#67e8f9' },
]

const ACTIONS = [
  { icon: Upload,        label: 'Evidence',    desc: 'Upload files',          path: 'evidence',    color: '#818cf8' },
  { icon: HardDrive,     label: 'Artifacts',   desc: 'Browse extracted',      path: 'artifacts',   color: '#60a5fa' },
  { icon: Clock,         label: 'Timeline',    desc: 'File activity',         path: 'timeline',    color: '#34d399' },
  { icon: Bot,           label: 'Investigate', desc: 'AI analysis',           path: 'investigate', color: '#a78bfa' },
  { icon: Network,       label: 'Entity Map',  desc: 'Relationships',         path: 'entities',    color: '#22d3ee' },
  { icon: AlertTriangle, label: 'Anomalies',   desc: 'Timestamp flags',       path: 'anomalies',   color: '#fbbf24' },
  { icon: UserSearch,    label: 'Profiles',    desc: 'AI suspect profile',    path: 'profiles',    color: '#f472b6' },
  { icon: FileText,      label: 'Reports',     desc: 'PDF generation',        path: 'reports',     color: '#fb923c' },
  { icon: Crosshair,     label: 'Watchlist',   desc: 'Keyword alerts',        path: 'watchlist',   color: '#ef4444' },
  { icon: Key,           label: 'Credentials', desc: 'Passwords & API keys',  path: 'credentials', color: '#f87171' },
  { icon: Zap,           label: 'Contradictions', desc: 'AI inconsistency finder', path: 'contradictions', color: '#fbbf24' },
  { icon: GitCompare,    label: 'Compare',     desc: 'Side-by-side view',    path: 'compare',     color: '#67e8f9' },
  { icon: Globe,         label: 'Geo Map',     desc: 'GPS & IP locations',    path: 'geomap',      color: '#4ade80' },
  { icon: StickyNote,    label: 'Notes',       desc: 'Case notes',            path: 'notes',       color: '#fde68a' },
  { icon: ShieldCheck,   label: 'Audit Log',   desc: 'Chain of custody',      path: 'audit',       color: '#94a3b8' },
  { icon: Settings2,     label: 'Access',      desc: 'Manage user access',    path: 'settings',    color: '#c084fc' },
]

export default function CaseDetailPage() {
  const { caseId } = useParams()
  const navigate = useNavigate()
  const [caseData, setCaseData] = useState(null)
  const [evidence, setEvidence] = useState([])
  const [entities, setEntities] = useState([])

  useEffect(() => { loadData() }, [caseId])

  const loadData = async () => {
    try {
      const [cR, eR, entR] = await Promise.all([
        getCase(caseId),
        getEvidence(caseId),
        getEntities(caseId, { page_size: 200 }),
      ])
      setCaseData(cR.data)
      setEvidence(eR.data.items || eR.data)
      setEntities(entR.data.items || entR.data)
    } catch {
      toast.error('Failed to load case')
    }
  }

  const handleExport = async () => {
    try {
      const res = await exportCase(caseId)
      const url = URL.createObjectURL(res.data)
      const a   = document.createElement('a')
      a.href    = url
      a.download = `idfai_case_${(caseData?.case_name || caseId).replace(/\s+/g, '_')}.zip`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      toast.success('Case exported successfully')
    } catch {
      toast.error('Export failed')
    }
  }

  if (!caseData) return (
    <div style={{ width: '100%' }}>
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(5, 1fr)',
        gap: 12,
        marginTop: 24,
        marginBottom: 28,
      }}>
        {Array(5).fill(0).map((_, i) => (
          <div key={i} className="skeleton" style={{ height: 110, borderRadius: 14 }} />
        ))}
      </div>
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(4, 1fr)',
        gap: 10,
      }}>
        {Array(8).fill(0).map((_, i) => (
          <div key={i} className="skeleton" style={{ height: 120, borderRadius: 16 }} />
        ))}
      </div>
    </div>
  )

  const ec = entities.reduce((a, e) => {
    a[e.entity_type] = (a[e.entity_type] || 0) + 1
    return a
  }, {})

  const statsValues = [
    Array.isArray(evidence) ? evidence.length : 0,
    caseData.query_count || 0,
    ec.Person || 0,
    ec.Location || 0,
    ec.IP || 0,
  ]

  return (
    <div className="animate-fade-in">
      {/* Page header */}
      <div style={{ width: '100%', marginBottom: 28 }}>
        <div style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: 16,
        }}>
          <div>
            <h1 style={{
              fontSize: 28,
              fontWeight: 700,
              letterSpacing: '-0.03em',
              lineHeight: 1.2,
              background: 'linear-gradient(135deg, #fff 30%, #818cf8 100%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
            }}>
              {caseData.case_name}
            </h1>
            <p style={{
              fontSize: 13,
              color: 'var(--color-white-6)',
              marginTop: 4,
            }}>
              {caseData.description || `Case ID: ${caseData.id.slice(0, 8)}`}
            </p>
          </div>
          <div style={{
            display: 'flex',
            gap: 8,
            alignItems: 'center',
            marginTop: 4,
            flexWrap: 'wrap',
          }}>
            <Badge label={caseData.status} />
            <Badge label={caseData.priority} />
            {caseData.case_number && (
              <span style={{
                fontSize: 11,
                color: 'var(--color-white-2)',
                fontFamily: 'monospace',
              }}>
                #{caseData.case_number}
              </span>
            )}
            <span style={{ fontSize: 11, color: 'var(--color-white-6)' }}>
              by {caseData.created_by}
            </span>
            <button
              onClick={handleExport}
              title="Export case as ZIP"
              style={{
                display: 'flex', alignItems: 'center', gap: 5,
                padding: '5px 12px', borderRadius: 7, marginLeft: 6,
                background: 'var(--color-white-04)',
                border: '1px solid rgba(255,255,255,0.09)',
                color: 'rgba(255,255,255,0.45)',
                fontSize: 11, cursor: 'pointer',
                transition: 'all 0.15s',
              }}
              onMouseEnter={e => {
                e.currentTarget.style.color = 'var(--text-primary)'
                e.currentTarget.style.borderColor = 'var(--color-white-2)'
              }}
              onMouseLeave={e => {
                e.currentTarget.style.color = 'rgba(255,255,255,0.45)'
                e.currentTarget.style.borderColor = 'var(--color-white-09)'
              }}
            >
              <Download size={11} />
              Export
            </button>
          </div>
        </div>
      </div>

      <div style={{ width: '100%' }}>
        {/* Stat cards */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(5, 1fr)',
          gap: 12,
          marginBottom: 28,
        }}>
          {STATS_CONFIG.map((s, i) => (
            <AnimStatCard
              key={s.key}
              icon={s.icon}
              label={s.label}
              value={statsValues[i]}
              color={s.color}
              delay={i * 60}
            />
          ))}
        </div>

        {/* Section label */}
        <p style={{
          fontSize: 10,
          fontWeight: 600,
          color: 'var(--color-white-2)',
          textTransform: 'uppercase',
          letterSpacing: '0.1em',
          marginBottom: 14,
        }}>
          Navigation
        </p>

        {/* Action grid */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: 10,
        }}>
          {ACTIONS.map((action, i) => (
            <TiltActionCard
              key={action.path}
              icon={action.icon}
              label={action.label}
              desc={action.desc}
              color={action.color}
              animDelay={i * 35}
              onClick={() => navigate(`/cases/${caseId}/${action.path}`)}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
