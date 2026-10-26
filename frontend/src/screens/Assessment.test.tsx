import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { Assessment, Comparator } from '../api/types'
import { Shell } from '../components/Shell'
import { AuthContext } from '../lib/auth'
import { AuditLine, ComparatorPanel, DecisionForm, RecordedDecision } from './Assessment'

const a: Assessment = {
  id: 17, risk_class: 'Medium', probabilities: { Low: 0.2, Medium: 0.5, High: 0.3 },
  feature_vector: {}, contributions: [], extracted: {}, extraction_completeness: 0.9,
  features_populated: 36, features_total: 40, features_not_extractable: [],
  extraction_model: 'gemini-x', model_file: 'classifier.joblib', model_sha256: 'ab'.repeat(32),
  assessed_by: 'wanjiru', created_at: '2026-10-23T09:30:00Z',
}
const text = (html: string) => html.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&amp;/g, '&').replace(/\s+/g, ' ')

describe('audit line', () => {
  it('names the assessment, time, classifier, hash, extraction model and assessor', () => {
    const html = renderToStaticMarkup(<AuditLine a={a} />)
    expect(html).toContain('Assessment 17')
    expect(html).toContain('assessed by wanjiru')
    expect(html).toContain('classifier classifier.joblib')
    expect(html).toContain(`title="${a.model_sha256}"`)
    expect(html).toContain('sha256 abababababab')
    expect(html).toContain('extraction gemini-x')
    expect(html).toContain('stored permanently')
  })

  it('says so when the assessor is not recorded', () => {
    expect(renderToStaticMarkup(<AuditLine a={{ ...a, assessed_by: null }} />))
      .toContain('assessed by unknown (recorded before sign-in existed)')
  })
})

describe('practice labelling', () => {
  const d = { decision: 'approve' as const, note: null, created_at: '2026-10-23T09:40:00Z' }

  it('labels a practice decision', () => {
    const html = renderToStaticMarkup(<RecordedDecision d={d} risk="Low" borderline={false} practice />)
    expect(html).toContain('Practice: ')
    expect(html).toContain('A practice decision')
  })

  it('leaves a live decision unlabelled', () => {
    expect(renderToStaticMarkup(<RecordedDecision d={d} risk="Low" borderline={false} practice={false} />))
      .not.toMatch(/[Pp]ractice/)
  })

  it('shows the practice banner and badge on an interview screen', () => {
    const shell = (practice: boolean) => renderToStaticMarkup(
      <AuthContext.Provider value={{ user: null, signOut: () => {} }}>
        <Shell title="t" interviewId={3} step="review" practice={practice}>body</Shell>
      </AuthContext.Provider>)
    expect(shell(true)).toContain('Practice interview.')
    expect(text(shell(true))).toContain(' Practice ')
    expect(shell(false)).not.toMatch(/[Pp]ractice/)
  })
})

describe('recorded decision with an outcome', () => {
  it('shows the outcome, amounts, member message and notes, and whether it differs from the model', () => {
    const html = text(renderToStaticMarkup(<RecordedDecision practice={false} risk="Low" borderline={false} d={{
      decision: 'approve', outcome: 'approve_reduced', approved_amount_kes: 40000, note: 'checked payslips',
      officer_notes: 'checked payslips', member_message: 'Approved for less.', decided_by: 'wanjiru',
      created_at: '2026-10-23T09:40:00Z',
    }} />))
    expect(html).toContain('Approve a reduced amount')
    expect(html).toContain('Approved amount: KSh 40,000')
    expect(html).toContain('Approved for less.')
    expect(html).toContain('checked payslips')
    expect(html).toContain('Decided by wanjiru')
    expect(html).not.toContain('differs from the model')
  })

  it('flags a decision that differs from the model', () => {
    const html = renderToStaticMarkup(<RecordedDecision practice={false} risk="High" borderline={false}
      d={{ decision: 'approve', outcome: 'approve', note: null, created_at: '2026-10-23T09:40:00Z' }} />)
    expect(html).toContain('differs from the model')
  })
})

