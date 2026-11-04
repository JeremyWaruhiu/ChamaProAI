import { useCallback, useState } from 'react'
import { ApiError, api, newIdempotencyKey } from '../api/client'
import type { AutomaticDecisionDetail, Outcome, PolicyCheck } from '../api/types'
import { ApplicationStatusBadge, OutcomeBadge, RiskBadge } from '../components/Badges'
import { Icon } from '../components/Icon'
import { ErrorNotice, Notice } from '../components/Notice'
import { useToast } from '../components/toastContext'
import { Badge, Card, DetailList, EmptyState, Modal, PageHeader, SkeletonList, SkeletonPage } from '../components/ui'
import { useLoad } from '../hooks/useLoad'
import { formatDateTime, formatKes } from '../lib/format'
import { paths } from '../lib/router'
import { outcomeLabel } from '../lib/status'
import { t } from '../strings'
import { Contributions } from './Assessment'
import styles from './Tables.module.css'

const P = t.automatic
const OUTCOMES: Outcome[] = ['approve', 'approve_reduced', 'refer', 'not_now']

export function AutomaticDecisions() {
  const [outcome, setOutcome] = useState('')
  const load = useCallback(() => api.automaticDecisions({ outcome, limit: 500 }), [outcome])
  const { data, error, reload } = useLoad(load)

  return (
    <>
      <PageHeader title={P.title} lead={P.lead} />
      {error && <ErrorNotice doing={P.loadFailed} error={error} onRetry={reload} />}
      <Card>
        <div className={styles.toolbar}>
          <label className={styles.select}>
            <span className="visually-hidden">{P.outcomeLabel}</span>
            <select className="select" value={outcome} onChange={(e) => setOutcome(e.target.value)}>
              <option value="">{P.allOutcomes}</option>
              {OUTCOMES.map((o) => <option key={o} value={o}>{outcomeLabel(o)}</option>)}
            </select>
          </label>
        </div>
        {!data && !error && <SkeletonList what={P.title} />}
        {data && data.length === 0 && <EmptyState icon="sparkle" title={P.empty}>{P.emptyBody}</EmptyState>}
        {data && data.length > 0 && (
          <div className={`table-wrap ${styles.stack}`}>
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">{P.member}</th>
                  <th scope="col" className="right">{P.amount}</th>
                  <th scope="col">{P.outcome}</th>
                  <th scope="col">{P.risk}</th>
                  <th scope="col">{P.version}</th>
                  <th scope="col">{P.when}</th>
                </tr>
              </thead>
              <tbody>
                {data.map((d) => (
                  <tr key={d.id}>
                    <td>
                      <a href={paths.decision(d.id)} className="row-link" aria-label={P.open(d.member_name)}>{d.member_name}</a>
                      <div className={styles.sub}>
                        {d.member_no}
                        {d.trigger === 'acceptance' && <span>· {P.acceptance}</span>}
                      </div>
                    </td>
                    <td className="right num" data-label={P.amount}>
                      {d.amount_kes !== null ? formatKes(d.amount_kes) : <span className="subtle">—</span>}
                      <div className={styles.sub}>{P.requested(formatKes(d.amount_requested_kes))}</div>
                    </td>
                    <td data-label={P.outcome}><OutcomeBadge outcome={d.outcome} /></td>
                    <td data-label={P.risk}><RiskBadge risk={d.risk_class} /></td>
                    <td data-label={P.version}><span className={styles.mono}>{d.policy_version}</span></td>
                    <td className="num" data-label={P.when}>{formatDateTime(d.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  )
}

function shown(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') return Number.isInteger(value) ? value.toLocaleString('en-KE') : String(value)
  return typeof value === 'string' ? value : JSON.stringify(value)
}

function CheckResult({ passed }: { passed: boolean | null }) {
  if (passed === null) return <Badge tone="neutral">{P.unknown}</Badge>
  return passed ? <Badge tone="low" icon="check">{P.pass}</Badge> : <Badge tone="high" icon="x">{P.fail}</Badge>
}

function CheckRow({ c }: { c: PolicyCheck }) {
  return (
    <tr>
      <td>{P.checkLabel[c.check] ?? c.check}</td>
      <td data-label={P.resultCol}><CheckResult passed={c.passed} /></td>
      <td data-label={P.valuesCol}>
        <span className={styles.mono}>
          {Object.entries(c.values).map(([k, v]) => `${k}: ${shown(v)}`).join('; ')}
        </span>
      </td>
    </tr>
  )
}

/** Everything about one decision that needs no action: exported for its test. */
export function DecisionBody({ d }: { d: AutomaticDecisionDetail }) {
  const checks = d.trace.checks ?? []
  const asked = d.trace.clarifications?.asked ?? []
  const answered = d.trace.clarifications?.answered ?? []
  const overrides = Object.entries(d.overrides)
  const R = P.summaryRows
  return (
    <>
      <Card title={P.summary}>
        <DetailList items={[
          [R.outcome, <OutcomeBadge key="o" outcome={d.outcome} />],
          [R.amount, d.amount_kes !== null ? formatKes(d.amount_kes) : '—'],
          [R.requested, formatKes(d.amount_requested_kes)],
          [R.term, P.months(d.trace.effective?.term_months)],
          [R.version, <span key="v" className={styles.mono}>{d.policy_version}</span>],
          [R.status, <ApplicationStatusBadge key="s" status={d.application_status} />],
          [R.told, d.member_message ?? '—'],
          [R.model, <span key="m" className={styles.mono}>{d.model_file} {d.model_sha256.slice(0, 12)}</span>],
          [P.probabilities, Object.entries(d.probabilities).map(([k, v]) => `${k} ${(v * 100).toFixed(1)}%`).join(', ')],
        ]} />
      </Card>
      <Card title={P.checks}>
        <div className={`table-wrap ${styles.stack}`}>
          <table className="table">
            <thead>
              <tr><th scope="col">{P.checkCol}</th><th scope="col">{P.resultCol}</th><th scope="col">{P.valuesCol}</th></tr>
            </thead>
            <tbody>{checks.map((c) => <CheckRow key={c.check} c={c} />)}</tbody>
          </table>
        </div>
      </Card>
      <Contributions a={{ contributions: d.contributions, risk_class: d.risk_class }} />
      <Card title={P.clarifications}>
        {asked.length === 0
          ? <p className="muted">{P.nothingAsked}</p>
          : <DetailList items={[[P.asked, asked.join(', ')], [P.answered, answered.join(', ') || '—']]} />}
        <h3 className="eyebrow">{P.overrides}</h3>
        {overrides.length === 0
          ? <p className="muted">{P.noOverrides}</p>
          : <DetailList items={overrides.map(([k, v]) => [k, shown(v)])} />}
      </Card>
      <Card title={P.provenance}>
        <DetailList items={Object.entries(d.provenance).map(([k, v]) => [k, P.provenanceLabel[v] ?? v])} />
      </Card>
    </>
  )
}

function ReverseCard({ d, onDone }: { d: AutomaticDecisionDetail; onDone: () => void }) {
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  // One key from opening the dialog, so a retry after a lost reply cannot do it twice.
  const [key, setKey] = useState(newIdempotencyKey)

  if (d.loan_status === 'reversed') return <Notice tone="info" title={P.reversed} />
  if (!d.reversible_until || d.loan_id === null) return null
  const loanId = d.loan_id

  async function reverse() {
    setBusy(true)
    setProblem(null)
    try {
      await api.reverseLoan(loanId, reason, key)
      toast(P.reverseDone)
      setOpen(false)
      onDone()
    } catch (e) {
      setProblem(e instanceof ApiError ? e.message : P.reverseFailed)
      // Refused, so nothing was done: the same key could not be replayed anyway.
      setKey(newIdempotencyKey())
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <p className="muted">{P.reverseUntil(formatDateTime(d.reversible_until))}</p>
      <button type="button" className="btn btn-danger" onClick={() => setOpen(true)}>
        <Icon name="x" size={16} /> {P.reverse}
      </button>
      <Modal open={open} title={P.reverseTitle} onClose={() => setOpen(false)}
             actions={<>
               <button type="button" className="btn btn-quiet" onClick={() => setOpen(false)}>{t.common.cancel}</button>
               <button type="button" className="btn btn-danger" disabled={busy || reason.trim().length < 3} onClick={reverse}>
                 {busy && <span className="spinner" aria-hidden />} {P.reverseConfirm}
               </button>
             </>}>
        <p>{P.reverseBody}</p>
        {problem && <Notice tone="error" title={P.reverseFailed}>{problem}</Notice>}
        <label className="field">
          <span className="field-label">{P.reverseReason}</span>
          <textarea className="textarea" rows={3} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
          <span className="subtle small">{P.reverseHint}</span>
        </label>
      </Modal>
    </Card>
  )
}

export function AutomaticDecisionPage({ id }: { id: number }) {
  const load = useCallback(() => api.automaticDecision(id), [id])
  const { data, error, reload } = useLoad(load)
  if (error && !data) return <ErrorNotice doing={P.loadFailed} error={error} onRetry={reload} />
  if (!data) return <SkeletonPage what={P.title} />
  return (
    <>
      <PageHeader eyebrow={<a href={paths.decisions()}>{P.back}</a>} title={P.title1(data.member_name)}
                  lead={`${data.member_no} · ${formatDateTime(data.created_at)}`}
                  badges={<RiskBadge risk={data.risk_class} />}
                  actions={<a href={paths.application(data.application_id)} className="btn btn-quiet"><Icon name="file" /> {P.application}</a>} />
      <ReverseCard d={data} onDone={reload} />
      <DecisionBody d={data} />
    </>
  )
}
