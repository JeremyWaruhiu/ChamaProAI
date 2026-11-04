import { useCallback, useEffect, useRef, useState, type ChangeEvent } from 'react'
import { ApiError, api } from '../api/client'
import type { MyPractice, MyQuestion, MyResponse } from '../api/types'
import { EditedBadge, StatusBadge, TypedBadge } from '../components/Badges'
import { Icon } from '../components/Icon'
import { ErrorNotice, Notice } from '../components/Notice'
import { LevelMeter, MicUnavailable } from '../components/RecorderParts'
import { ReplayButton } from '../components/ReplayButton'
import { Card, PracticeBadge, SkeletonPage } from '../components/ui'
import { extensionFor, micUnavailable, useRecorder } from '../hooks/useRecorder'
import { practiceQuestion, submitBlocked, waiting } from '../lib/apply'
import { domainLabel } from '../lib/domains'
import { formatClock } from '../lib/format'
import { navigate, paths } from '../lib/router'
import { susComplete, susScore } from '../lib/sus'
import { t } from '../strings'
import memberStyles from './Member.module.css'
import styles from './Practice.module.css'
import recording from './Recording.module.css'

const P = t.practice
const R = t.runner
const S = t.sus
const MAX_BYTES = 25 * 1024 * 1024
const POLL_MS = 3000

/** Load a practice interview; keeps polling while an answer is being transcribed. */
function usePractice(id: number) {
  const [data, setData] = useState<MyPractice | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const seq = useRef(0)
  const refresh = useCallback(async () => {
    const mine = ++seq.current
    try {
      const next = await api.practice(id)
      if (mine === seq.current) { setData(next); setError(null) }
    } catch (e) {
      if (mine === seq.current) setError(e as ApiError)
    }
  }, [id])
  // oxlint-disable-next-line react/set-state-in-effect -- fetch on mount; state is set after the await
  useEffect(() => { refresh() }, [refresh])
  const polling = !!data?.responses.some(waiting)
  useEffect(() => {
    if (!polling) return
    const timer = setInterval(() => { if (!document.hidden) refresh() }, POLL_MS)
    return () => clearInterval(timer)
  }, [polling, refresh])
  return { data, error, refresh, setData }
}

/** Every screen of a practice interview says it is one. */
function Frame({ id, applicationId, step, children }: { id: number; applicationId?: number; step: string; children: React.ReactNode }) {
  return (
    <div className={styles.frame}>
      <a href={applicationId ? paths.myApplication(applicationId) : paths.my()} className={memberStyles.back}>
        <Icon name="arrowLeft" size={16} /> {P.backToApplication}
      </a>
      <header className={styles.head}>
        <h1 className={`display ${memberStyles.title}`}>{step}</h1>
        <PracticeBadge />
      </header>
      <p className={memberStyles.practice} role="note" data-practice-id={id}>
        <Icon name="sparkle" size={18} /> <span><strong>{P.banner}</strong> {P.bannerBody}</span>
      </p>
      {children}
    </div>
  )
}

// --- One question per screen ---------------------------------------------------------------

export function PracticeRunner({ id, question }: { id: number; question: number | null }) {
  const { data, error, refresh } = usePractice(id)
  if (error) return <Frame id={id} step={P.title}><ErrorNotice doing={P.loadFailed} error={error} onRetry={refresh} /></Frame>
  if (!data) return <Frame id={id} step={P.title}><SkeletonPage what={P.title} /></Frame>
  const qs = data.questions
  const firstOpen = qs.find((q) => !data.responses.some((r) => r.sentence_no === q.order))?.order ?? qs[0].order
  const n = question ?? firstOpen
  const q = qs.find((x) => x.order === n) ?? qs[0]
  const total = qs.length
  return (
    <Frame id={id} applicationId={data.application_id} step={P.title}>
      {data.status === 'assessed' && (
        <Notice action={<a className="btn btn-secondary" href={paths.practiceResult(id)}>{P.viewResult}</a>}>{P.done}</Notice>
      )}
      <QuestionView q={q} n={q.order} total={total} language={data.language} />
      <AnswerPanel key={q.order} practice={data} q={q} onChange={refresh} />
      <nav className={styles.nav} aria-label={R.questions}>
        {q.order > 1
          ? <a className="btn btn-secondary btn-large" href={paths.practice(id, q.order - 1)}><Icon name="arrowLeft" /> {P.previous}</a>
          : <span />}
        {q.order < total
          ? <a className="btn btn-primary btn-large" href={paths.practice(id, q.order + 1)}>{P.next} <Icon name="arrowRight" /></a>
          : <a className="btn btn-primary btn-large" href={paths.practiceReview(id)}>{P.toReview} <Icon name="arrowRight" /></a>}
      </nav>
    </Frame>
  )
}