// --- Comparator --------------------------------------------------------------------

const comparator = (over: Partial<Comparator> = {}): Comparator => ({
  rule: 'r', max_borrowable_kes: 75000, amount_requested_kes: 60000, tenure_months: 30, verified_guarantors: 0,
  conditions: [
    { name: 'savings_multiple', label: 'Amount requested is at most 3 x SACCO savings', result: 'pass',
      detail: 'KSh 60,000 requested; maximum KSh 75,000', agreement: 'agree' },
    { name: 'guarantors', label: 'At least 2 guarantors', result: 'pending', detail: 'no guarantors submitted yet', agreement: 'pending' },
    { name: 'tenure', label: "At least 6 months' membership", result: 'fail', detail: '3 month(s)', agreement: 'diverge' },
  ],
  result: 'fail', rule_recommendation: 'decline', model_recommendation: 'approve', agreement: 'diverge', mode: 'live',
  ...over,
})

describe('comparator display', () => {
  it('shows every condition with its pass, fail or pending result and its agreement', () => {
    const html = renderToStaticMarkup(<ComparatorPanel c={comparator()} />)
    expect(html.match(/data-result="pass"/g)).toHaveLength(1)
    expect(html.match(/data-result="pending"/g)).toHaveLength(1)
    expect(html.match(/data-result="fail"/g)).toHaveLength(1)
    const t = text(html)
    for (const s of ['Amount requested is at most 3 x SACCO savings', 'At least 2 guarantors', "At least 6 months' membership",
      'Pass', 'Pending', 'Fail', 'Agrees with the model', 'Differs from the model', 'Not yet known',
      'Overall: Fails', 'Rule: decline', 'Maximum under the rule: KSh 75,000', '30 months of membership']) {
      expect(t).toContain(s)
    }
  })

  it('reads as pending, approving once guarantors are verified', () => {
    const t = text(renderToStaticMarkup(<ComparatorPanel c={comparator({ result: 'pending',
      rule_recommendation: 'approve_with_guarantors', agreement: 'agree' })} />))
    expect(t).toContain('Overall: Pending')
    expect(t).toContain('Rule: approve once guarantors are verified')
    expect(t).toContain('Agrees with the model')
  })

  it('says no comparison is made when the model referred', () => {
    expect(text(renderToStaticMarkup(<ComparatorPanel c={comparator({ result: 'pass', rule_recommendation: 'approve',
      agreement: 'undetermined', model_recommendation: 'refer' })} />))).toContain('Model referred: no comparison')
  })

  it('carries the practice badge on a practice application', () => {
    expect(text(renderToStaticMarkup(<ComparatorPanel c={comparator({ mode: 'practice' })} />))).toContain('Practice')
    expect(renderToStaticMarkup(<ComparatorPanel c={comparator()} />)).not.toMatch(/[Pp]ractice/)
  })
})

// --- Decision panel ------------------------------------------------------------------

describe('decision panel', () => {
  const form = (hasApplication: boolean) => renderToStaticMarkup(
    <DecisionForm interviewId={3} name="Grace" practice={false} onDecided={async () => {}}
                  requested={hasApplication ? 60000 : null} hasApplication={hasApplication} />)

  it('offers the five outcomes, officer notes and a member message', () => {
    const html = form(true)
    expect(html.match(/name="outcome"/g)).toHaveLength(5)
    const t = text(html)
    for (const s of ['Approve', 'Approve with guarantors', 'Approve a reduced amount', 'Refer to loan committee', 'Decline',
      'Officer notes', 'Never shown to the member', 'Message to the member', 'The full KSh 60,000 requested.']) {
      expect(t).toContain(s)
    }
    expect(html).not.toMatch(/disabled=""[^>]*name="outcome"/)
  })

  it('disables the application-only outcomes when there is no application', () => {
    const html = form(false)
    expect(html.match(/<input[^>]*disabled=""[^>]*name="outcome"/g)).toHaveLength(2)
    expect(text(html)).toContain('Needs a loan application')
  })
})
