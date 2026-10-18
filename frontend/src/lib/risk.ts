import type { DecisionValue } from '../api/types'

export type RiskClass = 'Low' | 'Medium' | 'High'

/** What each class means operationally at the SACCO. */
export const RISK_MEANING: Record<RiskClass, string> = {
  Low: 'Approve on standard terms',
  Medium: 'Refer to the loan committee',
  High: 'Decline, or refer for manual review',
}

export const RISK_ORDER: RiskClass[] = ['Low', 'Medium', 'High']

export const DECISION_LABEL: Record<DecisionValue, string> = {
  approve: 'Approve',
  decline: 'Decline',
  refer: 'Refer to loan committee',
}

/** Two most likely classes within this many points is a close call. */
export const BORDERLINE_POINTS = 10

export interface Closeness {
  borderline: boolean
  first: [string, number]
  second: [string, number]
  gapPoints: number
}

export function closeness(probabilities: Record<string, number>): Closeness {
  const ranked = Object.entries(probabilities).sort((a, b) => b[1] - a[1])
  const [first, second] = ranked
  const gapPoints = Math.round((first[1] - second[1]) * 1000) / 10
  return { borderline: gapPoints <= BORDERLINE_POINTS, first, second, gapPoints }
}

/** The model's recommendation in words. A borderline call is always a referral. */
export function recommendation(riskClass: string, borderline: boolean): string {
  if (borderline) return 'Refer to the loan committee (borderline)'
  return RISK_MEANING[riskClass as RiskClass] ?? riskClass
}

export function riskTone(riskClass: string | null | undefined): 'low' | 'medium' | 'high' | 'none' {
  switch (riskClass) {
    case 'Low': return 'low'
    case 'Medium': return 'medium'
    case 'High': return 'high'
    default: return 'none'
  }
}
