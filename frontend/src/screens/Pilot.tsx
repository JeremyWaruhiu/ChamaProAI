import { useCallback } from 'react'
import { api } from '../api/client'
import { Icon } from '../components/Icon'
import { ErrorNotice } from '../components/Notice'
import { Badge, Card, DetailList, EmptyState, Kpi, PageHeader, SkeletonPage } from '../components/ui'
import { useLoad } from '../hooks/useLoad'
import { formatDateTime } from '../lib/format'
import { t } from '../strings'
import styles from './Pilot.module.css'
import tables from './Tables.module.css'

const P = t.pilot

export function Pilot() {
  const load = useCallback(() => api.pilot(), [])
  const { data: st, error, reload } = useLoad(load)
  if (error) return <ErrorNotice doing={P.loadFailed} error={error} onRetry={reload} />
  if (!st) return <SkeletonPage what={P.title} />
  const kik = st.practice_by_language.kik ?? 0
  const en = st.practice_by_language.en ?? 0
  const most = Math.max(kik, en, 1)
  return (
    <>
      <PageHeader title={P.title} lead={P.lead} />
      <div className={styles.kpis}>
        <Kpi icon="users" tone="low" label={P.volunteers} value={st.volunteers} />
        <Kpi icon="mic" tone="wait" label={P.practice} value={kik + en} />
        <Kpi icon="scale" tone="info" label={P.assessments} value={st.completed_assessments} />
        <Kpi icon="activity" tone="attention" label={P.answers} value={st.answers_total} />
      </div>
      <div className={styles.grid}>
        <Card title={P.byLanguage}>
          <ul className={styles.bars}>
            {([[t.common.kikuyu, kik], [t.common.english, en]] as const).map(([label, n]) => (
              <li key={label}>
                <span>{label}</span>
                <span className={styles.track}>{n > 0 && <span className={styles.fill} style={{ width: `${(100 * n) / most}%` }} />}</span>
                <span className="num">{n}</span>
              </li>
            ))}
          </ul>
        </Card>
        <Card title={P.sus} delay={0.05}>
          {st.sus_mean === null ? <p className="muted">{P.susNone}</p> : (
            <div className={styles.sus}>
              <p className={`${styles.susValue} num`} aria-label={`${P.susMean}: ${st.sus_mean}`}>{st.sus_mean}</p>
              <div>
                <p className={styles.susLabel}>{P.susMean}</p>
                <p className="subtle small">{P.susN(st.sus_n, st.sus_members)}</p>
              </div>
            </div>
          )}
        </Card>
        <Card title={P.settings} delay={0.1}>
          <DetailList items={[
            [P.signupOpen, <Badge key="s" tone={st.signup_open ? 'low' : 'neutral'}>{st.signup_open ? P.open : P.closed}</Badge>],
            [P.assessments, P.usedToday(st.used_today, st.daily_cap)],
            [P.practice, P.perMemberCap(st.per_member_cap)],
          ]} />
        </Card>
        <Card title={P.exports} delay={0.15}>
          <p className="muted small">{P.exportsLead}</p>
          <div className={styles.exports}>
            <a className="btn btn-secondary" href={api.pilotExportUrl('aggregates')} download><Icon name="download" /> {P.exportAggregates}</a>
            <a className="btn btn-secondary" href={api.pilotExportUrl('transcripts')} download><Icon name="download" /> {P.exportTranscripts}</a>
          </div>
        </Card>
      </div>
      <div className={styles.grid}>
        <Card title={P.perMember} delay={0.2}>
          {st.answers_per_member.length === 0 ? <EmptyState icon="mic" title={P.perMemberEmpty} /> : (
            <div className={`table-wrap ${tables.stack}`}>
              <table className="table">
                <thead><tr><th>{P.memberNo}</th><th>{P.answersCol}</th><th>{P.interviewsCol}</th></tr></thead>
                <tbody>
                  {st.answers_per_member.map((m) => (
                    <tr key={m.member_no}>
                      <td>{m.member_no}</td>
                      <td data-label={P.answersCol} className="num">{m.answers}</td>
                      <td data-label={P.interviewsCol} className="num">{m.interviews}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        <Card title={P.comments} delay={0.25}>
          {st.comments.length === 0 ? <EmptyState icon="file" title={P.commentsEmpty} /> : (
            <ul className={styles.comments}>
              {st.comments.map((c, i) => (
                <li key={i}>
                  <p className={styles.comment}>{c.comment}</p>
                  <p className="subtle small">{P.commentMeta(c.member_no, c.score, formatDateTime(c.created_at))}</p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  )
}
