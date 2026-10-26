// A null metric is "not yet measured": never shown or drawn as 0.

import { t } from '../strings'

export const NOT_MEASURED = t.charts.notMeasured

export function isMeasured(v: number | null | undefined): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}

/** A number as text, or "not yet measured" when there is none. */
export function fmt(v: number | null | undefined, digits = 3): string {
  return isMeasured(v) ? v.toFixed(digits) : NOT_MEASURED
}

export function pct(v: number | null | undefined, digits = 1): string {
  return isMeasured(v) ? `${(v * 100).toFixed(digits)}%` : NOT_MEASURED
}
