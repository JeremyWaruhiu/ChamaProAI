import { useRef, useState, type ChangeEvent } from 'react'
import { ApiError, api } from '../api/client'
import type { InterviewState, Question, ResponseOut } from '../api/types'
import { StatusBadge } from '../components/Badges'
import { ErrorNotice, Loading, Notice } from '../components/Notice'
import { ReplayButton } from '../components/ReplayButton'
import { Shell } from '../components/Shell'
import { useInterview } from '../hooks/useInterview'
import { useQuestions } from '../hooks/useQuestions'
import { extensionFor, recordingSupported, useRecorder } from '../hooks/useRecorder'
import { DOMAINS, domainIndex, domainLabel } from '../lib/domains'
import { applicantName, formatClock } from '../lib/format'
import { paths } from '../lib/router'
import styles from './Recording.module.css'

const MAX_BYTES = 25 * 1024 * 1024
const SECONDS_PER_CLIP = 35

export function Recording({ id, question }: { id: number; question: number | null }) {
  const iv = useInterview(id)
  const qs = useQuestions()
  const name = applicantName(iv.data?.applicant.name)

  const loading = (!iv.data && !iv.error) || (!qs.questions && !qs.error)
  const questions = qs.questions ?? []
  const n = question ?? firstUnanswered(questions, iv.data) ?? 1
  const q = questions.find((x) => x.sentence_no === n)
  const total = questions.length
  const domain = q ? domainIndex(q.domain) : -1

  return (
    <Shell title={iv.data ? <>Interview — <strong>{name}</strong></> : 'Interview'} interviewId={id} step="record"
           aside={domain >= 0 && `Domain ${domain + 1} of ${DOMAINS.length}`}>
      {iv.error && <ErrorNotice doing="Could not load this interview" error={iv.error} onRetry={iv.refresh} />}
      {qs.error && <ErrorNotice doing="Could not load the interview questions" error={qs.error} onRetry={qs.retry} />}
      {loading && <Loading what="the interview" />}

      {iv.data && q && (
        <div className={styles.layout}>
          <p className="eyebrow">Question {n} of {total} — {domainLabel(q.domain)}</p>
          <QuestionCard q={q} />

          {/* key: a new question starts with a fresh recorder and no stale messages */}
          <AnswerPanel key={n} interview={iv.data} q={q} onChange={iv.refresh} />

          <Progress interview={iv.data} questions={questions} current={n} />

          <nav className={styles.nav} aria-label="Questions">
            {n > 1 ? <a className="btn btn-secondary" href={paths.record(id, n - 1)}>‹ Previous</a> : <span />}
            {n < total
              ? <a className="btn btn-primary btn-large" href={paths.record(id, n + 1)}>Next question ›</a>
              : <a className="btn btn-primary btn-large" href={paths.review(id)}>Review transcripts ›</a>}
          </nav>
        </div>
      )}
      {iv.data && qs.questions && !q && (
        <Notice tone="warning" title={`There is no question ${n}`}
                action={<a className="btn btn-secondary" href={paths.record(id, 1)}>Go to question 1</a>} />
      )}
    </Shell>
  )
}

function firstUnanswered(questions: Question[], iv: InterviewState | null): number | undefined {
  if (!iv) return undefined
  const done = new Set(iv.responses.map((r) => r.sentence_no))
  return questions.find((q) => !done.has(q.sentence_no))?.sentence_no
}

function QuestionCard({ q }: { q: Question }) {
  const kikuyu = q.kikuyu.trim()
  return (
    <div className={`card ${styles.question}`}>
      {kikuyu ? (
        <>
          <p className={styles.primary} lang="ki">“{kikuyu}”</p>
          <p className={styles.gloss} lang="en">{q.english}</p>
        </>
      ) : (
        <p className={styles.primary} lang="en">{q.english}</p>
      )}
    </div>
  )
}

type Busy = null | 'uploading' | 'deleting'

