import React from 'react'

/**
 * PageLayout — shared page wrapper.
 * Uses full available width (no maxWidth cap).
 * Animate entrance with fade-in.
 */
export default function PageLayout({
  title,
  subtitle,
  actions,
  children,
  fullWidth = false,  // kept for backwards compat but no longer limits width
}) {
  return (
    <div
      className="animate-fade-in"
      style={{ width: '100%' }}
    >
      {(title || actions) && (
        <div style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          marginBottom: 18,
          gap: 12,
        }}>
          <div>
            {title && (
              <h1 style={{
                fontSize: 22,
                fontWeight: 700,
                letterSpacing: '-0.02em',
                lineHeight: 1.2,
                background: 'linear-gradient(135deg, var(--ink-0) 0%, var(--brand-primary) 100%)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
              }}>
                {title}
              </h1>
            )}
            {subtitle && (
              <p style={{
                fontSize: 14,
                color: 'var(--ink-1)',
                marginTop: 3,
                lineHeight: 1.4,
              }}>
                {subtitle}
              </p>
            )}
          </div>
          {actions && (
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              flexShrink: 0,
              marginTop: 2,
            }}>
              {actions}
            </div>
          )}
        </div>
      )}
      {children}
    </div>
  )
}

