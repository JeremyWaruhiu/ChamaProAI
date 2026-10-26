import { useCallback, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { ApplicationStatus } from '../api/types'
import { ApplicationStatusBadge, OutcomeBadge, RiskBadge } from '../components/Badges'
import { Icon } from '../components/Icon'
import { ErrorNotice } from '../components/Notice'
import { Card, EmptyState, PageHeader, PracticeBadge, SkeletonList } from '../components/ui'
import { useLoad } from '../hooks/useLoad'
import { formatDate, formatKes } from '../lib/format'
import { navigate, paths } from '../lib/router'
import { matchesApplication } from '../lib/selectors'
import { APPLICATION_STATUSES, statusLabel } from '../lib/status'
import { t } from '../strings'
import styles from './Tables.module.css'

const P = t.applications

const isStatus = (s: string | null): s is ApplicationStatus => !!s && (APPLICATION_STATUSES as string[]).includes(s)

export function Applications({ status }: { status: string | null }) {
  const filter = isStatus(status) ? status : undefined
  const load = useCallback(() => api.applications({ status: filter, limit: 500 }), [filter])
  const { data, error, reload } = useLoad(load)
  const [q, setQ] = useState('')
  const shown = useMemo(() => (data ?? []).filter((a) => matchesApplication(a, q)), [data, q])

  return (
    <>
      <PageHeader title={P.title} lead={P.lead}
                  actions={<a href={paths.start()} className="btn btn-accent"><Icon name="mic" /> {t.nav.startInterview}</a>} />
      {error && <ErrorNotice doing={P.loadFailed} error={error} onRetry={reload} />}
      <Card>
        <div className={styles.toolbar}>
          <div className={styles.searchField}>
            <Icon name="search" className={styles.searchIcon} />
            <input type="search" className="input" value={q} onChange={(e) => setQ(e.target.value)}
                   aria-label={P.searchLabel} placeholder={P.searchLabel} />
          </div>
          <label className={styles.select}>
            <span className="visually-hidden">{P.statusLabel}</span>
            <select className="select" value={filter ?? ''} onChange={(e) => navigate(paths.applications(e.target.value || null))}>
              <option value="">{P.allStatuses}</option>
              {APPLICATION_STATUSES.map((s) => <option key={s} value={s}>{statusLabel(s)}</option>)}
            </select>
          </label>
        </div>

        {!data && !error && <SkeletonList what={P.title} />}
        {data && data.length === 0 && (
          <EmptyState icon="file" title={filter ? P.noMatch : P.empty}>{filter ? null : P.emptyBody}</EmptyState>
        )}
        {data && data.length > 0 && shown.length === 0 && <EmptyState icon="search" title={P.noMatch} />}
        {shown.length > 0 && (
          <div className={`table-wrap ${styles.stack}`}>
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">{P.member}</th>
                  <th scope="col" className="right">{P.amount}</th>
                  <th scope="col">{P.status}</th>
                  <th scope="col">{P.risk}</th>
                  <th scope="col">{P.outcome}</th>
                  <th scope="col">{P.updated}</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((a) => (
                  <tr key={a.id}>
                    <td>
                      <a href={paths.application(a.id)} className="row-link" aria-label={`${P.open(a.id)}: ${a.member_name}`}>
                        {a.member_name}
                      </a>
                      <div className={styles.sub}>
                        {P.detailTitle(a.id)} · {a.member_no}
                        {a.mode === 'practice' && <PracticeBadge />}
                      </div>
                    </td>
                    <td className="right num" data-label={P.amount}>
                      {formatKes(a.amount_requested_kes)}
                      <div className={styles.sub}>{t.common.months(a.term_months)}</div>
                    </td>
                    <td data-label={P.status}><ApplicationStatusBadge status={a.status} /></td>
                    <td data-label={P.risk}>{a.risk_class ? <RiskBadge risk={a.risk_class} /> : <span className="subtle">—</span>}</td>
                    <td data-label={P.outcome}>{a.outcome ? <OutcomeBadge outcome={a.outcome} /> : <span className="subtle">—</span>}</td>
                    <td className="num" data-label={P.updated}>{formatDate(a.updated_at)}</td>
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
