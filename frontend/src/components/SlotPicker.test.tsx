// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { BookingCalendar, DaySlots } from '../api/types'
import { Picker, SlotButtons } from './SlotPicker'

const CAL: BookingCalendar = {
  today: '2026-11-04', last_date: '2027-02-02', times: ['08:30', '09:00'], timezone: 'Africa/Nairobi',
  holidays: [{ date: '2026-12-25', name: 'Christmas Day' }],
}
const DAY: DaySlots = {
  date: '2026-11-10', blocked_reason: null,
  slots: [
    { time: '08:30', starts_at: '2026-11-10T05:30:00+00:00', available: false, reason: 'booked' },
    { time: '09:00', starts_at: '2026-11-10T06:00:00+00:00', available: true, reason: null },
    { time: '09:30', starts_at: '2026-11-10T06:30:00+00:00', available: false, reason: 'past' },
  ],
}
beforeEach(() => { vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(DAY), { status: 200 }))) })
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const day = (name: RegExp) => screen.getByRole('button', { name })

describe('the calendar', () => {
  it('does not offer past dates or weekends', () => {
    const onChange = vi.fn()
    render(<Picker cal={CAL} date="" time="" onChange={onChange} />)
    fireEvent.click(day(/Tuesday 3 November 2026/))
    fireEvent.click(day(/Saturday 7 November 2026/))
    expect(onChange).not.toHaveBeenCalled()
    expect(day(/Saturday 7 November 2026/).getAttribute('aria-disabled')).toBe('true')
    expect(screen.getByRole('status').textContent).toContain('weekdays only')
  })

  it('offers a weekday', () => {
    const onChange = vi.fn()
    render(<Picker cal={CAL} date="" time="" onChange={onChange} />)
    fireEvent.click(day(/Tuesday 10 November 2026/))
    expect(onChange).toHaveBeenCalledWith({ date: '2026-11-10', time: '' })
  })

  it('blocks a holiday and names it, on a phone too where a tooltip never shows', () => {
    const onChange = vi.fn()
    render(<Picker cal={CAL} date="" time="" onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: 'Next month' }))
    expect(screen.getByText('25 Dec: Christmas Day')).toBeTruthy()         // the list under the month
    const christmas = day(/Friday 25 December 2026. Christmas Day/)
    fireEvent.click(christmas)
    expect(onChange).not.toHaveBeenCalled()
    expect(screen.getByRole('status').textContent).toContain('Christmas Day: public holiday')
  })

  it('cannot go before this month or past the booking window', () => {
    render(<Picker cal={CAL} date="" time="" onChange={() => {}} />)
    expect((screen.getByRole('button', { name: 'Previous month' }) as HTMLButtonElement).disabled).toBe(true)
    const next = screen.getByRole('button', { name: 'Next month' }) as HTMLButtonElement
    fireEvent.click(next)
    fireEvent.click(next)
    fireEvent.click(next)
    expect(next.disabled).toBe(true)                                       // February 2027
  })

  it('clears the time when the date changes, since it may be taken on the new one', () => {
    const onChange = vi.fn()
    render(<Picker cal={CAL} date="2026-11-10" time="09:00" onChange={onChange} />)
    fireEvent.click(day(/Wednesday 11 November 2026/))
    expect(onChange).toHaveBeenCalledWith({ date: '2026-11-11', time: '' })
  })

  it('says times are Nairobi time', () => {
    render(<Picker cal={CAL} date="" time="" onChange={() => {}} />)
    expect(screen.getByText(/Nairobi time/)).toBeTruthy()
  })
})

describe('the slots', () => {
  it('disables a booked slot and says so; no name is shown', () => {
    const onPick = vi.fn()
    render(<SlotButtons day={DAY} time="" onPick={onPick} />)
    const booked = screen.getByRole('button', { name: /08:30/ }) as HTMLButtonElement
    expect(booked.disabled).toBe(true)
    expect(booked.textContent).toContain('Booked')
    fireEvent.click(booked)
    expect(onPick).not.toHaveBeenCalled()
  })

  it('disables a slot earlier today', () => {
    render(<SlotButtons day={DAY} time="" onPick={() => {}} />)
    expect((screen.getByRole('button', { name: /09:30/ }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('offers a free slot', () => {
    const onPick = vi.fn()
    render(<SlotButtons day={DAY} time="" onPick={onPick} />)
    fireEvent.click(screen.getByRole('button', { name: /09:00/ }))
    expect(onPick).toHaveBeenCalledWith('09:00')
  })

  it('marks the one chosen', () => {
    render(<SlotButtons day={DAY} time="09:00" onPick={() => {}} />)
    expect(screen.getByRole('button', { name: /09:00/ }).getAttribute('aria-pressed')).toBe('true')
  })

  it('says when a day is full', () => {
    render(<SlotButtons day={{ ...DAY, slots: [DAY.slots[0]] }} time="" onPick={() => {}} />)
    expect(screen.getByText(/No times are free/)).toBeTruthy()
  })
})
