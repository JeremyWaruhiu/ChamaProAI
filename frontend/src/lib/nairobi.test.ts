import { describe, expect, it } from 'vitest'
import type { BookingCalendar } from '../api/types'
import { addDays, addMonths, bookable, formatNairobi, mondayOf, monthWeeks, nairobiDay, nairobiTime } from './nairobi'

const CAL: BookingCalendar = {
  today: '2026-11-04', last_date: '2027-02-02', times: [], timezone: 'Africa/Nairobi',
  holidays: [{ date: '2026-12-25', name: 'Christmas Day' }, { date: '2027-01-01', name: "New Year's Day" }],
}

describe('Nairobi time', () => {
  // process.env.TZ is whatever the machine says; these must not depend on it.
  it('shows an instant in Nairobi, not in the viewer’s zone', () => {
    expect(nairobiTime('2026-11-10T05:30:00+00:00')).toBe('08:30')
    expect(formatNairobi('2026-11-10T05:30:00+00:00')).toBe('Tue 10 Nov 2026, 08:30')
  })

  it('counts the day at the branch: 21:30 UTC is already tomorrow', () => {
    expect(nairobiDay('2026-11-10T21:30:00+00:00')).toBe('2026-11-11')
    expect(nairobiDay('2026-11-10T20:59:00+00:00')).toBe('2026-11-10')
  })
})

describe('calendar days', () => {
  it('adds across months and years', () => {
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01')
    expect(addMonths('2026-12', 1)).toBe('2027-01')
    expect(addMonths('2027-01', -1)).toBe('2026-12')
  })

  it('finds the Monday of a week', () => {
    expect(mondayOf('2026-11-04')).toBe('2026-11-02')       // a Wednesday
    expect(mondayOf('2026-11-02')).toBe('2026-11-02')
    expect(mondayOf('2026-11-08')).toBe('2026-11-02')       // a Sunday
  })

  it('lays out a month Monday first, whole weeks only', () => {
    const weeks = monthWeeks('2026-11')                     // 1 Nov 2026 is a Sunday
    expect(weeks[0]).toEqual([null, null, null, null, null, null, '2026-11-01'])
    expect(weeks.every((w) => w.length === 7)).toBe(true)
    expect(weeks.flat().filter(Boolean)).toHaveLength(30)
  })
})

describe('the date picker’s rules', () => {
  it('allows a weekday in the window', () => {
    expect(bookable('2026-11-04', CAL)).toEqual({ blocked: false })
    expect(bookable('2026-11-10', CAL)).toEqual({ blocked: false })
  })

  it('blocks past dates, weekends and dates past the window', () => {
    expect(bookable('2026-11-03', CAL)).toMatchObject({ blocked: true, holiday: false })
    expect(bookable('2026-11-07', CAL)).toMatchObject({ blocked: true, reason: expect.stringContaining('weekdays') })
    expect(bookable('2026-11-08', CAL)).toMatchObject({ blocked: true, reason: expect.stringContaining('weekdays') })
    expect(bookable('2027-02-03', CAL)).toMatchObject({ blocked: true, holiday: false })
  })

  it('gives the holiday’s name as the reason', () => {
    expect(bookable('2026-12-25', CAL)).toEqual({ blocked: true, holiday: true, reason: 'Christmas Day: public holiday' })
  })
})
