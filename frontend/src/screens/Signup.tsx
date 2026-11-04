import { useCallback, useState, type FormEvent } from 'react'
import { ApiError, api } from '../api/client'
import type { Me, SignupInfo } from '../api/types'
import { Icon } from '../components/Icon'
import { ErrorNotice, Notice } from '../components/Notice'
import { Field, Skeleton } from '../components/ui'
import { useLoad } from '../hooks/useLoad'
import { EMPTY_SIGNUP, signupErrors, toSignupBody, type SignupDraft } from '../lib/signup'
import { paths } from '../lib/router'
import { t } from '../strings'
import { LoginPage } from './Login'
import loginStyles from './Login.module.css'
import styles from './Signup.module.css'

const S = t.signup

export function Signup({ onSignedIn }: { onSignedIn: (me: Me) => void }) {
  const load = useCallback(() => api.signupInfo(), [])
  const { data: info, error, reload } = useLoad(load)
  return (
    <LoginPage asideTitle={S.asideTitle} asideBody={S.asideBody}>
      <div className={`card ${loginStyles.card}`}>
        {error && <ErrorNotice doing={S.loadFailed} error={error} onRetry={reload} />}
        {!info && !error && <Skeleton height={320} radius={12} />}
        {info && !info.enabled && (
          <Notice title={S.closed} action={<a className="btn btn-secondary" href={paths.login()}>{S.signIn}</a>}>{S.closedBody}</Notice>
        )}
        {info?.enabled && <SignupForm info={info} onSignedIn={onSignedIn} />}
      </div>
    </LoginPage>
  )
}

export function SignupForm({ info, onSignedIn }: { info: SignupInfo; onSignedIn: (me: Me) => void }) {
  const [d, setD] = useState<SignupDraft>(EMPTY_SIGNUP)
  const [tried, setTried] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const errors = tried ? signupErrors(d) : {}
  const put = <K extends keyof SignupDraft>(k: K, v: SignupDraft[K]) => setD((x) => ({ ...x, [k]: v }))

  async function submit(e: FormEvent) {
    e.preventDefault()
    setTried(true)
    if (Object.keys(signupErrors(d)).length) return
    setBusy(true)
    setError(null)
    try {
      onSignedIn(await api.signup(toSignupBody(d, info.consent_version)))
    } catch (err) {
      setError(err as ApiError)
      setBusy(false)
    }
  }

  return (
    <form className={styles.form} onSubmit={submit} noValidate aria-labelledby="signup-title">
      <div>
        <h1 id="signup-title" className={`display ${styles.title}`}>{S.title}</h1>
        <p className="muted">{S.lead}</p>
      </div>
      <Field id="su-name" label={S.fullName} error={errors.full_name}>
        {(p) => <input {...p} className="input" autoComplete="name" maxLength={200} value={d.full_name}
                       onChange={(e) => put('full_name', e.target.value)} />}
      </Field>
      <Field id="su-phone" label={S.phone} hint={S.phoneHint} error={errors.phone}>
        {(p) => <input {...p} className="input" type="tel" inputMode="tel" autoComplete="tel" maxLength={32} value={d.phone}
                       onChange={(e) => put('phone', e.target.value)} />}
      </Field>
      <Field id="su-email" label={S.email} optional error={errors.email}>
        {(p) => <input {...p} className="input" type="email" inputMode="email" autoComplete="email" maxLength={254} value={d.email}
                       onChange={(e) => put('email', e.target.value)} />}
      </Field>
      <Field id="su-password" label={S.password} hint={S.passwordHint} error={errors.password}>
        {(p) => <input {...p} className="input" type="password" autoComplete="new-password" maxLength={1024} value={d.password}
                       onChange={(e) => put('password', e.target.value)} />}
      </Field>
      <Field id="su-confirm" label={S.confirm} error={errors.confirm}>
        {(p) => <input {...p} className="input" type="password" autoComplete="new-password" maxLength={1024} value={d.confirm}
                       onChange={(e) => put('confirm', e.target.value)} />}
      </Field>
      <Field id="su-invite" label={S.invite} hint={S.inviteHint} error={errors.invite}>
        {(p) => <input {...p} className="input" autoComplete="off" autoCapitalize="none" spellCheck={false} maxLength={200} value={d.invite}
                       onChange={(e) => put('invite', e.target.value)} />}
      </Field>
      <ConsentBox text={info.consent_text} checked={d.consent} onChange={(v) => put('consent', v)} error={errors.consent}
                  title={S.consentTitle} agree={S.consentAgree} />
      {error && <ErrorNotice doing={S.failed} error={error} />}
      <button type="submit" className="btn btn-primary btn-large btn-block" disabled={busy} aria-busy={busy || undefined}>
        {busy && <span className="spinner" aria-hidden />} {busy ? S.submitting : S.submit}
      </button>
      <p className={styles.alt}>{S.haveAccount} <a href={paths.login()}>{S.signIn}</a></p>
    </form>
  )
}

/** The consent text, always in full, and the box that says it has been read. */
export function ConsentBox({ text, checked, onChange, error, title, agree }: {
  text: string[]; checked: boolean; onChange: (v: boolean) => void; error?: string | null; title: string; agree: string
}) {
  return (
    <section className={styles.consent} aria-labelledby="consent-title">
      <p id="consent-title" className={styles.consentTitle}><Icon name="shield" size={18} /> {title}</p>
      <ul className={styles.consentText}>{text.map((line) => <li key={line}>{line}</li>)}</ul>
      <label className="choice">
        <input type="checkbox" checked={checked} aria-invalid={error ? true : undefined}
               aria-describedby={error ? 'consent-error' : undefined} onChange={(e) => onChange(e.target.checked)} />
        <span>{agree}</span>
      </label>
      {error && <p id="consent-error" className="field-error">{error}</p>}
    </section>
  )
}
