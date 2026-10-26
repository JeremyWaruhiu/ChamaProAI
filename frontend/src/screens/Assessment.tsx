import { AnimatePresence, m } from 'motion/react'
import { useState, type FormEvent } from 'react'
import { ApiError, api } from '../api/client'
import type {
  Assessment as AssessmentT, Comparator, Contribution, Decision, InterviewState, Outcome, RuleCondition,
} from '../api/types'
import { OutcomeBadge, RiskBadge, StatusBadge, TypedBadge } from '../components/Badges'
import { Icon } from '../components/Icon'
import { ErrorNotice, Notice } from '../components/Notice'
import { ReplayButton } from '../components/ReplayButton'
import { Shell } from '../components/Shell'
import { useToast } from '../components/toastContext'
import { Badge, Card, Field, PracticeBadge, SkeletonPage } from '../components/ui'
import { cx } from '../lib/cx'
import { useInterview } from '../hooks/useInterview'
import { useQuestions } from '../hooks/useQuestions'
import { DEFAULT_GUARANTORS, EMPTY_DECISION, decisionBody, decisionErrors, outcomeOptions, type DecisionDraft } from '../lib/decision'
import { domainLabel } from '../lib/domains'
import { explain } from '../lib/explain'
import { extractedFacts, featureLabel, featureValue } from '../lib/features'
import { applicantName, formatDateTime, formatKes, percent } from '../lib/format'
import { fade, fadeUp, useReducedMotion } from '../lib/motion'
import {
  BORDERLINE_POINTS, RISK_MEANING, RISK_ORDER, agrees, closeness, recommendation, riskTone,
  type Closeness, type RiskClass,
} from '../lib/risk'
import { paths } from '../lib/router'
import type { Tone } from '../lib/status'
import { t } from '../strings'
import styles from './Assessment.module.css'

const A = t.assessment
const D = t.decision
const C = t.comparator
const COMPLETENESS_WARNING = 0.8

export function Assessment({ id }: { id: number }) {
  const iv = useInterview(id)
  const data = iv.data
  const name = applicantName(data?.applicant.name)
  const a = data?.assessment

  return (
    <Shell title={data ? A.titleFor(name) : A.title} interviewId={id} step="assessment"
           applicationId={data?.application_id} practice={data?.mode === 'practice'}
           aside={a && A.assessedAt(formatDateTime(a.created_at))}>
      {iv.error && <ErrorNotice doing={A.loadFailed} error={iv.error} onRetry={iv.refresh} />}
      {!data && !iv.error && <SkeletonPage what={A.title} />}

      {data && !a && (
        <Notice tone="info" title={A.notAssessed}
                action={<a className="btn btn-primary" href={paths.review(id)}>{A.goToReview}</a>}>
          {A.notAssessedBody}
        </Notice>
      )}

      {data && a && <AssessmentView interview={data} a={a} name={name} onDecided={iv.refresh} />}
    </Shell>
  )
}

function AssessmentView({ interview, a, name, onDecided }: {
  interview: InterviewState; a: AssessmentT; name: string; onDecided: () => Promise<void>
}) {
  const close = closeness(a.probabilities)
  return (
    <div className={styles.page}>
      <p className={styles.support}><Icon name="user" size={18} /> <strong>{A.support}</strong>{A.supportBody}</p>

      {close.borderline && <Borderline close={close} />}

      <div className={styles.top}>
        <RiskCard a={a} />
        <Explanation a={a} />
      </div>

      <section className={styles.side} aria-label={A.modelVsRule}>
        <h2 className={styles.sectionTitle}>{A.modelVsRule}</h2>
        <div className={styles.sideGrid}>
          <ModelSide a={a} close={close} />
          {a.comparator ? <ComparatorPanel c={a.comparator} /> : (
            <Card title={C.title} className={styles.ruleCard}><p className="muted">{A.noApplication}</p></Card>
          )}
        </div>
      </section>

      <div className={styles.grid}>
        <Contributions a={a} />
        <div className={styles.stack}>
          <Probabilities a={a} />
          <Completeness a={a} />
        </div>
      </div>

      <Facts a={a} interviewId={interview.id} />
      <Transcripts interview={interview} />

      <DecisionPanel interview={interview} a={a} close={close} name={name} onDecided={onDecided} />

      <AuditLine a={a} />
    </div>
  )
}

