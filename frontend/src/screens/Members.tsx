import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { Icon } from '../components/Icon'
import { ErrorNotice } from '../components/Notice'
import { Badge, Card, EmptyState, PageHeader, SkeletonList } from '../components/ui'
import { useLoad } from '../hooks/useLoad'
import { formatDay } from '../lib/format'
import { paths } from '../lib/router'
import { t } from '../strings'
import styles from './Tables.module.css'

const M = t.members

export function Members() {
  const [q, setQ] = useState('')
  const [term, setTerm] = useState('')
  useEffect(() => {
    const id = window.setTimeout(() => setTerm(q.trim()), 250)
    return () => window.clearTimeout(id)
  }, [q])
  // The server searches names and member numbers.
  const load = useCallback(() => api.members(term || undefined, 500), [term])
  const { data, error, reload } = useLoad(load)

  return (
    <>
      <PageHeader title={M.title} lead={M.lead}
                  actions={<a href={paths.start()} className="btn btn-accent"><Icon name="mic" /> {t.nav.startInterview}</a>} />
      {error && <ErrorNotice doing={M.loadFailed} error={error} onRetry={reload} />}
      <Card>
        <div className={styles.toolbar}>
          <div className={styles.searchField}>
            <Icon name="search" className={styles.searchIcon} />
            <input type="search" className="input" value={q} onChange={(e) => setQ(e.target.value)}
                   aria-label={M.searchLabel} placeholder={M.searchLabel} />
          </div>
        </div>
        {!data && !error && <SkeletonList what={M.title} />}
        {data && data.length === 0 && (term
          ? <EmptyState icon="search" title={M.noMatch} />
          : <EmptyState icon="users" title={M.empty}>{M.emptyBody}</EmptyState>)}
        {data && data.length > 0 && (
          <div className={`table-wrap ${styles.stack}`}>
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">{M.name}</th>
                  <th scope="col">{M.memberNo}</th>
                  <th scope="col">{M.phone}</th>
                  <th scope="col">{M.joined}</th>
                  <th scope="col">{M.login}</th>
                  <th scope="col"><span className="visually-hidden">{M.startInterview}</span></th>
                </tr>
              </thead>
              <tbody>
                {data.map((m) => (
                  <tr key={m.id}>
                    <td><a href={paths.member(m.id)} className="row-link">{m.full_name}</a></td>
                    <td className={styles.mono} data-label={M.memberNo}>{m.member_no}</td>
                    <td className="num" data-label={M.phone}>{m.phone ?? <span className="subtle">—</span>}</td>
                    <td className="num" data-label={M.joined}>{formatDay(m.joined_on)}</td>
                    <td data-label={M.login}>
                      {m.user_id ? <Badge tone="low" icon="check">{M.hasLogin}</Badge> : <Badge>{M.noLogin}</Badge>}
                    </td>
                    <td className="right">
                      <a href={paths.start(m.id)} className="btn btn-secondary btn-sm"><Icon name="mic" size={16} /> {M.startInterview}</a>
                    </td>
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
