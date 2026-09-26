import { useState, useEffect, useCallback } from 'react'
import { getSystemInfo, getIngestionModes } from '../api/client'

/**
 * One shared description of the machine the job will run on.
 *
 * The queue form used to hardcode its limits: a 0-8 GB "Min Free RAM"
 * slider, a 70% CPU default, and advice text branching on a fixed
 * 8/16/32 GB ladder. On a 16 GB machine that offered a ceiling the
 * hardware could never reach and hid seven gigabytes of usable headroom.
 * The backend now derives all of it from the live probe
 * (backend/modules/ingestion_modes.suggest_budget) and sends the *bounds*
 * for the controls along with the defaults.
 *
 * This hook fetches that once and shares it, so the Evidence page's queue
 * form, the Queue page and <ResourceMonitor /> all describe the same device
 * with the same numbers. A module-level cache means a second consumer
 * renders immediately instead of waiting on a second round-trip.
 */

let cache = null            // last successful payload
let inflight = null          // promise of an in-flight fetch
const listeners = new Set()

function publish(payload) {
  cache = payload
  listeners.forEach((fn) => fn(payload))
}

function load() {
  if (inflight) return inflight
  inflight = Promise.all([
    getSystemInfo(),
    getIngestionModes().catch(() => null),
  ])
    .then(([infoRes, modesRes]) => {
      const info = infoRes?.data || {}
      const modes = modesRes?.data?.modes || info.modes || []
      const payload = {
        system: info.system || info.hardware || {},
        budget: modesRes?.data?.budget || info.suggested_budget || null,
        modes,
        defaultMode: modesRes?.data?.default_mode || info.default_mode || 'normal',
      }
      publish(payload)
      return payload
    })
    .finally(() => { inflight = null })
  return inflight
}

export function refreshSystemInfo() {
  // Force a fresh walk: the backend re-detects attached devices, so this is
  // the "I just plugged in an evidence drive" path.
  inflight = null
  return load()
}

/**
 * Returns { system, budget, modes, defaultMode, loading, refresh }.
 *
 * `budget` is null until the first response lands. Callers must handle that:
 * the RAM slider, for example, should render disabled with a placeholder
 * rather than guessing a maximum and snapping the value when the real one
 * arrives.
 */
export default function useSystemInfo() {
  const [data, setData] = useState(cache)
  const [loading, setLoading] = useState(!cache)

  useEffect(() => {
    // Re-read the module cache: another component may have populated it
    // between our initial render and this effect.
    setData(cache)
    const fn = (payload) => setData(payload)
    listeners.add(fn)

    if (cache) {
      setLoading(false)
    } else {
      load()
        .then(() => setLoading(false))
        .catch(() => setLoading(false))
    }

    return () => { listeners.delete(fn) }
  }, [])

  const refresh = useCallback(async () => {
    setLoading(true)
    try { await refreshSystemInfo() } catch { /* keep last known */ }
    finally { setLoading(false) }
  }, [])

  return {
    system: data?.system || null,
    budget: data?.budget || null,
    modes: data?.modes || [],
    defaultMode: data?.defaultMode || 'normal',
    loading,
    refresh,
  }
}
