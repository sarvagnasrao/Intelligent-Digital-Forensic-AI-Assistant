/**
 * useWebSocket.js
 * ──────────────
 * A robust WebSocket hook with automatic reconnection.
 * Connects to the IDF AI backend on port 8000 (same host as the app).
 *
 * Usage:
 *   const { send } = useWebSocket('/ws/global', (data) => { ... })
 *   const { send } = useWebSocket(`/ws/cases/${caseId}`, handler)
 */

import { useEffect, useRef, useCallback } from 'react'

export default function useWebSocket(url, onMessage, options = {}) {
  const wsRef           = useRef(null)
  const reconnectTimer  = useRef(null)
  const onMessageRef    = useRef(onMessage)

  const {
    reconnect       = true,
    reconnectDelay  = 3000,
  } = options

  // Keep onMessage ref up-to-date without re-triggering connect
  useEffect(() => {
    onMessageRef.current = onMessage
  }, [onMessage])

  const connect = useCallback(() => {
    // Don't double-connect
    if (
      wsRef.current &&
      (wsRef.current.readyState === WebSocket.CONNECTING ||
       wsRef.current.readyState === WebSocket.OPEN)
    ) {
      return
    }

    // Build WebSocket URL: same host, port 8000
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host     = window.location.hostname
    const fullUrl  = `${protocol}//${host}:8000${url}`

    const ws = new WebSocket(fullUrl)
    wsRef.current = ws

    ws.onopen = () => {
      console.log(`[WS] Connected: ${url}`)
      // Clear any pending reconnect timer
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current)
        reconnectTimer.current = null
      }
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        onMessageRef.current(data)
      } catch {
        onMessageRef.current(event.data)
      }
    }

    ws.onclose = (event) => {
      console.log(`[WS] Disconnected: ${url} (code ${event.code})`)
      if (reconnect) {
        reconnectTimer.current = setTimeout(connect, reconnectDelay)
      }
    }

    ws.onerror = () => {
      // onerror is always followed by onclose — let onclose handle reconnect
      ws.close()
    }
  }, [url, reconnect, reconnectDelay]) // onMessage intentionally excluded (uses ref)

  useEffect(() => {
    connect()
    return () => {
      // Cleanup on unmount: cancel reconnect and close socket
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current)
        reconnectTimer.current = null
      }
      if (wsRef.current) {
        // Prevent the onclose handler from scheduling a reconnect
        wsRef.current.onclose = null
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [connect])

  /**
   * send — sends a message over the WebSocket.
   * Silently no-ops if the socket is not currently OPEN.
   */
  const send = useCallback((data) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        typeof data === 'string' ? data : JSON.stringify(data)
      )
    }
  }, [])

  return { send }
}
