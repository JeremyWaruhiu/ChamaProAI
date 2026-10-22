import { useEffect, useRef, useState, type FormEvent, type Ref } from 'react'
import { ApiError, api } from '../api/client'
import type { Me } from '../api/types'
import { GOOGLE_NOT_ENABLED, googleStatusFor, mountGoogleButton, type GoogleStatus } from '../lib/google'
import styles from './Login.module.css'

/** API messages are lower-case fragments; the form shows them as a sentence. */
function sentence(message: string): string {
  const s = message.trim()
  if (!s) return s
  const capped = s[0].toUpperCase() + s.slice(1)
  return /[.!?]$/.test(capped) ? capped : `${capped}.`
}

export function Login({ onSignedIn }: { onSignedIn: (me: Me) => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [shown, setShown] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const userRef = useRef<HTMLInputElement>(null)
  const passRef = useRef<HTMLInputElement>(null)

  const [clientId, setClientId] = useState<string | null>(null)
  const [google, setGoogle] = useState<GoogleStatus>('off')
  const [googleBusy, setGoogleBusy] = useState(false)
  const [googleError, setGoogleError] = useState<string | null>(null)
  const googleRef = useRef<HTMLDivElement>(null)
  // The parent passes a new callback on each render; GIS must be set up only once.
  const signedIn = useRef(onSignedIn)
  useEffect(() => { signedIn.current = onSignedIn }, [onSignedIn])

  useEffect(() => { userRef.current?.focus() }, [])

  // Show Google sign-in only when the server has a client ID configured.
  useEffect(() => {
    let alive = true
    api.authConfig()
      .then((cfg) => {
        if (!alive) return
        setGoogle(googleStatusFor(cfg))
        setClientId(cfg.google_client_id)
      })
      .catch(() => { /* no config, no Google button; password sign-in is unaffected */ })
    return () => { alive = false }
  }, [])

  // Once its container is on the page, let Google render the button into it.
  useEffect(() => {
    const el = googleRef.current
    if (!clientId || !el) return
    let alive = true
    mountGoogleButton({
      clientId, el,
      signIn: api.googleLogin,
      onSignedIn: (me) => signedIn.current(me),
      onBusy: (b) => { if (alive) { setGoogleBusy(b); if (b) { setGoogleError(null); setError(null) } } },
      onError: (e) => { if (alive) setGoogleError(sentence(e.message)) },
    })
      .then(() => { if (alive) setGoogle('ready') })
      .catch(() => { if (alive) setGoogle('unavailable') })
    return () => { alive = false }
  }, [clientId])

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (busy || googleBusy) return
    if (!username.trim() || !password) {
      setError('Enter your username and password.')
      ;(username.trim() ? passRef : userRef).current?.focus()
      return
    }
    setBusy(true)
    setError(null)
    setGoogleError(null)
    try {
      onSignedIn(await api.login(username, password))
    } catch (err) {
      const apiErr = err as ApiError
      setError(sentence(apiErr.message))
      setBusy(false)
      if (apiErr.status === 401) {
        setPassword('')
        passRef.current?.focus()
      }
    }
  }

  return (
    <LoginForm username={username} password={password} shown={shown} busy={busy} error={error}
               userRef={userRef} passRef={passRef}
               onUsername={setUsername} onPassword={setPassword}
               onToggle={() => setShown((v) => !v)} onSubmit={submit}
               google={google} googleRef={googleRef} googleBusy={googleBusy} googleError={googleError}
               onGooglePlaceholder={() => setGoogleError(GOOGLE_NOT_ENABLED)} />
  )
}

interface FormProps {
  username: string
  password: string
  shown: boolean
  busy: boolean
  error: string | null
  userRef?: Ref<HTMLInputElement>
  passRef?: Ref<HTMLInputElement>
  onUsername: (v: string) => void
  onPassword: (v: string) => void
  onToggle: () => void
  onSubmit: (e: FormEvent) => void
  google?: GoogleStatus
  googleRef?: Ref<HTMLDivElement>
  googleBusy?: boolean
  googleError?: string | null
  /** Pressed the Google button while Google sign-in is not configured. */
  onGooglePlaceholder?: () => void
}

