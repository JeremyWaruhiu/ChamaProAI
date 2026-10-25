import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { Results } from '../api/types'
import { NOT_MEASURED } from '../lib/measure'
import { ResultsBody } from './Results'

const live: Results['live'] = {
  source: 'live database; practice interviews excluded', interview_count: 0, assessment_count: 0,
  practice_interview_count: 2,
  risk_class_distribution: { Low: 0, Medium: 0, High: 0 }, mean_extraction_completeness: null,
  decision_agreement: { rule: 'r', decisions: 0, agreements: 0, rate: null },
}

describe('ResultsBody', () => {
  it('renders an empty export as "not yet measured" throughout', () => {
    const out = renderToStaticMarkup(<ResultsBody data={{ generated_at: '2026-10-19T00:00:00Z', live }} />)
    expect(out).toContain(NOT_MEASURED)
    expect(out).not.toContain('NaN')
    expect(out).not.toContain('role="cell"')       // no confusion matrix drawn
  })

  it('says practice interviews are left out of the live stats', () => {
    const out = renderToStaticMarkup(<ResultsBody data={{ generated_at: '2026-10-19T00:00:00Z', live }} />)
    expect(out).toContain('Live interviews')
    expect(out).toContain('Practice interviews are left out of every figure here (2 held)')
  })

  it('shows null metrics as "not yet measured" next to measured ones', () => {
    const data: Results = {
      generated_at: '2026-10-19T00:00:00Z', live,
      held_out: {
        source: 's', validation: 'v', n_test: 10, auc_macro_ovr: null, macro_f1: 0.367,
        comparator_macro_f1: null, labels: ['Low', 'Medium', 'High'], confusion_matrix: null,
        per_class: { Low: { precision: 0.5, recall: null }, Medium: { precision: null, recall: 0.2 }, High: { precision: 0.1, recall: 0.5 } },
      },
    }
    const out = renderToStaticMarkup(<ResultsBody data={data} />)
    expect(out).toContain('0.367')
    const auc = out.slice(out.indexOf('AUC (macro one-vs-rest)'), out.indexOf('Macro-F1, model'))
    expect(auc).toContain(NOT_MEASURED)
    expect(auc).not.toMatch(/>0(\.0+)?</)
  })
})
