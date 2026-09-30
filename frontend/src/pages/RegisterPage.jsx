import React, { useState } from 'react'
import { useNavigate, Link } from
  'react-router-dom'
import { Shield } from 'lucide-react'
import { register } from '../api/client'
import { useAuth } from
  '../context/AuthContext'
import toast from 'react-hot-toast'

export default function RegisterPage() {
  const navigate = useNavigate()
  const { signIn } = useAuth()
  const [form, setForm] = useState({
    username: '',
    email: '',
    password: '',
    confirm_password: '',
    full_name: '',
    role: 'Analyst'
  })
  const [loading, setLoading] =
    useState(false)

  const handleRegister = async () => {
    if (!form.username || !form.email ||
        !form.password || !form.full_name) {
      toast.error('Fill in all fields')
      return
    }
    if (form.password !==
        form.confirm_password) {
      toast.error('Passwords do not match')
      return
    }
    if (form.password.length < 8) {
      toast.error(
        'Password must be 8+ characters')
      return
    }
    setLoading(true)
    try {
      await register({
        username: form.username,
        email: form.email,
        password: form.password,
        full_name: form.full_name,
        // No role is sent. The backend assigns the first account Admin and
        // every later one Analyst, ignoring any role in the request body, so
        // sending one would only suggest the client chooses it.
      })
      // Auto login after register
      await signIn(
        form.username, form.password)
      navigate('/cases')
      toast.success('Account created')
    } catch (e) {
      toast.error(
        e.response?.data?.detail ||
        'Registration failed')
    } finally {
      setLoading(false)
    }
  }

  const fields = [
    { key: 'full_name',
      label: 'Full Name',
      placeholder: 'Det. Elena Markov',
      type: 'text' },
    { key: 'username',
      label: 'Username',
      placeholder: 'elena_markov',
      type: 'text' },
    { key: 'email',
      label: 'Email',
      placeholder: 'elena@interpol.int',
      type: 'email' },
    { key: 'password',
      label: 'Password',
      placeholder: '••••••••',
      type: 'password' },
    { key: 'confirm_password',
      label: 'Confirm Password',
      placeholder: '••••••••',
      type: 'password' }
  ]

  return (
    <div className="min-h-screen
      bg-surface-0 flex items-center
      justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-6">
          <div className="w-16 h-16
            rounded-2xl bg-accent
            flex items-center
            justify-center mx-auto mb-4
            shadow-lg shadow-accent/30">
            <Shield size={32}
              className="text-white" />
          </div>
          <h1 className="text-2xl
            font-bold text-ink-0">
            Create Account
          </h1>
          <p className="text-ink-2
            text-sm mt-1">
            The first account created on
            this workstation becomes
            Admin. Later accounts start as
            Analyst and are promoted from
            User Management.
          </p>
        </div>

        <div className="bg-surface-2 border
          border-line rounded-2xl p-6
          shadow-xl">
          <div className="space-y-3">
            {fields.map(field => (
              <div key={field.key}>
                <label className="text-xs
                  text-ink-2 mb-1
                  block font-medium">
                  {field.label}
                </label>
                <input
                  id={`register-${field.key}`}
                  type={field.type}
                  value={form[field.key]}
                  onChange={e => setForm({
                    ...form,
                    [field.key]:
                      e.target.value
                  })}
                  placeholder={
                    field.placeholder}
                  className="w-full
                    bg-surface-1 border
                    border-line
                    rounded-xl px-4 py-2.5
                    text-sm text-ink-0
                    placeholder:text-ink-2
                    focus:outline-none
                    focus:border-accent
                    transition-colors"
                />
              </div>
            ))}

            {/* The role selector was removed. The backend used to take the
                role straight from this dropdown, so any anonymous visitor
                could create themselves an Admin account on a product whose
                entire value is a trustworthy chain of custody. The backend
                no longer accepts a client-supplied role at all; the first
                account created becomes Admin and every later one is an
                Analyst until an existing Admin promotes it from User
                Management. Offering the choice here would have been
                decoration over an escalation that is no longer possible. */}

            <button
              id="register-submit"
              onClick={handleRegister}
              disabled={loading}
              className="w-full bg-accent
                hover:bg-accent-hover
                disabled:opacity-50
                text-white py-3 rounded-xl
                text-sm font-semibold
                transition-colors mt-2
                shadow-md shadow-accent/20"
            >
              {loading
                ? 'Creating account...'
                : 'Create Account'}
            </button>
          </div>

          <p className="text-center
            text-xs text-ink-2 mt-4">
            Have an account?{' '}
            <Link to="/login"
              className="text-accent
                         hover:underline
                         font-medium">
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}
