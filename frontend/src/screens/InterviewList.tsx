import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { ApiError, api } from '../api/client'
import type { InterviewSummary } from '../api/types'
import { RiskBadge } from '../components/Badges'
import { ErrorNotice, Loading } from '../components/Notice'
import { Shell } from '../components/Shell'
import { applicantName, formatDate } from '../lib/format'
import { useAuth } from '../lib/auth'
import { DECISION_LABEL } from '../lib/risk'
import { navigate, paths } from '../lib/router'
import styles from './InterviewList.module.css'

function statusText(iv: InterviewSummary): string {
  if (iv.status === 'assessed') {
    return iv.decision ? `Decision: ${DECISION_LABEL[iv.decision]}` : 'Assessed, awaiting decision'
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
          <p className="muted">Start one with <strong>New interview</strong>. Each interview asks the applicant 40 short questions.</p>
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
                  <span className={styles.ref}>Interview {iv.id}</span>
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
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => { input.current?.focus() }, [])

  async function submit(e?: FormEvent) {
    e?.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const iv = await api.createInterview(name)
      navigate(paths.record(iv.id, 1))
    } catch (err) {
      setError(err as ApiError)
      setBusy(false)
    }
  }

  return (
    <form className={`card ${styles.newForm}`} onSubmit={submit}>
      <h3 className={styles.newTitle}>Start a new interview</h3>
      <label className="field-label" htmlFor="applicant">Applicant's name</label>
      <input id="applicant" ref={input} className="input" value={name} maxLength={200}
             autoComplete="off" placeholder="For example, Wanjiru Njeri"
             onChange={(e) => setName(e.target.value)} />
      <p className={`muted ${styles.hint}`}>You can leave this blank and add it later.</p>
      {error && <ErrorNotice doing="Could not start the interview" error={error} onRetry={() => submit()} />}
      <div className={styles.newActions}>
        <button type="button" className="btn btn-quiet" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy && <span className="spinner" aria-hidden />} Start interview
        </button>
      </div>
    </form>
  )
}
