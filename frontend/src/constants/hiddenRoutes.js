// ── Hidden routes ─────────────────────────────────────────────
//
// One registry, consulted by both the sidebar and the router, so a route
// cannot be hidden from the navigation and still reachable by typing the
// URL (or arriving from a stale bookmark, a case-detail link, or a
// WebSocket-driven navigate call).
//
// The instinct to filter these independently in two files is the bug this
// exists to prevent: the two lists drift, and the result is a feature that is
// invisible in the menu but one click away for anyone who knows the path. A
// reviewer checking "can I get to that page?" would be right to.
//
// A hidden route is *retired*, not broken. Hitting one explains itself and
// offers a way back, rather than 404-ing or rendering an empty shell.
//
// GEO_MAP is here for a reason worth stating: it fetches raster tiles from
// `tile.openstreetmap.org` at runtime (GeoMapPage.jsx:85). That is not a
// feature that can be made air-gap-safe - the tile set is unbounded and
// cannot be vendored - and this product's entire premise is that evidence
// never leaves the machine. On an air-gapped deployment the page renders an
// empty grey square and looks broken; on a connected one it silently reports
// the host's location data to a third party. Both are worse than not having
// it. The extracted EXIF coordinates are not lost: they are on the Evidence
// page, per artifact, and Timeline shows ordering by timestamp.

export const HIDDEN_ROUTES = {
  GEO_MAP: {
    // Route pattern, matched exactly. Keep these in step with the
    // corresponding <Route path=...> in App.jsx.
    path: '/cases/:caseId/geomap',
    label: 'Geo Map',
    // What the page was, so the retired-route screen can say what was
    // removed and where the equivalent lives.
    reason:
      'The interactive map is disabled. It draws tiles from ' +
      'openstreetmap.org, which sends this machine\'s location data to a ' +
      'third party and cannot work without an internet connection - ' +
      'neither is acceptable for a product that keeps evidence local. ' +
      'Latitude and longitude extracted from your evidence are unchanged ' +
      'and still shown on the Evidence page.',
    // Where the investigator should go instead. Rendered as a link.
    alternative: {
      label: 'Open Evidence',
      to: '/cases/:caseId/evidence',
    },
  },
}

// Resolve ':param' segments in a pattern against real params, so a
// retired-route screen can offer a working link back into the same case.
// /cases/:caseId/geomap + { caseId: 'abc' } -> /cases/abc/evidence
export function resolveRoutePath(pattern, params = {}) {
  return pattern.replace(/:([A-Za-z0-9_]+)/g, (whole, key) =>
    params[key] !== undefined && params[key] !== null
      ? encodeURIComponent(String(params[key]))
      : whole
  )
}

// The reason a path is retired, or null if it is not retired. Keys are
// matched on the *shape* of the path, not the literal, because
// /cases/abc/geomap is what the browser actually holds.
export function hiddenReasonFor(pathname) {
  const segments = String(pathname || '').split('/').filter(Boolean)
  for (const entry of Object.values(HIDDEN_ROUTES)) {
    const pattern = entry.path.split('/').filter(Boolean)
    if (pattern.length !== segments.length) continue
    const matches = pattern.every((p, i) =>
      p.startsWith(':') || p === segments[i]
    )
    if (matches) return entry
  }
  return null
}

// The per-case navigation lists store a bare final segment ('geomap'),
// because they are appended to `/cases/<caseId>/`. Matching on that shape
// here means one registry serves three callers - the sidebar, the case
// detail action grid, and the router - instead of three lists that drift.
//
// The matching is on the last segment, so it stays correct for a retired
// route that is not a per-case route only by coincidence. If a non-case
// route is ever retired, it belongs in its own check rather than in here.
export function isRetiredCasePath(segment) {
  const needle = String(segment || '')
    .replace(/^\/+/, '')
    .replace(/\/+$/, '')
  if (!needle) return false
  return Object.values(HIDDEN_ROUTES).some((entry) => {
    const pattern = entry.path.split('/').filter(Boolean)
    return pattern.length > 0 && pattern[pattern.length - 1] === needle
  })
}
