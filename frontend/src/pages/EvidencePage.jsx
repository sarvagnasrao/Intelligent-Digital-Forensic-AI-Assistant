import React, { useState, useEffect, useRef, useCallback } from "react"
import { useParams, useNavigate } from "react-router-dom"
import {
  Upload, File, FileText,
  Database, Music, Video,
  Image, Mail, Table,
  CheckCircle, Clock,
  AlertCircle, RefreshCw,
  Info, Shield, Archive,
  Play, Loader, X, Cpu,
  ChevronDown, ChevronUp,
  Zap, Activity, ChevronRight, Square,
  Zap as ZapIcon, Sliders, Save, MemoryStick, HardDrive,
  UploadCloud, Settings, Plus, User
} from "lucide-react"
import {
  getEvidence, uploadEvidence,
  getEvidenceItem, archiveEvidence,
  verifyEvidence,
  addToQueue, estimateTime,
  getStorageStats,
  getQueue, getQueueHistory, cancelJob,
  forceStartJob, stopJob, updateJobSettings
} from "../api/client"
import Badge from "../components/Badge"
import ConfirmDialog from "../components/ConfirmDialog"
import PageLayout from "../components/PageLayout"
import ResourceMonitor from "../components/ResourceMonitor"
import toast from "react-hot-toast"
import { formatDistanceToNow } from "date-fns"
import { fromUtc } from '../utils/time'
import useWebSocket from "../hooks/useWebSocket"

// ── Supported format groups ────────────────────────────────
const FILE_GROUPS = [
  {
    label: 'Forensic Images',
    icon: Database,
    color: 'text-accent',
    exts: '.E01 .001 .dd .raw .img',
    desc: 'Full disk image ingestion via pytsk3 — extracts all files inside the image'
  },
  {
    label: 'Documents',
    icon: FileText,
    color: 'text-blue-400',
    exts: '.pdf .txt .docx .doc',
    desc: 'Text extraction with full content indexing'
  },
  {
    label: 'Spreadsheets & Slides',
    icon: Table,
    color: 'text-green-400',
    exts: '.xlsx .xls .pptx .ppt',
    desc: 'Cell data and slide text extracted and indexed'
  },
  {
    label: 'Audio',
    icon: Music,
    color: 'text-purple-400',
    exts: '.mp3 .wav .m4a .flac .ogg .aac',
    desc: 'Transcribed via Whisper (local AI) — no cloud required'
  },
  {
    label: 'Video',
    icon: Video,
    color: 'text-pink-400',
    exts: '.mp4 .avi .mov .mkv .wmv',
    desc: 'Metadata extracted + audio track transcribed via Whisper'
  },
  {
    label: 'Images',
    icon: Image,
    color: 'text-yellow-400',
    exts: '.jpg .jpeg .png .tiff .bmp',
    desc: 'OCR (text in images) + EXIF metadata (GPS, camera, date)'
  },
  {
    label: 'Email',
    icon: Mail,
    color: 'text-orange-400',
    exts: '.eml .msg',
    desc: 'Headers, body, sender, recipient, date all extracted'
  },
]

// ── Per-extension icon map ─────────────────────────────────
const EXT_ICON = {
  '.pdf':  FileText, '.txt':  FileText,
  '.docx': FileText, '.doc':  FileText,
  '.xlsx': Table,    '.xls':  Table,
  '.pptx': FileText, '.ppt':  FileText,
  '.mp3':  Music,    '.wav':  Music,
  '.m4a':  Music,    '.flac': Music,
  '.ogg':  Music,    '.aac':  Music,
  '.mp4':  Video,    '.avi':  Video,
  '.mov':  Video,    '.mkv':  Video,
  '.wmv':  Video,
  '.jpg':  Image,    '.jpeg': Image,
  '.png':  Image,    '.tiff': Image,
  '.bmp':  Image,
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
  'Failed': <AlertCircle size={14} className="text-danger" />
}

const ACCEPT_STRING =
  '.pdf,.txt,.docx,.doc,' +
  '.xlsx,.xls,.pptx,.ppt,' +
  '.mp3,.wav,.m4a,.flac,.ogg,.aac,' +
  '.mp4,.avi,.mov,.mkv,.wmv,' +
  '.jpg,.jpeg,.png,.tiff,.bmp,' +
  '.eml,.msg,.e01,.001,.dd,.raw,.img'

