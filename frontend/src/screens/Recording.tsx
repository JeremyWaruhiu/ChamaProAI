import { AnimatePresence, m } from 'motion/react'
import { useRef, useState, type ChangeEvent } from 'react'
import { ApiError, api } from '../api/client'
import type { InterviewState, Question, ResponseOut } from '../api/types'
import { StatusBadge, TypedBadge } from '../components/Badges'
import { Icon } from '../components/Icon'
import { ErrorNotice, Notice } from '../components/Notice'
import { ReplayButton } from '../components/ReplayButton'
import { Shell } from '../components/Shell'
import { SkeletonPage } from '../components/ui'
import { useHealth } from '../hooks/useHealth'
import { useInterview } from '../hooks/useInterview'
import { useQuestions } from '../hooks/useQuestions'
import { extensionFor, recordingSupported, useRecorder } from '../hooks/useRecorder'
import { domainLabel, topicsOf } from '../lib/domains'
import { applicantName, formatClock } from '../lib/format'
import { fade, fadeUp, useReducedMotion } from '../lib/motion'
import { describeSeconds, realTimeFactor, transcriptionSeconds } from '../lib/pace'
import { paths } from '../lib/router'
import { firstUnanswered } from '../lib/selectors'
import { t } from '../strings'
import styles from './Recording.module.css'

const R = t.runner
const MAX_BYTES = 25 * 1024 * 1024

export function Recording({ id, question }: { id: number; question: number | null }) {
  const iv = useInterview(id)
  const qs = useQuestions(iv.data?.question_set)
  const reduced = useReducedMotion()
  const name = applicantName(iv.data?.applicant.name)

  const loading = (!iv.data && !iv.error) || (!!iv.data && !qs.questions && !qs.error)
  const questions = qs.questions ?? []
  const resumeAt = firstUnanswered(questions, iv.data)
  const n = question ?? resumeAt ?? 1
  const q = questions.find((x) => x.order === n)
  const total = questions.length
  const topics = topicsOf(questions)
  const topic = q ? topics.findIndex((tp) => tp.key === q.topic) : -1

  return (
    <Shell title={iv.data ? R.titleFor(name) : R.title} interviewId={id} step="record"
           applicationId={iv.data?.application_id} practice={iv.data?.mode === 'practice'}
           aside={topic >= 0 && topics.length > 1 && topics.length < questions.length && R.topicOf(topic + 1, topics.length)}>
      {iv.error && <ErrorNotice doing={R.loadFailed} error={iv.error} onRetry={iv.refresh} />}
      {qs.error && <ErrorNotice doing={R.questionsFailed} error={qs.error} onRetry={qs.retry} />}
      {loading && <SkeletonPage what={R.title} />}

      {iv.data && q && (
        <div className={styles.layout}>
          <Progress interview={iv.data} questions={questions} current={n} />

          {question === null && resumeAt !== undefined && resumeAt > 1 && (
            <p className={styles.resumed} role="status"><Icon name="info" size={18} /> {R.resumed(resumeAt)}</p>
          )}

          <AnimatePresence mode="wait" initial={false}>
            <m.div key={n} className={styles.stage} {...fadeUp(reduced, 0, 10)}>
              <QuestionCard q={q} n={n} total={total} english={iv.data.language === 'en'} />
              {/* key: a new question starts with a fresh recorder and no stale messages */}
              <AnswerPanel key={n} interview={iv.data} q={q} onChange={iv.refresh} />
            </m.div>
          </AnimatePresence>

          <nav className={styles.nav} aria-label={R.questions}>
            {n > 1
              ? <a className="btn btn-secondary btn-large" href={paths.record(id, n - 1)}><Icon name="arrowLeft" /> {R.previous}</a>
              : <span />}
            {n < total
              ? <a className="btn btn-primary btn-large" href={paths.record(id, n + 1)}>{R.nextQuestion} <Icon name="arrowRight" /></a>
              : <a className="btn btn-primary btn-large" href={paths.review(id)}>{R.toReview} <Icon name="arrowRight" /></a>}
          </nav>
        </div>
      )}
      {iv.data && qs.questions && !q && (
        <Notice tone="warning" title={R.noQuestion(n)}
                action={<a className="btn btn-secondary" href={paths.record(id, 1)}>{R.goToFirst}</a>} />
      )}
    </Shell>
  )
}

