import { useState, useEffect, useCallback } from 'react'
import { getPreferences } from '../api/client'

// Mirrors the server-side default. Keeping it here means the panel shows
// immediately on first paint instead of flashing hidden while the
// preferences request is in flight.
const DEFAULTS = { show_system_resources: true }

const CACHE_KEY = 'idfai_prefs'

function readCache() {
  try {
    const raw = localStorage.getItem(CACHE_KEY)
    return raw ? { ...DEFAULTS, ...JSON.parse(raw) } : DEFAULTS
  } catch {
    return DEFAULTS
  }
}

export function cachePreferences(prefs) {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(prefs))
  } catch {
    /* private mode / quota - the cache is an optimisation, not required */
  }
}

/**
 * Reads the signed-in user's preferences.
 *
 * The cached copy is returned synchronously on the first render so that a
 * user who has switched the System Resources panel off never sees it flash
 * in before the network round-trip resolves. The server value always wins
 * once it arrives.
 */
export default function usePreferences() {
  const [prefs, setPrefs] = useState(readCache)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      const res = await getPreferences()
      const next = { ...DEFAULTS, ...res.data }
      setPrefs(next)
      cachePreferences(next)
    } catch {
      /* offline or unauthenticated - fall back to whatever is cached */
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  return { prefs, loading, refresh }
}
