import { describe, expect, it } from 'vitest'
import type { Question } from '../api/types'
import { domainLabel, topicsOf } from './domains'

const q = (order: number, topic: string): Question =>
  ({ id: `x${order}`, version: 'v2', topic, order, text_en: '', text_kik: '', features: [] })

describe('topics', () => {
  it('labels every v2 topic', () => {
    for (const t of ['household', 'income', 'income_sources', 'savings_in_kind', 'purchases',
      'guarantorship', 'sacco_borrowing', 'chama_borrowing']) {
      expect(domainLabel(t)).not.toBe('Other')
    }
  })

  it('falls back to "Other" for an unknown or empty topic', () => {
    expect(domainLabel('weather')).toBe('Other')
    expect(domainLabel('')).toBe('Other')
    expect(domainLabel(null)).toBe('Other')
  })

  it('lists a set\'s topics once each, in interview order', () => {
    expect(topicsOf([q(1, 'household'), q(2, 'household'), q(3, 'income'), q(4, 'household')]))
      .toEqual([{ key: 'household', label: 'Household' }, { key: 'income', label: 'Income' }])
  })
})
