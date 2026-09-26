/**
 * useNotifications.js
 * ────────────────────
 * Global notification hook — subscribes to /ws/global and shows
 * styled toast notifications for server-pushed events.
 *
 * Mount once inside AppLayout (after the router is available)
 * so navigate() works correctly.
 *
 * Supported event types:
 *   INGESTION_COMPLETE  — green toast, click navigates to artifacts
 *   INGESTION_FAILED    — red toast
 *   NEW_NOTE            — neutral toast
 *   ENTITY_FLAGGED      — orange toast
 */

import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import useWebSocket from './useWebSocket'

// Shared dark toast base style — matches the IDF AI glassmorphism theme
const BASE_STYLE = {
  background: '#14161f',
  color:      'var(--text-primary)',
  fontSize:   13,
  fontFamily: 'inherit',
  borderRadius: 10,
  padding:    '10px 14px',
}

export default function useNotifications() {
  const navigate = useNavigate()

  const handleMessage = useCallback(
    (data) => {
      if (!data?.type) return

      switch (data.type) {
        // ── Ingestion complete ──────────────────────────────────────────────
        case 'INGESTION_COMPLETE': {
          const label = data.filename || 'File'
          toast.success(
            (t) => (
              <span
                style={{ cursor: data.case_id ? 'pointer' : 'default' }}
                onClick={() => {
                  if (data.case_id) {
                    navigate(`/cases/${data.case_id}/artifacts`)
                    toast.dismiss(t.id)
                  }
                }}
              >
                <strong>{label}</strong> ingested successfully
                {data.case_id && (
                  <span style={{ opacity: 0.55, marginLeft: 6, fontSize: 11 }}>
                    — Click to view artifacts
                  </span>
                )}
              </span>
            ),
            {
              id:       `ingest-ok-${data.job_id || data.evidence_id}`,
              duration: 7000,
              icon:     '📁',
              style: {
                ...BASE_STYLE,
                border: '1px solid rgba(16,185,129,0.35)',
              },
            }
          )
          break
        }

        // ── Ingestion failed ────────────────────────────────────────────────
        case 'INGESTION_FAILED': {
          const label = data.filename || 'File'
          toast.error(
            `Ingestion failed: ${label}`,
            {
              id:       `ingest-fail-${data.job_id || data.evidence_id}`,
              duration: 9000,
              style: {
                ...BASE_STYLE,
                border: '1px solid rgba(239,68,68,0.35)',
              },
            }
          )
          break
        }

        // ── New note added ──────────────────────────────────────────────────
        case 'NEW_NOTE': {
          toast(
            '📝 New note added to case',
            {
              id:       `note-${Date.now()}`,
              duration: 4000,
              style: {
                ...BASE_STYLE,
                border: '1px solid rgba(253,230,138,0.25)',
              },
            }
          )
          break
        }

        // ── Entity flagged ──────────────────────────────────────────────────
        case 'ENTITY_FLAGGED': {
          const name = data.entity_name ? `"${data.entity_name}"` : 'An entity'
          toast(
            `⚑ ${name} was flagged`,
            {
              id:       `flag-${Date.now()}`,
              duration: 5000,
              style: {
                ...BASE_STYLE,
                border: '1px solid rgba(249,115,22,0.35)',
              },
            }
          )
          break
        }

        // ── Artifact flagged ────────────────────────────────────────────────
        case 'ARTIFACT_FLAGGED': {
          toast(
            `🚩 Artifact flagged: ${data.filename || ''}`,
            {
              id:       `aflag-${Date.now()}`,
              duration: 5000,
              style: {
                ...BASE_STYLE,
                border: '1px solid rgba(251,146,60,0.35)',
              },
            }
          )
          break
        }

        // ── Access granted to a case ─────────────────────────────────────────
        case 'CASE_ACCESS_GRANTED': {
          toast(
            `🔓 You have been granted access to a case`,
            {
              id:       `access-${Date.now()}`,
              duration: 5000,
              style: {
                ...BASE_STYLE,
                border: '1px solid rgba(99,102,241,0.35)',
              },
            }
          )
          break
        }

        default:
          break
      }
    },
    [navigate]
  )

  // Connect to the global WebSocket — auto-reconnects on disconnect
  useWebSocket('/ws/global', handleMessage, { reconnect: true, reconnectDelay: 4000 })
}
