import { useCallback, useState, type FormEvent } from 'react'
import { ApiError, api } from '../api/client'
import type { EventBody, EventType, SaccoEvent } from '../api/types'
import { EventList } from '../components/EventList'
import { Icon } from '../components/Icon'
import { ErrorNotice } from '../components/Notice'
import { useToast } from '../components/toastContext'
import { Card, EmptyState, Field, Modal, PageHeader, SkeletonList } from '../components/ui'
import { useLoad } from '../hooks/useLoad'
import { todayYmd } from '../lib/format'
import { draftOf, eventErrors, type EventDraft as Draft } from '../lib/events'
import { paths } from '../lib/router'
import { t } from '../strings'
import styles from './Events.module.css'

const E = t.events
const TYPES: EventType[] = ['agm', 'member_meeting', 'training', 'loan_deadline', 'other']

export function Events() {
  const toast = useToast()
  const load = useCallback(() => api.events(), [])
  const { data, error, reload } = useLoad(load)
  const [editing, setEditing] = useState<SaccoEvent | 'new' | null>(null)
  const [removing, setRemoving] = useState<SaccoEvent | null>(null)
  const [removeError, setRemoveError] = useState<ApiError | null>(null)
  const [busy, setBusy] = useState(false)

  async function remove() {
    if (!removing) return
    setBusy(true)
    setRemoveError(null)
    try {
      await api.deleteEvent(removing.id)
      toast(E.removed)
      setRemoving(null)
      await reload()
    } catch (e) {
      setRemoveError(e as ApiError)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PageHeader title={E.title} lead={E.lead} actions={
        <button type="button" className="btn btn-primary" onClick={() => setEditing('new')}><Icon name="plus" /> {E.add}</button>
      } />
      {error && <ErrorNotice doing={E.loadFailed} error={error} onRetry={reload} />}
      {!data && !error && <SkeletonList rows={3} what={E.title} />}
      {data?.length === 0 && <div className="card"><EmptyState icon="calendar" title={E.empty}>{E.emptyBody}</EmptyState></div>}
      {data && data.length > 0 && (
        <Card>
          <EventList events={data} actions={(ev) => (
            <>
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => setEditing(ev)}><Icon name="edit" size={16} /> {E.edit}</button>
              <button type="button" className="btn btn-danger btn-sm" onClick={() => setRemoving(ev)}>{E.remove}</button>
            </>
          )} />
        </Card>
      )}
      {editing && <EventForm key={editing === 'new' ? 'new' : editing.id} event={editing === 'new' ? null : editing}
                             onClose={() => setEditing(null)} onSaved={reload} />}
      <Modal open={!!removing} title={E.removeTitle} onClose={() => setRemoving(null)}
             actions={<>
               <button type="button" className="btn btn-quiet" onClick={() => setRemoving(null)}>{E.keep}</button>
               <button type="button" className="btn btn-danger" onClick={remove} disabled={busy}>{E.remove}</button>
             </>}>
        {removing && <p>{E.removeBody(removing.title)}</p>}
        {removeError && <ErrorNotice doing={E.removeFailed} error={removeError} />}
      </Modal>
    </>
  )
}

function EventForm({ event, onClose, onSaved }: { event: SaccoEvent | null; onClose: () => void; onSaved: () => Promise<void> }) {
  const toast = useToast()
  const [d, setD] = useState<Draft>(() => draftOf(event))
  const [tried, setTried] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const errors = tried ? eventErrors(d) : {}
  const put = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((x) => ({ ...x, [k]: v }))

  async function submit(e?: FormEvent) {
    e?.preventDefault()
    setTried(true)
    if (Object.keys(eventErrors(d)).length) return
    setBusy(true)
    setError(null)
    const body: EventBody = {
      title: d.title.trim(), event_type: d.event_type, date: d.date, time: d.time,
      location: d.location.trim() || null, online_link: d.online_link.trim() || null, description: d.description.trim() || null,
    }
    try {
      if (event) await api.updateEvent(event.id, body)
      else await api.createEvent(body)
      toast(E.saved)
      await onSaved()
      onClose()
    } catch (err) {
      setError(err as ApiError)
      setBusy(false)
    }
  }

  return (
    <Modal open title={event ? E.formEdit : E.formNew} onClose={onClose}
           actions={<>
             <button type="button" className="btn btn-quiet" onClick={onClose}>{t.common.cancel}</button>
             <button type="button" className="btn btn-primary" onClick={() => submit()} disabled={busy}>
               {busy && <span className="spinner" aria-hidden />} {E.save}
             </button>
           </>}>
      <form className={styles.form} onSubmit={submit} noValidate>
        <Field id="ev-title" label={E.titleField} error={errors.title}>
          {(p) => <input {...p} className="input" maxLength={200} value={d.title} onChange={(e) => put('title', e.target.value)} />}
        </Field>
        <Field id="ev-type" label={E.type}>
          {(p) => (
            <select {...p} className="select" value={d.event_type} onChange={(e) => put('event_type', e.target.value as EventType)}>
              {TYPES.map((ty) => <option key={ty} value={ty}>{E.types[ty]}</option>)}
            </select>
          )}
        </Field>
        <div className={styles.two}>
          <Field id="ev-date" label={E.date} error={errors.date}>
            {(p) => <input {...p} className="input" type="date" min={todayYmd()} value={d.date} onChange={(e) => put('date', e.target.value)} />}
          </Field>
          <Field id="ev-time" label={E.time} error={errors.time}>
            {(p) => <input {...p} className="input" type="time" value={d.time} onChange={(e) => put('time', e.target.value)} />}
          </Field>
        </div>
        <Field id="ev-location" label={E.location} optional>
          {(p) => <input {...p} className="input" maxLength={200} value={d.location} onChange={(e) => put('location', e.target.value)} />}
        </Field>
        <Field id="ev-link" label={E.link} optional hint={E.linkHint} error={errors.online_link}>
          {(p) => <input {...p} className="input" type="url" inputMode="url" maxLength={500} value={d.online_link} onChange={(e) => put('online_link', e.target.value)} />}
        </Field>
        <Field id="ev-description" label={E.description} optional>
          {(p) => <textarea {...p} className="textarea" rows={3} maxLength={2000} value={d.description} onChange={(e) => put('description', e.target.value)} />}
        </Field>
      </form>
      {error && <ErrorNotice doing={E.failed} error={error} />}
    </Modal>
  )
}

/** The officer home's short list. */
export function UpcomingEvents() {
  const load = useCallback(() => api.events(), [])
  const { data, error, reload } = useLoad(load)
  return (
    <Card title={E.upcomingCard} delay={0.1} actions={<a href={paths.events()} className="btn btn-quiet btn-sm">{t.bookings.viewAll}</a>}>
      {error && <ErrorNotice doing={E.loadFailed} error={error} onRetry={reload} />}
      {!data && !error && <SkeletonList rows={2} what={E.upcomingCard} />}
      {data?.length === 0 && <EmptyState icon="calendar" title={E.empty} />}
      {data && data.length > 0 && <EventList events={data.slice(0, 4)} />}
    </Card>
  )
}
