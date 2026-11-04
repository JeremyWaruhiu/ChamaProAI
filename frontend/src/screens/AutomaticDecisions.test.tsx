import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { AutomaticDecisionDetail } from '../api/types'
import { parse, paths } from '../lib/router'
import { DecisionBody } from './AutomaticDecisions'

const d: AutomaticDecisionDetail = {
  id: 7, application_id: 3, member_id: 2, member_no: 'M-1010', member_name: 'Wanjiru Kamau', trigger: 'commit',
  outcome: 'approve', amount_requested_kes: 40000, amount_kes: 40000, risk_class: 'Low', policy_version: '2026.11.1',
  application_status: 'approved', loan_id: 4, loan_status: 'active', reversible_until: null,
  created_at: '2026-11-04T10:00:00Z', probabilities: { Low: 0.5173, Medium: 0.4029, High: 0.0798 },
  contributions: [{ feature: 'log_monthly_income', value: 10.7, shap: 0.466 }],
  feature_vector: {}, features: {}, provenance: { monthly_income_kes: 'verified', term_months: 'conversation' },
  overrides: { term_months: 12 }, member_message: 'You can have KSh 40,000 now.', model_file: 'classifier.joblib',
  model_sha256: 'abcdef0123456789',
  trace: { effective: { amount_kes: 40000, term_months: 12 },
           checks: [{ check: 'affordability', passed: true, values: { instalment_kes: 3554, limit_kes: 15000 } },
                    { check: 'auto_limit', passed: false, values: { amount_kes: 60000 } },
                    { check: 'guarantor_capacity', passed: null, values: {} }],
           clarifications: { conditions: {}, asked: ['C1'], answered: ['C1'], returned: [] } },
}

describe('DecisionBody', () => {
  const out = renderToStaticMarkup(<DecisionBody d={d} />)

  it('shows every check, whichever way it went, with its values', () => {
    expect(out).toContain('Affordable')
    expect(out).toContain('instalment_kes: 3,554; limit_kes: 15,000')
    expect(out).toContain('Passed')
    expect(out).toContain('Failed')
    expect(out).toContain('Not worked out')
  })

  it('shows the SHAP drivers, the version, and what the member said', () => {
    expect(out).toContain('Monthly income')
    expect(out).toContain('2026.11.1')
    expect(out).toContain('term_months')
    expect(out).toContain('This conversation')
    expect(out).toContain('Verified by an officer')
  })

  it('says so when nothing was asked or said', () => {
    const quiet = { ...d, overrides: {}, trace: { ...d.trace, clarifications: { conditions: {}, asked: [], answered: [], returned: [] } } }
    const text = renderToStaticMarkup(<DecisionBody d={quiet} />)
    expect(text).toContain('Nothing was asked.')
    expect(text).toContain('every value came from the profile')
  })
})

describe('routes', () => {
  it('reaches the list and one decision', () => {
    expect(parse(paths.decisions())).toEqual({ screen: 'decisions' })
    expect(parse(paths.decision(7))).toEqual({ screen: 'decision', id: 7 })
    expect(parse('#/decisions/x').screen).toBe('notFound')
  })
})
