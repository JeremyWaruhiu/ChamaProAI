import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import { ApiError, api, newIdempotencyKey } from '../api/client'
import type { ConversationBrief, ConversationDetail, ConversationOutcome, Language, MemberExplain, Turn } from '../api/types'
import { Icon } from '../components/Icon'
import { ErrorNotice } from '../components/Notice'
import { useToast } from '../components/toastContext'
import { Modal, SkeletonList } from '../components/ui'
import { extensionFor, micUnavailable, useRecorder } from '../hooks/useRecorder'
import { useSpeech, type Spoken } from '../hooks/useSpeech'
import { closingActions, lastBotTurns, latestExplain, laterStage, memberStage, quickReplies, TEXT_STAGES, understood,
  VOICE_STAGES, type Stage } from '../lib/conversation'
import { cx } from '../lib/cx'
import { navigate, paths, redirect } from '../lib/router'
import { t } from '../strings'
import styles from './Chat.module.css'

const C = t.chat
const O = C.outcome
const POLL_MS = 400
const SHORTEST_HOLD_MS = 500
const LONGEST_HOLD_MS = 55_000     // the server takes up to 60 s

const spoken = (turns: Turn[]): Spoken[] => turns.filter((x) => x.audio_url).map((x) => ({ seq: x.seq, url: x.audio_url! }))

// --- Pieces ------------------------------------------------------------------------------------

export function StageIndicator({ stages, current }: { stages: Stage[]; current: Stage | null }) {
  const here = current ? stages.indexOf(current) : -1
  return (
    <ol className={styles.stages} role="status" aria-label={C.stagesLabel} data-testid="stages">
      {stages.map((s, i) => (
        <li key={s} className={cx(styles.stage, i === here && styles.stageNow, i < here && styles.stageDone)}
            aria-current={i === here ? 'step' : undefined}>
          {i === here ? <span className={styles.spinner} aria-hidden />
            : i < here ? <Icon name="check" size={16} /> : <span className={styles.stageDot} aria-hidden />}
          {C.stage[s]}
        </li>
      ))}
    </ol>
  )
}

export function BotBubble({ turn, playing, loading, onReplay }: {
  turn: Pick<Turn, 'seq' | 'text' | 'audio_url'>; playing: boolean; loading: boolean; onReplay: (line: Spoken) => void
}) {
  return (
    <li className={cx(styles.bubble, styles.bot)} data-testid="bot-bubble">
      <p>{turn.text}</p>
      {turn.audio_url && (
        <button type="button" className={cx(styles.replay, playing && styles.replayOn)} aria-label={C.replay} title={C.replay}
                onClick={() => onReplay({ seq: turn.seq, url: turn.audio_url! })}>
          {loading ? <span className={styles.spinner} role="status" aria-label={C.audioLoading} /> : <Icon name="speaker" size={22} />}
        </button>
      )}
    </li>
  )
}

export function MemberBubble({ turn, latest }: { turn: Turn; latest: boolean }) {
  const chips = understood(turn.extraction?.used)
  const translated = turn.translation && turn.translation !== turn.text ? turn.translation : null
  const [chosen, setChosen] = useState<boolean | null>(null)
  const open = chosen ?? latest     // only the newest stays open on a small screen, unless they chose otherwise
  return (
    <li className={cx(styles.bubble, styles.member)} data-testid="member-bubble">
      <p className={styles.heard}>{turn.input_mode === 'voice' && <Icon name="mic" size={16} />} {turn.text}</p>
      {(translated || chips.length > 0) && (
        <details className={styles.more} open={open} onToggle={(e) => { if (e.currentTarget.open !== open) setChosen(e.currentTarget.open) }}>
          <summary>{C.understood}</summary>
          {translated && <p className={styles.translation}><span>{C.translation}:</span> {translated}</p>}
          {chips.length > 0 && (
            <ul className={styles.chips}>
              {chips.map((c) => <li key={c.key} className={styles.chip}>{c.label}: {c.value}</li>)}
            </ul>
          )}
        </details>
      )}
    </li>
  )
}

