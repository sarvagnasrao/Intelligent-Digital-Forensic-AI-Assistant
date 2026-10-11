import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Shield, Lock, Eye, EyeOff } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { apiErrorMessage } from '../api/client'
import toast from 'react-hot-toast'

export default function LoginPage() {
  const { user, signIn } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState({ username: '', password: '' })
  const [loading, setLoading] = useState(false)
  const [showPass, setShowPass] = useState(false)

  // If already authenticated, redirect immediately to the Dashboard
  useEffect(() => {
    if (user) {
      navigate('/dashboard', { replace: true })
    }
  }, [user, navigate])

  const handleLogin = async (e) => {
    e?.preventDefault()
    if (!form.username || !form.password) {
      toast.error('Enter credentials')
      return
    }
    setLoading(true)
    try {
      const res = await signIn(form.username, form.password)
      if (res?.requires2FA) {
        navigate('/2fa')
        return
      }
      navigate('/dashboard', { replace: true })
    } catch (err) {
      toast.error(apiErrorMessage(err, 'Authentication failed'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      minHeight: '100vh',
      width: '100%',
      background: 'var(--bg-app)',
      color: 'var(--text-primary)',
      fontFamily: 'Inter, system-ui, sans-serif',
      position: 'relative',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '28px 4vw',
      overflowY: 'auto',
      overflowX: 'hidden',
      boxSizing: 'border-box',
    }}>

      {/* Ambient background decoration */}
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
        {/* Ambient Blue Blobs */}
        <div style={{
          position: 'absolute',
          top: '-10%', left: '-5%',
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

      {/* Two-Column Responsive Wrapper */}
      <div
        className="w-full max-w-[1100px] grid grid-cols-1 lg:grid-cols-[1.1fr_0.9fr] gap-8 xl:gap-14 items-center relative z-10"
        style={{
          margin: 'auto 0',
        }}
      >
        {/* Left Column: Heading and Application Name Only */}
        <div style={{ textAlign: 'left', padding: '16px 0' }}>
          <h1 style={{
            fontSize: 'clamp(32px, 3.8vw, 50px)',
            fontWeight: 800,
            letterSpacing: '-0.03em',
            lineHeight: 1.15,
            marginBottom: 16,
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
            fontSize: 17,
            fontWeight: 600,
            color: 'var(--text-secondary)',
            letterSpacing: '-0.01em',
            margin: 0,
            lineHeight: 1.4,
          }}>
            Intelligent Digital Forensic AI Assistant
          </p>
        </div>

        {/* Right Column: Dedicated Login Card (Without Registration Option) */}
        <div
          className="animate-scale-in"
          style={{
            width: '100%',
            maxWidth: 420,
            background: 'var(--surface-1)',
            border: '1px solid var(--line-DEFAULT)',
            borderRadius: 18,
            padding: '32px 30px',
            boxShadow: '0 25px 60px rgba(0,0,0,0.3)',
            justifySelf: 'center',
          }}
        >
          {/* Header */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: 26,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div style={{
                width: 38,
                height: 38,
                borderRadius: 10,
                background: 'linear-gradient(135deg, #0284c7, #2563eb)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                boxShadow: '0 4px 12px rgba(2,132,199,0.35)',
                flexShrink: 0,
              }}>
                <Shield size={18} color="white" />
              </div>
              <div>
                <p style={{
                  fontSize: 19,
                  fontWeight: 700,
                  color: 'var(--text-primary)',
                  lineHeight: 1.2,
                  margin: 0,
                }}>
                  Sign In
                </p>
                <p style={{
                  fontSize: 12.5,
                  color: 'var(--text-secondary)',
                  marginTop: 2,
                  marginBottom: 0,
                }}>
                  IDF AI Assistant
                </p>
              </div>
            </div>

            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 5,
              padding: '3px 8px',
              borderRadius: 12,
              background: 'rgba(16,185,129,0.1)',
              border: '1px solid rgba(16,185,129,0.25)',
              fontSize: 11,
              color: '#059669',
              fontWeight: 500,
            }}>
              <span style={{
                width: 5, height: 5,
                borderRadius: '50%',
                background: '#10b981',
                boxShadow: '0 0 6px #10b981',
              }} />
              Air-gapped
            </div>
          </div>

          {/* Credentials Form */}
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 15,
          }}>
            <div>
              <label style={{
                fontSize: 13,
                color: 'var(--text-primary)',
                fontWeight: 500,
                display: 'block',
                marginBottom: 6,
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
                  background: 'var(--surface-2)',
                  border: '1px solid var(--line-DEFAULT)',
                  borderRadius: 10,
                  padding: '12px 14px',
                  fontSize: 14.5,
                  color: 'var(--text-primary)',
                  outline: 'none',
                  boxSizing: 'border-box',
                }}
                onFocus={e => { e.target.style.borderColor = 'var(--brand-primary)' }}
                onBlur={e => { e.target.style.borderColor = 'var(--line-DEFAULT)' }}
              />
            </div>

            <div>
              <label style={{
                fontSize: 13,
                color: 'var(--text-primary)',
                fontWeight: 500,
                display: 'block',
                marginBottom: 6,
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
                    background: 'var(--surface-2)',
                    border: '1px solid var(--line-DEFAULT)',
                    borderRadius: 10,
                    padding: '12px 38px 12px 14px',
                    fontSize: 14.5,
                    color: 'var(--text-primary)',
                    outline: 'none',
                    boxSizing: 'border-box',
                  }}
                  onFocus={e => { e.target.style.borderColor = 'var(--brand-primary)' }}
                  onBlur={e => { e.target.style.borderColor = 'var(--line-DEFAULT)' }}
                />
                <button
                  type="button"
                  onClick={() => setShowPass(!showPass)}
                  style={{
                    position: 'absolute',
                    right: 12,
                    top: '50%',
                    transform: 'translateY(-50%)',
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    color: 'var(--text-secondary)',
                    display: 'flex',
                    padding: 0,
                  }}>
                  {showPass ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            <button
              onClick={handleLogin}
              disabled={loading}
              style={{
                width: '100%',
                padding: '13px',
                marginTop: 6,
                borderRadius: 10,
                background: loading ? 'rgba(2,132,199,0.5)' : 'linear-gradient(135deg, #0284c7, #2563eb)',
                border: 'none',
                color: '#ffffff',
                fontSize: 14.5,
                fontWeight: 600,
                cursor: loading ? 'not-allowed' : 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 8,
                boxShadow: loading ? 'none' : '0 4px 18px rgba(2,132,199,0.35)',
              }}
            >
              {loading
                ? 'Authenticating...'
                : <><Lock size={15} /> Authenticate</>}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