/** The per-assessment audit record, as stored. */
export function AuditLine({ a }: { a: AssessmentT }) {
  const { head, tail } = A.audit(a.id, formatDateTime(a.created_at), a.assessed_by, a.model_file, a.extraction_model)
  return (
    <p className={styles.audit}>
      <Icon name="shield" size={16} /> <span>
        {head}(<span title={a.model_sha256}>{A.sha(a.model_sha256.slice(0, 12))}</span>){tail}
      </span>
    </p>
  )
}

function Borderline({ close }: { close: Closeness }) {
  const [c1, p1] = close.first
  const [c2, p2] = close.second
  return (
    <div className={styles.borderline} role="alert">
      <Icon name="alert" size={22} />
      <div>
        <p className={styles.borderlineTitle}>{A.borderlineTitle}</p>
        <p>{A.borderlineBody(c1, percent(p1), c2, percent(p2), close.gapPoints, BORDERLINE_POINTS)}</p>
      </div>
    </div>
  )
}

/** The three bands with this application's marked: where it sits at a glance. */
function RiskCard({ a }: { a: AssessmentT }) {
  const tone = riskTone(a.risk_class)
  const reduced = useReducedMotion()
  return (
    <m.section className={cx(styles.risk, styles[tone])} aria-label={A.riskEyebrow} {...fadeUp(reduced)}>
      <p className="eyebrow">{A.riskEyebrow}</p>
      <p className={cx('display', styles.riskClass)}>{A.risk(a.risk_class)}</p>
      <p className={styles.meaning}>{RISK_MEANING[a.risk_class as RiskClass] ?? ''}</p>
      <ol className={styles.bands} aria-hidden>
        {RISK_ORDER.map((c) => (
          <li key={c} className={cx(styles.band, styles[`band${c}`], c === a.risk_class && styles.bandOn)}>{c}</li>
        ))}
      </ol>
      <p className={styles.riskProb}>{A.probability(percent(a.probabilities[a.risk_class] ?? 0))}</p>
    </m.section>
  )
}

function Explanation({ a }: { a: AssessmentT }) {
  const { favour, against } = explain(a.risk_class, a.contributions)
  return (
    <Card eyebrow={A.explanationEyebrow} title={A.explanation(a.risk_class)} delay={0.05}>
      {favour.length + against.length === 0 ? <p className="muted">{A.nothingStrong}</p> : (
        <div className={styles.reasons}>
          {favour.length > 0 && (
            <div>
              <p className={styles.reasonHead}><span className={styles.up} aria-hidden>▲</span> {A.inFavour}</p>
              <ul className={styles.reasonList}>{favour.map((f) => <li key={f}>{f}</li>)}</ul>
            </div>
          )}
          {against.length > 0 && (
            <div>
              <p className={styles.reasonHead}><span className={styles.down} aria-hidden>▼</span> {A.against}</p>
              <ul className={styles.reasonList}>{against.map((f) => <li key={f}>{f}</li>)}</ul>
            </div>
          )}
        </div>
      )}
      <p className={`subtle small ${styles.note}`}>{A.explanationNote}</p>
    </Card>
  )
}

function ModelSide({ a, close }: { a: AssessmentT; close: Closeness }) {
  return (
    <Card eyebrow={A.modelSide} title={recommendation(a.risk_class, close.borderline)} className={styles.modelCard}>
      <div className={styles.badgeRow}><RiskBadge risk={a.risk_class} /></div>
      <p className="muted">{A.modelAdvice}</p>
    </Card>
  )
}

