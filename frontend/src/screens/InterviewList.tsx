import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { ApiError, api } from '../api/client'
import type { ApplicantFormOptions, InterviewSummary, MaritalStatus } from '../api/types'
import { RiskBadge } from '../components/Badges'
import { ErrorNotice, Loading } from '../components/Notice'
import { Shell } from '../components/Shell'
import { EMPTY_DRAFT, missingFields, type Draft } from '../lib/applicant'
import { applicantName, formatDate } from '../lib/format'
import { useAuth } from '../lib/auth'
import { DECISION_LABEL } from '../lib/risk'
import { navigate, paths } from '../lib/router'
import styles from './InterviewList.module.css'

function statusText(iv: InterviewSummary): string {
  if (iv.status === 'assessed') {
    const label = iv.mode === 'practice' ? 'Practice decision' : 'Decision'
    return iv.decision ? `${label}: ${DECISION_LABEL[iv.decision]}` : 'Assessed, awaiting decision'
  }
  if (iv.counts.queued + iv.counts.transcribing > 0) return 'Transcribing answers'
  if (iv.responses_recorded === 0) return 'Not started'
  if (iv.responses_recorded < iv.questions_total) return 'Recording in progress'
  return 'Ready for review'
}

/** Where opening an interview should land: the next thing the officer has to do. */
function destination(iv: InterviewSummary): string {
  if (iv.status === 'assessed') return paths.assessment(iv.id)
  if (iv.responses_recorded >= iv.questions_total) return paths.review(iv.id)
  return paths.record(iv.id)
}

export function InterviewList() {
  const [items, setItems] = useState<InterviewSummary[] | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [creating, setCreating] = useState(false)
  const { user } = useAuth()

  const load = useCallback(async () => {
    try {
      setItems(await api.interviews())
      setError(null)
    } catch (e) {
      setError(e as ApiError)
    }
  }, [])

  // oxlint-disable-next-line react/set-state-in-effect -- fetch on mount; state is set after the await
  useEffect(() => { load() }, [load])

  return (
    <Shell title={<><strong>ChamaPro AI</strong> | Interviews</>}
           aside={<>SACCO credit assessment{user?.role === 'admin' && <> · <a href={paths.results()} className={styles.adminLink}>Model &amp; Evaluation</a></>}</>}>
      <div className={styles.top}>
        <div>
          <h2 className={styles.heading}>Loan interviews</h2>
          <p className="muted">Open an interview to continue it, or start a new one.</p>
        </div>
        {!creating && (
          <button className="btn btn-primary btn-large" onClick={() => setCreating(true)}>
            + New interview
          </button>
        )}
      </div>

      {creating && <NewInterview onCancel={() => setCreating(false)} />}

      {error && <ErrorNotice doing="Could not load the interviews" error={error} onRetry={load} />}
      {!items && !error && <Loading what="interviews" />}

      {items && items.length === 0 && (
        <div className={`card ${styles.empty}`}>
          <p className={styles.emptyTitle}>No interviews yet</p>
          <p className="muted">Start one with <strong>New interview</strong>. Each interview asks the applicant eight short questions.</p>
        </div>
      )}

      {items && items.length > 0 && (
        <section aria-labelledby="list-label">
          <p id="list-label" className={`eyebrow ${styles.label}`}>All interviews, newest first</p>
          <div className={styles.table} role="table" aria-label="Interviews">
            <div className={styles.head} role="row">
              <span role="columnheader">Applicant</span>
              <span role="columnheader">Date</span>
              <span role="columnheader">Answers</span>
              <span role="columnheader">Status</span>
              <span role="columnheader" className={styles.riskCol}>Risk class</span>
            </div>
            {items.map((iv) => (
              <a key={iv.id} href={destination(iv)} className={`${styles.row} card`} role="row">
                <span role="cell" className={styles.name}>
                  {applicantName(iv.applicant_name)}
                  <span className={styles.ref}>
                    Interview {iv.id}
                    {iv.language === 'en' && <span className={styles.tag}>English</span>}
                    {iv.mode === 'practice' && <span className={`${styles.tag} ${styles.practiceTag}`}>Practice</span>}
                  </span>
                </span>
                <span role="cell">{formatDate(iv.created_at)}</span>
                <span role="cell">
                  <span className={styles.count}>{iv.responses_recorded}</span>
                  <span className="muted"> of {iv.questions_total}</span>
                  <span className={styles.meter} aria-hidden>
                    <span style={{ width: `${(100 * iv.responses_recorded) / iv.questions_total}%` }} />
                  </span>
                </span>
                <span role="cell" className={styles.status}>{statusText(iv)}</span>
                <span role="cell" className={styles.riskCol}>
                  {iv.risk_class ? <RiskBadge risk={iv.risk_class} /> : <span className="muted">Not assessed</span>}
                </span>
              </a>
            ))}
          </div>
        </section>
      )}
    </Shell>
  )
}

