import React, { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Lock, Eye, EyeOff, CheckCircle, Shield, QrCode, User, Settings2, Link as LinkIcon } from 'lucide-react'
import { changePassword, getPreferences, updatePreferences, setup2FA, verify2FA, disable2FA } from '../api/client'
import { useAuth } from '../context/AuthContext'
import toast from 'react-hot-toast'
import PageLayout from '../components/PageLayout'
import { useTheme } from '../context/ThemeContext'
import { cachePreferences } from '../hooks/usePreferences'

const inputStyle = {
  width: '100%',
  background: 'var(--color-white-04)',
  border: '1px solid rgba(255,255,255,0.09)',
  borderRadius: 9,
  padding: '10px 12px',
  fontSize: 13,
  color: 'var(--text-primary)',
  outline: 'none',
  boxSizing: 'border-box',
}

const selectStyle = {
  ...inputStyle,
  appearance: 'none',
  cursor: 'pointer'
}

function AccountTab({ user }) {
  return (
    <div className="animate-fade-in" style={{ maxWidth: 420 }}>
      <div style={{
        background: 'var(--color-white-03)',
        border: '1px solid rgba(255,255,255,0.07)',
        borderRadius: 14,
        padding: 24,
      }}>
        <div style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 11, color: 'var(--color-white-3)', textTransform: 'uppercase', letterSpacing: '0.08em', display: 'block', marginBottom: 6 }}>
            Username
          </label>
          <input value={user?.username || ''} readOnly style={{ ...inputStyle, color: 'var(--color-white-4)', background: 'transparent' }} />
        </div>
        <div style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 11, color: 'var(--color-white-3)', textTransform: 'uppercase', letterSpacing: '0.08em', display: 'block', marginBottom: 6 }}>
            Full Name
          </label>
          <input value={user?.full_name || ''} readOnly style={{ ...inputStyle, color: 'var(--color-white-4)', background: 'transparent' }} />
        </div>
        <div style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 11, color: 'var(--color-white-3)', textTransform: 'uppercase', letterSpacing: '0.08em', display: 'block', marginBottom: 6 }}>
            Email
          </label>
          <input value={user?.email || ''} readOnly style={{ ...inputStyle, color: 'var(--color-white-4)', background: 'transparent' }} />
        </div>
        <div style={{ marginBottom: 8 }}>
          <label style={{ fontSize: 11, color: 'var(--color-white-3)', textTransform: 'uppercase', letterSpacing: '0.08em', display: 'block', marginBottom: 6 }}>
            Role
          </label>
          <input value={user?.role || ''} readOnly style={{ ...inputStyle, color: 'var(--color-white-4)', background: 'transparent' }} />
        </div>
      </div>
    </div>
  )
}