export function WhySheet({ explain, onClose }: { explain: MemberExplain | null; onClose: () => void }) {
  return (
    <Modal open={explain !== null} title={C.whyTitle} onClose={onClose}>
      {explain && (
        <div className={styles.why}>
          <p>{explain.reason}</p>
          <h3>{C.whyChecks}</h3>
          <ul className={styles.whyChecks}>
            {explain.checks.map((c) => (
              <li key={c.text} className={c.passed === null ? undefined : c.passed ? styles.met : styles.notMet}>
                <span className={styles.whyMark}>
                  <Icon name={c.passed === null ? 'info' : c.passed ? 'check' : 'x'} size={18} />
                  <span className="visually-hidden">{c.passed === null ? C.checkUnknown : c.passed ? C.checkPassed : C.checkFailed}</span>
                </span>
                {c.text}
              </li>
            ))}
          </ul>
          {explain.drivers.length > 0 && (
            <>
              <h3>{C.whyDrivers}</h3>
              <ul className={styles.whyDrivers}>{explain.drivers.map((d) => <li key={d}>{d}</li>)}</ul>
            </>
          )}
        </div>
      )}
    </Modal>
  )
}

export function OutcomeCard({ outcome, turns, onChanged }: {
  outcome: ConversationOutcome; turns: Turn[]; onChanged: () => void
}) {
  const toast = useToast()
  const [why, setWhy] = useState<MemberExplain | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [busy, setBusy] = useState(false)
  const key = useRef(newIdempotencyKey())
  const explain = latestExplain(turns)
  const actions = closingActions({ turns })
  const review = actions.find((a) => a.id === 'request_review')
  const book = actions.find((a) => a.id === 'book_interview')
  const rows: [string, string][] = []
  if (outcome.amount_kes !== null) rows.push([O.amount, t.common.ksh(outcome.amount_kes)])
  else if (outcome.requested_kes !== null) rows.push([O.requested, t.common.ksh(outcome.requested_kes)])
  if (outcome.term_months !== null) rows.push([O.term, C.months(outcome.term_months)])
  if (outcome.instalment_kes !== null) rows.push([O.instalment, t.common.ksh(outcome.instalment_kes)])
  if (outcome.guarantors.length) rows.push([O.guarantors, outcome.guarantors.join(', ')])

  async function askForReview() {
    if (!review?.application_id) return
    setBusy(true)
    setError(null)
    try {
      await api.requestReview(review.application_id, key.current)
      toast(O.reviewDone, 'success')
      onChanged()
    } catch (e) {
      setError(e as ApiError)
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className={styles.outcome} data-testid="outcome">
      <h2 className={cx(styles.outcomeTitle, outcome.decision === 'approved' && styles.outcomeGood)}>{O[outcome.decision]}</h2>
      {rows.length > 0 && (
        <dl className={styles.outcomeRows}>
          {rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
        </dl>
      )}
      {outcome.balance_before_kes !== null && outcome.balance_after_kes !== null && (
        <div className={styles.balance}>
          <p className={styles.balanceTitle}>{O.balance}</p>
          <p className={styles.balanceFigures}>
            <span><small>{O.balanceBefore}</small> {t.common.ksh(outcome.balance_before_kes)}</span>
            <Icon name="chevronRight" size={20} />
            <span><small>{O.balanceAfter}</small> <strong>{t.common.ksh(outcome.balance_after_kes)}</strong></span>
          </p>
        </div>
      )}
      {error && <ErrorNotice doing={O.reviewFailed} error={error} />}
      {outcome.review_requested && <p role="status" className={styles.reviewed}><Icon name="check" size={18} /> {O.reviewDone}</p>}
      <div className={styles.outcomeActions}>
        {explain && <button type="button" className="btn btn-secondary" onClick={() => setWhy(explain)}>{O.why}</button>}
        {review && !outcome.review_requested && (
          <button type="button" className="btn btn-secondary" disabled={busy} onClick={askForReview}>{review.label}</button>
        )}
        {book && <a className="btn btn-primary" href={book.application_id ? paths.myApplication(book.application_id) : paths.apply()}>{book.label}</a>}
        <a className="btn btn-quiet" href={paths.mySacco()}>{O.mySacco}</a>
      </div>
      <WhySheet explain={why} onClose={() => setWhy(null)} />
    </li>
  )
}

function LanguageChoice() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  async function choose(language: Language) {
    setBusy(true)
    setError(null)
    try {
      const started = await api.startConversation(language)
      redirect(paths.chat(started.conversation.id))
    } catch (e) {
      setError(e as ApiError)
      setBusy(false)
    }
  }

  return (
    <div className={styles.choose}>
      <h1 className={`display ${styles.chooseTitle}`}>{C.chooseLanguage}</h1>
      <p className="muted">{C.chooseLead}</p>
      {error && <ErrorNotice doing={C.startFailed} error={error} />}
      <button type="button" className={`btn btn-primary ${styles.language}`} disabled={busy} onClick={() => choose('kik')} lang="kik">{C.kikuyu}</button>
      <button type="button" className={`btn btn-primary ${styles.language}`} disabled={busy} onClick={() => choose('en')}>{C.english}</button>
      {busy && <p role="status" className={styles.starting}><span className={styles.spinner} aria-hidden /> {C.starting}</p>}
    </div>
  )
}

// --- The conversation --------------------------------------------------------------------------

type Pending = { voice: true } | { voice: false; text: string }

function Conversation({ initial, reload }: { initial: ConversationDetail; reload: () => Promise<ConversationDetail | null> }) {
  const [conv, setConv] = useState<ConversationBrief>(initial.conversation)
  const [turns, setTurns] = useState<Turn[]>(initial.turns)
  const [outcome, setOutcome] = useState<ConversationOutcome | null>(initial.outcome)
  const [pending, setPending] = useState<Pending | null>(null)
  const [waiting, setWaiting] = useState(initial.conversation.busy)
  const [stage, setStage] = useState<Stage | null>(null)
  const [draft, setDraft] = useState('')
  const [error, setError] = useState<ApiError | null>(null)
  const [hint, setHint] = useState<string | null>(null)
  const speech = useSpeech()
  const rec = useRecorder()
  const holding = useRef(false)
  const recordedAt = useRef<number | null>(null)
  const started = useRef<Promise<void> | null>(null)
  const end = useRef<HTMLLIElement>(null)
  const mic = micUnavailable()
  const open = conv.status === 'open'
  const busy = pending !== null || waiting

  // Heard after a reload: only what was said since the member last spoke, and only if they still can answer.
  const queued = useRef(false)
  useEffect(() => {
    if (queued.current || !open) return
    queued.current = true
    speech.enqueue(spoken(lastBotTurns(turns)))
  }, [open, turns, speech])

  useEffect(() => { end.current?.scrollIntoView?.({ block: 'end' }) }, [turns.length, pending, outcome, stage, conv.status])

  // Back after a reload with a reply still being worked on: wait for it, and ask again.
  useEffect(() => {
    if (!waiting) return
    const id = window.setInterval(async () => {
      const fresh = await reload().catch(() => null)
      if (fresh && !fresh.conversation.busy) {
        setConv(fresh.conversation)
        setTurns(fresh.turns)
        setOutcome(fresh.outcome)
        setWaiting(false)
        speech.enqueue(spoken(lastBotTurns(fresh.turns)))
      }
    }, 1000)
    return () => window.clearInterval(id)
  }, [waiting, reload, speech])

  // A stop the member cannot miss: the server would refuse anything longer.
  useEffect(() => {
    if (rec.state === 'recording' && rec.elapsed * 1000 >= LONGEST_HOLD_MS) void release()
  })

  const send = useCallback(async (reply: { text: string } | { audio: Blob; filename: string }) => {
    speech.stop()
    setError(null)
    setHint(null)
    const voice = 'audio' in reply
    const stages = voice ? VOICE_STAGES : TEXT_STAGES
    setPending(voice ? { voice: true } : { voice: false, text: reply.text })
    setStage(voice ? 'transcribing' : 'understanding')
    const poll = window.setInterval(() => {
      api.conversationStage(conv.id)
        .then((s) => setStage((now) => laterStage(stages, now, memberStage(s.stage))))
        .catch(() => { /* the indicator only: the reply itself says what happened */ })
    }, POLL_MS)
    try {
      const out = await api.replyToConversation(conv.id, reply)
      setConv(out.conversation)
      setTurns((was) => [...was, out.member_turn, ...out.bot_turns])
      setOutcome(out.outcome)
      speech.enqueue(spoken(out.bot_turns))
      if (!voice) setDraft('')
    } catch (e) {
      setError(e as ApiError)
      // It may have ended, or be busy elsewhere: take the server's word for where it stands.
      const fresh = await reload().catch(() => null)
      if (fresh) {
        setConv(fresh.conversation)
        setTurns(fresh.turns)
        setOutcome(fresh.outcome)
        setWaiting(fresh.conversation.busy)
      }
    } finally {
      window.clearInterval(poll)
      setPending(null)
      setStage(null)
    }
  }, [conv.id, reload, speech])

  function press() {
    if (busy || holding.current) return
    speech.unlock()
    speech.stop()
    setHint(null)
    setError(null)
    holding.current = true
    recordedAt.current = null
    started.current = rec.start().then(() => {
      if (holding.current) recordedAt.current = Date.now()
      else { rec.cancel(); setHint(C.micReady) }       // let go during the browser's permission question
    })
  }

  async function release() {
    if (!holding.current) return
    holding.current = false
    const at = recordedAt.current
    if (at === null) return
    if (Date.now() - at < SHORTEST_HOLD_MS) { rec.cancel(); setHint(C.holdLonger); return }
    const blob = await rec.stop()
    if (blob) await send({ audio: blob, filename: `reply.${extensionFor(blob.type)}` })
  }

  function cancelHold() {
    if (holding.current) { holding.current = false; rec.cancel() }
  }

  function onMicDown(e: PointerEvent<HTMLButtonElement>) {
    e.currentTarget.setPointerCapture?.(e.pointerId)
    press()
  }

  function onMicKey(e: KeyboardEvent<HTMLButtonElement>, down: boolean) {
    if (e.key !== ' ' && e.key !== 'Enter') return
    e.preventDefault()
    if (e.repeat) return
    if (down) press()
    else void release()
  }

  function submit() {
    const text = draft.trim()
    if (!text || busy) return
    speech.unlock()
    void send({ text })
  }

  const replies = open && !busy ? quickReplies(conv.state, conv.language) : []
  const lastMember = turns.map((x) => x.speaker).lastIndexOf('member')
  const recording = rec.state === 'recording'
  const stages = pending?.voice === false ? TEXT_STAGES : VOICE_STAGES

  return (
    <>
      <ol className={styles.turns} aria-live="polite" lang={conv.language === 'kik' ? undefined : 'en'}>
        {turns.map((turn, i) => (turn.speaker === 'bot'
          ? <BotBubble key={turn.seq} turn={turn} playing={speech.playing === turn.seq} loading={speech.loading === turn.seq}
                       onReplay={speech.replay} />
          : <MemberBubble key={turn.seq} turn={turn} latest={i === lastMember} />))}
        {pending && (
          <li className={cx(styles.bubble, styles.member, styles.sending)}>
            <p className={styles.heard}>{pending.voice ? <><Icon name="mic" size={16} /> {C.voiceReply}</> : pending.text}</p>
          </li>
        )}
        {outcome && <OutcomeCard outcome={outcome} turns={turns} onChanged={() => { reload().then((d) => d && setOutcome(d.outcome)).catch(() => {}) }} />}
        <li ref={end} className={styles.end} aria-hidden />
      </ol>

      <footer className={cx(styles.composer, conv.status === 'completed' && !error && styles.composerEmpty)}>
        {!speech.unlocked && open && (
          <button type="button" className={`btn btn-accent ${styles.tap}`} onClick={speech.unlock}>
            <Icon name="speaker" size={22} /> {C.tapToStart}
          </button>
        )}
        {error && <ErrorNotice doing={C.replyFailed} error={error} />}
        {rec.error && <p role="alert" className={styles.hint}>{rec.error}</p>}
        {hint && <p role="status" className={styles.hint}>{hint}</p>}
        {conv.status === 'abandoned' && (
          <div className={styles.ended}>
            <p>{C.abandoned}</p>
            <button type="button" className="btn btn-primary" onClick={() => navigate(paths.chat())}>{C.startAgain}</button>
          </div>
        )}
        {waiting && !pending && <p role="status" className={styles.hint}><span className={styles.spinner} aria-hidden /> {C.stillWorking}</p>}
        {(pending || recording) && <StageIndicator stages={stages} current={recording ? 'listening' : stage} />}
        {replies.length > 0 && (
          <div className={styles.quick}>
            {replies.map((r) => (
              <button key={r.send} type="button" className={`btn btn-primary ${styles.quickReply}`}
                      onClick={() => { speech.unlock(); void send({ text: r.send }) }}>{r.label}</button>
            ))}
          </div>
        )}
        {open && (
          <>
            {mic === null ? (
              <button type="button" className={cx(styles.mic, recording && styles.micOn)} disabled={busy} aria-pressed={recording}
                      onPointerDown={onMicDown} onPointerUp={() => void release()} onPointerCancel={cancelHold}
                      onKeyDown={(e) => onMicKey(e, true)} onKeyUp={(e) => onMicKey(e, false)}
                      onContextMenu={(e) => e.preventDefault()} data-testid="mic">
                <Icon name="mic" size={28} /> {recording ? C.releaseToSend : C.holdToTalk}
                {recording && <span className={styles.level} style={{ transform: `scaleX(${rec.level})` }} aria-hidden />}
              </button>
            ) : <p className={styles.hint}>{mic === 'insecure' ? C.micInsecure : C.micNone}</p>}
            <form className={styles.typeRow} onSubmit={(e) => { e.preventDefault(); submit() }}>
              <input className={`input ${styles.typeBox}`} value={draft} disabled={busy} aria-label={C.typeLabel}
                     placeholder={C.typePlaceholder} autoComplete="off" enterKeyHint="send" maxLength={1000}
                     onChange={(e) => setDraft(e.target.value)} />
              <button type="submit" className={`btn btn-secondary ${styles.sendBtn}`} disabled={busy || !draft.trim()} aria-label={C.send} title={C.send}>
                <Icon name="send" size={22} />
              </button>
            </form>
          </>
        )}
      </footer>
    </>
  )
}

// --- The screen --------------------------------------------------------------------------------

export function Chat({ id }: { id: number | null }) {
  const [detail, setDetail] = useState<ConversationDetail | null>(null)
  const [nothingOpen, setNothingOpen] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  const reload = useCallback(() => (id ? api.conversation(id) : api.currentConversation()), [id])
  const load = useCallback(async () => {
    setError(null)
    try {
      const found = await reload()
      if (found && !id) redirect(paths.chat(found.conversation.id))
      else if (found) setDetail(found)
      else setNothingOpen(true)
    } catch (e) {
      setError(e as ApiError)
    }
  }, [id, reload])
  // oxlint-disable-next-line react/set-state-in-effect -- fetch on mount; state is set after the await
  useEffect(() => { void load() }, [load])

  return (
    <div className={styles.chat}>
      <header className={styles.top}>
        <a href={paths.my()} className={styles.back} aria-label={C.back} title={C.back}><Icon name="arrowLeft" size={24} /></a>
        <h1 className={styles.title}>{C.title}</h1>
      </header>
      {error && <div className={styles.padded}><ErrorNotice doing={C.loadFailed} error={error} onRetry={load} /></div>}
      {!error && !detail && !nothingOpen && <div className={styles.padded}><SkeletonList rows={3} what={C.title} /></div>}
      {nothingOpen && <LanguageChoice />}
      {detail && <Conversation initial={detail} reload={reload as () => Promise<ConversationDetail | null>} />}
    </div>
  )
}
