import React, { useState, useEffect, useCallback } from 'react'
import {
  Cpu, MemoryStick, HardDrive, Gauge, ChevronDown, ChevronUp,
  RefreshCw, Monitor, Network, Battery, Server, ShieldAlert,
} from 'lucide-react'
import { getSystemInfo, rescanSystemInfo } from '../api/client'
import { refreshSystemInfo } from '../hooks/useSystemInfo'
import usePreferences from '../hooks/usePreferences'

/**
 * Live hardware + device monitor.
 *
 * Everything shown here is re-detected, not hardcoded: CPU model and core
 * counts, every GPU with its VRAM, every mounted volume (fixed and
 * removable), network adapters, chassis model, battery. The backend
 * re-walks the hardware whenever the set of attached devices changes, so
 * plugging in an evidence drive or an eGPU shows up here automatically.
 *
 * Rendered on both the Evidence page and the Queue page so an operator
 * sees an identical hardware description in both places.
 *
 * Honours the "System resource monitoring" preference in
 * Settings > Preferences: when switched off this component renders nothing
 * and stops polling entirely, so an investigator who does not care about
 * hardware pays nothing for it.
 */

const GB = (mb) => (mb == null ? '—' : `${(mb / 1024).toFixed(1)} GB`)

function Metric({ icon: Icon, label, value, sub, tone = 'text-ink-0' }) {
  return (
    <div className="min-w-0">
      <p className="text-xs text-ink-2 mb-1 flex items-center gap-1">
        <Icon size={11} className="shrink-0" />
        <span className="truncate">{label}</span>
      </p>
      <p className={`text-xl font-bold tabular-nums truncate ${tone}`}>
        {value}
        {sub && (
          <span className="text-sm font-normal text-ink-2 ml-1">{sub}</span>
        )}
      </p>
    </div>
  )
}

function SpecRow({ label, value, mono = true }) {
  if (value == null || value === '') return null
  return (
    <div className="flex items-start justify-between gap-4 py-0.5">
      <span className="text-xs text-ink-2 shrink-0">{label}</span>
      <span
        className={`text-xs text-ink-0 text-right break-words ${
          mono ? 'font-mono' : ''
        }`}
      >
        {value}
      </span>
    </div>
  )
}

function Bar({ percent, tone }) {
  return (
    <div className="h-1.5 bg-surface-3 rounded-full overflow-hidden mt-2">
      <div
        className={`h-full rounded-full transition-all duration-500 ${tone}`}
        style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
      />
    </div>
  )
}

function Section({ icon: Icon, title, count, children }) {
  return (
    <div className="border-t border-line pt-3 mt-4 first:border-0 first:pt-0 first:mt-0">
      <p className="text-[10px] font-mono uppercase tracking-widest text-ink-2 mb-2 flex items-center gap-1.5">
        <Icon size={11} />
        {title}
        {count != null && (
          <span className="text-accent">({count})</span>
        )}
      </p>
      {children}
    </div>
  )
}

