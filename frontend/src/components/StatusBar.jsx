import React, { useState, useRef, useEffect } from 'react'
import GlobalSearch from './GlobalSearch'
import { Moon, Sun, Bell, HelpCircle, AlertTriangle, CheckCircle, Zap } from 'lucide-react'
import { useTheme } from '../context/ThemeContext'
import { useAuth } from '../context/AuthContext'

export default function StatusBar() {
  const { theme, setTheme } = useTheme()
  const { user } = useAuth()

  const isDark = theme === 'dark' || (theme === 'system' && window.matchMedia?.('(prefers-color-scheme: dark)').matches)

  const [showNotifs, setShowNotifs] = useState(false);
  const [unreadCount, setUnreadCount] = useState(3);
  const notifRef = useRef(null);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (notifRef.current && !notifRef.current.contains(event.target)) {
        setShowNotifs(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const toggleTheme = () => {
    setTheme(isDark ? 'light' : 'dark')
  }

  const initial = user?.full_name?.[0] || user?.username?.[0] || 'A'
  const name = user?.full_name || user?.username || 'Analyst'
  const role = user?.role || 'Digital Forensic Expert'

  return (
    <div style={{
      height: 44,
      background: 'var(--bg-panel)',
      borderBottom: '1px solid var(--border-base)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '0 16px',
      flexShrink: 0,
      position: 'sticky',
      top: 0,
      zIndex: 40,
      transition: 'background 0.3s ease, border-color 0.3s ease',
    }}>
      {/* Left side search */}
      <div style={{ display: 'flex', alignItems: 'center', flex: 1 }}>
        <GlobalSearch />
      </div>

      {/* Right side options */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
      }}>
        {/* Theme Switcher Button */}
        <button
          onClick={toggleTheme}
          title={isDark ? "Switch to Light Mode" : "Switch to Dark Mode"}
          style={{
            background: 'transparent',
            border: 'none',
            color: 'var(--text-secondary)',
            cursor: 'pointer',
            padding: 4,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            transition: 'color 0.2s',
          }}
          onMouseEnter={e => e.currentTarget.style.color = 'var(--text-primary)'}
          onMouseLeave={e => e.currentTarget.style.color = 'var(--text-secondary)'}
        >
          {isDark ? <Sun size={17} /> : <Moon size={17} />}
        </button>

        {/* Notifications Icon with Badge */}
        <div ref={notifRef} style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
          <button
            title="Notifications"
            onClick={() => setShowNotifs(!showNotifs)}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              padding: 4,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'color 0.2s',
            }}
            onMouseEnter={e => e.currentTarget.style.color = 'var(--text-primary)'}
            onMouseLeave={e => e.currentTarget.style.color = 'var(--text-secondary)'}
          >
            <Bell size={17} />
          </button>
          {/* Notification Badge matching reference image */} {unreadCount > 0 && (
          <span style={{
            position: 'absolute',
            top: -1,
            right: -1,
            width: 13,
            height: 13,
            borderRadius: '50%',
            background: '#ef4444',
            color: '#ffffff',
            fontSize: 8,
            fontWeight: 700,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            border: '1.5px solid var(--bg-panel)',
            pointerEvents: 'none',
          }}>
            {unreadCount}
          </span>
          )}
          {showNotifs && (
            <div className="animate-fade-up" style={{
              position: 'absolute',
              top: 'calc(100% + 12px)',
              right: -10,
              width: 320,
              background: 'var(--bg-panel)',
              border: '1px solid var(--border-base)',
              borderRadius: 12,
              boxShadow: '0 10px 40px -10px rgba(0,0,0,0.3)',
              zIndex: 100,
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden'
            }}>
              <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>Notifications</span>
                <span onClick={() => setUnreadCount(0)} style={{ fontSize: 11, color: 'var(--brand-primary)', cursor: 'pointer' }}>Mark all as read</span>
              </div>
              <div style={{ maxHeight: 300, overflowY: 'auto', display: 'flex', flexDirection: 'column' }}>
                <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', gap: 12, cursor: 'pointer', background: unreadCount > 0 ? 'var(--bg-hover)' : 'transparent' }}>
                  <div style={{ color: '#10b981', marginTop: 2 }}><CheckCircle size={16} /></div>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 2 }}>Potential Match Found</div>
                    <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>AI found 3 potential matches in Cyber Fraud Investigation.</div>
                    <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>10 min ago</div>
                  </div>
                </div>
                <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', gap: 12, cursor: 'pointer', background: unreadCount > 0 ? 'var(--bg-hover)' : 'transparent' }}>
                  <div style={{ color: '#f59e0b', marginTop: 2 }}><AlertTriangle size={16} /></div>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 2 }}>Anomaly Detected</div>
                    <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>Unusual file behavior detected in Malware Incident Response.</div>
                    <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>25 min ago</div>
                  </div>
                </div>
                <div style={{ padding: '12px 16px', display: 'flex', gap: 12, cursor: 'pointer', background: unreadCount > 0 ? 'var(--bg-hover)' : 'transparent' }}>
                  <div style={{ color: '#3b82f6', marginTop: 2 }}><Zap size={16} /></div>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 2 }}>Keyword Alert</div>
                    <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>Keyword "confidential" found in 12 new documents.</div>
                    <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>1 hour ago</div>
                  </div>
                </div>
              </div>
              <div style={{ padding: '10px', borderTop: '1px solid var(--border-subtle)', textAlign: 'center', fontSize: 12, color: 'var(--text-secondary)', cursor: 'pointer' }}>
                View all notifications
              </div>
            </div>
          )}
        </div>

        {/* Help Circle Icon */}
        <button
          title="Help"
          style={{
            background: 'transparent',
            border: 'none',
            color: 'var(--text-secondary)',
            cursor: 'pointer',
            padding: 4,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            transition: 'color 0.2s',
          }}
          onMouseEnter={e => e.currentTarget.style.color = 'var(--text-primary)'}
          onMouseLeave={e => e.currentTarget.style.color = 'var(--text-secondary)'}
        >
          <HelpCircle size={17} />
        </button>

        {/* Divider */}
        <div style={{
          width: 1,
          height: 18,
          background: 'var(--border-base)',
        }} />

        {/* User Card */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
        }}>
          {/* Circle Avatar */}
          <div style={{
            width: 32,
            height: 32,
            borderRadius: '50%',
            background: 'linear-gradient(135deg, #0284c7 0%, #2563eb 100%)',
            border: '1.5px solid rgba(2, 132, 199, 0.25)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 2px 6px rgba(2, 132, 199, 0.15)',
          }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: '#ffffff' }}>
              {initial}
            </span>
          </div>
          {/* Text labels */}
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'center',
          }}>
            <span style={{
              fontSize: 12,
              fontWeight: 600,
              color: 'var(--text-primary)',
              lineHeight: 1.2,
            }}>
              {name}
            </span>
            <span style={{
              fontSize: 9,
              color: 'var(--text-muted)',
              marginTop: 1,
              fontWeight: 500,
            }}>
              {role}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}







