import React, { useState,
                useEffect,
                useRef } from 'react'
import { useParams } from 'react-router-dom'
import {
  Send, Bot, User, RefreshCw,
  Trash2, Shield, AlertCircle,
  FileText, Sparkles, ChevronDown,
  X, Download
} from 'lucide-react'
import {
  getQueries, askQuestion,
  deleteQuery, getEvidence,
  generateCaseSummary,
  getLatestSummary
} from '../api/client'
import { useAuth } from
  '../context/AuthContext'
import toast from 'react-hot-toast'
import { formatDistanceToNow } from
  'date-fns'
import { fromUtc } from '../utils/time'
import PageLayout from '../components/PageLayout'

// Renders AI response with citations
function ResponseText({ text }) {
  if (!text) return (
    <p style={{
      color: 'var(--color-white-2)',
      fontStyle: 'italic',
      fontSize: 12,
    }}>
      The AI did not return a response for this query. Try rephrasing your question.
    </p>
  )

  // Highlight citation markers
  const parts = text.split(
    /(\[Source:[^\]]+\])/g)
  return (
    <div style={{
      fontSize: 13,
      color: 'rgba(255,255,255,0.75)',
      lineHeight: 1.8,
      whiteSpace: 'pre-wrap',
      wordBreak: 'break-word',
    }}>
      {parts.map((part, i) =>
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
    } catch {}
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
  const [question, setQuestion] =
    useState('')
  const [loading, setLoading] =
    useState(false)
  const [loadingHistory, setLoadingHistory] =
    useState(true)
  const [evidence, setEvidence] =
    useState([])
  const [selectedEvidence, setSelectedEvidence] =
    useState('')
  const [askedBy, setAskedBy] =
    useState(user?.full_name ||
             user?.username ||
             'Investigator')
  const [showSummary, setShowSummary] =
    useState(false)
  const [hasMoreQueries, setHasMoreQueries] =
    useState(false)
  const [queryPage, setQueryPage] =
    useState(1)
  const bottomRef = useRef()
  const textareaRef = useRef()

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

  const loadData = async () => {
    setLoadingHistory(true)
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
      setEvidence(
        (eRes.data || []).filter(
          e => e.status === 'Indexed'))
    } catch {
      toast.error('Failed to load')
    } finally {
      setLoadingHistory(false)
    }
  }

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
    } catch {}
  }

  const clearMemory = () => {
    setQueries([])
    toast.success(
      'Conversation cleared')
  }

  const handleAsk = async () => {
    const q = question.trim()
    if (!q || loading) return
    setQuestion('')
    setLoading(true)

    // Optimistic UI — show question
    // immediately
    const tempId = `temp_${Date.now()}`
    const tempEntry = {
      id: tempId,
      question_text: q,
      processed_response: null,
      asked_by: askedBy,
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
          asked_by: askedBy,
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

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' &&
        !e.shiftKey) {
      e.preventDefault()
      handleAsk()
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

        {/* Officer name */}
        <input
          value={askedBy}
          onChange={e =>
            setAskedBy(e.target.value)}
          placeholder="Officer name"
          style={{
            width: 180,
            background:
              'var(--color-white-04)',
            border:
              '1px solid rgba(255,255,255,0.09)',
            borderRadius: 8,
            padding: '8px 12px',
            fontSize: 12,
            color: 'var(--text-primary)',
            outline: 'none',
          }}
        />

        {/* Clear conversation */}
        {queries.length > 0 && (
          <button
            onClick={clearMemory}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 5,
              padding: '8px 14px',
              borderRadius: 8,
              background: 'none',
              border:
                '1px solid rgba(239,68,68,0.2)',
              color:
                'rgba(239,68,68,0.5)',
              fontSize: 12,
              cursor: 'pointer',
            }}
            onMouseEnter={e => {
              e.currentTarget.style
                .color = '#f87171'
              e.currentTarget.style
                .borderColor =
                'rgba(239,68,68,0.4)'
            }}
            onMouseLeave={e => {
              e.currentTarget.style
                .color =
                'rgba(239,68,68,0.5)'
              e.currentTarget.style
                .borderColor =
                'rgba(239,68,68,0.2)'
            }}
          >
            <Trash2 size={12} />
            Clear conversation
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
                        {q.model_used}
                        {' '}·{' '}
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
          onChange={e =>
            setQuestion(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask a forensic question about the evidence... (Enter to send, Shift+Enter for newline)"
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
