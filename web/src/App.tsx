import { Navigate, Route, Routes, useLocation } from 'react-router'
import { AuthProvider, RequireRole, useAuth } from './auth'
import { TopBar } from './components/TopBar'
import { ErrorBoundary } from './components/ErrorBoundary'
import { useNightRoom } from './components/useNightRoom'
import './components/night.css'
import AuthPage from './pages/AuthPage'
import CaregiverDashboard from './pages/CaregiverDashboard'
import Home from './pages/Home'
import LiveSession from './pages/LiveSession'
import ResidentDetail from './pages/ResidentDetail'
import Welcome from './pages/Welcome'

function Root() {
  const { me, loading } = useAuth()
  if (loading) return <p className="wrap page-pad muted">Loading…</p>
  if (me?.role === 'caregiver') return <Navigate to="/caregiver" replace />
  if (me?.role === 'resident') return <Home />
  return <Welcome />
}

export default function App() {
  const { pathname } = useLocation()
  useNightRoom() // every page sits in the evening room; welcome, sign-in and the resident home add lanterns
  return (
    <AuthProvider>
      <TopBar />
      {/* keyed by path so moving to another page clears a caught error */}
      <ErrorBoundary key={pathname}>
        <Routes>
          <Route path="/" element={<Root />} />
          <Route path="/login" element={<AuthPage who="resident" mode="login" key="r-login" />} />
          <Route path="/signup" element={<AuthPage who="resident" mode="signup" key="r-signup" />} />
          <Route path="/caregiver/login" element={<AuthPage who="caregiver" mode="login" key="c-login" />} />
          <Route path="/caregiver/signup" element={<AuthPage who="caregiver" mode="signup" key="c-signup" />} />
          <Route path="/caregiver" element={<RequireRole role="caregiver"><CaregiverDashboard /></RequireRole>} />
          <Route path="/caregiver/residents/:id" element={<RequireRole role="caregiver"><ResidentDetail /></RequireRole>} />
          <Route path="/caregiver/live/:id" element={<RequireRole role="caregiver"><LiveSession /></RequireRole>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </ErrorBoundary>
    </AuthProvider>
  )
}