function NewInterview({ onCancel }: { onCancel: () => void }) {
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT)
  const [options, setOptions] = useState<ApplicantFormOptions | null>(null)
  const [optionsError, setOptionsError] = useState<ApiError | null>(null)
  const [tried, setTried] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setDraft((d) => ({ ...d, [k]: v }))
  const missing = missingFields(draft)

  const loadOptions = useCallback(async () => {
    try {
      setOptions(await api.applicantForm())
      setOptionsError(null)
    } catch (e) {
      setOptionsError(e as ApiError)
    }
  }, [])

  useEffect(() => { input.current?.focus() }, [])
  // oxlint-disable-next-line react/set-state-in-effect -- fetch on mount; state is set after the await
  useEffect(() => { loadOptions() }, [loadOptions])

  async function submit(e?: FormEvent) {
    e?.preventDefault()
    setTried(true)
    if (missing.length > 0 || !draft.sex || !draft.marital) return
    setBusy(true)
    setError(null)
    try {
      const iv = await api.createInterview({
        applicant_name: draft.name,
        applicant: { age: Number(draft.age), sex: draft.sex, education: Number(draft.education),
                     marital_status: draft.marital },
        language: draft.language,
        mode: draft.practice ? 'practice' : 'live',
      })
      navigate(paths.record(iv.id, 1))
    } catch (err) {
      setError(err as ApiError)
      setBusy(false)
    }
  }

  return (
    <form className={`card ${styles.newForm}`} onSubmit={submit} noValidate>
      <h3 className={styles.newTitle}>Start a new interview</h3>
      <label className="field-label" htmlFor="applicant">Applicant's name</label>
      <input id="applicant" ref={input} className="input" value={draft.name} maxLength={200}
             autoComplete="off" placeholder="For example, Wanjiru Njeri"
             onChange={(e) => set('name', e.target.value)} />
      <p className={`muted ${styles.hint}`}>You can leave the name blank. The details below are needed: the interview does not ask for them.</p>

      {optionsError && <ErrorNotice doing="Could not load the applicant form" error={optionsError} onRetry={loadOptions} />}
      {!options && !optionsError && <Loading what="the applicant form" />}
      {options && (
        <div className={styles.formGrid}>
          <div>
            <label className="field-label" htmlFor="age">Age</label>
            <input id="age" className="input" inputMode="numeric" value={draft.age} maxLength={3}
                   autoComplete="off" onChange={(e) => set('age', e.target.value.replace(/\D/g, ''))} />
          </div>
          <fieldset className={styles.fieldset}>
            <legend className="field-label">Sex</legend>
            <div className={styles.choiceRow}>
              {options.sex.map((o) => (
                <label key={o.value} className={styles.choice}>
                  <input type="radio" name="sex" value={o.value} checked={draft.sex === o.value}
                         onChange={() => set('sex', o.value)} /> {o.label}
                </label>
              ))}
            </div>
          </fieldset>
          <div className={styles.wide}>
            <label className="field-label" htmlFor="education">Highest level of education</label>
            <select id="education" className="input" value={draft.education}
                    onChange={(e) => set('education', e.target.value)}>
              <option value="">Choose…</option>
              {options.education.map((o) => <option key={o.value} value={String(o.value)}>{o.label}</option>)}
            </select>
          </div>
          <div className={styles.wide}>
            <label className="field-label" htmlFor="marital">Marital status</label>
            <select id="marital" className="input" value={draft.marital}
                    onChange={(e) => set('marital', e.target.value as MaritalStatus | '')}>
              <option value="">Choose…</option>
              {options.marital_status.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>
          <fieldset className={`${styles.fieldset} ${styles.wide}`}>
            <legend className="field-label">Interview language</legend>
            <div className={styles.choiceRow}>
              {([['kik', 'Kikuyu'], ['en', 'English']] as const).map(([v, label]) => (
                <label key={v} className={styles.choice}>
                  <input type="radio" name="language" value={v} checked={draft.language === v}
                         onChange={() => set('language', v)} /> {label}
                </label>
              ))}
            </div>
          </fieldset>
          <label className={`${styles.choice} ${styles.wide}`}>
            <input type="checkbox" checked={draft.practice} onChange={(e) => set('practice', e.target.checked)} />
            {' '}Practice interview (training only: kept out of the live statistics)
          </label>
        </div>
      )}

      {tried && missing.length > 0 && (
        <p className={styles.missing} role="alert">Please fill in: {missing.join(', ')}.</p>
      )}
      {error && <ErrorNotice doing="Could not start the interview" error={error} onRetry={() => submit()} />}
      <div className={styles.newActions}>
        <button type="button" className="btn btn-quiet" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="submit" className="btn btn-primary" disabled={busy || !options}>
          {busy && <span className="spinner" aria-hidden />} Start interview
        </button>
      </div>
    </form>
  )
}
