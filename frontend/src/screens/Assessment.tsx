import { useState } from 'react'
import { ApiError, api } from '../api/client'
import type { Assessment as AssessmentT, Contribution, Decision, DecisionValue, InterviewState } from '../api/types'
import { RiskBadge } from '../components/Badges'
import { ErrorNotice, Loading, Notice } from '../components/Notice'
import { Shell } from '../components/Shell'
import { useInterview } from '../hooks/useInterview'
import { extractedFacts, featureLabel, featureValue } from '../lib/features'
import { applicantName, formatDateTime, percent } from '../lib/format'
import {
  BORDERLINE_POINTS, DECISION_LABEL, RISK_MEANING, RISK_ORDER, closeness, recommendation, riskTone,
  type Closeness, type RiskClass,
} from '../lib/risk'
import { paths } from '../lib/router'
import styles from './Assessment.module.css'

const COMPLETENESS_WARNING = 0.8

export function Assessment({ id }: { id: number }) {
  const iv = useInterview(id)
  const data = iv.data
  const name = applicantName(data?.applicant.name)
  const a = data?.assessment

  return (
    <Shell title={data ? <>Assessment — <strong>{name}</strong></> : 'Assessment'} interviewId={id} step="assessment"
           aside={a && `Assessed ${formatDateTime(a.created_at)}`}>
      {iv.error && <ErrorNotice doing="Could not load this interview" error={iv.error} onRetry={iv.refresh} />}
      {!data && !iv.error && <Loading what="the assessment" />}

      {data && !a && (
        <Notice tone="info" title="This interview has not been assessed yet"
                action={<a className="btn btn-primary" href={paths.review(id)}>Go to transcript review</a>}>
          Review the transcripts first, then run the assessment from the review screen.
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
      <p className={styles.support}>
        <strong>Decision support only.</strong> The loan officer makes the decision.
      </p>

      {close.borderline && <Borderline close={close} />}

      <div className={styles.grid}>
        <div className={styles.left}>
          <RiskCard a={a} />
          <Probabilities a={a} />
          <Completeness a={a} />
        </div>
        <Contributions a={a} />
      </div>

      <Facts a={a} interviewId={interview.id} />

      <DecisionPanel interview={interview} a={a} close={close} name={name} onDecided={onDecided} />

      <p className={styles.audit}>
        Assessment {a.id} · recorded {formatDateTime(a.created_at)} · classifier {a.model_file}
        {' '}(<span title={a.model_sha256}>sha256 {a.model_sha256.slice(0, 12)}</span>)
        {' '}· extraction {a.extraction_model} · stored permanently and cannot be changed
      </p>
    </div>
  )
}

function Borderline({ close }: { close: Closeness }) {
  const [c1, p1] = close.first
  const [c2, p2] = close.second
  return (
    <div className={styles.borderline} role="alert">
      <p className={styles.borderlineTitle}>Borderline — refer to the loan committee</p>
      <p>
        The model could not clearly separate {c1} risk ({percent(p1)}) from {c2} risk ({percent(p2)}):
        they are {close.gapPoints} points apart, within the {BORDERLINE_POINTS}-point margin.
        Treat this as a close call, whatever the class shown below.
      </p>
    </div>
  )
}

function RiskCard({ a }: { a: AssessmentT }) {
  const tone = riskTone(a.risk_class)
  return (
    <section className={`${styles.risk} ${styles[tone]}`} aria-label="Model risk class">
      <p className="eyebrow">Model risk class</p>
      <p className={styles.riskClass}>{a.risk_class} risk</p>
      <p className={styles.meaning}>{RISK_MEANING[a.risk_class as RiskClass] ?? ''}</p>
      <p className={styles.riskProb}>Model probability {percent(a.probabilities[a.risk_class] ?? 0)}</p>
    </section>
  )
}

function Probabilities({ a }: { a: AssessmentT }) {
  const classes = [...RISK_ORDER.filter((c) => c in a.probabilities),
    ...Object.keys(a.probabilities).filter((c) => !RISK_ORDER.includes(c as RiskClass))]
  return (
    <section className={`card ${styles.panel}`} aria-label="Probabilities">
      <p className="eyebrow">How likely each class is</p>
      <ul className={styles.bars}>
        {classes.map((c) => {
          const p = a.probabilities[c]
          return (
            <li key={c} className={c === a.risk_class ? styles.predicted : undefined}>
              <span className={styles.barLabel}>{c}</span>
              <span className={styles.barTrack}>
                <span className={`${styles.barFill} ${styles[riskTone(c)]}`} style={{ width: `${p * 100}%` }} />
              </span>
              <span className={styles.barValue}>{(p * 100).toFixed(1)}%</span>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function Completeness({ a }: { a: AssessmentT }) {
  const low = a.extraction_completeness < COMPLETENESS_WARNING
  return (
    <section className={`card ${styles.panel}`} aria-label="Evidence completeness">
      <div className={styles.completenessHead}>
        <p className="eyebrow">Evidence completeness</p>
        <p className={styles.completenessValue}>{percent(a.extraction_completeness)}</p>
      </div>
      <span className={styles.meter}><span className={low ? styles.meterLow : undefined}
                                          style={{ width: `${a.extraction_completeness * 100}%` }} /></span>
      <p className="muted">{a.features_populated} of the {a.features_total} facts the model uses were available.</p>
      {low && (
        <Notice tone="warning" title="Less than 80% of the evidence was available">
          The model had to work without several facts. Treat this assessment with extra caution and check what the system heard below.
        </Notice>
      )}
    </section>
  )
}

function Contributions({ a }: { a: AssessmentT }) {
  if (typeof a.contributions === 'string') {
    return (
      <section className={`card ${styles.panel}`}>
        <p className="eyebrow">What moved this assessment</p>
        <Notice tone="warning" title="Explanations are not available for this assessment">{a.contributions}</Notice>
      </section>
    )
  }
  const max = Math.max(...a.contributions.map((c) => Math.abs(c.shap)), 1e-9)
  return (
    <section className={`card ${styles.panel}`} aria-label="Contributions">
      <p className="eyebrow">What moved this assessment</p>
      <p className={`muted ${styles.small}`}>
        The facts that weighed most, in order. Each pushed the model towards or away from <strong>{a.risk_class} risk</strong>.
      </p>
      <ol className={styles.contribs}>
        {a.contributions.map((c) => <ContributionRow key={c.feature} c={c} max={max} risk={a.risk_class} />)}
      </ol>
    </section>
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
          {towards ? '▲' : '▼'} made {risk} risk {towards ? 'more' : 'less'} likely
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
  const { heard, notStated } = extractedFacts(a.extracted)
  return (
    <section className={`card ${styles.panel}`} aria-label="Extracted facts">
      <div className={styles.factsHead}>
        <p className="eyebrow">What the system heard — the facts the score relied on</p>
        <a href={paths.review(interviewId)}>Compare with the transcripts</a>
      </div>
      <dl className={styles.facts}>
        {heard.map((f) => (
          <div key={f.label} className={styles.fact}>
            <dt>{f.label}</dt>
            <dd>{f.value}</dd>
          </div>
        ))}
      </dl>
      {notStated.length > 0 && (
        <p className={styles.notStated}><strong>Not stated in the interview:</strong> {notStated.join(', ')}.</p>
      )}
    </section>
  )
}

const DECISIONS: DecisionValue[] = ['approve', 'decline', 'refer']

/** Does the officer's decision follow the model's recommendation? */
function agrees(risk: string, borderline: boolean, d: DecisionValue): boolean {
  if (borderline || risk === 'Medium') return d === 'refer'
  if (risk === 'Low') return d === 'approve'
  if (risk === 'High') return d === 'decline' || d === 'refer'
  return false
}

function DecisionPanel({ interview, a, close, name, onDecided }: {
  interview: InterviewState; a: AssessmentT; close: Closeness; name: string; onDecided: () => Promise<void>
}) {
  return (
    <section className={styles.decision} aria-label="Model recommendation and officer decision">
      <div className={styles.side}>
        <p className="eyebrow">Model's recommendation</p>
        <RiskBadge risk={a.risk_class} />
        <p className={styles.recommendation}>{recommendation(a.risk_class, close.borderline)}</p>
        <p className="muted">Advice from the scoring model. It does not decide.</p>
      </div>
      <div className={`${styles.side} ${styles.officer}`}>
        <p className="eyebrow">Loan officer's decision</p>
        {interview.decision
          ? <RecordedDecision d={interview.decision} risk={a.risk_class} borderline={close.borderline} />
          : <DecisionForm interviewId={interview.id} name={name} onDecided={onDecided} />}
      </div>
    </section>
  )
}

function RecordedDecision({ d, risk, borderline }: { d: Decision; risk: string; borderline: boolean }) {
  return (
    <>
      <p className={styles.decided}>{DECISION_LABEL[d.decision]}</p>
      {d.note && <blockquote className={styles.note}>{d.note}</blockquote>}
      <p className="muted">Recorded {formatDateTime(d.created_at)}. A recorded decision cannot be changed.</p>
      {!agrees(risk, borderline, d.decision) && (
        <p className={styles.differs}>This decision differs from the model's recommendation.</p>
      )}
    </>
  )
}

function DecisionForm({ interviewId, name, onDecided }: { interviewId: number; name: string; onDecided: () => Promise<void> }) {
  const [choice, setChoice] = useState<DecisionValue | null>(null)
  const [note, setNote] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  async function record() {
    if (!choice) return
    setSaving(true)
    setError(null)
    try {
      await api.decide(interviewId, choice, note)
      await onDecided()
    } catch (e) {
      setError(e as ApiError)
      setSaving(false)
      setConfirming(false)
    }
  }

  return (
    <div className={styles.form}>
      <div className={styles.choices} role="radiogroup" aria-label="Choose a decision">
        {DECISIONS.map((d) => (
          <button key={d} type="button" role="radio" aria-checked={choice === d}
                  className={`btn ${styles.choice}`} disabled={saving}
                  onClick={() => { setChoice(d); setConfirming(false) }}>
            {DECISION_LABEL[d]}
          </button>
        ))}
      </div>
      <label className="field-label" htmlFor="note">Reason or note <span className="muted">(optional)</span></label>
      <textarea id="note" className="textarea" rows={2} maxLength={2000} value={note} disabled={saving}
                placeholder="For example, what you checked or why you agree or disagree with the model"
                onChange={(e) => setNote(e.target.value)} />
      {confirming && choice ? (
        <div className={styles.confirm}>
          <p>Record <strong>{DECISION_LABEL[choice]}</strong> for {name}? A recorded decision cannot be changed.</p>
          <div className={styles.confirmActions}>
            <button className="btn btn-quiet" onClick={() => setConfirming(false)} disabled={saving}>Go back</button>
            <button className="btn btn-primary" onClick={record} disabled={saving}>
              {saving && <span className="spinner" aria-hidden />} Confirm decision
            </button>
          </div>
        </div>
      ) : (
        <button className="btn btn-primary btn-large" disabled={!choice} onClick={() => setConfirming(true)}>
          Record decision
        </button>
      )}
      {error && <ErrorNotice doing="The decision was not recorded" error={error} />}
    </div>
  )
}
