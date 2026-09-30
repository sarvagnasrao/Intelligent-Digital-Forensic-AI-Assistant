import React, { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, Filter, X, ChevronLeft, ChevronRight, Activity, Clock, User, FolderOpen, Download, RefreshCw, ExternalLink, AlertTriangle } from 'lucide-react'
import { getGlobalActivity, apiErrorMessage } from '../api/client'
import { format, formatDistanceToNow } from 'date-fns'
import { fromUtc } from '../utils/time'
import toast from 'react-hot-toast'
import { ACTION_META } from '../constants/activityMeta'
import PageLayout from '../components/PageLayout'

const SEVERITY_CONFIG = {
  info: { color: '#60a5fa', bg: 'rgba(59,130,246,0.1)', border: 'rgba(59,130,246,0.25)' },
  warning: { color: '#fbbf24', bg: 'rgba(245,158,11,0.1)', border: 'rgba(245,158,11,0.25)' },
  error: { color: '#f87171', bg: 'rgba(239,68,68,0.1)', border: 'rgba(239,68,68,0.25)' },
  critical: { color: '#e879f9', bg: 'rgba(232,121,249,0.1)', border: 'rgba(232,121,249,0.25)' }
}
function ActionBadge({ type }) {
  const meta = ACTION_META[type] || { color: '#64748b', label: type?.replace(/_/g, ' ').toLowerCase() || 'unknown' }
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '2px 8px', borderRadius: 6, fontSize: 11, fontWeight: 500, background: `${meta.color}15`, border: `1px solid ${meta.color}30`, color: meta.color, whiteSpace: 'nowrap' }}>
      <span style={{ width: 5, height: 5, borderRadius: '50%', background: meta.color, boxShadow: `0 0 6px ${meta.color}`, flexShrink: 0, display: 'inline-block' }} />
      {meta.label}
    </span>
  )
}

function FilterChip({ label, onRemove }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '3px 10px 3px 8px', borderRadius: 99, fontSize: 11, background: 'rgba(99,102,241,0.15)', border: '1px solid rgba(99,102,241,0.3)', color: '#a5b4fc', cursor: 'default' }}>
      {label}
      <button onClick={onRemove} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, color: '#818cf8', lineHeight: 1, display: 'flex' }}><X size={10} /></button>
    </span>
  )
}