/** Kikuyu with an English gloss where the Kikuyu exists; English alone otherwise. */
function QuestionCard({ q, n, total, english }: { q: Question; n: number; total: number; english: boolean }) {
  const kikuyu = english ? '' : q.text_kik.trim()
  return (
    <section className={`card ${styles.question}`} aria-labelledby="question-text">
      <p className={styles.questionMeta}>
        <span className={styles.questionNo}>{R.questionOf(n, total)}</span>
        <span className={styles.topic}>{domainLabel(q.topic)}</span>
      </p>
      {kikuyu ? (
        <>
          <h2 id="question-text" className={styles.primary} lang="ki">“{kikuyu}”</h2>
          <p className={styles.gloss} lang="en">{q.text_en}</p>
        </>
      ) : (
        <h2 id="question-text" className={styles.primary} lang="en">{q.text_en}</h2>
      )}
    </section>
  )
}

type Busy = null | 'uploading' | 'deleting' | 'saving'

function AnswerPanel({ interview, q, onChange }: { interview: InterviewState; q: Question; onChange: () => Promise<void> }) {
  const rec = useRecorder()
  const reduced = useReducedMotion()
  const [busy, setBusy] = useState<Busy>(null)
  const [waitingFor, setWaitingFor] = useState<number | null>(null)
  const [error, setError] = useState<{ doing: string; error: ApiError; retry?: () => void } | null>(null)
  const [typing, setTyping] = useState(false)
  const [typed, setTyped] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)

  const response = interview.responses.find((r) => r.sentence_no === q.order)
  const readOnly = interview.status === 'assessed'
  const lang = interview.language === 'en' ? 'en' : 'ki'

  async function upload(audio: Blob, filename: string) {
    if (audio.size > MAX_BYTES) {
      setError({ doing: R.tooLarge, error: new ApiError(413, R.tooLargeBody) })
      return
    }
    setBusy('uploading')
    setError(null)
    try {
      await api.uploadResponse(interview.id, q.order, audio, filename)
      await onChange()
    } catch (e) {
      setError({ doing: R.notSaved, error: e as ApiError, retry: () => upload(audio, filename) })
    } finally {
      setBusy(null)
    }
  }

  async function stopAndSave() {
    const blob = await rec.stop()
    if (!blob) {
      setError({ doing: R.nothingRecorded, error: new ApiError(0, R.nothingRecordedBody) })
      return
    }
    await upload(blob, `answer-${q.order}.${extensionFor(blob.type)}`)
  }

  async function saveTyped() {
    setBusy('saving')
    setError(null)
    try {
      await api.typeResponse(interview.id, q.order, typed)
      await onChange()
      setTyping(false)
      setTyped('')
    } catch (e) {
      setError({ doing: R.typedNotSaved, error: e as ApiError, retry: saveTyped })
    } finally {
      setBusy(null)
    }
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
      setError({ doing: R.removeFailed, error: e as ApiError, retry: () => reRecord(r) })
    } finally {
      setBusy(null)
      setWaitingFor(null)
    }
  }

  const idleActions = (
    <div className={styles.secondary}>
      <button type="button" className="btn btn-secondary" onClick={() => setTyping(true)}
              disabled={busy !== null || rec.state !== 'idle'}>
        <Icon name="keyboard" /> {R.type}
      </button>
      <input ref={fileInput} type="file" accept="audio/*" className="visually-hidden"
             onChange={chooseFile} tabIndex={-1} aria-hidden />
      <button type="button" className="btn btn-quiet" onClick={() => fileInput.current?.click()}
              disabled={busy !== null || rec.state !== 'idle'}>
        <Icon name="upload" /> {R.upload}
      </button>
    </div>
  )

  let body
  let key: string
  if (busy === 'uploading') {
    key = 'uploading'
    body = <p className={styles.line}><span className="spinner" aria-hidden /> {R.saving}</p>
  } else if (typing && !response && !readOnly) {
    key = 'typing'
    body = (
      <div className={styles.typed}>
        <label className="field-label" htmlFor={`typed${q.order}`}>{R.typeLabel(interview.language !== 'en')}</label>
        <textarea id={`typed${q.order}`} className="textarea" lang={lang} rows={4} maxLength={5000}
                  value={typed} disabled={busy === 'saving'} autoFocus
                  onChange={(e) => setTyped(e.target.value)} />
        <div className={styles.actions}>
          <button className="btn btn-primary btn-large" onClick={saveTyped} disabled={busy === 'saving' || !typed.trim()}>
            {busy === 'saving' && <span className="spinner" aria-hidden />} {R.saveTyped}
          </button>
          <button className="btn btn-quiet" onClick={() => setTyping(false)} disabled={busy === 'saving'}>{t.common.cancel}</button>
        </div>
      </div>
    )
  } else if (busy === 'deleting') {
    key = 'deleting'
    body = <p className={styles.line}><span className="spinner" aria-hidden /> {waitingFor ? R.waitingRemove : R.removing}</p>
  } else if (rec.state === 'recording') {
    key = 'recording'
    body = (
      <div className={styles.recorder}>
        <button type="button" className={`${styles.recButton} ${styles.recLive}`} onClick={stopAndSave}
                aria-label={R.stopAndSave}>
          <Icon name="stop" size={34} />
        </button>
        <p className={styles.live} aria-live="polite">
          <span className={styles.dot} aria-hidden /> {R.recording} <span className={`${styles.clock} num`}>{formatClock(rec.elapsed)}</span>
        </p>
        <LevelMeter level={rec.level} />
        <div className={styles.actions}>
          <button className="btn btn-primary" onClick={stopAndSave}><Icon name="stop" /> {R.stopAndSave}</button>
          <button className="btn btn-quiet" onClick={rec.cancel}>{t.common.cancel}</button>
        </div>
      </div>
    )
  } else if (response) {
    key = `response-${response.id}-${response.status}`
    body = <ResponseStatus interview={interview} response={response} readOnly={readOnly} lang={lang} onReRecord={reRecord} />
  } else if (readOnly) {
    key = 'none'
    body = <p className="muted">{R.noAnswer}</p>
  } else {
    key = 'idle'
    body = (
      <div className={styles.recorder}>
        <p className={styles.instructions}>{R.askThen}</p>
        {recordingSupported() ? (
          <>
            <button type="button" className={styles.recButton} onClick={rec.start} disabled={rec.state === 'starting'}
                    aria-describedby="rec-hint">
              {rec.state === 'starting' ? <span className="spinner" aria-hidden /> : <Icon name="mic" size={36} />}
              <span className="visually-hidden">{R.record}</span>
            </button>
            <p className={styles.recLabel}>{rec.state === 'starting' ? R.starting : R.record}</p>
            <p id="rec-hint" className="subtle small">{R.recordHint}</p>
          </>
        ) : (
          <p className="muted">{R.noMic}</p>
        )}
        {idleActions}
      </div>
    )
  }

  return (
    <section className={`card ${styles.answer}`} aria-label={R.answer}>
      <AnimatePresence mode="wait" initial={false}>
        <m.div key={key} {...fade(reduced)}>{body}</m.div>
      </AnimatePresence>
      {rec.error && <Notice tone="warning">{rec.error}</Notice>}
      {error && <ErrorNotice doing={error.doing} error={error.error} onRetry={error.retry} />}
    </section>
  )
}