function PreferencesTab() {
  const { setTheme } = useTheme()
  const [prefs, setPrefs] = useState({
    theme: 'dark',
    timezone: 'UTC',
    show_system_resources: true,
  })
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    loadPrefs()
  }, [])

  const loadPrefs = async () => {
    setLoading(true)
    try {
      const res = await getPreferences()
      setPrefs({
        theme: res.data.theme,
        timezone: res.data.timezone,
        // Absent on servers that predate this preference - default to on.
        show_system_resources: res.data.show_system_resources !== false,
      })
    } catch {
      toast.error('Failed to load preferences')
    } finally {
      setLoading(false)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      await updatePreferences({
        theme: prefs.theme,
        timezone: prefs.timezone,
        show_system_resources: prefs.show_system_resources,
      })
      cachePreferences({ ...prefs })
      setTheme(prefs.theme)
      toast.success('Preferences saved')
    } catch {
      toast.error('Failed to save preferences')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return null

  return (
    <div className="animate-fade-in" style={{ maxWidth: 420 }}>
      <div style={{
        background: 'var(--color-white-03)',
        border: '1px solid rgba(255,255,255,0.07)',
        borderRadius: 14,
        padding: 24,
      }}>
        <div style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 11, color: 'var(--color-white-3)', textTransform: 'uppercase', letterSpacing: '0.08em', display: 'block', marginBottom: 6 }}>
            Theme
          </label>
          <select 
            value={prefs.theme} 
            onChange={e => setPrefs(p => ({ ...p, theme: e.target.value }))}
            style={selectStyle}
          >
            <option value="dark">Dark</option>
            <option value="light">Light</option>
            <option value="system">System Default</option>
          </select>
        </div>
        <div style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 11, color: 'var(--color-white-3)', textTransform: 'uppercase', letterSpacing: '0.08em', display: 'block', marginBottom: 6 }}>
            Timezone
          </label>
          <select 
            value={prefs.timezone} 
            onChange={e => setPrefs(p => ({ ...p, timezone: e.target.value }))}
            style={selectStyle}
          >
            <option value="UTC">UTC (Recommended for Forensics)</option>
            <option value="Local">Local Time</option>
          </select>
        </div>

        {/* Hardware telemetry - optional, some investigators never want it */}
        <div style={{
          marginBottom: 24,
          padding: 14,
          borderRadius: 10,
          border: '1px solid rgba(255,255,255,0.07)',
          background: 'var(--color-white-04)',
          display: 'flex',
          alignItems: 'center',
          gap: 14,
        }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, color: 'var(--text-primary)', fontWeight: 500, marginBottom: 3 }}>
              System resource monitoring
            </div>
            <div style={{ fontSize: 11, color: 'var(--color-white-4)', lineHeight: 1.5 }}>
              Show live CPU, RAM and queue telemetry on the Evidence page.
              Turn off to hide hardware settings you do not use.
            </div>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={prefs.show_system_resources}
            aria-label="System resource monitoring"
            title={prefs.show_system_resources ? 'Monitoring on' : 'Monitoring off'}
            onClick={() => setPrefs(p => ({ ...p, show_system_resources: !p.show_system_resources }))}
            style={{
              flexShrink: 0,
              width: 42,
              height: 24,
              borderRadius: 12,
              border: 'none',
              padding: 0,
              cursor: 'pointer',
              position: 'relative',
              background: prefs.show_system_resources
                ? 'linear-gradient(90deg, #6366f1, #4f46e5)'
                : 'rgba(255,255,255,0.14)',
              transition: 'background 0.2s ease',
            }}
          >
            <span style={{
              position: 'absolute',
              top: 3,
              left: prefs.show_system_resources ? 21 : 3,
              width: 18,
              height: 18,
              borderRadius: '50%',
              background: '#fff',
              boxShadow: '0 1px 3px rgba(0,0,0,0.35)',
              transition: 'left 0.2s ease',
            }} />
          </button>
        </div>

        <button
          onClick={handleSave}
          disabled={saving}
          style={{
            width: '100%', padding: '11px', borderRadius: 9,
            background: saving ? 'rgba(79,70,229,0.5)' : '#4f46e5',
            border: 'none', color: 'var(--color-white-full)', fontSize: 13, fontWeight: 500,
            cursor: saving ? 'not-allowed' : 'pointer',
          }}
        >
          {saving ? 'Saving...' : 'Save Preferences'}
        </button>
      </div>
    </div>
  )
}

