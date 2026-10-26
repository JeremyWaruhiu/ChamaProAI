import { t } from '../strings'

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

export function formatClock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

export const percent = (fraction: number) => `${Math.round(fraction * 100)}%`

export const applicantName = (name: string | null | undefined) => name?.trim() || t.common.unnamedApplicant

/** KSh 60,000 */
export const formatKes = (n: number) => t.common.ksh(n)

/** 2026-10-26 (a date-only value) as 26 Oct 2026, read as a calendar date, not a UTC instant. */
export function formatDay(ymd: string): string {
  const [y, m, d] = ymd.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

/** Whole shillings as typed ("60,000", "60 000"): the number, or null if it is not one. */
export function parseShillings(text: string): number | null {
  const s = text.replace(/[\s,]/g, '')
  return /^\d{1,12}$/.test(s) ? Number(s) : null
}

/** Today in Nairobi as YYYY-MM-DD, for date inputs and "not in the future" checks. */
export function todayYmd(now: Date = new Date()): string {
  const eat = new Date(now.getTime() + 3 * 3600_000)
  return eat.toISOString().slice(0, 10)
}

export const isSameDay = (iso: string, now: Date = new Date()) =>
  new Date(iso).toDateString() === now.toDateString()
