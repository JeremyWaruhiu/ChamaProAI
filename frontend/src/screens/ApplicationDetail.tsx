import { useCallback, useState } from 'react'
import { ApiError, api } from '../api/client'
import type { ApplicationDetail as Detail, Guarantor } from '../api/types'
import { ApplicationStatusBadge, OutcomeBadge, RiskBadge } from '../components/Badges'
import { Icon } from '../components/Icon'
import { ErrorNotice } from '../components/Notice'
import { useToast } from '../components/toastContext'
import { Badge, Card, DetailList, EmptyState, Modal, PageHeader, PracticeBadge, SkeletonPage, Timeline } from '../components/ui'
import { useLoad } from '../hooks/useLoad'
import { formatDateTime, formatDay, formatKes } from '../lib/format'
import { paths } from '../lib/router'
import { statusLabel, type Tone } from '../lib/status'
import { t } from '../strings'
import { ComparatorPanel } from './Assessment'
import styles from './ApplicationDetail.module.css'

const P = t.applications
const G_TONE: Record<Guarantor['status'], Tone> = { pending: 'wait', verified: 'low', rejected: 'high' }

export function ApplicationDetail({ id }: { id: number }) {
  const load = useCallback(() => api.application(id), [id])
  const { data: app, error, reload, setData } = useLoad(load)

  if (error) return <ErrorNotice doing={P.detailFailed} error={error} onRetry={reload} />
  if (!app) return <SkeletonPage what={P.detailTitle(id)} />
  const practice = app.mode === 'practice'

  return (
    <>
      <PageHeader eyebrow={<a href={paths.applications()} className={styles.back}><Icon name="arrowLeft" size={16} /> {P.title}</a>}
                  title={P.detailTitle(app.id)}
                  lead={<>{app.member.full_name} · {app.member_no} · {formatKes(app.amount_requested_kes)}</>}
                  badges={<><ApplicationStatusBadge status={app.status} />{practice && <PracticeBadge />}</>}
                  actions={<NextAction app={app} />} />

      <div className={styles.grid}>
        <div className={styles.main}>
          <Card title={P.summary}>
            <DetailList items={[
              [P.member, <a key="m" href={paths.member(app.member_id)}>{app.member.full_name} ({app.member_no})</a>],
              [P.memberSince, formatDay(app.member.joined_on)],
              [P.requested, `${formatKes(app.amount_requested_kes)} · ${t.common.months(app.term_months)}`],
              [P.purpose, app.purpose],
              [P.savings, formatKes(app.sacco_savings_kes)],
              [P.createdBy, `${app.created_by}, ${formatDateTime(app.created_at)}`],
            ]} />
          </Card>

          {app.comparator && <ComparatorPanel c={app.comparator} />}

          <Card title={P.decision} delay={0.05}>
            {app.decision ? (
              <div className={styles.decision}>
                <div className={styles.badges}>
                  <OutcomeBadge outcome={app.decision.outcome ?? app.decision.decision} />
                  {app.risk_class && <RiskBadge risk={app.risk_class} />}
                  {app.decision.approved_amount_kes ? <Badge>{t.decision.approvedAmount(app.decision.approved_amount_kes)}</Badge> : null}
                  {app.decision.guarantors_required ? <Badge tone="medium">{t.decision.guarantorsRequired(app.decision.guarantors_required)}</Badge> : null}
                </div>
                {app.decision.member_message && (
                  <p><span className="subtle small">{t.decision.memberMessage}:</span> {app.decision.member_message}</p>
                )}
                {(app.decision.officer_notes ?? app.decision.note) && (
                  <p><span className="subtle small">{t.decision.officerNotes}:</span> {app.decision.officer_notes ?? app.decision.note}</p>
                )}
                <p className="subtle small">
                  {t.decision.recordedAt(formatDateTime(app.decision.created_at))}
                  {app.decision.decided_by && <> {t.decision.by(app.decision.decided_by)}</>}
                </p>
              </div>
            ) : <p className="muted">{P.noDecision}</p>}
          </Card>

          <Guarantors app={app} onChanged={(g) => setData({ ...app, guarantors: app.guarantors.map((x) => (x.id === g.id ? g : x)) })}
                      reload={reload} />
        </div>

        <aside className={styles.aside}>
          <Card title={P.timeline} delay={0.1}>
            {app.timeline.length ? (
              <Timeline label={P.timeline} compact items={app.timeline.map((e, i) => ({
                key: `${e.status}-${i}`,
                title: statusLabel(e.status),
                meta: formatDateTime(e.at),
                state: i === app.timeline.length - 1 && !['approved', 'declined'].includes(e.status) ? 'current' : 'done',
              }))} />
            ) : <p className="muted">{P.timelineEmpty}</p>}
          </Card>
          <Card title={P.interview} delay={0.15}>
            {app.interview ? (
              <div className={styles.interview}>
                <p className={styles.badges}>
                  <span>{t.interviews.ref(app.interview.id)}</span>
                  <Badge>{app.interview.language === 'en' ? t.common.english : t.common.kikuyu}</Badge>
                  {app.interview.mode === 'practice' && <PracticeBadge />}
                </p>
                <a className="btn btn-secondary btn-block"
                   href={app.interview.status === 'assessed' ? paths.assessment(app.interview.id) : paths.record(app.interview.id)}>
                  {app.interview.status === 'assessed' ? P.openAssessment : P.continueInterview}
                </a>
              </div>
            ) : <p className="muted">{P.noInterview}</p>}
          </Card>
        </aside>
      </div>
    </>
  )
}