const RESULT_TONE: Record<RuleCondition['result'], Tone> = { pass: 'low', fail: 'high', pending: 'wait' }
const AGREE_TONE: Record<RuleCondition['agreement'], Tone> = { agree: 'low', diverge: 'attention', pending: 'wait', undetermined: 'neutral' }
const RESULT_ICON = { pass: 'check', fail: 'x', pending: 'clock' } as const

/** The SACCO rule beside the model: each condition with its result and whether it agrees. */
export function ComparatorPanel({ c }: { c: Comparator }) {
  return (
    <Card eyebrow={C.title} title={C.recommends[c.rule_recommendation]} className={styles.ruleCard}>
      <div className={styles.badgeRow}>
        <Badge tone={RESULT_TONE[c.result]} icon={RESULT_ICON[c.result]}>{C.overall}: {C.result[c.result]}</Badge>
        <Badge tone={AGREE_TONE[c.agreement]}>{C.agreement[c.agreement]}</Badge>
        {c.mode === 'practice' && <PracticeBadge />}
      </div>
      <p className="subtle small">{C.rule}</p>
      <ul className={styles.conditions} aria-label={C.conditions}>
        {c.conditions.map((x) => (
          <li key={x.name} className={cx(styles.condition, styles[`cond-${x.result}`])} data-result={x.result}>
            <span className={styles.condIcon} aria-hidden><Icon name={RESULT_ICON[x.result]} size={14} /></span>
            <div className={styles.condText}>
              <span className={styles.condLabel}>{x.label}</span>
              <span className="subtle small">{x.detail}</span>
            </div>
            <div className={styles.condBadges}>
              <Badge tone={RESULT_TONE[x.result]}>{C.condition[x.result]}</Badge>
              <Badge tone={AGREE_TONE[x.agreement]}>{C.agreement[x.agreement]}</Badge>
            </div>
          </li>
        ))}
      </ul>
      <p className="subtle small">{C.maxBorrowable(c.max_borrowable_kes)} · {C.tenure(c.tenure_months)} · {C.verified(c.verified_guarantors)}</p>
    </Card>
  )
}

function Probabilities({ a }: { a: AssessmentT }) {
  const classes = [...RISK_ORDER.filter((c) => c in a.probabilities),
    ...Object.keys(a.probabilities).filter((c) => !RISK_ORDER.includes(c as RiskClass))]
  return (
    <Card title={A.probabilities}>
      <ul className={styles.bars}>
        {classes.map((c) => {
          const p = a.probabilities[c]
          return (
            <li key={c} className={c === a.risk_class ? styles.predicted : undefined}>
              <span className={styles.barLabel}>{c}</span>
              <span className={styles.barTrack}>
                <span className={cx(styles.barFill, styles[riskTone(c)])} style={{ width: `${p * 100}%` }} />
              </span>
              <span className={`${styles.barValue} num`}>{(p * 100).toFixed(1)}%</span>
            </li>
          )
        })}
      </ul>
    </Card>
  )
}

function Completeness({ a }: { a: AssessmentT }) {
  const low = a.extraction_completeness < COMPLETENESS_WARNING
  return (
    <Card title={A.completeness} actions={<span className={`${styles.completenessValue} num`}>{percent(a.extraction_completeness)}</span>}>
      <span className={styles.meter}><span className={low ? styles.meterLow : undefined}
                                          style={{ width: `${a.extraction_completeness * 100}%` }} /></span>
      <p className="muted small">{A.completenessBody(a.features_populated, a.features_total)}</p>
      {low && <div className={styles.gap}><Notice tone="warning" title={A.lowEvidence}>{A.lowEvidenceBody}</Notice></div>}
    </Card>
  )
}

