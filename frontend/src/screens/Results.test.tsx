import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { Results } from '../api/types'
import { formatTime } from '../lib/format'
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

  it('says when the live figures were computed, when the server says', () => {
    const at = '2026-11-02T13:42:05.123+00:00'
    const out = renderToStaticMarkup(<ResultsBody data={{ generated_at: '2026-10-19T00:00:00Z', live: { ...live, computed_at: at } }} />)
    expect(out).toContain(`Computed at ${formatTime(at)}.`)
    expect(out).toContain('kept for up to a minute')
    expect(renderToStaticMarkup(<ResultsBody data={{ generated_at: '2026-10-19T00:00:00Z', live }} />))
      .not.toContain('Computed at')
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

  it('fills the RandomForest columns and states which model is better, and by how much', () => {
    const data: Results = {
      generated_at: '2026-11-02T00:00:00Z', live,
      model_card: { source: 's', estimator: 'hist_gradient_boosting' } as Results['model_card'],
      held_out: {
        source: 's', n_test: 10, auc_macro_ovr: 0.5683, macro_f1: 0.3674, comparator_macro_f1: 0.28,
        labels: ['Low', 'Medium', 'High'], confusion_matrix: null,
        per_class: { Low: { precision: 0.59, recall: 0.38 }, Medium: { precision: 0.31, recall: 0.26 }, High: { precision: 0.27, recall: 0.53 } },
      },
      random_forest: {
        source: 'models/random_forest.joblib scored on frame', notes: [],
        per_class: { Low: { precision: 0.5994, recall: 0.5175 }, Medium: { precision: 0.3191, recall: 0.3992 }, High: { precision: 0.2893, recall: 0.2823 } },
        versus_deployed: {
          auc_macro_ovr: { deployed: 0.5683, random_forest: 0.5808, difference: 0.0125, better: 'random_forest' },
          macro_f1: { deployed: 0.3674, random_forest: 0.3986, difference: 0.0312, better: 'random_forest' },
          high_recall: { deployed: 0.5323, random_forest: 0.2823, difference: -0.25, better: 'deployed' },
        },
      },
    }
    const out = renderToStaticMarkup(<ResultsBody data={data} />)
    const perClass = out.slice(out.indexOf('Per-class precision and recall'), out.indexOf('Top 10 features'))
    expect(perClass).toContain('0.599')                 // RandomForest Low precision
    expect(perClass).toContain('0.282')                 // RandomForest High recall
    expect(perClass).not.toContain(NOT_MEASURED)
    expect(out).toContain('Deployed (hist_gradient_boosting)')
    expect(out).toContain('Macro-F1: the RandomForest is higher by 0.0312.')
    expect(out).toContain('AUC (macro one-vs-rest): the RandomForest is higher by 0.0125.')
    expect(out).toContain('High-risk recall: the deployed model is higher by 0.2500.')
    expect(out).toContain('+0.0312')
    expect(out).toContain('trade-off')
  })

  it('keeps the comparison "not yet measured" until a RandomForest is exported', () => {
    const out = renderToStaticMarkup(<ResultsBody data={{ generated_at: '2026-11-02T00:00:00Z', live }} />)
    const card = out.slice(out.indexOf('Deployed model vs RandomForest'), out.indexOf('Confusion matrix'))
    expect(card).toContain(NOT_MEASURED)
    expect(card).not.toContain('is higher by')
  })
})
