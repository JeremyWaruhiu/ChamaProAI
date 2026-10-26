import { useCallback, useMemo, useState } from 'react'
import { api } from '../api/client'
import { RiskBadge } from '../components/Badges'
import { Icon } from '../components/Icon'
import { ErrorNotice } from '../components/Notice'
import { Badge, Card, EmptyState, PageHeader, PracticeBadge, SkeletonList } from '../components/ui'
import { useLoad } from '../hooks/useLoad'
import { applicantName, formatDate } from '../lib/format'
import { paths } from '../lib/router'
import { filterInterviews, interviewDestination, type InterviewFilter } from '../lib/selectors'
import { interviewStatusText, interviewTone } from '../lib/status'
import { t } from '../strings'
import styles from './Tables.module.css'

const T = t.interviews
type Filter = InterviewFilter

export function InterviewList() {
  const load = useCallback(() => api.interviews(), [])
  const { data, error, reload } = useLoad(load)
  const [q, setQ] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const shown = useMemo(() => (data ? filterInterviews(data, q, filter) : []), [data, q, filter])

  return (
    <>
      <PageHeader title={T.title} lead={T.lead}
                  actions={<a href={paths.start()} className="btn btn-accent"><Icon name="mic" /> {t.nav.startInterview}</a>} />
      {error && <ErrorNotice doing={T.loadFailed} error={error} onRetry={reload} />}
      <Card>
        <div className={styles.toolbar}>
          <div className={styles.searchField}>
            <Icon name="search" className={styles.searchIcon} />
            <input type="search" className="input" value={q} onChange={(e) => setQ(e.target.value)}
                   aria-label={T.searchLabel} placeholder={T.searchLabel} />
          </div>
          <div className={styles.segmented} role="group" aria-label={T.filterStatus}>
            {(Object.keys(T.filters) as Filter[]).map((f) => (
              <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}>{T.filters[f]}</button>
            ))}
          </div>
        </div>
        {!data && !error && <SkeletonList what={T.title} />}
        {data && data.length === 0 && (
          <EmptyState icon="mic" title={T.empty} action={<a href={paths.start()} className="btn btn-primary">{t.nav.startInterview}</a>}>
            {T.emptyBody}
          </EmptyState>
        )}
        {data && data.length > 0 && shown.length === 0 && <EmptyState icon="search" title={T.noMatch} />}
        {shown.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">{T.applicant}</th>
                  <th scope="col">{T.date}</th>
                  <th scope="col">{T.answers}</th>
                  <th scope="col">{T.status}</th>
                  <th scope="col">{T.riskClass}</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((iv) => (
                  <tr key={iv.id}>
                    <td>
                      <a href={interviewDestination(iv)} className="row-link">{applicantName(iv.applicant_name)}</a>
                      <div className={styles.sub}>
                        {T.ref(iv.id)}
                        {iv.language === 'en' && <Badge>{t.common.english}</Badge>}
                        {iv.mode === 'practice' && <PracticeBadge />}
                      </div>
                    </td>
                    <td className="num">{formatDate(iv.created_at)}</td>
                    <td>
                      <span className="num"><strong>{iv.responses_recorded}</strong> <span className="subtle">/ {iv.questions_total}</span></span>
                      <span className={styles.meter} aria-hidden>
                        <span style={{ width: `${(100 * iv.responses_recorded) / iv.questions_total}%` }} />
                      </span>
                    </td>
                    <td><Badge tone={interviewTone(iv)}>{interviewStatusText(iv)}</Badge></td>
                    <td>{iv.risk_class ? <RiskBadge risk={iv.risk_class} /> : <span className="subtle">{t.risk.notAssessed}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && shown.length > 0 && <p className={styles.count}>{t.common.showing(shown.length, data.length)}</p>}
      </Card>
    </>
  )
}
