import React from 'react'
import useCountUp from '../hooks/useCountUp'

const ACCENT_COLORS = {
  indigo: {
    line: '#0284c7',
    icon: 'rgba(2,132,199,0.15)',
    text: '#38bdf8'
  },
  blue: {
    line: '#3b82f6',
    icon: 'rgba(59,130,246,0.15)',
    text: '#60a5fa'
  },
  green: {
    line: '#10b981',
    icon: 'rgba(16,185,129,0.15)',
    text: '#34d399'
  },
  purple: {
    line: '#8b5cf6',
    icon: 'rgba(139,92,246,0.15)',
    text: '#a78bfa'
  },
  yellow: {
    line: '#f59e0b',
    icon: 'rgba(245,158,11,0.15)',
    text: '#fbbf24'
  },
  red: {
    line: '#ef4444',
    icon: 'rgba(239,68,68,0.15)',
    text: '#f87171'
  },
  slate: {
    line: '#64748b',
    icon: 'rgba(100,116,139,0.15)',
    text: '#94a3b8'
  },
}

/**
 * Animated stat card with Linear-style design:
 * - Gradient accent top line
 * - Radial glow in corner
 * - Count-up animation for numeric values
 */
export default function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  accent = 'indigo',
  onClick,
  animDelay = 0,
  className = ''
}) {
  const numValue = typeof value === 'number' ? value : 0
  const displayCount = useCountUp(numValue, 600)
  const colors = ACCENT_COLORS[accent] || ACCENT_COLORS.indigo

  return (
    <div
      onClick={onClick}
      className={`stat-card ${onClick ? 'cursor-pointer' : ''} ${className}`}
      style={{ animationDelay: `${animDelay}ms` }}
    >
      {/* Top accent gradient line */}
      <div
        className="absolute inset-x-0 top-0 h-[2px] rounded-t-lg"
        style={{
          background: `linear-gradient(90deg, ${colors.line}ee, ${colors.line}44)`
        }}
      />

      {/* Subtle radial glow in top-right corner */}
      <div
        className="absolute -top-6 -right-6 w-24 h-24 rounded-full pointer-events-none"
        style={{
          background: `radial-gradient(circle, ${colors.line}18 0%, transparent 70%)`
        }}
      />

      <div className="relative">
        <div className="flex items-start justify-between mb-3">
          <p
            className="text-xs uppercase tracking-widest font-medium"
            style={{ color: '#5c6280' }}
          >
            {label}
          </p>
          <div
            className="w-7 h-7 rounded-md flex items-center justify-center shrink-0"
            style={{ background: colors.icon }}
          >
            {Icon && <Icon size={14} style={{ color: colors.text }} />}
          </div>
        </div>

        <p
          className="text-3xl font-bold tracking-tight animate-count-up tabular-nums"
          style={{
            color: '#e8eaf2',
            animationDelay: `${animDelay + 100}ms`
          }}
        >
          {typeof value === 'number'
            ? displayCount.toLocaleString()
            : value ?? '—'}
        </p>

        {sub && (
          <p className="text-xs mt-1.5 truncate" style={{ color: '#5c6280' }}>
            {sub}
          </p>
        )}
      </div>
    </div>
  )
}
