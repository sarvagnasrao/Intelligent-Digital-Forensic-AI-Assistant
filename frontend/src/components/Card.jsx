import React from 'react'

export function Card({
  children,
  className = '',
  padding = true,
  hover = false,
  onClick
}) {
  return (
    <div
      onClick={onClick}
      className={`card
        ${padding ? 'p-4' : ''}
        ${hover
          ? 'cursor-pointer hover:border-line-bright hover:bg-surface-3 transition-all duration-150'
          : ''}
        ${className}`}
    >
      {children}
    </div>
  )
}

export function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  accent = '#0284c7',
  onClick
}) {
  return (
    <div
      onClick={onClick}
      className={`stat-card
        ${onClick
          ? 'cursor-pointer hover:bg-surface-3 transition-all duration-150'
          : ''}`}
      style={{ '--tw-gradient-from': accent }}
    >
      {/* Top accent line */}
      <div
        className="absolute inset-x-0 top-0 h-[2px] rounded-t-lg"
        style={{ background: accent }}
      />
      <div className="flex items-start justify-between">
        <p className="text-xs text-ink-2 uppercase tracking-widest font-medium">
          {label}
        </p>
        <div
          className="w-8 h-8 rounded flex items-center justify-center shrink-0"
          style={{ background: `${accent}22` }}
        >
          {Icon && (
            <Icon size={15} style={{ color: accent }} />
          )}
        </div>
      </div>
      <p className="text-3xl font-bold text-ink-0 mt-3 tracking-tight">
        {value ?? '—'}
      </p>
      {sub && (
        <p className="text-xs text-ink-2 mt-1.5">{sub}</p>
      )}
    </div>
  )
}
