import React, { useState, useEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'
import { MapPin, Wifi, Globe, RefreshCw, AlertCircle } from 'lucide-react'
import { getGeoData } from '../api/client'
import PageLayout from '../components/PageLayout'
import toast from 'react-hot-toast'

export default function GeoMapPage() {
  const { caseId } = useParams()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const mapRef = useRef(null)
  const mapInstanceRef = useRef(null)

  useEffect(() => {
    loadGeoData()
    // Cleanup on unmount
    return () => {
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove()
        mapInstanceRef.current = null
      }
    }
  }, [caseId])

  useEffect(() => {
    if (data) {
      // Always rebuild map when data changes
      buildMap()
    }
  }, [data])

  const loadGeoData = async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true)
    else setLoading(true)

    try {
      const res = await getGeoData(caseId)
      setData(res.data)
    } catch {
      toast.error('Failed to load geographic data')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  const handleRefresh = () => {
    // Destroy old map before refetching
    if (mapInstanceRef.current) {
      mapInstanceRef.current.remove()
      mapInstanceRef.current = null
    }
    loadGeoData(true)
  }

  const buildMap = () => {
    if (!mapRef.current || !data) return

    // Destroy existing map if any
    if (mapInstanceRef.current) {
      mapInstanceRef.current.remove()
      mapInstanceRef.current = null
    }

    const hasPoints = (
      data.gps_points.some(p => p.lat && p.lon) ||
      data.ip_points.some(p => p.lat && p.lon)
    )

    // Dynamic import of Leaflet to avoid SSR issues
    import('leaflet').then(({ default: L }) => {
      // Guard: container may have unmounted
      if (!mapRef.current) return

      const map = L.map(mapRef.current, {
        center: [20, 0],
        zoom: 2,
        zoomControl: true,
        scrollWheelZoom: true
      })

      L.tileLayer(
        'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
        {
          attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
          maxZoom: 18
        }
      ).addTo(map)

      // ── GPS markers (indigo circles) ───────────────────
      const gpsIcon = L.divIcon({
        html:
          '<div style="width:14px;height:14px;' +
          'background:#0284c7;border-radius:50%;' +
          'border:2.5px solid white;' +
          'box-shadow:0 0 6px rgba(2,132,199,0.7);">' +
          '</div>',
        iconSize: [14, 14],
        iconAnchor: [7, 7],
        className: ''
      })

      const gpsMarkers = []
      data.gps_points.forEach(pt => {
        if (pt.lat && pt.lon) {
          const marker = L.marker([pt.lat, pt.lon], { icon: gpsIcon })
            .addTo(map)
            .bindPopup(
              `<div style="font-family:monospace;font-size:12px;line-height:1.6;">` +
              `<b>📷 ${pt.label}</b><br/>` +
              `<span style="color:#888;">${pt.path || ''}</span><br/>` +
              `<b>Lat:</b> ${pt.lat.toFixed(6)}<br/>` +
              `<b>Lon:</b> ${pt.lon.toFixed(6)}<br/>` +
              (pt.modified ? `<b>Modified:</b> ${String(pt.modified).slice(0, 10)}` : '') +
              `</div>`,
              { maxWidth: 280 }
            )
          gpsMarkers.push(marker)
        }
      })

      // ── IP markers (amber squares) ─────────────────────
      const ipIcon = L.divIcon({
        html:
          '<div style="width:12px;height:12px;' +
          'background:#f59e0b;border-radius:3px;' +
          'border:2.5px solid white;' +
          'box-shadow:0 0 6px rgba(245,158,11,0.7);">' +
          '</div>',
        iconSize: [12, 12],
        iconAnchor: [6, 6],
        className: ''
      })

      data.ip_points.forEach(pt => {
        if (pt.lat && pt.lon) {
          L.marker([pt.lat, pt.lon], { icon: ipIcon })
            .addTo(map)
            .bindPopup(
              `<div style="font-family:monospace;font-size:12px;line-height:1.6;">` +
              `<b>🌐 ${pt.ip}</b><br/>` +
              `<b>City:</b> ${pt.city || '—'}<br/>` +
              `<b>Country:</b> ${pt.country || '—'}<br/>` +
              `<b>ISP:</b> ${pt.isp || 'Unknown'}` +
              `</div>`,
              { maxWidth: 260 }
            )
        }
      })

      // Fit map to all visible markers
      const allLatLngs = [
        ...data.gps_points
          .filter(p => p.lat && p.lon)
          .map(p => [p.lat, p.lon]),
        ...data.ip_points
          .filter(p => p.lat && p.lon)
          .map(p => [p.lat, p.lon])
      ]
      if (allLatLngs.length > 0) {
        map.fitBounds(allLatLngs, { padding: [40, 40], maxZoom: 10 })
      }

      mapInstanceRef.current = map
    })
  }

  // ── Loading spinner ──────────────────────────────────────
  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-7 h-7 border-2 border-accent rounded-full border-t-transparent animate-spin" />
      </div>
    )
  }

  const hasAnyGeoData = (
    data?.gps_points.some(p => p.lat && p.lon) ||
    data?.ip_points.some(p => p.lat && p.lon)
  )

  return (
    <PageLayout
      fullWidth={true}
      title={
        <span className="flex items-center gap-2">
          <Globe size={22} className="text-accent" />
          Geographic Map
        </span>
      }
      subtitle="See where your evidence was created or accessed. GPS coordinates extracted from photos and IP address locations are plotted on an interactive map, giving you a geographic picture of your investigation."
      actions={
        <div className="flex items-center gap-5">
          {/* Legend */}
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-1.5">
              <span
                className="inline-block w-3 h-3 rounded-full"
                style={{ background: '#0284c7', boxShadow: '0 0 5px rgba(2,132,199,0.5)' }}
              />
              <span className="text-xs text-ink-2">
                GPS ({data?.total_gps ?? 0})
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              <span
                className="inline-block w-3 h-3 rounded"
                style={{ background: '#f59e0b', boxShadow: '0 0 5px rgba(245,158,11,0.5)' }}
              />
              <span className="text-xs text-ink-2">
                IP ({data?.total_ips ?? 0})
              </span>
            </div>
          </div>

          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="flex items-center gap-1.5 text-xs text-ink-2 hover:text-accent transition-colors disabled:opacity-50"
          >
            <RefreshCw size={12} className={refreshing ? 'animate-spin' : ''} />
            {refreshing ? 'Loading…' : 'Refresh'}
          </button>
        </div>
      }
    >

      {/* ── Map container ── */}
      <div
        className="relative bg-surface-2 border border-line rounded-2xl overflow-hidden mb-5"
        style={{ height: '500px' }}
      >
        <div
          ref={mapRef}
          className="absolute inset-0"
          style={{ zIndex: 1 }}
        />
        {!hasAnyGeoData && (
          <div className="absolute inset-0 z-10 flex items-center justify-center pointer-events-none bg-surface-2/60 backdrop-blur-sm">
            <div className="bg-surface-1/90 border border-line rounded-xl p-6 flex flex-col items-center justify-center text-ink-2 gap-3 shadow-2xl backdrop-blur-md">
              <Globe size={42} className="opacity-40 text-accent" />
              <p className="text-sm font-semibold text-ink-0">No Public Geographic Data</p>
              <div className="text-xs text-center space-y-2 max-w-sm opacity-80">
                <p>No valid public IP addresses or GPS coordinates found in this case yet.</p>
                <div className="p-2 bg-surface-3/50 rounded-lg border border-line/50 text-[10px] text-left">
                  <p className="font-bold mb-1">Note on IP Addresses:</p>
                  <p>Private network IPs (like 192.168.x.x or 10.x.x.x) are extracted but <b>cannot</b> be geolocated on the world map.</p>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── Stats bar ── */}
      <div className="grid grid-cols-3 gap-4 mb-5">
        <div className="bg-surface-2 border border-line rounded-xl p-4 text-center">
          <p className="text-3xl font-bold text-accent">{data?.total_gps ?? 0}</p>
          <p className="text-xs text-ink-2 mt-1">GPS Photo Locations</p>
        </div>
        <div className="bg-surface-2 border border-line rounded-xl p-4 text-center">
          <p className="text-3xl font-bold text-warning">{data?.total_ips ?? 0}</p>
          <p className="text-xs text-ink-2 mt-1">Geolocated IP Addresses</p>
        </div>
        <div className="bg-surface-2 border border-line rounded-xl p-4 text-center">
          <p className="text-3xl font-bold text-ink-0">
            {(data?.ip_points ?? []).filter(p => p.type === 'ip_private').length}
          </p>
          <p className="text-xs text-ink-2 mt-1">Private / Internal IPs</p>
        </div>
      </div>

      {/* ── GPS points list ── */}
      {data?.gps_points.length > 0 && (
        <div className="bg-surface-2 border border-line rounded-xl p-4 mb-4">
          <h2 className="text-xs font-semibold text-ink-2 uppercase tracking-wider mb-3 flex items-center gap-2">
            <MapPin size={13} className="text-accent" />
            GPS Locations from Images ({data.gps_points.length})
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {data.gps_points.map((pt, i) => (
              <div
                key={i}
                className="bg-surface-1 rounded-xl p-3 border border-line
                  hover:border-accent/30 transition-colors"
              >
                <p className="text-xs font-semibold text-ink-0 truncate mb-1">
                  📷 {pt.label}
                </p>
                <p className="text-xs font-mono text-accent">
                  {pt.lat?.toFixed(5)}, {pt.lon?.toFixed(5)}
                </p>
                <p className="text-xs text-ink-2 font-mono truncate mt-0.5">
                  {pt.path}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── IP points list ── */}
      {data?.ip_points.length > 0 && (
        <div className="bg-surface-2 border border-line rounded-xl p-4">
          <h2 className="text-xs font-semibold text-ink-2 uppercase tracking-wider mb-3 flex items-center gap-2">
            <Wifi size={13} className="text-warning" />
            IP Addresses ({data.ip_points.length})
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {data.ip_points.map((pt, i) => (
              <div
                key={i}
                className={`bg-surface-1 rounded-xl p-3 border transition-colors
                  ${pt.type === 'ip_private'
                    ? 'border-line opacity-60'
                    : pt.lat
                    ? 'border-warning/20 hover:border-warning/40'
                    : 'border-line'}`}
              >
                <p className="text-xs font-mono font-semibold text-ink-0 mb-0.5">
                  {pt.ip}
                </p>
                {pt.type === 'ip_private' ? (
                  <p className="text-xs text-ink-2">Private network</p>
                ) : pt.lat ? (
                  <>
                    <p className="text-xs text-warning">
                      {pt.city}{pt.city && pt.country ? ', ' : ''}{pt.country}
                    </p>
                    <p className="text-xs text-ink-2 truncate">{pt.isp}</p>
                  </>
                ) : (
                  <p className="text-xs text-ink-2 flex items-center gap-1">
                    <AlertCircle size={10} /> Location unknown
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </PageLayout>
  )
}