function AnswerPanel({ interview, q, onChange }: { interview: InterviewState; q: Question; onChange: () => Promise<void> }) {
  const rec = useRecorder()
  const [busy, setBusy] = useState<Busy>(null)
  const [waitingFor, setWaitingFor] = useState<number | null>(null)
  const [error, setError] = useState<{ doing: string; error: ApiError } | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const response = interview.responses.find((r) => r.sentence_no === q.sentence_no)
  const readOnly = interview.status === 'assessed'

  async function upload(audio: Blob, filename: string) {
    if (audio.size > MAX_BYTES) {
      setError({ doing: 'This recording is too large', error: new ApiError(413, 'Recordings must be under 25 MB. Record a shorter answer.') })
      return
    }
    setBusy('uploading')
    setError(null)
    try {
      await api.uploadResponse(interview.id, q.sentence_no, audio, filename)
      await onChange()
    } catch (e) {
      setError({ doing: 'The recording was not saved', error: e as ApiError })
    } finally {
      setBusy(null)
    }
  }

  async function stopAndSave() {
    const blob = await rec.stop()
    if (!blob) {
      setError({ doing: 'Nothing was recorded', error: new ApiError(0, 'The microphone produced no sound. Try again.') })
      return
    }
    await upload(blob, `answer-${q.sentence_no}.${extensionFor(blob.type)}`)
  }

  function chooseFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (file) upload(file, file.name)
  }

  async function reRecord(r: ResponseOut) {
    setBusy('deleting')
    setError(null)
    try {
      await api.deleteResponse(r.id, (s) => setWaitingFor(s))
      await onChange()
    } catch (e) {
      setError({ doing: 'Could not remove the old recording', error: e as ApiError })
    } finally {
      setBusy(null)
      setWaitingFor(null)
    }
  }

  const uploadControl = (
    <>
      <input ref={fileInput} type="file" accept="audio/*" className="visually-hidden"
             onChange={chooseFile} tabIndex={-1} aria-hidden />
      <button type="button" className="btn btn-secondary" onClick={() => fileInput.current?.click()}
              disabled={busy !== null || rec.state !== 'idle'}>
        Upload a recording
      </button>
    </>
  )

  let body
  if (busy === 'uploading') {
    body = <p className={styles.line}><span className="spinner" aria-hidden /> Saving the recording…</p>
  } else if (busy === 'deleting') {
    body = (
      <p className={styles.line}>
        <span className="spinner" aria-hidden />
        {waitingFor
          ? 'This answer is being transcribed right now. The old recording will be removed as soon as that finishes, usually within a minute.'
          : 'Removing the old recording…'}
      </p>
    )
  } else if (rec.state === 'recording') {
    body = (
      <div className={styles.recording}>
        <p className={styles.live} aria-live="polite">
          <span className={styles.dot} aria-hidden /> Recording <span className={styles.clock}>{formatClock(rec.elapsed)}</span>
        </p>
        <div className={styles.actions}>
          <button className="btn btn-primary btn-large" onClick={stopAndSave}>■ Stop and save</button>
          <button className="btn btn-quiet" onClick={rec.cancel}>Cancel</button>
        </div>
      </div>
    )
  } else if (response) {
    body = <ResponseStatus interview={interview} response={response} readOnly={readOnly} onReRecord={reRecord} />
  } else if (readOnly) {
    body = <p className="muted">No answer was recorded for this question.</p>
  } else {
    body = (
      <div className={styles.empty}>
        <p className="muted">Ask the question, then press <strong>Record answer</strong> while the applicant replies.</p>
        <div className={styles.actions}>
          {recordingSupported() && (
            <button className="btn btn-primary btn-large" onClick={rec.start} disabled={rec.state === 'starting'}>
              {rec.state === 'starting' ? <span className="spinner" aria-hidden /> : <span className={styles.recIcon} aria-hidden />}
              Record answer
            </button>
          )}
          {uploadControl}
        </div>
        {!recordingSupported() && (
          <p className="muted">This browser cannot record from the microphone. Upload a recording instead.</p>
        )}
      </div>
    )
  }

  return (
    <section className={`card ${styles.answer}`} aria-label="Answer">
      {body}
      {rec.error && <Notice tone="warning">{rec.error}</Notice>}
      {error && <ErrorNotice doing={error.doing} error={error.error} />}
    </section>
  )
}

