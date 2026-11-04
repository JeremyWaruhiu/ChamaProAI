import type { BookingCalendar } from '../api/types'
import { t } from '../strings'

// Interview and event times are stored in UTC and always shown in Nairobi time,
// whatever the time zone of the phone or laptop looking at them. Calendar days
// are plain YYYY-MM-DD strings, worked out in UTC so no local offset can move one.

const ZONE = 'Africa/Nairobi'

/** Tue 10 Nov 2026, 09:00 */
export function formatNairobi(iso: string): string {
  const d = new Date(iso)
  const day = d.toLocaleDateString('en-GB', { timeZone: ZONE, weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })
  return `${day.replace(',', '')}, ${nairobiTime(iso)}`
}

/** 09:00 */
export const nairobiTime = (iso: string): string =>
  new Date(iso).toLocaleTimeString('en-GB', { timeZone: ZONE, hour: '2-digit', minute: '2-digit', hour12: false })

/** The calendar day an instant falls on in Nairobi. */
export function nairobiDay(iso: string): string {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: ZONE, year: 'numeric', month: '2-digit', day: '2-digit' })
  return parts.format(new Date(iso))
}

const asDate = (ymd: string) => new Date(`${ymd}T00:00:00Z`)
const ymdOf = (d: Date) => d.toISOString().slice(0, 10)

export function addDays(ymd: string, n: number): string {
  const d = asDate(ymd)
  d.setUTCDate(d.getUTCDate() + n)
  return ymdOf(d)
}

export const weekdayOf = (ymd: string): number => asDate(ymd).getUTCDay() // 0 Sunday ... 6 Saturday

/** The Monday of the week a day is in. */
export const mondayOf = (ymd: string): string => addDays(ymd, -((weekdayOf(ymd) + 6) % 7))

/** "10 Nov" */
export const shortDay = (ymd: string): string =>
  asDate(ymd).toLocaleDateString('en-GB', { timeZone: 'UTC', day: 'numeric', month: 'short' })

/** "Tuesday 10 November 2026" */
export const longDay = (ymd: string): string =>
  asDate(ymd).toLocaleDateString('en-GB', { timeZone: 'UTC', weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }).replace(',', '')

export const monthName = (ym: string): string =>
  asDate(`${ym}-01`).toLocaleDateString('en-GB', { timeZone: 'UTC', month: 'long', year: 'numeric' })

export function addMonths(ym: string, n: number): string {
  const d = asDate(`${ym}-01`)
  d.setUTCMonth(d.getUTCMonth() + n)
  return ymdOf(d).slice(0, 7)
}

/** The weeks of a month, Monday first; days outside it are null. */
export function monthWeeks(ym: string): (string | null)[][] {
  const first = `${ym}-01`
  const cells: (string | null)[] = Array.from({ length: (weekdayOf(first) + 6) % 7 }, () => null)
  for (let d = first; d.startsWith(ym); d = addDays(d, 1)) cells.push(d)
  while (cells.length % 7) cells.push(null)
  return Array.from({ length: cells.length / 7 }, (_, i) => cells.slice(i * 7, i * 7 + 7))
}

export type Bookable = { blocked: false } | { blocked: true; reason: string; holiday: boolean }

/** The date picker's answer for one day: the same rules as bookings.day_problem. */
export function bookable(ymd: string, cal: BookingCalendar): Bookable {
  const B = t.booking
  const holiday = cal.holidays.find((h) => h.date === ymd)
  if (holiday) return { blocked: true, reason: B.holiday(holiday.name), holiday: true }
  if (ymd < cal.today) return { blocked: true, reason: B.past, holiday: false }
  if (ymd > cal.last_date) return { blocked: true, reason: B.tooFar, holiday: false }
  const day = weekdayOf(ymd)
  if (day === 0 || day === 6) return { blocked: true, reason: B.weekend, holiday: false }
  return { blocked: false }
}
