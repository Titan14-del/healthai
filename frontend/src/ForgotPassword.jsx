import { useState } from 'react'
import { Link } from 'react-router-dom'

export default function ForgotPassword() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await fetch('/forgot-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      })
      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.detail || 'Something went wrong')
      }
      setSent(true)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  if (sent) {
    return (
      <div className="auth-card">
        <h1>Check your email</h1>
        <p>If that email is registered, we've sent a password reset link.</p>
        <Link to="/login" className="btn">Back to login</Link>
      </div>
    )
  }

  return (
    <div className="auth-card">
      <h1>Forgot password</h1>
      <p>Enter your email and we'll send you a reset link.</p>
      <form onSubmit={handleSubmit}>
        <input
          type="email"
          placeholder="Email"
          value={email}
          onChange={e => setEmail(e.target.value)}
          required
          autoFocus
        />
        {error && <p className="error">{error}</p>}
        <button type="submit" className="btn" disabled={loading}>
          {loading ? 'Sending...' : 'Send reset link'}
        </button>
      </form>
      <Link to="/login" className="back-link">Back to login</Link>
    </div>
  )
}
