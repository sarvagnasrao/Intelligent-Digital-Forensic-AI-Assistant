import React, { useState,
                useEffect,
                useMemo,
                useRef } from 'react'
import { useParams } from 'react-router-dom'
import {
  Send, Bot, User, RefreshCw,
  Trash2, Shield, AlertCircle, EyeOff,
  FileText, Sparkles, ChevronDown,
  X, Download, UserCheck
} from 'lucide-react'
import {
  getQueries, askQuestion,
  deleteQuery, getEvidence,
  generateCaseSummary,
  getLatestSummary,
  apiErrorMessage
} from '../api/client'
import { useAuth } from
  '../context/AuthContext'
import toast from 'react-hot-toast'
import { formatDistanceToNow } from
  'date-fns'
import { fromUtc } from '../utils/time'
import PageLayout from '../components/PageLayout'

// Renders AI response with citations
// Must match EVIDENCE_NOTE_MARKER in backend/modules/rag_engine.py. Both
// sides need it: the backend writes the caveat, this renders it.
const EVIDENCE_CAVEAT_MARKER = 'Evidence caveat:'

function ResponseText({ text }) {
  // The old text here blamed the investigator's question ("Try rephrasing your
  // question"). That advice was guaranteed to fail: the usual cause is a missing
  // model, and no rewording of a question installs one. The backend now names the
  // actual fault; this fallback only covers the case where it returned nothing at
  // all, and it says what to check rather than what to retype.
  if (!text) return (
    <p style={{
      color: 'var(--color-white-2)',
      fontStyle: 'italic',
      fontSize: 12,
    }}>
      The assistant returned no text for this question. Check the System Health
      page - if Ollama is not ready to answer, the model needs pulling
      (&apos;ollama pull llama3.2:3b&apos;).
    </p>
  )

  // Highlight citation markers
  const parts = text.split(
    /(\[Source:[^\]]+\])/g)

  // The backend appends an evidence caveat when retrieval matched more than
  // the model's context window can carry, so only part of what was retrieved
  // reached the model. It is split out and styled as its own block: a limit
  // on the evidence behind a finding must not be rendered in the same voice
  // as the finding, or it reads as part of the conclusion.
  const caveatAt = parts.findIndex(
    (p) => p.includes(EVIDENCE_CAVEAT_MARKER))
  const bodyParts = caveatAt === -1
    ? parts : parts.slice(0, caveatAt)
  const caveat = caveatAt === -1
    ? null
    : parts.slice(caveatAt).join('').trim()

  return (
    <div style={{
      fontSize: 13,
      color: 'rgba(255,255,255,0.75)',
      lineHeight: 1.8,
      whiteSpace: 'pre-wrap',
      wordBreak: 'break-word',
    }}>
      {bodyParts.map((part, i) =>
        part.startsWith('[Source:')
          ? (
            <span key={i} style={{
              fontSize: 10,
              color: '#818cf8',
              background:
                'rgba(99,102,241,0.1)',
              border:
                '1px solid rgba(99,102,241,0.2)',
              borderRadius: 4,
              padding: '1px 6px',
              margin: '0 2px',
              fontFamily: 'monospace',
            }}>
              {part}
            </span>
          ) : (
            <span key={i}>{part}</span>
          )
      )}
      {caveat && (
        <div style={{
          marginTop: 10,
          padding: '8px 10px',
          borderLeft:
            '2px solid rgba(245,158,11,0.5)',
          background:
            'rgba(245,158,11,0.06)',
          borderRadius: '0 4px 4px 0',
          color: 'rgba(253,230,138,0.85)',
          fontSize: 11.5,
          lineHeight: 1.7,
          whiteSpace: 'normal',
        }}>
          {caveat}
        </div>
      )}
    </div>
  )
}

