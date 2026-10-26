import { useCallback, useEffect, useState } from 'react'
import { ApiError, api } from '../api/client'
import type { AuditEntry, UserOut } from '../api/types'
import { ErrorNotice } from '../components/Notice'
import { Card, EmptyState, PageHeader, SkeletonList } from '../components/ui'
import { formatDateTime } from '../lib/format'
import { auditFilter } from '../lib/selectors'
import { t } from '../strings'
import styles from './Tables.module.css'

const L = t.audit
const PAGE = 50

const detailsText = (d: Record<string, unknown>) =>
  Object.entries(d).map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`).join(' · ')

export function AuditLog() {
  const [form, setForm] = useState({ actor: '', action: '', entity: '', since: '', until: '' })
  const [users, setUsers] = useState<UserOut[]>([])
  const [rows, setRows] = useState<AuditEntry[] | null>(null)
  const [more, setMore] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)
  const put = (k: keyof typeof form, v: string) => setForm((f) => ({ ...f, [k]: v }))

  useEffect(() => { api.users().then(setUsers, () => {}) }, [])

  const load = useCallback(async (offset: number) => {
    setError(null)
    try {
      const page = await api.audit({ ...auditFilter(form), limit: PAGE, offset })
      setRows((r) => (offset === 0 ? page : [...(r ?? []), ...page]))
      setMore(page.length === PAGE)
    } catch (e) {
      setError(e as ApiError)
    }
  }, [form])

  // oxlint-disable-next-line react/set-state-in-effect -- refetch from the top whenever a filter changes
  useEffect(() => { setRows(null); load(0) }, [load])

  return (
    <>
      <PageHeader title={L.title} lead={L.lead} />
      <Card>
        <div className={styles.filters}>
          <label className="field">
            <span className="field-label">{L.actor}</span>
            <select className="select" value={form.actor} onChange={(e) => put('actor', e.target.value)}>
              <option value="">{L.anyone}</option>
              {users.map((u) => <option key={u.id} value={u.id}>{u.username}</option>)}
            </select>
          </label>
          <label className="field">
            <span className="field-label">{L.action}</span>
            <select className="select" value={form.action} onChange={(e) => put('action', e.target.value)}>
              <option value="">{L.anyAction}</option>
              {Object.entries(L.actions).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <label className="field">
            <span className="field-label">{L.entity}</span>
            <select className="select" value={form.entity} onChange={(e) => put('entity', e.target.value)}>
              <option value="">{L.anyEntity}</option>
              {Object.entries(L.entities).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <label className="field">
            <span className="field-label">{L.since}</span>
            <input className="input" type="date" value={form.since} onChange={(e) => put('since', e.target.value)} />
          </label>
          <label className="field">
            <span className="field-label">{L.until}</span>
            <input className="input" type="date" value={form.until} onChange={(e) => put('until', e.target.value)} />
          </label>
        </div>

        {error && <ErrorNotice doing={L.loadFailed} error={error} onRetry={() => load(0)} />}
        {!rows && !error && <SkeletonList what={L.title} />}
        {rows && rows.length === 0 && <EmptyState icon="scroll" title={L.empty} />}
        {rows && rows.length > 0 && (
          <div className={`table-wrap ${styles.stack}`}>
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">{L.when}</th>
                  <th scope="col">{L.actor}</th>
                  <th scope="col">{L.action}</th>
                  <th scope="col">{L.record}</th>
                  <th scope="col">{L.details}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td className={`num ${styles.nowrap}`}>{formatDateTime(r.created_at)}</td>
                    <td data-label={L.actor}>{r.actor ?? <span className="subtle">{L.script}</span>}</td>
                    <td data-label={L.action}><code>{r.action}</code></td>
                    <td data-label={L.record}>{L.entities[r.entity] ?? r.entity}{r.entity_id ? ` ${r.entity_id}` : ''}</td>
                    <td data-label={L.details} className={styles.detailsCell}>{detailsText(r.details) || <span className="subtle">—</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {more && (
          <div className={styles.more}>
            <button type="button" className="btn btn-secondary" disabled={loadingMore}
                    onClick={async () => { setLoadingMore(true); await load(rows?.length ?? 0); setLoadingMore(false) }}>
              {loadingMore && <span className="spinner" aria-hidden />} {L.more}
            </button>
          </div>
        )}
      </Card>
    </>
  )
}
