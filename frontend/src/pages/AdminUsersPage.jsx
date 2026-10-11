import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Users, Shield, CheckCircle,
  XCircle, ArrowLeft, UserPlus, X
} from 'lucide-react'
import {
  getUsers, updateUserRole, adminResetPassword,
  deactivateUser, activateUser, register, apiErrorMessage
} from '../api/client'
import { useAuth } from '../context/AuthContext'
import ConfirmDialog from '../components/ConfirmDialog'
import PageLayout from '../components/PageLayout'
import toast from 'react-hot-toast'
import { formatDistanceToNow } from 'date-fns'
import { fromUtc } from '../utils/time'

const ROLES = ['Viewer', 'Analyst', 'Investigator', 'Admin']

const ROLE_COLOR = {
  Admin:        'bg-danger/20 text-danger',
  Investigator: 'bg-accent/20 text-accent',
  Analyst:      'bg-blue-500/20 text-blue-400',
  Viewer:       'bg-gray-500/20 text-gray-400',
}

const ROLE_DESC = {
  Admin:        'Full access',
  Investigator: 'Create + manage cases',
  Analyst:      'View + query',
  Viewer:       'Read-only',
}

export default function AdminUsersPage() {
  const { user: currentUser } = useAuth()
  const navigate = useNavigate()
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [updatingId, setUpdatingId] = useState(null)
  const [confirmDeactivate, setConfirmDeactivate] = useState(null)

  // Add User Modal State
  const [showAddModal, setShowAddModal] = useState(false)
  const [newUser, setNewUser] = useState({
    full_name: '',
    username: '',
    email: '',
    role: 'Analyst',
    password: '',
    confirm_password: '',
  })
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    if (currentUser?.role !== 'Admin') {
      navigate('/dashboard')
      return
    }
    loadUsers()
  }, [])

  const loadUsers = async () => {
    try {
      const res = await getUsers()
      setUsers(res.data)
    } catch {
      toast.error('Failed to load users')
    } finally {
      setLoading(false)
    }
  }

  const handleRoleChange = async (userId, newRole) => {
    if (userId === currentUser.id && newRole !== 'Admin') {
      toast.error('Cannot demote yourself')
      return
    }
    setUpdatingId(userId)
    try {
      await updateUserRole(userId, newRole)
      setUsers(prev =>
        prev.map(u => u.id === userId ? { ...u, role: newRole } : u)
      )
      toast.success(`Role updated to ${newRole}`)
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Update failed')
    } finally {
      setUpdatingId(null)
    }
  }

  const handleToggleActive = async (userId, isActive) => {
    if (userId === currentUser.id) {
      toast.error('Cannot change your own active status')
      return
    }
    try {
      if (isActive) {
        await deactivateUser(userId)
      } else {
        await activateUser(userId)
      }
      setUsers(prev =>
        prev.map(u =>
          u.id === userId
            ? { ...u, is_active: !isActive }
            : u
        )
      )
      toast.success(isActive ? 'User deactivated' : 'User reactivated')
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Action failed')
    }
  }

  const handleAdminReset = async (userId) => {
    const newPass = window.prompt('Enter new password for this user (min 8 characters):')
    if (!newPass) return
    if (newPass.length < 8) {
      toast.error('Min 8 characters')
      return
    }
    try {
      await adminResetPassword(userId, newPass)
      toast.success('Password reset successfully')
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Reset failed')
    }
  }

  const handleCreateUser = async (e) => {
    e?.preventDefault()
    if (!newUser.full_name || !newUser.username || !newUser.email || !newUser.password) {
      toast.error('All fields are required')
      return
    }
    if (newUser.password !== newUser.confirm_password) {
      toast.error('Passwords do not match')
      return
    }
    if (newUser.password.length < 8) {
      toast.error('Password must be at least 8 characters')
      return
    }

    setCreating(true)
    try {
      await register({
        username: newUser.username,
        email: newUser.email,
        password: newUser.password,
        full_name: newUser.full_name,
        role: newUser.role,
      })
      toast.success(`User @${newUser.username} created successfully`)
      setShowAddModal(false)
      setNewUser({
        full_name: '',
        username: '',
        email: '',
        role: 'Analyst',
        password: '',
        confirm_password: '',
      })
      loadUsers()
    } catch (err) {
      toast.error(apiErrorMessage(err, 'Failed to create user'))
    } finally {
      setCreating(false)
    }
  }

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <div className="w-6 h-6 border-2 border-accent rounded-full border-t-transparent animate-spin" />
    </div>
  )

  return (
    <PageLayout
      title="User Management"
      subtitle={`${users.length} user(s) registered · Admin access only`}
      actions={
        <div className="flex items-center gap-2.5">
          {/* Admin-only Add User action */}
          <button
            id="add-new-user-btn"
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-medium transition-colors text-sm shadow-sm"
          >
            <UserPlus size={15} />
            Add User
          </button>
          <button
            id="back-to-dashboard"
            onClick={() => navigate('/dashboard')}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-line hover:bg-surface-4 text-ink-1 hover:text-ink-0 transition-colors text-sm"
          >
            <ArrowLeft size={16} />
            Back
          </button>
        </div>
      }
    >

      {/* Role legend */}
      <div className="flex gap-3 mb-4 flex-wrap">
        {ROLES.map(role => (
          <div key={role} className="flex items-center gap-1.5">
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${ROLE_COLOR[role]}`}>
              {role}
            </span>
            <span className="text-xs text-ink-2">{ROLE_DESC[role]}</span>
          </div>
        ))}
      </div>

      {/* Users table */}
      <div className="bg-surface-2 border border-line rounded-xl overflow-hidden">
        {/* Table header */}
        <div className="grid grid-cols-12 gap-2 px-4 py-2.5 border-b border-line bg-surface-1">
          {[
            { label: 'User',       cols: 'col-span-3' },
            { label: 'Email',      cols: 'col-span-3' },
            { label: 'Role',       cols: 'col-span-2' },
            { label: 'Last Login', cols: 'col-span-2' },
            { label: 'Actions',    cols: 'col-span-2' },
          ].map(({ label, cols }) => (
            <span key={label}
              className={`${cols} text-xs font-semibold text-ink-2 uppercase tracking-wider`}>
              {label}
            </span>
          ))}
        </div>

        {/* User rows */}
        {users.map(u => (
          <div
            key={u.id}
            className={`grid grid-cols-12 gap-2 px-4 py-3 border-b border-line
              last:border-0 items-center
              ${!u.is_active ? 'opacity-50' : ''}`}
          >
            {/* Avatar + name */}
            <div className="col-span-3 flex items-center gap-2">
              <div className="w-7 h-7 rounded-full bg-accent/20 flex items-center justify-center shrink-0">
                <span className="text-xs text-accent font-bold">
                  {u.full_name?.[0] || '?'}
                </span>
              </div>
              <div className="min-w-0">
                <p className="text-sm font-medium text-ink-0 truncate">
                  {u.full_name}
                </p>
                <p className="text-xs text-ink-2">
                  @{u.username}
                  {u.id === currentUser.id && (
                    <span className="text-accent ml-1">(you)</span>
                  )}
                </p>
              </div>
            </div>

            {/* Email */}
            <div className="col-span-3">
              <p className="text-xs text-ink-1 truncate">{u.email}</p>
            </div>

            {/* Role selector */}
            <div className="col-span-2">
              <select
                id={`role-select-${u.id}`}
                value={u.role}
                disabled={updatingId === u.id || !u.is_active}
                onChange={e => handleRoleChange(u.id, e.target.value)}
                className={`w-full bg-surface-1 border border-line rounded-lg
                  px-2 py-1 text-xs focus:outline-none focus:border-accent
                  appearance-none cursor-pointer disabled:opacity-50
                  disabled:cursor-not-allowed ${ROLE_COLOR[u.role]}`}
              >
                {ROLES.map(r => (
                  <option key={r} value={r}
                    className="bg-surface-2 text-ink-0">
                    {r}
                  </option>
                ))}
              </select>
            </div>

            {/* Last login */}
            <div className="col-span-2">
              <p className="text-xs text-ink-2">
                {u.last_login
                  ? (() => {
                      try {
                        return formatDistanceToNow(
                          fromUtc(u.last_login), { addSuffix: true })
                      } catch {
                        return 'Unknown'
                      }
                    })()
                  : 'Never'}
              </p>
            </div>

            {/* Actions: Reset pwd + Deactivate/Reactivate */}
            <div className="col-span-2 flex items-center gap-2 flex-wrap">
              {/* Reset password */}
              <button
                id={`reset-pwd-${u.id}`}
                onClick={() => handleAdminReset(u.id)}
                className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg border transition-colors border-line text-ink-2 hover:text-amber-400 hover:border-amber-400/40"
              >
                Reset pwd
              </button>
              {/* Deactivate / Reactivate */}
              {u.id !== currentUser.id && (
                <button
                  id={`toggle-active-${u.id}`}
                  onClick={() =>
                    u.is_active
                      ? setConfirmDeactivate(u)
                      : handleToggleActive(u.id, u.is_active)
                  }
                  className={`flex items-center gap-1 text-xs px-2 py-1 rounded-lg border transition-colors
                    ${u.is_active
                      ? 'border-line text-ink-2 hover:text-danger hover:border-danger/40'
                      : 'border-success/40 text-success hover:bg-success/10'}`}
                >
                  {u.is_active
                    ? <><XCircle size={11} /> Deactivate</>
                    : <><CheckCircle size={11} /> Reactivate</>
                  }
                </button>
              )}
            </div>
          </div>
        ))}

        {users.length === 0 && (
          <div className="py-12 text-center text-ink-2">
            <Users size={28} className="mx-auto mb-2 opacity-30" />
            <p className="text-sm">No users found</p>
          </div>
        )}
      </div>

      {/* Add User Modal */}
      {showAddModal && (
        <div
          className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4"
          onClick={() => setShowAddModal(false)}
        >
          <div
            className="bg-surface-2 border border-line rounded-2xl p-6 w-full max-w-md shadow-2xl animate-scale-in"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between pb-3 border-b border-line mb-4">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-indigo-500/10 text-indigo-400 flex items-center justify-center">
                  <UserPlus size={16} />
                </div>
                <div>
                  <h2 className="font-bold text-ink-0 text-base">Add New User</h2>
                  <p className="text-xs text-ink-2">Create credentials and assign an investigator role</p>
                </div>
              </div>
              <button
                onClick={() => setShowAddModal(false)}
                className="text-ink-2 hover:text-ink-0 p-1 transition-colors"
              >
                <X size={16} />
              </button>
            </div>

            <form onSubmit={handleCreateUser} className="space-y-3.5">
              <div>
                <label className="block text-xs font-semibold text-ink-1 mb-1">
                  Full Name
                </label>
                <input
                  type="text"
                  placeholder="e.g. Detective John Doe"
                  value={newUser.full_name}
                  onChange={e => setNewUser({ ...newUser, full_name: e.target.value })}
                  className="w-full bg-surface-1 border border-line rounded-lg px-3 py-2 text-sm text-ink-0 focus:outline-none focus:border-accent"
                  required
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-ink-1 mb-1">
                    Username
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. jdoe"
                    value={newUser.username}
                    onChange={e => setNewUser({ ...newUser, username: e.target.value })}
                    className="w-full bg-surface-1 border border-line rounded-lg px-3 py-2 text-sm text-ink-0 focus:outline-none focus:border-accent"
                    required
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-ink-1 mb-1">
                    Role
                  </label>
                  <select
                    value={newUser.role}
                    onChange={e => setNewUser({ ...newUser, role: e.target.value })}
                    className="w-full bg-surface-1 border border-line rounded-lg px-3 py-2 text-sm text-ink-0 focus:outline-none focus:border-accent"
                  >
                    {ROLES.map(r => (
                      <option key={r} value={r}>
                        {r} ({ROLE_DESC[r]})
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-ink-1 mb-1">
                  Email Address
                </label>
                <input
                  type="email"
                  placeholder="e.g. jdoe@forensics.local"
                  value={newUser.email}
                  onChange={e => setNewUser({ ...newUser, email: e.target.value })}
                  className="w-full bg-surface-1 border border-line rounded-lg px-3 py-2 text-sm text-ink-0 focus:outline-none focus:border-accent"
                  required
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-ink-1 mb-1">
                    Password (8+ chars)
                  </label>
                  <input
                    type="password"
                    placeholder="••••••••"
                    value={newUser.password}
                    onChange={e => setNewUser({ ...newUser, password: e.target.value })}
                    className="w-full bg-surface-1 border border-line rounded-lg px-3 py-2 text-sm text-ink-0 focus:outline-none focus:border-accent"
                    required
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-ink-1 mb-1">
                    Confirm Password
                  </label>
                  <input
                    type="password"
                    placeholder="••••••••"
                    value={newUser.confirm_password}
                    onChange={e => setNewUser({ ...newUser, confirm_password: e.target.value })}
                    className="w-full bg-surface-1 border border-line rounded-lg px-3 py-2 text-sm text-ink-0 focus:outline-none focus:border-accent"
                    required
                  />
                </div>
              </div>

              <div className="flex gap-2.5 justify-end pt-3 border-t border-line mt-4">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="px-4 py-2 bg-surface-4 text-ink-1 rounded-xl text-sm transition-colors hover:text-ink-0"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-sm font-medium transition-colors disabled:opacity-50"
                >
                  {creating ? 'Creating...' : 'Create User'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Deactivate confirmation */}
      <ConfirmDialog
        isOpen={!!confirmDeactivate}
        title="Deactivate User"
        message={`Deactivate ${confirmDeactivate?.full_name} (@${confirmDeactivate?.username})? They will be locked out immediately.`}
        confirmLabel="Deactivate"
        onConfirm={() => handleToggleActive(confirmDeactivate.id, true)}
        onCancel={() => setConfirmDeactivate(null)}
      />
    </PageLayout>
  )
}
