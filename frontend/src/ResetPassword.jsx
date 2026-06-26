import { useState } from 'react'
import { useSearchParams, Link } from 'react-router-dom'

export default function ResetPassword() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')

  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [done, setDone] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')

    if (password !== confirm) {
      setError('Passwords do not match')
      return
    }

    setLoading(true)
    try {
      const res = await fetch('/reset-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, new_password: password }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Reset failed')
      setDone(true)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  if (!token) {
    return (
      <div className="auth-card">
        <h1>Invalid link</h1>
        <p>This password reset link is missing or invalid.</p>
        <Link to="/forgot-password" className="btn">Request a new link</Link>
      </div>
    )
  }

  if (done) {
    return (
      <div className="auth-card">
        <h1>Password reset</h1>
        <p>Your password has been reset successfully.</p>
        <Link to="/login" className="btn">Log in</Link>
      </div>
    )
  }

  return (
    <div className="auth-card">
      <h1>Reset password</h1>
      <p>Enter your new password.</p>
      <form onSubmit={handleSubmit}>
        <input
          type="password"
          placeholder="New password (8+ chars, uppercase, number, special)"
          value={password}
          onChange={e => setPassword(e.target.value)}
          required
          minLength={8}
          autoFocus
        />
        <input
          type="password"
          placeholder="Confirm new password"
          value={confirm}
          onChange={e => setConfirm(e.target.value)}
          required
          minLength={8}
        />
        {error && <p className="error">{error}</p>}
        <button type="submit" className="btn" disabled={loading}>
          {loading ? 'Resetting...' : 'Reset password'}
        </button>
      </form>
    </div>
  )
}
