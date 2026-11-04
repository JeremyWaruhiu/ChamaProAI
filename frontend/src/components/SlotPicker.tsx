import { useCallback, useEffect, useState } from 'react'
import { ApiError, api } from '../api/client'
import type { BookingCalendar, DaySlots } from '../api/types'
import { useLoad } from '../hooks/useLoad'
import { cx } from '../lib/cx'
import { addMonths, bookable, longDay, monthName, monthWeeks, shortDay } from '../lib/nairobi'
import { t } from '../strings'
import { Icon } from './Icon'
import { ErrorNotice } from './Notice'
import { Skeleton } from './ui'
import styles from './SlotPicker.module.css'

const B = t.booking

/**
 * Choose an interview date and half-hour slot. A native date input cannot grey
 * out weekends or say why a day is closed, so the month is drawn here. Closed days
 * stay pressable: on a phone that is the only way to learn why ("Jamhuri Day").
 * The API enforces the same rules whatever is sent.
 */
export function SlotPicker({ date, time, onChange, errorDate, errorTime, idPrefix = 'slot' }: {
  date: string; time: string; onChange: (next: { date: string; time: string }) => void
  errorDate?: string | null; errorTime?: string | null; idPrefix?: string
}) {
  const load = useCallback(() => api.bookingCalendar(), [])
  const { data: cal, error, reload } = useLoad(load)
  if (error) return <ErrorNotice doing={B.calendarFailed} error={error} onRetry={reload} />
  if (!cal) return <Skeleton height={320} radius={12} />
  return <Picker cal={cal} date={date} time={time} onChange={onChange} errorDate={errorDate} errorTime={errorTime} idPrefix={idPrefix} />
}

/** The picker itself, given the calendar. */
export function Picker({ cal, date, time, onChange, errorDate, errorTime, idPrefix = 'slot' }: {
  cal: BookingCalendar; date: string; time: string; onChange: (next: { date: string; time: string }) => void
  errorDate?: string | null; errorTime?: string | null; idPrefix?: string
}) {
  const [month, setMonth] = useState((date || cal.today).slice(0, 7))
  const [why, setWhy] = useState<string | null>(null)
  const first = cal.today.slice(0, 7)
  const last = cal.last_date.slice(0, 7)
  const inMonth = cal.holidays.filter((h) => h.date.startsWith(month))

  function press(day: string) {
    const b = bookable(day, cal)
    if (b.blocked) {
      setWhy(`${shortDay(day)}: ${b.reason}`)
      return
    }
    setWhy(null)
    onChange({ date: day, time: day === date ? time : '' })
  }

  return (
    <div className={styles.picker}>
      <div className={styles.calendar} role="group" aria-labelledby={`${idPrefix}-month`}>
        <div className={styles.monthBar}>
          <button type="button" className={styles.navBtn} aria-label={B.previousMonth} disabled={month <= first}
                  onClick={() => setMonth(addMonths(month, -1))}><Icon name="chevronLeft" size={20} /></button>
          <p id={`${idPrefix}-month`} className={styles.month} aria-live="polite">{monthName(month)}</p>
          <button type="button" className={styles.navBtn} aria-label={B.nextMonth} disabled={month >= last}
                  onClick={() => setMonth(addMonths(month, 1))}><Icon name="chevronRight" size={20} /></button>
        </div>
        <div className={styles.grid}>
          {B.weekdays.map((d) => <span key={d} className={styles.dow} aria-hidden>{d}</span>)}
          {monthWeeks(month).flat().map((day, i) => {
            if (!day) return <span key={`e${i}`} />
            const b = bookable(day, cal)
            return (
              <button key={day} type="button" onClick={() => press(day)} aria-pressed={day === date}
                      aria-disabled={b.blocked || undefined} aria-label={b.blocked ? `${longDay(day)}. ${b.reason}` : longDay(day)}
                      title={b.blocked ? b.reason : undefined}
                      className={cx(styles.day, b.blocked && styles.closed, b.blocked && b.holiday && styles.holidayDay,
                                    day === date && styles.selected)}>
                {Number(day.slice(8))}
              </button>
            )
          })}
        </div>
        {why && <p className={styles.why} role="status"><Icon name="info" size={16} /> {why}</p>}
        {inMonth.length > 0 && (
          <div className={styles.holidays}>
            <p className={styles.holidaysTitle}>{B.holidaysThisMonth}</p>
            <ul>{inMonth.map((h) => <li key={h.date}><span className={styles.holidayDot} aria-hidden />{shortDay(h.date)}: {h.name}</li>)}</ul>
          </div>
        )}
        {errorDate && <p className="field-error">{errorDate}</p>}
      </div>
      <SlotList date={date} time={time} onPick={(hhmm) => onChange({ date, time: hhmm })} error={errorTime} />
      <p className="subtle small">{B.timezone}</p>
    </div>
  )
}

function SlotList({ date, time, onPick, error }: { date: string; time: string; onPick: (hhmm: string) => void; error?: string | null }) {
  const [day, setDay] = useState<DaySlots | null>(null)
  const [failed, setFailed] = useState<ApiError | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (!date) return
    let live = true
    api.bookingSlots(date).then(
      (d) => { if (live) { setDay(d); setFailed(null) } },
      (e) => { if (live) setFailed(e as ApiError) },
    )
    return () => { live = false }
  }, [date, attempt])

  if (!date) return <p className={cx('muted', styles.slotHint)}>{B.chooseDate}</p>
  if (failed) return <ErrorNotice doing={B.slotsFailed} error={failed} onRetry={() => setAttempt((n) => n + 1)} />
  if (!day || day.date !== date) return <p className={styles.slotHint}><span className="spinner" aria-hidden /> {B.loadingSlots}</p>
  if (day.blocked_reason) return <p className="field-error">{day.blocked_reason}</p>
  return <SlotButtons day={day} time={time} onPick={onPick} error={error} />
}

/** The half-hour slots of a day; a taken one is disabled and says so. */
export function SlotButtons({ day, time, onPick, error }: { day: DaySlots; time: string; onPick: (hhmm: string) => void; error?: string | null }) {
  const free = day.slots.some((s) => s.available)
  return (
    <div role="group" aria-label={B.slotsFor(longDay(day.date))}>
      <p className="field-label">{B.slotsFor(shortDay(day.date))}</p>
      {!free && <p className="muted">{B.noneLeft}</p>}
      <div className={styles.slots}>
        {day.slots.map((s) => (
          <button key={s.time} type="button" disabled={!s.available} aria-pressed={s.time === time}
                  onClick={() => onPick(s.time)}
                  className={cx(styles.slot, s.time === time && styles.slotChosen)}>
            <span className="num">{s.time}</span>
            {s.reason && <span className={styles.slotNote}>{s.reason === 'booked' ? B.booked : B.gone}</span>}
          </button>
        ))}
      </div>
      {error && <p className="field-error">{error}</p>}
    </div>
  )
}
