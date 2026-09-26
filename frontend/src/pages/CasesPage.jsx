import React, { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, FolderOpen, ChevronRight, Archive, Upload } from 'lucide-react'
import { getCases, createCase, archiveCase, importCase } from '../api/client'
import Badge from '../components/Badge'
import ConfirmDialog from '../components/ConfirmDialog'
import PageLayout from '../components/PageLayout'
import toast from 'react-hot-toast'
import { formatDistanceToNow } from 'date-fns'
import { fromUtc } from '../utils/time'

export default function CasesPage({ setActiveCaseId }) {
  const navigate = useNavigate()
  const [cases, setCases] = useState([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({
    case_name: '',
    case_number: '',
    priority: 'Medium',
    description: '',
    created_by: 'Investigator',
    tags: ''
  })
  const [confirmArchive, setConfirmArchive] = useState(null)
  const importRef = useRef()

  useEffect(() => { loadCases() }, [])

  const loadCases = async () => {
    try {
      const res = await getCases()
      setCases(res.data)
    } catch {
      toast.error('Failed to load cases')
    } finally {
      setLoading(false)
    }
  }

  const handleCreate = async () => {
    if (!form.case_name.trim()) {
      toast.error('Case name is required')
      return
    }
    try {
      const payload = {
        ...form,
        tags: form.tags
          ? form.tags.split(',').map(t => t.trim()).filter(Boolean)
          : []
      }
      const res = await createCase(payload)
      toast.success('Case created')
      setShowForm(false)
      setForm({ case_name: '', case_number: '', priority: 'Medium', description: '', created_by: 'Investigator', tags: '' })
      setActiveCaseId(res.data.id)
      navigate(`/cases/${res.data.id}`)
    } catch {
      toast.error('Failed to create case')
    }
  }

  const openCase = (c) => {
    setActiveCaseId(c.id)
    navigate(`/cases/${c.id}`)
  }

  const handleArchive = async (c) => {
    try {
      await archiveCase(c.id)
      setCases(prev => prev.filter(x => x.id !== c.id))
      toast.success(`"${c.case_name}" archived`)
    } catch {
      toast.error('Archive failed')
    }
  }

  const handleImport = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    // reset so the same file can be re-imported if needed
    e.target.value = ''
    const fd = new FormData()
    fd.append('file', file)
    try {
      const res = await importCase(fd)
      toast.success(`Imported: ${res.data.case_name}`)
      navigate(`/cases/${res.data.new_case_id}`)
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Import failed')
    }
  }

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <div className="w-6 h-6 border-2 border-accent rounded-full border-t-transparent animate-spin" />
    </div>
  )

  return (
    <PageLayout
      title="Cases"
      subtitle={`${cases.length} investigation case(s)`}
      actions={
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {/* Hidden file input for ZIP import */}
          <input
            ref={importRef}
            type="file"
            accept=".zip"
            style={{ display: 'none' }}
            onChange={handleImport}
          />
          <button
            onClick={() => importRef.current?.click()}
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '8px 14px', borderRadius: 8,
              background: 'var(--color-white-04)',
              border: '1px solid rgba(255,255,255,0.09)',
              color: 'var(--color-white-4)',
              fontSize: 12, cursor: 'pointer',
              transition: 'all 0.15s',
            }}
            onMouseEnter={e => {
              e.currentTarget.style.color = 'var(--text-primary)'
              e.currentTarget.style.borderColor = 'var(--color-white-2)'
            }}
            onMouseLeave={e => {
              e.currentTarget.style.color = 'var(--color-white-4)'
              e.currentTarget.style.borderColor = 'var(--color-white-09)'
            }}
          >
            <Upload size={13} />
            Import Case
          </button>
          <button
            onClick={() => setShowForm(true)}
            className="flex items-center gap-2 bg-accent hover:bg-accent-hover text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
          >
            <Plus size={16} />
            New Case
          </button>
        </div>
      }
    >
      {/* New Case Form */}
      {showForm && (
        <div className="bg-surface-2 border border-line rounded-xl p-5 mb-6">
          <h2 className="font-semibold text-ink-0 mb-4">Create New Case</h2>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs text-ink-2 mb-1 block">Case Name *</label>
              <input
                value={form.case_name}
                onChange={e => setForm({ ...form, case_name: e.target.value })}
                placeholder="Operation Phantom"
                className="w-full bg-surface-1 border border-line rounded-lg px-3 py-2 text-sm text-ink-0 placeholder:text-ink-2 focus:outline-none focus:border-accent"
              />
            </div>
            <div>
              <label className="text-xs text-ink-2 mb-1 block">Case Number</label>
              <input
                value={form.case_number}
                onChange={e => setForm({ ...form, case_number: e.target.value })}
                placeholder="IDF-2025-001"
                className="w-full bg-surface-1 border border-line rounded-lg px-3 py-2 text-sm text-ink-0 placeholder:text-ink-2 focus:outline-none focus:border-accent"
              />
            </div>
            <div>
              <label className="text-xs text-ink-2 mb-1 block">Priority</label>
              <select
                value={form.priority}
                onChange={e => setForm({ ...form, priority: e.target.value })}
                className="w-full bg-surface-1 border border-line rounded-lg px-3 py-2 text-sm text-ink-0 focus:outline-none focus:border-accent"
              >
                {['Low', 'Medium', 'High', 'Critical'].map(p => (
                  <option key={p}>{p}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-ink-2 mb-1 block">Investigator Name</label>
              <input
                value={form.created_by}
                onChange={e => setForm({ ...form, created_by: e.target.value })}
                placeholder="Det. Markov"
                className="w-full bg-surface-1 border border-line rounded-lg px-3 py-2 text-sm text-ink-0 placeholder:text-ink-2 focus:outline-none focus:border-accent"
              />
            </div>
            <div className="col-span-2">
              <label className="text-xs text-ink-2 mb-1 block">Description</label>
              <textarea
                value={form.description}
                onChange={e => setForm({ ...form, description: e.target.value })}
                rows={2}
                placeholder="Brief case summary..."
                className="w-full bg-surface-1 border border-line rounded-lg px-3 py-2 text-sm text-ink-0 placeholder:text-ink-2 focus:outline-none focus:border-accent resize-none"
              />
            </div>
            <div className="col-span-2">
              <label className="text-xs text-ink-2 mb-1 block">Tags (comma separated)</label>
              <input
                value={form.tags}
                onChange={e => setForm({ ...form, tags: e.target.value })}
                placeholder="cybercrime, financial"
                className="w-full bg-surface-1 border border-line rounded-lg px-3 py-2 text-sm text-ink-0 placeholder:text-ink-2 focus:outline-none focus:border-accent"
              />
            </div>
          </div>
          <div className="flex gap-3 mt-4">
            <button
              onClick={handleCreate}
              className="bg-accent hover:bg-accent-hover text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
            >
              Create Case
            </button>
            <button
              onClick={() => setShowForm(false)}
              className="bg-surface-4 text-ink-1 px-4 py-2 rounded-lg text-sm transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Case grid */}
      <div className="grid grid-cols-1 gap-3">
        {cases.map(c => (
          <button
            key={c.id}
            onClick={() => openCase(c)}
            className="bg-surface-2 border border-line rounded-xl p-4 text-left hover:border-accent/50 hover:bg-surface-4 transition-all group relative"
          >
            <div className="flex items-start justify-between">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <FolderOpen size={16} className="text-accent shrink-0" />
                  <span className="font-semibold text-ink-0 truncate">{c.case_name}</span>
                  {c.case_number && (
                    <span className="text-xs text-ink-2 font-mono">#{c.case_number}</span>
                  )}
                </div>
                {c.description && (
                  <p className="text-sm text-ink-1 truncate ml-6">{c.description}</p>
                )}
                <div className="flex items-center gap-2 mt-2 ml-6">
                  <Badge label={c.status} />
                  <Badge label={c.priority} />
                  <span className="text-xs text-ink-2">
                    {c.evidence_count} evidence · {c.query_count} queries
                  </span>
                  <span className="text-xs text-ink-2 ml-auto">
                    {formatDistanceToNow(fromUtc(c.created_at), { addSuffix: true })}
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-1 ml-2 shrink-0">
                <button
                  id={`archive-case-${c.id}`}
                  onClick={e => { e.stopPropagation(); setConfirmArchive(c) }}
                  className="p-1 rounded text-ink-2 hover:text-danger opacity-0 group-hover:opacity-100 transition-all"
                  title="Archive case"
                >
                  <Archive size={13} />
                </button>
                <ChevronRight size={16} className="text-ink-2 group-hover:text-accent transition-colors mt-1" />
              </div>
            </div>
          </button>
        ))}
        {cases.length === 0 && !showForm && (
          <div className="text-center py-16 text-ink-2">
            <FolderOpen size={40} className="mx-auto mb-3 opacity-30" />
            <p className="text-sm">No cases yet. Create your first investigation case.</p>
          </div>
        )}
      </div>

      <ConfirmDialog
        isOpen={!!confirmArchive}
        title="Archive Case"
        message={`Archive "${confirmArchive?.case_name}"? It will be removed from the active list. Evidence files are preserved on disk.`}
        confirmLabel="Archive"
        onConfirm={() => handleArchive(confirmArchive)}
        onCancel={() => setConfirmArchive(null)}
      />
    </PageLayout>
  )
}
