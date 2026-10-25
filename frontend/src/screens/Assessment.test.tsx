import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { Assessment } from '../api/types'
import { Shell } from '../components/Shell'
import { AuthContext } from '../lib/auth'
import { AuditLine, RecordedDecision } from './Assessment'

const a: Assessment = {
  id: 17, risk_class: 'Medium', probabilities: { Low: 0.2, Medium: 0.5, High: 0.3 },
  feature_vector: {}, contributions: [], extracted: {}, extraction_completeness: 0.9,
  features_populated: 36, features_total: 40, features_not_extractable: [],
  extraction_model: 'gemini-x', model_file: 'classifier.joblib', model_sha256: 'ab'.repeat(32),
  assessed_by: 'wanjiru', created_at: '2026-10-23T09:30:00Z',
}

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

  it('shows the practice banner on an interview screen', () => {
    const shell = (practice: boolean) => renderToStaticMarkup(
      <AuthContext.Provider value={{ user: null, signOut: () => {} }}>
        <Shell title="t" interviewId={3} step="review" practice={practice}>body</Shell>
      </AuthContext.Provider>)
    expect(shell(true)).toContain('Practice interview.')
    expect(shell(false)).not.toContain('Practice interview.')
  })
})
