import { describe, expect, it } from 'vitest'
import { extractedFacts, featureLabel, featureValue } from './features'

// The classifier's feature contract, as built by build_vector() in
// scripts/score_interview.py.
const CLASSIFIER_FEATURES = [
  'age', 'household_size', 'children', 'children_under5', 'children_in_school',
  'log_monthly_income', 'income_missing', 'log_agri_income', 'education',
  'sacco_loan_use', 'chama_loan_use', 'is_female',
  'marital_married', 'marital_single', 'marital_widowed', 'marital_divorced',
  ...Array.from({ length: 11 }, (_, i) => `B3A__${i + 1}`),
  ...Array.from({ length: 5 }, (_, i) => `F1__${i + 1}`),
  ...Array.from({ length: 6 }, (_, i) => `B1L__${i + 1}`),
  'E3B__3', 'E3B__7',
]

describe('featureLabel', () => {
  it('has a plain-language label for every one of the 40 classifier features', () => {
    expect(CLASSIFIER_FEATURES).toHaveLength(40)
    const raw = CLASSIFIER_FEATURES.filter((f) => featureLabel(f) === f)
    expect(raw).toEqual([])
    expect(new Set(CLASSIFIER_FEATURES.map(featureLabel)).size).toBe(40)
  })

  it.each([
    ['log_monthly_income', 'Monthly income'],
    ['B3A__1', 'Income from farming'],
    ['B3A__10', 'Income from other sources'],
    ['B3A__11', 'Has no source of income'],
    ['F1__1', 'Owns land or buildings'],
    ['B1L__6', 'Bought livestock in the last year'],
    ['E3B__3', 'Lost money as a SACCO guarantor'],
    ['E3B__7', 'Lost money as a chama guarantor'],
  ])('labels %s as "%s"', (feature, label) => {
    expect(featureLabel(feature)).toBe(label)
  })

  it('shows an unknown feature by its code', () => {
    expect(featureLabel('Z9__1')).toBe('Z9__1')
  })
})

describe('featureValue', () => {
  it('says "not stated" for a missing value', () => {
    expect(featureValue('age', null)).toBe('not stated')
    expect(featureValue('age', Number.NaN)).toBe('not stated')
  })

  it('turns log income back into shillings', () => {
    expect(featureValue('log_monthly_income', Math.log1p(8000))).toBe('KSh 8,000')
    expect(featureValue('log_agri_income', 0)).toBe('KSh 0')
  })

  it('formats counts, codes and flags', () => {
    expect(featureValue('age', 41.6)).toBe('42 years')
    expect(featureValue('household_size', 6)).toBe('6 people')
    expect(featureValue('education', 4)).toBe('secondary complete')
    expect(featureValue('sacco_loan_use', 2)).toBe('using now')
    expect(featureValue('is_female', 1)).toBe('female')
    expect(featureValue('income_missing', 1)).toBe('not given')
    expect(featureValue('F1__2', 1)).toBe('yes')
    expect(featureValue('F1__2', 0)).toBe('no')
  })

  it('falls back to the number for an out-of-range code or unknown feature', () => {
    expect(featureValue('education', 99)).toBe('99')
    expect(featureValue('Z9__1', 3.5)).toBe('3.5')
  })
})

describe('extractedFacts', () => {
  it('reports what was heard and what was not stated', () => {
    const { heard, notStated } = extractedFacts({
      age: 42, monthly_income_kes: 15000, income_sources: { farming: 1, own_business: 1, pension: 0 },
      marital_status: 'married',
    })
    expect(heard).toContainEqual({ label: 'Age', value: '42 years' })
    expect(heard).toContainEqual({ label: 'Monthly income', value: 'KSh 15,000' })
    expect(heard).toContainEqual({ label: 'Income sources', value: 'farming, own business' })
    expect(heard).toContainEqual({ label: 'Marital status', value: 'married' })
    expect(heard).toContainEqual({ label: 'Owns', value: 'none mentioned' })
    expect(notStated).toContain('Household size')
    expect(notStated).not.toContain('Age')
  })

  it('copes with an empty or malformed object', () => {
    const { heard, notStated } = extractedFacts({ income_sources: 'garbage', age: 'forty' })
    expect(heard).toContainEqual({ label: 'Income sources', value: 'none mentioned' })
    expect(notStated).toContain('Age')
    expect(notStated).toContain('Marital status')
  })
})
