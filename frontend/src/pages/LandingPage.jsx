import React from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Shield, Network, Bot,
  HardDrive, FileText,
  Lock, ChevronRight, Activity,
  Search, AlertTriangle,
  Key, Globe, LayoutDashboard, LogOut
} from 'lucide-react'
import { useAuth } from '../context/AuthContext'

const FEATURES = [
  {
    icon: HardDrive,
    title: 'Forensic Ingestion',
    desc: 'Parse .E01, .001, .dd disk images. Extract every file, email, browser history and registry entry automatically.',
    color: '#0284c7',
  },
  {
    icon: Bot,
    title: 'AI Investigation',
    desc: 'Ask questions in natural language. Every answer is grounded in evidence with full source citations.',
    color: '#2563eb',
  },
  {
    icon: Network,
    title: 'Entity Relationship Graph',
    desc: 'Visualise connections between people, locations, devices and IP addresses across all evidence.',
    color: '#06b6d4',
  },
  {
    icon: Shield,
    title: 'Chain of Custody',
    desc: 'SHA-256 integrity verification, full audit trail, and signed PDF reports for every action taken.',
    color: '#10b981',
  },
  {
    icon: Key,
    title: 'Credential Scanner',
    desc: 'Automatically detect passwords, API keys, private keys and tokens hidden within evidence files.',
    color: '#f59e0b',
  },
  {
    icon: Globe,
    title: 'Geographic Intelligence',
    desc: 'Plot GPS coordinates from EXIF metadata and geolocate IP addresses on an interactive map.',
    color: '#ef4444',
  },
]

const STATS = [
  { value: '15+', label: 'File formats' },
  { value: 'AES', label: 'Encryption' },
  { value: '100%', label: 'Air-gapped' },
  { value: 'SHA-256', label: 'Integrity' },
]