/** Twenty segments that light up with the microphone's level. */
export function LevelMeter({ level, segments = 20 }: { level: number; segments?: number }) {
  const lit = Math.round(Math.max(0, Math.min(1, level)) * segments)
  return (
    <div className={styles.meter} role="meter" aria-label={R.level} aria-valuemin={0} aria-valuemax={100}
         aria-valuenow={Math.round(level * 100)}>
      {Array.from({ length: segments }, (_, i) => (
        <span key={i} className={i < lit ? (i >= segments * 0.85 ? styles.segHot : styles.segOn) : undefined} />
      ))}
    </div>
  )
}

function ResponseStatus({ interview, response: r, readOnly, lang, onReRecord }: {
  interview: InterviewState; response: ResponseOut; readOnly: boolean; lang: string; onReRecord: (r: ResponseOut) => void
}) {
  const rtf = realTimeFactor(useHealth(), interview.language)
  let message
  if (r.source === 'typed') {
    message = (
      <p>{R.typed} <span className={styles.heard} lang={lang}>“{r.transcript}”</span>
        {!readOnly && <span className="muted">{R.canCorrect}</span>}</p>
    )
  } else if (r.status === 'queued') {
    const ahead = interview.responses.filter((x) => x.id < r.id && (x.status === 'queued' || x.status === 'transcribing'))
    const eta = rtf === null ? null : transcriptionSeconds(rtf, [...ahead, r].map((x) => x.duration_s))
    message = <p>{R.queued(ahead.length)}{eta !== null && R.usuallyReady(describeSeconds(eta))}{R.carryOn}</p>
  } else if (r.status === 'transcribing') {
    message = (
      <p>{R.transcribing}
        {rtf !== null && R.usuallyTakes(describeSeconds(transcriptionSeconds(rtf, [r.duration_s])))}
        {R.carryOn}</p>
    )
  } else if (r.status === 'transcribed') {
    message = r.transcript?.trim()
      ? <p>{R.heard} <span className={styles.heard} lang={lang}>“{r.transcript}”</span>{!readOnly && <span className="muted">{R.canCorrect}</span>}</p>
      : <p className="muted">{R.noWords}</p>
  } else {
    message = <p>{R.failed}</p>
  }

  return (
    <div className={styles.status}>
      <div className={styles.statusHead}>
        {r.source === 'typed' ? <TypedBadge /> : <StatusBadge status={r.status} />}
        {(r.status === 'queued' || r.status === 'transcribing') && <span className={styles.calmBar} aria-hidden />}
      </div>
      <div className={styles.message}>{message}</div>
      <div className={styles.actions}>
        {r.source === 'audio' && <ReplayButton responseId={r.id} />}
        {!readOnly && (
          <button className="btn btn-secondary" onClick={() => onReRecord(r)}>
            {r.source === 'typed' ? R.removeTyped : R.reRecord}
          </button>
        )}
      </div>
    </div>
  )
}