export function QuestionView({ q, n, total, language }: { q: MyQuestion; n: number; total: number; language: MyPractice['language'] }) {
  const shown = practiceQuestion(q, language)
  return (
    <section className={`card ${recording.question}`} aria-labelledby="practice-question">
      <p className={recording.questionMeta}>
        <span className={styles.questionNo}>{P.questionOf(n, total)}</span>
        <span className={recording.topic}>{domainLabel(q.topic)}</span>
      </p>
      <h2 id="practice-question" className={recording.primary} lang={shown.lang}>{shown.text}</h2>
      {shown.gloss && <p className={recording.gloss} lang="en">{shown.gloss}</p>}
      {shown.kikuyuNote && <p className={styles.kikuyuNote}><Icon name="info" size={16} /> {P.kikuyuNote}</p>}
    </section>
  )
}

function AnswerPanel({ practice, q, onChange }: { practice: MyPractice; q: MyQuestion; onChange: () => Promise<void> }) {
  const rec = useRecorder()
  const blocked = micUnavailable()
  const [busy, setBusy] = useState<null | 'uploading' | 'saving' | 'deleting'>(null)
  const [error, setError] = useState<{ doing: string; error: ApiError; retry?: () => void } | null>(null)
  const [typing, setTyping] = useState(false)
  const [typed, setTyped] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const response = practice.responses.find((r) => r.sentence_no === q.order)
  const readOnly = practice.status === 'assessed'
  const lang = practice.language === 'en' ? 'en' : 'ki'

  async function upload(audio: Blob, filename: string) {
    if (audio.size > MAX_BYTES) {
      setError({ doing: R.tooLarge, error: new ApiError(413, R.tooLargeBody) })
      return
    }
    setBusy('uploading')
    setError(null)
    try {
      await api.uploadPractice(practice.id, q.order, audio, filename)
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
      await api.typePractice(practice.id, q.order, typed)
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

  async function remove(r: MyResponse) {
    setBusy('deleting')
    setError(null)
    try {
      await api.deletePracticeResponse(r.id)
      await onChange()
    } catch (e) {
      setError({ doing: R.removeFailed, error: e as ApiError, retry: () => remove(r) })
    } finally {
      setBusy(null)
    }
  }

  let body
  if (busy === 'uploading') {
    body = <p className={recording.line}><span className="spinner" aria-hidden /> {R.saving}</p>
  } else if (busy === 'deleting') {
    body = <p className={recording.line}><span className="spinner" aria-hidden /> {R.removing}</p>
  } else if (response) {
    body = (
      <div className={recording.status}>
        <div className={recording.statusHead}>
          {response.source === 'typed' ? <TypedBadge /> : <StatusBadge status={response.status} />}
          {waiting(response) && <span className={recording.calmBar} aria-hidden />}
        </div>
        <div className={recording.message}>
          {waiting(response) ? <p>{P.waiting}</p>
            : response.status === 'failed' ? <p>{P.failed}</p>
              : <p>{response.source === 'typed' ? R.typed : R.heard} <span className={recording.heard} lang={lang}>“{response.transcript}”</span></p>}
        </div>
        <div className={recording.actions}>
          {response.source === 'audio' && <ReplayButton responseId={response.id} url={api.practiceAudioUrl(response.id)} />}
          {!readOnly && (
            <button type="button" className="btn btn-secondary" onClick={() => remove(response)}>
              {response.source === 'typed' ? R.removeTyped : R.reRecord}
            </button>
          )}
        </div>
      </div>
    )
  } else if (readOnly) {
    body = <p className="muted">{R.noAnswer}</p>
  } else if (typing) {
    body = (
      <div className={recording.typed}>
        <label className="field-label" htmlFor={`typed${q.order}`}>{R.typeLabel(practice.language !== 'en')}</label>
        <textarea id={`typed${q.order}`} className="textarea" lang={lang} rows={4} maxLength={5000} value={typed}
                  disabled={busy === 'saving'} autoFocus onChange={(e) => setTyped(e.target.value)} />
        <div className={recording.actions}>
          <button type="button" className="btn btn-primary btn-large" onClick={saveTyped} disabled={busy === 'saving' || !typed.trim()}>
            {busy === 'saving' && <span className="spinner" aria-hidden />} {R.saveTyped}
          </button>
          <button type="button" className="btn btn-quiet" onClick={() => setTyping(false)} disabled={busy === 'saving'}>{t.common.cancel}</button>
        </div>
      </div>
    )
  } else if (rec.state === 'recording') {
    body = (
      <div className={recording.recorder}>
        <button type="button" className={`${recording.recButton} ${recording.recLive}`} onClick={stopAndSave} aria-label={R.stopAndSave}>
          <Icon name="stop" size={34} />
        </button>
        <p className={recording.live} aria-live="polite">
          <span className={recording.dot} aria-hidden /> {R.recording} <span className={`${recording.clock} num`}>{formatClock(rec.elapsed)}</span>
        </p>
        <LevelMeter level={rec.level} />
        <div className={recording.actions}>
          <button type="button" className="btn btn-primary" onClick={stopAndSave}><Icon name="stop" /> {R.stopAndSave}</button>
          <button type="button" className="btn btn-quiet" onClick={rec.cancel}>{t.common.cancel}</button>
        </div>
      </div>
    )
  } else {
    body = (
      <div className={recording.recorder}>
        {blocked ? <MicUnavailable reason={blocked} /> : (
          <>
            <button type="button" className={recording.recButton} onClick={rec.start} disabled={rec.state === 'starting'}>
              {rec.state === 'starting' ? <span className="spinner" aria-hidden /> : <Icon name="mic" size={36} />}
              <span className="visually-hidden">{R.record}</span>
            </button>
            <p className={recording.recLabel}>{rec.state === 'starting' ? R.starting : R.record}</p>
          </>
        )}
        <div className={recording.secondary}>
          <button type="button" className="btn btn-secondary" onClick={() => setTyping(true)}><Icon name="keyboard" /> {R.type}</button>
          <input ref={fileInput} type="file" accept="audio/*" className="visually-hidden" onChange={chooseFile} tabIndex={-1} aria-hidden />
          <button type="button" className="btn btn-quiet" onClick={() => fileInput.current?.click()}><Icon name="upload" /> {R.upload}</button>
        </div>
      </div>
    )
  }

  return (
    <section className={`card ${recording.answer}`} aria-label={R.answer}>
      {body}
      {rec.error && <Notice tone="warning">{rec.error}</Notice>}
      {error && <ErrorNotice doing={error.doing} error={error.error} onRetry={error.retry} />}
    </section>
  )
}

// --- Review and submit ------------------------------------------------------------------------

export function PracticeReview({ id }: { id: number }) {
  const { data, error, refresh, setData } = usePractice(id)
  const [drafts, setDrafts] = useState<Record<number, string>>({})
  if (error) return <Frame id={id} step={P.review}><ErrorNotice doing={P.loadFailed} error={error} onRetry={refresh} /></Frame>
  if (!data) return <Frame id={id} step={P.review}><SkeletonPage what={P.review} /></Frame>
  const setDraft = (rid: number, text: string | undefined) => setDrafts((d) => {
    const next = { ...d }
    if (text === undefined) delete next[rid]
    else next[rid] = text
    return next
  })
  return (
    <Frame id={id} applicationId={data.application_id} step={P.review}>
      {data.status === 'assessed'
        ? <Notice action={<a className="btn btn-secondary" href={paths.practiceResult(id)}>{P.viewResult}</a>}>{P.done}</Notice>
        : <p className="muted">{P.reviewLead}</p>}
      <ol className={styles.reviewList}>
        {data.questions.map((q) => (
          <ReviewRow key={q.order} practice={data} q={q} response={data.responses.find((r) => r.sentence_no === q.order)}
                     draft={drafts[data.responses.find((r) => r.sentence_no === q.order)?.id ?? -1]}
                     onDraft={setDraft} onSaved={refresh} />
        ))}
      </ol>
      {data.status === 'open' && (
        <SubmitPanel practice={data} unsaved={Object.keys(drafts).length} onDone={(next) => { setData(next); navigate(paths.practiceResult(id)) }} />
      )}
    </Frame>
  )
}

function ReviewRow({ practice, q, response: r, draft, onDraft, onSaved }: {
  practice: MyPractice; q: MyQuestion; response: MyResponse | undefined; draft: string | undefined
  onDraft: (rid: number, text: string | undefined) => void; onSaved: () => Promise<void>
}) {
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const shown = practiceQuestion(q, practice.language)
  const readOnly = practice.status === 'assessed'
  const value = r ? draft ?? r.transcript ?? '' : ''
  const dirty = !!r && draft !== undefined && draft !== (r.transcript ?? '')
  const lang = practice.language === 'en' ? 'en' : 'ki'

  async function save() {
    if (!r) return
    setSaving(true)
    setError(null)
    try {
      await api.savePracticeTranscript(r.id, value)
      await onSaved()
      onDraft(r.id, undefined)
      setSaved(true)
      window.setTimeout(() => setSaved(false), 2500)
    } catch (e) {
      setError(e as ApiError)
    } finally {
      setSaving(false)
    }
  }

  return (
    <li className={`card ${styles.reviewCard}`}>
      <p className={styles.questionNo}>{P.questionOf(q.order, practice.questions.length)}</p>
      <p className={styles.reviewQuestion} lang={shown.lang}>{shown.text}</p>
      {!r && (
        <p className={styles.missing}><Icon name="alert" size={16} /> {P.notAnswered}{' '}
          {!readOnly && <a href={paths.practice(practice.id, q.order)}>{P.answerThis}</a>}</p>
      )}
      {r && waiting(r) && <p className="muted">{P.waiting}</p>}
      {r && !waiting(r) && (readOnly
        ? <p className={styles.readonlyText} lang={lang}>{r.transcript}</p>
        : (
          <>
            <label className="visually-hidden" htmlFor={`pt${r.id}`}>{P.questionOf(q.order, practice.questions.length)}</label>
            <textarea id={`pt${r.id}`} className="textarea" lang={lang} rows={3} maxLength={5000} spellCheck={false} value={value}
                      placeholder={r.status === 'failed' ? P.failed : undefined}
                      onChange={(e) => onDraft(r.id, e.target.value)} />
          </>
        ))}
      {r && (
        <div className={styles.reviewActions}>
          {r.source === 'typed' ? <TypedBadge /> : <StatusBadge status={r.status} />}
          {r.edited && <EditedBadge />}
          {r.source === 'audio' && <ReplayButton responseId={r.id} url={api.practiceAudioUrl(r.id)} />}
          {!readOnly && !waiting(r) && (
            <>
              <button type="button" className="btn btn-primary" onClick={save} disabled={!dirty || !value.trim() || saving}>
                {saving && <span className="spinner" aria-hidden />} {P.save}
              </button>
              {dirty && <button type="button" className="btn btn-quiet" onClick={() => onDraft(r.id, undefined)}>{t.review.undo}</button>}
              {saved && <span className={styles.saved} role="status"><Icon name="check" size={16} /> {P.saved}</span>}
            </>
          )}
        </div>
      )}
      {error && <ErrorNotice doing={P.saveFailed} error={error} onRetry={save} />}
    </li>
  )
}

export function SubmitPanel({ practice, unsaved, onDone }: { practice: MyPractice; unsaved: number; onDone: (p: MyPractice) => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const { remaining_today: left, allowed_per_day: allowed, pilot_full_today: full } = practice.limits
  const capped = left === 0 ? P.capMember(allowed) : full ? P.capPilot : null
  const blocked = capped ?? submitBlocked(practice, unsaved)

  async function submit() {
    setBusy(true)
    setError(null)
    try {
      onDone(await api.submitPractice(practice.id))
    } catch (e) {
      // A timed-out assessment may still have been stored by the server.
      try {
        const latest = await api.practice(practice.id)
        if (latest.status === 'assessed') { onDone(latest); return }
      } catch { /* show the first error */ }
      setError(e as ApiError)
      setBusy(false)
    }
  }

  return (
    <section className={`card ${styles.submit}`} aria-label={P.submit}>
      {capped && <Notice tone="warning">{capped}</Notice>}
      {!capped && <p className="subtle small">{P.remaining(left, allowed)}</p>}
      {!capped && blocked && <p className="muted">{blocked}</p>}
      {busy
        ? <p className={styles.running}><span className="spinner" aria-hidden /> {P.submitting}</p>
        : (
          <button type="button" className="btn btn-primary btn-large btn-block" disabled={!!blocked} onClick={submit}>
            <Icon name="check" /> {P.submit}
          </button>
        )}
      {error && <ErrorNotice doing={P.submitFailed} error={error} />}
    </section>
  )
}

// --- The result, and the questionnaire ------------------------------------------------------------

export function PracticeResult({ id }: { id: number }) {
  const { data, error, refresh } = usePractice(id)
  if (error) return <Frame id={id} step={P.result}><ErrorNotice doing={P.loadFailed} error={error} onRetry={refresh} /></Frame>
  if (!data) return <Frame id={id} step={P.result}><SkeletonPage what={P.result} /></Frame>
  return (
    <Frame id={id} applicationId={data.application_id} step={P.result}>
      {!data.result ? (
        <Notice action={<a className="btn btn-secondary" href={paths.practiceReview(id)}>{P.toReviewAction}</a>}>{P.notSubmitted}</Notice>
      ) : (
        <ResultView result={data.result} />
      )}
      {data.result && !data.sus_answered && <SusForm id={id} />}
    </Frame>
  )
}

/** Words only. Nothing here reads a class, a score or a probability, because the API sends none. */
export function ResultView({ result }: { result: NonNullable<MyPractice['result']> }) {
  return (
    <>
      <Card title={P.result}>
        <div className={memberStyles.message}><p>{result.message}</p></div>
      </Card>
      {result.reasons.length > 0 && (
        <Card title={P.reasons} delay={0.05}>
          <ul className={memberStyles.reasons}>{result.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        </Card>
      )}
    </>
  )
}

export function SusForm({ id }: { id: number }) {
  const [answers, setAnswers] = useState<(number | null)[]>(() => S.statements.map(() => null))
  const [comment, setComment] = useState('')
  const [tried, setTried] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const [done, setDone] = useState<null | { skipped: true } | { score: number }>(null)

  if (done) {
    return (
      <div className={memberStyles.done} role="status">
        <span className={memberStyles.doneIcon}><Icon name="check" size={26} /></span>
        <div>
          <p className={memberStyles.doneTitle}>{'score' in done ? S.thanks : S.skipped}</p>
          {'score' in done && <p className="muted">{S.yourScore(done.score)}</p>}
        </div>
      </div>
    )
  }

  async function send() {
    setTried(true)
    if (!susComplete(answers)) return
    setBusy(true)
    setError(null)
    try {
      await api.answerSus(id, answers, comment)
      setDone({ score: susScore(answers) })
    } catch (e) {
      setError(e as ApiError)
      setBusy(false)
    }
  }

  return (
    <Card title={S.title} delay={0.1}>
      <p className="muted small">{S.lead}</p>
      <ol className={styles.sus}>
        {S.statements.map((text, i) => (
          <li key={text}>
            <fieldset className={styles.susItem} aria-invalid={tried && answers[i] === null ? true : undefined}>
              <legend className={styles.susStatement}>{i + 1}. {text}</legend>
              <div className={styles.susScale}>
                {[1, 2, 3, 4, 5].map((v) => (
                  <label key={v} className={styles.susOption}>
                    <input type="radio" name={`sus-${i}`} value={v} checked={answers[i] === v}
                           aria-label={`${v}: ${S.scale[v - 1]}`}
                           onChange={() => setAnswers((a) => a.map((x, j) => (j === i ? v : x)))} />
                    <span aria-hidden>{v}</span>
                  </label>
                ))}
              </div>
              <div className={styles.susEnds} aria-hidden><span>{S.scale[0]}</span><span>{S.scale[4]}</span></div>
            </fieldset>
          </li>
        ))}
      </ol>
      <div className="field">
        <label className="field-label" htmlFor="sus-comment">{S.comment} <span className="subtle">{t.common.optional}</span></label>
        <textarea id="sus-comment" className="textarea" rows={3} maxLength={2000} value={comment} onChange={(e) => setComment(e.target.value)} />
      </div>
      {tried && !susComplete(answers) && <p className="field-error" role="alert">{S.incomplete}</p>}
      {error && <ErrorNotice doing={S.failed} error={error} />}
      <div className={styles.susActions}>
        <button type="button" className="btn btn-primary btn-large" onClick={send} disabled={busy}>
          {busy && <span className="spinner" aria-hidden />} {busy ? S.sending : S.send}
        </button>
        <button type="button" className="btn btn-quiet" onClick={() => setDone({ skipped: true })} disabled={busy}>{S.skip}</button>
      </div>
    </Card>
  )
}
