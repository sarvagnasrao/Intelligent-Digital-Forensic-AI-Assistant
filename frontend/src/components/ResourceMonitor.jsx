import React, { useState, useEffect, useCallback } from 'react'
import {
  Cpu, MemoryStick, HardDrive, ChevronDown, ChevronUp,
  RefreshCw, Monitor, Battery, Server, ShieldAlert,
} from 'lucide-react'
import { getSystemInfo, rescanSystemInfo } from '../api/client'
import { refreshSystemInfo } from '../hooks/useSystemInfo'
import usePreferences from '../hooks/usePreferences'

/**
 * Live hardware load monitor.
 *
 * The default view is deliberately small: three independent gauges - CPU,
 * memory, GPU - plus a VRAM meter and a storage line. That is the question an
 * operator actually has while an ingest runs: which of the three is the
 * bottleneck, and did the GPU get used at all. They do not move together (a job
 * can sit at 90% RAM with the CPU idle, or peg the GPU while memory is
 * untouched), so each gets its own bar and its own scale rather than sharing
 * one. See LoadGauge for the unmeasurable case, which is a real state here - a
 * machine with no telemetry source must never be drawn as "0% busy".
 *
 * Everything else this component knows - per-adapter GPU rows, the CPU, RAM
 * and pagefile the ingestion budget is derived from, the mounted volumes -
 * sits behind "Show device details". It is all genuinely re-detected rather
 * than hardcoded (the backend re-walks the hardware whenever the attached
 * device set changes, so plugging in an evidence drive or an eGPU shows up on
 * its own). But it is a long list of static facts, and leaving it expanded
 * buries the three live numbers it is supposed to support.
 *
 * Deliberately NOT shown: the network adapter list, and the machine's
 * serialisable identity (chassis, BIOS, hostname, OS version). A NIC list
 * carries no information about resource use, and identifying the host is not
 * resource monitoring - the audit log already records what machine a case was
 * worked on. Both are still available from the backend (`network_adapters`,
 * `machine_*`) for anything that genuinely needs them.
 *
 * Rendered on both the Evidence page and the Queue page so an operator sees an
 * identical description in both places.
 *
 * Honours the "System resource monitoring" preference in
 * Settings > Preferences: when switched off this component renders nothing
 * and stops polling entirely, so an investigator who does not care about
 * hardware pays nothing for it.
 */

const GB = (mb) => (mb == null ? '—' : `${(mb / 1024).toFixed(1)} GB`)

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

/**
 * One resource, measured on its own scale, with its own bar.
 *
 * The point of separating these is that they are independent: a job can sit at
 * 90% RAM with the CPU idle, or peg the GPU while memory is untouched. A single
 * shared bar cannot show that, and an operator watching an ingest needs to
 * know which of the three is the bottleneck.
 *
 * `percent === null` is a first-class state, not zero. The backend reports a
 * metric it cannot measure as null with a reason, and rendering that as "0%"
 * would claim an idle GPU during a transcription that is quietly running on
 * the CPU - the exact lie the null is there to prevent. So an unknown reading
 * shows an em dash, a neutral track, and the reason.
 */
function LoadGauge({ icon: Icon, label, percent, detail, note, toneFor }) {
  const known = percent != null && !Number.isNaN(percent)
  const clamped = known ? Math.min(100, Math.max(0, percent)) : 0
  const tone = known ? toneFor(clamped) : 'bg-ink-3'
  const textTone = known ? toneFor(clamped).replace('bg-', 'text-') : 'text-ink-2'

  return (
    <div className="min-w-0">
      <p className="text-xs text-ink-2 mb-1 flex items-center gap-1">
        <Icon size={11} className="shrink-0" />
        <span className="truncate">{label}</span>
      </p>
      <p className={`text-xl font-bold tabular-nums truncate ${textTone}`}>
        {known ? `${clamped.toFixed(0)}%` : '—'}
        {detail && (
          <span className="text-xs font-normal text-ink-2 ml-1.5">
            {detail}
          </span>
        )}
      </p>
      <div
        className="h-1.5 bg-surface-3 rounded-full overflow-hidden mt-2"
        role="meter"
        aria-label={label}
        aria-valuenow={known ? Math.round(clamped) : undefined}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuetext={known ? `${Math.round(clamped)} percent` : 'not measurable'}
      >
        <div
          className={`h-full rounded-full transition-all duration-500 ${tone}`}
          style={{ width: `${clamped}%` }}
        />
      </div>
      {(note || !known) && (
        <p className="text-[10px] text-ink-2 mt-1 leading-snug">
          {note || 'Not measurable on this machine'}
        </p>
      )}
    </div>
  )
}

