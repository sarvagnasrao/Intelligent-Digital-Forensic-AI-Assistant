import React, { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { Shield, RefreshCw } from 'lucide-react'
import { getAuditLog } from '../api/client'
import PageLayout from '../components/PageLayout'
import toast from 'react-hot-toast'
import { formatDistanceToNow, format } from 'date-fns'
import { fromUtc } from '../utils/time'

const ACTION_COLORS = {
  CASE_CREATED:    'text-blue-400 bg-blue-500/10',
  CASE_UPDATED:    'text-blue-400 bg-blue-500/10',
  CASE_CLOSED:     'text-gray-400 bg-gray-500/10',
  FILE_UPLOADED:   'text-accent bg-accent/10',
  FILE_INGESTED:   'text-success bg-success/10',
  // Amber, not success: the job completed and the evidence is Indexed, so this
  // is the only signal that files were never copied.
  FILE_INGEST_PARTIAL: 'text-warning bg-warning/10',
  QUERY_MADE:      'text-purple-400 bg-purple-500/10',
  QUERY_FLAGGED:   'text-warning bg-warning/10',
  QUERY_DELETED:   'text-danger bg-danger/10',
  NOTE_ADDED:      'text-teal-400 bg-teal-500/10',
  ENTITY_FLAGGED:  'text-warning bg-warning/10',
  EVIDENCE_ARCHIVED: 'text-gray-400 bg-gray-500/10',
  // Auth events
  LOGIN_SUCCESS:   'text-success bg-success/10',
  LOGIN_FAILED:    'text-danger bg-danger/10',
  LOGIN_LOCKED:    'text-danger bg-danger/10',
  ACCOUNT_LOCKED:  'text-danger bg-danger/10',
  ACCOUNT_CREATED: 'text-blue-400 bg-blue-500/10',
}

export default function AuditPage() {
  const { caseId } = useParams()
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('ALL')

  useEffect(() => { loadAudit() }, [caseId])

  const loadAudit = async () => {
    setLoading(true)
    try {
      const res = await getAuditLog(caseId)
      setLogs(res.data)
    } catch {
      toast.error('Failed to load audit log')
    } finally {
      setLoading(false)
    }
  }

  const actionTypes = ['ALL', ...new Set(logs.map(l => l.action_type))]
  const filtered = filter === 'ALL' ? logs : logs.filter(l => l.action_type === filter)

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <div className="w-6 h-6 border-2 border-accent rounded-full border-t-transparent animate-spin" />
    </div>
  )

  return (
    <PageLayout
      title="Audit Log"
      subtitle="Complete record of every action taken in this case."
    >
      {/* Refresh + entry count */}
      <div className="flex items-center justify-between mb-4">
        <p className="text-ink-1 text-xs">{filtered.length} of {logs.length} entries</p>
        <button
          onClick={loadAudit}
          className="flex items-center gap-2 text-ink-2 hover:text-ink-0 text-sm transition-colors"
        >
          <RefreshCw size={14} />
          Refresh
        </button>
      </div>

      {/* Action type filter */}
      <div className="flex gap-2 flex-wrap mb-5">
        {actionTypes.map(type => (
          <button
            key={type}
            onClick={() => setFilter(type)}
            className={`text-xs px-3 py-1 rounded-full transition-colors
              ${filter === type
                ? 'bg-accent text-white'
                : 'bg-surface-2 border border-line text-ink-2 hover:text-ink-0'}`}
          >
            {type.replace(/_/g, ' ')}
          </button>
        ))}
      </div>

      {/* Timeline */}
      <div className="relative">
        <div className="absolute left-[19px] top-0 bottom-0 w-px bg-border" />
        <div className="space-y-3">
          {filtered.map((log, idx) => {
            const colorClass = ACTION_COLORS[log.action_type] || 'text-ink-2 bg-surface-4'
            const details = typeof log.details === 'object' ? log.details : {}
            return (
              <div key={log.id || idx} className="flex items-start gap-4 pl-1">
                {/* Timeline dot */}
                <div className={`w-9 h-9 rounded-full flex items-center justify-center shrink-0 z-10 ${colorClass}`}>
                  <Shield size={14} />
                </div>

                {/* Card */}
                <div className="flex-1 bg-surface-2 border border-line rounded-xl p-3 mb-1">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <span className={`text-xs font-mono font-semibold px-1.5 py-0.5 rounded ${colorClass}`}>
                        {log.action_type.replace(/_/g, ' ')}
                      </span>
                      <span className="text-xs text-ink-2 ml-2">by {log.performed_by}</span>
                      {log.machine_id && (
                        <span className="text-xs text-ink-2 ml-1">on {log.machine_id}</span>
                      )}
                    </div>
                    <div className="text-right shrink-0">
                      <p className="text-xs text-ink-2">
                        {formatDistanceToNow(fromUtc(log.performed_at), { addSuffix: true })}
                      </p>
                      <p className="text-xs text-ink-2 font-mono">
                        {format(fromUtc(log.performed_at), 'HH:mm:ss')}
                      </p>
                    </div>
                  </div>

                  {/* Details */}
                  {Object.keys(details).length > 0 && (
                    <div className="mt-2 bg-surface-1 rounded-lg p-2">
                      <div className="flex flex-wrap gap-x-4 gap-y-1">
                        {Object.entries(details).map(([k, v]) => (
                          <span key={k} className="text-xs text-ink-2">
                            <span className="text-ink-1">{k.replace(/_/g, ' ')}:</span>{' '}
                            <span className="font-mono text-ink-0">
                              {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                            </span>
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )
          })}
          {filtered.length === 0 && (
            <div className="text-center py-16 text-ink-2 pl-10">
              <Shield size={40} className="mx-auto mb-3 opacity-30" />
              <p className="text-sm">No audit entries for this filter</p>
            </div>
          )}
        </div>
      </div>
    </PageLayout>
  )
}
