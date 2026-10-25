import { useState, type FormEvent, type InputHTMLAttributes, type ReactNode } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router'
import { Eye, EyeSlash, WarningCircle } from '@phosphor-icons/react'
import type { Hand } from '../api'
import { useAuth } from '../auth'
import { Lantern } from '../components/Lantern'
import { StampMark } from '../components/StampMark'
import { useNightRoom } from '../components/useNightRoom'
import '../components/room.css'
import './Auth.css'

type Who = 'resident' | 'caregiver'
type Mode = 'login' | 'signup'

const COPY = {
  resident: {
    login: { title: 'Resident log in', lede: 'Welcome back. Log in to pick up your games.', cta: 'Log in', line: 'Back to the games' },
    signup: { title: 'Create a resident account', lede: 'Set up your own account to play the games.', cta: 'Create my account', line: 'Your own place to play' },
    path: { login: '/login', signup: '/signup' },
  },
  caregiver: {
    login: {
      title: 'Care team log in',
      lede: 'See residents’ results, trends and anything worth checking in on.',
      cta: 'Log in to the care dashboard',
      line: 'See how everyone is doing',
    },
    signup: { title: 'Register as care team', lede: 'The code keeps residents’ results private.', cta: 'Register', line: 'Join your care team' },
    path: { login: '/caregiver/login', signup: '/caregiver/signup' },
  },
} as const

/** A labelled field on the paper: the label sits above the box, large enough to read without squinting. */
function Field({
  id,
  label,
  hint,
  right,
  ...input
}: { id: string; label: string; hint?: string; right?: ReactNode } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className="af">
      <label htmlFor={id}>{label}</label>
      <div className="af-box">
        <input id={id} aria-describedby={hint ? `${id}-hint` : undefined} {...input} />
        {right}
      </div>
      {hint && (
        <p id={`${id}-hint`} className="af-hint">
          {hint}
        </p>
      )}
    </div>
  )
}

/** 0-4 from length and variety. A nudge, not a rule: the server only needs 8 characters. */
function strength(pw: string): number {
  if (!pw) return 0
  let s = pw.length >= 8 ? 1 : 0
  if (pw.length >= 12) s += 1
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) s += 1
  if (/\d/.test(pw) && /[^A-Za-z0-9]/.test(pw)) s += 1
  return Math.min(4, Math.max(pw.length >= 3 ? 1 : 0, s))
}
const LEVELS = ['', 'Short', 'Okay', 'Good', 'Strong']