/**
 * Per-logical-core CPU load, as a strip of thin bars.
 *
 * Worth showing during ingestion: a transcription pinned to one core looks
 * identical to a balanced workload on a single averaged percentage, and the
 * two call for different amounts of throttling. Capped so a 64-core server
 * does not render 64 slivers.
 */
const MAX_CORE_BARS = 16

function CoreStrip({ perCore }) {
  if (!Array.isArray(perCore) || perCore.length === 0) return null
  const shown = perCore.slice(0, MAX_CORE_BARS)
  const hidden = perCore.length - shown.length

  return (
    <div className="mt-2">
      <div className="flex items-end gap-[2px] h-6" aria-hidden="true">
        {shown.map((value, i) => {
          const known = value != null
          const h = known ? Math.max(4, Math.min(100, value)) : 0
          return (
            <div
              key={i}
              className={`flex-1 rounded-sm transition-all duration-500 ${
                known
                  ? value >= 90 ? 'bg-danger'
                    : value >= 70 ? 'bg-warning' : 'bg-accent'
                  : 'bg-surface-3'
              }`}
              style={{ height: `${h}%` }}
            />
          )
        })}
      </div>
      <p className="text-[10px] font-mono text-ink-2 mt-1">
        {shown.length} logical core{shown.length === 1 ? '' : 's'}
        {hidden > 0 ? ` (+${hidden} more not shown)` : ''}
      </p>
    </div>
  )
}

/** Shared "everything is fine" tone ladder, for a resource where high is bad. */
const pressureTone = (warn, danger) => (percent) =>
  percent >= danger ? 'bg-danger'
    : percent >= warn ? 'bg-warning' : 'bg-accent'

/**
 * High GPU utilisation during an ingest is the *desired* outcome - it means
 * Whisper reached the card instead of falling back to the CPU - so the bar is
 * tinted positively rather than alarmed. VRAM pressure is the thing that
 * actually goes wrong, and it gets its own meter below.
 */