/** SHAP bars: each fact's push towards or away from the predicted band, scaled to the largest. */
function Contributions({ a }: { a: AssessmentT }) {
  if (typeof a.contributions === 'string') {
    return (
      <Card title={A.contributions}>
        <Notice tone="warning" title={A.noShap}>{a.contributions}</Notice>
      </Card>
    )
  }
  const max = Math.max(...a.contributions.map((c) => Math.abs(c.shap)), 1e-9)
  return (
    <Card title={A.contributions}>
      <p className="muted small">{A.contributionsLead(a.risk_class)}</p>
      <ol className={styles.contribs}>
        {a.contributions.map((c) => <ContributionRow key={c.feature} c={c} max={max} risk={a.risk_class} />)}
      </ol>
    </Card>
  )
}

function ContributionRow({ c, max, risk }: { c: Contribution; max: number; risk: string }) {
  const towards = c.shap >= 0
  return (
    <li className={styles.contrib}>
      <div className={styles.contribText}>
        <span className={styles.contribFact}>
          {featureLabel(c.feature)} <span className={styles.contribValue}>{featureValue(c.feature, c.value)}</span>
        </span>
        <span className={towards ? styles.towards : styles.away}>
          {towards ? '▲' : '▼'} {towards ? A.towards(risk) : A.away(risk)}
        </span>
      </div>
      <span className={styles.contribTrack} aria-hidden>
        <span className={towards ? styles.contribPos : styles.contribNeg}
              style={{ width: `${(Math.abs(c.shap) / max) * 50}%` }} />
      </span>
    </li>
  )
}

function Facts({ a, interviewId }: { a: AssessmentT; interviewId: number }) {
  const { heard, notStated, fromForm } = extractedFacts(a.extracted, a.applicant_form)
  return (
    <Card title={A.facts} actions={<a href={paths.review(interviewId)} className="btn btn-quiet btn-sm">{A.compare}</a>}>
      <dl className={styles.facts}>
        {heard.map((f) => (
          <div key={f.label} className={styles.fact}>
            <dt>{f.label}</dt>
            <dd>{f.value}</dd>
          </div>
        ))}
      </dl>
      {notStated.length > 0 && <p className={styles.notStated}><strong>{A.notStated}</strong> {notStated.join(', ')}.</p>}
      {fromForm.length > 0 && (
        <p className={styles.notStated}>
          <strong>{A.fromForm}</strong> {fromForm.map((f) => `${f.label} ${f.value}`).join(', ')}.
        </p>
      )}
    </Card>
  )
}

/** What was said, with the recordings, kept beside the result for a last check. */
function Transcripts({ interview }: { interview: InterviewState }) {
  const qs = useQuestions(interview.question_set)
  const lang = interview.language === 'en' ? 'en' : 'ki'
  return (
    <details className={`card ${styles.transcripts}`}>
      <summary className={styles.transcriptsSummary}>
        <Icon name="wave" /> <span>{A.transcripts}</span>
        <span className="subtle small">{interview.responses.length}</span>
        <Icon name="chevronDown" className={styles.chevron} />
      </summary>
      <p className="muted small">{A.transcriptsLead}</p>
      <ol className={styles.transcriptList}>
        {interview.responses.map((r) => {
          const q = qs.questions?.find((x) => x.order === r.sentence_no)
          return (
            <li key={r.id} className={styles.transcriptItem}>
              <div className={styles.transcriptHead}>
                <span className="subtle small">{t.review.question(r.sentence_no, domainLabel(r.domain))}</span>
                {r.source === 'typed' ? <TypedBadge /> : <StatusBadge status={r.status} />}
              </div>
              {q && <p className={styles.transcriptQ}>{q.text_en}</p>}
              <p lang={lang} className={styles.transcriptA}>{r.transcript?.trim() || <span className="muted">{t.review.noTranscript}</span>}</p>
              {r.source === 'audio' && <ReplayButton responseId={r.id} className="btn btn-secondary btn-sm" />}
            </li>
          )
        })}
      </ol>
    </details>
  )
}

// --- Decision ----------------------------------------------------------------------------

