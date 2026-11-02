import { describe, expect, it } from 'vitest'
import type { Versus } from '../api/types'
import { overall, verdict } from './compare'
import { NOT_MEASURED } from './measure'

const row = (deployed: number, rf: number, better: Versus['better']): Versus =>
  ({ deployed, random_forest: rf, difference: Math.round((rf - deployed) * 1e4) / 1e4, better })

describe('the deployed model against the RandomForest', () => {
  it('says which model is higher and by how much', () => {
    expect(verdict('macro_f1', row(0.3674, 0.3986, 'random_forest'))).toBe('Macro-F1: the RandomForest is higher by 0.0312.')
    expect(verdict('high_recall', row(0.5323, 0.2823, 'deployed'))).toBe('High-risk recall: the deployed model is higher by 0.2500.')
    expect(verdict('auc_macro_ovr', row(0.5, 0.5, 'tie'))).toBe('AUC (macro one-vs-rest): the two models are level.')
  })

  it('never invents a winner for an unmeasured metric', () => {
    expect(verdict('macro_f1', null)).toBe(`Macro-F1: ${NOT_MEASURED}`)
    expect(verdict('macro_f1', { deployed: 0.3, random_forest: null, difference: null, better: null })).toContain(NOT_MEASURED)
    expect(overall(null)).toBeNull()
    expect(overall({ macro_f1: row(0.3, 0.4, 'random_forest') })).toBeNull()      // the others unknown
  })

  it('calls a split result a trade-off, not a win', () => {
    expect(overall({
      auc_macro_ovr: row(0.5683, 0.5808, 'random_forest'), macro_f1: row(0.3674, 0.3986, 'random_forest'),
      high_recall: row(0.5323, 0.2823, 'deployed'),
    })).toContain('trade-off')
    expect(overall({
      auc_macro_ovr: row(0.5, 0.6, 'random_forest'), macro_f1: row(0.3, 0.3, 'tie'), high_recall: row(0.2, 0.3, 'random_forest'),
    })).toBe('The RandomForest is ahead on every measure here.')
  })
})