const gpuTone = (percent) => (percent >= 90 ? 'bg-success' : 'bg-accent')

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
  // The full device inventory (chassis, BIOS, per-adapter rows, every volume,
  // every NIC) is reference material, not a live reading, so it is collapsed
  // by default. The thing an operator watches during an ingest is which of
  // CPU, memory and GPU is the bottleneck, and a wall of static specs pushes
  // that off the panel. Nothing is lost - it is one click away - but it no
  // longer competes with the three gauges for attention.
  const [showInventory, setShowInventory] = useState(false)

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

  // Every one of these may be null. `?? 0` is deliberately NOT used: a missing
  // measurement and an idle machine must not look the same. See LoadGauge.
  const cpuPct = info?.cpu_percent ?? null
  const ramPct = info?.ram_percent ?? null
  const gpuPct = info?.gpu_util_available ? info.gpu_util_percent : null
  const diskPct = info?.disk_percent ?? null

  const volumes = info?.volumes || []
  const shownVolumes = showAllVolumes ? volumes : volumes.slice(0, 3)
  const gpus = info?.gpus || []

  // The backend's reason is shown whenever it has one, *including* when a
  // number is available. On a mixed machine - a discrete card plus an
  // integrated one that exposes no counter - the aggregate is the busiest
  // measured adapter, not a reading of the whole machine. Suppressing the note
  // just because a number came back would turn "the one card I could measure is
  // idle" into "the GPU is idle", which is the lie this panel exists to avoid.
  const gpuReason = info?.gpu_telemetry_reason
    || (info?.gpu_util_available ? null : 'No GPU utilisation source on this machine')
  const gpuMeasured = info?.gpu_adapters_measured
  const gpuTotal = info?.gpu_adapters_total
  const gpuPartial = gpuTotal > 1 && gpuMeasured != null && gpuMeasured < gpuTotal
  const vramUsed = info?.gpu_vram_used_mb ?? null
  // The denominator MUST be the one covering the same adapters as the
  // numerator. `gpu_vram_total_mb` is summed over every card in the inventory,
  // while `gpu_vram_used_mb` only sums the cards that were actually measured -
  // so pairing them yields a ratio of two different populations, which on a
  // mixed machine understates by roughly the unmeasured share. The backend
  // therefore reports a measured-only total, and that wins when present.
  const vramTotal =
    info?.gpu_vram_measured_total_mb || info?.gpu_vram_total_mb || null
  const vramPct = vramUsed != null && vramTotal
    ? (vramUsed / vramTotal) * 100
    : null

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
              {/* ── Live load: three independent resources ──
                  Each has its own bar, its own scale and its own
                  unmeasurable state, because they do not move together. */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
                <LoadGauge
                  icon={Cpu}
                  label="CPU"
                  percent={cpuPct}
                  toneFor={pressureTone(70, 90)}
                  detail={`${info.cpu_count_physical || info.cpu_count || '?'}C/${info.cpu_count_logical || '?'}T`}
                  note="Sustained load above the queue ceiling throttles ingestion"
                />
                {/* `swap_used_mb` is passed through untouched. An `|| 0` here
                    would render a pagefile whose used-bytes could not be read
                    as "0.0 GB swap", i.e. "swap is idle" - the same fabricated
                    quiet a null GPU reading would imply during a CPU
                    transcription. GB() already maps null to an em dash. */}
                <LoadGauge
                  icon={MemoryStick}
                  label="Memory"
                  percent={ramPct}
                  toneFor={pressureTone(75, 90)}
                  detail={`${GB(info.available_ram_mb)} free`}
                  note={info.swap_total_mb
                    ? `of ${GB(info.total_ram_mb)} · ${GB(info.swap_used_mb)} swap`
                    : `of ${GB(info.total_ram_mb)} · no pagefile`}
                />
                <div>
                  <LoadGauge
                    icon={Monitor}
                    label="GPU"
                    percent={gpuPct}
                    toneFor={gpuTone}
                    detail={info.gpu_count
                      ? `${info.gpu_count} adapter${info.gpu_count === 1 ? '' : 's'}`
                      : undefined}
                    note={gpuReason}
                  />
                  {/* When only some adapters are measurable, the number is the
                      busiest of those - say so on the label, where it cannot be
                      skimmed past as "the GPU". */}
                  {gpuPartial && (
                    <p className="text-[10px] font-mono text-ink-2 mt-1">
                      busiest of {gpuMeasured}/{gpuTotal} measured
                    </p>
                  )}
                  {/* VRAM gets its own meter: it is the part of the GPU
                      that actually runs out during an ingest. */}
                  {vramPct != null && (
                    <div className="mt-2">
                      <div className="h-1 bg-surface-3 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all duration-500 ${
                            vramPct >= 92 ? 'bg-danger'
                              : vramPct >= 75 ? 'bg-warning' : 'bg-accent'
                          }`}
                          style={{ width: `${Math.min(100, vramPct)}%` }}
                        />
                      </div>
                      <p className="text-[10px] font-mono text-ink-2 mt-1">
                        VRAM {GB(vramUsed)} of {GB(vramTotal)}
                      </p>
                    </div>
                  )}
                </div>
              </div>

              {/* Per-core detail, under the CPU gauge it belongs to. */}
              {cpuPct != null && (
                <CoreStrip perCore={info.cpu_per_core_percent} />
              )}

              {/* Storage is a capacity fact rather than a load metric, so it
                  gets a line rather than a fourth competing gauge. */}
              <div className="mt-4 pt-3 border-t border-line">
                <div className="flex items-center justify-between gap-4">
                  <p className="text-xs text-ink-2 flex items-center gap-1.5">
                    <HardDrive size={11} className="shrink-0" />
                    Storage
                  </p>
                  <p className="text-xs text-ink-0 tabular-nums">
                    {GB(info.disk_free_mb)} free
                    <span className="text-ink-2">
                      {' '}of {GB(info.disk_total_mb)}
                      {diskPct != null ? ` · ${diskPct.toFixed(0)}% used` : ''}
                    </span>
                  </p>
                </div>
                {diskPct != null && (
                  <div className="h-1.5 bg-surface-3 rounded-full overflow-hidden mt-2">
                    <div
                      className={`h-full rounded-full transition-all duration-500 ${
                        diskPct >= 90 ? 'bg-danger'
                          : diskPct >= 75 ? 'bg-warning' : 'bg-success'
                      }`}
                      style={{ width: `${Math.min(100, diskPct)}%` }}
                    />
                  </div>
                )}
              </div>

              {/* ── Detail, collapsed by default ──
                  Only what bears on an ingest: which adapter is actually being
                  measured (and which cannot be), the CPU/RAM/pagefile the
                  budget is derived from, and where the volumes are.

                  Removed: the network adapter list, and the chassis / BIOS /
                  hostname / OS identity block. A NIC list says nothing about
                  resource use, and a machine's serialisable identity is not
                  resource monitoring. Both remain available from the OS and
                  the audit log; neither earns screen space next to a running
                  transcription. */}
              <button
                type="button"
                onClick={() => setShowInventory(s => !s)}
                aria-expanded={showInventory}
                className="mt-4 w-full flex items-center justify-center gap-1.5 text-[10px] font-mono uppercase tracking-widest text-ink-2 hover:text-accent transition-colors cursor-pointer bg-surface-3 border-0 rounded py-1.5"
              >
                {showInventory
                  ? <ChevronUp size={11} />
                  : <ChevronDown size={11} />}
                {showInventory ? 'Hide device details' : 'Show device details'}
              </button>

              {showInventory && (
                <>
              <Section icon={Server} title="Processor & Memory">
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
                {gpus.map((g, i) => {
                  const util = g.util_percent ?? null
                  return (
                    <div
                      key={`${g.name}-${i}`}
                      className="py-1 first:pt-0 last:pb-0"
                    >
                      <div className="flex items-start justify-between gap-4">
                        <span className="text-xs text-ink-2 shrink-0">
                          {g.shared_memory ? 'Integrated' : 'Dedicated'}
                        </span>
                        <span className="text-xs text-ink-0 text-right font-mono break-words">
                          {g.name}
                          <span className="text-ink-2">
                            {/* Three distinct states, deliberately not
                                collapsed. "no dedicated VRAM" (integrated),
                                "total unknown" (a dedicated card we could
                                not measure) and a real figure are different
                                facts, and conflating the last two would let a
                                measurement gap read as a hardware fact. */}
                            {g.vram_total_mb
                              ? ` — ${GB(g.vram_total_mb)} VRAM`
                              : g.shared_memory
                                ? ' — shared memory, no dedicated VRAM'
                                : ' — VRAM total not measurable'}
                          </span>
                        </span>
                      </div>
                      <div className="flex items-center justify-between gap-4 mt-0.5">
                        <span className="text-[10px] font-mono text-ink-2 shrink-0">
                          {util != null
                            ? `${util}% busy`
                            : (g.gpu_telemetry_reason
                              ? 'utilisation unavailable'
                              : 'no telemetry for this adapter')}
                        </span>
                        <span className="text-[10px] font-mono text-ink-2">
                          {g.vram_used_mb != null
                            ? `${GB(g.vram_used_mb)}${
                                g.vram_total_mb ? ` of ${GB(g.vram_total_mb)}` : ''
                              } VRAM in use`
                            : 'VRAM in use unknown'}
                        </span>
                      </div>
                      {/* Per-adapter bar. Null renders as a flat neutral
                          track, so "unmeasured" cannot read as "idle". */}
                      <div className="h-1 bg-surface-3 rounded-full overflow-hidden mt-1">
                        <div
                          className={`h-full rounded-full transition-all duration-500 ${
                            util == null ? 'bg-ink-3'
                              : util >= 90 ? 'bg-success' : 'bg-accent'
                          }`}
                          style={{ width: `${util == null ? 0 : util}%` }}
                        />
                      </div>
                    </div>
                  )
                })}
                {info.gpu_vram_shared_only && gpus.length > 0 && (
                  <p className="text-[10px] text-warning mt-1">
                    No discrete GPU detected — local LLM inference will run
                    on CPU and will be slow.
                  </p>
                )}
                {/* Say plainly when a real adapter is present but cannot be
                    measured. "0% busy" here would be actively misleading. */}
                {!info.gpu_util_available && gpuReason && (
                  <p className="text-[10px] text-ink-2 mt-1">
                    {gpuReason}.
                  </p>
                )}
                {info.gpu_telemetry_source === 'nvml'
                  && info.gpu_driver_version && (
                  <p className="text-[10px] font-mono text-ink-3 mt-1">
                    Live via NVML · driver {info.gpu_driver_version}
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
                </>
              )}
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
