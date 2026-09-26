  import React, { useState } from 'react'
  import { useNavigate } from 'react-router-dom'
  import { Shield, Network, Bot,
           HardDrive, FileText,
           Lock, Eye, EyeOff,
           ChevronRight, Activity,
           Search, AlertTriangle,
           Key, Globe } from 'lucide-react'
  import { useAuth } from '../context/AuthContext'
  import toast from 'react-hot-toast'

  const FEATURES = [
    {
      icon: HardDrive,
      title: 'Forensic Ingestion',
      desc: 'Parse .E01, .001, .dd disk images. Extract every file, email, browser history and registry entry automatically.',
      color: '#6366f1',
    },
    {
      icon: Bot,
      title: 'AI Investigation',
      desc: 'Ask questions in natural language. Every answer is grounded in evidence with full source citations.',
      color: '#8b5cf6',
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

  export default function LoginPage() {
    const { signIn } = useAuth()
    const navigate = useNavigate()
    const [form, setForm] = useState({ username: '', password: '' })
    const [loading, setLoading] = useState(false)
    const [showPass, setShowPass] = useState(false)
    const [showLogin, setShowLogin] = useState(false)

    const handleLogin = async (e) => {
      e?.preventDefault()
      if (!form.username || !form.password) {
        toast.error('Enter credentials')
        return
      }
      setLoading(true)
      try {
        await signIn(form.username, form.password)
        navigate('/')
      } catch (e) {
        toast.error(
          e.response?.data?.detail || 'Authentication failed'
        )
      } finally {
        setLoading(false)
      }
    }

    return (
      <div style={{
        minHeight: '100vh',
        background: 'var(--bg-app)',
        color: 'var(--text-primary)',
        fontFamily: 'Inter, system-ui, sans-serif',
        position: 'relative',
        overflow: 'hidden',
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
              'rgba(79,70,229,0.2) 0%,' +
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
          padding: '24px 6vw',
          borderBottom: '1px solid rgba(255,255,255,0.05)',
          background: 'rgba(4,5,11,0.6)',
          backdropFilter: 'blur(10px)',
        }}>
          <div style={{
            display: 'flex',
            alignItems: 'center', gap: 10,
          }}>
            <div style={{
              width: 32, height: 32,
              borderRadius: 9,
              background: 'linear-gradient(135deg, #4f46e5, #7c3aed)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 4px 16px rgba(99,102,241,0.4)',
            }}>
              <Shield size={16} color="white"/>
            </div>
            <div>
              <span style={{
                fontSize: 20,
                fontWeight: 700,
                letterSpacing: '-0.02em',
              }}>
                IDF AI
              </span>
              <span style={{
                fontSize: 13,
                color: 'var(--color-white-3)',
                marginLeft: 8,
              }}>
                Intelligent Digital Forensic AI Assistant
              </span>
            </div>
          </div>

          <div style={{
            display: 'flex', gap: 8 }}>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '6px 14px',
              borderRadius: 20,
              background: 'rgba(16,185,129,0.1)',
              border: '1px solid rgba(16,185,129,0.2)',
              fontSize: 13,
              color: '#34d399',
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
              onClick={() => setShowLogin(true)}
              style={{
                padding: '9px 24px',
                borderRadius: 8,
                background: '#4f46e5',
                border: 'none',
                color: 'var(--color-white-full)',
                fontSize: 15,
                fontWeight: 500,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 6,
              }}>
              Sign In
              <ChevronRight size={13} />
            </button>
          </div>
        </nav>

        {/* Hero section */}
        <div style={{
          position: 'relative', zIndex: 1,
          maxWidth: '100%',
          margin: '0 auto',
          padding: '80px 6vw 60px',
          display: 'flex',
          gap: '8vw',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
        }}>
          {/* Left Column: Copy & Actions */}
          <div style={{ flex: '1 1 500px', textAlign: 'left' }}>
            {/* Badge */}
            <div style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 8,
              padding: '6px 16px',
              borderRadius: 20,
              background: 'rgba(99,102,241,0.1)',
              border: '1px solid rgba(99,102,241,0.25)',
              fontSize: 13,
              fontWeight: 500,
              color: '#818cf8',
              marginBottom: 28,
            }}>
              <Lock size={13} />
              Secure · Local · Air-gapped
            </div>

            <h1 style={{
              fontSize: 'clamp(56px, 7vw, 84px)',
              fontWeight: 800,
              letterSpacing: '-0.04em',
              lineHeight: 1.1,
              marginBottom: 24,
            }}>
              <span style={{
                background: 'linear-gradient(135deg, #fff 0%, #c7d2fe 60%, #818cf8 100%)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
              }}>
                Digital Forensics
              </span>
              <br />
              <span style={{
                background: 'linear-gradient(135deg, #06b6d4, #818cf8)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
              }}>
                Powered by AI
              </span>
            </h1>

            <p style={{
              fontSize: 24,
              color: 'var(--color-white-6)',
              maxWidth: 700,
              marginBottom: 56,
              lineHeight: 1.6,
            }}>
              Ingest forensic disk images, extract evidence, map entity relationships, and conduct AI-assisted investigations — entirely offline, entirely under your control.
            </p>

            {/* CTA buttons */}
            <div style={{
              display: 'flex',
              gap: 16,
              marginBottom: 56,
            }}>
              <button
                onClick={() => setShowLogin(true)}
                style={{
                  padding: '18px 40px',
                  borderRadius: 14,
                  background: 'linear-gradient(135deg, #4f46e5, #7c3aed)',
                  border: 'none',
                  color: 'var(--color-white-full)',
                  fontSize: 18,
                  fontWeight: 600,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                  boxShadow: '0 8px 30px rgba(99,102,241,0.4)',
                }}>
                <Lock size={20} />
                Sign in to Investigate
              </button>
              <button
                onClick={() => navigate('/register')}
                style={{
                  padding: '18px 36px',
                  borderRadius: 14,
                  background: 'var(--color-white-05)',
                  border: '1px solid rgba(255,255,255,0.12)',
                  color: 'var(--color-white-6)',
                  fontSize: 18,
                  fontWeight: 500,
                  cursor: 'pointer',
                }}>
                Create account
              </button>
            </div>

            {/* Stat pills */}
            <div style={{
              display: 'flex',
              gap: 16, flexWrap: 'wrap',
            }}>
              {STATS.map(s => (
                <div key={s.label} style={{
                  padding: '12px 28px',
                  borderRadius: 12,
                  background: 'var(--color-white-03)',
                  border: '1px solid rgba(255,255,255,0.08)',
                }}>
                  <p style={{
                    fontSize: 32,
                    fontWeight: 700,
                    color: '#c7d2fe',
                    lineHeight: 1.2,
                  }}>
                    {s.value}
                  </p>
                  <p style={{
                    fontSize: 14,
                    color: 'var(--color-white-4)',
                    textTransform: 'uppercase',
                    letterSpacing: '0.07em',
                    marginTop: 4,
                  }}>
                    {s.label}
                  </p>
                </div>
              ))}
            </div>
            
            {/* Bottom disclaimer for left column */}
            <p style={{
              fontSize: 15,
              color: 'var(--color-white-2)',
              marginTop: 48,
              lineHeight: 1.5,
            }}>
              All processing is performed locally. No data leaves your machine. No cloud services. No external API calls for evidence.
            </p>
          </div>

          {/* Right Column: Features Grid */}
          <div style={{ flex: '1 1 500px' }}>
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(2, 1fr)',
              gap: 16,
            }}>
              {FEATURES.map((f, i) => (
                <div
                  key={f.title}
                  className="animate-fade-up"
                  style={{
                    background: 'rgba(255,255,255,0.025)',
                    border: `1px solid ${f.color}20`,
                    borderRadius: 16,
                    padding: '28px',
                    transition: 'all 0.2s',
                    animationDelay: `${i * 80}ms`,
                  }}
                  onMouseEnter={e => {
                    e.currentTarget.style.borderColor = `${f.color}50`
                    e.currentTarget.style.background = `${f.color}08`
                    e.currentTarget.style.transform = 'translateY(-2px)'
                  }}
                  onMouseLeave={e => {
                    e.currentTarget.style.borderColor = `${f.color}20`
                    e.currentTarget.style.background = 'rgba(255,255,255,0.025)'
                    e.currentTarget.style.transform = 'translateY(0)'
                  }}
                >
                  <div style={{
                    width: 52, height: 52,
                    borderRadius: 12,
                    background: `${f.color}18`,
                    border: `1px solid ${f.color}30`,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    marginBottom: 16,
                  }}>
                    <f.icon size={24} style={{ color: f.color }} />
                  </div>
                  <p style={{
                    fontSize: 20,
                    fontWeight: 600,
                    color: 'var(--text-primary)',
                    marginBottom: 8,
                    letterSpacing: '-0.01em',
                  }}>
                    {f.title}
                  </p>
                  <p style={{
                    fontSize: 16,
                    color: 'var(--color-white-4)',
                    lineHeight: 1.6,
                  }}>
                    {f.desc}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Login modal overlay */}
        {showLogin && (
          <div
            style={{
              position: 'fixed', inset: 0,
              background: 'rgba(0,0,0,0.7)',
              zIndex: 50,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: 20,
            }}
            onClick={e => {
              if (e.target === e.currentTarget) setShowLogin(false)
            }}
          >
            <div
              className="animate-scale-in"
              style={{
                width: '100%', maxWidth: 400,
                background: '#0e0f1a',
                border: '1px solid rgba(255,255,255,0.1)',
                borderRadius: 18,
                padding: 32,
                boxShadow: '0 25px 60px rgba(0,0,0,0.8)',
              }}
            >
              {/* Modal header */}
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10, marginBottom: 28,
              }}>
                <div style={{
                  width: 36, height: 36,
                  borderRadius: 10,
                  background: 'linear-gradient(135deg, #4f46e5, #7c3aed)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  boxShadow: '0 4px 12px rgba(99,102,241,0.4)',
                }}>
                  <Shield size={16} color="white" />
                </div>
                <div>
                  <p style={{
                    fontSize: 20,
                    fontWeight: 700,
                    color: 'var(--text-primary)',
                    lineHeight: 1.2,
                  }}>
                    Sign In
                  </p>
                  <p style={{
                    fontSize: 13,
                    color: 'var(--color-white-4)',
                  }}>
                    Intelligent Digital Forensic AI Assistant
                  </p>
                </div>
              </div>

              {/* Form */}
              <div style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 12,
              }}>
                <div>
                  <label style={{
                    fontSize: 13,
                    color: 'var(--color-white-5)',
                    fontWeight: 500,
                    display: 'block',
                    marginBottom: 8,
                  }}>
                    Username
                  </label>
                  <input
                    type="text"
                    value={form.username}
                    onChange={e => setForm(f => ({ ...f, username: e.target.value }))}
                    onKeyDown={e => e.key === 'Enter' && handleLogin()}
                    placeholder="Enter username"
                    autoFocus
                    style={{
                      width: '100%',
                      background: 'var(--color-white-05)',
                      border: '1px solid rgba(255,255,255,0.1)',
                      borderRadius: 10,
                      padding: '14px 16px',
                      fontSize: 15,
                      color: 'var(--text-primary)',
                      outline: 'none',
                    }}
                    onFocus={e => { e.target.style.borderColor = 'rgba(99,102,241,0.6)' }}
                    onBlur={e => { e.target.style.borderColor = 'var(--color-white-1)' }}
                  />
                </div>

                <div>
                  <label style={{
                    fontSize: 13,
                    color: 'var(--color-white-5)',
                    fontWeight: 500,
                    display: 'block',
                    marginBottom: 8,
                  }}>
                    Password
                  </label>
                  <div style={{ position: 'relative' }}>
                    <input
                      type={showPass ? 'text' : 'password'}
                      value={form.password}
                      onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                      onKeyDown={e => e.key === 'Enter' && handleLogin()}
                      placeholder="Enter password"
                      style={{
                        width: '100%',
                        background: 'var(--color-white-05)',
                        border: '1px solid rgba(255,255,255,0.1)',
                        borderRadius: 10,
                        padding: '14px 40px 14px 16px',
                        fontSize: 15,
                        color: 'var(--text-primary)',
                        outline: 'none',
                      }}
                      onFocus={e => { e.target.style.borderColor = 'rgba(99,102,241,0.6)' }}
                      onBlur={e => { e.target.style.borderColor = 'var(--color-white-1)' }}
                    />
                    <button
                      onClick={() => setShowPass(!showPass)}
                      style={{
                        position: 'absolute',
                        right: 14,
                        top: '50%',
                        transform: 'translateY(-50%)',
                        background: 'none',
                        border: 'none',
                        cursor: 'pointer',
                        color: 'var(--color-white-4)',
                        display: 'flex',
                        padding: 0,
                      }}>
                      {showPass ? <EyeOff size={18} /> : <Eye size={18} />}
                    </button>
                  </div>
                </div>

                <button
                  onClick={handleLogin}
                  disabled={loading}
                  style={{
                    width: '100%',
                    padding: '14px',
                    marginTop: 8,
                    borderRadius: 10,
                    background: loading ? 'rgba(79,70,229,0.5)' : 'linear-gradient(135deg, #4f46e5, #7c3aed)',
                    border: 'none',
                    color: 'var(--color-white-full)',
                    fontSize: 16,
                    fontWeight: 600,
                    cursor: loading ? 'not-allowed' : 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: 8,
                    boxShadow: loading ? 'none' : '0 4px 20px rgba(99,102,241,0.35)',
                  }}>
                  {loading
                    ? 'Authenticating...'
                    : <><Lock size={16} /> Authenticate</>}
                </button>

                <div style={{ textAlign: 'center', paddingTop: 12 }}>
                  <span style={{ fontSize: 14, color: 'var(--color-white-3)' }}>
                    No account?{' '}
                  </span>
                  <button
                    onClick={() => navigate('/register')}
                    style={{
                      background: 'none',
                      border: 'none',
                      color: '#818cf8',
                      fontSize: 14,
                      fontWeight: 500,
                      cursor: 'pointer',
                      fontFamily: 'inherit',
                    }}>
                    Register here
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    )
  }
