import { useCallback, useState } from 'react'
import { ApiError, api } from '../api/client'
import type { Booking } from '../api/types'
import { Icon } from '../components/Icon'
import { ErrorNotice } from '../components/Notice'
import { SlotPicker } from '../components/SlotPicker'
import { useToast } from '../components/toastContext'
import { Badge, Card, EmptyState, Modal, PageHeader, SkeletonList } from '../components/ui'
import { useLoad } from '../hooks/useLoad'
import { cx } from '../lib/cx'
import { formatKes, todayYmd } from '../lib/format'
import { addDays, formatNairobi, longDay, mondayOf, nairobiDay, nairobiTime, shortDay } from '../lib/nairobi'
import { navigate, paths } from '../lib/router'
import { BOOKING_TONE } from '../lib/status'
import { t } from '../strings'
import styles from './Bookings.module.css'
import tables from './Tables.module.css'

const B = t.bookings
const languageOf = (b: Booking) => (b.language === 'en' ? t.common.english : t.common.kikuyu)

export function Bookings() {
  const [view, setView] = useState<'upcoming' | 'week'>('upcoming')
  const [monday, setMonday] = useState(() => mondayOf(todayYmd()))
  const load = useCallback(() => (view === 'upcoming'
    ? api.bookings({ limit: 200 })
    : api.bookings({ start: monday, end: addDays(monday, 4), limit: 200 })), [view, monday])
  const { data, error, reload } = useLoad(load)
  const [openId, setOpenId] = useState<number | null>(null)
  const [moving, setMoving] = useState<Booking | null>(null)
  const [cancelling, setCancelling] = useState<Booking | null>(null)
  const opened = data?.find((b) => b.id === openId) ?? null

  return (
    <>
      <PageHeader title={B.title} lead={B.lead} actions={
        <div className={tables.segmented} role="group" aria-label={B.title}>
          <button type="button" aria-pressed={view === 'upcoming'} onClick={() => setView('upcoming')}>{B.upcoming}</button>
          <button type="button" aria-pressed={view === 'week'} onClick={() => setView('week')}>{B.week}</button>
        </div>
      } />
      {error && <ErrorNotice doing={B.loadFailed} error={error} onRetry={reload} />}
      {!data && !error && <SkeletonList rows={4} what={B.title} />}
      {data && view === 'upcoming' && (
        data.length === 0
          ? <div className="card"><EmptyState icon="clock" title={B.empty}>{B.emptyBody}</EmptyState></div>
          : <ul className={styles.list}>
              {data.map((b) => <li key={b.id}><BookingCard b={b} onChanged={reload} onMove={setMoving} onCancel={setCancelling} /></li>)}
            </ul>
      )}
      {data && view === 'week' && (
        <>
          <div className={styles.weekBar}>
            <button type="button" className="btn btn-secondary" onClick={() => setMonday(addDays(monday, -7))} aria-label={B.previousWeek}><Icon name="chevronLeft" /></button>
            <p className={styles.weekLabel} aria-live="polite">{B.weekOf(shortDay(monday), shortDay(addDays(monday, 4)))}</p>
            <button type="button" className="btn btn-secondary" onClick={() => setMonday(addDays(monday, 7))} aria-label={B.nextWeek}><Icon name="chevronRight" /></button>
          </div>
          <div className={styles.week}>
            {[0, 1, 2, 3, 4].map((i) => {
              const day = addDays(monday, i)
              const rows = data.filter((b) => nairobiDay(b.starts_at) === day)
              return (
                <section key={day} className={cx('card', styles.day)} aria-label={longDay(day)}>
                  <h2 className={styles.dayTitle}>{longDay(day).split(' ')[0]} <span className={styles.dayDate}>{shortDay(day)}</span></h2>
                  {rows.length === 0 && <p className="subtle small">{B.weekEmpty}</p>}
                  <ul className={styles.dayList}>
                    {rows.map((b) => (
                      <li key={b.id}>
                        <button type="button" className={styles.entry} onClick={() => setOpenId(b.id)}>
                          <span className={styles.entryTop}>
                            <span className={styles.entryTime}>{nairobiTime(b.starts_at)}</span>
                            <Badge tone={BOOKING_TONE[b.status]} title={t.booking.status[b.status]}>{t.booking.statusShort[b.status]}</Badge>
                          </span>
                          <span className={styles.entryName}>{b.member_name}</span>
                          <span className="subtle small">{formatKes(b.amount_requested_kes)}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </section>
              )
            })}
          </div>
        </>
      )}
      <Modal open={opened !== null} title={B.manageTitle} onClose={() => setOpenId(null)}>
        {opened && <BookingCard b={opened} bare onChanged={reload}
                                onMove={(b) => { setOpenId(null); setMoving(b) }}
                                onCancel={(b) => { setOpenId(null); setCancelling(b) }} />}
      </Modal>
      <RescheduleModal booking={moving} onClose={() => setMoving(null)} onDone={reload} />
      <CancelModal booking={cancelling} onClose={() => setCancelling(null)} onDone={reload} />
    </>
  )
}

function BookingCard({ b, bare = false, onChanged, onMove, onCancel }: {
  b: Booking; bare?: boolean; onChanged: () => Promise<void>; onMove: (b: Booking) => void; onCancel: (b: Booking) => void
}) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  async function act(work: () => Promise<unknown>, message?: string) {
    setBusy(true)
    setError(null)
    try {
      await work()
      if (message) toast(message)
      await onChanged()
    } catch (e) {
      setError(e as ApiError)
    } finally {
      setBusy(false)
    }
  }

  async function open() {
    setBusy(true)
    setError(null)
    try {
      const started = await api.startBooking(b.id)
      navigate(paths.record(started.interview_id!))
    } catch (e) {
      setError(e as ApiError)
      setBusy(false)
    }
  }

  return (
    <article className={cx(!bare && 'card', styles.card, bare && styles.bare)}>
      <div className={styles.cardTop}>
        <p className={styles.when}><Icon name="clock" size={16} /> {formatNairobi(b.starts_at)}</p>
        <Badge tone={BOOKING_TONE[b.status]}>{t.booking.status[b.status]}</Badge>
      </div>
      <p className={styles.who}>
        <a href={paths.member(b.member_id)}>{b.member_name}</a> <span className="subtle small">{b.member_no}</span>
      </p>
      <p className="subtle small">
        {formatKes(b.amount_requested_kes)} · {t.common.months(b.term_months)} · {b.purpose} · {languageOf(b)}
        {b.member_phone && <> · <a href={`tel:${b.member_phone}`}>{b.member_phone}</a></>}
      </p>
      <div className={styles.actions}>
        {b.status === 'requested' && (
          <button type="button" className="btn btn-primary btn-sm" disabled={busy}
                  onClick={() => act(() => api.confirmBooking(b.id), B.confirmed)}>
            <Icon name="check" size={16} /> {B.confirm}
          </button>
        )}
        {b.status === 'confirmed' && (
          <button type="button" className="btn btn-accent btn-sm" disabled={busy} onClick={open}>
            <Icon name="mic" size={16} /> {B.start}
          </button>
        )}
        {b.status === 'started' && b.interview_id && (
          <a className="btn btn-accent btn-sm" href={paths.record(b.interview_id)}><Icon name="mic" size={16} /> {B.continue}</a>
        )}
        {(b.status === 'requested' || b.status === 'confirmed') && (
          <>
            <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => onMove(b)}>{B.reschedule}</button>
            <button type="button" className="btn btn-danger btn-sm" disabled={busy} onClick={() => onCancel(b)}>{B.cancel}</button>
          </>
        )}
        <a className="btn btn-quiet btn-sm" href={paths.application(b.application_id)}>{B.openApplication}</a>
      </div>
      {error && <ErrorNotice doing={B.actionFailed} error={error} />}
    </article>
  )
}

function RescheduleModal({ booking, onClose, onDone }: { booking: Booking | null; onClose: () => void; onDone: () => Promise<void> }) {
  const toast = useToast()
  const [slot, setSlot] = useState({ date: '', time: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const close = () => { setSlot({ date: '', time: '' }); setError(null); setBusy(false); onClose() }

  async function move() {
    if (!booking) return
    setBusy(true)
    setError(null)
    try {
      await api.rescheduleBooking(booking.id, slot.date, slot.time)
      toast(B.rescheduled)
      await onDone()
      close()
    } catch (e) {
      setError(e as ApiError)
      setBusy(false)
    }
  }

  return (
    <Modal open={!!booking} title={B.rescheduleTitle} onClose={close}
           actions={<>
             <button type="button" className="btn btn-quiet" onClick={close}>{t.common.cancel}</button>
             <button type="button" className="btn btn-primary" onClick={move} disabled={busy || !slot.date || !slot.time}>
               {busy && <span className="spinner" aria-hidden />} {B.moveTo}
             </button>
           </>}>
      {booking && <p className="muted small">{booking.member_name}, {formatNairobi(booking.starts_at)}</p>}
      {booking && <SlotPicker date={slot.date} time={slot.time} idPrefix="move" onChange={setSlot} />}
      {error && <ErrorNotice doing={B.actionFailed} error={error} />}
    </Modal>
  )
}

function CancelModal({ booking, onClose, onDone }: { booking: Booking | null; onClose: () => void; onDone: () => Promise<void> }) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const close = () => { setError(null); setBusy(false); onClose() }

  async function cancel() {
    if (!booking) return
    setBusy(true)
    setError(null)
    try {
      await api.cancelBooking(booking.id)
      toast(B.cancelled)
      await onDone()
      close()
    } catch (e) {
      setError(e as ApiError)
      setBusy(false)
    }
  }

  return (
    <Modal open={!!booking} title={B.cancelTitle} onClose={close}
           actions={<>
             <button type="button" className="btn btn-quiet" onClick={close}>{B.keep}</button>
             <button type="button" className="btn btn-danger" onClick={cancel} disabled={busy}>
               {busy && <span className="spinner" aria-hidden />} {B.cancel}
             </button>
           </>}>
      {booking && <p>{B.cancelBody(booking.member_name, formatNairobi(booking.starts_at))}</p>}
      {error && <ErrorNotice doing={B.actionFailed} error={error} />}
    </Modal>
  )
}

/** The officer home's short list: the next few, each opening the bookings page. */
export function UpcomingInterviews() {
  const load = useCallback(() => api.bookings({ limit: 6 }), [])
  const { data, error, reload } = useLoad(load)
  return (
    <Card title={B.upcomingCard} delay={0.05} actions={<a href={paths.bookings()} className="btn btn-quiet btn-sm">{B.viewAll}</a>}>
      {error && <ErrorNotice doing={B.loadFailed} error={error} onRetry={reload} />}
      {!data && !error && <SkeletonList rows={3} what={B.upcomingCard} />}
      {data?.length === 0 && <EmptyState icon="clock" title={B.upcomingEmpty} />}
      {data && data.length > 0 && (
        <ul className={styles.homeList}>
          {data.map((b) => (
            <li key={b.id}>
              <a href={paths.bookings()} className={styles.homeRow}>
                <span>
                  <strong>{b.member_name}</strong>
                  <span className={styles.homeMeta}>{formatNairobi(b.starts_at)} · {languageOf(b)}</span>
                </span>
                <Badge tone={BOOKING_TONE[b.status]}>{t.booking.status[b.status]}</Badge>
              </a>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