export default function LandingPage() {
  const { user, signOut } = useAuth()
  const navigate = useNavigate()

  return (
    <div style={{
      minHeight: '100vh',
      background: 'var(--bg-app)',
      color: 'var(--text-primary)',
      fontFamily: 'Inter, system-ui, sans-serif',
      position: 'relative',
      overflowY: 'auto',
      overflowX: 'hidden',
    }}>

      {/* Animated background blobs */}
      <div style={{
        position: 'fixed', inset: 0,
        zIndex: 0, pointerEvents: 'none',
      }}>
        {/* Dot grid */}
        <div style={{
          position: 'absolute', inset: 0,
          backgroundImage:
            'radial-gradient(circle,' +
            'rgba(255,255,255,0.045) 1px,' +
            'transparent 1px)',
          backgroundSize: '28px 28px',
        }} />
        {/* Blobs */}
        <div style={{
          position: 'absolute',
          top: '-15%', left: '-10%',
          width: '50%', height: '50%',
          borderRadius: '50%',
          background:
            'radial-gradient(ellipse,' +
            'rgba(2,132,199,0.18) 0%,' +
            'transparent 70%)',
          animation:
            'blob-move-1 18s ease-in-out infinite',
        }} />
        <div style={{
          position: 'absolute',
          bottom: '-10%', right: '-5%',
          width: '45%', height: '45%',
          borderRadius: '50%',
          background:
            'radial-gradient(ellipse,' +
            'rgba(6,182,212,0.15) 0%,' +
            'transparent 70%)',
          animation:
            'blob-move-2 22s ease-in-out infinite',
        }} />
        {/* Vignette */}
        <div style={{
          position: 'absolute', inset: 0,
          background:
            'radial-gradient(ellipse at 50% 0%,' +
            'transparent 40%,' +
            'rgba(4,5,11,0.7) 100%)',
        }} />
      </div>

      {/* Top nav */}
      <nav style={{
        position: 'relative', zIndex: 10,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '12px 4vw',
        borderBottom: '1px solid var(--line-DEFAULT)',
        background: 'var(--surface-1)',
        backdropFilter: 'blur(10px)',
      }}>
        <div style={{
          display: 'flex',
          alignItems: 'center', gap: 8,
        }}>
          <div style={{
            width: 28, height: 28,
            borderRadius: 8,
            background: 'linear-gradient(135deg, #0284c7, #2563eb)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 4px 12px rgba(2,132,199,0.35)',
          }}>
            <Shield size={14} color="white"/>
          </div>
          <div>
            <span style={{
              fontSize: 17,
              fontWeight: 700,
              color: 'var(--text-primary)',
              letterSpacing: '-0.02em',
            }}>
              IDF AI
            </span>
            <span style={{
              fontSize: 12,
              color: 'var(--text-secondary)',
              marginLeft: 8,
            }}>
              Intelligent Digital Forensic AI Assistant
            </span>
          </div>
        </div>

        <div style={{
          display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            padding: '4px 12px',
            borderRadius: 20,
            background: 'rgba(16,185,129,0.1)',
            border: '1px solid rgba(16,185,129,0.25)',
            fontSize: 12,
            color: '#059669',
            fontWeight: 500,
          }}>
            <span style={{
              width: 6, height: 6,
              borderRadius: '50%',
              background: '#10b981',
              boxShadow: '0 0 6px #10b981',
              animation: 'pulse-glow 2s ease infinite',
            }} />
            Air-gapped · Local AI
          </div>

          <button
            onClick={() => navigate('/dashboard')}
            style={{
              padding: '7px 18px',
              borderRadius: 8,
              background: 'linear-gradient(135deg, #0284c7, #2563eb)',
              border: 'none',
              color: '#ffffff',
              fontSize: 14,
              fontWeight: 500,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              boxShadow: '0 2px 10px rgba(2,132,199,0.3)',
            }}>
            <LayoutDashboard size={14} />
            Dashboard
            <ChevronRight size={13} />
          </button>

          <button
            onClick={() => signOut()}
            title="Sign Out"
            style={{
              padding: '7px 12px',
              borderRadius: 8,
              background: 'var(--surface-2)',
              border: '1px solid var(--line-DEFAULT)',
              color: 'var(--text-secondary)',
              fontSize: 13,
              fontWeight: 500,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: 5,
            }}>
            <LogOut size={13} />
            Sign Out
          </button>
        </div>
      </nav>

      {/* Hero section */}
      <div style={{
        position: 'relative', zIndex: 1,
        maxWidth: '100%',
        margin: '0 auto',
        padding: '24px 4vw 16px',
        display: 'flex',
        gap: '2.5vw',
        justifyContent: 'space-between',
        alignItems: 'center',
        flexWrap: 'wrap',
      }}>
        {/* Left Column: Copy & Actions */}
        <div style={{ flex: '1 1 440px', textAlign: 'left' }}>
          {/* Badge */}
          <div style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            padding: '4px 12px',
            borderRadius: 20,
            background: 'rgba(2,132,199,0.1)',
            border: '1px solid rgba(2,132,199,0.25)',
            fontSize: 12,
            fontWeight: 500,
            color: '#0284c7',
            marginBottom: 12,
          }}>
            <Lock size={12} />
            Secure · Local · Air-gapped
          </div>

          <h1 style={{
            fontSize: 'clamp(28px, 3.2vw, 42px)',
            fontWeight: 800,
            letterSpacing: '-0.03em',
            lineHeight: 1.15,
            marginBottom: 12,
          }}>
            <span style={{
              background: 'linear-gradient(135deg, var(--text-primary) 40%, #0284c7 100%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
            }}>
              Digital Forensics
            </span>
            <br />
            <span style={{
              background: 'linear-gradient(135deg, #0284c7 0%, #2563eb 100%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
            }}>
              Powered by AI
            </span>
          </h1>

          <p style={{
            fontSize: 15,
            color: 'var(--text-secondary)',
            maxWidth: 620,
            marginBottom: 20,
            lineHeight: 1.5,
          }}>
            Ingest forensic disk images, extract evidence, map entity relationships, and conduct AI-assisted investigations — entirely offline, entirely under your control.
          </p>

          {/* CTA buttons */}
          <div style={{
            display: 'flex',
            gap: 12,
            marginBottom: 24,
          }}>
            <button
              onClick={() => navigate('/dashboard')}
              style={{
                padding: '10px 22px',
                borderRadius: 10,
                background: 'linear-gradient(135deg, #0284c7, #2563eb)',
                border: 'none',
                color: 'var(--color-white-full)',
                fontSize: 14,
                fontWeight: 600,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                boxShadow: '0 4px 16px rgba(2,132,199,0.35)',
              }}>
              <LayoutDashboard size={16} />
              Open Dashboard
            </button>
            <button
              onClick={() => navigate('/cases')}
              style={{
                padding: '10px 20px',
                borderRadius: 10,
                background: 'var(--surface-2)',
                border: '1px solid var(--line-DEFAULT)',
                color: 'var(--text-primary)',
                fontSize: 14,
                fontWeight: 500,
                cursor: 'pointer',
              }}>
              View Cases
            </button>
          </div>

          {/* Stat pills */}
          <div style={{
            display: 'flex',
            gap: 10, flexWrap: 'wrap',
          }}>
            {STATS.map(s => (
              <div key={s.label} style={{
                padding: '6px 14px',
                borderRadius: 10,
                background: 'var(--surface-2)',
                border: '1px solid var(--line-DEFAULT)',
              }}>
                <p style={{
                  fontSize: 20,
                  fontWeight: 700,
                  color: 'var(--brand-primary)',
                  lineHeight: 1.1,
                }}>
                  {s.value}
                </p>
                <p style={{
                  fontSize: 11,
                  color: 'var(--text-secondary)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                  marginTop: 2,
                }}>
                  {s.label}
                </p>
              </div>
            ))}
          </div>
          
          {/* Bottom disclaimer for left column */}
          <p style={{
            fontSize: 12,
            color: 'var(--text-muted)',
            marginTop: 16,
            lineHeight: 1.4,
          }}>
            All processing is performed locally. No data leaves your machine. No cloud services.
          </p>
        </div>

        {/* Right Column: Features Grid */}
        <div style={{ flex: '1 1 440px' }}>
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(2, 1fr)',
            gap: 10,
          }}>
            {FEATURES.map((f, i) => (
              <div
                key={f.title}
                className="animate-fade-up"
                style={{
                  background: 'var(--surface-1)',
                  border: '1px solid var(--line-DEFAULT)',
                  borderRadius: 12,
                  padding: '14px 16px',
                  transition: 'all 0.2s',
                  animationDelay: `${i * 80}ms`,
                }}
                onMouseEnter={e => {
                  e.currentTarget.style.borderColor = `${f.color}`
                  e.currentTarget.style.background = 'var(--surface-2)'
                  e.currentTarget.style.transform = 'translateY(-2px)'
                }}
                onMouseLeave={e => {
                  e.currentTarget.style.borderColor = 'var(--line-DEFAULT)'
                  e.currentTarget.style.background = 'var(--surface-1)'
                  e.currentTarget.style.transform = 'translateY(0)'
                }}
              >
                <div style={{
                  width: 36, height: 36,
                  borderRadius: 9,
                  background: `${f.color}18`,
                  border: `1px solid ${f.color}30`,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  marginBottom: 8,
                }}>
                  <f.icon size={18} style={{ color: f.color }} />
                </div>
                <p style={{
                  fontSize: 15,
                  fontWeight: 600,
                  color: 'var(--text-primary)',
                  marginBottom: 4,
                  letterSpacing: '-0.01em',
                }}>
                  {f.title}
                </p>
                <p style={{
                  fontSize: 12,
                  color: 'var(--text-secondary)',
                  lineHeight: 1.4,
                }}>
                  {f.desc}
                </p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
