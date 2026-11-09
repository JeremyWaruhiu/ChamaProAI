import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, api } from '../api/client'
import type { DemoStatus, Health, PolicyCheck, PresentDetail, PresentRow, PresentTurn, StaffExplain } from '../api/types'
import { Icon } from '../components/Icon'
import { ErrorNotice } from '../components/Notice'
import { useToast } from '../components/toastContext'
import { Badge, EmptyState, Modal, SkeletonList } from '../components/ui'
import { useAuth } from '../lib/auth'
import { cx } from '../lib/cx'
import { formatDateTime } from '../lib/format'
import { evaluationsOf, featureRows, previousEvaluation, shapRows, type SourceKind } from '../lib/present'
import { usePresentationMode } from '../lib/presentation'
import { RISK_ORDER } from '../lib/risk'
import { paths } from '../lib/router'
import { t } from '../strings'
import styles from './Present.module.css'

const P = t.present
const A = t.automatic
const OPEN_POLL_MS = 1000
const CLOSED_POLL_MS = 4000
const SOURCES: SourceKind[] = ['records', 'profile', 'conversation', 'missing']
const SOURCE_STYLE: Record<SourceKind, string> = { records: styles.fromRecords, profile: styles.fromProfile,
                                                   conversation: styles.fromConversation, missing: styles.fromMissing }
const RISK_STYLE: Record<string, string> = { Low: styles.riskLow, Medium: styles.riskMedium, High: styles.riskHigh }

function PresentationToggle() {
  const [on, set] = usePresentationMode()
  return (
    <button type="button" className={cx('btn btn-secondary', styles.toggle)} aria-pressed={on} onClick={() => set(!on)}>
      <Icon name={on ? 'x' : 'overview'} size={18} /> {on ? P.presentationOn : P.presentation}
    </button>
  )
}

/** Fetch now and every `ms`, keeping what is on the screen through a dropped poll. */
function usePolling<T>(load: () => Promise<T>, ms: (data: T | null) => number) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const latest = useRef<T | null>(null)
  const refresh = useCallback(async () => {
    try {
      const next = await load()
      latest.current = next
      setData(next)
      setError(null)
    } catch (e) {
      setError(e as ApiError)
    }
  }, [load])
  useEffect(() => {
    let timer = 0
    let live = true
    const tick = async () => {
      await refresh()
      if (live) timer = window.setTimeout(tick, ms(latest.current))
    }
    void tick()
    return () => { live = false; window.clearTimeout(timer) }
  }, [refresh, ms])
  return { data, error, refresh }
}

// --- Choosing a conversation ---------------------------------------------------------------------

const everyTwoSeconds = () => 2000

function SpeechStatus() {
  const [health, setHealth] = useState<Health | null>(null)
  const kik = health?.asr.kik
  const warmed = kik?.warmed
  useEffect(() => {
    if (warmed) return
    const check = () => { api.health().then(setHealth).catch(() => {}) }
    check()
    const id = window.setInterval(check, 5000)     // the page is often open before the model has warmed
    return () => window.clearInterval(id)
  }, [warmed])
  if (!kik) return null
  return kik.warmed ? <Badge tone="low" icon="check">{P.speechReady}</Badge>
    : <Badge tone={kik.loaded ? 'wait' : 'high'}>{kik.loaded ? P.speechNotReady : P.speechOff}</Badge>
}