export default function ResourceMonitor({
  title = 'System Resources',
  refreshMs = 8000,
  defaultOpen = true,
  extra = null,
  className = '',
}) {
  const { prefs } = usePreferences()
  const show = prefs.show_system_resources !== false

  const [info, setInfo] = useState(null)
  const [error, setError] = useState(false)
  const [open, setOpen] = useState(defaultOpen)
  const [scanning, setScanning] = useState(false)
  const [showAllVolumes, setShowAllVolumes] = useState(false)

  const apply = useCallback((res) => {
    // The endpoint returns the same object under "system" and "hardware";
    // accept either so this keeps working if one is renamed.
    setInfo(res.data?.hardware || res.data?.system || null)
    setError(false)
  }, [])

  const load = useCallback(async () => {
    try {
      apply(await getSystemInfo())
    } catch {
      setError(true)
    }
  }, [apply])

  // Normal polling. Skipped entirely when the preference is off.
  useEffect(() => {
    if (!show) return undefined
    load()
    const id = setInterval(load, refreshMs)
    return () => clearInterval(id)
  }, [show, load, refreshMs])

  // Full re-walk on demand, for when the operator just plugged something in.
  const rescan = async () => {
    setScanning(true)
    try {
      apply(await rescanSystemInfo())
      // Invalidate the shared device budget too. The queue form sizes its
      // RAM-floor slider from that budget, and a rescan is exactly the
      // moment the answer changes - e.g. after plugging in a bigger machine
      // or a GPU. Fire-and-forget: a failure here must not blank the panel.
      refreshSystemInfo().catch(() => {})
    } catch {
      setError(true)
    } finally {
      setScanning(false)
    }
  }

  if (!show) return null

  const ramPct = info?.ram_percent ?? 0
  const ramTone = ramPct >= 90 ? 'bg-danger'
    : ramPct >= 75 ? 'bg-warning' : 'bg-accent'
  const ramText = ramPct >= 90 ? 'text-danger'
    : ramPct >= 75 ? 'text-warning' : 'text-ink-0'

  const diskPct = info?.disk_percent ?? 0
  const diskTone = diskPct >= 90 ? 'bg-danger'
    : diskPct >= 75 ? 'bg-warning' : 'bg-success'

  const volumes = info?.volumes || []
  const shownVolumes = showAllVolumes ? volumes : volumes.slice(0, 3)
  const gpus = info?.gpus || []
  const adapters = info?.network_adapters || []

  return (
    <div className={`bg-surface-1 border border-line rounded-xl shadow-sm ${className}`}>
      <div className="flex items-center justify-between px-5 py-4">
        <button
          type="button"
          onClick={() => setOpen(o => !o)}
          className="flex items-center gap-2 text-sm font-bold text-ink-0 hover:text-accent transition-colors cursor-pointer bg-transparent border-0 p-0"
          aria-expanded={open}
        >
          <Cpu size={16} className="text-accent" />
          {title}
          {open ? <ChevronUp size={14} className="text-ink-2" />
                : <ChevronDown size={14} className="text-ink-2" />}
        </button>
        <button
          onClick={rescan}
          disabled={scanning}
          title="Re-detect all hardware and attached devices"
          aria-label="Re-detect all hardware and attached devices"
          className="text-[10px] flex items-center gap-1 font-mono text-ink-2 hover:text-accent transition-colors uppercase tracking-widest bg-surface-3 px-2 py-1 rounded cursor-pointer disabled:opacity-50"
        >
          <RefreshCw
            size={10}
            className={scanning ? 'animate-spin' : ''}
          />
          {scanning ? 'Scanning' : 'Rescan'}
        </button>
      </div>

      {open && (
        <div className="px-5 pb-5">
          {error && !info && (
            <p className="text-xs text-danger py-2">
              Hardware telemetry unavailable — the backend did not respond.
            </p>
          )}

          {info && (
            <>
              {/* ── Live load ── */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <Metric
                  icon={MemoryStick}
                  label="Available RAM"
                  tone={ramText}
                  value={GB(info.available_ram_mb)}
                  sub={`of ${GB(info.total_ram_mb)}`}
                />
                <Metric
                  icon={Gauge}
                  label="CPU Usage"
                  value={`${info.cpu_percent ?? 0}%`}
                  sub={`${info.cpu_count_physical || info.cpu_count || '?'}C/${info.cpu_count_logical || '?'}T`}
                />
                <Metric
                  icon={Monitor}
                  label="GPU"
                  value={info.gpu_count ? `${info.gpu_count}` : '—'}
                  sub={info.gpu_vram_total_mb
                    ? GB(info.gpu_vram_total_mb)
                    : info.gpu_count === 1 ? 'adapter' : 'adapters'}
                />
                <Metric
                  icon={HardDrive}
                  label="Storage Free"
                  value={GB(info.disk_free_mb)}
                  sub={`of ${GB(info.disk_total_mb)}`}
                />
              </div>

              <Bar percent={ramPct} tone={ramTone} />
              <div className="flex justify-between text-[10px] font-mono text-ink-2 mt-1">
                <span>RAM {ramPct.toFixed(0)}% used</span>
                <span>Storage {diskPct.toFixed(0)}% used</span>
              </div>

              {/* ── Machine / CPU ── */}
              <Section icon={Server} title="Machine">
                <SpecRow
                  label="Chassis"
                  value={[info.machine_manufacturer, info.machine_model]
                    .filter(Boolean).join(' ') || null}
                />
                <SpecRow label="CPU" value={info.cpu_model} />
                <SpecRow
                  label="Cores"
                  value={`${info.cpu_count_physical ?? '?'} physical / ${info.cpu_count_logical ?? '?'} logical`}
                />
                <SpecRow
                  label="Clock"
                  value={info.cpu_freq_max_mhz
                    ? `${(info.cpu_freq_max_mhz / 1000).toFixed(2)} GHz max${info.cpu_freq_mhz ? ` · ${(info.cpu_freq_mhz / 1000).toFixed(2)} GHz now` : ''}`
                    : null}
                />
                <SpecRow label="System RAM" value={GB(info.total_ram_mb)} />
                {/* A machine with no pagefile cannot commit enough memory
                    for the LLM, which is a confusing failure to debug
                    without this line. */}
                <SpecRow
                  label="Swap / pagefile"
                  value={info.swap_total_mb
                    ? `${GB(info.swap_total_mb)}${info.swap_used_mb ? ` (${GB(info.swap_used_mb)} used)` : ''}`
                    : 'None configured'}
                />
                {info.bios_version && (
                  <SpecRow label="BIOS" value={info.bios_version} />
                )}
                <SpecRow label="Hostname" value={info.hostname} />
                <SpecRow
                  label="OS"
                  value={[info.platform_system, info.platform_release,
                    info.platform_machine].filter(Boolean).join(' ')}
                />
                {info.is_laptop && (
                  <SpecRow
                    label="Battery"
                    value={`${info.battery_percent ?? '—'}%${
                      info.on_ac ? ' · on AC power' : ' · on battery'}`}
                  />
                )}
              </Section>

              {/* ── GPUs ── */}
              <Section icon={Monitor} title="Graphics" count={gpus.length}>
                {gpus.length === 0 && (
                  <p className="text-xs text-ink-2">
                    No display adapter reported by the operating system.
                  </p>
                )}
                {gpus.map((g, i) => (
                  <div
                    key={`${g.name}-${i}`}
                    className="flex items-start justify-between gap-4 py-0.5"
                  >
                    <span className="text-xs text-ink-2 shrink-0">
                      {g.shared_memory ? 'Integrated' : 'Dedicated'}
                    </span>
                    <span className="text-xs text-ink-0 text-right font-mono break-words">
                      {g.name}
                      <span className="text-ink-2">
                        {g.vram_total_mb
                          ? ` — ${GB(g.vram_total_mb)} VRAM`
                          : ' — shared memory, no dedicated VRAM'}
                      </span>
                    </span>
                  </div>
                ))}
                {info.gpu_vram_shared_only && gpus.length > 0 && (
                  <p className="text-[10px] text-warning mt-1">
                    No discrete GPU detected — local LLM inference will run
                    on CPU and will be slow.
                  </p>
                )}
              </Section>

              {/* ── Storage devices ── */}
              <Section
                icon={HardDrive}
                title="Storage Devices"
                count={volumes.length}
              >
                {volumes.length === 0 && (
                  <p className="text-xs text-ink-2">
                    No mounted volumes reported.
                  </p>
                )}
                {shownVolumes.map((v, i) => (
                  <div
                    key={`${v.device}-${i}`}
                    className="flex items-start justify-between gap-4 py-0.5"
                  >
                    <span className="text-xs text-ink-2 shrink-0">
                      {v.removable ? 'Removable' : 'Fixed'}
                      {v.writable ? '' : ' · read-only'}
                    </span>
                    <span className="text-xs text-ink-0 text-right font-mono break-words">
                      {v.device}
                      <span className="text-ink-2">
                        {v.fstype !== 'unknown' ? ` · ${v.fstype}` : ''}
                        {v.total_mb
                          ? ` · ${GB(v.free_mb)} free / ${GB(v.total_mb)}`
                          : ''}
                      </span>
                      {v.is_evidence_store && (
                        <span className="text-accent"> · evidence store</span>
                      )}
                    </span>
                  </div>
                ))}
                {volumes.length > 3 && (
                  <button
                    type="button"
                    onClick={() => setShowAllVolumes(s => !s)}
                    className="text-[10px] font-mono uppercase tracking-widest text-accent hover:underline mt-1 bg-transparent border-0 p-0 cursor-pointer"
                  >
                    {showAllVolumes
                      ? 'Show fewer volumes'
                      : `Show all ${volumes.length} volumes`}
                  </button>
                )}
                {(info.disk_read_mb != null || info.disk_write_mb != null) && (
                  <p className="text-[10px] font-mono text-ink-2 mt-1">
                    I/O since boot: read {GB(info.disk_read_mb)} · written{' '}
                    {GB(info.disk_write_mb)}
                  </p>
                )}
              </Section>

              {/* ── Network ── */}
              <Section
                icon={Network}
                title="Network Adapters"
                count={info.network_count}
              >
                {adapters.length === 0 && (
                  <p className="text-xs text-ink-2">
                    No network interfaces reported.
                  </p>
                )}
                {adapters.map((a, i) => (
                  <div
                    key={`${a.name}-${i}`}
                    className="flex items-start justify-between gap-4 py-0.5"
                  >
                    <span className="text-xs text-ink-2 shrink-0">
                      {a.virtual ? 'Virtual' : a.up ? 'Connected' : 'Down'}
                    </span>
                    <span className="text-xs text-ink-0 text-right font-mono break-words">
                      {a.name}
                      <span className="text-ink-2">
                        {a.mac && a.mac !== '-' ? ` · ${a.mac}` : ''}
                        {a.ips && a.ips.length ? ` · ${a.ips[0]}` : ''}
                      </span>
                    </span>
                  </div>
                ))}
              </Section>
            </>
          )}

          {/* Advisory: the local LLM needs commit headroom this box lacks. */}
          {info && !info.swap_total_mb && (
            <p className="text-[10px] text-warning flex items-start gap-1.5 mt-4 bg-surface-3 rounded px-2 py-1.5">
              <ShieldAlert size={12} className="shrink-0 mt-px" />
              <span>
                No pagefile is configured, so the OS commits only physical
                RAM. A local LLM may fail to load on this machine even
                though RAM looks sufficient.
              </span>
            </p>
          )}

          {/* Evidence store headroom. This is the number that decides
              whether a multi-hundred-GB disk image can be accepted. */}
          {info?.evidence_free_mb > 0 && (
            <p
              className={`text-[10px] flex items-start gap-1.5 mt-2 ${
                info.evidence_free_mb < 40960 ? 'text-warning' : 'text-ink-2'
              }`}
            >
              <HardDrive size={12} className="shrink-0 mt-px" />
              <span>
                Evidence store on {info.evidence_store_volume} has{' '}
                {GB(info.evidence_free_mb)} free of{' '}
                {GB(info.evidence_total_mb)}
                {info.evidence_free_mb < 40960 &&
                  ' — a disk image larger than this will not fit. Point IDFAI_DATA_DIR at a bigger volume, or free space, before ingesting it.'}
              </span>
            </p>
          )}

          {info?.is_laptop && info.on_ac === false && (
            <p className="text-[10px] text-ink-2 flex items-center gap-1.5 mt-2">
              <Battery size={12} />
              Running on battery ({info.battery_percent}%) — long ingestion
              jobs will be slower and may suspend.
            </p>
          )}

          {info && (
            <p className="text-[10px] font-mono text-ink-3 mt-3">
              Auto-detected · last scan{' '}
              {info.scanned_at
                ? new Date(info.scanned_at * 1000).toLocaleTimeString()
                : '—'}
            </p>
          )}

          {extra}
        </div>
      )}
    </div>
  )
}
