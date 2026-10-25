import { useState } from 'react'
import { ApiError, api } from '../api/client'
import type { InterviewState, Question, ResponseOut } from '../api/types'
import { EditedBadge, StatusBadge, TypedBadge } from '../components/Badges'
import { ErrorNotice, Loading, Notice } from '../components/Notice'
import { ReplayButton } from '../components/ReplayButton'
import { Shell } from '../components/Shell'
import { pending, useInterview } from '../hooks/useInterview'
import { useQuestions } from '../hooks/useQuestions'
import { domainLabel } from '../lib/domains'
import { applicantName, formatDateTime } from '../lib/format'
import { navigate, paths } from '../lib/router'
import styles from './Review.module.css'

export function Review({ id }: { id: number }) {
  const iv = useInterview(id)
  const qs = useQuestions(iv.data?.question_set)
  const [drafts, setDrafts] = useState<Record<number, string>>({})
  const data = iv.data
  const name = applicantName(data?.applicant.name)

  const setDraft = (rid: number, text: string | undefined) =>
    setDrafts((d) => {
      const next = { ...d }
      if (text === undefined) delete next[rid]
      else next[rid] = text
      return next
    })

  const questionFor = (n: number) => qs.questions?.find((q) => q.order === n)

  return (
    <Shell title={data ? <>Transcript — <strong>{name}</strong></> : 'Transcript'} interviewId={id} step="review"
           practice={data?.mode === 'practice'}
           aside={data && `${data.counts.transcribed} of ${data.responses.length} transcribed`}>
      {iv.error && <ErrorNotice doing="Could not load this interview" error={iv.error} onRetry={iv.refresh} />}
      {qs.error && <ErrorNotice doing="Could not load the interview questions" error={qs.error} onRetry={qs.retry} />}
      {!data && !iv.error && <Loading what="the transcripts" />}

      {data && (
        <div className={styles.layout}>
          {data.status === 'assessed' ? (
            <Notice tone="info" title="This interview has been assessed"
                    action={<a className="btn btn-secondary" href={paths.assessment(id)}>View assessment</a>}>
              Transcripts are kept exactly as they were assessed and can no longer be changed.
            </Notice>
          ) : (
            <Notice tone="info">
              Listen to each recorded answer and correct any transcript that does not match what the applicant said, and check any typed answer, before you run the assessment.
            </Notice>
          )}

          <Summary interview={data} total={qs.questions?.length ?? data.responses.length} />

          {data.responses.length === 0 && (
            <div className={`card ${styles.empty}`}>
              <p>No answers have been recorded yet.</p>
              <a className="btn btn-primary" href={paths.record(id, 1)}>Start recording</a>
            </div>
          )}

          <ol className={styles.list}>
            {data.responses.map((r) => (
              <li key={r.id}>
                <ResponseCard response={r} question={questionFor(r.sentence_no)} english={data.language === 'en'}
                              readOnly={data.status === 'assessed'} draft={drafts[r.id]}
                              onDraft={(t) => setDraft(r.id, t)} onSaved={iv.refresh} />
              </li>
            ))}
          </ol>

          {data.status === 'open' && data.responses.length > 0 && (
            <RunAssessment interview={data} unsaved={Object.keys(drafts).length} />
          )}
        </div>
      )}
    </Shell>
  )
}

function Summary({ interview, total }: { interview: InterviewState; total: number }) {
  const waiting = interview.counts.queued + interview.counts.transcribing
  const missing = total - interview.responses.length
  return (
    <>
      {waiting > 0 && (
        <Notice tone="calm" title={`${waiting} ${waiting === 1 ? 'answer is' : 'answers are'} still being transcribed`}>
          This is expected: each answer takes about 35 seconds. You can review the others meanwhile; this page updates by itself.
        </Notice>
      )}
      {missing > 0 && interview.status === 'open' && (
        <p className={styles.missing}>
          {missing} of {total} questions have no recorded answer.{' '}
          <a href={paths.record(interview.id)}>Record the remaining answers</a>
        </p>
      )}
    </>
  )
}

