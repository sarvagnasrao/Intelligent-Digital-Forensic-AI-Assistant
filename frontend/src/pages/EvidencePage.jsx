import React, { useState, useEffect, useRef, useCallback } from "react"
import { useParams, useNavigate } from "react-router-dom"
import {
  Upload, File, FileText, FileCode,
  Database, Music, Video,
  Image, Mail, Table, MessageSquare,
  CheckCircle, Clock,
  AlertCircle, RefreshCw,
  Info, Shield, Archive, ArchiveRestore, Eye, EyeOff,
  Play, Loader, X, Cpu,
  ChevronDown, ChevronUp,
  Zap, Activity, ChevronRight, Square,
  Zap as ZapIcon, Sliders, Save, MemoryStick, HardDrive,
  UploadCloud, Settings, Plus, User, Gauge, Circle
} from "lucide-react"
import {
  getEvidence, uploadEvidence, uploadMultiEvidence,
  getEvidenceItem, archiveEvidence, restoreEvidence,
  verifyEvidence, getEvidenceFormats,
  addToQueue, estimateTime,
  getStorageStats,
  getQueue, getQueueHistory, cancelJob,
  forceStartJob, stopJob, updateJobSettings,
  apiErrorMessage
} from "../api/client"
import Badge from "../components/Badge"
import ConfirmDialog from "../components/ConfirmDialog"
import PageLayout from "../components/PageLayout"
import ResourceMonitor from "../components/ResourceMonitor"
import toast from "react-hot-toast"
import { formatDistanceToNow } from "date-fns"
import { fromUtc } from '../utils/time'
import useWebSocket from "../hooks/useWebSocket"
import useSystemInfo from "../hooks/useSystemInfo"

// ── Supported format groups ────────────────────────────────
// The format groups themselves are served by the backend
// (GET /api/evidence/formats) rather than restated here. Only the
// presentation lives in the frontend: an icon and a colour per group key.
//
// This list used to be hardcoded, and it drifted from the server's own list
// in both directions - the file picker offered formats the server refused
// with a 400, and the format guide described a set the server no longer
// accepted. A list of accepted evidence formats is a fact about the backend,
// not a piece of UI copy.
const GROUP_STYLE = {
  Database:  { icon: Database,  color: 'text-accent' },
  FileText:  { icon: FileText,  color: 'text-blue-400' },
  Table:     { icon: Table,     color: 'text-green-400' },
  Settings:  { icon: Settings,  color: 'text-cyan-400' },
  FileCode:  { icon: FileCode,  color: 'text-amber-400' },
  MessageSquare: { icon: MessageSquare, color: 'text-teal-400' },
  Mail:      { icon: Mail,      color: 'text-orange-400' },
  Image:     { icon: Image,     color: 'text-yellow-400' },
  Music:     { icon: Music,     color: 'text-purple-400' },
  Video:     { icon: Video,     color: 'text-pink-400' },
}

const DEFAULT_GROUP_STYLE = { icon: File, color: 'text-ink-2' }

// ── Per-extension icon map ─────────────────────────────────
// Presentation only. An extension with no entry here still uploads and
// ingests correctly; it just gets the generic File glyph in the list, which
// is why this is a lookup and not a gate.
const EXT_ICON = {
  '.pdf':  FileText, '.txt':  FileText, '.rtf': FileText,
  '.log':  FileText, '.md':   FileText, '.nfo': FileText,
  '.out':  FileText, '.err':  FileText, '.trace': FileText,
  '.csv':  Table,    '.tsv':  Table,   '.xls': Table,
  '.xlsx': Table,    '.json': Table,   '.jsonl': Table,
  '.ndjson': Table,  '.xml':  Table,   '.plist': Table,
  '.mobileconfig': Table, '.sqlite': Table, '.sqlite3': Table, '.db': Table,
  '.yaml': Settings, '.yml':  Settings, '.ini':  Settings,
  '.cfg':  Settings, '.conf': Settings, '.config': Settings,
  '.toml': Settings, '.properties': Settings, '.env': Settings,
  '.srt':  MessageSquare, '.vtt': MessageSquare, '.ass': MessageSquare,
  '.docx': FileText, '.doc':  FileText,
  '.pptx': FileText, '.ppt':  FileText,
  '.mp3':  Music,    '.wav':  Music,
  '.m4a':  Music,    '.flac': Music,
  '.ogg':  Music,    '.aac':  Music,
  '.wma':  Music,    '.aiff': Music,
  '.mp4':  Video,    '.avi':  Video,
  '.mov':  Video,    '.mkv':  Video,
  '.wmv':  Video,    '.flv':  Video,
  '.webm': Video,    '.m4v':  Video,
  '.jpg':  Image,    '.jpeg': Image,
  '.png':  Image,    '.tiff': Image,
  '.tif':  Image,    '.bmp':  Image,
  '.gif':  Image,    '.webp': Image,
  '.eml':  Mail,     '.msg':  Mail,
  '.e01':  Database, '.001':  Database,
  '.dd':   Database, '.raw':  Database,
  '.img':  Database,
}

const statusIcon = {
  'Uploaded': <Clock size={14} className="text-warning" />,
  'Queued': <Clock size={14} className="text-warning" />,
  'Running': <Loader size={14} className="text-accent animate-spin" />,
  'Indexed': <CheckCircle size={14} className="text-success" />,
  'Completed': <CheckCircle size={14} className="text-success" />,
  'Failed': <AlertCircle size={14} className="text-danger" />,
  // Without this, an archived item fell through to the pending Clock above.
  // Archived is neither pending nor done — it is a deliberate removal, and the
  // icon should say so rather than implying work is outstanding.
  'Archived': <Archive size={14} className="text-ink-2" />,
}

// Mirrors normalize_extension() in backend/modules/file_formats.py, so the
// icon shown matches the format the server actually ingested. Two cases the
// naive `split('.').pop()` gets wrong, and both are common evidence:
// rotated logs ("app.log.1" is a .log, not a ".1") and dotfiles (".env" has
// no extension at all).
const DOTFILE_ICONS = new Set([
  '.env', '.envrc', '.gitignore', '.gitconfig', '.npmrc',
  '.bashrc', '.bash_history', '.zsh_history', '.profile',
  '.htaccess', '.htpasswd', '.netrc', '.pgpass',
])

function fileExtension(filename) {
  if (!filename) return ''
  const name = String(filename).split('\\').pop().toLowerCase()
  if (DOTFILE_ICONS.has(name)) return name
  const parts = name.split('.')
  if (parts.length > 1 && /^\d{1,2}$/.test(parts[parts.length - 1])) {
    return '.' + parts[parts.length - 2]
  }
  return parts.length > 1 ? '.' + parts[parts.length - 1] : ''
}

function getFileIcon(filename) {
  if (!filename) return File
  return EXT_ICON[fileExtension(filename)] || File
}

