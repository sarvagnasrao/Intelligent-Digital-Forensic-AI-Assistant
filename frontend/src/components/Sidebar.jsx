import React, { useState, useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  Fingerprint, LayoutDashboard, Layers, Activity, Users, Plus, Search,
  ChevronRight, Upload, HardDrive, Clock, Bot, Network, UserSearch,
  AlertTriangle, Crosshair, Key, Zap, GitCompare, Globe, FileText,
  StickyNote, ShieldCheck, Settings2, Settings, LogOut, Cpu, Database,
  PanelLeftClose
} from 'lucide-react'
import { getCases } from '../api/client'
import { useAuth } from '../context/AuthContext'

// ── Global navigation ────────────────────────────────────────────────────
// These routes are not scoped to a case.
const NAV_TOP = [
  { icon: LayoutDashboard, label: 'Dashboard',    path: '/'            },
  { icon: Layers,          label: 'Queue',         path: '/queue'       },
  { icon: Activity,        label: 'System Health', path: '/health'      },
  { icon: ShieldCheck,    label: 'Logs & Activity', path: '/activity'  },
]

// ── Per-case navigation ──────────────────────────────────────────────────
// Rendered nested beneath each case in the list, so the analyst always
// sees which case a tool belongs to. Rendered as
// `/cases/<caseId>/<path>`.
const CASE_NAV = [
  { icon: Upload,        label: 'Evidence',       path: 'evidence'       },
  { icon: HardDrive,     label: 'Artifacts',      path: 'artifacts'      },
  { icon: Clock,         label: 'Timeline',       path: 'timeline'       },
  { icon: Bot,           label: 'Investigate',    path: 'investigate'    },
  { icon: Network,       label: 'Entity Map',     path: 'entities'       },
  { icon: UserSearch,    label: 'Profiles',       path: 'profiles'       },
  { icon: AlertTriangle, label: 'Anomalies',      path: 'anomalies'      },
  { icon: Crosshair,     label: 'Watchlist',      path: 'watchlist'      },
  { icon: Key,           label: 'Credentials',    path: 'credentials'    },
  { icon: Zap,           label: 'Contradictions', path: 'contradictions' },
  { icon: GitCompare,    label: 'Compare',        path: 'compare'        },
  { icon: Globe,         label: 'Geo Map',        path: 'geomap'         },
  { icon: FileText,      label: 'Reports',        path: 'reports'        },
  { icon: StickyNote,    label: 'Notes',          path: 'notes'          },
  { icon: ShieldCheck,   label: 'Audit Log',      path: 'audit'          },
  { icon: Settings2,     label: 'Access',         path: 'settings'       },
]

// Literal hex (not CSS vars) so the translucent tag background can be
// derived by appending an alpha suffix - "1a" ~ 10%, "40" ~ 25%.
const STATUS_COLOR = {
  Open:     '#3b82f6',
  Active:   '#4f46e5',
  Closed:   '#64748b',
  Archived: '#94a3b8',
}

const STATUS_LABEL = {
  Open:     'OPEN',
  Active:   'ACTIVE',
  Closed:   'CLOSED',
  Archived: 'ARCH',
}

// Shared section-heading style for the "NAVIGATION" / "ACTIVE CASES" labels
const sectionLabel = {
  fontSize: 9,
  fontWeight: 700,
  color: 'var(--ink-3)',
  letterSpacing: '0.12em',
  textTransform: 'uppercase',
}

function NavItem({ icon: Icon, label, active, onClick, collapsed }) {
  const [hovered, setHovered] = useState(false)
  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      title={collapsed ? label : undefined}
      style={{
        width: '100%',
        display: 'flex',
        alignItems: 'center',
        gap: collapsed ? 0 : 9,
        padding: collapsed ? '10px 0' : '7px 10px',
        justifyContent: collapsed ? 'center' : 'flex-start',
        borderRadius: 8,
        background: active
          ? 'linear-gradient(135deg, #4f46e5 0%, #6366f1 100%)'
          : hovered ? 'var(--bg-hover)' : 'transparent',
        border: 'none',
        cursor: 'pointer',
        color: active ? '#ffffff' : hovered ? 'var(--ink-0)' : 'var(--ink-1)',
        fontSize: 13,
        fontWeight: active ? 600 : 500,
        textAlign: 'left',
        transition: 'all 0.15s ease',
        overflow: 'hidden',
        whiteSpace: 'nowrap',
      }}
    >
      <Icon size={15} style={{ flexShrink: 0 }} />
      {!collapsed && (
        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {label}
        </span>
      )}
    </button>
  )
}

