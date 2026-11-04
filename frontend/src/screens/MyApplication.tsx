import { AnimatePresence, m } from 'motion/react'
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { ApiError, api } from '../api/client'
import type { Language, MyApplication as Mine, MyGuarantor, MyMember, SignupInfo } from '../api/types'
import { OutcomeBadge } from '../components/Badges'
import { Icon } from '../components/Icon'
import { ErrorNotice } from '../components/Notice'
import { SlotPicker } from '../components/SlotPicker'
import { Badge, Card, DetailList, Field, PracticeBadge, SkeletonPage, Timeline } from '../components/ui'
import { useLoad } from '../hooks/useLoad'
import { formatDate, formatKes } from '../lib/format'
import { formatNairobi } from '../lib/nairobi'
import { checkGuarantors, emptyGuarantor, toGuarantorIn, type GuarantorCheck, type GuarantorDraft } from '../lib/guarantors'
import { fadeUp, useReducedMotion } from '../lib/motion'
import { navigate, paths } from '../lib/router'
import { STATUS_TONE, memberStages, type Tone } from '../lib/status'
import { t } from '../strings'
import { ConsentBox } from './Signup'
import styles from './Member.module.css'

const Y = t.my
const F = t.guarantorForm
const K = t.myBooking
const P = t.practice
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

      <BookingCard app={app} onChanged={setData} />

      <Card title={Y.next} delay={0.15}>
        <p>{app.status === 'interview_pending' && app.booking && !['started', 'cancelled'].includes(app.booking.status)
          ? K.nextBooked : Y.nextSteps[app.status]}</p>
      </Card>

      <AnimatePresence mode="wait" initial={false}>
        {app.guarantors_still_needed > 0 ? (
          <m.div key="form" {...fadeUp(reduced)}>
            <GuarantorSection key={app.guarantors_still_needed} app={app} cap={cap}
                              onSubmitted={(next) => { setData(next); setSubmitted(next.status !== 'guarantor_required') }} />
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

      <PracticeCard app={app} />

      {(app.history?.length ?? 0) > 0 && (
        <Card title={t.history.title}>
          <ol className={styles.history}>
            {app.history!.map((h, i) => (
              <li key={i}><span>{h.label}</span> <span className="subtle small">{formatDate(h.at)}</span></li>
            ))}
          </ol>
        </Card>
      )}
    </div>
  )
}

