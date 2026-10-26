import { m } from 'motion/react'
import { useState } from 'react'
import { ApiError, api } from '../api/client'
import type { InterviewState, Question, ResponseOut } from '../api/types'
import { EditedBadge, StatusBadge, TypedBadge } from '../components/Badges'
import { Icon } from '../components/Icon'
import { ErrorNotice, Notice } from '../components/Notice'
import { ReplayButton } from '../components/ReplayButton'
import { Shell } from '../components/Shell'
import { EmptyState, SkeletonPage } from '../components/ui'
import { useHealth } from '../hooks/useHealth'
import { pending, useInterview } from '../hooks/useInterview'
import { useQuestions } from '../hooks/useQuestions'
import { domainLabel } from '../lib/domains'
import { applicantName, formatDateTime } from '../lib/format'
import { fadeUp, stagger, useReducedMotion } from '../lib/motion'
import { describeSeconds, realTimeFactor, transcriptionSeconds } from '../lib/pace'
import { navigate, paths } from '../lib/router'
import { t } from '../strings'
import styles from './Review.module.css'

const V = t.review

export function Review({ id }: { id: number }) {
  const iv = useInterview(id)
  const qs = useQuestions(iv.data?.question_set)
  const [drafts, setDrafts] = useState<Record<number, string>>({})
  const health = useHealth()
  const reduced = useReducedMotion()
  const data = iv.data
  const rtf = data ? realTimeFactor(health, data.language) : null
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
    <Shell title={data ? V.titleFor(name) : V.title} interviewId={id} step="review"
           applicationId={data?.application_id} practice={data?.mode === 'practice'}
           aside={data && V.transcribedOf(data.counts.transcribed, data.responses.length)}>
      {iv.error && <ErrorNotice doing={V.loadFailed} error={iv.error} onRetry={iv.refresh} />}
      {qs.error && <ErrorNotice doing={t.runner.questionsFailed} error={qs.error} onRetry={qs.retry} />}
      {!data && !iv.error && <SkeletonPage what={V.title} />}

      {data && (
        <div className={styles.layout}>
          {data.status === 'assessed' ? (
            <Notice tone="info" title={V.assessed}
                    action={<a className="btn btn-secondary" href={paths.assessment(id)}>{V.viewAssessment}</a>}>
              {V.assessedBody}
            </Notice>
          ) : (
            <Notice tone="info">{V.intro}</Notice>
          )}

          <Summary interview={data} total={qs.questions?.length ?? data.responses.length} rtf={rtf} />

          {data.responses.length === 0 && (
            <div className="card">
              <EmptyState icon="mic" title={V.none}
                          action={<a className="btn btn-primary" href={paths.record(id, 1)}>{V.startRecording}</a>} />
            </div>
          )}

          <ol className={styles.list}>
            {data.responses.map((r, i) => (
              <m.li key={r.id} {...fadeUp(reduced, stagger(reduced, i))}>
                <ResponseCard response={r} question={questionFor(r.sentence_no)} english={data.language === 'en'} rtf={rtf}
                              readOnly={data.status === 'assessed'} draft={drafts[r.id]}
                              onDraft={(text) => setDraft(r.id, text)} onSaved={iv.refresh} />
              </m.li>
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

function Summary({ interview, total, rtf }: { interview: InterviewState; total: number; rtf: number | null }) {
  const waiting = interview.responses.filter((r) => r.status === 'queued' || r.status === 'transcribing')
  const missing = total - interview.responses.length
  const eta = rtf === null ? null : transcriptionSeconds(rtf, waiting.map((r) => r.duration_s))
  return (
    <>
      {waiting.length > 0 && (
        <Notice tone="calm" title={V.stillTranscribing(waiting.length)}>
          {V.expected}{eta !== null && V.readyIn(waiting.length, describeSeconds(eta))}.{V.meanwhile}
        </Notice>
      )}
      {missing > 0 && interview.status === 'open' && (
        <p className={styles.missing}>
          <Icon name="alert" size={18} /> {V.missing(missing, total)}{' '}
          <a href={paths.record(interview.id)}>{V.recordRemaining}</a>
        </p>
      )}
    </>
  )
}

function ResponseCard({ response: r, question, english, rtf, readOnly, draft, onDraft, onSaved }: {
  response: ResponseOut
  question: Question | undefined
  english: boolean
  rtf: number | null
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
  const kind = r.source === 'typed' ? V.typedAnswer : english ? V.transcript : V.kikuyuTranscript

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
        <span className={styles.qno} aria-hidden>{r.sentence_no}</span>
        <div className={styles.qtextWrap}>
          <p className={styles.qmeta}>{V.question(r.sentence_no, domainLabel(r.domain))}</p>
          <h2 id={`q${r.id}`} className={styles.qtext}>{question?.text_en ?? V.questionN(r.sentence_no)}</h2>
        </div>
        <div className={styles.badges}>
          {r.edited && <EditedBadge />}
          {r.source === 'typed' ? <TypedBadge /> : <StatusBadge status={r.status} />}
        </div>
      </header>

      {(r.status === 'queued' || r.status === 'transcribing') ? (
        <p className={styles.waiting}>
          {r.status === 'transcribing'
            ? V.transcribingNow(rtf === null ? null : describeSeconds(transcriptionSeconds(rtf, [r.duration_s])))
            : V.waitingTurn}
        </p>
      ) : editable ? (
        <>
          <label className="visually-hidden" htmlFor={`t${r.id}`}>{V.forQuestion(kind, r.sentence_no)}</label>
          <textarea id={`t${r.id}`} className={`textarea ${styles.transcript}`} lang={lang} value={value}
                    rows={2} spellCheck={false}
                    placeholder={r.status === 'failed' ? V.failedPlaceholder : V.emptyPlaceholder}
                    onChange={(e) => onDraft(e.target.value)} />
        </>
      ) : (
        <p className={styles.readonlyText} lang={lang}>{r.transcript?.trim() || <span className="muted">{V.noTranscript}</span>}</p>
      )}

      {r.source === 'audio' && r.edited && r.transcript_asr !== r.transcript && (
        <p className={styles.original}>
          {V.corrected(r.edited_at ? formatDateTime(r.edited_at) : '')}
          <span lang={lang}>“{r.transcript_asr?.trim() || V.nothing}”</span>
        </p>
      )}
      {r.source === 'typed' && <p className={styles.original}>{V.typedByOfficer}</p>}

      <div className={styles.actions}>
        {r.source === 'audio' && <ReplayButton responseId={r.id} />}
        {editable && (
          <>
            <button className="btn btn-primary" onClick={save} disabled={!dirty || !value.trim() || saving}>
              {saving && <span className="spinner" aria-hidden />} {V.saveCorrection}
            </button>
            {dirty && <button className="btn btn-quiet" onClick={() => onDraft(undefined)} disabled={saving}>{V.undo}</button>}
            {saved && <span className={styles.saved} role="status"><Icon name="check" size={16} /> {V.saved}</span>}
          </>
        )}
      </div>
      {error && <ErrorNotice doing={V.notSaved} error={error} onRetry={save} />}
    </article>
  )
}

function RunAssessment({ interview, unsaved }: { interview: InterviewState; unsaved: number }) {
  const [confirming, setConfirming] = useState(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  const blocked = pending(interview)
    ? V.blockedWait
    : interview.counts.transcribed === 0
      ? V.blockedNone
      : unsaved > 0
        ? V.blockedUnsaved(unsaved)
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
    <section className={`card ${styles.run}`} aria-label={V.run}>
      {running ? (
        <p className={styles.runningText}><span className="spinner" aria-hidden /> {V.running(interview.language === 'en')}</p>
      ) : confirming ? (
        <>
          <p><strong>{V.confirmRun}</strong> {V.confirmRunBody}</p>
          <div className={styles.actions}>
            <button className="btn btn-quiet" onClick={() => setConfirming(false)}>{V.notYet}</button>
            <button className="btn btn-primary btn-large" onClick={run}>{V.run}</button>
          </div>
        </>
      ) : (
        <>
          <div>
            <p><strong>{V.runTitle}</strong></p>
            <p className="muted">{blocked ?? V.willAssess(interview.counts.transcribed)}</p>
          </div>
          <button className="btn btn-primary btn-large" disabled={!!blocked} onClick={() => setConfirming(true)}>
            <Icon name="scale" /> {V.run}
          </button>
        </>
      )}
      {error && <ErrorNotice doing={V.runFailed} error={error} onRetry={run} />}
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
