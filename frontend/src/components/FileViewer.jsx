import React, { useState, useEffect } from 'react'
import {
  Download, X, FileText, Image as ImageIcon,
  Music, Video, Mail, Database, AlertTriangle,
  ZoomIn, ZoomOut
} from 'lucide-react'
import { apiErrorMessage } from '../api/client'

// ── Categorise by extension ───────────────────────────────────

function getCategory(filename) {
  const ext = filename
    ? '.' + filename.split('.').pop().toLowerCase()
    : ''
  if (['.jpg', '.jpeg', '.png', '.gif',
       '.bmp', '.webp', '.tiff'].includes(ext))
    return 'image'
  if (ext === '.pdf')
    return 'pdf'
  if (['.txt', '.log', '.csv', '.xml',
       '.json', '.md', '.py', '.js',
       '.html', '.htm'].includes(ext))
    return 'text'
  if (['.mp3', '.wav', '.m4a',
       '.flac', '.ogg', '.aac'].includes(ext))
    return 'audio'
  if (['.mp4', '.avi', '.mov',
       '.mkv', '.wmv'].includes(ext))
    return 'video'
  if (['.eml', '.msg'].includes(ext))
    return 'email'
  if (['.db', '.sqlite', '.sqlite3'].includes(ext))
    return 'database'
  if (['.docx', '.doc', '.xlsx',
       '.xls', '.pptx', '.ppt'].includes(ext))
    return 'office'
  return 'binary'
}

// ── Sub-viewers ───────────────────────────────────────────────

function ImageViewer({ url, filename }) {
  const [zoom, setZoom] = useState(1)
  return (
    <div className="flex flex-col items-center h-full">
      <div className="flex items-center gap-2 mb-2">
        <button
          onClick={() => setZoom(z => Math.max(0.25, z - 0.25))}
          className="p-1.5 rounded-lg bg-surface-1 text-ink-2 hover:text-ink-0"
        >
          <ZoomOut size={14} />
        </button>
        <span className="text-xs text-ink-2 w-12 text-center">
          {Math.round(zoom * 100)}%
        </span>
        <button
          onClick={() => setZoom(z => Math.min(4, z + 0.25))}
          className="p-1.5 rounded-lg bg-surface-1 text-ink-2 hover:text-ink-0"
        >
          <ZoomIn size={14} />
        </button>
        <button
          onClick={() => setZoom(1)}
          className="text-xs text-ink-2 hover:text-accent px-2"
        >
          Reset
        </button>
      </div>
      <div className="flex-1 overflow-auto flex items-center justify-center bg-surface-1 rounded-xl p-4 w-full">
        <img
          src={url}
          alt={filename}
          style={{
            transform: `scale(${zoom})`,
            transformOrigin: 'center',
            maxWidth: '100%',
            transition: 'transform 0.2s'
          }}
          className="rounded"
        />
      </div>
    </div>
  )
}

function PDFViewer({ url }) {
  return (
    <iframe
      src={url}
      className="w-full h-full rounded-xl border border-line"
      title="PDF Viewer"
    />
  )
}

/**
 * fetch that refuses to hand back an error page as if it were content.
 *
 * Both viewers below used `r.text()` with no status check, so a 401, 403 or
 * 500 produced a *resolved* promise and its body was rendered as the
 * evidence. The text viewer showed `{"detail":"Not authorized"}` under a
 * filename; the email viewer parsed the same body into a message with no
 * From, no Subject and no Date and presented it as a recovered email. In a
 * forensic viewer a fabricated artefact is worse than a visible failure,
 * because it is the one thing on the screen a reviewer cannot sanity-check
 * at a glance.
 *
 * The thrown value is shaped like an axios error so `apiErrorMessage` can be
 * reused unchanged — that keeps one precedence ladder for "what do we tell
 * the operator" instead of a second, subtly different one here.
 */
async function fetchChecked(url) {
  const r = await fetch(url, {
    headers: {
      Authorization: `Bearer ${localStorage.getItem('cfi_token')}`
    }
  })
  if (!r.ok) {
    throw Object.assign(new Error(`HTTP ${r.status}`), {
      response: { status: r.status, data: null }
    })
  }
  return r.text()
}