function getFileIcon(filename) {
  if (!filename) return File
  const ext = '.' + filename.split('.').pop().toLowerCase()
  return EXT_ICON[ext] || File
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

// ── Queue Settings Modal ────────────────────────────────────
function QueueModal({ ev, onClose, onQueue }) {
  const [cpu, setCpu]     = useState(95)
  const [ram, setRam]     = useState(0.5)
  const [saving, setSaving] = useState(false)

  const handleQueue = async () => {
    setSaving(true)
    await onQueue(cpu, ram)
    setSaving(false)
  }

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-surface-2 border border-line rounded-2xl w-full max-w-sm shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-line">
          <div className="flex items-center gap-2">
            <Sliders size={16} className="text-accent" />
            <h2 className="text-sm font-semibold text-ink-0">Queue Ingestion</h2>
          </div>
          <button onClick={onClose} className="text-ink-2 hover:text-ink-0 transition-colors">
            <X size={16} />
          </button>
        </div>

        <div className="p-5 space-y-5">
          <div className="flex items-center gap-2 bg-surface-1 rounded-lg px-3 py-2">
            <p className="text-xs text-ink-0 truncate" title={ev.original_filename}>
              Queueing: <span className="font-semibold">{ev.original_filename}</span>
            </p>
          </div>

          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs font-semibold text-ink-0 flex items-center gap-1.5">
                <Cpu size={12} className="text-accent" /> CPU Throttle
              </label>
              <span className={`text-sm font-bold tabular-nums ${cpu >= 80 ? 'text-warning' : cpu >= 50 ? 'text-accent' : 'text-success'}`}>{cpu}%</span>
            </div>
            <input type="range" min="10" max="100" step="5" value={cpu} onChange={e => setCpu(Number(e.target.value))} className="w-full accent-violet-500" />
            <div className="flex justify-between text-[10px] text-ink-2 mt-0.5"><span>10%</span><span>50%</span><span>100%</span></div>
          </div>

          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs font-semibold text-ink-0 flex items-center gap-1.5">
                <MemoryStick size={12} className="text-accent" /> Min Free RAM
              </label>
              <span className={`text-sm font-bold tabular-nums ${ram < 1 ? 'text-danger' : ram < 2 ? 'text-warning' : 'text-success'}`}>{ram} GB</span>
            </div>
            <input type="range" min="0" max="8" step="0.5" value={ram} onChange={e => setRam(Number(e.target.value))} className="w-full accent-violet-500" />
            <div className="flex justify-between text-[10px] text-ink-2 mt-0.5"><span>0 GB</span><span>2 GB</span><span>8 GB</span></div>
          </div>
        </div>

        <div className="flex gap-2 px-5 pb-5">
          <button onClick={onClose} className="flex-1 py-2 rounded-lg border border-line text-xs text-ink-2 hover:text-ink-0 transition-colors">Cancel</button>
          <button onClick={handleQueue} disabled={saving} className="flex-1 py-2 rounded-lg bg-accent hover:bg-accent/90 text-white text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors disabled:opacity-50">
            {saving ? <Loader size={12} className="animate-spin" /> : <Plus size={12} />} Queue Job
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Edit Settings Modal ────────────────────────────────────
function EditSettingsModal({ job, onClose, onSaved }) {
  const [cpu, setCpu]     = useState(job.cpu_throttle_percent ?? 70)
  const [ram, setRam]     = useState(Math.round((job.min_free_ram_mb ?? 2048) / 1024 * 10) / 10)
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    setSaving(true)
    try {
      await updateJobSettings(job.id, {
        cpu_throttle_percent: cpu,
        min_free_ram_mb:      Math.round(ram * 1024),
      })
      toast.success(`Settings updated — CPU ${cpu}%, RAM floor ${ram} GB`)
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

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-surface-2 border border-line rounded-2xl w-full max-w-sm shadow-2xl">
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

        <div className="p-5 space-y-5">
          {/* Status badge */}
          <div className="flex items-center gap-2 bg-surface-1 rounded-lg px-3 py-2">
            <span className={`w-2 h-2 rounded-full shrink-0 ${job.status === 'Running' ? 'bg-accent animate-pulse' : 'bg-warning'}`} />
            <p className="text-xs text-ink-2">
              <span className="font-medium text-ink-0">{job.status}</span>
              {job.status === 'Running' && ' — changes apply on next batch check'}
              {job.status === 'Queued'  && ' — changes apply when job starts'}
            </p>
          </div>

          {/* CPU slider */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs font-semibold text-ink-0 flex items-center gap-1.5">
                <Cpu size={12} className="text-accent" /> CPU Throttle
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
              type="range" min="0" max="8" step="0.5"
              value={ram}
              onChange={e => setRam(Number(e.target.value))}
              className="w-full accent-violet-500"
            />
            <div className="flex justify-between text-[10px] text-ink-2 mt-0.5">
              <span>0 GB (override)</span>
              <span>2 GB (safe)</span>
              <span>8 GB (cautious)</span>
            </div>
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
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [investigator, setInvestigator] = useState('Investigator')
  const [includeDeleted, setIncludeDeleted] = useState(false)
  const [showFormats, setShowFormats] = useState(false)
  const [confirmArchive, setConfirmArchive] = useState(null)
  const [verifyResult, setVerifyResult] = useState({})
  const [verifying, setVerifying] = useState({})
  const fileRef = useRef()
  const pollRef = useRef({})

  // Queue state
  const [queuingEv, setQueuingEv] = useState(null)
  const [estimates, setEstimates] = useState({})
  const [addingToQueue, setAddingToQueue] = useState({})

  // Storage stats
  const [storageStats, setStorageStats] = useState(null)

  const loadEvidence = async () => {
    try {
      const res = await getEvidence(caseId)
      setEvidence(Array.isArray(res.data) ? res.data : [])
    } catch (e) {
      toast.error('Failed to load evidence')
    }
  }

  const handleUpload = async (file) => {
    if (!file) return
    setUploading(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('ingested_by', investigator)
      await uploadEvidence(caseId, formData)
      toast.success(`Uploaded ${file.name}`)
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
      toast.error('Failed to archive')
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

  const handleEstimate = async (ev) => {
    try {
      const cpu = queueConfig[ev.id]?.cpu_throttle_percent || 70
      const res = await estimateTime([ev.id], cpu)
      setEstimates(prev => ({
        ...prev,
        [ev.id]: res.data.estimates[ev.id] || { human_readable: 'Unknown' }
      }))
    } catch (e) {
      toast.error('Failed to estimate time')
    }
  }

  const handleAddToQueue = async (ev, cpu, ram) => {
    setAddingToQueue(prev => ({ ...prev, [ev.id]: true }))
    try {
      await addToQueue({
        evidence_id: ev.id,
        case_id: caseId,
        cpu_throttle_percent: cpu,
        min_free_ram_mb: Math.round(ram * 1024),
        priority: 1
      })
      toast.success('Added to queue')
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
    } catch {}
  }

  const loadHistory = async () => {
    setLoadingHistory(true)
    try {
      const res = await getQueueHistory()
      setHistory(Array.isArray(res.data) ? res.data : [])
    } catch {}
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
                {FILE_GROUPS.map(group => (
                  <div key={group.label} className="bg-surface-2 border border-line rounded-xl p-3 flex gap-3">
                    <group.icon size={18} className={`${group.color} shrink-0 mt-0.5`} />
                    <div>
                      <p className="text-xs font-semibold text-ink-0">{group.label}</p>
                      <p className="text-[10px] text-ink-2 leading-tight mt-0.5">{group.exts}</p>
                    </div>
                  </div>
                ))}
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
                  handleUpload(e.dataTransfer.files[0])
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
                type="file"
                ref={fileRef}
                className="hidden"
                onChange={e => {
                  if (e.target.files.length > 0) handleUpload(e.target.files[0])
                }}
              />
            </div>

          </div>

          {/* 3. Uploaded Evidence List (Bottom) */}
          <div>
            <h2 className="text-lg font-bold text-ink-0 mb-4 flex items-center gap-2"><Database size={20} className="text-accent" /> Evidence Library</h2>
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
                  </div>
                )
              })}
              {evidence.length === 0 && (
                <div className="text-center py-8 border border-dashed border-line rounded-xl text-ink-2 text-sm">
                  No evidence uploaded yet.
                </div>
              )}
            </div>
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
                <p className="text-sm text-ink-2 italic bg-surface-1 p-3 rounded-lg border border-line border-dashed">No active jobs</p>
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
                      <span>{job.cpu_throttle_percent}% CPU</span>
                      <span>{(job.min_free_ram_mb / 1024).toFixed(1)}GB RAM</span>
                    </div>
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
      
      {queuingEv && (
        <QueueModal
          ev={queuingEv}
          onClose={() => setQueuingEv(null)}
          onQueue={(cpu, ram) => handleAddToQueue(queuingEv, cpu, ram)}
        />
      )}
    </PageLayout>

  )
}