/** The sign-in form itself, stateless so it can be rendered in tests. */
export function LoginForm({
  username, password, shown, busy, error, userRef, passRef, onUsername, onPassword, onToggle, onSubmit,
  google = 'off', googleRef, googleBusy = false, googleError = null, onGooglePlaceholder,
}: FormProps) {
  const invalid = error ? true : undefined
  return (
    <div className={styles.page}>
      <header className={styles.bar}>
        <span className={styles.brand}>ChamaPro AI</span>
      </header>
      <main className={styles.main}>
        <div className={`card ${styles.card}`}>
          <div className={styles.intro}>
            <h1 id="login-title" className={styles.title}>ChamaPro AI</h1>
            <p className={styles.tagline}>SACCO credit assessment from Kikuyu loan interviews</p>
          </div>

          <form className={styles.form} onSubmit={onSubmit} noValidate aria-labelledby="login-title">
            <div className={styles.field}>
              <label className={styles.label} htmlFor="login-username">Username</label>
              <input id="login-username" ref={userRef} className="input" name="username" type="text"
                     autoComplete="username" autoCapitalize="none" autoCorrect="off" spellCheck={false}
                     required maxLength={64} value={username} readOnly={busy}
                     aria-invalid={invalid} aria-describedby={error ? 'login-error' : undefined}
                     onChange={(e) => onUsername(e.target.value)} />
            </div>

            <div className={styles.field}>
              <label className={styles.label} htmlFor="login-password">Password</label>
              <div className={styles.passwordRow}>
                <input id="login-password" ref={passRef} className={`input ${styles.passwordInput}`} name="password"
                       type={shown ? 'text' : 'password'} autoComplete="current-password"
                       required maxLength={1024} value={password} readOnly={busy}
                       aria-invalid={invalid} aria-describedby={error ? 'login-error' : undefined}
                       onChange={(e) => onPassword(e.target.value)} />
                <button type="button" className={styles.toggle} onClick={onToggle}
                        aria-controls="login-password" aria-pressed={shown}
                        aria-label={shown ? 'Hide password' : 'Show password'}>
                  {shown ? 'Hide' : 'Show'}
                </button>
              </div>
            </div>

            <p id="login-error" className={styles.error} role="alert">
              {error}
            </p>

            <button type="submit" className="btn btn-primary btn-large btn-block"
                    aria-disabled={busy || googleBusy || undefined} aria-busy={busy || undefined}>
              {busy && <span className="spinner" aria-hidden />}
              {busy ? 'Signing in…' : 'Sign in'}
            </button>
          </form>

          {google !== 'off' && (
            <section className={styles.google} aria-label="Sign in with Google">
              <div className={styles.divider}><span>or</span></div>
              {google === 'disabled' ? <GooglePlaceholder onClick={onGooglePlaceholder} /> : (
                /* Google Identity Services renders its own branded button here. */
                <div id="google-signin" ref={googleRef} className={styles.googleButton}
                     hidden={google === 'unavailable'} aria-busy={google === 'loading' || googleBusy || undefined} />
              )}
              {google === 'unavailable' && (
                <p className={styles.help}>Google sign-in could not load. Use your username and password.</p>
              )}
              {googleBusy && (
                <p className={styles.status} role="status"><span className="spinner" aria-hidden /> Signing in with Google…</p>
              )}
              <p id="google-error" className={styles.error} role="alert">{googleError}</p>
            </section>
          )}

          <p className={styles.help}>Accounts are created by your SACCO administrator.</p>
        </div>
      </main>
    </div>
  )
}

/**
 * Shown when the server has no Google client ID. Not Google's button and no
 * Google artwork: a plain "G" on our own secondary button. Pressing it never
 * loads Google's script; the page explains that Google sign-in is not set up.
 */
export function GooglePlaceholder({ onClick }: { onClick?: () => void }) {
  return (
    <button type="button" className="btn btn-secondary btn-block"
            aria-describedby="google-error" onClick={onClick}>
      <span className={styles.gMark} aria-hidden>G</span>
      Sign in with Google
    </button>
  )
}
