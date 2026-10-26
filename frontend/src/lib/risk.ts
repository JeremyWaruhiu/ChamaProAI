import type { DecisionValue, Outcome } from '../api/types'
import { t } from '../strings'

export type RiskClass = 'Low' | 'Medium' | 'High'

/** What each class means operationally at the SACCO. */
export const RISK_MEANING: Record<RiskClass, string> = t.risk.meaning

export const RISK_ORDER: RiskClass[] = ['Low', 'Medium', 'High']

export const DECISION_LABEL: Record<DecisionValue, string> = t.risk.decision

/** The coarse decision each outcome is a kind of. */
export const COARSE: Record<Outcome, DecisionValue> = {
  approve: 'approve', approve_with_guarantor: 'approve', approve_reduced: 'approve',
  refer: 'refer', decline: 'decline',
}

/** The officer decision each risk class recommends (comparator.RECOMMENDED_DECISION). */
export const RECOMMENDED: Record<RiskClass, DecisionValue> = { Low: 'approve', Medium: 'refer', High: 'decline' }

/** Does the officer's outcome follow the model's recommendation? A borderline call is a referral. */
export function agrees(risk: string, borderline: boolean, outcome: Outcome | DecisionValue): boolean {
  const d = COARSE[outcome]
  if (borderline || risk === 'Medium') return d === 'refer'
  if (risk === 'Low') return d === 'approve'
  if (risk === 'High') return d === 'decline' || d === 'refer'
  return false
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
  if (borderline) return t.risk.borderline
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