function CaseNavItem({ icon: Icon, label, active, onClick }) {
  const [hovered, setHovered] = useState(false)
  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      title={label}
      style={{
        width: '100%',
        display: 'flex',
        alignItems: 'center',
        gap: 7,
        padding: '5px 8px',
        justifyContent: 'flex-start',
        borderRadius: 6,
        background: active ? 'var(--brand-glow)' : hovered ? 'var(--bg-hover)' : 'transparent',
        border: 'none',
        cursor: 'pointer',
        color: active ? 'var(--brand-primary)' : hovered ? 'var(--ink-0)' : 'var(--ink-1)',
        fontSize: 11.5,
        fontWeight: active ? 600 : 400,
        textAlign: 'left',
        transition: 'all 0.12s ease',
        overflow: 'hidden',
        whiteSpace: 'nowrap',
      }}
    >
      <Icon size={12} style={{ flexShrink: 0 }} />
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{label}</span>
    </button>
  )
}

export default function Sidebar({ activeCaseId, setActiveCaseId, status, collapsed, onToggle }) {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, signOut, isAdmin } = useAuth()
  const [cases, setCases] = useState([])
  const [expanded, setExpanded] = useState(activeCaseId)
  const [search, setSearch] = useState('')
  const [searchFocus, setSearchFocus] = useState(false)

  useEffect(() => { loadCases() }, [])
  // Keep the expanded case in sync when the shell switches cases
  // (e.g. from the dashboard or the case list page).
  useEffect(() => { setExpanded(activeCaseId) }, [activeCaseId])

  const loadCases = async () => {
    try {
      const r = await getCases()
      setCases((r.data || []).filter(c => c.status !== 'Archived'))
    } catch {
      // Sidebar must never break the app if the case list fails to load.
      setCases([])
    }
  }

  const filtered = cases.filter(c =>
    (c.case_name || '').toLowerCase().includes(search.toLowerCase())
  )

  const isActive = (p) => location.pathname === p

  // Three states, not two. `status` is null until the first /api/status lands, and
  // that call takes ~2 s (it asks Ollama for its model list). Treating "not known
  // yet" as failure rendered a red "Ollama offline" dot for the whole time the
  // request was in flight - and a slow or hung /api/tags made that look permanent.
  // So an absent reading is neutral, never a failure colour.
  const dbOk = status?.database === 'connected'
  const dbKnown = !!status
  const ollamaOk = status?.ollama === 'running'
  const ollamaKnown = !!status

  return (
    <aside style={{
      width: '100%',
      background: 'var(--surface-1)',
      borderRight: '1px solid var(--line-DEFAULT)',
      display: 'flex',
      flexDirection: 'column',
      height: '100vh',
      overflow: 'hidden',
      position: 'relative',
    }}>

      {/* Accent stripe along the top of the rail */}
      <div style={{
        position: 'absolute',
        top: 0, left: 0, right: 0,
        height: '2px',
        background: 'linear-gradient(90deg, #4f46e5, #8b5cf6)',
        zIndex: 2,
      }} />

      {/* Brand header */}
      {collapsed ? (
        <button
          onClick={onToggle}
          title="Expand Sidebar"
          style={{
            width: '100%',
            padding: '16px 0',
            borderBottom: '1px solid var(--line-DEFAULT)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'transparent',
            border: 'none',
            borderTop: 'none', borderLeft: 'none', borderRight: 'none',
            cursor: 'pointer',
            flexShrink: 0,
          }}
        >
          <div style={{
            width: 30, height: 30, borderRadius: 8,
            background: 'linear-gradient(135deg, #3b82f6, #8b5cf6)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: '0 4px 12px rgba(139,92,246,0.3)',
          }}>
            <Fingerprint size={15} color="white" />
          </div>
        </button>
      ) : (
        <div style={{
          padding: '20px 16px 18px',
          borderBottom: '1px solid var(--line-DEFAULT)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 8,
          flexShrink: 0,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
            <div style={{
              width: 32, height: 32, borderRadius: 8, flexShrink: 0,
              background: 'linear-gradient(135deg, #3b82f6, #8b5cf6)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: '0 4px 12px rgba(139,92,246,0.3)',
            }}>
              <Fingerprint size={16} color="white" />
            </div>
            <div style={{ minWidth: 0 }}>
              <h1 style={{
                fontSize: 13, fontWeight: 700, color: 'var(--ink-0)',
                letterSpacing: '-0.01em', lineHeight: 1.2, margin: 0,
              }}>
                IDF AI Assistant
              </h1>
              <p style={{
                fontSize: 9, color: 'var(--ink-2)', margin: '1px 0 0 0',
                whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
              }}>
                Intelligent Digital Forensic AI
              </p>
            </div>
          </div>
          <button
            onClick={onToggle}
            title="Collapse Sidebar"
            style={{
              width: 24, height: 24, flexShrink: 0,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              borderRadius: 6,
              border: '1px solid var(--line-DEFAULT)',
              background: 'transparent',
              color: 'var(--ink-2)',
              cursor: 'pointer',
              transition: 'all 0.15s',
            }}
            onMouseEnter={e => { e.currentTarget.style.color = 'var(--ink-0)'; e.currentTarget.style.borderColor = 'var(--line-bright)' }}
            onMouseLeave={e => { e.currentTarget.style.color = 'var(--ink-2)'; e.currentTarget.style.borderColor = 'var(--line-DEFAULT)' }}
          >
            <PanelLeftClose size={13} />
          </button>
        </div>
      )}

      {/* ── Global navigation ─────────────────────────────────────────── */}
      {!collapsed && (
        <div style={{ padding: '12px 12px 2px', flexShrink: 0 }}>
          <span style={{ ...sectionLabel, padding: '0 4px' }}>Navigation</span>
        </div>
      )}
      <div style={{
        padding: collapsed ? '8px 6px 2px' : '2px 8px 4px',
        flexShrink: 0,
        display: 'flex', flexDirection: 'column', gap: 2,
      }}>
        {NAV_TOP.map(item => (
          <NavItem
            key={item.path}
            icon={item.icon}
            label={item.label}
            active={isActive(item.path)}
            onClick={() => navigate(item.path)}
            collapsed={collapsed}
          />
        ))}
        {isAdmin && (
          <NavItem
            icon={Users}
            label="Users & Access"
            active={location.pathname.startsWith('/admin/users')}
            onClick={() => navigate('/admin/users')}
            collapsed={collapsed}
          />
        )}
      </div>

      {/* Divider between global nav and the case tree */}
      <div style={{
        height: 1,
        margin: collapsed ? '4px 8px' : '6px 12px',
        background: 'var(--line-DEFAULT)',
        flexShrink: 0,
      }} />

      {/* ── Active cases: heading, add button, search ─────────────────── */}
      {!collapsed && (
        <div style={{ padding: '8px 12px 6px', flexShrink: 0 }}>
          <div style={{
            display: 'flex', alignItems: 'center',
            justifyContent: 'space-between', marginBottom: 7,
          }}>
            <span style={{ ...sectionLabel, padding: '0 2px' }}>Active Cases</span>
            <button
              onClick={() => navigate('/cases')}
              title="Manage cases"
              style={{
                width: 18, height: 18, flexShrink: 0,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                borderRadius: 4,
                border: '1px solid var(--line-DEFAULT)',
                background: 'transparent',
                color: 'var(--ink-2)',
                cursor: 'pointer',
                transition: 'all 0.12s',
              }}
              onMouseEnter={e => { e.currentTarget.style.color = 'var(--brand-primary)'; e.currentTarget.style.borderColor = 'var(--brand-primary)' }}
              onMouseLeave={e => { e.currentTarget.style.color = 'var(--ink-2)'; e.currentTarget.style.borderColor = 'var(--line-DEFAULT)' }}
            >
              <Plus size={11} />
            </button>
          </div>
          <div style={{ position: 'relative' }}>
            <Search
              size={11}
              style={{
                position: 'absolute', left: 8, top: '50%',
                transform: 'translateY(-50%)',
                color: 'var(--ink-3)', pointerEvents: 'none',
              }}
            />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              onFocus={() => setSearchFocus(true)}
              onBlur={() => setSearchFocus(false)}
              placeholder="Search cases..."
              style={{
                width: '100%',
                background: 'var(--surface-2)',
                border: `1px solid ${searchFocus ? 'var(--brand-primary)' : 'var(--line-DEFAULT)'}`,
                borderRadius: 6,
                padding: '5px 8px 5px 24px',
                fontSize: 11.5,
                color: 'var(--ink-0)',
                outline: 'none',
                transition: 'all 0.12s',
              }}
            />
          </div>
        </div>
      )}

      {/* ── Case list, each expandable to reveal its own tools ─────────── */}
      <div style={{
        flex: 1,
        overflowY: collapsed ? 'hidden' : 'auto',
        padding: collapsed ? '4px 6px' : '2px 8px 8px',
      }}>
        {!collapsed && filtered.map((c) => {
          const isOpen = expanded === c.id
          const isCurrent = activeCaseId === c.id
          const statusColor = STATUS_COLOR[c.status] || '#94a3b8'

          return (
            <div key={c.id} style={{ marginBottom: 1 }}>
              <button
                onClick={() => {
                  setActiveCaseId(c.id)
                  setExpanded(isOpen ? null : c.id)
                  navigate(`/cases/${c.id}`)
                }}
                style={{
                  width: '100%', display: 'flex', alignItems: 'center', gap: 7,
                  padding: '6px 8px', borderRadius: 8,
                  background: isCurrent ? 'var(--brand-glow)' : 'transparent',
                  border: 'none',
                  cursor: 'pointer',
                  color: isCurrent ? 'var(--brand-primary)' : 'var(--ink-1)',
                  fontSize: 12, fontWeight: isCurrent ? 600 : 500,
                  textAlign: 'left', transition: 'all 0.12s',
                  whiteSpace: 'nowrap', overflow: 'hidden',
                }}
                onMouseEnter={e => { if (!isCurrent) e.currentTarget.style.background = 'var(--bg-hover)' }}
                onMouseLeave={e => { if (!isCurrent) e.currentTarget.style.background = 'transparent' }}
              >
                <span style={{
                  fontSize: 8, fontWeight: 700, letterSpacing: '0.06em',
                  color: statusColor,
                  background: `${statusColor}1a`,
                  border: `1px solid ${statusColor}40`,
                  borderRadius: 3,
                  padding: '1px 4px',
                  flexShrink: 0,
                }}>
                  {STATUS_LABEL[c.status] || 'UNKN'}
                </span>
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {c.case_name}
                </span>
                <span style={{
                  flexShrink: 0, color: 'var(--ink-3)', display: 'flex',
                  transform: isOpen ? 'rotate(90deg)' : 'rotate(0deg)',
                  transition: 'transform 0.22s ease',
                }}>
                  <ChevronRight size={11} />
                </span>
              </button>

              {/* Nested per-case tools */}
              <div style={{
                overflow: 'hidden',
                maxHeight: isOpen ? '700px' : '0',
                opacity: isOpen ? 1 : 0,
                transition: 'max-height 0.28s cubic-bezier(0.4,0,0.2,1), opacity 0.22s ease',
                marginLeft: 12, paddingLeft: 8,
                borderLeft: '1px solid var(--line-DEFAULT)',
                marginTop: isOpen ? 2 : 0,
                marginBottom: isOpen ? 2 : 0,
              }}>
                <div style={{
                  display: 'flex', flexDirection: 'column', gap: 1,
                  paddingTop: 2, paddingBottom: 2,
                }}>
                  {CASE_NAV.map(nav => {
                    const np = `/cases/${c.id}/${nav.path}`
                    return (
                      <CaseNavItem
                        key={nav.path}
                        icon={nav.icon}
                        label={nav.label}
                        active={location.pathname === np}
                        onClick={() => navigate(np)}
                      />
                    )
                  })}
                </div>
              </div>
            </div>
          )
        })}

        {/* Collapsed: one dot per case, colour = status */}
        {collapsed && cases.slice(0, 8).map(c => {
          const isCurrent = activeCaseId === c.id
          const statusColor = STATUS_COLOR[c.status] || '#94a3b8'
          return (
            <button
              key={c.id}
              onClick={() => { setActiveCaseId(c.id); navigate(`/cases/${c.id}`) }}
              title={c.case_name}
              style={{
                width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                padding: '6px 0', borderRadius: 6,
                background: isCurrent ? 'var(--brand-glow)' : 'transparent',
                border: 'none', cursor: 'pointer', transition: 'all 0.12s',
              }}
            >
              <span style={{
                width: 7, height: 7, borderRadius: '50%',
                background: statusColor, opacity: isCurrent ? 1 : 0.5,
              }} />
            </button>
          )
        })}

        {!collapsed && filtered.length === 0 && (
          <div style={{ padding: '18px 8px', textAlign: 'center' }}>
            <p style={{ fontSize: 10, color: 'var(--ink-3)' }}>
              {search ? 'No cases found' : 'No active cases'}
            </p>
          </div>
        )}
      </div>

      {/* ── System health ─────────────────────────────────────────────── */}
      {!collapsed && (
        <div style={{
          padding: '8px 14px',
          borderTop: '1px solid var(--line-DEFAULT)',
          display: 'flex', alignItems: 'center', gap: 14,
          flexShrink: 0,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }} title={dbOk ? 'Database connected' : dbKnown ? 'Database error' : 'Database status not measured yet'}>
            <span style={{
              width: 5, height: 5, borderRadius: '50%', flexShrink: 0,
              background: dbOk ? '#10b981' : dbKnown ? '#ef4444' : '#94a3b8',
            }} />
            <Database size={11} style={{ color: 'var(--ink-2)', flexShrink: 0 }} />
            <span style={{ fontSize: 9, color: 'var(--ink-2)', letterSpacing: '0.04em' }}>DB</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }} title={ollamaOk ? 'Ollama ready to answer' : ollamaKnown ? 'Ollama not answering' : 'AI status not measured yet'}>
            <span style={{
              width: 5, height: 5, borderRadius: '50%', flexShrink: 0,
              background: ollamaOk ? '#10b981' : ollamaKnown ? '#ef4444' : '#94a3b8',
            }} />
            <Cpu size={11} style={{ color: 'var(--ink-2)', flexShrink: 0 }} />
            <span style={{ fontSize: 9, color: 'var(--ink-2)', letterSpacing: '0.04em' }}>AI</span>
          </div>
        </div>
      )}
      {collapsed && (
        <div style={{
          padding: '7px 0', flexShrink: 0,
          display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 5,
          borderTop: '1px solid var(--line-DEFAULT)',
        }}>
          <span title={`Database: ${dbOk ? 'Connected' : dbKnown ? 'Error' : 'Checking'}`} style={{
            width: 5, height: 5, borderRadius: '50%',
            background: dbOk ? '#10b981' : dbKnown ? '#ef4444' : '#94a3b8',
          }} />
          <span title={`AI: ${ollamaOk ? 'Ready' : ollamaKnown ? 'Not answering' : 'Checking'}`} style={{
            width: 5, height: 5, borderRadius: '50%',
            background: ollamaOk ? '#10b981' : ollamaKnown ? '#ef4444' : '#94a3b8',
          }} />
        </div>
      )}

      {/* ── User footer ───────────────────────────────────────────────── */}
      <div style={{
        padding: collapsed ? '12px 6px' : '10px 14px',
        borderTop: '1px solid var(--line-DEFAULT)',
        background: 'var(--surface-2)',
        flexShrink: 0,
      }}>
        <div style={{
          display: 'flex', alignItems: 'center',
          gap: collapsed ? 0 : 10,
          justifyContent: collapsed ? 'center' : 'flex-start',
        }}>
          <div style={{
            width: 30, height: 30, borderRadius: '50%', flexShrink: 0,
            background: 'linear-gradient(135deg, #3b82f6, #8b5cf6)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            border: '1.5px solid rgba(255,255,255,0.15)',
          }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: '#ffffff' }}>
              {user?.full_name?.[0] || user?.username?.[0] || 'A'}
            </span>
          </div>
          {!collapsed && (
            <>
              <div style={{ flex: 1, minWidth: 0 }}>
                <p style={{
                  fontSize: 12, fontWeight: 600, color: 'var(--ink-0)',
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  margin: 0, lineHeight: 1.3,
                }}>
                  {user?.full_name || user?.username || 'Analyst'}
                </p>
                <p style={{ fontSize: 9, color: 'var(--ink-2)', margin: 0 }}>
                  {user?.role || 'Digital Forensic Expert'}
                </p>
              </div>
              <button
                onClick={() => navigate('/settings')}
                title="Settings"
                style={{
                  padding: 5, borderRadius: 5, background: 'transparent', border: 'none',
                  color: 'var(--ink-2)', cursor: 'pointer', display: 'flex', transition: 'all 0.15s',
                }}
                onMouseEnter={e => { e.currentTarget.style.color = 'var(--brand-primary)'; e.currentTarget.style.background = 'var(--bg-hover)' }}
                onMouseLeave={e => { e.currentTarget.style.color = 'var(--ink-2)'; e.currentTarget.style.background = 'transparent' }}
              >
                <Settings size={13} />
              </button>
              <button
                onClick={signOut}
                title="Sign out"
                style={{
                  padding: 5, borderRadius: 5, background: 'transparent', border: 'none',
                  color: 'var(--ink-2)', cursor: 'pointer', display: 'flex', transition: 'all 0.15s',
                }}
                onMouseEnter={e => { e.currentTarget.style.color = '#ef4444'; e.currentTarget.style.background = 'rgba(239,68,68,0.12)' }}
                onMouseLeave={e => { e.currentTarget.style.color = 'var(--ink-2)'; e.currentTarget.style.background = 'transparent' }}
              >
                <LogOut size={13} />
              </button>
            </>
          )}
        </div>
      </div>
    </aside>
  )
}