function IntegrationsTab() {
  const [keys, setKeys] = useState({ openai: '', virustotal: '' })
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    loadPrefs()
  }, [])

  const loadPrefs = async () => {
    setLoading(true)
    try {
      const res = await getPreferences()
      setKeys({
        openai: res.data.api_keys?.openai || '',
        virustotal: res.data.api_keys?.virustotal || ''
      })
    } catch {
      toast.error('Failed to load integrations')
    } finally {
      setLoading(false)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      await updatePreferences({ api_keys: keys })
      toast.success('Integrations saved')
    } catch {
      toast.error('Failed to save integrations')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return null

  return (
    <div className="animate-fade-in" style={{ maxWidth: 420 }}>
      <div style={{
        background: 'var(--color-white-03)',
        border: '1px solid rgba(255,255,255,0.07)',
        borderRadius: 14,
        padding: 24,
      }}>
        <p style={{ fontSize: 12, color: 'var(--color-white-4)', marginBottom: 20 }}>
          API keys are stored securely and used by the backend to fetch intelligence during investigations.
        </p>
        <div style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 11, color: 'var(--color-white-3)', textTransform: 'uppercase', letterSpacing: '0.08em', display: 'block', marginBottom: 6 }}>
            OpenAI API Key
          </label>
          <input 
            type="password"
            value={keys.openai}
            onChange={e => setKeys(k => ({ ...k, openai: e.target.value }))}
            placeholder="sk-..."
            style={inputStyle}
          />
        </div>
        <div style={{ marginBottom: 24 }}>
          <label style={{ fontSize: 11, color: 'var(--color-white-3)', textTransform: 'uppercase', letterSpacing: '0.08em', display: 'block', marginBottom: 6 }}>
            VirusTotal API Key
          </label>
          <input 
            type="password"
            value={keys.virustotal}
            onChange={e => setKeys(k => ({ ...k, virustotal: e.target.value }))}
            placeholder="Enter API Key"
            style={inputStyle}
          />
        </div>
        <button
          onClick={handleSave}
          disabled={saving}
          style={{
            width: '100%', padding: '11px', borderRadius: 9,
            background: saving ? 'rgba(79,70,229,0.5)' : '#4f46e5',
            border: 'none', color: 'var(--color-white-full)', fontSize: 13, fontWeight: 500,
            cursor: saving ? 'not-allowed' : 'pointer',
          }}
        >
          {saving ? 'Saving...' : 'Save Keys'}
        </button>
      </div>
    </div>
  )
}