function NextAction({ app }: { app: Detail }) {
  if (app.status === 'assessed' && app.interview) {
    return <a className="btn btn-primary" href={paths.assessment(app.interview.id)}><Icon name="scale" /> {P.decideNow}</a>
  }
  if ((app.status === 'interview_pending' || app.status === 'draft') && app.interview) {
    return <a className="btn btn-primary" href={paths.record(app.interview.id)}><Icon name="mic" /> {P.continueInterview}</a>
  }
  if (app.status === 'interview_complete' && app.interview) {
    return <a className="btn btn-primary" href={paths.review(app.interview.id)}>{t.review.run}</a>
  }
  return null
}

function Guarantors({ app, onChanged, reload }: { app: Detail; onChanged: (g: Guarantor) => void; reload: () => Promise<void> }) {
  const toast = useToast()
  const [busy, setBusy] = useState<number | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [rejecting, setRejecting] = useState<Guarantor | null>(null)
  const [reason, setReason] = useState('')
  const reviewable = app.status === 'guarantor_submitted' || app.status === 'guarantor_required'
  const needed = app.decision?.guarantors_required ?? null

  async function act(g: Guarantor, verdict: 'verify' | 'reject') {
    setBusy(g.id)
    setError(null)
    try {
      const out = verdict === 'verify' ? await api.verifyGuarantor(g.id) : await api.rejectGuarantor(g.id, reason)
      onChanged(out)
      toast(verdict === 'verify' ? P.verified(g.full_name) : P.rejected(g.full_name))
      setRejecting(null)
      setReason('')
      await reload()   // the application may have moved on (approved, or asking for more)
    } catch (e) {
      setError(e as ApiError)
    } finally {
      setBusy(null)
    }
  }

  return (
    <Card title={P.guarantors} delay={0.1}>
      {app.status === 'guarantor_required' && needed && <p className={styles.waiting}><Icon name="clock" size={18} /> {P.guarantorsWaiting(needed)}</p>}
      {error && <ErrorNotice doing={P.reviewFailed} error={error} />}
      {app.guarantors.length === 0 ? <EmptyState icon="users" title={P.guarantorsEmpty} /> : (
        <ul className={styles.guarantors}>
          {app.guarantors.map((g) => (
            <li key={g.id} className={styles.guarantor}>
              <div className={styles.gHead}>
                <div>
                  <p className={styles.gName}>{g.full_name}</p>
                  <p className="subtle small">{g.member_no} · {g.relationship}</p>
                </div>
                <Badge tone={G_TONE[g.status]}>{P.guarantorStatus[g.status]}</Badge>
              </div>
              <DetailList items={[
                [P.guaranteed, formatKes(g.amount_guaranteed_kes)],
                [P.phone, <a key="p" href={`tel:${g.phone}`}>{g.phone}</a>],
              ]} />
              {g.verified_by && g.verified_at && (
                <p className="subtle small">{P.guarantorStatus[g.status]} {P.by(g.verified_by, formatDateTime(g.verified_at))}</p>
              )}
              {reviewable && g.status === 'pending' && (
                <div className={styles.gActions}>
                  <button type="button" className="btn btn-primary btn-sm" disabled={busy !== null} onClick={() => act(g, 'verify')}>
                    {busy === g.id ? <span className="spinner" aria-hidden /> : <Icon name="check" size={16} />} {P.verify}
                  </button>
                  <button type="button" className="btn btn-danger btn-sm" disabled={busy !== null} onClick={() => setRejecting(g)}>
                    <Icon name="x" size={16} /> {P.reject}
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      <Modal open={!!rejecting} title={rejecting ? P.rejectTitle(rejecting.full_name) : ''} onClose={() => setRejecting(null)}
             actions={<>
               <button type="button" className="btn btn-quiet" onClick={() => setRejecting(null)}>{t.common.cancel}</button>
               <button type="button" className="btn btn-danger" disabled={busy !== null} onClick={() => rejecting && act(rejecting, 'reject')}>
                 {busy !== null && <span className="spinner" aria-hidden />} {P.rejectConfirm}
               </button>
             </>}>
        <p>{P.rejectBody}</p>
        <label className="field">
          <span className="field-label">{P.rejectReason} <span className="subtle">{t.common.optional}</span></span>
          <textarea className="textarea" rows={3} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
      </Modal>
    </Card>
  )
}
