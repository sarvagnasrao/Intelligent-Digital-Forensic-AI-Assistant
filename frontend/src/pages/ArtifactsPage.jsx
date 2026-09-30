import React, { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import {
  FileText, File, Database, Globe, Image,
  Flag, Search, ChevronRight, X,
  Hash, HardDrive, Eye
} from 'lucide-react'
import { getAllArtifacts, getArtifact, flagArtifact } from '../api/client'
import FileViewer from '../components/FileViewer'
import Badge from '../components/Badge'
import Pagination from '../components/Pagination'
import PageLayout from '../components/PageLayout'
import toast from 'react-hot-toast'

// Icon by file extension
const EXT_ICON = {
  '.pdf':    FileText,
  '.txt':    FileText,
  '.log':    FileText,
  '.csv':    FileText,
  '.db':     Database,
  '.sqlite': Database,
  '.sqlite3':Database,
  '.html':   Globe,
  '.htm':    Globe,
  '.jpg':    Image,
  '.jpeg':   Image,
  '.png':    Image,
  '.tiff':   Image,
  '.tif':    Image,
}

// Colour by extraction type
const TYPE_COLOR = {
  text:            'text-blue-400',
  pdf:             'text-red-400',
  sqlite:          'text-yellow-400',
  html:            'text-green-400',
  exif:            'text-purple-400',
  browser_history: 'text-green-400',
  registry:        'text-orange-400',
  ocr:             'text-pink-400',
  audio:           'text-indigo-400',
  video:           'text-violet-400',
  email:           'text-sky-400',
  docx:            'text-blue-300',
  xlsx:            'text-emerald-400',
  pptx:            'text-orange-300',
  unsupported:     'text-ink-2',
  error:           'text-danger',
}

const PAGE_SIZE = 50

function formatBytes(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1048576).toFixed(1)} MB`
}

export default function ArtifactsPage() {
  const { caseId } = useParams()
  const [artifacts, setArtifacts] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [filterType, setFilterType] = useState('')
  const [filterExt, setFilterExt] = useState('')
  const [showFlagged, setShowFlagged] = useState(false)
  const [selected, setSelected] = useState(null)
  const [detail, setDetail] = useState(null)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [viewerArtifact, setViewerArtifact] = useState(null)
  const [page, setPage] = useState(1)
  const [pagination, setPagination] = useState(null)

  // Reset page when filters change
  useEffect(() => {
    setPage(1)
  }, [filterType, filterExt, showFlagged])

  // Reload when page or filters change
  useEffect(() => {
    loadArtifacts()
  }, [caseId, page, filterType, filterExt, showFlagged])

  const loadArtifacts = async (searchOverride) => {
    setLoading(true)
    try {
      const params = {
        page,
        page_size: PAGE_SIZE,
      }
      if (filterType)   params.extraction_type = filterType
      if (filterExt)    params.extension = filterExt
      if (showFlagged)  params.is_flagged = true
      const s = searchOverride !== undefined ? searchOverride : search
      if (s)            params.search = s

      const res = await getAllArtifacts(caseId, params)

      // Handle both old flat array and new pagination envelope
      if (res.data.items !== undefined) {
        setArtifacts(res.data.items)
        setPagination(res.data)
      } else {
        setArtifacts(res.data)
        setPagination(null)
      }
    } catch {
      toast.error('Failed to load artifacts')
    } finally {
      setLoading(false)
    }
  }

  // Only search on Enter key
  const handleSearchKey = (e) => {
    if (e.key === 'Enter') {
      setPage(1)
      loadArtifacts(search)
    }
  }

  const openDetail = async (artifact) => {
    setSelected(artifact.id)
    setLoadingDetail(true)
    try {
      const res = await getArtifact(caseId, artifact.id)
      setDetail(res.data)
      // If file is viewable, also open the full viewer modal
      if (res.data.is_viewable || res.data.stored_file_path) {
        setViewerArtifact(res.data)
      }
    } catch {
      toast.error('Failed to load artifact detail')
    } finally {
      setLoadingDetail(false)
    }
  }

  const handleFlag = async (artifactId, e) => {
    e.stopPropagation()
    try {
      const res = await flagArtifact(caseId, artifactId)
      const flagged = res.data.is_flagged
      setArtifacts(prev =>
        prev.map(a => a.id === artifactId ? { ...a, is_flagged: flagged } : a)
      )
      if (detail?.id === artifactId) {
        setDetail(prev => ({ ...prev, is_flagged: flagged }))
      }
      toast.success(flagged ? 'Artifact flagged' : 'Flag removed')
    } catch {
      toast.error('Failed to update flag')
    }
  }

  // Derive filter options from loaded page of data
  const types = [...new Set(artifacts.map(a => a.extraction_type))].filter(Boolean)
  const extensions = [...new Set(artifacts.map(a => a.file_extension))].filter(Boolean).slice(0, 20)

  // Client-side search highlight after load
  const filtered = search
    ? artifacts.filter(a =>
        a.internal_path.toLowerCase().includes(search.toLowerCase()))
    : artifacts

  return (
    <PageLayout
      fullWidth={true}
      title="Forensic Artifacts"
      subtitle="Every individual file found inside your evidence — photos, documents, emails, databases — is listed here. You can search, filter by type, and flag any file as important evidence for your investigation."
    >
      <div style={{ display: 'flex', gap: '1rem', height: 'calc(100vh - 12rem)' }}>
        {/* ── Left panel: artifact list ───────────────────────────────────── */}
        <div className="flex-1 min-w-0 flex flex-col">
          {/* Search + Filters row */}
        <div className="flex gap-2 mb-4 flex-wrap">
          <div className="relative flex-1 min-w-48">
            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-2" />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              onKeyDown={handleSearchKey}
              placeholder="Search by path… (Enter to search)"
              className="w-full bg-surface-2 border border-line rounded-lg pl-8 pr-3 py-2 text-sm text-ink-0 placeholder:text-ink-2 focus:outline-none focus:border-accent"
            />
          </div>
          <select
            value={filterType}
            onChange={e => setFilterType(e.target.value)}
            className="bg-surface-2 border border-line rounded-lg px-3 py-2 text-sm text-ink-0 focus:outline-none focus:border-accent"
          >
            <option value="">All types</option>
            {types.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
          <select
            value={filterExt}
            onChange={e => setFilterExt(e.target.value)}
            className="bg-surface-2 border border-line rounded-lg px-3 py-2 text-sm text-ink-0 focus:outline-none focus:border-accent"
          >
            <option value="">All extensions</option>
            {extensions.map(ext => <option key={ext} value={ext}>{ext}</option>)}
          </select>
          <button
            onClick={() => setShowFlagged(v => !v)}
            className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm border transition-colors
              ${showFlagged
                ? 'bg-warning/20 border-warning/50 text-warning'
                : 'bg-surface-2 border-line text-ink-2 hover:text-warning hover:border-warning/30'}`}
          >
            <Flag size={13} />
            Flagged
          </button>
        </div>

        {/* Artifact list */}
        <div className="flex-1 overflow-y-auto space-y-1.5 pr-1">
          {loading ? (
            <div className="flex items-center justify-center h-48">
              <div className="w-6 h-6 border-2 border-accent rounded-full border-t-transparent animate-spin" />
            </div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-16 text-ink-2">
              <HardDrive size={40} className="mx-auto mb-3 opacity-30" />
              <p className="text-sm font-medium mb-1">No artifacts found</p>
              <p className="text-xs">Upload a disk image (.E01, .001, .dd) to extract forensic evidence</p>
            </div>
          ) : (
            filtered.map(artifact => {
              const Icon = EXT_ICON[artifact.file_extension] || File
              const colorCls = TYPE_COLOR[artifact.extraction_type] || 'text-ink-2'
              const isSelected = selected === artifact.id

              return (
                /* A div, not a <button>: the View and Flag controls below are
                   themselves buttons, and a <button> inside a <button> is
                   invalid HTML. The browser silently hoists the inner ones out
                   of the row, so the row's own click handler stops covering
                   them and the keyboard could not reach the row at all.
                   role/tabIndex/onKeyDown keep it operable without nesting. */
                <div
                  key={artifact.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => openDetail(artifact)}
                  onKeyDown={e => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      openDetail(artifact)
                    }
                  }}
                  className={`w-full flex items-center gap-3 p-3 rounded-xl text-left transition-all border cursor-pointer
                    ${isSelected
                      ? 'bg-accent/10 border-accent/40'
                      : 'bg-surface-2 border-line hover:border-accent/30 hover:bg-surface-4'}`}
                >
                  <Icon size={16} className={`shrink-0 ${colorCls}`} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium text-ink-0 truncate">
                        {artifact.filename}
                      </p>
                      {artifact.extraction_type === 'registry' && (
                        <span style={{
                          fontSize: 9,
                          fontWeight: 700,
                          padding: '2px 6px',
                          borderRadius: 4,
                          background: 'rgba(251,146,60,0.12)',
                          border: '1px solid rgba(251,146,60,0.3)',
                          color: '#fb923c',
                          textTransform: 'uppercase',
                          letterSpacing: '0.07em',
                          flexShrink: 0,
                        }}>
                          Registry
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-ink-2 font-mono truncate">
                      {artifact.internal_path}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-xs text-ink-2">
                      {formatBytes(artifact.file_size_bytes)}
                    </span>
                    {artifact.extraction_type && (
                      <span className={`text-xs font-mono ${colorCls} opacity-70`}>
                        {artifact.extraction_type}
                      </span>
                    )}
                    {artifact.is_viewable && (
                      <button
                        onClick={e => {
                          e.stopPropagation()
                          openDetail(artifact)
                        }}
                        className="text-xs px-2 py-1 rounded-lg bg-accent/20 text-accent hover:bg-accent/30 transition-colors flex items-center gap-1"
                      >
                        <Eye size={11} />
                        View
                      </button>
                    )}
                    {artifact.is_flagged && (
                      <Flag size={11} className="text-warning" />
                    )}
                    <button
                      onClick={e => handleFlag(artifact.id, e)}
                      className={`p-1 rounded transition-colors
                        ${artifact.is_flagged
                          ? 'text-warning'
                          : 'text-ink-2 hover:text-warning'}`}
                      title={artifact.is_flagged ? 'Remove flag' : 'Flag artifact'}
                    >
                      <Flag size={11} />
                    </button>
                    <ChevronRight size={13} className="text-ink-2" />
                  </div>
                </div>
              )
            })
          )}
        </div>

        {/* Pagination controls */}
        {pagination && (
          <Pagination
            page={pagination.page}
            totalPages={pagination.total_pages}
            total={pagination.total}
            pageSize={pagination.page_size}
            onPageChange={p => setPage(p)}
          />
        )}
      </div>

      {/* ── Right panel: detail view ────────────────────────────────────── */}
      {(detail || loadingDetail) && (
        <div className="w-96 shrink-0 overflow-y-auto">
          <div className="bg-surface-2 border border-line rounded-xl p-4 sticky top-0">
            {/* Panel header */}
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold text-ink-0 text-sm truncate flex-1 mr-2">
                {detail?.filename ?? '…'}
              </h2>
              <button
                onClick={() => { setDetail(null); setSelected(null) }}
                className="text-ink-2 hover:text-ink-0 p-1 shrink-0 transition-colors"
              >
                <X size={14} />
              </button>
            </div>

            {loadingDetail ? (
              <div className="flex items-center justify-center h-32">
                <div className="w-5 h-5 border-2 border-accent rounded-full border-t-transparent animate-spin" />
              </div>
            ) : detail && (
              <>
                {/* Internal path */}
                <div className="flex items-start gap-2 mb-3">
                  <HardDrive size={13} className="text-ink-2 mt-0.5 shrink-0" />
                  <div>
                    <p className="text-xs text-ink-2 mb-0.5">Internal Path</p>
                    <p className="text-xs font-mono text-ink-1 break-all leading-relaxed">
                      {detail.internal_path}
                    </p>
                  </div>
                </div>

                {/* SHA-256 */}
                <div className="flex items-start gap-2 mb-3">
                  <Hash size={13} className="text-ink-2 mt-0.5 shrink-0" />
                  <div>
                    <p className="text-xs text-ink-2 mb-0.5">SHA-256</p>
                    <p className="text-xs font-mono text-ink-1 break-all">
                      {detail.sha256_hash
                        ? `${detail.sha256_hash.slice(0, 24)}…`
                        : '—'}
                    </p>
                  </div>
                </div>

                {/* MACB Timestamps */}
                <div className="bg-surface-1 rounded-lg p-3 mb-3">
                  <p className="text-xs font-semibold text-ink-2 uppercase tracking-wider mb-2">
                    MACB Timestamps
                  </p>
                  <div className="space-y-1.5">
                    {[
                      ['Modified', detail.modified_at],
                      ['Accessed', detail.accessed_at],
                      ['Created',  detail.created_at_ts],
                      ['Born',     detail.born_at],
                    ].map(([label, value]) => (
                      <div key={label} className="flex items-start justify-between gap-2">
                        <span className="text-xs text-ink-2 w-16 shrink-0">{label}</span>
                        <span className="text-xs font-mono text-ink-1 text-right leading-tight">
                          {value && value !== 'Unknown' ? value : '—'}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Size + Type tiles */}
                <div className="grid grid-cols-2 gap-2 mb-3">
                  <div className="bg-surface-1 rounded-lg p-2 text-center">
                    <p className="text-xs text-ink-2 mb-0.5">Size</p>
                    <p className="text-xs font-medium text-ink-0">
                      {formatBytes(detail.file_size_bytes)}
                    </p>
                  </div>
                  <div className="bg-surface-1 rounded-lg p-2 text-center">
                    <p className="text-xs text-ink-2 mb-0.5">Type</p>
                    <p className={`text-xs font-medium ${TYPE_COLOR[detail.extraction_type] || 'text-ink-0'}`}>
                      {detail.extraction_type || '—'}
                    </p>
                  </div>
                </div>

                {/* Flag button */}
                <button
                  onClick={e => handleFlag(detail.id, e)}
                  className={`w-full flex items-center justify-center gap-2 py-2 rounded-lg text-sm border mb-3 transition-colors
                    ${detail.is_flagged
                      ? 'bg-warning/20 border-warning/50 text-warning'
                      : 'bg-surface-1 border-line text-ink-2 hover:text-warning hover:border-warning/30'}`}
                >
                  <Flag size={13} />
                  {detail.is_flagged ? 'Remove Flag' : 'Flag as Important'}
                </button>

                {/* Entropy Analysis */}
                {detail.shannon_entropy !== null &&
                 detail.shannon_entropy !== undefined && (
                  <div className="bg-surface-1 rounded-lg p-3 mb-3">
                    <p className="text-xs font-semibold text-ink-2 uppercase tracking-wider mb-2">
                      Entropy Analysis
                    </p>
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-xs text-ink-2">Shannon Entropy</span>
                      <span className={`text-xs font-bold tabular-nums
                        ${detail.shannon_entropy >= 7.5
                          ? 'text-danger'
                          : detail.shannon_entropy >= 7.0
                          ? 'text-warning'
                          : 'text-success'}`}>
                        {detail.shannon_entropy?.toFixed(2)} / 8.0
                      </span>
                    </div>
                    {/* Entropy bar */}
                    <div className="w-full bg-surface-0 rounded-full h-1.5 mb-1.5">
                      <div
                        className={`h-1.5 rounded-full transition-all
                          ${detail.shannon_entropy >= 7.5
                            ? 'bg-danger'
                            : detail.shannon_entropy >= 7.0
                            ? 'bg-warning'
                            : 'bg-success'}`}
                        style={{ width: `${(detail.shannon_entropy / 8.0) * 100}%` }}
                      />
                    </div>
                    <p className="text-xs text-ink-2">
                      {detail.shannon_entropy >= 7.5
                        ? '🔒 Likely encrypted — content may be hidden'
                        : detail.shannon_entropy >= 7.0
                        ? '📦 Possibly compressed or packed'
                        : detail.shannon_entropy >= 5.0
                        ? '📄 Mixed content'
                        : '📝 Plain or structured data'}
                    </p>
                    {detail.is_deleted && (
                      <p className="text-xs text-warning mt-2 flex items-center gap-1">
                        ⚠ Recovered deleted file
                      </p>
                    )}
                  </div>
                )}

                {/* Extracted text */}
                {detail.extracted_text ? (
                  <div>
                    <p className="text-xs font-semibold text-ink-2 uppercase tracking-wider mb-2">
                      Extracted Content
                    </p>
                    <div className="bg-surface-1 rounded-lg p-3 max-h-72 overflow-y-auto">
                      <pre className="text-xs font-mono text-ink-1 whitespace-pre-wrap leading-relaxed">
                        {detail.extracted_text.slice(0, 2000)}
                        {detail.extracted_text.length > 2000 && '\n\n[truncated…]'}
                      </pre>
                    </div>
                  </div>
                ) : (
                  <div className="bg-surface-1 rounded-lg p-3 text-center">
                    <p className="text-xs text-ink-2">No text extracted from this file</p>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {/* FileViewer modal */}
      {viewerArtifact && (
        <FileViewer
          artifact={viewerArtifact}
          caseId={caseId}
          onClose={() => {
            setViewerArtifact(null)
            setSelected(null)
          }}
        />
      )}
      </div>
    </PageLayout>
  )
}