function DecisionPanel({ interview, a, close, name, onDecided }: {
  interview: InterviewState; a: AssessmentT; close: Closeness; name: string; onDecided: () => Promise<void>
}) {
  const practice = interview.mode === 'practice'
  const reduced = useReducedMotion()
  return (
    <section className={styles.decision} aria-label={D.eyebrow}>
      <div className={styles.decisionHead}>
        <p className="eyebrow">{practice ? D.eyebrowPractice : D.eyebrow}</p>
        {practice && <PracticeBadge />}
      </div>
      <AnimatePresence mode="wait" initial={false}>
        <m.div key={interview.decision ? 'recorded' : 'form'} {...fade(reduced)}>
          {interview.decision
            ? <RecordedDecision d={interview.decision} risk={a.risk_class} borderline={close.borderline} practice={practice} />
            : <DecisionForm interviewId={interview.id} name={name} practice={practice} onDecided={onDecided}
                            requested={a.comparator?.amount_requested_kes ?? null}
                            hasApplication={!!interview.application_id} />}
        </m.div>
      </AnimatePresence>
    </section>
  )
}

export function RecordedDecision({ d, risk, borderline, practice }: {
  d: Decision; risk: string; borderline: boolean; practice: boolean
}) {
  const outcome: Outcome = d.outcome ?? d.decision
  const notes = d.officer_notes ?? d.note
  return (
    <div className={styles.recorded}>
      <p className={styles.decided}>
        <Icon name="check" size={22} /> {practice && D.practicePrefix}{D.outcomes[outcome]}
      </p>
      <div className={styles.badgeRow}>
        <OutcomeBadge outcome={outcome} />
        {d.approved_amount_kes ? <Badge tone="neutral">{D.approvedAmount(d.approved_amount_kes)}</Badge> : null}
        {d.guarantors_required ? <Badge tone="medium">{D.guarantorsRequired(d.guarantors_required)}</Badge> : null}
      </div>
      {practice && <p className="muted">{D.practiceNote}</p>}
      {d.member_message && (
        <div className={styles.quoteBlock}>
          <p className={styles.quoteLabel}>{D.memberMessage}</p>
          <blockquote className={styles.note}>{d.member_message}</blockquote>
        </div>
      )}
      {notes && (
        <div className={styles.quoteBlock}>
          <p className={styles.quoteLabel}>{D.officerNotes}</p>
          <blockquote className={styles.note}>{notes}</blockquote>
        </div>
      )}
      <p className="muted small">{D.recordedAt(formatDateTime(d.created_at))}{d.decided_by && <> {D.by(d.decided_by)}</>}</p>
      {!agrees(risk, borderline, outcome) && <p className={styles.differs}><Icon name="info" size={16} /> {D.differs}</p>}
    </div>
  )
}