function Progress({ interview, questions, current }: { interview: InterviewState; questions: Question[]; current: number }) {
  const byNo = new Map(interview.responses.map((r) => [r.sentence_no, r]))
  const topics = topicsOf(questions)
  const currentTopic = questions.find((q) => q.order === current)?.topic
  const recorded = interview.responses.length
  const waiting = interview.counts.queued + interview.counts.transcribing
  // v1 groups 40 questions into 8 domains; v2 asks one question per topic, so
  // the chips are the questions themselves.
  const grouped = topics.length < questions.length
  const chips = grouped ? questions.filter((q) => q.topic === currentTopic) : questions
  const index = questions.findIndex((q) => q.order === current)

  return (
    <section className={styles.progress} aria-label={R.progressLabel(recorded, questions.length)}>
      <div className={styles.progressHead}>
        <p className={styles.progressTitle}>{R.questionOf(index + 1, questions.length)}</p>
        <p className="subtle small">{R.progressLabel(recorded, questions.length)}{waiting > 0 && R.beingTranscribed(waiting)}</p>
      </div>
      <div className={styles.bar} aria-hidden>
        <span className={styles.barDone} style={{ width: `${(100 * recorded) / questions.length}%` }} />
        <span className={styles.barHere} style={{ left: `${(100 * index) / questions.length}%`, width: `${100 / questions.length}%` }} />
      </div>
      {grouped && (
        <ol className={styles.segments} aria-label={R.domains(topics.length)}>
          {topics.map((d) => {
            const dq = questions.filter((q) => q.topic === d.key)
            const done = dq.filter((q) => byNo.has(q.order)).length
            const target = dq.find((q) => !byNo.has(q.order)) ?? dq[0]
            return (
              <li key={d.key}>
                <a href={target ? paths.record(interview.id, target.order) : undefined}
                   className={styles.segment} aria-current={d.key === currentTopic ? 'true' : undefined}
                   title={R.segment(d.label, done, dq.length)}>
                  <span className={styles.track}><span style={{ width: `${dq.length ? (100 * done) / dq.length : 0}%` }} /></span>
                  <span className={styles.segLabel}>{d.label}</span>
                </a>
              </li>
            )
          })}
        </ol>
      )}
      <ol className={styles.chips} aria-label={grouped ? R.questionsIn(domainLabel(currentTopic)) : R.questions}>
        {chips.map((q) => {
          const r = byNo.get(q.order)
          const state = r ? (r.status === 'failed' ? 'failed' : r.status === 'transcribed' ? 'done' : 'waiting') : 'none'
          const said = r ? (r.source === 'typed' ? t.status.typed : t.status[r.status]) : R.notAnswered
          return (
            <li key={q.order}>
              <a href={paths.record(interview.id, q.order)} className={`${styles.chip} ${styles[state]}`}
                 aria-current={q.order === current ? 'step' : undefined}
                 title={`${domainLabel(q.topic)} · ${said}`}
                 aria-label={R.pillLabel(q.order, domainLabel(q.topic), said.toLowerCase())}>
                <span className={styles.chipNo}>{q.order}</span>
                <span className={styles.chipIcon} aria-hidden>
                  {state === 'done' && <Icon name="check" size={12} />}
                  {state === 'failed' && <Icon name="alert" size={12} />}
                  {state === 'waiting' && <span className={styles.chipPulse} />}
                </span>
              </a>
            </li>
          )
        })}
      </ol>
    </section>
  )
}
