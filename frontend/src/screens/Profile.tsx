import { useCallback, useState, type FormEvent, type ReactNode } from 'react'
import { ApiError, api } from '../api/client'
import type { MyMember, MyMemberUpdate } from '../api/types'
import { Icon } from '../components/Icon'
import { ErrorNotice } from '../components/Notice'
import { useToast } from '../components/toastContext'
import { Badge, Card, DetailList, Field, Modal, PageHeader, SkeletonPage } from '../components/ui'
import { useLoad } from '../hooks/useLoad'
import { ROLE_LABEL, displayName, useAuth } from '../lib/auth'
import { formatDate, formatDay, formatKes, parseShillings } from '../lib/format'
import { passwordErrors, type PasswordForm } from '../lib/forms'
import { applicantProblems } from '../lib/applicant'
import { toApplicantForm } from '../lib/apply'
import { normalisePhone } from '../lib/phone'
import { t } from '../strings'
import { ApplicantFields } from './Apply'
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
      {me.role === 'member' && me.member && <MemberRecord />}
      <div className={styles.grid}>
        <Card title={P.account}>
          <div className={styles.who}>
            <span className={styles.avatar} aria-hidden>{(me.member?.full_name ?? displayName(me)).slice(0, 1).toUpperCase()}</span>
            <div>
              <p className={styles.name}>{me.member?.full_name ?? displayName(me)}</p>
              <Badge tone={me.role === 'admin' ? 'attention' : me.role === 'member' ? 'info' : 'low'}>{ROLE_LABEL[me.role]}</Badge>
            </div>
          </div>
          <DetailList items={[
            [P.username, me.username],
            [P.role, ROLE_LABEL[me.role]],
            ...(me.member ? [[P.memberNo, me.member.member_no] as [string, string]] : []),
            // The Google sign-in address; a member's contact email is on their record above.
            ...(me.role !== 'member' || me.email
              ? [[P.email, me.email ?? <span key="e" className="subtle">{P.noEmail}</span>] as [string, ReactNode]] : []),
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

/** A member's own record. Staff keep the name, number, start date and a verified savings figure. */
function MemberRecord() {
  const R = t.memberRecord
  const load = useCallback(() => Promise.all([api.myMember(), api.applyOptions()]), [])
  const { data, error, reload, setData } = useLoad(load)
  if (error) return error.status === 404 ? null : <ErrorNotice doing={R.loadFailed} error={error} onRetry={reload} />
  if (!data) return null
  const [m, options] = data
  return <MemberRecordForm key={m.member_no} m={m} options={options} onSaved={(next) => setData([next, options])} />
}

function MemberRecordForm({ m, options, onSaved }: {
  m: MyMember; options: Awaited<ReturnType<typeof api.applyOptions>>; onSaved: (m: MyMember) => void
}) {
  const R = t.memberRecord
  const toast = useToast()
  const [phone, setPhone] = useState(m.phone ?? '')
  const [email, setEmail] = useState(m.email ?? '')
  const [savings, setSavings] = useState(m.savings_kes === null ? '' : String(m.savings_kes))
  const [form, setForm] = useState({
    age: m.age === null ? '' : String(m.age), sex: m.sex ?? '', education: m.education === null ? '' : String(m.education),
    marital: m.marital_status ?? '',
  } as { age: string; sex: MyMember['sex'] | ''; education: string; marital: MyMember['marital_status'] | '' })
  const [tried, setTried] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const locked = m.savings_status === 'verified'
  const formFilled = form.age !== '' || form.sex !== '' || form.education !== '' || form.marital !== ''
  const formProblems = formFilled
    ? applicantProblems({ age: form.age, sex: form.sex ?? '', education: form.education, marital: form.marital ?? '' })
    : []
  const errors = tried ? {
    phone: !normalisePhone(phone) ? R.errors.phone : null,
    email: email.trim() && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim()) ? R.errors.email : null,
    savings: !locked && savings.trim() && parseShillings(savings) === null ? R.errors.savings : null,
  } : { phone: null, email: null, savings: null }
  const formErrors = tried ? Object.fromEntries(formProblems.map((f) => [f, t.applicant.missing[f]])) : {}

  async function submit(e: FormEvent) {
    e.preventDefault()
    setTried(true)
    const typedSavings = parseShillings(savings)
    if (!normalisePhone(phone) || formProblems.length
        || (email.trim() && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim()))
        || (!locked && savings.trim() && typedSavings === null)) return
    const body: MyMemberUpdate = { phone: normalisePhone(phone)!, email: email.trim() || null }
    if (!locked && typedSavings !== null) body.savings_kes = typedSavings
    if (formFilled) {
      body.applicant = toApplicantForm({ age: form.age, sex: form.sex ?? '', education: form.education, marital: form.marital ?? '' })
    }
    setBusy(true)
    setError(null)
    try {
      onSaved(await api.updateMyMember(body))
      toast(R.saved)
      setTried(false)
    } catch (err) {
      setError(err as ApiError)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={styles.record}>
      <Card title={R.title}>
        <p className="muted small">{R.lead}</p>
        <DetailList items={[
          [R.fullName, m.full_name],
          [R.memberNo, m.member_no],
          [R.joined, formatDay(m.joined_on)],
          ...(locked ? [[R.savingsLocked, formatKes(m.savings_kes!)] as [string, string]] : []),
          ...(m.savings_kes !== null ? [[t.apply.savingsVerification, (
            <Badge key="sv" tone={locked ? 'low' : 'wait'} icon={locked ? 'check' : 'clock'}>{t.savingsStatus[m.savings_status]}</Badge>
          )] as [string, ReactNode]] : []),
        ]} />
        <form className={styles.form} onSubmit={submit} noValidate>
          <Field id="me-phone" label={R.phone} error={errors.phone}>
            {(p) => <input {...p} className="input" type="tel" inputMode="tel" autoComplete="tel" maxLength={32} value={phone}
                           onChange={(e) => setPhone(e.target.value)} />}
          </Field>
          <Field id="me-email" label={R.email} optional hint={R.emailHint} error={errors.email}>
            {(p) => <input {...p} className="input" type="email" inputMode="email" autoComplete="email" maxLength={254} value={email}
                           onChange={(e) => setEmail(e.target.value)} />}
          </Field>
          {!locked && (
            <Field id="me-savings" label={R.savings} optional hint={R.savingsHint} error={errors.savings}>
              {(p) => <input {...p} className="input num" inputMode="numeric" autoComplete="off" value={savings}
                             onChange={(e) => setSavings(e.target.value)} />}
            </Field>
          )}
          <div>
            <p className="field-label">{R.applicant}</p>
            <p className="subtle small">{R.applicantLead}</p>
            <ApplicantFields d={{ age: form.age, sex: form.sex ?? '', education: form.education, marital: form.marital ?? '' }}
                             options={options} errors={formErrors}
                             put={(k, v) => setForm((f) => ({ ...f, [k]: v }))} />
          </div>
          {error && <ErrorNotice doing={R.failed} error={error} />}
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy && <span className="spinner" aria-hidden />} {busy ? R.saving : R.save}
          </button>
        </form>
      </Card>
    </div>
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