export function DecisionForm({ interviewId, name, practice, onDecided, requested, hasApplication }: {
  interviewId: number; name: string; practice: boolean; onDecided: () => Promise<void>
  requested: number | null; hasApplication: boolean
}) {
  const toast = useToast()
  const [draft, setDraft] = useState<DecisionDraft>(EMPTY_DECISION)
  const [tried, setTried] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const errors = tried ? decisionErrors(draft, hasApplication ? requested : null) : {}
  const set = <K extends keyof DecisionDraft>(k: K, v: DecisionDraft[K]) => { setDraft((d) => ({ ...d, [k]: v })); setConfirming(false) }

  function review(e: FormEvent) {
    e.preventDefault()
    setTried(true)
    if (Object.keys(decisionErrors(draft, hasApplication ? requested : null)).length) return
    setConfirming(true)
  }

  async function record() {
    setSaving(true)
    setError(null)
    try {
      await api.decide(interviewId, decisionBody(draft))
      toast(D.recorded)
      await onDecided()
    } catch (e) {
      setError(e as ApiError)
      setSaving(false)
      setConfirming(false)
    }
  }

  const label = draft.outcome ? D.outcomes[draft.outcome] : ''
  return (
    <form className={styles.form} onSubmit={review} noValidate>
      <fieldset className={styles.outcomes} aria-describedby={errors.outcome ? 'outcome-error' : undefined}>
        <legend className="field-label">{D.choose}</legend>
        {outcomeOptions(hasApplication).map(({ outcome, available }) => (
          <label key={outcome} className={cx('choice', styles.outcome, !available && styles.outcomeOff)}>
            <input type="radio" name="outcome" value={outcome} checked={draft.outcome === outcome}
                   disabled={!available || saving} onChange={() => set('outcome', outcome)} />
            <span className={styles.outcomeText}>
              <span className={styles.outcomeTitle}>{D.outcomes[outcome]}</span>
              <span className="subtle small">
                {!available ? D.needsApplication
                  : outcome === 'approve' ? D.outcomeHints.approve(requested) : D.outcomeHints[outcome]}
              </span>
            </span>
          </label>
        ))}
        {errors.outcome && <p id="outcome-error" className="field-error">{errors.outcome}</p>}
      </fieldset>

      {draft.outcome === 'approve_with_guarantor' && (
        <Field id="dec-guarantors" label={D.guarantorsLabel} error={errors.guarantors}>
          {(p) => <input {...p} className={`input num ${styles.short}`} type="number" min={1} max={10} step={1}
                         value={draft.guarantors} placeholder={String(DEFAULT_GUARANTORS)}
                         onChange={(e) => set('guarantors', e.target.value)} />}
        </Field>
      )}
      {draft.outcome === 'approve_reduced' && requested !== null && (
        <Field id="dec-amount" label={D.reducedLabel} hint={D.reducedHint(requested)} error={errors.reducedAmount}>
          {(p) => <input {...p} className={`input num ${styles.short}`} inputMode="numeric" value={draft.reducedAmount}
                         onChange={(e) => set('reducedAmount', e.target.value)} />}
        </Field>
      )}

      <div className={styles.texts}>
        <Field id="dec-notes" label={D.notesLabel} hint={D.notesHint} error={errors.officerNotes} optional>
          {(p) => <textarea {...p} className="textarea" rows={3} maxLength={2000} value={draft.officerNotes} disabled={saving}
                            placeholder={D.notesPlaceholder} onChange={(e) => set('officerNotes', e.target.value)} />}
        </Field>
        <Field id="dec-message" label={D.messageLabel} hint={D.messageHint} error={errors.memberMessage} optional>
          {(p) => <textarea {...p} className="textarea" rows={3} maxLength={1000} value={draft.memberMessage} disabled={saving}
                            onChange={(e) => set('memberMessage', e.target.value)} />}
        </Field>
      </div>

      {confirming && draft.outcome ? (
        <div className={styles.confirm} role="alertdialog" aria-label={D.confirm}>
          <p>{D.confirmText(label, practice, name)}</p>
          {draft.outcome === 'approve_reduced' && <p className="muted">{D.approvedAmount(Number(draft.reducedAmount.replace(/\D/g, '')))}</p>}
          {draft.outcome === 'approve_with_guarantor' && <p className="muted">{D.guarantorsRequired(Number(draft.guarantors))}</p>}
          <div className={styles.confirmActions}>
            <button type="button" className="btn btn-quiet" onClick={() => setConfirming(false)} disabled={saving}>{D.goBack}</button>
            <button type="button" className="btn btn-primary" onClick={record} disabled={saving} autoFocus>
              {saving && <span className="spinner" aria-hidden />} {D.confirm}
            </button>
          </div>
        </div>
      ) : (
        <button type="submit" className="btn btn-primary btn-large">{D.record(practice)}</button>
      )}
      {error && <ErrorNotice doing={D.notRecorded} error={error} onRetry={record} />}
      {requested !== null && <p className="subtle small">{t.applications.requested}: {formatKes(requested)}</p>}
    </form>
  )
}
