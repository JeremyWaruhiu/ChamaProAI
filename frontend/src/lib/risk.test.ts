import { describe, expect, it } from 'vitest'
import { BORDERLINE_POINTS, RISK_MEANING, closeness, recommendation, riskTone } from './risk'

describe('closeness (the borderline rule)', () => {
  it('ranks the classes by probability whatever the key order', () => {
    const c = closeness({ High: 0.2, Low: 0.5, Medium: 0.3 })
    expect(c.first).toEqual(['Low', 0.5])
    expect(c.second).toEqual(['Medium', 0.3])
    expect(c.gapPoints).toBe(20)
    expect(c.borderline).toBe(false)
  })

  it('is borderline at exactly the threshold, inclusive', () => {
    expect(BORDERLINE_POINTS).toBe(10)
    // 0.55 - 0.45 is 0.10000000000000003 in floating point; still exactly 10 points
    const c = closeness({ Low: 0.55, Medium: 0.45, High: 0 })
    expect(c.gapPoints).toBe(10)
    expect(c.borderline).toBe(true)
  })

  it('is not borderline just above the threshold', () => {
    const c = closeness({ Low: 0.501, Medium: 0.4, High: 0.099 })
    expect(c.gapPoints).toBe(10.1)
    expect(c.borderline).toBe(false)
  })

  it('rounds the gap to one decimal place', () => {
    expect(closeness({ Low: 0.4123, Medium: 0.3456, High: 0.2421 }).gapPoints).toBe(6.7)
  })

  it('treats a tie as borderline', () => {
    const c = closeness({ Low: 0.4, Medium: 0.4, High: 0.2 })
    expect(c.gapPoints).toBe(0)
    expect(c.borderline).toBe(true)
  })
})

describe('recommendation', () => {
  it.each([
    ['Low', 'Approve on standard terms'],
    ['Medium', 'Refer to the loan committee'],
    ['High', 'Decline, or refer for manual review'],
  ])('gives the SACCO meaning of %s', (riskClass, text) => {
    expect(recommendation(riskClass, false)).toBe(text)
    expect(RISK_MEANING[riskClass as keyof typeof RISK_MEANING]).toBe(text)
  })

  it('always refers a borderline call, whatever the class', () => {
    for (const riskClass of ['Low', 'Medium', 'High']) {
      expect(recommendation(riskClass, true)).toBe('Refer to the loan committee (borderline)')
    }
  })

  it('passes an unknown class through rather than inventing advice', () => {
    expect(recommendation('Unknown', false)).toBe('Unknown')
  })
})

describe('riskTone', () => {
  it('maps classes to tones and anything else to none', () => {
    expect([riskTone('Low'), riskTone('Medium'), riskTone('High')]).toEqual(['low', 'medium', 'high'])
    expect([riskTone(null), riskTone(undefined), riskTone('low')]).toEqual(['none', 'none', 'none'])
  })
})