// Summary modal
function SummaryModal({ caseId, onClose }) {
  const [summary, setSummary] =
    useState(null)
  const [loading, setLoading] =
    useState(false)
  const [existing, setExisting] =
    useState(null)

  useEffect(() => {
    loadExisting()
  }, [])

  const loadExisting = async () => {
    try {
      const res = await getLatestSummary(
        caseId)
      if (res.data.has_summary) {
        setExisting(res.data)
        setSummary(res.data.summary)
      }
      setSummaryError(null)
    } catch (e) {
      /* Was `catch {}`. `summary` stays null, which is exactly what the
         server returns for a case that has never been summarised - so a
         failed request and a genuine absence rendered the identical
         "Generate Summary" empty state. Here that is merely unhelpful. In
         the summary block below, the same `null` is the input to a
         "Generate" affordance that invites the investigator to spend a
         model run reproducing a summary that already exists. */
      setSummaryError(apiErrorMessage(
        e, 'Could not check for an existing summary'))
    }
  }

  const handleGenerate = async () => {
    setLoading(true)
    try {
      const res = await generateCaseSummary(
        caseId)
      setSummary(res.data.summary)
      setExisting({
        generated_at:
          res.data.generated_at,
        generated_by:
          res.data.generated_by
      })
      toast.success('Summary generated')
    } catch (e) {
      toast.error(
        e.response?.data?.detail ||
        'Generation failed')
    } finally {
      setLoading(false)
    }
  }

  const handleDownload = () => {
    if (!summary) return
    const blob = new Blob(
      [summary],
      { type: 'text/markdown' })
    const url =
      URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download =
      `case-summary-${
        caseId.slice(0,8)}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  const renderMd = (text) => text
    .replace(/^## (.+)$/gm,
      '<p style="font-size:14px;' +
      'font-weight:700;color:#e2e4f0;' +
      'margin:18px 0 6px;' +
      'padding-bottom:4px;' +
      'border-bottom:1px solid ' +
      'rgba(255,255,255,0.06)">' +
      '$1</p>')
    .replace(/^### (.+)$/gm,
      '<p style="font-size:12px;' +
      'font-weight:600;' +
      'color:#c7d2fe;' +
      'margin:12px 0 4px">$1</p>')
    .replace(/\*\*(.+?)\*\*/g,
      '<strong style="color:#e2e4f0">' +
      '$1</strong>')
    .replace(/^- (.+)$/gm,
      '<div style="display:flex;' +
      'gap:8px;margin:3px 0">' +
      '<span style="color:#6366f1;' +
      'flex-shrink:0">•</span>' +
      '<span>$1</span></div>')
    .replace(/\n/g, '<br/>')

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      background: 'rgba(0,0,0,0.7)',
      zIndex: 50,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: 24,
    }}>
      <div style={{
        background: '#14161f',
        border:
          '1px solid rgba(255,255,255,0.1)',
        borderRadius: 16,
        width: '100%',
        maxWidth: 760,
        maxHeight: '85vh',
        display: 'flex',
        flexDirection: 'column',
        boxShadow:
          '0 25px 60px rgba(0,0,0,0.8)',
      }}>
        {/* Modal header */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '16px 20px',
          borderBottom:
            '1px solid rgba(255,255,255,0.07)',
          flexShrink: 0,
        }}>
          <div>
            <p style={{
              fontSize: 15,
              fontWeight: 600,
              color: 'var(--text-primary)',
            }}>
              Case Intelligence Summary
            </p>
            {existing && (
              <p style={{
                fontSize: 11,
                color: 'var(--color-white-3)',
                marginTop: 2,
              }}>
                Generated{' '}
                {formatDistanceToNow(
                  fromUtc(existing.generated_at),
                  { addSuffix: true }
                )}{' '}
                by {existing.generated_by}
              </p>
            )}
          </div>
          <div style={{
            display: 'flex', gap: 8 }}>
            {summary && (
              <button
                onClick={handleDownload}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 5,
                  padding: '6px 12px',
                  borderRadius: 7,
                  background:
                    'var(--color-white-05)',
                  border:
                    '1px solid rgba(255,255,255,0.09)',
                  color:
                    'var(--color-white-4)',
                  fontSize: 12,
                  cursor: 'pointer',
                }}>
                <Download size={12} />
                .md
              </button>
            )}
            <button
              onClick={handleGenerate}
              disabled={loading}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                padding: '6px 14px',
                borderRadius: 7,
                background: '#4f46e5',
                border: 'none',
                color: 'var(--color-white-full)',
                fontSize: 12,
                fontWeight: 500,
                cursor: loading
                  ? 'not-allowed'
                  : 'pointer',
                opacity: loading ? 0.6 : 1,
              }}>
              {loading
                ? <><RefreshCw size={12}
                    className="animate-spin"/>
                    Generating...</>
                : <><Sparkles size={12} />
                    {summary
                      ? 'Regenerate'
                      : 'Generate'}</>
              }
            </button>
            <button
              onClick={onClose}
              style={{
                padding: 6,
                borderRadius: 7,
                background: 'none',
                border: 'none',
                color:
                  'var(--color-white-4)',
                cursor: 'pointer',
                display: 'flex',
              }}>
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Modal body */}
        <div style={{
          flex: 1,
          overflowY: 'auto',
          padding: '20px 24px',
        }}>
          {loading && !summary && (
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '60px 20px',
              gap: 16,
            }}>
              <div style={{
                width: 48, height: 48,
                borderRadius: 14,
                background:
                  'rgba(99,102,241,0.15)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}>
                <Sparkles size={22}
                  color="#818cf8" />
              </div>
              <div style={{
                textAlign: 'center' }}>
                <p style={{
                  fontSize: 14,
                  color: 'var(--text-primary)',
                  marginBottom: 4,
                }}>
                  Synthesising case intelligence...
                </p>
                <p style={{
                  fontSize: 12,
                  color:
                    'var(--color-white-3)',
                }}>
                  Analysing evidence,
                  entities and findings
                </p>
              </div>
            </div>
          )}

          {!loading && !summary && (
            <div style={{
              textAlign: 'center',
              padding: '60px 20px',
            }}>
              {summaryError ? (
                /* Third state, and the one that used to be missing. Both of
                   the two branches below are true statements: "no summary
                   yet" and "here is what to click". Neither is true when the
                   question was never answered - and on this panel a false
                   "No summary yet" is the costly direction, because it
                   invites the investigator to spend a model run producing a
                   summary that may already exist, and to overwrite it. */
                <>
                  <AlertCircle size={40} style={{
                    margin: '0 auto 14px',
                    color: 'rgba(239,68,68,0.5)',
                  }} />
                  <p style={{
                    fontSize: 13,
                    color: '#f87171',
                    marginBottom: 6,
                  }}>
                    Could not check for a summary
                  </p>
                  <p style={{
                    fontSize: 12,
                    color: 'var(--color-white-2)',
                    maxWidth: 320,
                    margin: '0 auto 14px',
                  }}>
                    {summaryError}. This is not the same as there being
                    none, so nothing has been generated or overwritten.
                  </p>
                  <button
                    onClick={loadExisting}
                    style={{
                      fontSize: 12,
                      color: '#818cf8',
                      background: 'none',
                      border: '1px solid rgba(129,140,248,0.4)',
                      borderRadius: 6,
                      padding: '6px 14px',
                      cursor: 'pointer',
                    }}>
                    Try again
                  </button>
                </>
              ) : (
                <>
                  <FileText size={40} style={{
                    margin: '0 auto 14px',
                    color:
                      'var(--color-white-1)',
                  }} />
                  <p style={{
                    fontSize: 13,
                    color:
                      'var(--color-white-3)',
                    marginBottom: 6,
                  }}>
                    No summary yet
                  </p>
                  <p style={{
                    fontSize: 12,
                    color:
                      'var(--color-white-2)',
                    maxWidth: 300,
                    margin: '0 auto',
                  }}>
                    Click Generate to produce
                    an executive summary of
                    all case evidence and
                    findings
                  </p>
                </>
              )}
            </div>
          )}

          {summary && (
            <div
              style={{
                fontSize: 13,
                color:
                  'rgba(255,255,255,0.65)',
                lineHeight: 1.8,
              }}
              dangerouslySetInnerHTML={{
                __html: renderMd(summary)
              }}
            />
          )}
        </div>
      </div>
    </div>
  )
}

export default function InvestigatePage() {
  const { caseId } = useParams()
  const { user } = useAuth()
  const [queries, setQueries] =
    useState([])
  const [loading, setLoading] =
    useState(false)
  const [loadingHistory, setLoadingHistory] =
    useState(true)
  const [evidence, setEvidence] =
    useState([])
  const [selectedEvidence, setSelectedEvidence] =
    useState('')
  const [showSummary, setShowSummary] =
    useState(false)
  const [hasMoreQueries, setHasMoreQueries] =
    useState(false)
  // Fetch failures, held apart from the data they concern. A failed page
  // load and a genuinely short history must not look the same, and a failed
  // "is there already a summary" check must not look like "there is not".
  const [historyError, setHistoryError] = useState(null)
  const [summaryError, setSummaryError] = useState(null)
  const [queryPage, setQueryPage] =
    useState(1)
  const bottomRef = useRef()
  const textareaRef = useRef()

  // ── Prompt durability ──────────────────────────────────────
  // Two separate things were lost when the investigator moved to
  // another tab, and they are lost for different reasons.
  //
  // 1. An unsent draft. It lived in component state, and changing
  //    route unmounts this page, so it went with it.
  //
  // 2. A question already submitted but still generating. This one
  //    is subtler: the API writes its QueryLog only AFTER
  //    run_rag_query returns (backend/routers/queries.py), so a
  //    question in flight does not exist in the database yet. The
  //    refetch on return could not find a row that had not been
  //    created, so the investigator's own question vanished from
  //    the screen while the model was still working on it.
  //
  // Both are persisted, so the words survive the navigation and the
  // pending question is reconciled against the server once it lands.
  const draftKey = `cfi_draft_${caseId}`
  const PENDING_KEY = 'cfi_pending_questions'
  // A pending entry older than this is assumed lost (the backend
  // died mid-request) rather than polled for ever.
  const PENDING_TTL_MS = 10 * 60 * 1000

  const readPending = (cid) => {
    try {
      const all = JSON.parse(
        localStorage.getItem(PENDING_KEY) || '[]')
      if (!Array.isArray(all)) return []
      const cutoff = Date.now() - PENDING_TTL_MS
      return all.filter(p =>
        p && p.caseId === cid &&
        typeof p.text === 'string' &&
        p.at > cutoff)
    } catch {
      return []
    }
  }

  const writePending = (all) => {
    try {
      localStorage.setItem(
        PENDING_KEY, JSON.stringify(all))
    } catch (e) {
      /* This is a real guard, not sloppiness: private-browsing modes and
         full quotas both throw here, and without a catch the page dies.
         But it was completely silent, and the feature it protects is the
         in-flight-question reconciliation - a failed write means a question
         that vanishes mid-generation is never re-rendered and never
         reconciled. A console warning is the right weight: not a toast
         (these fire from a fire-and-forget write, so a toast would be
         noise the investigator cannot act on) and not silence. */
      console.warn(
        '[investigate] could not persist in-flight questions; ' +
        'they will not survive a reload if it happens now:', e)
    }
  }

  // Mirror for the polling interval, which must not close over a
  // stale snapshot of the list.
  const pendingRef = useRef([])

  const [pending, setPending] = useState(
    () => readPending(caseId))
  pendingRef.current = pending

  // Restore the unsent draft on mount.
  const [question, setQuestion] = useState(() => {
    try {
      return localStorage.getItem(draftKey) || ''
    } catch {
      return ''
    }
  })

  useEffect(() => {
    try {
      if (question) {
        localStorage.setItem(draftKey, question)
      } else {
        localStorage.removeItem(draftKey)
      }
    } catch (e) {
      // Same reasoning as writePending: the guard is necessary, silence is
      // not. Losing the draft is invisible otherwise - the textarea simply
      // comes back empty on the next visit, which looks like the
      // investigator never typed it.
      console.warn(
        '[investigate] could not save the draft for ' + draftKey + ':', e)
    }
  }, [question, draftKey])

  useEffect(() => {
    loadData()
  }, [caseId])

  // Scroll to the latest message whenever history finishes loading
  useEffect(() => {
    if (!loadingHistory) {
      setTimeout(() => {
        bottomRef.current?.scrollIntoView(
          { behavior: 'instant' })
      }, 50)
    }
  }, [loadingHistory])

  // `quiet` suppresses the skeleton. The background poll that
  // watches for a landed answer must not blank the transcript
  // every few seconds — that reads as the page breaking.
  const loadData = async (quiet = false) => {
    if (!quiet) setLoadingHistory(true)
    try {
      const [qRes, eRes] =
        await Promise.all([
          getQueries(caseId, {
            page: 1,
            page_size: 20
          }),
          getEvidence(caseId)
        ])

      const items =
        qRes.data.items || qRes.data
      // Extra client-side filter
      // to exclude any system entries
      const filtered = items.filter(q =>
        !q.question_text?.startsWith(
          '[PROFILE]') &&
        !q.question_text?.startsWith(
          '[SUMMARY]') &&
        !q.question_text?.startsWith(
          '[CONTRADICTION') &&
        !q.question_text?.startsWith('[')
      )
      setQueries(filtered)
      setHasMoreQueries(
        qRes.data.has_next || false)

      // Fold the in-flight questions back into the transcript.
      // The backend writes a QueryLog only after the model has
      // answered, so a question that is still generating is absent
      // from this response. Anything the server now knows about has
      // landed and stops being pending; whatever is left is still in
      // flight and is re-rendered as a waiting entry.
      const serverTexts = filtered.map(
        f => f.question_text)
      const outstanding =
        pendingRef.current.filter(
          p => !serverTexts.includes(p.text))

      if (outstanding.length
          !== pendingRef.current.length) {
        const kept = new Set(outstanding.map(
          p => `${p.caseId}::${p.text}`))
        let all = []
        try {
          all = JSON.parse(
            localStorage.getItem(PENDING_KEY) || '[]')
          if (!Array.isArray(all)) all = []
        } catch {
          all = []
        }
        writePending(all.filter(p =>
          p && (p.caseId !== caseId ||
                kept.has(`${p.caseId}::${p.text}`))))
        setPending(outstanding)
      }

      setQueries([
        ...filtered,
        ...outstanding.map((p, i) => ({
          id: `pending_${p.at}_${i}`,
          question_text: p.text,
          processed_response: null,
          asked_by: user?.username || 'your account',
          asked_at: new Date(p.at).toISOString(),
          is_loading: true,
        })),
      ])
      setEvidence(
        (eRes.data || []).filter(
          e => e.status === 'Indexed'))
    } catch {
      if (!quiet) toast.error('Failed to load')
    } finally {
      if (!quiet) setLoadingHistory(false)
    }
  }

  // While a question is in flight, keep asking the server for
  // its answer. The QueryLog is written only once generation
  // finishes, so without this poll the answer stays invisible
  // until the investigator reloads by hand — which is the same
  // "it disappeared" complaint one level down.
  useEffect(() => {
    if (!pending.length) return
    const t = setInterval(() => {
      loadData(true)
    }, 3000)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending.length, caseId])

  const loadEarlier = async () => {
    const next = queryPage + 1
    try {
      const res = await getQueries(
        caseId, {
          page: next,
          page_size: 20
        })
      const items =
        res.data.items || res.data
      const filtered = items.filter(q =>
        !q.question_text?.startsWith('['))
      setQueries(prev => [
        ...filtered, ...prev])
      setQueryPage(next)
      setHasMoreQueries(
        res.data.has_next || false)
      setHistoryError(null)
    } catch (e) {
      /* Was `catch {}`. `hasMoreQueries` is still true, so the control stays
         on screen inviting another click, and every one of those clicks does
         nothing at all - no new questions, no message, no disabled state.
         On a page whose entire value is the transcript, a history that
         silently stops growing is indistinguishable from a short
         investigation, and nothing on screen suggests a request failed. */
      setHistoryError(apiErrorMessage(
        e, 'Could not load earlier questions'))
    }
  }

  /* This only ever emptied local state while announcing "Conversation
     cleared" - no API call, so the transcript returned on reload and the
     QueryLog rows were untouched. Deleting those rows would be the wrong
     fix: a record of what was asked of an assistant is itself case
     evidence. So the control is renamed to say what it actually does,
     which is hide-this-transcript-from-the-view. */
  const clearMemory = () => {
    setQueries([])
    setQueryPage(0)
    setHasMoreQueries(false)
    toast.success(
      'Transcript hidden from this view',
      { icon: '👁' })
  }

  const handleAsk = async () => {
    const q = question.trim()
    if (!q || loading) return
    setQuestion('')
    setLoading(true)

    // Record the question as in flight BEFORE the request goes
    // out, so that navigating away mid-generation cannot lose it.
    // The request itself is not cancelled on unmount — the backend
    // finishes and persists it — it simply stops being visible
    // until something brings it back on screen.
    const stamp = {
      caseId,
      text: q,
      at: Date.now(),
    }
    const nextPending = [...pendingRef.current, stamp]
    pendingRef.current = nextPending
    setPending(nextPending)
    let stored = []
    try {
      stored = JSON.parse(
        localStorage.getItem(PENDING_KEY) || '[]')
      if (!Array.isArray(stored)) stored = []
    } catch {
      stored = []
    }
    writePending([...stored, stamp])

    // Optimistic UI — show question
    // immediately
    const tempId = `temp_${Date.now()}`
    const tempEntry = {
      id: tempId,
      question_text: q,
      processed_response: null,
      asked_by: user?.username || 'your account',
      asked_at: new Date().toISOString(),
      is_loading: true,
    }
    setQueries(prev => [
      ...prev, tempEntry])

    // Scroll to bottom
    setTimeout(() => {
      bottomRef.current?.scrollIntoView(
        { behavior: 'smooth' })
    }, 50)

    try {
      // Build conversation history
      // from last 5 real exchanges
      const history = queries
        .slice(-5)
        .map(prev => ({
          role: 'investigator',
          question: prev.question_text,
          answer: prev.processed_response
                  || ''
        }))

      const res = await askQuestion(
        caseId, {
          question_text: q,
          evidence_id:
            selectedEvidence || null,
          conversation_history: history
        })

      // Replace temp entry with real result.
      // NOTE: POST /ask returns "answer" but the
      // query list renders "processed_response" —
      // map the field so the response shows immediately
      // without a page reload.
      setQueries(prev => prev.map(p =>
        p.id === tempId
          ? {
              ...res.data,
              id: res.data.query_id,
              question_text: q,
              processed_response: res.data.answer,
              asked_at: new Date().toISOString(),
              is_loading: false,
            }
          : p
      ))
    } catch (e) {
      setQueries(prev =>
        prev.filter(p =>
          p.id !== tempId))
      toast.error(
        e.response?.data?.detail ||
        'Query failed')
    } finally {
      setLoading(false)
      setTimeout(() => {
        bottomRef.current?.scrollIntoView(
          { behavior: 'smooth' })
      }, 100)
      textareaRef.current?.focus()
    }
  }

  const handleDelete = async (id) => {
    try {
      await deleteQuery(caseId, id)
      setQueries(prev =>
        prev.filter(q => q.id !== id))
    } catch {
      toast.error('Delete failed')
    }
  }

  // ── Prompt history (terminal-style ↑ / ↓) ─────────────────
  // Sourced from the questions already asked in this case rather
  // than a second private store, so the recall list and the
  // visible transcript can never disagree. Ascending order is
  // reversed to newest-first, and duplicates are dropped so
  // re-asking the same thing does not pad the list.
  const promptHistory = useMemo(() => {
    const seen = new Set()
    const out = []
    for (let i = queries.length - 1; i >= 0; i--) {
      const t = (queries[i].question_text || '').trim()
      if (!t || seen.has(t)) continue
      seen.add(t)
      out.push(t)
    }
    return out
  }, [queries])

  const [historyIndex, setHistoryIndex] =
    useState(null)
  // What the investigator had typed before they started
  // arrowing back, restored when they arrow past the newest
  // entry — the same courtesy a shell gives you.
  const historyDraftRef = useRef('')

  // Arrow keys are only taken over at the edges of the text.
  // In a textarea ArrowUp is also the ordinary way to move
  // between lines, so hijacking it unconditionally would break
  // Shift+Enter multi-line editing.
  const recallPrompt = (dir) => {
    const ta = textareaRef.current
    if (!ta || !promptHistory.length) return false
    const atStart = ta.selectionStart === 0
    const atEnd =
      ta.selectionStart === ta.value.length
    if (dir === 'up' && !atStart) return false
    if (dir === 'down' && !atEnd) return false

    let idx
    if (historyIndex === null) {
      // Nothing being recalled yet: only Up starts a recall.
      if (dir === 'down') return false
      historyDraftRef.current = question
      idx = 0
    } else {
      idx = historyIndex + dir
    }

    if (idx < 0) idx = 0

    if (idx >= promptHistory.length) {
      // Past the newest — hand back the original draft.
      setHistoryIndex(null)
      setQuestion(historyDraftRef.current)
      historyDraftRef.current = ''
      focusEndOfPrompt()
      return true
    }

    setHistoryIndex(idx)
    setQuestion(promptHistory[idx])
    focusEndOfPrompt()
    return true
  }

  const focusEndOfPrompt = () => {
    requestAnimationFrame(() => {
      const el = textareaRef.current
      if (!el) return
      el.focus()
      el.setSelectionRange(
        el.value.length, el.value.length)
    })
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' &&
        !e.shiftKey) {
      e.preventDefault()
      setHistoryIndex(null)
      historyDraftRef.current = ''
      handleAsk()
      return
    }
    if (e.key === 'ArrowUp' && !e.shiftKey) {
      if (recallPrompt('up')) e.preventDefault()
      return
    }
    if (e.key === 'ArrowDown' && !e.shiftKey) {
      if (recallPrompt('down')) e.preventDefault()
    }
  }

  return (
    <PageLayout
      title="Investigate"
      subtitle="AI analysis grounded in evidence"
      actions={
        <button
          onClick={() =>
            setShowSummary(true)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 7,
            padding: '9px 18px',
            borderRadius: 10,
            background:
              'linear-gradient(135deg,' +
              'rgba(99,102,241,0.15),' +
              'rgba(139,92,246,0.1))',
            border:
              '1px solid rgba(99,102,241,0.3)',
            color: '#a5b4fc',
            fontSize: 13,
            fontWeight: 500,
            cursor: 'pointer',
            transition: 'all 0.15s',
            flexShrink: 0,
          }}
          onMouseEnter={e => {
            e.currentTarget.style
              .background =
              'linear-gradient(135deg,' +
              'rgba(99,102,241,0.25),' +
              'rgba(139,92,246,0.18))'
            e.currentTarget.style
              .boxShadow =
              '0 4px 20px rgba(99,102,241,0.2)'
          }}
          onMouseLeave={e => {
            e.currentTarget.style
              .background =
              'linear-gradient(135deg,' +
              'rgba(99,102,241,0.15),' +
              'rgba(139,92,246,0.1))'
            e.currentTarget.style
              .boxShadow = 'none'
          }}
        >
          <Sparkles size={14} />
          Generate Case Intelligence
          Summary
        </button>
      }
    >
      <div style={{
        height: 'calc(100vh - 150px)',
        display: 'flex',
        flexDirection: 'column',
      }}>

        {/* Controls row */}
        <div style={{
        display: 'flex',
        gap: 10, marginBottom: 12,
        flexShrink: 0,
        flexWrap: 'wrap',
      }}>
        {/* Evidence filter */}
        <select
          value={selectedEvidence}
          onChange={e =>
            setSelectedEvidence(
              e.target.value)}
          style={{
            flex: 1, minWidth: 200,
            background:
              'var(--color-white-04)',
            border:
              '1px solid rgba(255,255,255,0.09)',
            borderRadius: 8,
            padding: '8px 12px',
            fontSize: 12,
            color: 'var(--text-primary)',
            outline: 'none',
          }}>
          <option value="">
            All indexed evidence
          </option>
          {evidence.map(e => (
            <option key={e.id}
              value={e.id}>
              {e.original_filename}
            </option>
          ))}
        </select>

        {/*
          Was an editable "Officer name" input whose value was written
          verbatim into QueryLog.asked_by AND into the QUERY_MADE audit
          entry - so the name on the forensic record was whatever was
          typed into a text box on this page. The server now takes the
          asker from the authenticated session, and a typed value would be
          silently discarded.

          Shown rather than offered, for the same reason as the case and
          note forms: a control that looks editable and is not is the B29
          defect. The investigator still needs to see who is asking, so
          the name is displayed - it just cannot be changed here.
        */}
        <span
          title="The query is recorded against your signed-in account."
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            padding: '8px 12px',
            borderRadius: 8,
            border: '1px solid rgba(255,255,255,0.09)',
            background: 'var(--color-white-04)',
            fontSize: 12,
            color: 'var(--text-secondary)',
            whiteSpace: 'nowrap',
            maxWidth: 200,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          <UserCheck
            size={13}
            style={{ flexShrink: 0 }}
          />
          {user?.username
            ? user.username
            : 'your account'}
        </span>

        {/* Hide transcript - not a delete, so not styled as one */}
        {queries.length > 0 && (
          <button
            onClick={clearMemory}
            title="Hides this transcript from the screen. The questions stay in the case record."
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 5,
              padding: '8px 14px',
              borderRadius: 8,
              background: 'none',
              border:
                '1px solid rgba(148,163,184,0.25)',
              color:
                'rgba(148,163,184,0.8)',
              fontSize: 12,
              cursor: 'pointer',
            }}
            onMouseEnter={e => {
              e.currentTarget.style
                .color = '#cbd5e1'
              e.currentTarget.style
                .borderColor =
                'rgba(148,163,184,0.45)'
            }}
            onMouseLeave={e => {
              e.currentTarget.style
                .color =
                'rgba(148,163,184,0.8)'
              e.currentTarget.style
                .borderColor =
                'rgba(148,163,184,0.25)'
            }}
          >
            <EyeOff size={12} />
            Hide transcript
          </button>
        )}
      </div>

      {/* Memory indicator */}
      {queries.length > 0 && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6, marginBottom: 12,
          flexShrink: 0,
        }}>
          <span style={{
            width: 6, height: 6,
            borderRadius: '50%',
            background: '#10b981',
            boxShadow:
              '0 0 6px #10b981',
            flexShrink: 0,
          }} />
          <span style={{
            fontSize: 11,
            color: 'var(--color-white-3)',
          }}>
            Conversation memory active —
            AI remembers last{' '}
            {Math.min(
              queries.length, 5)}{' '}
            exchange(s)
          </span>
        </div>
      )}

      {/* Chat area */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        marginBottom: 12,
        paddingRight: 4,
      }}>
        {/* Load earlier */}
        {hasMoreQueries && (
          <button
            onClick={loadEarlier}
            style={{
              display: 'block',
              width: '100%',
              padding: '8px',
              marginBottom: 16,
              background: 'none',
              border:
                '1px dashed rgba(255,255,255,0.08)',
              borderRadius: 8,
              color:
                'var(--color-white-2)',
              fontSize: 12,
              cursor: 'pointer',
            }}>
            Load earlier messages
          </button>
        )}

        {/* A failed "load earlier" is stated next to the control that
            failed, and the control stays available so the investigator can
            retry. It is not disabled, because a transient failure is the
            common case and a permanently greyed-out button would be a
            control that never recovers on its own. */}
        {historyError && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 12,
            marginBottom: 16,
            padding: '8px 12px',
            borderRadius: 8,
            border: '1px solid rgba(239,68,68,0.2)',
            background: 'rgba(239,68,68,0.05)',
            fontSize: 12,
            color: '#f87171',
          }}>
            <span>{historyError}</span>
            <button
              onClick={loadEarlier}
              style={{
                flexShrink: 0,
                background: 'none',
                border: '1px solid rgba(239,68,68,0.35)',
                borderRadius: 6,
                padding: '3px 10px',
                color: '#f87171',
                fontSize: 11,
                cursor: 'pointer',
              }}>
              Retry
            </button>
          </div>
        )}

        {/* Loading history */}
        {loadingHistory && (
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 16,
          }}>
            {Array(3).fill(0).map(
              (_,i) => (
              <div key={i}
                className="skeleton"
                style={{
                  height: 80,
                  borderRadius: 12,
                  animationDelay:
                    `${i*100}ms`,
                }} />
            ))}
          </div>
        )}

        {/* Empty state */}
        {!loadingHistory &&
         queries.length === 0 && (
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            height: '60%',
            gap: 16,
            textAlign: 'center',
          }}>
            <div style={{
              width: 64, height: 64,
              borderRadius: 18,
              background:
                'rgba(99,102,241,0.1)',
              border:
                '1px solid rgba(99,102,241,0.2)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}>
              <Bot size={28}
                color="#818cf8" />
            </div>
            <div>
              <p style={{
                fontSize: 15,
                fontWeight: 600,
                color: 'var(--text-primary)',
                marginBottom: 6,
              }}>
                Ready to analyse evidence
              </p>
              <p style={{
                fontSize: 13,
                color:
                  'var(--color-white-3)',
                maxWidth: 340,
                lineHeight: 1.6,
              }}>
                Ask questions about the
                indexed evidence. The AI
                will cite every claim
                with sources.
              </p>
            </div>
            <div style={{
              display: 'flex',
              gap: 8, flexWrap: 'wrap',
              justifyContent: 'center',
            }}>
              {[
                "Who are the primary suspects?",
                "What files were modified recently?",
                "What locations appear in the evidence?",
                "Summarise the key communications found",
              ].map(suggestion => (
                <button
                  key={suggestion}
                  onClick={() => {
                    setQuestion(suggestion)
                    textareaRef.current
                      ?.focus()
                  }}
                  style={{
                    padding: '6px 12px',
                    borderRadius: 20,
                    background:
                      'rgba(99,102,241,0.08)',
                    border:
                      '1px solid rgba(99,102,241,0.2)',
                    color: '#818cf8',
                    fontSize: 11,
                    cursor: 'pointer',
                    transition:
                      'all 0.15s',
                  }}>
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Conversation */}
        {!loadingHistory && (
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 20,
          }}>
            {queries.map((q, i) => (
              <div
                key={q.id}
                className="animate-fade-up"
                style={{
                  animationDelay:
                    `${i * 30}ms`,
                }}>

                {/* Officer question */}
                <div style={{
                  display: 'flex',
                  justifyContent: 'flex-end',
                  marginBottom: 10,
                }}>
                  <div style={{
                    maxWidth: '75%' }}>
                    <div style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6,
                      justifyContent:
                        'flex-end',
                      marginBottom: 4,
                    }}>
                      <span style={{
                        fontSize: 10,
                        color:
                          'var(--color-white-2)',
                      }}>
                        {q.asked_by}
                        {' '}·{' '}
                        {formatDistanceToNow(
                          fromUtc(q.asked_at),
                          { addSuffix: true }
                        )}
                      </span>
                      <div style={{
                        width: 22,
                        height: 22,
                        borderRadius: 6,
                        background:
                          'rgba(99,102,241,0.2)',
                        display: 'flex',
                        alignItems:
                          'center',
                        justifyContent:
                          'center',
                      }}>
                        <User size={11}
                          color="#818cf8" />
                      </div>
                    </div>
                    <div style={{
                      background:
                        'rgba(99,102,241,0.12)',
                      border:
                        '1px solid rgba(99,102,241,0.25)',
                      borderRadius:
                        '12px 2px 12px 12px',
                      padding: '10px 14px',
                    }}>
                      <p style={{
                        fontSize: 13,
                        color: '#c7d2fe',
                        lineHeight: 1.6,
                      }}>
                        {q.question_text}
                      </p>
                    </div>
                  </div>
                </div>

                {/* AI response */}
                <div style={{
                  display: 'flex',
                  gap: 10,
                  alignItems:
                    'flex-start',
                }}>
                  <div style={{
                    width: 28,
                    height: 28,
                    borderRadius: 8,
                    background:
                      'var(--color-white-05)',
                    border:
                      '1px solid rgba(255,255,255,0.08)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent:
                      'center',
                    flexShrink: 0,
                    marginTop: 2,
                  }}>
                    <Shield size={13}
                      color="#818cf8" />
                  </div>
                  <div style={{
                    flex: 1,
                    minWidth: 0,
                  }}>
                    <div style={{
                      display: 'flex',
                      alignItems:
                        'center',
                        gap: 8,
                      marginBottom: 6,
                    }}>
                      <span style={{
                        fontSize: 11,
                        fontWeight: 600,
                        color: '#818cf8',
                      }}>
                        IDF AI Analysis
                      </span>
                      {q.cited_sentence_count
                       > 0 && (
                        <span style={{
                          fontSize: 10,
                          color:
                            '#34d399',
                          background:
                            'rgba(16,185,129,0.1)',
                          border:
                            '1px solid rgba(16,185,129,0.2)',
                          padding:
                            '1px 6px',
                          borderRadius: 4,
                        }}>
                          {q.cited_sentence_count}
                          {' '}citations
                        </span>
                      )}
                      <button
                        onClick={() =>
                          handleDelete(
                            q.id)}
                        style={{
                          marginLeft:
                            'auto',
                          padding: 4,
                          background:
                            'none',
                          border: 'none',
                          cursor:
                            'pointer',
                          color:
                            'var(--color-white-1)',
                          display: 'flex',
                        }}
                        onMouseEnter={
                          e => {
                          e.currentTarget
                            .style.color =
                            '#f87171'
                        }}
                        onMouseLeave={
                          e => {
                          e.currentTarget
                            .style.color =
                            'var(--color-white-1)'
                        }}>
                        <Trash2
                          size={11} />
                      </button>
                    </div>

                    <div style={{
                      background:
                        'rgba(255,255,255,0.025)',
                      border:
                        '1px solid rgba(255,255,255,0.07)',
                      borderRadius:
                        '2px 12px 12px 12px',
                      padding:
                        '12px 16px',
                    }}>
                      {q.is_loading ? (
                        <div style={{
                          display: 'flex',
                          alignItems:
                            'center',
                          gap: 8,
                        }}>
                          <RefreshCw
                            size={13}
                            color="#818cf8"
                            className="animate-spin"
                          />
                          <span style={{
                            fontSize: 12,
                            color:
                              'var(--color-white-4)',
                          }}>
                            Analysing
                            evidence...
                          </span>
                        </div>
                      ) : (
                        <ResponseText
                          text={
                            q.processed_response
                          }
                        />
                      )}
                    </div>

                    {/* Response meta */}
                    {!q.is_loading &&
                     q.response_time_ms
                     > 0 && (
                      <p style={{
                        fontSize: 10,
                        color:
                          'var(--color-white-1)',
                        marginTop: 4,
                      }}>
                        {/* The model name is shown only when a model actually
                            answered. `model_used` is null whenever the
                            question never reached the model — retrieval
                            failed, or nothing survived the relevance floor —
                            and rendering it unconditionally left a dangling
                            "· 0.1s" that implied a model had replied. */}
                        {q.model_used
                          ? q.model_used + ' · '
                          : 'No model consulted · '}
                        {(q.response_time_ms
                          / 1000
                        ).toFixed(1)}s
                      </p>
                    )}
                  </div>
                </div>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Input area */}
      <div style={{
        flexShrink: 0,
        background:
          'var(--color-white-03)',
        border:
          '1px solid rgba(255,255,255,0.08)',
        borderRadius: 14,
        padding: '12px 14px',
      }}>
        <textarea
          ref={textareaRef}
          value={question}
          onChange={e => {
            setQuestion(e.target.value)
            // Typing invalidates a recall in progress, so the
            // next ArrowUp starts again from the newest prompt
            // rather than jumping relative to a stale position.
            setHistoryIndex(null)
            historyDraftRef.current = ''
          }}
          onKeyDown={handleKeyDown}
          placeholder="Ask a forensic question about the evidence... (Enter to send, Shift+Enter for newline, ↑/↓ for recent)"
          rows={3}
          style={{
            width: '100%',
            background: 'none',
            border: 'none',
            outline: 'none',
            resize: 'none',
            fontSize: 13,
            color: 'var(--text-primary)',
            lineHeight: 1.6,
            fontFamily: 'inherit',
          }}
        />
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginTop: 8,
        }}>
          <span style={{
            fontSize: 11,
            color: 'var(--color-white-2)',
          }}>
            Enter to send ·
            Shift+Enter for newline
          </span>
          <button
            onClick={handleAsk}
            disabled={
              !question.trim() ||
              loading}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '8px 16px',
              borderRadius: 9,
              background:
                question.trim() &&
                !loading
                  ? '#4f46e5'
                  : 'rgba(79,70,229,0.3)',
              border: 'none',
              color: 'var(--color-white-full)',
              fontSize: 12,
              fontWeight: 500,
              cursor:
                question.trim() &&
                !loading
                  ? 'pointer'
                  : 'not-allowed',
              transition: 'all 0.15s',
            }}>
            {loading
              ? <RefreshCw size={13}
                  className="animate-spin"/>
              : <Send size={13} />}
            {loading
              ? 'Analysing'
              : 'Send'}
          </button>
        </div>
      </div>

      {/* Summary modal */}
      {showSummary && (
        <SummaryModal
          caseId={caseId}
          onClose={() =>
            setShowSummary(false)}
        />
      )}
      </div>
    </PageLayout>
  )
}
