import { useCallback, useState, type FormEvent } from 'react'
import { ApiError, api } from '../api/client'
import { Icon } from '../components/Icon'
import { ErrorNotice } from '../components/Notice'
import { useToast } from '../components/toastContext'
import { Badge, Card, DetailList, Field, Modal, PageHeader, SkeletonPage } from '../components/ui'
import { useLoad } from '../hooks/useLoad'
import { ROLE_LABEL, useAuth } from '../lib/auth'
import { formatDate } from '../lib/format'
import { passwordErrors, type PasswordForm } from '../lib/forms'
import { t } from '../strings'
import styles from './Profile.module.css'

const P = t.profile

export function Profile() {
  const load = useCallback(() => api.profile(), [])
  const { data: me, error, reload } = useLoad(load)

  if (error) return <ErrorNotice doing={P.loadFailed} error={error} onRetry={reload} />
  if (!me) return <SkeletonPage what={P.title} />

  const google = me.email ? P.googleLinked(me.email) : me.google_sign_in_available ? P.googleNotLinked : P.googleUnavailable
  return (
    <>
      <PageHeader title={P.title} lead={P.lead} />
      <div className={styles.grid}>
        <Card title={P.account}>
          <div className={styles.who}>
            <span className={styles.avatar} aria-hidden>{(me.member?.full_name ?? me.username).slice(0, 1).toUpperCase()}</span>
            <div>
              <p className={styles.name}>{me.member?.full_name ?? me.username}</p>
              <Badge tone={me.role === 'admin' ? 'attention' : me.role === 'member' ? 'info' : 'low'}>{ROLE_LABEL[me.role]}</Badge>
            </div>
          </div>
          <DetailList items={[
            [P.username, me.username],
            [P.role, ROLE_LABEL[me.role]],
            ...(me.member ? [[P.memberNo, me.member.member_no] as [string, string]] : []),
            [P.email, me.email ?? <span key="e" className="subtle">{P.noEmail}</span>],
            [P.google, <span key="g" className={styles.google}>
              {me.email ? <Badge tone="low" icon="check">G</Badge> : <Badge>G</Badge>} {google}
            </span>],
            [P.since, formatDate(me.created_at)],
            [P.thisSession, <span key="s">{me.signed_in_with && P.signedInWith(me.signed_in_with)} {P.sessions(me.active_sessions)}</span>],
          ]} />
        </Card>
        <div className={styles.stack}>
          <ChangePassword />
          <SignOutEverywhere />
        </div>
      </div>
    </>
  )
}

function ChangePassword() {
  const toast = useToast()
  const empty: PasswordForm = { current: '', next: '', confirm: '' }
  const [f, setF] = useState<PasswordForm>(empty)
  const [tried, setTried] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const errors = tried ? passwordErrors(f) : {}
  const put = (k: keyof PasswordForm, v: string) => setF((x) => ({ ...x, [k]: v }))

  async function submit(e: FormEvent) {
    e.preventDefault()
    setTried(true)
    if (Object.keys(passwordErrors(f)).length) return
    setBusy(true)
    setError(null)
    try {
      await api.changePassword(f.current, f.next)
      toast(P.changed)
      setF(empty)
      setTried(false)
    } catch (err) {
      setError(err as ApiError)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card title={P.password} delay={0.05}>
      <p className="muted small">{P.passwordLead}</p>
      <form className={styles.form} onSubmit={submit} noValidate>
        <Field id="pw-current" label={P.current} error={errors.current}>
          {(p) => <input {...p} className="input" type="password" autoComplete="current-password" value={f.current}
                         onChange={(e) => put('current', e.target.value)} />}
        </Field>
        <Field id="pw-new" label={P.new} hint={P.newHint} error={errors.next}>
          {(p) => <input {...p} className="input" type="password" autoComplete="new-password" value={f.next}
                         onChange={(e) => put('next', e.target.value)} />}
        </Field>
        <Field id="pw-confirm" label={P.confirm} error={errors.confirm}>
          {(p) => <input {...p} className="input" type="password" autoComplete="new-password" value={f.confirm}
                         onChange={(e) => put('confirm', e.target.value)} />}
        </Field>
        {error && <ErrorNotice doing={P.changeFailed} error={error} />}
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? <span className="spinner" aria-hidden /> : <Icon name="key" />} {busy ? P.changing : P.change}
        </button>
      </form>
    </Card>
  )
}

function SignOutEverywhere() {
  const { signOut } = useAuth()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  async function go() {
    setBusy(true)
    setError(null)
    try {
      await api.logoutAll()
      setOpen(false)
      signOut()
    } catch (e) {
      setError(e as ApiError)
      setBusy(false)
    }
  }

  return (
    <Card title={P.everywhere} delay={0.1}>
      <p className="muted small">{P.everywhereLead}</p>
      <button type="button" className={`btn btn-danger ${styles.spaced}`} onClick={() => setOpen(true)}>
        <Icon name="logout" /> {P.everywhereButton}
      </button>
      <Modal open={open} title={P.everywhereConfirm} onClose={() => setOpen(false)}
             actions={<>
               <button type="button" className="btn btn-quiet" onClick={() => setOpen(false)}>{t.common.cancel}</button>
               <button type="button" className="btn btn-danger" onClick={go} disabled={busy}>
                 {busy && <span className="spinner" aria-hidden />} {P.everywhereButton}
               </button>
             </>}>
        <p>{P.everywhereLead}</p>
        {error && <ErrorNotice doing={P.everywhereFailed} error={error} />}
      </Modal>
    </Card>
  )
}