/** The booked interview, or booking one if none stands. */
function BookingCard({ app, onChanged }: { app: Mine; onChanged: (a: Mine) => void }) {
  const [slot, setSlot] = useState({ date: '', time: '' })
  const [language, setLanguage] = useState<Language>('kik')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const b = app.booking
  const canBook = !b && (app.status === 'draft' || app.status === 'interview_pending')
  if (!b && !canBook) return null

  async function book() {
    setBusy(true)
    setError(null)
    try {
      onChanged(await api.bookInterview(app.id, { ...slot, language }))
    } catch (e) {
      setError(e as ApiError)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card title={K.title}>
      {b ? (
        <>
          <p className={styles.nextWhen}><Icon name="clock" size={18} /> {formatNairobi(b.starts_at)}</p>
          <div className={styles.badges}>
            <Badge tone={b.status === 'confirmed' ? 'low' : 'wait'}>{t.booking.status[b.status]}</Badge>
            <Badge>{b.language === 'en' ? t.common.english : t.common.kikuyu}</Badge>
          </div>
        </>
      ) : (
        <>
          <p className="muted">{K.none}</p>
          <div className={styles.bookForm}>
            <LanguageChoice name="bk-language" value={language} onChange={setLanguage} legend={t.apply.language} />
            <SlotPicker date={slot.date} time={slot.time} idPrefix="bk" onChange={setSlot} />
            {error && <ErrorNotice doing={K.failed} error={error} />}
            <button type="button" className="btn btn-primary btn-block" onClick={book} disabled={busy || !slot.date || !slot.time}>
              {busy && <span className="spinner" aria-hidden />} {busy ? K.booking : K.book}
            </button>
          </div>
        </>
      )}
    </Card>
  )
}

function LanguageChoice({ name, value, onChange, legend }: { name: string; value: Language; onChange: (l: Language) => void; legend: string }) {
  return (
    <fieldset className={styles.fieldset}>
      <legend className="field-label">{legend}</legend>
      {(['kik', 'en'] as const).map((l) => (
        <label key={l} className="choice">
          <input type="radio" name={name} checked={value === l} onChange={() => onChange(l)} />
          <span>{l === 'kik' ? t.common.kikuyu : t.common.english}</span>
        </label>
      ))}
    </fieldset>
  )
}

/** Practice interviews on this application: start one, carry on, or see a result. */
function PracticeCard({ app }: { app: Mine }) {
  const [language, setLanguage] = useState<Language>('kik')
  const [member, setMember] = useState<MyMember | null>(null)
  const [info, setInfo] = useState<SignupInfo | null>(null)
  const [agreed, setAgreed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const attempts = app.practice ?? []
  const open = attempts.find((a) => a.status === 'open')

  useEffect(() => {
    let live = true
    api.myMember().then((m) => { if (live) setMember(m) }).catch(() => { /* the start button still reports any problem */ })
    api.signupInfo().then((i) => { if (live) setInfo(i) }).catch(() => { /* as above */ })
    return () => { live = false }
  }, [])

  const needConsent = member?.consent_current === false
  const needForm = member?.applicant_complete === false

  async function start() {
    setBusy(true)
    setError(null)
    try {
      if (needConsent && info) await api.giveConsent(info.consent_version)
      const p = await api.startPractice(app.id, language)
      navigate(paths.practice(p.id))
    } catch (e) {
      setError(e as ApiError)
      setBusy(false)
    }
  }

  return (
    <Card title={<>{P.cardTitle} <PracticeBadge /></>}>
      <p className="muted small">{P.cardLead}</p>
      {attempts.length > 0 && (
        <ul className={styles.attempts}>
          {attempts.map((a) => (
            <li key={a.id} className={styles.attempt}>
              <span>
                {a.language === 'en' ? t.common.english : t.common.kikuyu} · {formatDate(a.created_at)}
                <span className="subtle small"> · {a.status === 'assessed' ? P.done : P.attempt(a.answered, a.questions_total)}</span>
              </span>
              <a className="btn btn-secondary btn-sm" href={a.status === 'assessed' ? paths.practiceResult(a.id) : paths.practice(a.id)}>
                {a.status === 'assessed' ? P.viewResult : P.continue}
              </a>
            </li>
          ))}
        </ul>
      )}
      {!open && needForm && (
        <p className={styles.nextLink}><a href={paths.profile()}>{P.needForm} {P.goToProfile}</a></p>
      )}
      {!open && !needForm && (
        <div className={styles.bookForm}>
          <LanguageChoice name="pr-language" value={language} onChange={setLanguage} legend={P.language} />
          {needConsent && info && (
            <ConsentBox text={info.consent_text} checked={agreed} onChange={setAgreed} title={P.consentTitle} agree={P.consentAgree} />
          )}
          {error && <ErrorNotice doing={P.startFailed} error={error} />}
          <button type="button" className="btn btn-secondary btn-block" onClick={start} disabled={busy || (needConsent && !agreed)}>
            {busy ? <span className="spinner" aria-hidden /> : <Icon name="sparkle" />} {busy ? P.starting : P.start}
          </button>
        </div>
      )}
    </Card>
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
      <StandingGuarantors app={app} needed={needed} onUsed={onSubmitted} />
      <GuarantorForm rows={rows} setRows={setRows} needed={needed} cap={cap} busy={busy} onSubmit={submit} />
      {error && <ErrorNotice doing={F.failed} error={error} onRetry={submit} />}
    </section>
  )
}

/** The borrower's standing pledges from members who can cover their share, if any. */
function StandingGuarantors({ app, needed, onUsed }: { app: Mine; needed: number; onUsed: (a: Mine) => void }) {
  const S = t.sacco
  const load = useCallback(() => api.guarantorOffers(app.id), [app.id])
  const { data } = useLoad(load)
  const [chosen, setChosen] = useState<number[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  if (!data?.offers?.length) return null

  const toggle = (id: number) => setChosen((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id]))
  async function use() {
    setBusy(true)
    setError(null)
    try {
      onUsed(await api.usePledges(app.id, chosen))
    } catch (e) {
      setError(e as ApiError)
      setBusy(false)
    }
  }

  return (
    <fieldset className={styles.offers}>
      <legend className={styles.gLegend}>{S.offersTitle}</legend>
      <p className="muted small">{S.offersLead(data.share_kes)}</p>
      {data.offers.map((o) => (
        <label key={o.pledge_id} className="choice">
          <input type="checkbox" checked={chosen.includes(o.pledge_id)} disabled={busy || (!chosen.includes(o.pledge_id) && chosen.length >= needed)}
                 onChange={() => toggle(o.pledge_id)} />
          <span>{o.full_name} ({o.member_no})</span>
        </label>
      ))}
      {error && <ErrorNotice doing={S.useFailed} error={error} />}
      <button type="button" className="btn btn-primary" disabled={busy || chosen.length === 0} onClick={use}>
        {busy && <span className="spinner" aria-hidden />} {S.submitChosen(chosen.length || 1)}
      </button>
      <p className="subtle small">{S.orType}</p>
    </fieldset>
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
