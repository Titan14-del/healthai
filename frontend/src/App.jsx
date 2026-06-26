import { Routes, Route, Link } from 'react-router-dom'
import ForgotPassword from './ForgotPassword'
import ResetPassword from './ResetPassword'
import './App.css'

function Home() {
  return (
    <>
      <section id="center">
        <div>
          <h1>HealthAI</h1>
          <p>AI-powered medical symptom analysis</p>
        </div>
        <div className="home-links">
          <Link to="/forgot-password" className="btn">Forgot password</Link>
        </div>
      </section>
    </>
  )
}

function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />
    </Routes>
  )
}

export default App