export default function AuthPage({ who, mode }: { who: Who; mode: Mode }) {
  useNightRoom()
  const { me, loginResident, signupResident, loginCaregiver, signupCaregiver } = useAuth()
  const navigate = useNavigate()
  const from = (useLocation().state as { from?: string } | null)?.from ?? (who === 'caregiver' ? '/caregiver' : '/')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [inviteCode, setInviteCode] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [hand, setHand] = useState<Hand>('unknown')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const isSignup = mode === 'signup'
  const text = COPY[who][mode]

  if (me) return <Navigate to={me.role === 'caregiver' ? '/caregiver' : '/'} replace />

  const ready = username.trim() && password && (who === 'resident' || !isSignup || inviteCode.trim())

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (who === 'resident') {
        if (isSignup) await signupResident(username, password, hand)
        else await loginResident(username, password)
      } else if (isSignup) await signupCaregiver(username, password, displayName, inviteCode)
      else await loginCaregiver(username, password)
      navigate(from, { replace: true })
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const swapMode: Mode = isSignup ? 'login' : 'signup'
  const swapLabel =
    who === 'resident'
      ? isSignup
        ? 'I already have an account · Log in'
        : 'I’m new here · Create a resident account'
      : isSignup
        ? 'I already have an account · Log in'
        : 'I’m new to the care team · Register'
  const level = strength(password)

  return (
    <main className={`room au-page ${who === 'resident' ? 'dye-resident' : 'dye-care'}`}>
      {/* .door: the lantern lights up while you are writing in the form beside it */}
      <div className="au-grid door">
        <aside className="au-side">
          <Lantern shape={who === 'resident' ? 'column' : 'moon'} cord={who === 'resident' ? 70 : 110} delay={150}>
            <b>{who === 'resident' ? 'Resident' : 'Care team'}</b>
            <small>{text.line}</small>
          </Lantern>
        </aside>

        <section className="au-sheet" aria-labelledby="au-title">
          <StampMark size={44} />
          <nav className="au-tags" aria-label="Who is signing in?">
            {(['resident', 'caregiver'] as Who[]).map((w) => (
              <Link
                key={w}
                to={COPY[w].path[mode]}
                state={w === 'resident' ? { from } : undefined}
                className="au-tag"
                aria-current={who === w ? 'page' : undefined}
              >
                {w === 'resident' ? 'Resident' : 'Care team'}
              </Link>
            ))}
          </nav>

          <h1 id="au-title">{text.title}</h1>
          <p className="au-lede">{text.lede}</p>

          <form onSubmit={submit} noValidate>
            {who === 'caregiver' && isSignup && (
              <Field
                id="display"
                label="Your name (shown to your team)"
                hint="Optional. Leave blank to use your username."
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                autoComplete="name"
                maxLength={40}
              />
            )}

            <Field
              id="username"
              label="Username"
              hint={isSignup ? (who === 'resident' ? 'A nickname or code, 3–24 characters. Please don’t use your real name.' : '3–24 characters.') : undefined}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoCapitalize="none"
              maxLength={24}
              required
              autoFocus
            />

            <Field
              id="password"
              label="Password"
              hint={isSignup ? 'At least 8 characters.' : undefined}
              type={showPassword ? 'text' : 'password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={isSignup ? 'new-password' : 'current-password'}
              maxLength={128}
              required
              right={
                <button
                  type="button"
                  className="af-show"
                  onClick={() => setShowPassword((s) => !s)}
                  aria-pressed={showPassword}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  {showPassword ? <EyeSlash size={24} weight="light" aria-hidden /> : <Eye size={24} weight="light" aria-hidden />}
                  {showPassword ? 'Hide' : 'Show'}
                </button>
              }
            />
            {isSignup && (
              <div className="af-meter" aria-live="polite">
                {[1, 2, 3, 4].map((n) => (
                  <i key={n} className={level >= n ? 'on' : ''} />
                ))}
                <span>{LEVELS[level]}</span>
              </div>
            )}

            {who === 'caregiver' && isSignup && (
              <Field
                id="code"
                label="Care team access code"
                hint="Ask your care team lead. It keeps residents’ results private."
                value={inviteCode}
                onChange={(e) => setInviteCode(e.target.value)}
                autoComplete="off"
                autoCapitalize="characters"
                maxLength={128}
                required
              />
            )}

            {who === 'resident' && isSignup && (
              <fieldset className="af-hand">
                <legend>Which hand do you usually write with?</legend>
                <div>
                  {(['left', 'right', 'unknown'] as Hand[]).map((h) => (
                    <label key={h} className={hand === h ? 'on' : ''}>
                      <input type="radio" name="hand" value={h} checked={hand === h} onChange={() => setHand(h)} />
                      {h === 'unknown' ? 'Not sure' : h[0].toUpperCase() + h.slice(1)}
                    </label>
                  ))}
                </div>
              </fieldset>
            )}

            {error && (
              <p className="af-error" role="alert" key={error}>
                <WarningCircle size={26} weight="light" aria-hidden />
                {error}
              </p>
            )}

            <button type="submit" className="stamp af-submit" disabled={busy || !ready}>
              {busy ? 'One moment…' : text.cta}
            </button>
          </form>

          <Link className="au-swap" to={COPY[who].path[swapMode]} state={who === 'resident' ? { from } : undefined}>
            {swapLabel}
          </Link>
        </section>
      </div>
    </main>
  )
}
