import { AnimatePresence, m } from 'motion/react'
import { useCallback, useRef, useState, type FormEvent } from 'react'
import { ApiError, api } from '../api/client'
import type { MyApplication as Mine, MyGuarantor } from '../api/types'
import { OutcomeBadge } from '../components/Badges'
import { Icon } from '../components/Icon'
import { ErrorNotice } from '../components/Notice'
import { Badge, Card, DetailList, Field, PracticeBadge, SkeletonPage, Timeline } from '../components/ui'
import { useLoad } from '../hooks/useLoad'
import { formatDate, formatKes } from '../lib/format'
import { checkGuarantors, emptyGuarantor, toGuarantorIn, type GuarantorCheck, type GuarantorDraft } from '../lib/guarantors'
import { fadeUp, useReducedMotion } from '../lib/motion'
import { paths } from '../lib/router'
import { STATUS_TONE, memberStages, type Tone } from '../lib/status'
import { t } from '../strings'
import styles from './Member.module.css'

const Y = t.my
const F = t.guarantorForm
const G_TONE: Record<MyGuarantor['status'], Tone> = { pending: 'wait', verified: 'low', rejected: 'high' }

export function MyApplication({ id }: { id: number }) {
  const load = useCallback(() => api.myApplication(id), [id])
  const { data: app, error, reload, setData } = useLoad(load)
  const [submitted, setSubmitted] = useState(false)
  const reduced = useReducedMotion()

  if (error) return <><Back /><ErrorNotice doing={Y.detailFailed} error={error} onRetry={reload} /></>
  if (!app) return <><Back /><SkeletonPage what={Y.title} /></>
  const stages = memberStages(app.status, app.timeline, app.guarantors_required)
  const cap = app.approved_amount_kes ?? app.amount_requested_kes

  return (
    <div className={styles.detail}>
      <Back />
      <m.header className={styles.head} {...fadeUp(reduced)}>
        <h1 className={`display ${styles.title}`}>{Y.titleFor(app.purpose)}</h1>
        <p className="muted">{Y.amountFor(app.amount_requested_kes, app.term_months)} · {Y.applied(formatDate(app.created_at))}</p>
        <div className={styles.badges}>
          <Badge tone={STATUS_TONE[app.status]}>{app.status_label}</Badge>
          {app.mode === 'practice' && <PracticeBadge />}
        </div>
      </m.header>

      {app.mode === 'practice' && <p className={styles.practice}><Icon name="sparkle" size={18} /> {Y.practiceNote}</p>}

      <Card title={Y.progress}>
        <Timeline label={Y.progress} items={stages.map((s) => ({
          key: s.key, title: s.label, state: s.state, stateLabel: Y.stageState[s.state],
          meta: s.at ? formatDate(s.at) : s.state === 'current' ? Y.stageState.current : undefined,
        }))} />
      </Card>

      {app.outcome && (
        <Card title={Y.outcome} delay={0.05}>
          <div className={styles.badges}><OutcomeBadge outcome={app.outcome} /></div>
          <DetailList items={[
            [Y.requested, formatKes(app.amount_requested_kes)],
            ...(app.approved_amount_kes ? [[Y.approved, formatKes(app.approved_amount_kes)] as [string, string]] : []),
            [Y.term, t.common.months(app.term_months)],
          ]} />
          {app.member_message && (
            <div className={styles.message}>
              <p className={styles.messageLabel}><Icon name="user" size={16} /> {Y.fromOfficer}</p>
              <p>{app.member_message}</p>
            </div>
          )}
        </Card>
      )}

      {app.reasons.length > 0 && (
        <Card title={Y.reasons} delay={0.1}>
          <p className="muted small">{Y.reasonsLead}</p>
          <ul className={styles.reasons}>{app.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        </Card>
      )}

      <Card title={Y.next} delay={0.15}>
        <p>{Y.nextSteps[app.status]}</p>
      </Card>

      <AnimatePresence mode="wait" initial={false}>
        {app.guarantors_still_needed > 0 ? (
          <m.div key="form" {...fadeUp(reduced)}>
            <GuarantorSection app={app} cap={cap} onSubmitted={(next) => { setData(next); setSubmitted(true) }} />
          </m.div>
        ) : submitted ? (
          <m.div key="done" className={styles.done} role="status" {...fadeUp(reduced)}>
            <span className={styles.doneIcon}><Icon name="check" size={26} /></span>
            <div>
              <p className={styles.doneTitle}>{F.doneTitle}</p>
              <p className="muted">{F.doneBody}</p>
            </div>
          </m.div>
        ) : null}
      </AnimatePresence>

      {app.guarantors.length > 0 && (
        <Card title={Y.guarantorsTitle}>
          <ul className={styles.guarantors}>
            {app.guarantors.map((g, i) => (
              <li key={`${g.member_no}-${i}`} className={styles.guarantor}>
                <div>
                  <p className={styles.gName}>{g.full_name}</p>
                  <p className="subtle small">{g.member_no} · {g.relationship} · {Y.guaranteed(g.amount_guaranteed_kes)}</p>
                </div>
                <Badge tone={G_TONE[g.status]} icon={g.status === 'verified' ? 'check' : g.status === 'rejected' ? 'x' : 'clock'}>
                  {Y.guarantorStatus[g.status]}
                </Badge>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}

function Back() {
  return <a href={paths.my()} className={styles.back}><Icon name="arrowLeft" size={16} /> {Y.back}</a>
}

function GuarantorSection({ app, cap, onSubmitted }: { app: Mine; cap: number; onSubmitted: (a: Mine) => void }) {
  const needed = app.guarantors_still_needed
  const [rows, setRows] = useState<GuarantorDraft[]>(() => Array.from({ length: needed }, emptyGuarantor))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  async function submit() {
    setBusy(true)
    setError(null)
    try {
      onSubmitted(await api.submitGuarantors(app.id, toGuarantorIn(rows)))
    } catch (e) {
      setError(e as ApiError)
      setBusy(false)
    }
  }

  return (
    <section className={styles.cta} aria-labelledby="guarantor-cta">
      <div className={styles.ctaHead}>
        <span className={styles.ctaIcon}><Icon name="users" size={24} /></span>
        <div>
          <h2 id="guarantor-cta" className={styles.ctaTitle}>{F.cta(needed)}</h2>
          <p className="muted">{F.ctaBody(needed)}</p>
        </div>
      </div>
      <GuarantorForm rows={rows} setRows={setRows} needed={needed} cap={cap} busy={busy} onSubmit={submit} />
      {error && <ErrorNotice doing={F.failed} error={error} onRetry={submit} />}
    </section>
  )
}

/** The guarantor form itself: exactly `needed` guarantors, checked before anything is sent. */
export function GuarantorForm({ rows, setRows, needed, cap, busy = false, onSubmit, initialCheck }: {
  rows: GuarantorDraft[]; setRows: (r: GuarantorDraft[]) => void; needed: number; cap: number
  busy?: boolean; onSubmit: () => void
  /** For tests: render as if the form had been submitted once. */
  initialCheck?: boolean
}) {
  const [tried, setTried] = useState(!!initialCheck)
  const summary = useRef<HTMLParagraphElement>(null)
  const check: GuarantorCheck = tried ? checkGuarantors(rows, needed, cap) : { rows: [], form: null, count: 0 }
  const put = (i: number, k: keyof GuarantorDraft, v: string) => setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)))

  function submit(e: FormEvent) {
    e.preventDefault()
    setTried(true)
    if (checkGuarantors(rows, needed, cap).count) {
      window.setTimeout(() => summary.current?.focus(), 0)
      return
    }
    onSubmit()
  }

  return (
    <form className={styles.gForm} onSubmit={submit} noValidate aria-label={F.title}>
      {check.count > 0 && (
        <p ref={summary} tabIndex={-1} className={styles.summary} role="alert">
          <Icon name="alert" size={18} /> {check.form ?? F.fixErrors(check.count)}
        </p>
      )}
      {rows.map((g, i) => {
        const e = check.rows[i] ?? {}
        const id = (k: string) => `g${i}-${k}`
        return (
          <fieldset key={i} className={styles.gFieldset}>
            <legend className={styles.gLegend}>{F.guarantorN(i + 1, rows.length)}</legend>
            <Field id={id('name')} label={F.fullName} error={e.full_name}>
              {(p) => <input {...p} className="input" value={g.full_name} autoComplete="off" maxLength={200} disabled={busy}
                             onChange={(ev) => put(i, 'full_name', ev.target.value)} />}
            </Field>
            <Field id={id('no')} label={F.memberNo} error={e.member_no}>
              {(p) => <input {...p} className="input" value={g.member_no} autoComplete="off" maxLength={32} disabled={busy}
                             autoCapitalize="characters" onChange={(ev) => put(i, 'member_no', ev.target.value)} />}
            </Field>
            <Field id={id('phone')} label={F.phone} hint={F.phoneHint} error={e.phone}>
              {(p) => <input {...p} className="input" type="tel" inputMode="tel" value={g.phone} autoComplete="off" disabled={busy}
                             onChange={(ev) => put(i, 'phone', ev.target.value)} />}
            </Field>
            <Field id={id('rel')} label={F.relationship} hint={F.relationshipHint} error={e.relationship}>
              {(p) => <input {...p} className="input" value={g.relationship} maxLength={60} disabled={busy}
                             onChange={(ev) => put(i, 'relationship', ev.target.value)} />}
            </Field>
            <Field id={id('amount')} label={F.amount} hint={F.amountHint(cap)} error={e.amount}>
              {(p) => <input {...p} className="input num" inputMode="numeric" value={g.amount} autoComplete="off" disabled={busy}
                             onChange={(ev) => put(i, 'amount', ev.target.value)} />}
            </Field>
          </fieldset>
        )
      })}
      <button type="submit" className="btn btn-primary btn-large btn-block" disabled={busy} aria-busy={busy || undefined}>
        {busy && <span className="spinner" aria-hidden />} {busy ? F.submitting : F.submit(needed)}
      </button>
    </form>
  )
}
