import { m } from 'motion/react'
import { useCallback } from 'react'
import { api } from '../api/client'
import type { MyApplicationSummary } from '../api/types'
import { Icon } from '../components/Icon'
import { ErrorNotice } from '../components/Notice'
import { Badge, EmptyState, PageHeader, PracticeBadge, SkeletonList } from '../components/ui'
import { useLoad } from '../hooks/useLoad'
import { formatDate } from '../lib/format'
import { fadeUp, stagger, useReducedMotion } from '../lib/motion'
import { paths } from '../lib/router'
import { STATUS_TONE, memberStages } from '../lib/status'
import { t } from '../strings'
import styles from './Member.module.css'

const Y = t.my

export function MyApplications() {
  const load = useCallback(() => api.myApplications(), [])
  const { data, error, reload } = useLoad(load)
  const reduced = useReducedMotion()

  return (
    <>
      <PageHeader title={Y.title} lead={Y.lead} />
      {error && <ErrorNotice doing={Y.loadFailed} error={error} onRetry={reload} />}
      {!data && !error && <SkeletonList rows={3} what={Y.title} />}
      {data?.length === 0 && <div className="card"><EmptyState icon="file" title={Y.empty}>{Y.emptyBody}</EmptyState></div>}
      {data && data.length > 0 && (
        <ul className={styles.list}>
          {data.map((a, i) => (
            <m.li key={a.id} {...fadeUp(reduced, stagger(reduced, i, 0.06))}>
              <ApplicationCard a={a} />
            </m.li>
          ))}
        </ul>
      )}
    </>
  )
}

function ApplicationCard({ a }: { a: MyApplicationSummary }) {
  const stages = memberStages(a.status)
  const here = stages.findIndex((s) => s.state === 'current' || s.state === 'failed')
  return (
    <a href={paths.myApplication(a.id)} className={`card ${styles.appCard}`}>
      <div className={styles.appTop}>
        <div>
          <p className={styles.appTitle}>{a.purpose}</p>
          <p className="subtle small">{Y.amountFor(a.amount_requested_kes, a.term_months)} · {Y.applied(formatDate(a.created_at))}</p>
        </div>
        <Icon name="chevronRight" className={styles.chev} />
      </div>
      <div className={styles.badges}>
        <Badge tone={STATUS_TONE[a.status]}>{a.status_label}</Badge>
        {a.mode === 'practice' && <PracticeBadge />}
      </div>
      <ol className={styles.dots} aria-label={Y.progress}>
        {stages.map((s, i) => (
          <li key={s.key} className={styles[`dot-${s.state}`]} aria-current={i === here ? 'step' : undefined}>
            <span className="visually-hidden">{s.label}, {Y.stageState[s.state]}</span>
          </li>
        ))}
      </ol>
      <p className={styles.dotsLabel} aria-hidden>{here >= 0 ? stages[here].label : stages[stages.length - 1].label}</p>
    </a>
  )
}
