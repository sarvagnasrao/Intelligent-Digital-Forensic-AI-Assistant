import React, { useState, useEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'
import { FileText, Plus, Download,
         Trash2, RefreshCw,
         CheckCircle, AlertCircle,
         Clock, Shield, UserCheck } from 'lucide-react'
import { getReports, createReport, getReport, deleteReport, apiErrorMessage } from '../api/client'
import ConfirmDialog from '../components/ConfirmDialog'
import PageLayout from '../components/PageLayout'
import toast from 'react-hot-toast'
import { formatDistanceToNow } from 'date-fns'
import { fromUtc } from '../utils/time'
import { useAuth } from '../context/AuthContext'

const REPORT_TYPES = [
  {
    value: 'Case Summary',
    desc: 'Case info, evidence inventory, '
          + 'top entities, flagged items'
  },
  {
    value: 'Query Transcript',
    desc: 'All AI Q&A with citations '
          + 'and metadata'
  },
  {
    value: 'Entity Report',
    desc: 'Full entity list with '
          + 'frequencies'
  },
  {
    value: 'Timeline Report',
    desc: 'MACB timeline with '
          + 'anomaly highlights'
  },
  {
    value: 'Full Investigation',
    desc: 'Everything — all sections '
          + 'combined'
  }
]

const STATUS_ICON = {
  Generating: <RefreshCw size={14}
    className="text-blue-400 animate-spin"/>,
  Complete:   <CheckCircle size={14}
    className="text-success" />,
  Failed:     <AlertCircle size={14}
    className="text-danger" />
}

export default function ReportsPage() {
  const { caseId } = useParams()
  const { user } = useAuth()
  const [reports, setReports] = useState([])
  const [loading, setLoading] = 
    useState(true)
  const [generating, setGenerating] = useState(false)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({
    report_type: 'Case Summary',
    query_ids_included: []
  })
  const [confirmDelete, setConfirmDelete] = useState(null)
  const pollRef = useRef({})
  // Consecutive failed status checks per report, and the reason the last one
  // failed. Kept apart from `reports` because they describe a different
  // thing: a row stuck on "Generating" after the poll could not reach the
  // server is NOT a report that failed to generate.
  const pollFailures = useRef({})
  const [pollError, setPollError] = useState({})

  useEffect(() => {
    loadReports()
    return () => {
      Object.values(pollRef.current)
        .forEach(clearInterval)
    }
  }, [caseId])

  const loadReports = async () => {
    try {
      const res = await getReports(caseId)
      setReports(res.data)
      res.data.forEach(r => {
        if (r.status === 'Generating')
          startPolling(r.id)
      })
    } catch {
      toast.error('Failed to load reports')
    } finally {
      setLoading(false)
    }
  }

  const startPolling = (reportId) => {
    if (pollRef.current[reportId]) return
    pollRef.current[reportId] = setInterval(
      async () => {
        try {
          const res = await getReport(caseId, reportId)
          // A successful check clears the failure streak and any previously
          // displayed "status unknown", so a recovered connection is visible
          // rather than leaving a stale error next to a live row.
          delete pollFailures.current[reportId]
          setPollError(prev => {
            if (!(reportId in prev)) return prev
            const next = { ...prev }
            delete next[reportId]
            return next
          })
          setReports(prev => prev.map(r =>
            r.id === reportId ? {
              ...r,
              status: res.data.status,
              page_count: res.data.page_count,
              sha256_hash: res.data.sha256_hash,
              file_exists: res.data.file_exists
            } : r
          ))
          if (res.data.status !== 'Generating') {
            clearInterval(pollRef.current[reportId])
            delete pollRef.current[reportId]
            if (res.data.status === 'Complete') {
              toast.success('Report ready to download')
            } else {
              toast.error('Report failed')
            }
          }
        } catch (e) {
          /* Was a bare `catch {}`. A report whose status check could not be
             made stayed on "Generating" for ever, and because the interval
             was only cleared inside the try block it never stopped polling
             either. That is the B11/B18 shape: a failure that never becomes
             terminal, so the row looks like slow work rather than a broken
             connection.

             Two things are deliberately not done here. The row is not
             marked "Failed", because we know the *check* failed and not
             that the *report* did - claiming the report failed would be its
             own invention. And the interval is not cleared on the first
             error, because a single dropped request during generation is
             normal and three seconds of tolerance costs nothing. After
             three consecutive failures the poll gives up and says the state
             is unknown. */
          const n = (pollFailures.current[reportId] || 0) + 1
          pollFailures.current[reportId] = n
          if (n >= 3) {
            clearInterval(pollRef.current[reportId])
            delete pollRef.current[reportId]
            setPollError(prev => ({
              ...prev,
              [reportId]: apiErrorMessage(
                e,
                'Could not reach the server to check this report')
            }))
            toast.error(
              'Stopped checking a report - status unknown. Reload the page to try again.')
          }
        }
      }, 3000)
  }

  const handleGenerate = async () => {
    setGenerating(true)
    try {
      const res = await createReport(caseId, form)
      setReports(prev => [{
        id: res.data.id,
        report_type: form.report_type,
        // What the SERVER recorded, not what was typed into the form.
        // Prefer the response; fall back to the session user, which is
        // exactly the value the server will have stored. Reading
        // `form.generated_by` here would leave the row's byline blank
        // until the first poll replaced it.
        generated_by: res.data?.generated_by
          || user?.username || 'your account',
        generated_at: new Date().toISOString(),
        status: 'Generating',
        page_count: 0,
        file_exists: false
      }, ...prev])
      startPolling(res.data.id)
      setShowForm(false)
      toast.success('Report generation started')
    } catch (e) {
      toast.error(
        e.response?.data?.detail || 'Failed to start report')
    } finally {
      setGenerating(false)
    }
  }

  const handleDownload = async (reportId, reportType) => {
    try {
      // Must use the authenticated api client — window.open has no token
      const token = localStorage.getItem('cfi_token')
      const res = await fetch(
        `/api/cases/${caseId}/reports/${reportId}/download`,
        { headers: { Authorization: `Bearer ${token}` } }
      )
      if (!res.ok) throw new Error('Download failed')
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `IDF_AI_Report_${reportType.replace(/ /g,'_')}_${reportId.slice(0,8)}.pdf`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      toast.error('Download failed')
    }
  }

  const handleDelete = async (reportId) => {
    try {
      await deleteReport(caseId, reportId)
      setReports(prev =>
        prev.filter(r => r.id !== reportId))
      toast.success('Report deleted')
    } catch {
      toast.error('Delete failed')
    }
  }

  return (
    <PageLayout
      title="Reports"
      subtitle="Generate, view, and download comprehensive court-ready PDF reports that summarise your findings, evidence, entities, and timelines for this case."
      actions={
        <button
          onClick={() => setShowForm(true)}
          className="flex items-center gap-2 bg-accent hover:bg-accent-hover text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
        >
          <Plus size={16} />
          Generate Report
        </button>
      }
    >

      {/* Generation form */}
      {showForm && (
        <div className="bg-surface-2 border 
          border-line rounded-xl p-5 mb-6">
          <h2 className="font-semibold 
            text-ink-0 mb-4">
            New Report
          </h2>
          <div className="grid 
            grid-cols-2 gap-4 mb-4">
            <div>
              <label className="text-xs 
                text-ink-2 mb-1 block">
                Report Type
              </label>
              <select
                value={form.report_type}
                onChange={e => setForm({
                  ...form,
                  report_type: e.target.value
                })}
                className="w-full bg-surface-1
                  border border-line rounded-lg
                  px-3 py-2 text-sm
                  text-ink-0
                  focus:outline-none 
                  focus:border-accent"
              >
                {REPORT_TYPES.map(t => (
                  <option 
                    key={t.value}
                    value={t.value}>
                    {t.value}
                  </option>
                ))}
              </select>
              <p className="text-xs 
                text-ink-2 mt-1">
                {REPORT_TYPES.find(
                  t => t.value === 
                    form.report_type
                )?.desc}
              </p>
            </div>
            <div>
              {/*
                Was an editable "Prepared By" input. The server now takes
                the report's author from the authenticated session — a
                report is a document that may be called on for later, so
                who prepared it is a fact about the record rather than a
                caption — and a typed name would be silently discarded.
                Shown, not offered, like the case and note forms.
              */}
              <label className="text-xs
                text-ink-2 mb-1 block">
                Prepared By
              </label>
              <div className="w-full bg-surface-0
                  border border-line rounded-lg
                  px-3 py-2 text-sm text-ink-1
                  flex items-center gap-2">
                <UserCheck
                  size={14}
                  className="text-accent shrink-0" />
                <span className="truncate">
                  {user?.username || 'your account'}
                </span>
              </div>
            </div>
          </div>
          <div className="flex gap-3">
            <button
              onClick={handleGenerate}
              disabled={generating}
              className="flex items-center 
                gap-2 bg-accent 
                hover:bg-accent-hover
                disabled:opacity-50 
                text-white px-4 py-2 
                rounded-lg text-sm 
                font-medium 
                transition-colors"
            >
              {generating
                ? <RefreshCw size={14}
                    className="animate-spin"/>
                : <FileText size={14} />
              }
              Generate
            </button>
            <button
              onClick={() => 
                setShowForm(false)}
              className="bg-surface-4 
                text-ink-1 
                px-4 py-2 rounded-lg 
                text-sm transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Reports list */}
      {loading ? (
        <div className="flex items-center 
          justify-center h-48">
          <div className="w-6 h-6 border-2 
            border-accent rounded-full 
            border-t-transparent 
            animate-spin" />
        </div>
      ) : (
        <div className="space-y-3">
          {reports.map(report => (
            <div key={report.id}
              className="bg-surface-2 border 
                border-line rounded-xl p-4">
              <div className="flex items-start
                justify-between">
                <div className="flex 
                  items-start gap-3">
                  <div className="w-9 h-9 
                    rounded-lg bg-accent/20
                    flex items-center 
                    justify-center shrink-0">
                    <FileText size={18}
                      className="text-accent"/>
                  </div>
                  <div>
                    <div className="flex 
                      items-center gap-2">
                      <span className="font-medium
                        text-ink-0 
                        text-sm">
                        {report.report_type}
                      </span>
                      {STATUS_ICON[
                        report.status]}
                      <span className={`text-xs
                        ${report.status === 
                          'Complete'
                          ? 'text-success'
                          : report.status === 
                            'Failed'
                          ? 'text-danger'
                          : 'text-blue-400'}`}>
                        {report.status}
                      </span>
                      {/* A third state, distinct from both Complete and
                          Failed: the poll gave up, so the real status is
                          unknown. The spinner keeps turning above because
                          the server still believes it is Generating, and
                          saying so is more truthful than picking one of the
                          other two. */}
                      {pollError[report.id] && (
                        <span className="text-xs text-warning">
                          {' '}· status unknown —{' '}
                          {pollError[report.id]}
                        </span>
                      )}
                    </div>
                    <p className="text-xs 
                      text-ink-2 mt-0.5">
                      Prepared by 
                      {' '}{report.generated_by}
                      {' · '}
                      {formatDistanceToNow(
                        fromUtc(report.generated_at),
                        { addSuffix: true }
                      )}
                      {report.page_count > 0 
                        && ` · ${report.page_count} pages`}
                    </p>
                    {report.sha256_hash && (
                      <p className="text-xs 
                        font-mono 
                        text-ink-2 mt-0.5">
                        SHA-256: 
                        {' '}{report.sha256_hash
                          .slice(0,16)}...
                      </p>
                    )}
                  </div>
                </div>
                <div className="flex 
                  items-center gap-2">
                  {report.status === 
                    'Complete' && 
                   report.file_exists && (
                    <button
                    onClick={() =>
                        handleDownload(
                          report.id,
                          report.report_type)}
                      className="flex 
                        items-center gap-1.5
                        bg-success/20 
                        hover:bg-success/30
                        text-success px-3 
                        py-1.5 rounded-lg 
                        text-xs font-medium
                        transition-colors"
                    >
                      <Download size={13} />
                      Download PDF
                    </button>
                  )}
                  <button
                    onClick={() => setConfirmDelete(report.id)}
                    className="p-1.5 rounded text-ink-2 hover:text-danger transition-colors"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            </div>
          ))}
          {reports.length === 0 && 
           !showForm && (
            <div className="text-center 
              py-16 text-ink-2">
              <FileText size={40}
                className="mx-auto mb-3 
                           opacity-30" />
              <p className="text-sm">
                No reports yet. Generate 
                your first report.
              </p>
            </div>
          )}
        </div>
      )}

      <ConfirmDialog
        isOpen={!!confirmDelete}
        title="Delete Report"
        message="Permanently delete this report PDF? This cannot be undone."
        confirmLabel="Delete"
        onConfirm={() => handleDelete(confirmDelete)}
        onCancel={() => setConfirmDelete(null)}
      />
    </PageLayout>
  )
}