function TextViewer({ url, filename }) {
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchChecked(url)
      .then(text => {
        setContent(text)
        setLoading(false)
      })
      .catch(e => {
        setError(apiErrorMessage(e, 'Could not load the file.'))
        setLoading(false)
      })
  }, [url])

  if (loading) return (
    <div className="flex items-center justify-center h-32 text-ink-2">
      Loading…
    </div>
  )
  if (error) return (
    <div className="text-danger text-sm">Error: {error}</div>
  )

  const lineCount = content.split('\n').length
  const ext = '.' + filename.split('.').pop().toLowerCase()

  return (
    <div className="h-full flex flex-col bg-surface-1 rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 border-b border-line">
        <span className="text-xs text-ink-2">
          {filename} — {lineCount} lines
        </span>
        <span className="text-xs font-mono text-ink-2">
          {ext.toUpperCase().slice(1)}
        </span>
      </div>
      <div className="flex-1 overflow-auto">
        <pre className="text-xs font-mono text-ink-1 p-4 whitespace-pre-wrap leading-relaxed">
          {content.slice(0, 100000)}
          {content.length > 100000 &&
            '\n\n[File truncated at 100,000 characters for display. Download to see full content.]'}
        </pre>
      </div>
    </div>
  )
}

function AudioViewer({ url, filename }) {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4">
      <div className="w-24 h-24 rounded-2xl bg-purple-500/20 flex items-center justify-center">
        <Music size={40} className="text-purple-400" />
      </div>
      <p className="text-sm font-medium text-ink-0">{filename}</p>
      <audio
        controls
        className="w-full max-w-md"
        style={{ colorScheme: 'dark' }}
      >
        <source src={url} />
        Your browser does not support audio playback.
      </audio>
      <p className="text-xs text-ink-2 text-center max-w-xs">
        Audio extracted from forensic image.
        Transcript available in the Extracted Text tab.
      </p>
    </div>
  )
}

function VideoViewer({ url, filename }) {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-3">
      <video
        controls
        className="max-w-full max-h-96 rounded-xl"
        style={{ background: '#000' }}
      >
        <source src={url} />
        Your browser does not support video playback.
      </video>
      <p className="text-xs text-ink-2">{filename}</p>
    </div>
  )
}

function EmailViewer({ url }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchChecked(url)
      .then(text => {
        const lines = text.split('\n')
        const headers = {}
        let bodyStart = 0
        for (let i = 0; i < lines.length; i++) {
          const line = lines[i]
          if (line.startsWith('From:'))
            headers.from = line.slice(5).trim()
          else if (line.startsWith('To:'))
            headers.to = line.slice(3).trim()
          else if (line.startsWith('Subject:'))
            headers.subject = line.slice(8).trim()
          else if (line.startsWith('Date:'))
            headers.date = line.slice(5).trim()
          else if (line.trim() === '') {
            bodyStart = i + 1
            break
          }
        }
        const body = lines.slice(bodyStart).join('\n')
        setData({ headers, body })
        setLoading(false)
      })
      .catch(e => {
        setError(apiErrorMessage(e, 'Could not load the message.'))
        setLoading(false)
      })
  }, [url])

  if (loading) return (
    <div className="flex items-center justify-center h-32 text-ink-2 text-sm">
      Loading email…
    </div>
  )
  if (error) return (
    <div className="text-danger text-sm">{error}</div>
  )
  if (!data) return (
    <div className="text-ink-2 text-sm">
      The server returned the file, but its contents are not a message this
      viewer can read. It has not been shown here rather than shown
      incorrectly.
    </div>
  )

  return (
    <div className="h-full flex flex-col">
      <div className="bg-surface-1 rounded-xl p-4 mb-3 space-y-2">
        {[
          ['From', data.headers.from],
          ['To', data.headers.to],
          ['Subject', data.headers.subject],
          ['Date', data.headers.date]
        ].map(([label, value]) =>
          value ? (
            <div key={label} className="flex gap-3">
              <span className="text-xs font-semibold text-ink-2 w-16 shrink-0">
                {label}
              </span>
              <span className="text-xs text-ink-0">{value}</span>
            </div>
          ) : null
        )}
      </div>
      <div className="flex-1 overflow-auto bg-surface-1 rounded-xl p-4">
        <pre className="text-xs text-ink-1 whitespace-pre-wrap font-sans leading-relaxed">
          {data.body}
        </pre>
      </div>
    </div>
  )
}