function DemoReset({ onDone }: { onDone: () => void }) {
  const toast = useToast()
  const [status, setStatus] = useState<DemoStatus | null>(null)
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  useEffect(() => { api.demoStatus().then(setStatus).catch(() => {}) }, [asking])
  if (!status?.available) return null

  async function reset() {
    setBusy(true)
    setError(null)
    try {
      const r = await api.demoReset()
      toast(P.demoResetDone(r.conversations_closed, r.loans_reversed, r.applications_closed), r.problems.length ? 'error' : 'success')
      if (r.problems.length) setError(new ApiError(409, r.problems.join(' ')))
      else setAsking(false)
      onDone()
    } catch (e) {
      setError(e as ApiError)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className={styles.reset}>
      <div>
        <h2 className={styles.panelTitle}>{P.demoReset}</h2>
        <p className={styles.small}>{P.demoResetLead}</p>
        <ul className={styles.demoPeople}>
          {status.people.map((p) => <li key={p.member_id}>{P.demoPerson(p.full_name, p.open_conversations, p.active_loans)}</li>)}
        </ul>
      </div>
      <button type="button" className="btn btn-secondary" onClick={() => setAsking(true)}>{P.demoReset}</button>
      <Modal open={asking} title={P.demoResetTitle} onClose={() => setAsking(false)} actions={<>
        <button type="button" className="btn btn-quiet" onClick={() => setAsking(false)}>{t.common.cancel}</button>
        <button type="button" className="btn btn-primary" disabled={busy} onClick={reset}>{P.demoResetConfirm}</button>
      </>}>
        <p>{P.demoResetBody}</p>
        {error && <ErrorNotice doing={P.demoResetFailed} error={error} />}
      </Modal>
    </section>
  )
}

export function PresentList() {
  const { user } = useAuth()
  const load = useCallback(() => api.presentList(), [])
  const { data, error, refresh } = usePolling<PresentRow[]>(load, everyTwoSeconds)
  return (
    <div className={styles.page} data-testid="present-list">
      <header className={styles.head}>
        <div>
          <h1 className={`display ${styles.title}`}>{P.title}</h1>
          <p className={styles.small}>{P.lead}</p>
        </div>
        <div className={styles.headActions}><SpeechStatus /><PresentationToggle /></div>
      </header>
      {error && !data && <ErrorNotice doing={P.loadFailed} error={error} onRetry={refresh} />}
      {!data && !error && <SkeletonList rows={3} what={P.title} />}
      {data?.length === 0 && <div className="card"><EmptyState icon="mic" title={P.empty}>{P.emptyBody}</EmptyState></div>}
      {data && data.length > 0 && (
        <ul className={styles.rows}>
          {data.map((c) => (
            <li key={c.id}>
              <a href={paths.presentOne(c.id)} className={cx(styles.row, c.status === 'open' && styles.rowOpen)} aria-label={P.follow(c.member_name)}>
                <strong className={styles.rowName}>{c.member_name}</strong>
                <span className={styles.small}>{c.member_no}</span>
                <span>{c.language === 'kik' ? t.chat.kikuyu : t.chat.english}</span>
                <Badge tone={c.status === 'open' ? 'attention' : c.status === 'completed' ? 'low' : 'neutral'}>{P.status[c.status]}</Badge>
                <span>{c.state}</span>
                <span className={styles.small}>{P.turns(c.turn_count)} · {formatDateTime(c.last_activity_at)}</span>
                <Icon name="chevronRight" />
              </a>
            </li>
          ))}
        </ul>
      )}
      {user?.role === 'admin' && <DemoReset onDone={refresh} />}
    </div>
  )
}

// --- Following one -------------------------------------------------------------------------------

const seconds = (v: number | null) => (v === null ? P.notRun : P.ms(v))

/** A dash on the screen; why there is none is for staff who point at it. */
function NoTranslation() {
  return (
    <span className={styles.muted} title={P.noTranslation} data-testid="no-translation">
      <span aria-hidden>-</span><span className="visually-hidden">{P.noTranslation}</span>
    </span>
  )
}

function MemberTurnCard({ turn, asked }: { turn: PresentTurn; asked: PresentTurn | null }) {
  const ex = turn.extraction
  const read = ex?.model ? P.readBy.model : P.readBy.parsers
  return (
    <li className={styles.turn} data-testid="present-turn">
      {asked && <p className={styles.asked}><span className={styles.tag}>{turn.template_id}</span> {asked.text}</p>}
      <div className={styles.turnBody}>
        {turn.input_mode === 'voice' && turn.audio_url
          ? <audio className={styles.player} controls preload="none" src={turn.audio_url} aria-label={P.voice} />
          : <span className={styles.typed}><Badge>{P.typed}</Badge></span>}
        <dl className={styles.turnRows}>
          <div><dt>{P.transcript}</dt><dd lang="kik" className={styles.spoken}>{turn.asr_transcript ?? turn.text}</dd></div>
          <div><dt>{P.translation}</dt><dd>{turn.translation ?? <NoTranslation />}</dd></div>
          <div><dt>{P.extracted} <small>({read})</small></dt>
            <dd><pre className={styles.json}>{JSON.stringify(ex?.used ?? {}, null, 2)}</pre></dd></div>
        </dl>
        <ul className={styles.latency} aria-label="Time taken">
          {(['asr', 'translate_extract', 'evaluate', 'tts'] as const).map((k) => (
            <li key={k}><small>{P.latency[k]}</small> <strong>{seconds(turn.latency_ms[k])}</strong></li>
          ))}
        </ul>
      </div>
    </li>
  )
}

function Pipeline({ detail }: { detail: PresentDetail }) {
  const { turns, row } = detail
  const box = useRef<HTMLOListElement>(null)
  const members = turns.filter((x) => x.speaker === 'member')
  useEffect(() => { box.current?.scrollTo?.({ top: box.current.scrollHeight, behavior: 'smooth' }) }, [members.length, row.busy])
  return (
    <section className={styles.left}>
      <h2 className={styles.panelTitle}>{P.pipeline}</h2>
      <ol ref={box} className={styles.turns}>
        {members.length === 0 && !row.busy && <li className={styles.muted}>{P.noTurns}</li>}
        {members.map((m) => {
          const before = turns.filter((x) => x.seq < m.seq && x.speaker === 'bot')
          return <MemberTurnCard key={m.seq} turn={m} asked={before[before.length - 1] ?? null} />
        })}
        {row.busy && (
          <li className={styles.working} role="status" data-testid="present-working">
            <span className={styles.spinner} aria-hidden /> {row.stage ? P.stage[row.stage] : P.working}
          </li>
        )}
      </ol>
    </section>
  )
}

export function RiskBars({ now, was }: { now: StaffExplain; was: StaffExplain | null }) {
  return (
    <section className={styles.panel} data-testid="risk">
      <h3 className={styles.panelTitle}>{P.risk}</h3>
      <p className={cx(styles.riskClass, RISK_STYLE[now.risk_class])}>{t.risk.badge(now.risk_class as never)}</p>
      <ul className={styles.probs}>
        {RISK_ORDER.map((c) => {
          const p = now.probabilities[c] ?? 0
          const b = was?.probabilities[c]
          return (
            <li key={c} className={styles.prob}>
              <span>{c}</span>
              <span className={styles.probTrack}>
                <span className={cx(styles.probFill, RISK_STYLE[c])} style={{ width: `${p * 100}%` }} />
                {b !== undefined && <span className={styles.probWas} style={{ left: `${b * 100}%` }} title={`${P.previous}: ${(b * 100).toFixed(1)}%`} />}
              </span>
              <strong>{(p * 100).toFixed(1)}%</strong>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

export function ShapChart({ now, was }: { now: StaffExplain; was: StaffExplain | null }) {
  const { rows, scale } = shapRows(now, was)
  const width = (v: number) => `${(Math.abs(v) / scale) * 50}%`
  return (
    <section className={styles.panel} data-testid="shap">
      <h3 className={styles.panelTitle}>{P.shap}</h3>
      {rows.length === 0 ? <p className={styles.muted}>{P.shapNone}</p> : (
        <>
          <ul className={styles.legend}>
            <li><span className={cx(styles.swatch, styles.favour)} /> {P.shapFavour}</li>
            <li><span className={cx(styles.swatch, styles.against)} /> {P.shapAgainst}</li>
            {was && <li><span className={cx(styles.swatch, styles.faint)} /> {P.previous}</li>}
          </ul>
          <ul className={styles.shapRows}>
            {rows.map((r) => (
              <li key={r.feature} className={styles.shapRow} data-testid="shap-row"
                  title={`${r.label} (${r.value}): ${r.now >= 0 ? '+' : ''}${r.now.toFixed(3)}${r.before === null ? '' : `, ${P.previous.toLowerCase()} ${r.before >= 0 ? '+' : ''}${r.before.toFixed(3)}`}`}>
                <span className={styles.shapLabel}>{r.label} <small>{r.value}</small></span>
                <span className={styles.shapTrack}>
                  <span className={cx(styles.shapBar, r.now >= 0 ? styles.favour : styles.against)}
                        style={r.now >= 0 ? { left: '50%', width: width(r.now) } : { right: '50%', width: width(r.now) }} />
                  {r.before !== null && (
                    <span className={cx(styles.shapBar, styles.shapWas, styles.faint)} data-testid="shap-was"
                          style={r.before >= 0 ? { left: '50%', width: width(r.before) } : { right: '50%', width: width(r.before) }} />
                  )}
                </span>
                <span className={styles.shapValue}>{r.now >= 0 ? '+' : ''}{r.now.toFixed(3)}</span>
              </li>
            ))}
          </ul>
          <p className={styles.note}>{P.shapNote}</p>
        </>
      )}
    </section>
  )
}

export function FeatureTable({ now }: { now: StaffExplain }) {
  return (
    <section className={styles.panel} data-testid="features">
      <h3 className={styles.panelTitle}>{P.features}</h3>
      <ul className={styles.legend}>
        {SOURCES.map((k) => <li key={k}><span className={cx(styles.swatch, SOURCE_STYLE[k])} /> {P.source[k]}</li>)}
      </ul>
      <table className={styles.features}>
        <thead><tr><th>{P.featureCol}</th><th>{P.valueCol}</th><th>{P.sourceCol}</th></tr></thead>
        <tbody>
          {featureRows(now).map((r) => (
            <tr key={r.key} className={SOURCE_STYLE[r.source]} data-source={r.source}>
              <td>{r.label}</td><td>{r.value}</td><td>{P.source[r.source]}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

function checkValue(v: unknown): string {
  if (v === null || v === undefined) return '-'
  if (typeof v === 'number') return Number.isInteger(v) ? v.toLocaleString('en-KE') : v.toFixed(2)
  return typeof v === 'object' ? JSON.stringify(v) : String(v)
}

function CheckList({ checks }: { checks: PolicyCheck[] }) {
  return (
    <section className={styles.panel} data-testid="checks">
      <h3 className={styles.panelTitle}>{P.checks}</h3>
      <ul className={styles.checks}>
        {checks.map((c) => (
          <li key={c.check}>
            <span className={styles.checkHead}>
              {c.passed === null ? <Badge>{A.unknown}</Badge>
                : c.passed ? <Badge tone="low" icon="check">{A.pass}</Badge> : <Badge tone="high" icon="x">{A.fail}</Badge>}
              <strong>{A.checkLabel[c.check] ?? c.check}</strong>
            </span>
            <span className={styles.checkValues}>
              {Object.entries(c.values).filter(([k]) => k !== 'guarantors').map(([k, v]) => `${k}: ${checkValue(v)}`).join('; ')}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}

export function Verdict({ now, detail }: { now: StaffExplain; detail: PresentDetail }) {
  const ledger = detail.outcome?.ledger
  const out = detail.outcome
  return (
    <section className={styles.verdict} data-testid="verdict">
      <div className={styles.verdictMain}>
        <strong className={styles.verdictOutcome}>{P.outcome[now.outcome] ?? now.outcome}</strong>
        <span className={styles.tag}>{now.reason_code}</span>
        {now.questions[0] && <span className={styles.tag}>{P.nextQuestion(now.questions[0])}</span>}
        <span className={styles.small}>{P.policy(now.policy_version)}</span>
      </div>
      <div className={styles.ledger} data-testid="ledger">
        {ledger && out ? (
          <>
            <span className={styles.ledgerEntry}><small>{P.ledger}</small> <code>{ledger.reference}</code> {ledger.entry_type} +{t.common.ksh(ledger.amount_kes)}</span>
            <span className={styles.ledgerBalance}><small>{P.balanceChange}</small>
              {t.common.ksh(out.balance_before_kes ?? 0)} <Icon name="chevronRight" size={18} /> <strong>{t.common.ksh(out.balance_after_kes ?? 0)}</strong></span>
          </>
        ) : <span className={styles.muted}>{P.ledgerNone}</span>}
      </div>
    </section>
  )
}

function Decision({ detail }: { detail: PresentDetail }) {
  const evaluations = evaluationsOf(detail.turns)
  const [picked, setPicked] = useState<number | null>(null)
  const index = picked !== null && picked < evaluations.length ? picked : evaluations.length - 1
  const now = evaluations[index]?.explain ?? null
  if (!now) {
    return <section className={styles.right}><p className={styles.muted}>{P.noEvaluation}</p></section>
  }
  const was = previousEvaluation(evaluations, index)
  return (
    <section className={styles.right} aria-label={P.decisionTitle}>
      <Verdict now={now} detail={detail} />
      {evaluations.length > 1 && (
        <div className={styles.picker} role="group" aria-label={P.evaluation}>
          <span className={styles.small}>{P.evaluation}</span>
          {evaluations.map((e, i) => (
            <button key={e.seq} type="button" aria-pressed={i === index} aria-label={P.pickEvaluation(i + 1)}
                    className={cx(styles.pick, i === index && styles.pickOn)}
                    onClick={() => setPicked(i === evaluations.length - 1 ? null : i)}>{i + 1}</button>
          ))}
        </div>
      )}
      <div className={styles.grid}>
        <div className={styles.gridCol}>
          <RiskBars now={now} was={was} />
          <ShapChart now={now} was={was} />
        </div>
        <div className={styles.gridCol}>
          <FeatureTable now={now} />
          <CheckList checks={now.trace.checks ?? []} />
        </div>
      </div>
    </section>
  )
}

export function PresentOne({ id }: { id: number }) {
  const load = useCallback(() => api.presentDetail(id), [id])
  const pace = useCallback((d: PresentDetail | null) => (d?.row.status === 'open' || !d ? OPEN_POLL_MS : CLOSED_POLL_MS), [])
  const { data, error, refresh } = usePolling<PresentDetail>(load, pace)
  return (
    <div className={styles.page} data-testid="present-one">
      <header className={styles.head}>
        <div className={styles.headLeft}>
          <a href={paths.present()} className={styles.back} aria-label={P.back} title={P.back}><Icon name="arrowLeft" /></a>
          {data && (
            <>
              <h1 className={styles.who}>{data.row.member_name}</h1>
              <Badge tone={data.row.status === 'open' ? 'attention' : data.row.status === 'completed' ? 'low' : 'neutral'}>{P.status[data.row.status]}</Badge>
              <span className={styles.small}>{data.row.language === 'kik' ? t.chat.kikuyu : t.chat.english} · {data.row.state}</span>
              {data.turns.some((x) => x.kik_pending) && <Badge>{P.pendingKikuyu}</Badge>}
            </>
          )}
          {error && data && <Badge tone="wait">{P.reconnecting}</Badge>}
        </div>
        <PresentationToggle />
      </header>
      {error && !data && <ErrorNotice doing={P.loadFailed} error={error} onRetry={refresh} />}
      {!data && !error && <SkeletonList rows={4} what={P.title} />}
      {data && (
        <div className={styles.columns}>
          <Pipeline detail={data} />
          <Decision detail={data} />
        </div>
      )}
    </div>
  )
}