function ResponseStatus({ interview, response: r, readOnly, onReRecord }: {
  interview: InterviewState; response: ResponseOut; readOnly: boolean; onReRecord: (r: ResponseOut) => void
}) {
  let message
  if (r.status === 'queued') {
    const ahead = interview.responses.filter((x) => x.id < r.id && (x.status === 'queued' || x.status === 'transcribing')).length
    const minutes = Math.max(1, Math.round(((ahead + 1) * SECONDS_PER_CLIP) / 60))
    message = (
      <p>Waiting its turn to be transcribed{ahead > 0 && <> — {ahead} {ahead === 1 ? 'answer' : 'answers'} ahead</>}.
        {' '}Ready in about {minutes} {minutes === 1 ? 'minute' : 'minutes'}. You can carry on with the next question.</p>
    )
  } else if (r.status === 'transcribing') {
    message = <p>Being transcribed now. This usually takes about {SECONDS_PER_CLIP} seconds. You can carry on with the next question.</p>
  } else if (r.status === 'transcribed') {
    message = r.transcript?.trim()
      ? <p>Heard: <span className={styles.heard} lang="ki">“{r.transcript}”</span>{!readOnly && <span className="muted"> You can correct this on the review screen.</span>}</p>
      : <p className="muted">No words were recognised in this recording. Listen to it, then record again or type the answer on the review screen.</p>
  } else {
    message = <p>This answer could not be transcribed. Record it again, or type what the applicant said on the review screen.</p>
  }

  return (
    <div className={styles.status}>
      <div className={styles.statusHead}>
        <StatusBadge status={r.status} />
        {(r.status === 'queued' || r.status === 'transcribing') && <span className={styles.calmBar} aria-hidden />}
      </div>
      <div className={styles.message}>{message}</div>
      <div className={styles.actions}>
        <ReplayButton responseId={r.id} />
        {!readOnly && <button className="btn btn-secondary" onClick={() => onReRecord(r)}>Re-record</button>}
      </div>
    </div>
  )
}

function Progress({ interview, questions, current }: { interview: InterviewState; questions: Question[]; current: number }) {
  const byNo = new Map(interview.responses.map((r) => [r.sentence_no, r]))
  const currentDomain = questions.find((q) => q.sentence_no === current)?.domain
  const recorded = interview.responses.length
  const waiting = interview.counts.queued + interview.counts.transcribing
  const inDomain = questions.filter((q) => q.domain === currentDomain)

  return (
    <section className={styles.progress} aria-label="Progress">
      <p className="eyebrow">Progress through the eight interview domains</p>
      <ol className={styles.segments}>
        {DOMAINS.map((d) => {
          const dq = questions.filter((q) => q.domain === d.key)
          const done = dq.filter((q) => byNo.has(q.sentence_no)).length
          const target = dq.find((q) => !byNo.has(q.sentence_no)) ?? dq[0]
          return (
            <li key={d.key}>
              <a href={target ? paths.record(interview.id, target.sentence_no) : undefined}
                 className={styles.segment} aria-current={d.key === currentDomain ? 'true' : undefined}
                 title={`${d.label}: ${done} of ${dq.length} recorded`}>
                <span className={styles.track}><span style={{ width: `${dq.length ? (100 * done) / dq.length : 0}%` }} /></span>
                <span className={styles.segLabel}>{d.label}</span>
              </a>
            </li>
          )
        })}
      </ol>
      <div className={styles.progressFoot}>
        <p><strong>{recorded} of {questions.length}</strong> answers recorded
          {waiting > 0 && <span className="muted"> · {waiting} being transcribed</span>}</p>
        <ol className={styles.pills} aria-label={`Questions in ${domainLabel(currentDomain)}`}>
          {inDomain.map((q) => {
            const r = byNo.get(q.sentence_no)
            const state = r ? (r.status === 'failed' ? 'failed' : r.status === 'transcribed' ? 'done' : 'waiting') : 'none'
            return (
              <li key={q.sentence_no}>
                <a href={paths.record(interview.id, q.sentence_no)} className={`${styles.pill} ${styles[state]}`}
                   aria-current={q.sentence_no === current ? 'true' : undefined}
                   aria-label={`Question ${q.sentence_no}${r ? `, ${r.status}` : ', not recorded'}`}>
                  {q.sentence_no}
                </a>
              </li>
            )
          })}
        </ol>
      </div>
    </section>
  )
}