function OfficeViewer({ extractedText, filename }) {
  if (!extractedText) return (
    <div className="flex flex-col items-center justify-center h-full text-ink-2 gap-3">
      <FileText size={40} className="opacity-30" />
      <p className="text-sm">No text could be extracted from this file.</p>
    </div>
  )
  return (
    <div className="h-full flex flex-col bg-white rounded-xl overflow-hidden">
      <div className="px-4 py-2 bg-gray-100 border-b border-gray-200">
        <span className="text-xs text-gray-600 font-medium">
          {filename} — Extracted Text
        </span>
      </div>
      <div className="flex-1 overflow-auto p-6">
        <div className="max-w-2xl mx-auto">
          <pre className="text-sm text-gray-800 whitespace-pre-wrap font-sans leading-relaxed">
            {extractedText}
          </pre>
        </div>
      </div>
    </div>
  )
}

function BinaryViewer({ filename, entropy, extractedText }) {
  return (
    <div className="flex flex-col items-center justify-center h-full text-ink-2 gap-4">
      <div className="w-16 h-16 rounded-2xl bg-surface-1 flex items-center justify-center">
        <AlertTriangle
          size={32}
          className={entropy >= 7.5 ? 'text-danger' : 'text-ink-2'}
        />
      </div>
      <p className="text-sm font-medium text-ink-0">{filename}</p>
      {entropy !== null && entropy !== undefined && (
        <div className="text-center">
          <p className={`text-lg font-bold ${
            entropy >= 7.5
              ? 'text-danger'
              : entropy >= 7.0
              ? 'text-warning'
              : 'text-ink-2'
          }`}>
            Entropy: {entropy?.toFixed(2)} / 8.0
          </p>
          <p className="text-xs text-ink-2 mt-1">
            {entropy >= 7.5
              ? '🔒 Likely encrypted — cannot display content'
              : entropy >= 7.0
              ? '📦 Possibly compressed'
              : 'Binary file format'}
          </p>
        </div>
      )}
      {extractedText && (
        <div className="w-full max-w-lg bg-surface-1 rounded-xl p-3 mt-2">
          <p className="text-xs text-ink-2 mb-2">Extracted text preview:</p>
          <pre className="text-xs font-mono text-ink-1 whitespace-pre-wrap max-h-32 overflow-auto">
            {extractedText.slice(0, 500)}
          </pre>
        </div>
      )}
      <p className="text-xs text-ink-2 text-center max-w-xs">
        Binary files cannot be displayed in the browser.
        Use the download button to view in an external application.
      </p>
    </div>
  )
}

// ── Main FileViewer component ─────────────────────────────────

