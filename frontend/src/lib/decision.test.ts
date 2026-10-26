import { describe, expect, it } from 'vitest'
import { EMPTY_DECISION, OUTCOMES, decisionBody, decisionErrors, outcomeOptions, type DecisionDraft } from './decision'
import { agrees } from './risk'

const d = (over: Partial<DecisionDraft>): DecisionDraft => ({ ...EMPTY_DECISION, ...over })

describe('decision outcomes', () => {
  it('offers all five outcomes on a loan application', () => {
    expect(OUTCOMES).toEqual(['approve', 'approve_with_guarantor', 'approve_reduced', 'refer', 'decline'])
    expect(outcomeOptions(true).every((o) => o.available)).toBe(true)
  })

  it('without an application, only approve, refer and decline can be chosen', () => {
    expect(outcomeOptions(false).filter((o) => o.available).map((o) => o.outcome)).toEqual(['approve', 'refer', 'decline'])
  })

  it('needs an outcome', () => {
    expect(decisionErrors(EMPTY_DECISION, 60000)).toHaveProperty('outcome')
  })

  it('approve with guarantor: 1 to 10, default 2', () => {
    expect(EMPTY_DECISION.guarantors).toBe('2')
    expect(decisionErrors(d({ outcome: 'approve_with_guarantor' }), 60000)).toEqual({})
    for (const guarantors of ['0', '11', '1.5', '']) {
      expect(decisionErrors(d({ outcome: 'approve_with_guarantor', guarantors }), 60000)).toHaveProperty('guarantors')
    }
    expect(decisionBody(d({ outcome: 'approve_with_guarantor', guarantors: '3' })))
      .toEqual({ outcome: 'approve_with_guarantor', guarantors_required: 3, officer_notes: null, member_message: null })
  })

  it('approve a reduced amount: above 0 and below the amount requested', () => {
    expect(decisionErrors(d({ outcome: 'approve_reduced', reducedAmount: '40,000' }), 60000)).toEqual({})
    expect(decisionErrors(d({ outcome: 'approve_reduced', reducedAmount: '60000' }), 60000)).toHaveProperty('reducedAmount')
    expect(decisionErrors(d({ outcome: 'approve_reduced', reducedAmount: '' }), 60000)).toHaveProperty('reducedAmount')
    expect(decisionBody(d({ outcome: 'approve_reduced', reducedAmount: '40,000' })).approved_amount_kes).toBe(40000)
  })

  it('refuses application-only outcomes when there is no application', () => {
    expect(decisionErrors(d({ outcome: 'approve_reduced', reducedAmount: '5' }), null)).toHaveProperty('outcome')
    expect(decisionErrors(d({ outcome: 'refer' }), null)).toEqual({})
  })

  it('keeps officer notes and the member message apart, trimmed, and bounded', () => {
    expect(decisionBody(d({ outcome: 'decline', officerNotes: '  checked arrears ', memberMessage: ' Sorry. ' })))
      .toEqual({ outcome: 'decline', officer_notes: 'checked arrears', member_message: 'Sorry.' })
    expect(decisionErrors(d({ outcome: 'refer', officerNotes: 'x'.repeat(2001) }), 1)).toHaveProperty('officerNotes')
    expect(decisionErrors(d({ outcome: 'refer', memberMessage: 'x'.repeat(1001) }), 1)).toHaveProperty('memberMessage')
  })

  it('counts every kind of approval as agreeing with a Low result', () => {
    for (const o of ['approve', 'approve_with_guarantor', 'approve_reduced'] as const) expect(agrees('Low', false, o)).toBe(true)
    expect(agrees('Low', true, 'approve')).toBe(false)
    expect(agrees('High', false, 'refer')).toBe(true)
  })
})
