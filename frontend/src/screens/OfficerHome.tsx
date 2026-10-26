import { m } from 'motion/react'
import { useCallback } from 'react'
import { api } from '../api/client'
import type { ApplicationSummary, InterviewSummary } from '../api/types'
import { ApplicationStatusBadge, RiskBadge } from '../components/Badges'
import { Icon } from '../components/Icon'
import { ErrorNotice } from '../components/Notice'
import { Badge, Card, EmptyState, Kpi, PageHeader, PracticeBadge, SkeletonList } from '../components/ui'
import { useLoad } from '../hooks/useLoad'
import { useAuth } from '../lib/auth'
import { applicantName, formatDateTime, formatKes, isSameDay } from '../lib/format'
import { fadeUp, useReducedMotion } from '../lib/motion'
import { paths } from '../lib/router'
import { interviewDestination } from '../lib/selectors'
import { interviewStatusText, interviewTone } from '../lib/status'
import { t } from '../strings'
import styles from './OfficerHome.module.css'

const H = t.officerHome

export function OfficerHome() {
  const { user } = useAuth()
  const reduced = useReducedMotion()
  const load = useCallback(() => Promise.all([
    api.interviews(),
    api.applications({ status: 'assessed' }),
    api.applications({ status: 'guarantor_submitted' }),
  ]), [])
  const { data, error, reload } = useLoad(load)
  const [interviews, awaiting, guarantors] = data ?? [null, null, null]
  const open = interviews?.filter((iv) => iv.status === 'open') ?? []
  const today = interviews?.filter((iv) => isSameDay(iv.created_at)) ?? []

  return (
    <>
      <PageHeader title={H.greeting(user?.username ?? '')} lead={H.lead} />

      <m.a href={paths.start()} className={styles.start} {...fadeUp(reduced, 0.05)}>
        <span className={styles.startIcon}><Icon name="mic" size={28} /></span>
        <span className={styles.startText}>
          <span className={styles.startTitle}>{H.start}</span>
          <span className={styles.startHint}>{H.startHint}</span>
        </span>
        <Icon name="arrowRight" size={24} className={styles.startArrow} />
      </m.a>

      {error && <ErrorNotice doing={t.interviews.loadFailed} error={error} onRetry={reload} />}

      <div className={styles.kpis}>
        <Kpi label={H.statOpen} icon="mic" tone="wait" value={interviews ? open.length : '–'} href={paths.interviews()} />
        <Kpi label={H.statAwaiting} icon="scale" tone="attention" value={awaiting ? awaiting.length : '–'}
             href={paths.applications('assessed')} />
        <Kpi label={H.statGuarantors} icon="users" tone="medium" value={guarantors ? guarantors.length : '–'}
             href={paths.applications('guarantor_submitted')} />
      </div>

      <div className={styles.grid}>
        <Card title={H.today} delay={0.05} actions={<a href={paths.interviews()} className="btn btn-quiet btn-sm">{H.viewAll}</a>}>
          {!interviews ? <SkeletonList rows={3} what={H.today} />
            : today.length ? <InterviewRows items={today} />
              : <EmptyState icon="clock" title={H.todayEmpty} />}
        </Card>
        <Card title={H.pending} delay={0.1} actions={<a href={paths.interviews()} className="btn btn-quiet btn-sm">{H.viewAll}</a>}>
          {!interviews ? <SkeletonList rows={3} what={H.pending} />
            : open.length ? <InterviewRows items={open.slice(0, 6)} />
              : <EmptyState icon="mic" title={H.pendingEmpty} />}
        </Card>
        <Card title={H.awaitingDecision} delay={0.15}
              actions={<a href={paths.applications('assessed')} className="btn btn-quiet btn-sm">{H.viewAll}</a>}>
          {!awaiting ? <SkeletonList rows={3} what={H.awaitingDecision} />
            : awaiting.length ? <ApplicationRows items={awaiting.slice(0, 6)} action={H.decide} />
              : <EmptyState icon="scale" title={H.awaitingEmpty} />}
        </Card>
        <Card title={H.guarantors} delay={0.2}
              actions={<a href={paths.applications('guarantor_submitted')} className="btn btn-quiet btn-sm">{H.viewAll}</a>}>
          {!guarantors ? <SkeletonList rows={3} what={H.guarantors} />
            : guarantors.length ? <ApplicationRows items={guarantors.slice(0, 6)} action={H.verify} />
              : <EmptyState icon="users" title={H.guarantorsEmpty} />}
        </Card>
      </div>
    </>
  )
}

function InterviewRows({ items }: { items: InterviewSummary[] }) {
  return (
    <ul className={styles.rows}>
      {items.map((iv) => (
        <li key={iv.id}>
          <a href={interviewDestination(iv)} className={styles.row}>
            <span className={styles.rowMain}>
              <span className={styles.rowTitle}>
                {applicantName(iv.applicant_name)}
                {iv.mode === 'practice' && <PracticeBadge />}
              </span>
              <span className={styles.rowMeta}>
                {t.interviews.ref(iv.id)} · {formatDateTime(iv.created_at)} · {H.answers(iv.responses_recorded, iv.questions_total)}
              </span>
              <span className={styles.meter} aria-hidden>
                <span style={{ width: `${(100 * iv.responses_recorded) / iv.questions_total}%` }} />
              </span>
            </span>
            <span className={styles.rowEnd}>
              {iv.risk_class ? <RiskBadge risk={iv.risk_class} /> : <Badge tone={interviewTone(iv)}>{interviewStatusText(iv)}</Badge>}
              <Icon name="chevronRight" size={18} />
            </span>
          </a>
        </li>
      ))}
    </ul>
  )
}

function ApplicationRows({ items, action }: { items: ApplicationSummary[]; action: string }) {
  return (
    <ul className={styles.rows}>
      {items.map((a) => (
        <li key={a.id}>
          <a href={a.status === 'assessed' && a.interview_id ? paths.assessment(a.interview_id) : paths.application(a.id)}
             className={styles.row}>
            <span className={styles.rowMain}>
              <span className={styles.rowTitle}>
                {a.member_name}
                {a.mode === 'practice' && <PracticeBadge />}
              </span>
              <span className={styles.rowMeta}>
                {t.applications.detailTitle(a.id)} · {a.member_no} · {formatKes(a.amount_requested_kes)}
              </span>
            </span>
            <span className={styles.rowEnd}>
              {a.risk_class && <RiskBadge risk={a.risk_class} />}
              <ApplicationStatusBadge status={a.status} />
              <span className={styles.rowAction}>{action}</span>
            </span>
          </a>
        </li>
      ))}
    </ul>
  )
}
