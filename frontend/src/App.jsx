import React, { useState, useEffect } from 'react'
import { Routes, Route } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext'
import ProtectedRoute from './components/ProtectedRoute'
import ErrorBoundary from './components/ErrorBoundary'
import Sidebar from './components/Sidebar'
import StatusBar from './components/StatusBar'
import AppBackground from './components/AppBackground'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import DashboardPage from './pages/DashboardPage'
import AdminUsersPage from './pages/AdminUsersPage'
import ActivityPage from './pages/ActivityPage'
import SettingsPage from './pages/SettingsPage'
import CredentialsPage from './pages/CredentialsPage'
import ComparisonPage from './pages/ComparisonPage'
import CaseSettingsPage from './pages/CaseSettingsPage'
import CasesPage from './pages/CasesPage'
import CaseDetailPage from './pages/CaseDetailPage'
import EvidencePage from './pages/EvidencePage'
import InvestigatePage from './pages/InvestigatePage'
import EntityMapPage from './pages/EntityMapPage'
import NotesPage from './pages/NotesPage'
import AuditPage from './pages/AuditPage'
import ArtifactsPage from './pages/ArtifactsPage'
import TimelinePage from './pages/TimelinePage'
import ReportsPage from './pages/ReportsPage'
import AnomalyPage from './pages/AnomalyPage'
import ProfilePage from './pages/ProfilePage'
import WatchlistPage from './pages/WatchlistPage'
import RetiredRoute from './components/RetiredRoute'
import ContradictionsPage from './pages/ContradictionsPage'
import QueuePage from './pages/QueuePage'
import SystemHealthPage from './pages/SystemHealthPage'
import StoragePage from './pages/StoragePage'
import ChangePasswordPage from './pages/ChangePasswordPage'
import TwoFactorPage from './pages/TwoFactorPage'
import { getStatus } from './api/client'
import useNotifications from './hooks/useNotifications.jsx'

const SIDEBAR_EXPANDED = 220
const SIDEBAR_COLLAPSED = 52