function SecurityTab({ user, navigate }) {
  // Password state
  const [form, setForm] = useState({ current_password: '', new_password: '', confirm: '' })
  const [show, setShow] = useState({ current: false, new: false, confirm: false })
  const [pwLoading, setPwLoading] = useState(false)

  // 2FA state
  const [step, setStep] = useState('start')
  const [qrData, setQrData] = useState(null)
  const [secret, setSecret] = useState('')
  const [code, setCode] = useState('')
  const [tfaLoading, setTfaLoading] = useState(false)

  const handlePasswordSubmit = async () => {
    if (!form.current_password || !form.new_password || !form.confirm) {
      toast.error('Fill in all password fields')
      return
    }
    if (form.new_password !== form.confirm) {
      toast.error('New passwords do not match')
      return
    }
    if (form.new_password.length < 8) {
      toast.error('Password must be 8+ characters')
      return
    }
    setPwLoading(true)
    try {
      await changePassword({ current_password: form.current_password, new_password: form.new_password })
      toast.success('Password changed successfully')
      setForm({ current_password: '', new_password: '', confirm: '' })
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to change password')
    } finally {
      setPwLoading(false)
    }
  }

  const handle2FASetup = async () => {
    setTfaLoading(true)
    try {
      const res = await setup2FA()
      setQrData(res.data)
      setSecret(res.data.secret)
      setStep('setup')
    } catch {
      toast.error('Setup failed')
    } finally {
      setTfaLoading(false)
    }
  }

  const handle2FAVerify = async () => {
    if (code.length !== 6) return
    setTfaLoading(true)
    try {
      await verify2FA(code)
      setStep('done')
      toast.success('2FA enabled!')
      setTimeout(() => window.location.reload(), 1500)
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Invalid code')
    } finally {
      setTfaLoading(false)
    }
  }

  const handle2FADisable = async () => {
    if (code.length !== 6) return
    setTfaLoading(true)
    try {
      await disable2FA(code)
      toast.success('2FA disabled')
      setTimeout(() => window.location.reload(), 1500)
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Invalid code')
    } finally {
      setTfaLoading(false)
    }
  }

  return (
    <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: 24, maxWidth: 420 }}>
      {/* Change Password Section */}
      <div style={{
        background: 'var(--color-white-03)',
        border: '1px solid rgba(255,255,255,0.07)',
        borderRadius: 14,
        padding: 24,
      }}>
        <h3 style={{ fontSize: 16, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 20 }}>Change Password</h3>
        
        {[{ key: 'current_password', label: 'Current Password', showKey: 'current' },
          { key: 'new_password', label: 'New Password', showKey: 'new' },
          { key: 'confirm', label: 'Confirm New Password', showKey: 'confirm' }].map(field => (
          <div key={field.key} style={{ marginBottom: 16 }}>
            <label style={{ fontSize: 11, color: 'var(--color-white-3)', textTransform: 'uppercase', letterSpacing: '0.08em', display: 'block', marginBottom: 6 }}>
              {field.label}
            </label>
            <div style={{ position: 'relative' }}>
              <input
                type={show[field.showKey] ? 'text' : 'password'}
                value={form[field.key]}
                onChange={e => setForm(f => ({ ...f, [field.key]: e.target.value }))}
                onKeyDown={e => e.key === 'Enter' && handlePasswordSubmit()}
                style={{...inputStyle, paddingRight: 40}}
              />
              <button
                onClick={() => setShow(s => ({ ...s, [field.showKey]: !s[field.showKey] }))}
                style={{ position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-white-3)', padding: 0, display: 'flex' }}
              >
                {show[field.showKey] ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
          </div>
        ))}
        <button
          onClick={handlePasswordSubmit}
          disabled={pwLoading}
          style={{ width: '100%', padding: '11px', borderRadius: 9, background: pwLoading ? 'rgba(79,70,229,0.5)' : '#4f46e5', border: 'none', color: 'var(--color-white-full)', fontSize: 13, fontWeight: 500, cursor: pwLoading ? 'not-allowed' : 'pointer', marginTop: 8 }}
        >
          {pwLoading ? 'Changing...' : 'Change Password'}
        </button>
      </div>

      {/* 2FA Section */}
      <div style={{
        background: 'var(--color-white-03)',
        border: '1px solid rgba(255,255,255,0.07)',
        borderRadius: 14,
        padding: 24,
      }}>
        <h3 style={{ fontSize: 16, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 20 }}>Two-Factor Authentication</h3>
        
        {step === 'start' && !user?.totp_enabled && (
          <div style={{ textAlign: 'center' }}>
            <p style={{ fontSize: 12, color: 'var(--color-white-4)', marginBottom: 20 }}>
              Add an extra layer of security. Use Google Authenticator, Authy, or any TOTP app to generate login codes.
            </p>
            <button
              onClick={handle2FASetup}
              disabled={tfaLoading}
              style={{ padding: '10px 28px', borderRadius: 9, background: '#4f46e5', border: 'none', color: 'var(--color-white-full)', fontSize: 13, fontWeight: 500, cursor: 'pointer' }}>
              Enable 2FA
            </button>
          </div>
        )}

        {step === 'setup' && qrData && (
          <div style={{ textAlign: 'center' }}>
            <p style={{ fontSize: 13, color: 'var(--text-primary)', marginBottom: 16 }}>Scan with your authenticator app</p>
            <img src={qrData.qr_code} alt="QR Code" style={{ width: 160, height: 160, borderRadius: 12, margin: '0 auto 16px', display: 'block', background: 'var(--color-white-full)', padding: 8 }} />
            <p style={{ fontSize: 11, color: 'var(--color-white-3)', marginBottom: 4 }}>Or enter manually:</p>
            <code style={{ fontSize: 12, fontFamily: 'monospace', color: '#818cf8', background: 'rgba(99,102,241,0.1)', padding: '4px 12px', borderRadius: 6, display: 'inline-block', marginBottom: 20, letterSpacing: '0.1em' }}>
              {qrData.manual_entry_key}
            </code>
            <input
              value={code} onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
              placeholder="000000" maxLength={6}
              onKeyDown={e => e.key === 'Enter' && handle2FAVerify()}
              style={{ width: '100%', background: 'var(--color-white-05)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 9, padding: '10px', fontSize: 24, color: 'var(--text-primary)', outline: 'none', textAlign: 'center', fontFamily: 'monospace', letterSpacing: '0.3em', marginBottom: 16 }}
            />
            <button onClick={handle2FAVerify} disabled={tfaLoading || code.length !== 6} style={{ width: '100%', padding: '10px', borderRadius: 9, background: code.length === 6 ? '#4f46e5' : 'rgba(79,70,229,0.3)', border: 'none', color: 'var(--color-white-full)', fontSize: 13, fontWeight: 500, cursor: code.length === 6 ? 'pointer' : 'not-allowed' }}>
              {tfaLoading ? 'Verifying...' : 'Verify & Enable'}
            </button>
          </div>
        )}

        {user?.totp_enabled && step === 'start' && (
          <div style={{ textAlign: 'center' }}>
            <p style={{ fontSize: 13, color: '#34d399', marginBottom: 16, fontWeight: 500 }}>✓ 2FA is currently active</p>
            <input
              value={code} onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
              placeholder="000000" maxLength={6}
              style={{ width: '100%', background: 'var(--color-white-05)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 9, padding: '10px', fontSize: 24, color: 'var(--text-primary)', outline: 'none', textAlign: 'center', fontFamily: 'monospace', letterSpacing: '0.3em', marginBottom: 16 }}
            />
            <button onClick={handle2FADisable} disabled={tfaLoading || code.length !== 6} style={{ width: '100%', padding: '10px', borderRadius: 9, background: 'rgba(239,68,68,0.15)', border: '1px solid rgba(239,68,68,0.3)', color: '#f87171', fontSize: 13, cursor: 'pointer' }}>
              Disable 2FA
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

export default function SettingsPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const tab = searchParams.get('tab') || 'account'

  const tabs = [
    { id: 'account', label: 'Account', icon: User },
    { id: 'preferences', label: 'Preferences', icon: Settings2 },
    { id: 'integrations', label: 'API Integrations', icon: LinkIcon },
    { id: 'security', label: 'Security', icon: Shield },
  ]

  return (
    <PageLayout title="Settings" subtitle="Manage your account and preferences">
      <div style={{ display: 'flex', gap: 40, alignItems: 'flex-start' }}>
        
        {/* Sidebar Navigation */}
        <div style={{ width: 220, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 4 }}>
          {tabs.map(t => {
            const Icon = t.icon
            const active = tab === t.id
            return (
              <button
                key={t.id}
                onClick={() => setSearchParams({ tab: t.id })}
                style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  padding: '12px 16px', borderRadius: 10,
                  background: active ? 'rgba(99,102,241,0.1)' : 'transparent',
                  border: 'none',
                  color: active ? '#818cf8' : 'var(--color-white-5)',
                  fontSize: 13, fontWeight: active ? 600 : 500,
                  cursor: 'pointer', textAlign: 'left',
                  transition: 'all 0.15s'
                }}
                onMouseEnter={e => {
                  if (!active) e.currentTarget.style.color = 'var(--text-primary)'
                }}
                onMouseLeave={e => {
                  if (!active) e.currentTarget.style.color = 'var(--color-white-5)'
                }}
              >
                <Icon size={16} />
                {t.label}
              </button>
            )
          })}
        </div>

        {/* Tab Content */}
        <div style={{ flex: 1, minWidth: 0, paddingBottom: 60 }}>
          {tab === 'account' && <AccountTab user={user} />}
          {tab === 'preferences' && <PreferencesTab />}
          {tab === 'integrations' && <IntegrationsTab />}
          {tab === 'security' && <SecurityTab user={user} navigate={navigate} />}
        </div>

      </div>
    </PageLayout>
  )
}