function ResponseCard({ response: r, question, english, readOnly, draft, onDraft, onSaved }: {
  response: ResponseOut
  question: Question | undefined
  english: boolean
  readOnly: boolean
  draft: string | undefined
  onDraft: (text: string | undefined) => void
  onSaved: () => Promise<void>
}) {
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const editable = !readOnly && (r.status === 'transcribed' || r.status === 'failed')
  const value = draft ?? r.transcript ?? ''
  const dirty = draft !== undefined && draft !== (r.transcript ?? '')
  const lang = english ? 'en' : 'ki'
  const kind = r.source === 'typed' ? 'Typed answer' : english ? 'Transcript' : 'Kikuyu transcript'

  async function save() {
    setSaving(true)
    setError(null)
    try {
      await api.saveTranscript(r.id, value)
      await onSaved()
      onDraft(undefined)
      setSaved(true)
      window.setTimeout(() => setSaved(false), 2500)
    } catch (e) {
      setError(e as ApiError)
    } finally {
      setSaving(false)
    }
  }

  return (
    <article className={`card ${styles.card} ${dirty ? styles.dirty : ''}`} aria-labelledby={`q${r.id}`}>
      <header className={styles.cardHead}>
        <div>
          <p className={styles.qno}>Question {r.sentence_no} · {domainLabel(r.domain)}</p>
          <h2 id={`q${r.id}`} className={styles.qtext}>{question?.text_en ?? `Question ${r.sentence_no}`}</h2>
        </div>
        <div className={styles.badges}>
          {r.edited && <EditedBadge />}
          {r.source === 'typed' ? <TypedBadge /> : <StatusBadge status={r.status} />}
        </div>
      </header>

      {(r.status === 'queued' || r.status === 'transcribing') ? (
        <p className={styles.waiting}>
          {r.status === 'transcribing' ? 'Being transcribed now — about 35 seconds.' : 'Waiting its turn to be transcribed.'}
        </p>
      ) : editable ? (
        <>
          <label className="visually-hidden" htmlFor={`t${r.id}`}>{kind} for question {r.sentence_no}</label>
          <textarea id={`t${r.id}`} className={`textarea ${styles.transcript}`} lang={lang} value={value}
                    rows={2} spellCheck={false}
                    placeholder={r.status === 'failed' ? 'This answer was not transcribed. Listen, then type what the applicant said.' : 'No words were recognised. Listen, then type what the applicant said.'}
                    onChange={(e) => onDraft(e.target.value)} />
        </>
      ) : (
        <p className={styles.readonlyText} lang={lang}>{r.transcript?.trim() || <span className="muted">No transcript</span>}</p>
      )}

      {r.source === 'audio' && r.edited && r.transcript_asr !== r.transcript && (
        <p className={styles.original}>
          Corrected {r.edited_at && formatDateTime(r.edited_at)}. The speech model heard:{' '}
          <span lang={lang}>“{r.transcript_asr?.trim() || 'nothing'}”</span>
        </p>
      )}
      {r.source === 'typed' && <p className={styles.original}>Typed by the officer; there is no recording.</p>}

      <div className={styles.actions}>
        {r.source === 'audio' && <ReplayButton responseId={r.id} />}
        {editable && (
          <>
            <button className="btn btn-primary" onClick={save} disabled={!dirty || !value.trim() || saving}>
              {saving && <span className="spinner" aria-hidden />} Save correction
            </button>
            {dirty && <button className="btn btn-quiet" onClick={() => onDraft(undefined)} disabled={saving}>Undo changes</button>}
            {saved && <span className={styles.saved} role="status">✓ Saved</span>}
          </>
        )}
      </div>
      {error && <ErrorNotice doing="The correction was not saved" error={error} onRetry={save} />}
    </article>
  )
}

function RunAssessment({ interview, unsaved }: { interview: InterviewState; unsaved: number }) {
  const [confirming, setConfirming] = useState(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  const blocked = pending(interview)
    ? 'Wait until every answer has been transcribed.'
    : interview.counts.transcribed === 0
      ? 'There are no transcribed answers to assess yet.'
      : unsaved > 0
        ? `Save or undo your ${unsaved === 1 ? 'correction' : `${unsaved} corrections`} first.`
        : null

  async function run() {
    setRunning(true)
    setError(null)
    try {
      await api.assess(interview.id)
      navigate(paths.assessment(interview.id))
    } catch (e) {
      // A timed-out (or concurrent) assessment may still have been stored by the server.
      if (await assessedAnyway(interview.id)) {
        navigate(paths.assessment(interview.id))
        return
      }
      setError(e as ApiError)
      setRunning(false)
      setConfirming(false)
    }
  }

  return (
    <section className={`card ${styles.run}`} aria-label="Run assessment">
      {running ? (
        <p className={styles.runningText}>
          <span className="spinner" aria-hidden /> Assessing: {interview.language === 'en' ? '' : 'translating the answers, '}extracting the facts and scoring.
          This takes about half a minute.
        </p>
      ) : confirming ? (
        <>
          <p><strong>Run the assessment now?</strong> Afterwards the answers and transcripts are fixed and can no longer be changed.</p>
          <div className={styles.actions}>
            <button className="btn btn-quiet" onClick={() => setConfirming(false)}>Not yet</button>
            <button className="btn btn-primary btn-large" onClick={run}>Run assessment</button>
          </div>
        </>
      ) : (
        <>
          <div>
            <p><strong>When every transcript is right, run the assessment.</strong></p>
            <p className="muted">{blocked ?? `${interview.counts.transcribed} transcribed answers will be assessed.`}</p>
          </div>
          <button className="btn btn-primary btn-large" disabled={!!blocked} onClick={() => setConfirming(true)}>
            Run assessment
          </button>
        </>
      )}
      {error && <ErrorNotice doing="The assessment could not be run" error={error} onRetry={run} />}
    </section>
  )
}

async function assessedAnyway(interviewId: number): Promise<boolean> {
  try {
    return !!(await api.interview(interviewId)).assessment
  } catch {
    return false
  }
}