function formatBytes(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1048576).toFixed(1)} MB`
}

// ── Sub-components ─────────────────────────────────────────

function ProgressBar({ percent, status }) {
  const color =
    status === 'Failed'  ? 'bg-danger'
    : status === 'Stopped' ? 'bg-warning'
    : status === 'Completed' ? 'bg-success'
    : 'bg-accent'
  return (
    <div className="w-full bg-surface-1 rounded-full h-2 mt-2">
      <div
        className={`h-2 rounded-full transition-all duration-700 ${color}`}
        style={{ width: `${Math.max(0, Math.min(100, percent))}%` }}
      />
    </div>
  )
}

function formatSeconds(s) {
  if (!s) return '—'
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m`
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`
}

const STEPS = [
  { key: '1', label: 'Reading' },
  { key: '2', label: 'Extracting' },
  { key: '3', label: 'Chunking' },
  { key: '4', label: 'Embedding' },
  { key: '5', label: 'Graph' },
]

function detectStep(currentStep) {
  if (!currentStep) return 0
  const m = currentStep.match(/Step (\d)\/5/)
  return m ? parseInt(m[1]) : 0
}

function StepIndicator({ currentStep }) {
  const active = detectStep(currentStep)
  return (
    <div className="flex items-center gap-1 mt-2 flex-wrap">
      {STEPS.map((s, i) => {
        const done    = active > i + 1
        const running = active === i + 1
        return (
          <React.Fragment key={s.key}>
            <div className={`flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium border transition-all
              ${done    ? 'bg-success/15 border-success/40 text-success'
              : running ? 'bg-accent/15 border-accent/40 text-accent animate-pulse'
              :           'bg-surface-1 border-line text-ink-2 opacity-40'}`}>
              {done    ? <CheckCircle size={9} />
               : running ? <Loader size={9} className="animate-spin" /> : null}
              {s.label}
            </div>
            {i < STEPS.length - 1 && (
              <ChevronRight size={10} className="text-ink-2 opacity-25 shrink-0" />
            )}
          </React.Fragment>
        )
      })}
    </div>
  )
}

// ── Instructions panel ─────────────────────────────────────
function InstructionsPanel() {
  const [open, setOpen] = useState(false)
  return (
    <div className="bg-surface-2 border border-accent/20 rounded-xl mb-6 overflow-hidden">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-accent/5 transition-colors"
      >
        <span className="flex items-center gap-2 text-xs font-semibold text-accent uppercase tracking-wider">
          <Info size={13} />
          How ingestion works — specs &amp; resource settings
        </span>
        {open ? <ChevronUp size={13} className="text-ink-2" /> : <ChevronDown size={13} className="text-ink-2" />}
      </button>

      {open && (
        <div className="px-4 pb-4 border-t border-line">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4">
            <div className="bg-surface-1 rounded-lg p-3">
              <div className="flex items-center gap-2 mb-2">
                <Activity size={13} className="text-accent" />
                <p className="text-xs font-semibold text-ink-0">5 Ingestion Phases</p>
              </div>
              <ol className="space-y-1.5">
                {[
                  ['Read file', 'Load bytes from disk'],
                  ['Extract text', 'PDF, DOCX, audio, images (OCR)'],
                  ['Chunk text', 'Split into ~500-word segments'],
                  ['Embed chunks', 'Store vectors in Qdrant for AI search'],
                  ['Entity graph', 'Extract names, IPs, locations, dates'],
                ].map(([name, desc], i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-accent text-xs font-bold shrink-0 w-4">{i + 1}.</span>
                    <div>
                      <p className="text-xs font-medium text-ink-0 leading-none">{name}</p>
                      <p className="text-[10px] text-ink-2 leading-tight mt-0.5">{desc}</p>
                    </div>
                  </li>
                ))}
              </ol>
            </div>

            <div className="bg-surface-1 rounded-lg p-3">
              <div className="flex items-center gap-2 mb-2">
                <FileText size={13} className="text-accent" />
                <p className="text-xs font-semibold text-ink-0">Supported File Types</p>
              </div>
              <div className="space-y-1.5">
                {[
                  ['Documents', 'PDF, TXT, DOCX, XLSX, PPTX, EML, MSG'],
                  ['Images (OCR)', 'JPG, PNG, TIFF, BMP (requires Tesseract)'],
                  ['Audio', 'MP3, WAV, M4A, FLAC (requires Whisper)'],
                  ['Video', 'MP4, AVI, MOV, MKV (requires ffmpeg)'],
                  ['Disk images', '.E01, .DD, .RAW, .IMG (forensic)'],
                ].map(([type, exts]) => (
                  <div key={type}>
                    <p className="text-[10px] font-semibold text-ink-2 uppercase tracking-wide">{type}</p>
                    <p className="text-xs text-ink-1">{exts}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="bg-surface-1 rounded-lg p-3">
              <div className="flex items-center gap-2 mb-2">
                <Cpu size={13} className="text-accent" />
                <p className="text-xs font-semibold text-ink-0">Resource Settings</p>
              </div>
              <div className="space-y-2.5">
                <div>
                  <p className="text-xs font-semibold text-ink-0">CPU Throttle %</p>
                  <p className="text-[10px] text-ink-2 leading-snug mt-0.5">
                    Limits how much CPU ingestion uses. 100% = full speed,
                    50% = half speed, 25% = very slow but minimal impact.
                  </p>
                </div>
                <div>
                  <p className="text-xs font-semibold text-ink-0">Min Free RAM (GB)</p>
                  <p className="text-[10px] text-ink-2 leading-snug mt-0.5">
                    RAM kept free for OS. If RAM drops below this, ingestion
                    pauses 30–60s and auto-resumes when free.
                  </p>
                </div>
                <div className="bg-accent/5 border border-accent/20 rounded p-2">
                  <p className="text-[10px] text-accent font-medium">
                    💡 Use Force Start to bypass limits instantly.
                    Use Edit to adjust specs on any active job.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Ingestion mode picker ────────────────────────────────────
// Rendered from the server's profile list, so a label or a description can
// never drift from the code that actually implements the mode.
function ModePicker({ modes, value, onChange, disabled }) {
  if (!modes.length) {
    return (
      <p className="text-[10px] text-ink-2">Loading profiles…</p>
    )
  }
  return (
    <div className="space-y-1.5" role="radiogroup" aria-label="Ingestion profile">
      {modes.map((m) => {
        const active = m.key === value
        const eff = m.effective || {}
        const warn = (eff.warnings || []).length > 0
        return (
          <button
            key={m.key}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={disabled}
            onClick={() => onChange(m.key)}
            className={`w-full text-left px-3 py-2 rounded-lg border transition-colors disabled:opacity-50
              ${active
                ? 'border-accent/60 bg-accent/10'
                : 'border-line bg-surface-1 hover:border-ink-2/40'}`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-semibold text-ink-0 flex items-center gap-1.5">
                {active
                  ? <CheckCircle size={12} className="text-accent" />
                  : <Circle size={12} className="text-ink-2 opacity-50" />}
                {m.label}
                <span className="text-[10px] font-normal text-ink-2">{m.tagline}</span>
              </span>
              <span className="text-[10px] text-ink-2 shrink-0 tabular-nums">
                {m.speed} · {m.accuracy}
              </span>
            </div>
            {active && (
              <p className="text-[10px] text-ink-2 leading-snug mt-1 ml-5">{m.description}</p>
            )}
            {active && (
              <div className="flex flex-wrap gap-1 mt-1.5 ml-5">
                {eff.whisper_model && (
                  <span className="text-[9px] px-1.5 py-0.5 rounded bg-surface-3 text-ink-2">
                    whisper: {eff.whisper_model}{eff.whisper_gpu ? ' (GPU)' : ''}
                  </span>
                )}
                <span className="text-[9px] px-1.5 py-0.5 rounded bg-surface-3 text-ink-2">
                  chunk: {eff.chunk_size}
                </span>
                {m.includes_deleted_files && (
                  <span className="text-[9px] px-1.5 py-0.5 rounded bg-success/15 text-success">
                    deleted-file recovery
                  </span>
                )}
                {!m.runs_ocr && (
                  <span className="text-[9px] px-1.5 py-0.5 rounded bg-warning/15 text-warning">
                    no OCR
                  </span>
                )}
              </div>
            )}
            {active && warn && (
              <p className="text-[10px] text-warning leading-snug mt-1.5 ml-5">
                {eff.warnings.join(' ')}
              </p>
            )}
          </button>
        )
      })}
    </div>
  )
}

// ── Queue Settings Modal ────────────────────────────────────
function QueueModal({ ev, onClose, onQueue }) {
  const { budget, modes, defaultMode, loading } = useSystemInfo()

  // The slider bounds and the defaults both come from the live device
  // budget. Before it arrives we render nothing numeric rather than
  // guessing - a hardcoded 8 GB maximum was the bug this replaced.
  const [mode, setMode]   = useState(null)
  const [cpu, setCpu]     = useState(null)
  const [ram, setRam]     = useState(null)
  const [saving, setSaving] = useState(false)

  // Seed the controls once, from the device budget.
  useEffect(() => {
    if (!budget) return
    if (cpu === null) setCpu(budget.cpu_throttle_percent)
    if (ram === null) setRam(
      Math.round((budget.ram_floor_default_mb / 1024) * 2) / 2
    )
  }, [budget, cpu, ram])

  const effectiveMode = mode || defaultMode
  const ramMaxGb = budget
    ? Math.max(1, Math.round(budget.ram_floor_max_mb / 1024))
    : 0

  const handleQueue = async () => {
    setSaving(true)
    try {
      await onQueue(cpu, ram, effectiveMode)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-surface-2 border border-line rounded-2xl w-full max-w-sm shadow-2xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-line">
          <div className="flex items-center gap-2">
            <Sliders size={16} className="text-accent" />
            <h2 className="text-sm font-semibold text-ink-0">Queue Ingestion</h2>
          </div>
          <button onClick={onClose} className="text-ink-2 hover:text-ink-0 transition-colors">
            <X size={16} />
          </button>
        </div>

        <div className="p-5 space-y-5 overflow-y-auto">
          <div className="flex items-center gap-2 bg-surface-1 rounded-lg px-3 py-2">
            <p className="text-xs text-ink-0 truncate" title={ev.original_filename}>
              Queueing: <span className="font-semibold">{ev.original_filename}</span>
            </p>
          </div>

          <div>
            <p className="text-xs font-semibold text-ink-0 flex items-center gap-1.5 mb-1.5">
              <Gauge size={12} className="text-accent" /> Ingestion Profile
            </p>
            <ModePicker
              modes={modes}
              value={effectiveMode}
              onChange={setMode}
              disabled={loading}
            />
          </div>

          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs font-semibold text-ink-0 flex items-center gap-1.5">
                <Cpu size={12} className="text-accent" /> CPU Ceiling
              </label>
              <span className={`text-sm font-bold tabular-nums ${cpu >= 80 ? 'text-warning' : cpu >= 50 ? 'text-accent' : 'text-success'}`}>
                {cpu === null ? '—' : `${cpu}%`}
              </span>
            </div>
            <input
              type="range" min="10" max="100" step="5"
              value={cpu ?? 90}
              onChange={e => setCpu(Number(e.target.value))}
              disabled={cpu === null}
              className="w-full accent-violet-500 disabled:opacity-40"
            />
            <div className="flex justify-between text-[10px] text-ink-2 mt-0.5">
              <span>10%</span><span>50%</span><span>100%</span>
            </div>
            {budget && (
              <p className="text-[10px] text-ink-2 mt-1">
                Ingestion sleeps between batches once the machine passes this
                load. Suggested for this device: {budget.cpu_throttle_percent}%.
              </p>
            )}
          </div>

          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs font-semibold text-ink-0 flex items-center gap-1.5">
                <MemoryStick size={12} className="text-accent" /> Min Free RAM
              </label>
              <span className={`text-sm font-bold tabular-nums ${ram === null ? '' : ram < 1 ? 'text-danger' : ram < 2 ? 'text-warning' : 'text-success'}`}>
                {ram === null ? '—' : `${ram} GB`}
              </span>
            </div>
            <input
              type="range" min="0" max={ramMaxGb || 1} step="0.5"
              value={ram ?? 0}
              onChange={e => setRam(Number(e.target.value))}
              disabled={ram === null}
              className="w-full accent-violet-500 disabled:opacity-40"
            />
            <div className="flex justify-between text-[10px] text-ink-2 mt-0.5">
              <span>0 GB (override)</span>
              <span>max {ramMaxGb || '—'} GB</span>
            </div>
            {budget && (
              <p className="text-[10px] text-ink-2 mt-1">
                {budget.description}. {budget.gpu_acceleration}. The job waits
                here if free memory drops below this, so it never starves the
                rest of the machine.
              </p>
            )}
            {ram !== null && ram < 1 && (
              <p className="text-[10px] text-danger mt-1 flex items-center gap-1">
                <AlertCircle size={10} />
                0 GB min RAM — ingestion will never pause. Use carefully.
              </p>
            )}
          </div>
        </div>

        <div className="flex gap-2 px-5 pb-5 pt-1">
          <button onClick={onClose} className="flex-1 py-2 rounded-lg border border-line text-xs text-ink-2 hover:text-ink-0 transition-colors">Cancel</button>
          <button onClick={handleQueue} disabled={saving || cpu === null || ram === null} className="flex-1 py-2 rounded-lg bg-accent hover:bg-accent/90 text-white text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors disabled:opacity-50">
            {saving ? <Loader size={12} className="animate-spin" /> : <Plus size={12} />} Queue Job
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Edit Settings Modal ────────────────────────────────────
function EditSettingsModal({ job, onClose, onSaved }) {
  const { budget, modes, defaultMode } = useSystemInfo()
  const [cpu, setCpu]     = useState(job.cpu_throttle_percent ?? 70)
  const [ram, setRam]     = useState(Math.round((job.min_free_ram_mb ?? 2048) / 1024 * 10) / 10)
  const [mode, setMode]   = useState(job.ingestion_mode || defaultMode)
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    setSaving(true)
    try {
      const res = await updateJobSettings(job.id, {
        cpu_throttle_percent: cpu,
        min_free_ram_mb:      Math.round(ram * 1024),
        ingestion_mode:       mode,
      })
      const live = res.data?.applied_live
      toast.success(
        live
          ? `Settings applied to the running job — CPU ${cpu}%, RAM floor ${ram} GB, ${mode}`
          : `Settings saved — CPU ${cpu}%, RAM floor ${ram} GB, ${mode}`
      )
      onSaved()
      onClose()
    } catch (e) {
      const d = e.response?.data?.detail;
      const msg = typeof d === 'string' ? d : (d?.detail || (Array.isArray(d) ? d[0]?.msg : 'Failed to update settings'));
      toast.error(msg)
    } finally {
      setSaving(false)
    }
  }

  // Slider ceiling follows the device, as it does in the queue form.
  const ramMaxGb = budget
    ? Math.max(1, Math.round(budget.ram_floor_max_mb / 1024))
    : 8

  // A job queued on a bigger machine (or before the budget was known) can
  // carry a floor above what this one can free. Pull it down so the slider
  // and the saved value agree instead of silently submitting an out-of-range
  // number the server would clamp anyway.
  useEffect(() => {
    if (budget && ram > ramMaxGb) setRam(ramMaxGb)
  }, [budget, ramMaxGb, ram])

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-surface-2 border border-line rounded-2xl w-full max-w-sm shadow-2xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-line">
          <div className="flex items-center gap-2">
            <Sliders size={16} className="text-accent" />
            <h2 className="text-sm font-semibold text-ink-0">Edit Resource Settings</h2>
          </div>
          <button onClick={onClose} className="text-ink-2 hover:text-ink-0 transition-colors">
            <X size={16} />
          </button>
        </div>

        <div className="p-5 space-y-5 overflow-y-auto">
          {/* Status badge */}
          <div className="flex items-center gap-2 bg-surface-1 rounded-lg px-3 py-2">
            <span className={`w-2 h-2 rounded-full shrink-0 ${job.status === 'Running' ? 'bg-accent animate-pulse' : 'bg-warning'}`} />
            <p className="text-xs text-ink-2">
              <span className="font-medium text-ink-0">{job.status}</span>
              {job.status === 'Running'
                ? ' — changes are pushed into the running job immediately'
                : ' — changes apply when the job starts'}
            </p>
          </div>

          {/* Profile */}
          <div>
            <p className="text-xs font-semibold text-ink-0 flex items-center gap-1.5 mb-1.5">
              <Gauge size={12} className="text-accent" /> Ingestion Profile
            </p>
            <ModePicker
              modes={modes}
              value={mode}
              onChange={setMode}
              disabled={job.status === 'Running'}
            />
            {job.status === 'Running' && (
              <p className="text-[10px] text-ink-2 mt-1">
                The profile is read when the job starts, so it cannot be
                changed mid-run. Stop and re-queue to switch.
              </p>
            )}
          </div>

          {/* CPU slider */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs font-semibold text-ink-0 flex items-center gap-1.5">
                <Cpu size={12} className="text-accent" /> CPU Ceiling
              </label>
              <span className={`text-sm font-bold tabular-nums
                ${cpu >= 80 ? 'text-warning' : cpu >= 50 ? 'text-accent' : 'text-success'}`}>
                {cpu}%
              </span>
            </div>
            <input
              type="range" min="10" max="100" step="5"
              value={cpu}
              onChange={e => setCpu(Number(e.target.value))}
              className="w-full accent-violet-500"
            />
            <div className="flex justify-between text-[10px] text-ink-2 mt-0.5">
              <span>10% (very slow)</span>
              <span>50% (balanced)</span>
              <span>100% (full)</span>
            </div>
          </div>

          {/* RAM slider */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs font-semibold text-ink-0 flex items-center gap-1.5">
                <MemoryStick size={12} className="text-accent" /> Min Free RAM
              </label>
              <span className={`text-sm font-bold tabular-nums
                ${ram < 1 ? 'text-danger' : ram < 2 ? 'text-warning' : 'text-success'}`}>
                {ram} GB
              </span>
            </div>
            <input
              type="range" min="0" max={ramMaxGb} step="0.5"
              value={Math.min(ram, ramMaxGb)}
              onChange={e => setRam(Number(e.target.value))}
              className="w-full accent-violet-500"
            />
            <div className="flex justify-between text-[10px] text-ink-2 mt-0.5">
              <span>0 GB (override)</span>
              <span>max {ramMaxGb} GB</span>
            </div>
            {budget && (
              <p className="text-[10px] text-ink-2 mt-1">
                {budget.description}. Capped at {ramMaxGb} GB — the most this
                machine can currently hold free.
              </p>
            )}
            {ram < 1 && (
              <p className="text-[10px] text-danger mt-1 flex items-center gap-1">
                <AlertCircle size={10} />
                0 GB min RAM — ingestion will never pause. Use carefully.
              </p>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex gap-2 px-5 pb-5">
          <button
            onClick={onClose}
            className="flex-1 py-2 rounded-lg border border-line text-xs text-ink-2 hover:text-ink-0 hover:border-ink-2 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex-1 py-2 rounded-lg bg-accent hover:bg-accent/90 text-white text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors disabled:opacity-50"
          >
            {saving ? <Loader size={12} className="animate-spin" /> : <Save size={12} />}
            Save Settings
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────

export default function EvidencePage() {
  const { caseId } = useParams()
  const [evidence, setEvidence] = useState([])
  // Kept separate from `evidence` rather than filtered at render time, so the
  // two lists are exactly what the server returned and the archived count on
  // the toggle cannot drift from what the toggle reveals.
  const [archived, setArchived] = useState([])
  const [showArchived, setShowArchived] = useState(false)
  const [restoring, setRestoring] = useState({})
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  // `investigator` used to be a state string appended to the upload
  // FormData as `ingested_by`. The server now takes the uploader from the
  // authenticated session, because that name is written to the chain of
  // custody — so the state is gone rather than kept as a dead field.
  const [includeDeleted, setIncludeDeleted] = useState(false)
  const [showFormats, setShowFormats] = useState(false)
  const [confirmArchive, setConfirmArchive] = useState(null)
  const [confirmRestore, setConfirmRestore] = useState(null)
  const [verifyResult, setVerifyResult] = useState({})
  const [verifying, setVerifying] = useState({})
  const fileRef = useRef()
  const pollRef = useRef({})

  // Queue state
  const [queuingEv, setQueuingEv] = useState(null)
  const [estimates, setEstimates] = useState({})
  // Per-evidence in-flight and failed estimates. Without `estimating`, a
  // second click would fire a duplicate request; without `estimateError`, a
  // failed estimate simply leaves the previous figure (or nothing) on
  // screen, which reads as "no estimate available" rather than "the request
  // failed". See handleEstimate.
  const [estimating, setEstimating] = useState({})
  const [estimateError, setEstimateError] = useState({})
  // Queue/history fetch failures. Kept apart from `queue`/`history` so that
  // a request that failed can never be rendered as an empty result.
  const [queueLoadError, setQueueLoadError] = useState(null)
  const [historyLoadError, setHistoryLoadError] = useState(null)
  const [addingToQueue, setAddingToQueue] = useState({})

  // Storage stats
  const [storageStats, setStorageStats] = useState(null)

  // Accepted formats, served by the backend. Null until it answers, and
  // null is rendered as "still loading" rather than as an empty list — a
  // format guide that reads as empty because a request is in flight is the
  // same not-yet-measaged-is-not-zero mistake the health panel makes.
  const [formats, setFormats] = useState(null)

  const loadFormats = async () => {
    try {
      const res = await getEvidenceFormats()
      setFormats(res.data)
    } catch (e) {
      // Leave it null. The upload path does not depend on this: the picker
      // simply stays unfiltered and the server remains the authority, so a
      // failed request must not block uploading evidence.
      console.warn('Could not load accepted evidence formats', e)
    }
  }

  const loadEvidence = async () => {
    try {
      // Both lists in one request. The server hides archived items by
      // default; asking for them here means the toggle can state an exact
      // count, and that count is derived from the same rows the list renders
      // rather than from a second query that could disagree with it.
      const res = await getEvidence(caseId, true)
      const all = Array.isArray(res.data) ? res.data : []
      setEvidence(all.filter(ev => ev.status !== 'Archived'))
      setArchived(all.filter(ev => ev.status === 'Archived'))
    } catch (e) {
      toast.error(apiErrorMessage(e, 'Failed to load evidence'))
    }
  }

  const handleUpload = async (files) => {
    if (!files || files.length === 0) return
    setUploading(true)
    try {
      if (files.length === 1) {
        const formData = new FormData()
        formData.append('file', files[0])
        await uploadEvidence(caseId, formData)
        toast.success(`Uploaded ${files[0].name}`)
      } else {
        const formData = new FormData()
        for (let i = 0; i < files.length; i++) {
          formData.append('files', files[i])
        }
        await uploadMultiEvidence(caseId, formData)
        // Not "combined": the endpoint combines split disk-image segments
        // and stores everything else individually, so claiming a merge here
        // would misdescribe three logs turned into one evidence item.
        toast.success(`Uploaded ${files.length} file${files.length === 1 ? '' : 's'}`)
      }
      loadEvidence()
    } catch (e) {
      const d = e.response?.data?.detail;
      const msg = typeof d === 'string' ? d : (d?.detail || (Array.isArray(d) ? d[0]?.msg : 'Upload failed'));
      toast.error(msg)
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const handleArchive = async (ev) => {
    try {
      await archiveEvidence(caseId, ev.id)
      toast.success('Evidence archived')
      setConfirmArchive(null)
      loadEvidence()
    } catch (e) {
      // A bare 'Failed to archive' turns three different outcomes into the
      // same four words: no permission, an ingestion job still running, and
      // an aborted search-index cleanup all read as a failed click. The
      // server explains each of them, so the reason is shown.
      toast.error(apiErrorMessage(e, 'Failed to archive'), { duration: 6000 })
      setConfirmArchive(null)
    }
  }

  const handleRestore = async (ev) => {
    setRestoring(prev => ({ ...prev, [ev.id]: true }))
    try {
      const res = await restoreEvidence(caseId, ev.id)
      // Use the server's wording. The restore deliberately does NOT bring the
      // search index back, and saying "restored" on its own would imply it did.
      toast.success(res?.data?.message || 'Evidence restored', { duration: 7000 })
      setConfirmRestore(null)
      loadEvidence()
    } catch (e) {
      toast.error(apiErrorMessage(e, 'Failed to restore'), { duration: 6000 })
    } finally {
      setRestoring(prev => {
        const next = { ...prev }
        delete next[ev.id]
        return next
      })
    }
  }

  const handleVerify = async (id) => {
    setVerifying(prev => ({ ...prev, [id]: true }))
    try {
      const res = await verifyEvidence(caseId, id)
      setVerifyResult(prev => ({ ...prev, [id]: res.data }))
      toast.success('Verification complete')
    } catch (e) {
      toast.error('Verification failed')
    } finally {
      setVerifying(prev => ({ ...prev, [id]: false }))
    }
  }

  // Currently unwired: QueueModal exposes no estimate control, so nothing
  // calls this. It is kept because the endpoint exists and the estimator is
  // genuinely useful, and it now takes the same arguments as
  // handleAddToQueue so that wiring it up cannot reintroduce the bug below.
  //
  // What the bug was: this read `queueConfig[ev.id]`, and there is no
  // `queueConfig` anywhere in the file. The per-evidence settings do not
  // live in a map at all - QueueModal holds them as local state and passes
  // them to onQueue. So the first line of this function would have thrown a
  // ReferenceError, been caught by the catch below, and shown the user
  // "Failed to estimate time" for a request that was never sent. It never
  // fired only because nothing calls it, which means it was dead code
  // guarding a guaranteed crash: correct-looking, impossible to reach, and
  // wrong the moment someone added the button it was written for.
  const handleEstimate = async (ev, cpu, ingestionMode) => {
    setEstimating(prev => ({ ...prev, [ev.id]: true }))
    try {
      // Limits omitted here are filled from the live device budget
      // server-side, so the estimate reflects this machine rather than a
      // stale default.
      const res = await estimateTime(
        [ev.id],
        cpu ?? null,
        ingestionMode ?? null
      )
      const files = res.data.files || res.data.estimates || []
      const est = Array.isArray(files)
        ? (files[0] || { human_readable: 'Unknown' })
        : (res.data.estimates[ev.id] || { human_readable: 'Unknown' })
      setEstimates(prev => ({ ...prev, [ev.id]: est }))
    } catch (e) {
      // Distinguishes "we could not ask" from "we asked and there is no
      // estimate", and says which - the same measured/could-not-measure
      // split the rest of this pass has been applying.
      setEstimateError(prev => ({
        ...prev,
        [ev.id]: apiErrorMessage(e, 'Could not reach the server for a time estimate')
      }))
      toast.error(apiErrorMessage(e, 'Failed to estimate time'))
    } finally {
      setEstimating(prev => ({ ...prev, [ev.id]: false }))
    }
  }

  const handleAddToQueue = async (ev, cpu, ram, ingestionMode) => {
    setAddingToQueue(prev => ({ ...prev, [ev.id]: true }))
    try {
      const res = await addToQueue({
        evidence_id: ev.id,
        case_id: caseId,
        cpu_throttle_percent: cpu,
        min_free_ram_mb: Math.round(ram * 1024),
        ingestion_mode: ingestionMode,
        priority: 1
      })
      const modeLabel = res.data?.ingestion_mode || ingestionMode
      const warn = res.data?.mode_warnings || []
      toast.success(
        warn.length
          ? `Queued as "${modeLabel}" — ${warn.join(' ')}`
          : `Queued as "${modeLabel}"`
      )
      loadEvidence()
      loadQueue()
      loadHistory()
      setQueuingEv(null)
    } catch (e) {
      const d = e.response?.data?.detail;
      const msg = typeof d === 'string' ? d : (d?.detail || (Array.isArray(d) ? d[0]?.msg : 'Failed to queue'));
      toast.error(msg)
    } finally {
      setAddingToQueue(prev => ({ ...prev, [ev.id]: false }))
    }
  }

  useEffect(() => {
    loadEvidence()
  }, [caseId])

  // Accepted formats do not vary per case, so this is fetched once.
  useEffect(() => {
    loadFormats()
  }, [])

  // --- QUEUE LOGIC ---
  const [queue, setQueue]           = useState([])
  const [history, setHistory]       = useState([])
  const [showHistory, setShowHistory] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [liveProgress, setLiveProgress] = useState({})
  const [editingJob, setEditingJob] = useState(null)   // job being settings-edited
  const [overrideJobs, setOverrideJobs] = useState({}) // jobId -> bool (local UI state)
  const [stoppingJobs, setStoppingJobs] = useState({}) // jobId -> bool

  useEffect(() => {
  }, [])

  useWebSocket('/ws/global', useCallback((data) => {
    if (data.type === 'INGESTION_COMPLETE' || data.type === 'INGESTION_FAILED') {
      loadQueue()
      loadHistory()
      if (data.job_id) {
        setLiveProgress(prev => { const n = { ...prev }; delete n[data.job_id]; return n })
        setOverrideJobs(prev => { const n = { ...prev }; delete n[data.job_id]; return n })
        setStoppingJobs(prev => { const n = { ...prev }; delete n[data.job_id]; return n })
      }
    } else if (data.type === 'INGESTION_PROGRESS' && data.job_id) {
      setLiveProgress(prev => ({
        ...prev,
        [data.job_id]: {
          percent: data.percent ?? prev[data.job_id]?.percent ?? 0,
          step:    data.step    ?? prev[data.job_id]?.step    ?? '',
        }
      }))
    }
  }, []))

  const loadAll = async () => {
    // Hardware telemetry is fetched by <ResourceMonitor />, which owns its
    // own polling and respects the Preferences toggle. This only covers the
    // queue data the page itself renders.
    await Promise.all([loadQueue(), loadHistory()])
  }

  const loadQueue = async () => {
    try {
      const res = await getQueue()
      setQueue(Array.isArray(res.data) ? res.data : [])
      setQueueLoadError(null)
    } catch (e) {
      // Was a bare `catch {}`, which left `queue` at its previous value.
      // On the very first load that previous value is `[]`, and the panel
      // below renders "No active jobs" from it. So a backend that was down
      // — or slow, or restarting — displayed a confidently empty queue: an
      // investigator would conclude nothing was ingesting and nothing was
      // wrong, while a job could have been running the whole time. Same
      // class as the rest of this pass: an unmeasured value rendered as a
      // measured one.
      setQueueLoadError(
        apiErrorMessage(e, 'Could not load the ingestion queue'))
    }
  }

  const loadHistory = async () => {
    setLoadingHistory(true)
    try {
      const res = await getQueueHistory()
      setHistory(Array.isArray(res.data) ? res.data : [])
      setHistoryLoadError(null)
    } catch (e) {
      setHistoryLoadError(
        apiErrorMessage(e, 'Could not load the queue history'))
    }
    finally { setLoadingHistory(false) }
  }

  const handleCancel = async (jobId) => {
    try {
      await cancelJob(jobId)
      await loadQueue()
      toast.success('Job cancelled')
    } catch (e) {
      const d = e.response?.data?.detail;
      const msg = typeof d === 'string' ? d : (d?.detail || (Array.isArray(d) ? d[0]?.msg : 'Cancel failed'));
      toast.error(msg)
    }
  }

  const handleForceStart = async (jobId) => {
    try {
      await forceStartJob(jobId)
      setOverrideJobs(prev => ({ ...prev, [jobId]: true }))
      toast.success('Force-start activated — resource limits bypassed')
      await loadQueue()
    } catch (e) {
      const d = e.response?.data?.detail;
      const msg = typeof d === 'string' ? d : (d?.detail || (Array.isArray(d) ? d[0]?.msg : 'Force-start failed'));
      toast.error(msg)
    }
  }

  const handleStop = async (jobId) => {
    try {
      setStoppingJobs(prev => ({ ...prev, [jobId]: true }))
      await stopJob(jobId)
      toast.success('Stop signal sent — job will halt after current batch')
      setTimeout(loadQueue, 1500)
    } catch (e) {
      setStoppingJobs(prev => { const n = { ...prev }; delete n[jobId]; return n })
      const d = e.response?.data?.detail;
      const msg = typeof d === 'string' ? d : (d?.detail || (Array.isArray(d) ? d[0]?.msg : 'Stop failed'));
      toast.error(msg)
    }
  }

  const handleRefresh = async () => {
    toast.success('Refreshed')
  }

  const running = queue.filter(j => j.status === 'Running')
  const waiting = queue.filter(j => j.status === 'Queued')

  const mergeProgress = (job) => {
    const live = liveProgress[job.id]
    if (!live) return job
    return {
      ...job,
      progress_percent: live.percent ?? job.progress_percent,
      current_step:     live.step    ?? job.current_step,
    }
  }

  useEffect(() => { loadAll(); const qPoll = setInterval(loadAll, 10000); return () => clearInterval(qPoll); }, [caseId])

  return (
    <PageLayout
      title="Evidence & Ingestion"
      subtitle="Manage your evidence files and monitor the ingestion queue."
      fullWidth={true}
    >
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-8 items-start">
        
        {/* MAIN CONTENT AREA: RESOURCES, UPLOAD, EVIDENCE */}
        <div className="xl:col-span-8 space-y-8">
          
          {/* 1. System Resources (Top) - hidden if opted out in Preferences.
                 Shares the hardware spec with the Queue page. */}
          <ResourceMonitor
            extra={(
              <div className="grid grid-cols-2 gap-4 border-t border-line mt-4 pt-4">
                <div>
                  <p className="text-xs text-ink-2 mb-1">Pipeline Activity</p>
                  <p className="text-xl font-bold text-ink-0">
                    {running.length} <span className="text-sm font-normal text-ink-2">active</span>
                  </p>
                </div>
                <div>
                  <p className="text-xs text-ink-2 mb-1">Queue</p>
                  <p className="text-xl font-bold text-ink-0">
                    {waiting.length} <span className="text-sm font-normal text-ink-2">pending</span>
                  </p>
                </div>
              </div>
            )}
          />

          {/* 2. Upload Section (Middle) */}
          <div>
            <div className="flex items-center justify-between mb-4">
               <h2 className="text-lg font-bold text-ink-0 flex items-center gap-2">
                 <UploadCloud size={20} className="text-accent" /> Upload Evidence
               </h2>
               <button
                 onClick={() => setShowFormats(!showFormats)}
                 className="flex items-center gap-1.5 text-xs text-ink-2 hover:text-accent transition-colors"
               >
                 <Info size={12} /> {showFormats ? 'Hide formats' : 'Supported formats'}
               </button>
            </div>
            
            {showFormats && (
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-2 mb-5">
                {!formats ? (
                  <div className="md:col-span-4 text-xs text-ink-2">
                    Loading supported formats…
                  </div>
                ) : formats.groups.map(group => {
                  const { icon: Icon, color } = GROUP_STYLE[group.icon] || DEFAULT_GROUP_STYLE
                  return (
                    <div key={group.key} className="bg-surface-2 border border-line rounded-xl p-3 flex gap-3">
                      <Icon size={18} className={`${color} shrink-0 mt-0.5`} />
                      <div className="min-w-0">
                        <p className="text-xs font-semibold text-ink-0">{group.label}</p>
                        <p className="text-[10px] text-ink-2 leading-tight mt-0.5 break-words">
                          {group.extensions_label}
                        </p>
                        <p className="text-[10px] text-ink-2 leading-tight mt-1">{group.description}</p>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}

            <div
              id="drop-zone"
              onDragOver={e => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={() => setDragOver(false)}
              onDrop={e => {
                e.preventDefault()
                setDragOver(false)
                if (e.dataTransfer.files.length > 0) {
                  handleUpload(e.dataTransfer.files)
                }
              }}
              onClick={() => fileRef.current?.click()}
              className={`w-full border-2 border-dashed rounded-2xl py-16 px-8 flex flex-col items-center justify-center text-center cursor-pointer transition-all
                ${dragOver ? 'border-accent bg-accent/10 scale-[1.01]' : 'border-line bg-surface-1 hover:border-accent/50 hover:bg-surface-2'}`}
            >
              <Upload size={40} className="mb-4 text-ink-2" />
              <p className="text-ink-0 font-bold text-lg mb-1">Upload Evidence</p>
              <p className="text-ink-2 text-sm">Drag & drop your files here, or click to browse</p>
              
              <input
                type="file" multiple
                ref={fileRef}
                // From the backend, so the native picker's filter is the
                // same list the server accepts. Undefined until it loads,
                // which leaves the input unfiltered rather than filtering to
                // a guess — the server is the authority either way.
                accept={formats?.accept}
                className="hidden"
                onChange={e => {
                  if (e.target.files.length > 0) handleUpload(e.target.files)
                }}
              />
            </div>

          </div>

          {/* 3. Uploaded Evidence List (Bottom) */}
          <div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-bold text-ink-0 flex items-center gap-2">
                <Database size={20} className="text-accent" /> Evidence Library
              </h2>
              {/* Archiving used to remove nothing, so this count is what tells
                  an investigator their click landed. It is derived from the
                  same response the lists render from, so it cannot disagree. */}
              {archived.length > 0 && (
                <button
                  onClick={() => setShowArchived(s => !s)}
                  className="text-xs font-semibold text-ink-2 hover:text-accent flex items-center gap-1.5 px-2 py-1 rounded-lg hover:bg-surface-2 transition-colors"
                >
                  {showArchived ? <EyeOff size={13} /> : <Eye size={13} />}
                  {showArchived ? 'Hide' : 'Show'} archived ({archived.length})
                </button>
              )}
            </div>
            <div className="space-y-4">
              {evidence.map(ev => {
                const Icon = getFileIcon(ev.original_filename);
                
                const rawJob = running.find(j => j.evidence_id === ev.id) || 
                               waiting.find(j => j.evidence_id === ev.id) || 
                               history.find(j => j.evidence_id === ev.id);
                const job = rawJob ? mergeProgress(rawJob) : null;
                const isProcessing = job && (job.status === 'Running' || job.status === 'Queued');
                const isCompleted = (job && job.status === 'Completed') || ev.status === 'Indexed';

                return (
                  <div key={ev.id} className="bg-surface-1 border border-line rounded-xl overflow-hidden hover:border-accent/30 transition-colors shadow-sm">
                    <div className="p-4 flex flex-col lg:flex-row lg:items-center justify-between gap-4">
                       <div className="flex items-center gap-3">
                         <div className="p-2 bg-surface-2 rounded-lg border border-line shrink-0">
                           <Icon size={18} className="text-accent" />
                         </div>
                         <div>
                           <p className="font-semibold text-ink-0 text-sm">
                             {ev.original_filename}
                           </p>
                           <p className="text-xs text-ink-2 mt-0.5">
                             {formatBytes(ev.file_size_bytes)} · Uploaded by {ev.ingested_by}
                           </p>
                         </div>
                       </div>
                       
                       <div className="flex flex-col sm:flex-row sm:items-center gap-4">
                         {!isProcessing && !isCompleted && (
                           <button
                             onClick={() => setQueuingEv(ev)}
                             disabled={addingToQueue[ev.id]}
                             className="text-xs font-bold bg-accent text-white px-3 py-1.5 rounded flex items-center gap-1.5 hover:bg-accent-hover transition-colors disabled:opacity-50"
                           >
                             {addingToQueue[ev.id] ? <Loader size={12} className="animate-spin"/> : <Plus size={12} />} Queue
                           </button>
                         )}
                         <div className="flex items-center gap-3">
                           {statusIcon[job ? job.status : ev.status] || <Clock size={14} className="text-ink-2" />}
                           <Badge label={job ? job.status : ev.status} />
                           {!isProcessing && (
                             <button
                               onClick={() => setConfirmArchive(ev)}
                               className="p-1.5 rounded text-ink-2 hover:bg-surface-2 hover:text-danger transition-colors"
                             >
                               <Archive size={14} />
                             </button>
                           )}
                         </div>
                       </div>
                    </div>
                  {/* Error message banner for failed ingestion */}
                  {ev.status === 'Failed' && ev.error_message && (
                    <div className="px-4 pb-4">
                      <div className="bg-danger/10 border border-danger/30 rounded-lg px-3 py-2 flex items-start gap-2">
                        <AlertCircle size={13} className="text-danger shrink-0 mt-0.5" />
                        <p className="text-[11px] text-danger leading-snug break-words">
                          {ev.error_message}
                        </p>
                      </div>
                    </div>
                  )}
                </div>
                )
              })}
              {evidence.length === 0 && (
                <div className="text-center py-8 border border-dashed border-line rounded-xl text-ink-2 text-sm">
                  No evidence uploaded yet.
                </div>
              )}
            </div>

            {/* ARCHIVED. Not a history log and not a recycle bin: these rows
                are the same evidence, excluded from the active investigation.
                They are reachable and reversible, because an operation that
                cannot be undone should not be one click away on a forensic
                record. */}
            {showArchived && archived.length > 0 && (
              <div className="mt-6 pt-6 border-t border-line">
                <h3 className="text-xs font-bold uppercase tracking-wider text-ink-2 mb-3 flex items-center gap-2">
                  <Archive size={13} /> Archived ({archived.length})
                </h3>
                <div className="space-y-3">
                  {archived.map(ev => (
                    <div
                      key={ev.id}
                      className="bg-surface-2/50 border border-line rounded-xl p-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3"
                    >
                      <div className="min-w-0">
                        <p className="font-semibold text-ink-1 text-sm truncate">
                          {ev.original_filename}
                        </p>
                        <p className="text-xs text-ink-2 mt-0.5">
                          {formatBytes(ev.file_size_bytes)} · uploaded by {ev.ingested_by}
                          {' · '}
                          out of the active investigation
                        </p>
                      </div>
                      <button
                        onClick={() => setConfirmRestore(ev)}
                        disabled={restoring[ev.id]}
                        className="text-xs font-bold bg-accent text-white px-3 py-1.5 rounded flex items-center gap-1.5 hover:bg-accent-hover transition-colors disabled:opacity-50 shrink-0"
                      >
                        {restoring[ev.id]
                          ? <Loader size={12} className="animate-spin" />
                          : <ArchiveRestore size={12} />}
                        Restore
                      </button>
                    </div>
                  ))}
                </div>
                <p className="text-xs text-ink-2 mt-3">
                  The file is still on disk. Restoring returns it as
                  <span className="text-ink-1 font-semibold"> Uploaded</span> —
                  its search index was deleted when it was archived, so queue
                  it again to make it searchable.
                </p>
              </div>
            )}
          </div>
        </div>
        {/* RIGHT SIDEBAR: INGESTION QUEUE */}
        <div className="xl:col-span-4 bg-surface-1 rounded-2xl p-6 border border-line shadow-sm flex flex-col h-max">
          <div className="flex items-center justify-between mb-6 sticky top-0 bg-surface-1 pt-2 pb-4 z-10 backdrop-blur-sm">
            <div className="flex items-center gap-2">
              <Zap size={22} className="text-accent" />
              <h2 className="text-lg font-bold text-ink-0">Ingestion Queue</h2>
            </div>
            <button onClick={loadAll} className="p-1.5 bg-surface-3 hover:bg-surface-1 text-ink-2 hover:text-accent rounded transition-colors" title="Refresh Queue">
              <RefreshCw size={14} />
            </button>
          </div>
          
          {/* Settings modal */}
          {editingJob && (
            <EditSettingsModal
              job={editingJob}
              onClose={() => setEditingJob(null)}
              onSaved={loadQueue}
            />
          )}

          {/* Currently Processing */}
          <div className="mb-8">
            <h3 className="text-sm font-semibold text-ink-1 uppercase tracking-wider mb-4 flex items-center justify-between">
              Currently Processing
              <span className="bg-surface-3 text-ink-0 py-0.5 px-2 rounded-full text-xs">{running.length}</span>
            </h3>
            <div className="space-y-3">
              {running.length === 0 ? (
                queueLoadError ? (
                  /* A failed check, not a measured zero. "No active jobs" is
                     a real answer from the server; this means we never got
                     to ask. The badge above still reads 0 because there is
                     genuinely nothing in the local list to count - so the
                     count is the one figure on screen that a failure could
                     have changed, and it is stated as unmeasured here. */
                  <p className="text-sm text-warning bg-surface-1 p-3 rounded-lg border border-warning/40">
                    Could not load the queue — status unknown. {queueLoadError}
                  </p>
                ) : (
                  <p className="text-sm text-ink-2 italic bg-surface-1 p-3 rounded-lg border border-line border-dashed">No active jobs</p>
                )
              ) : (
                running.map(job => (
                  <div key={job.id} className="bg-surface-1 border border-accent/30 rounded-xl p-3 shadow-[0_0_15px_rgba(var(--accent),0.1)] relative overflow-hidden group">
                    <div className="flex justify-between items-start mb-2 gap-2">
                      <p className="font-semibold text-ink-0 text-sm truncate" title={job.original_filename}>
                        {job.original_filename}
                      </p>
                      <button
                        onClick={() => handleStop(job.id)}
                        disabled={stoppingJobs[job.id]}
                        className="flex items-center gap-1 text-[10px] font-bold bg-danger/10 text-danger hover:bg-danger hover:text-white px-2 py-1 rounded transition-colors shrink-0"
                      >
                        <X size={12} /> Stop
                      </button>
                    </div>
                    <div className="mb-2">
                      <p className="text-[10px] text-ink-2 uppercase font-mono mb-1">{job.current_step || 'Processing...'}</p>
                      <ProgressBar percent={job.progress_percent} status="Running" />
                    </div>
                    <div className="flex justify-between items-center text-xs text-ink-2">
                      <span className="flex items-center gap-1.5">
                        <span className="px-1.5 py-0.5 rounded bg-accent/15 text-accent font-semibold">
                          {job.ingestion_mode || 'normal'}
                        </span>
                        <span>{job.cpu_throttle_percent}% CPU</span>
                      </span>
                      <span>{(job.min_free_ram_mb / 1024).toFixed(1)}GB RAM floor</span>
                    </div>
                    {/* Why a job is not moving, when the governor is holding
                        it back. Without this a throttled job just looks
                        broken, because the percent is legitimately frozen. */}
                    {job.governor?.reason && (
                      <p className="text-[10px] text-warning mt-1.5 flex items-start gap-1">
                        <AlertCircle size={10} className="shrink-0 mt-px" />
                        <span>
                          Throttled: {job.governor.reason}
                          {job.governor.ram_pauses > 0 && ` · ${job.governor.ram_pauses} RAM wait(s)`}
                        </span>
                      </p>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Pending Ingestion */}
          <div className="mb-8">
            <h3 className="text-sm font-semibold text-ink-1 uppercase tracking-wider mb-4 flex items-center justify-between">
              Pending
              <span className="bg-surface-3 text-ink-0 py-0.5 px-2 rounded-full text-xs">{waiting.length}</span>
            </h3>
            <div className="space-y-3">
              {waiting.length === 0 ? (
                <p className="text-sm text-ink-2 italic bg-surface-1 p-3 rounded-lg border border-line border-dashed">Queue is empty</p>
              ) : (
                waiting.map((job, index) => (
                  <div key={job.id} className="bg-surface-1 border border-line rounded-xl p-3 relative group hover:border-accent/50 transition-colors">
                    <div className="absolute -left-2.5 top-1/2 -translate-y-1/2 w-5 h-5 bg-surface-3 rounded-full flex items-center justify-center text-[10px] font-bold text-ink-1 border border-line">
                      {index + 1}
                    </div>
                    <div className="ml-2 flex justify-between items-center">
                      <div className="overflow-hidden">
                        <p className="font-semibold text-ink-0 text-sm truncate" title={job.original_filename}>
                          {job.original_filename}
                        </p>
                        <p className="text-xs text-ink-2 mt-0.5">
                          {formatBytes(job.file_size_bytes)}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => setEditingJob(job)}
                          className="flex items-center gap-1 text-[10px] font-bold bg-surface-2 text-ink-2 hover:text-accent hover:bg-surface-3 px-2 py-1 rounded transition-colors"
                        >
                          <Settings size={12} /> Edit
                        </button>
                        <button
                          onClick={() => handleForceStart(job.id)}
                          disabled={overrideJobs[job.id]}
                          className="flex items-center gap-1 text-[10px] font-bold bg-success/10 text-success hover:bg-success hover:text-white px-2 py-1 rounded transition-colors shrink-0"
                        >
                          <Play size={12} /> Force
                        </button>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Queue History */}
          <div>
            <h3 className="text-sm font-semibold text-ink-1 uppercase tracking-wider mb-4 flex items-center justify-between">
              History
            </h3>
            <div className="space-y-2">
              {historyLoadError ? (
                /* Same distinction as the queue above. A bare `.map` with no
                   else-branch renders a bare heading over nothing, which is
                   indistinguishable from "nothing has ever been ingested
                   here" - a claim this page used to make implicitly on every
                   failed request. */
                <p className="text-sm text-warning bg-surface-1 p-3 rounded-lg border border-warning/40">
                  Could not load history — {historyLoadError}
                </p>
              ) : history.length === 0 ? (
                <p className="text-sm text-ink-2 italic bg-surface-1 p-3 rounded-lg border border-line border-dashed">
                  No ingestion history yet
                </p>
              ) : null}
              {history.map(job => {
                const ev = evidence.find(e => e.id === job.evidence_id)
                const filename = ev ? ev.original_filename : (job.evidence_id || 'Unknown File')
                
                return (
                  <div key={job.id} className="flex items-center justify-between p-2 rounded-lg hover:bg-surface-1 transition-colors group">
                    <div className="flex items-center gap-2 overflow-hidden">
                      {statusIcon[job.status] || <Clock size={14} className="text-ink-2 shrink-0" />}
                      <p className="text-xs text-ink-0 truncate max-w-[150px]" title={filename}>
                        {filename}
                      </p>
                    </div>
                    <span className="text-[10px] text-ink-2 whitespace-nowrap">
                      {job.completed_at 
                        ? fromUtc(job.completed_at).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})
                        : (job.updated_at ? fromUtc(job.updated_at).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) : '—')}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        </div>

      </div>
      
      <ConfirmDialog
        isOpen={!!confirmArchive}
        title="Archive Evidence"
        message={`Archive "${confirmArchive?.original_filename}"? This removes it from active investigations. The file is kept on disk but AI queries will no longer return its content.`}
        confirmLabel="Archive"
        confirmClassName="bg-danger hover:bg-red-600 text-white"
        onConfirm={() => handleArchive(confirmArchive)}
        onCancel={() => setConfirmArchive(null)}
      />

      <ConfirmDialog
        isOpen={!!confirmRestore}
        title="Restore Evidence"
        message={`Restore "${confirmRestore?.original_filename}" to the active investigation? Its search index was deleted when it was archived, so it will come back as "Uploaded" and need queueing again to be searchable.`}
        confirmLabel="Restore"
        onConfirm={() => handleRestore(confirmRestore)}
        onCancel={() => setConfirmRestore(null)}
      />

      {queuingEv && (
        <QueueModal
          ev={queuingEv}
          onClose={() => setQueuingEv(null)}
          onQueue={(cpu, ram, ingestionMode) => handleAddToQueue(queuingEv, cpu, ram, ingestionMode)}
        />
      )}
    </PageLayout>

  )
}