function AppLayout() {
  const { user } = useAuth()
  // Global WebSocket notifications (ingestion complete, flags, notes, etc.)
  useNotifications()
  const [systemStatus, setSystemStatus] = useState(null)
  const [activeCaseId, setActiveCaseId] = useState(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)

  useEffect(() => {
    // A throw here used to fabricate `{ database: 'error', ollama: 'offline' }`,
    // which turned a backend that was merely slow to answer into a permanently
    // reported-dead AI. Now an unreachable status endpoint only says so.
    let cancelled = false
    const fetchStatus = async () => {
      try {
        const res = await getStatus()
        if (!cancelled) setSystemStatus(res.data)
      } catch {
        // Leave the previous payload alone if there was one; if there was not,
        // systemStatus stays null and the Sidebar renders a neutral "checking"
        // state rather than a fabricated failure.
        if (!cancelled) setSystemStatus(null)
      }
    }
    fetchStatus()
    // Fast at first - the backend is often still starting when the page opens -
    // then settle to the slow cadence once a real reading exists.
    const fast = setInterval(fetchStatus, 4000)
    const slow = setInterval(() => { if (systemStatus) clearInterval(fast) }, 4000)
    const interval = setInterval(fetchStatus, 30000)
    return () => { cancelled = true; clearInterval(fast); clearInterval(slow); clearInterval(interval) }
  }, [])

  const sidebarWidth = sidebarOpen ? SIDEBAR_EXPANDED : SIDEBAR_COLLAPSED

  return (
    <div style={{
      display: 'flex',
      height: '100vh',
      overflow: 'hidden',
      position: 'relative',
    }}>
      <AppBackground />

      <div style={{
        display: 'flex',
        width: '100%',
        height: '100%',
        position: 'relative',
        zIndex: 1,
      }}>
        {/* Sidebar — animate width */}
        <div style={{
          width: sidebarWidth,
          flexShrink: 0,
          transition: 'width 0.25s cubic-bezier(0.4,0,0.2,1)',
          overflow: 'hidden',
        }}>
          <Sidebar
            activeCaseId={activeCaseId}
            setActiveCaseId={setActiveCaseId}
            status={systemStatus}
            collapsed={!sidebarOpen}
            onToggle={() => setSidebarOpen(v => !v)}
          />
        </div>

        <div style={{
          display: 'flex',
          flexDirection: 'column',
          flex: 1,
          overflow: 'hidden',
          minWidth: 0,
        }}>
          {/* Search-only top bar */}
          <StatusBar />
          <main style={{
            flex: 1,
            overflowY: 'auto',
            padding: '24px',
          }}>
            <ErrorBoundary>
            <Routes>
              <Route path="/" element={
                <ProtectedRoute><DashboardPage activeCaseId={activeCaseId} setActiveCaseId={setActiveCaseId} /></ProtectedRoute>
              } />
              <Route path="/admin/users" element={
                <ProtectedRoute minimumRole="Admin"><AdminUsersPage /></ProtectedRoute>
              } />

              <Route path="/activity" element={
                <ProtectedRoute minimumRole="Analyst"><ActivityPage /></ProtectedRoute>
              } />
              <Route path="/settings" element={
                <ProtectedRoute><SettingsPage /></ProtectedRoute>
              } />
              <Route path="/health" element={
                <ProtectedRoute><SystemHealthPage /></ProtectedRoute>
              } />
              <Route path="/storage" element={
                <ProtectedRoute><StoragePage /></ProtectedRoute>
              } />
              <Route path="/change-password" element={
                <ProtectedRoute><ChangePasswordPage /></ProtectedRoute>
              } />
              <Route path="/2fa" element={
                <ProtectedRoute><TwoFactorPage /></ProtectedRoute>
              } />

              <Route path="/cases/:caseId/credentials" element={
                <ProtectedRoute minimumRole="Analyst"><CredentialsPage /></ProtectedRoute>
              } />
              <Route path="/cases/:caseId/contradictions" element={
                <ProtectedRoute minimumRole="Analyst"><ContradictionsPage /></ProtectedRoute>
              } />
              <Route path="/cases/:caseId/compare" element={
                <ProtectedRoute minimumRole="Analyst"><ComparisonPage /></ProtectedRoute>
              } />
              <Route path="/cases/:caseId/settings" element={
                <ProtectedRoute minimumRole="Investigator"><CaseSettingsPage /></ProtectedRoute>
              } />
              <Route path="/cases" element={
                <ProtectedRoute><CasesPage setActiveCaseId={setActiveCaseId} /></ProtectedRoute>
              } />
              <Route path="/cases/:caseId" element={
                <ProtectedRoute><CaseDetailPage /></ProtectedRoute>
              } />
              <Route path="/cases/:caseId/evidence" element={
                <ProtectedRoute minimumRole="Viewer"><EvidencePage /></ProtectedRoute>
              } />
              <Route path="/cases/:caseId/artifacts" element={
                <ProtectedRoute minimumRole="Viewer">
                  <ErrorBoundary><ArtifactsPage /></ErrorBoundary>
                </ProtectedRoute>
              } />
              <Route path="/cases/:caseId/timeline" element={
                <ProtectedRoute minimumRole="Viewer"><TimelinePage /></ProtectedRoute>
              } />
              <Route path="/cases/:caseId/investigate" element={
                <ProtectedRoute minimumRole="Analyst">
                  <ErrorBoundary><InvestigatePage /></ErrorBoundary>
                </ProtectedRoute>
              } />
              <Route path="/cases/:caseId/entities" element={
                <ProtectedRoute minimumRole="Viewer">
                  <ErrorBoundary><EntityMapPage /></ErrorBoundary>
                </ProtectedRoute>
              } />
              <Route path="/cases/:caseId/profiles" element={
                <ProtectedRoute minimumRole="Analyst">
                  <ErrorBoundary><ProfilePage /></ErrorBoundary>
                </ProtectedRoute>
              } />
              <Route path="/cases/:caseId/watchlist" element={
                <ProtectedRoute minimumRole="Analyst"><WatchlistPage /></ProtectedRoute>
              } />
              <Route path="/cases/:caseId/geomap" element={
                /* Retired - see constants/hiddenRoutes.js. Routed to an
                   explanation rather than 404-ing, so a stale bookmark or
                   an old link says what happened instead of looking like a
                   broken URL. The page component is deleted, not just
                   unrouted: the reason it cannot be kept is recorded in the
                   registry, and git holds the rest. */
                <ProtectedRoute minimumRole="Viewer">
                  <ErrorBoundary><RetiredRoute /></ErrorBoundary>
                </ProtectedRoute>
              } />
              <Route path="/cases/:caseId/notes" element={
                <ProtectedRoute minimumRole="Analyst"><NotesPage /></ProtectedRoute>
              } />
              <Route path="/cases/:caseId/audit" element={
                <ProtectedRoute minimumRole="Analyst"><AuditPage /></ProtectedRoute>
              } />
              <Route path="/cases/:caseId/reports" element={
                <ProtectedRoute minimumRole="Viewer"><ReportsPage /></ProtectedRoute>
              } />
              <Route path="/queue" element={
                <ProtectedRoute minimumRole="Analyst"><QueuePage /></ProtectedRoute>
              } />
              <Route path="/cases/:caseId/anomalies" element={
                <ProtectedRoute minimumRole="Analyst"><AnomalyPage /></ProtectedRoute>
              } />
            </Routes>
            </ErrorBoundary>
          </main>
        </div>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login"    element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/*"        element={<AppLayout />} />
      </Routes>
    </AuthProvider>
  )
}