export default function FileViewer({ artifact, caseId, onClose }) {
  const [activeTab, setActiveTab] = useState('file')

  if (!artifact) return null

  const category = getCategory(artifact.filename)

  // Build file URL with auth token as query param for media elements
  // (img/audio/video can't set Authorization headers)
  const token = localStorage.getItem('cfi_token')
  const fileUrl =
    `/api/cases/${caseId}/evidence/artifacts/${artifact.id}/view` +
    (token ? `?token=${token}` : '')

  const hasStoredFile = artifact.has_stored_file || artifact.is_viewable

  const downloadUrl =
    `/api/cases/${caseId}/evidence/artifacts/${artifact.id}/download`

  const TABS = [
    { id: 'file', label: '📄 View File' },
    { id: 'text', label: '📝 Extracted Text' },
    { id: 'meta', label: '🔍 Metadata' }
  ]

  return (
    <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4">
      <div className="bg-surface-2 border border-line rounded-2xl w-full max-w-5xl h-[85vh] flex flex-col shadow-2xl">

        {/* ── Header ── */}
        <div className="flex items-center gap-3 px-5 py-3 border-b border-line shrink-0">
          <div className="flex-1 min-w-0">
            <p className="font-semibold text-ink-0 truncate">
              {artifact.filename}
            </p>
            <p className="text-xs text-ink-2 font-mono truncate mt-0.5">
              {artifact.internal_path}
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {hasStoredFile && (
              <a
                href={downloadUrl}
                download={artifact.filename}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-surface-1 border border-line text-ink-2 hover:text-accent hover:border-accent/50 transition-colors"
              >
                <Download size={12} />
                Download
              </a>
            )}
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-ink-2 hover:text-ink-0 hover:bg-surface-4"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* ── Tabs ── */}
        <div className="flex gap-1 px-4 pt-2 border-b border-line shrink-0">
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-3 py-1.5 text-xs rounded-t-lg transition-colors border-b-2 ${
                activeTab === tab.id
                  ? 'text-accent border-accent'
                  : 'text-ink-2 border-transparent hover:text-ink-0'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* ── Content ── */}
        <div className="flex-1 overflow-hidden p-4">

          {/* View File tab */}
          {activeTab === 'file' && (
            <div className="h-full">
              {!hasStoredFile ? (
                <div className="flex flex-col items-center justify-center h-full text-ink-2 gap-3">
                  <AlertTriangle size={36} className="opacity-30" />
                  <p className="text-sm">File was not saved during ingestion.</p>
                  <p className="text-xs max-w-xs text-center">
                    This file was too large (&gt;100 MB) or is a system binary.
                    Re-ingest with the updated code to save all supported files.
                  </p>
                </div>
              ) : category === 'image' ? (
                <ImageViewer url={fileUrl} filename={artifact.filename} />
              ) : category === 'pdf' ? (
                <PDFViewer url={fileUrl} />
              ) : category === 'text' ? (
                <TextViewer url={fileUrl} filename={artifact.filename} />
              ) : category === 'audio' ? (
                <AudioViewer url={fileUrl} filename={artifact.filename} />
              ) : category === 'video' ? (
                <VideoViewer url={fileUrl} filename={artifact.filename} />
              ) : category === 'email' ? (
                <EmailViewer url={fileUrl} />
              ) : category === 'office' ? (
                <OfficeViewer
                  extractedText={artifact.extracted_text || artifact.text_preview}
                  filename={artifact.filename}
                />
              ) : (
                <BinaryViewer
                  filename={artifact.filename}
                  entropy={artifact.shannon_entropy}
                  extractedText={artifact.extracted_text || artifact.text_preview}
                />
              )}
            </div>
          )}

          {/* Extracted Text tab */}
          {activeTab === 'text' && (
            <div className="h-full overflow-auto bg-surface-1 rounded-xl p-4">
              {artifact.extracted_text || artifact.text_preview ? (
                <pre className="text-xs font-mono text-ink-1 whitespace-pre-wrap leading-relaxed">
                  {artifact.extracted_text || artifact.text_preview}
                </pre>
              ) : (
                <p className="text-sm text-ink-2 text-center mt-8">
                  No text was extracted from this file.
                </p>
              )}
            </div>
          )}

          {/* Metadata tab */}
          {activeTab === 'meta' && (
            <div className="h-full overflow-auto">
              <div className="grid grid-cols-2 gap-3">
                {[
                  ['Filename', artifact.filename],
                  ['Internal Path', artifact.internal_path],
                  ['File Size',
                    artifact.file_size_bytes
                      ? (artifact.file_size_bytes / 1024).toFixed(1) + ' KB'
                      : 'Unknown'],
                  ['SHA-256',
                    artifact.sha256_hash
                      ? artifact.sha256_hash.slice(0, 32) + '…'
                      : null],
                  ['Modified', artifact.modified_at],
                  ['Accessed', artifact.accessed_at],
                  ['Created', artifact.created_at_ts],
                  ['Born', artifact.born_at],
                  ['Extraction Type', artifact.extraction_type],
                  ['Entropy',
                    artifact.shannon_entropy != null
                      ? artifact.shannon_entropy.toFixed(3) + ' / 8.0'
                      : null],
                  ['Is Deleted',
                    artifact.is_deleted ? '⚠ Yes — recovered' : 'No'],
                  ['Anomaly',
                    artifact.is_anomaly ? '⚠ Flagged' : 'None'],
                  ['MIME Type', artifact.mime_type],
                  ['Stored on Disk',
                    artifact.has_stored_file || artifact.is_viewable
                      ? 'Yes'
                      : 'No (text-only)'],
                ]
                  .filter(([, v]) => v)
                  .map(([label, value]) => (
                    <div key={label} className="bg-surface-1 rounded-xl p-3">
                      <p className="text-xs text-ink-2 mb-1">{label}</p>
                      <p className="text-xs font-mono text-ink-0 break-all">
                        {value}
                      </p>
                    </div>
                  ))}
              </div>
            </div>
          )}

        </div>
      </div>
    </div>
  )
}
