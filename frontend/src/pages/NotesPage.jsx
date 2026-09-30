import React, { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { Plus, StickyNote, Trash2, Link, UserCheck } from 'lucide-react'
import { getNotes, createNote, deleteNote } from '../api/client'
import ConfirmDialog from '../components/ConfirmDialog'
import PageLayout from '../components/PageLayout'
import toast from 'react-hot-toast'
import { formatDistanceToNow } from 'date-fns'
import { fromUtc } from '../utils/time'
import { useAuth } from '../context/AuthContext'

export default function NotesPage() {
  const { caseId } = useParams()
  const { user } = useAuth()
  const [notes, setNotes] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({
    content: '',
    linked_to_type: '',
    linked_to_id: ''
  })
  const [loading, setLoading] = useState(true)
  const [confirmDelete, setConfirmDelete] = useState(null)

  useEffect(() => { loadNotes() }, [caseId])

  const loadNotes = async () => {
    try {
      const res = await getNotes(caseId)
      setNotes(res.data)
    } catch {
      toast.error('Failed to load notes')
    } finally {
      setLoading(false)
    }
  }

  const handleCreate = async () => {
    if (!form.content.trim()) {
      toast.error('Note content is required')
      return
    }
    try {
      const payload = {
        content: form.content,
        linked_to_type: form.linked_to_type || null,
        linked_to_id: form.linked_to_id || null
      }
      const res = await createNote(caseId, payload)
      setNotes(prev => [res.data, ...prev])
      setForm({ content: '', linked_to_type: '', linked_to_id: '' })
      setShowForm(false)
      toast.success('Note added')
    } catch {
      toast.error('Failed to create note')
    }
  }

  const handleDelete = async (noteId) => {
    try {
      await deleteNote(caseId, noteId)
      setNotes(prev => prev.filter(n => n.id !== noteId))
      toast.success('Note deleted')
    } catch {
      toast.error('Failed to delete note')
    }
  }

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <div className="w-6 h-6 border-2 border-accent rounded-full border-t-transparent animate-spin" />
    </div>
  )

  return (
    <PageLayout
      title="Notes"
      subtitle="Write and save your investigation notes here."
      actions={
        <button
          onClick={() => setShowForm(v => !v)}
          className="flex items-center gap-2 bg-accent hover:bg-accent-hover text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
        >
          <Plus size={16} />
          Add Note
        </button>
      }
    >
      {/* Create form */}
      {showForm && (
        <div className="bg-surface-2 border border-line rounded-xl p-5 mb-6">
          <h2 className="font-semibold text-ink-0 mb-4">New Note</h2>
          <div className="space-y-3">
            <div>
              {/*
                Was an editable "Author" input. The server now records the
                authenticated user as the note's author, so a typed name
                would be silently discarded - and a note's author is an
                assertion inside a case file, not a caption. Shown, not
                offered: the name that will be recorded is the account you
                are signed in as.
              */}
              <label className="text-xs text-ink-2 mb-1 block">Author</label>
              <div className="w-full bg-surface-0 border border-line rounded-lg px-3 py-2 text-sm text-ink-1 flex items-center gap-2">
                <UserCheck size={14} className="text-accent shrink-0" />
                <span className="truncate">{user?.username || 'your account'}</span>
              </div>
            </div>
            <div>
              <label className="text-xs text-ink-2 mb-1 block">Content *</label>
              <textarea
                value={form.content}
                onChange={e => setForm({ ...form, content: e.target.value })}
                rows={4}
                placeholder="Write your observation, finding, or note here…"
                className="w-full bg-surface-1 border border-line rounded-lg px-3 py-2 text-sm text-ink-0 placeholder:text-ink-2 focus:outline-none focus:border-accent resize-none"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-ink-2 mb-1 block">Link to type (optional)</label>
                <select
                  value={form.linked_to_type}
                  onChange={e => setForm({ ...form, linked_to_type: e.target.value })}
                  className="w-full bg-surface-1 border border-line rounded-lg px-3 py-2 text-sm text-ink-0 focus:outline-none focus:border-accent"
                >
                  <option value="">None</option>
                  {['Case', 'Evidence', 'Entity', 'Query'].map(t => (
                    <option key={t}>{t}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs text-ink-2 mb-1 block">Linked ID (optional)</label>
                <input
                  value={form.linked_to_id}
                  onChange={e => setForm({ ...form, linked_to_id: e.target.value })}
                  placeholder="UUID of linked item"
                  className="w-full bg-surface-1 border border-line rounded-lg px-3 py-2 text-sm text-ink-0 placeholder:text-ink-2 focus:outline-none focus:border-accent"
                />
              </div>
            </div>
          </div>
          <div className="flex gap-3 mt-4">
            <button
              onClick={handleCreate}
              className="bg-accent hover:bg-accent-hover text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
            >
              Save Note
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

      {/* Notes list */}
      <div className="space-y-3">
        {notes.map(n => (
          <div key={n.id} className="bg-surface-2 border border-line rounded-xl p-4 group">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-start gap-3 flex-1 min-w-0">
                <StickyNote size={16} className="text-accent shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-ink-0 whitespace-pre-wrap">{n.content}</p>
                  <div className="flex items-center gap-3 mt-2">
                    <span className="text-xs text-ink-2 font-medium">{n.author}</span>
                    <span className="text-xs text-ink-2">
                      {formatDistanceToNow(fromUtc(n.created_at), { addSuffix: true })}
                    </span>
                    {n.linked_to_type && (
                      <span className="flex items-center gap-1 text-xs text-accent-light">
                        <Link size={10} />
                        {n.linked_to_type}
                        {n.linked_to_id && ` · ${n.linked_to_id.slice(0, 8)}…`}
                      </span>
                    )}
                    {n.is_flagged && (
                      <span className="text-xs text-warning">⚑ Flagged</span>
                    )}
                  </div>
                </div>
              </div>
              <button
                onClick={() => setConfirmDelete(n.id)}
                className="opacity-0 group-hover:opacity-100 transition-opacity text-ink-2 hover:text-danger p-1 rounded shrink-0"
                title="Delete note"
              >
                <Trash2 size={14} />
              </button>
            </div>
          </div>
        ))}
        {notes.length === 0 && !showForm && (
          <div className="text-center py-16 text-ink-2">
            <StickyNote size={40} className="mx-auto mb-3 opacity-30" />
            <p className="text-sm">No notes yet — add your first observation</p>
          </div>
        )}
      </div>

      <ConfirmDialog
        isOpen={!!confirmDelete}
        title="Delete Note"
        message="Permanently delete this note? This cannot be undone."
        confirmLabel="Delete"
        onConfirm={() => handleDelete(confirmDelete)}
        onCancel={() => setConfirmDelete(null)}
      />
    </PageLayout>
  )
}
