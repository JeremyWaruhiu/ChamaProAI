import { useCallback } from 'react'
import { api } from '../api/client'
import { ApplicationStatusBadge, OutcomeBadge, RiskBadge } from '../components/Badges'
import { Icon } from '../components/Icon'
import { ErrorNotice } from '../components/Notice'
import { Card, DetailList, EmptyState, PageHeader, PracticeBadge, SkeletonPage } from '../components/ui'
import { useLoad } from '../hooks/useLoad'
import { formatDate, formatDay, formatKes } from '../lib/format'
import { paths } from '../lib/router'
import { t } from '../strings'
import styles from './Tables.module.css'

const M = t.members

export function MemberDetail({ id }: { id: number }) {
  const load = useCallback(() => Promise.all([api.member(id), api.applications({ member_id: id })]), [id])
  const { data, error, reload } = useLoad(load)
  if (error) return <ErrorNotice doing={M.detailFailed} error={error} onRetry={reload} />
  if (!data) return <SkeletonPage what={M.title} />
  const [member, apps] = data

  return (
    <>
      <PageHeader eyebrow={<a href={paths.members()}>{M.title}</a>} title={member.full_name} lead={member.member_no}
                  actions={<a href={paths.start(member.id)} className="btn btn-accent"><Icon name="mic" /> {M.startInterview}</a>} />
      <div className={styles.detailGrid}>
        <Card title={M.details}>
          <DetailList items={[
            [M.memberNo, member.member_no],
            [M.phone, member.phone ?? '—'],
            [M.joined, formatDay(member.joined_on)],
            [M.login, member.user_id ? M.hasLogin : M.noLogin],
          ]} />
        </Card>
        <Card title={M.applications} delay={0.05}>
          {apps.length === 0 ? <EmptyState icon="file" title={M.noApplications} /> : (
            <ul className={styles.cardList}>
              {apps.map((a) => (
                <li key={a.id}>
                  <a href={paths.application(a.id)} className={styles.cardLink}>
                    <span>
                      <strong>{t.applications.detailTitle(a.id)}</strong> · {formatKes(a.amount_requested_kes)}
                      <span className={styles.sub}>{formatDate(a.created_at)}{a.mode === 'practice' && <PracticeBadge />}</span>
                    </span>
                    <span className={styles.badges}>
                      {a.risk_class && <RiskBadge risk={a.risk_class} />}
                      {a.outcome ? <OutcomeBadge outcome={a.outcome} /> : <ApplicationStatusBadge status={a.status} />}
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  )
}
