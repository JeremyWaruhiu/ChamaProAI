import type { DecisionCreate, Outcome } from '../api/types'
import { t } from '../strings'
import { parseShillings } from './format'

// The officer's decision panel: which outcomes are offered, what each needs,
// and the body sent to the API (loans.decide checks the same rules).

export const OUTCOMES: Outcome[] = ['approve', 'approve_with_guarantor', 'approve_reduced', 'refer', 'decline']

/** Outcomes that only make sense on a loan application (the API refuses them otherwise). */
export const NEEDS_APPLICATION = new Set<Outcome>(['approve_with_guarantor', 'approve_reduced'])

export const DEFAULT_GUARANTORS = 2

export interface DecisionDraft {
  outcome: Outcome | null
  guarantors: string
  reducedAmount: string
  officerNotes: string
  memberMessage: string
}

export const EMPTY_DECISION: DecisionDraft = {
  outcome: null, guarantors: String(DEFAULT_GUARANTORS), reducedAmount: '', officerNotes: '', memberMessage: '',
}

/** Every outcome, each marked whether it can be chosen here. */
export function outcomeOptions(hasApplication: boolean): { outcome: Outcome; available: boolean }[] {
  return OUTCOMES.map((outcome) => ({ outcome, available: hasApplication || !NEEDS_APPLICATION.has(outcome) }))
}

export type DecisionField = 'outcome' | 'guarantors' | 'reducedAmount' | 'officerNotes' | 'memberMessage'

/** What is wrong with the draft; {} when it can be recorded. `requested` is the application's amount. */
export function decisionErrors(d: DecisionDraft, requested: number | null): Partial<Record<DecisionField, string>> {
  const E = t.decision.errors
  const out: Partial<Record<DecisionField, string>> = {}
  if (!d.outcome || (requested === null && NEEDS_APPLICATION.has(d.outcome))) out.outcome = E.outcome
  if (d.outcome === 'approve_with_guarantor') {
    const n = Number(d.guarantors)
    if (!d.guarantors.trim() || !Number.isInteger(n) || n < 1 || n > 10) out.guarantors = E.guarantors
  }
  if (d.outcome === 'approve_reduced' && requested !== null) {
    const amount = parseShillings(d.reducedAmount)
    if (amount === null || amount <= 0 || amount >= requested) out.reducedAmount = E.reduced(requested)
  }
  if (d.officerNotes.length > 2000) out.officerNotes = E.notes
  if (d.memberMessage.length > 1000) out.memberMessage = E.message
  return out
}

/** The request body for a draft with no errors. */
export function decisionBody(d: DecisionDraft): DecisionCreate {
  if (!d.outcome) throw new Error('no outcome chosen')
  const body: DecisionCreate = {
    outcome: d.outcome,
    officer_notes: d.officerNotes.trim() || null,
    member_message: d.memberMessage.trim() || null,
  }
  if (d.outcome === 'approve_with_guarantor') body.guarantors_required = Number(d.guarantors)
  if (d.outcome === 'approve_reduced') body.approved_amount_kes = parseShillings(d.reducedAmount)!
  return body
}