export default function ActivityPage() {
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [filters, setFilters] = useState({ q: '', action_type: '', performed_by: '', case_id: '', date_from: '', date_to: '', severity: '' })
  const [inputQ, setInputQ] = useState('')
  const [showFilters, setShowFilters] = useState(false)
  // Kept apart from `data` so a failed request can never be rendered as an
  // empty audit log. On an audit page that distinction is the whole point:
  // "no events recorded" and "we could not read the log" are very different
  // facts about an investigation.
  const [loadError, setLoadError] = useState(null)

  useEffect(() => { load() }, [page, filters])

  const load = async () => {
    setLoading(true)
    try {
      const params = { page, page_size: 50, ...Object.fromEntries(Object.entries(filters).filter(([,v]) => v)) }
      const res = await getGlobalActivity(params)
      setData(res.data)
      setLoadError(null)
    } catch (e) {
      /* `data` is left as-is, which on the first load means it stays `null`.
         That is the whole bug: with `data === null` the empty-state test
         `data?.items.length === 0` evaluates to `undefined === 0` - false -
         so the empty state is skipped and the table falls through to
         `data?.items.map(...)`, which maps over `undefined` and renders
         nothing at all. The result was a header row, an empty body, and a
         subtitle still reading "Loading..." that could never resolve: the
         page looked like a request that never came back, rather than one
         that came back broken. */
      setLoadError(apiErrorMessage(e, 'Could not load activity'))
      toast.error('Failed to load activity')
    } finally {
      setLoading(false)
    }
  }

  const applySearch = () => { setFilters(f => ({ ...f, q: inputQ })); setPage(1) }
  const clearFilter = (key) => { setFilters(f => ({ ...f, [key]: '' })); if (key === 'q') setInputQ(''); setPage(1) }
  const setFilter = (key, val) => { setFilters(f => ({ ...f, [key]: val })); setPage(1) }
  const activeFilters = Object.entries(filters).filter(([,v]) => v)

  const exportCSV = () => {
    if (!data?.items) return
    const rows = [['Action', 'Performed By', 'Case ID', 'Timestamp', 'Details'], ...data.items.map(item => [item.action_type, item.performed_by, item.case_id || '', item.performed_at, JSON.stringify(item.details)])]
    const csv = rows.map(r => r.map(c => `"${String(c).replace(/"/g,'""')}"`).join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `idfai-activity-${new Date().toISOString().slice(0,10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const opts = data?.filter_options

  return (
    <PageLayout
      title="Activity Log"
      subtitle={loadError
        ? 'Activity log unavailable'
        : data ? `${data.total.toLocaleString()} total events` : 'Loading...'}
      actions={
        <>
          <button onClick={load} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px', borderRadius: 8, background: 'var(--color-white-04)', border: '1px solid rgba(255,255,255,0.08)', color: 'var(--color-white-5)', fontSize: 12, cursor: 'pointer' }}><RefreshCw size={13} />Refresh</button>
          <button onClick={exportCSV} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px', borderRadius: 8, background: 'rgba(99,102,241,0.15)', border: '1px solid rgba(99,102,241,0.3)', color: '#a5b4fc', fontSize: 12, cursor: 'pointer' }}><Download size={13} />Export CSV</button>
        </>
      }
    >
      {/* Search + Filter bar */}
      <div style={{ background: 'var(--color-white-03)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 12, padding: 16, marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 8 }}>
          <div style={{ flex: 1, position: 'relative' }}>
            <Search size={13} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--color-white-2)', pointerEvents: 'none' }} />
            <input value={inputQ} onChange={e => setInputQ(e.target.value)} onKeyDown={e => e.key === 'Enter' && applySearch()} placeholder="Search by action, user, or details..." style={{ width: '100%', background: 'var(--color-white-04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8, padding: '9px 12px 9px 36px', fontSize: 13, color: 'var(--text-primary)', outline: 'none' }} onFocus={e => { e.target.style.borderColor = 'rgba(99,102,241,0.5)' }} onBlur={e => { e.target.style.borderColor = 'var(--color-white-08)' }} />
          </div>
          <button onClick={applySearch} style={{ padding: '9px 20px', borderRadius: 8, background: '#4f46e5', border: 'none', color: 'var(--color-white-full)', fontSize: 13, fontWeight: 500, cursor: 'pointer' }}>Search</button>
          <button onClick={() => setShowFilters(!showFilters)} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '9px 16px', borderRadius: 8, background: showFilters ? 'rgba(99,102,241,0.2)' : 'var(--color-white-04)', border: showFilters ? '1px solid rgba(99,102,241,0.4)' : '1px solid rgba(255,255,255,0.08)', color: showFilters ? '#a5b4fc' : 'var(--color-white-4)', fontSize: 12, cursor: 'pointer' }}>
            <Filter size={13} />Filters
            {activeFilters.length > 0 && <span style={{ background: '#6366f1', color: 'var(--color-white-full)', borderRadius: 99, fontSize: 10, padding: '0 5px', minWidth: 16, textAlign: 'center', lineHeight: '16px' }}>{activeFilters.length}</span>}
          </button>
        </div>

        {showFilters && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginTop: 12, paddingTop: 12, borderTop: '1px solid rgba(255,255,255,0.06)' }}>
            <div><label style={{ fontSize: 10, color: 'var(--color-white-3)', textTransform: 'uppercase', letterSpacing: '0.08em', display: 'block', marginBottom: 6 }}>Action Type</label><select value={filters.action_type} onChange={e => setFilter('action_type', e.target.value)} style={{ width: '100%', background: 'var(--color-white-04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8, padding: '8px 10px', fontSize: 12, color: 'var(--text-primary)', outline: 'none' }}><option value="">All actions</option>{opts?.action_types.sort().map(t => (<option key={t} value={t}>{t.replace(/_/g, ' ').toLowerCase()}</option>))}</select></div>
            <div><label style={{ fontSize: 10, color: 'var(--color-white-3)', textTransform: 'uppercase', letterSpacing: '0.08em', display: 'block', marginBottom: 6 }}>User</label><select value={filters.performed_by} onChange={e => setFilter('performed_by', e.target.value)} style={{ width: '100%', background: 'var(--color-white-04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8, padding: '8px 10px', fontSize: 12, color: 'var(--text-primary)', outline: 'none' }}><option value="">All users</option>{opts?.users.sort().map(u => (<option key={u} value={u}>{u}</option>))}</select></div>
            <div><label style={{ fontSize: 10, color: 'var(--color-white-3)', textTransform: 'uppercase', letterSpacing: '0.08em', display: 'block', marginBottom: 6 }}>From Date</label><input type="date" value={filters.date_from} onChange={e => setFilter('date_from', e.target.value)} style={{ width: '100%', background: 'var(--color-white-04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8, padding: '8px 10px', fontSize: 12, color: 'var(--text-primary)', outline: 'none', colorScheme: 'dark' }} /></div>
            <div><label style={{ fontSize: 10, color: 'var(--color-white-3)', textTransform: 'uppercase', letterSpacing: '0.08em', display: 'block', marginBottom: 6 }}>To Date</label><input type="date" value={filters.date_to} onChange={e => setFilter('date_to', e.target.value)} style={{ width: '100%', background: 'var(--color-white-04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8, padding: '8px 10px', fontSize: 12, color: 'var(--text-primary)', outline: 'none', colorScheme: 'dark' }} /></div>
            <div><label style={{ fontSize: 10, color: 'var(--color-white-3)', textTransform: 'uppercase', letterSpacing: '0.08em', display: 'block', marginBottom: 6 }}>Severity</label><select value={filters.severity || ''} onChange={e => setFilter('severity', e.target.value)} style={{ width: '100%', background: 'var(--color-white-04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8, padding: '8px 10px', fontSize: 12, color: 'var(--text-primary)', outline: 'none' }}><option value="">All severities</option><option value="info">Info</option><option value="warning">Warning</option><option value="error">Error</option><option value="critical">Critical</option></select></div>
          </div>
        )}

        {activeFilters.length > 0 && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 10 }}>
            {activeFilters.map(([key, val]) => <FilterChip key={key} label={`${key.replace(/_/g,' ')}: ${val}`} onRemove={() => clearFilter(key)} />)}
            <button onClick={() => { setFilters({ q:'', action_type:'', performed_by:'', case_id:'', date_from:'', date_to:'', severity:'' }); setInputQ(''); setPage(1) }} style={{ fontSize: 11, color: 'var(--color-white-3)', background: 'none', border: 'none', cursor: 'pointer', padding: '3px 6px' }}>Clear all</button>
          </div>
        )}
      </div>

      {/* Results */}
      <div style={{ background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 12, overflow: 'hidden' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr 1fr 0.7fr 2.5fr 1fr', gap: 16, alignItems: 'center', padding: '10px 20px', borderBottom: '1px solid rgba(255,255,255,0.06)', background: 'var(--color-white-03)' }}>
          {['Action', 'User', 'Case', 'Severity', 'Details', 'Time'].map(h => <span key={h} style={{ fontSize: 10, fontWeight: 600, color: 'var(--color-white-2)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>{h}</span>)}
        </div>

        {loading ? (
          <div>{Array(8).fill(0).map((_,i) => <div key={i} style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr 1fr 0.7fr 2.5fr 1fr', gap: 16, alignItems: 'center', padding: '14px 20px', borderBottom: '1px solid rgba(255,255,255,0.04)' }}><div className="skeleton" style={{ height: 20, borderRadius: 6, animationDelay: `${i*80}ms` }} /><div className="skeleton" style={{ height: 20, borderRadius: 6, animationDelay: `${i*80+40}ms` }} /><div className="skeleton" style={{ height: 20, borderRadius: 6, width: '70%', animationDelay: `${i*80+80}ms` }} /><div className="skeleton" style={{ height: 20, borderRadius: 6, width: '60%', animationDelay: `${i*80+120}ms` }} /><div className="skeleton" style={{ height: 20, borderRadius: 6, width: '80%', animationDelay: `${i*80+160}ms` }} /><div className="skeleton" style={{ height: 20, borderRadius: 6, width: '60%', animationDelay: `${i*80+200}ms` }} /></div>)}</div>
        ) : loadError ? (
          /* Rendered before the empty state on purpose. An audit log that
             could not be read must never present itself as an audit log with
             nothing in it. */
          <div style={{ padding: '60px 20px', textAlign: 'center', color: 'var(--color-white-2)' }}>
            <AlertTriangle size={36} style={{ margin: '0 auto 12px', opacity: 0.4, color: 'var(--color-amber-400, #f59e0b)' }} />
            <p style={{ fontSize: 14, color: 'var(--text-primary)' }}>Could not load the activity log</p>
            <p style={{ fontSize: 12, marginTop: 4 }}>{loadError}</p>
            <button onClick={load} style={{ marginTop: 14, fontSize: 12, color: '#818cf8', background: 'none', border: '1px solid rgba(129,140,248,0.4)', borderRadius: 6, padding: '6px 14px', cursor: 'pointer' }}>Try again</button>
          </div>
        ) : !data || data.items?.length === 0 ? (
          <div style={{ padding: '60px 20px', textAlign: 'center', color: 'var(--color-white-2)' }}><Activity size={36} style={{ margin: '0 auto 12px', opacity: 0.3 }} /><p style={{ fontSize: 14 }}>No activity found</p><p style={{ fontSize: 12, marginTop: 4 }}>Try adjusting your filters</p></div>
        ) : (
          data?.items.map((item, i) => {
            const detailStr = Object.entries(item.details || {}).slice(0, 2).map(([k, v]) => `${k}: ${String(v).slice(0,20)}`).join(' · ')
            return (
              <div key={item.id} className="animate-fade-up" style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr 1fr 0.7fr 2.5fr 1fr', gap: 16, alignItems: 'center', padding: '13px 20px', borderBottom: '1px solid rgba(255,255,255,0.04)', animationDelay: `${i * 20}ms`, transition: 'background 0.15s', cursor: item.case_id ? 'pointer' : 'default' }} onMouseEnter={e => { e.currentTarget.style.background = 'var(--color-white-03)' }} onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}>
                <div><ActionBadge type={item.action_type} /></div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}><div style={{ width: 22, height: 22, borderRadius: 6, background: 'rgba(99,102,241,0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 700, color: '#818cf8', flexShrink: 0 }}>{item.performed_by?.[0]?.toUpperCase() || '?'}</div><span style={{ fontSize: 12, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.performed_by}</span></div>
                <div>{item.case_id ? <button onClick={() => navigate(`/cases/${item.case_id}`)} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#818cf8', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}><FolderOpen size={11} />{item.case_id.slice(0, 8)}</button> : <span style={{ fontSize: 11, color: 'var(--color-white-2)' }}>—</span>}</div>
                <div>
                  {(() => {
                    const sev = item.severity || 'info'
                    const cfg = SEVERITY_CONFIG[sev] || SEVERITY_CONFIG.info
                    return (
                      <span style={{ display: 'inline-flex', alignItems: 'center', padding: '2px 8px', borderRadius: 5, fontSize: 10, fontWeight: 600, background: cfg.bg, border: `1px solid ${cfg.border}`, color: cfg.color, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                        {sev}
                      </span>
                    )
                  })()}
                </div>
                <div><span style={{ fontSize: 11, color: 'var(--color-white-3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block' }} title={JSON.stringify(item.details)}>{detailStr || '—'}</span></div>
                <div><span style={{ fontSize: 11, color: 'var(--color-white-3)' }} title={format(fromUtc(item.performed_at), 'PPpp')}>{formatDistanceToNow(fromUtc(item.performed_at), { addSuffix: true })}</span></div>
              </div>
            )
          })
        )}
      </div>

      {/* Pagination */}
      {data && data.total_pages > 1 && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 16, padding: '0 4px' }}>
          <p style={{ fontSize: 12, color: 'var(--color-white-2)' }}>Showing {((page-1) * 50) + 1}–{Math.min(page * 50, data.total)} of {data.total.toLocaleString()} events</p>
          <div style={{ display: 'flex', gap: 4 }}>
            <button onClick={() => setPage(p => Math.max(1, p-1))} disabled={!data.has_prev} style={{ padding: '6px 12px', borderRadius: 8, background: 'var(--color-white-04)', border: '1px solid rgba(255,255,255,0.08)', color: data.has_prev ? 'var(--text-primary)' : 'var(--color-white-2)', fontSize: 12, cursor: data.has_prev ? 'pointer' : 'default', display: 'flex', alignItems: 'center', gap: 4 }}><ChevronLeft size={13} />Prev</button>
            {Array.from({ length: Math.min(5, data.total_pages) }, (_, i) => {
              let n; if (data.total_pages <= 5) { n = i + 1 } else if (page <= 3) { n = i + 1 } else if (page >= data.total_pages - 2) { n = data.total_pages - 4 + i } else { n = page - 2 + i }
              return <button key={n} onClick={() => setPage(n)} style={{ width: 32, height: 32, borderRadius: 8, background: n === page ? 'rgba(99,102,241,0.3)' : 'var(--color-white-04)', border: n === page ? '1px solid rgba(99,102,241,0.5)' : '1px solid rgba(255,255,255,0.08)', color: n === page ? '#a5b4fc' : 'var(--text-primary)', fontSize: 12, cursor: 'pointer', fontWeight: n === page ? 600 : 400 }}>{n}</button>
            })}
            <button onClick={() => setPage(p => Math.min(data.total_pages, p+1))} disabled={!data.has_next} style={{ padding: '6px 12px', borderRadius: 8, background: 'var(--color-white-04)', border: '1px solid rgba(255,255,255,0.08)', color: data.has_next ? 'var(--text-primary)' : 'var(--color-white-2)', fontSize: 12, cursor: data.has_next ? 'pointer' : 'default', display: 'flex', alignItems: 'center', gap: 4 }}>Next<ChevronRight size={13} /></button>
          </div>
        </div>
      )}
    </PageLayout>
  )
}
