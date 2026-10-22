import { describe, expect, it } from 'vitest'
import { parse, paths, type Route } from './router'

describe('parse', () => {
  it.each<[string, Route]>([
    ['', { screen: 'list' }],
    ['#', { screen: 'list' }],
    ['#/', { screen: 'list' }],
    ['#/interviews/7/record', { screen: 'record', id: 7, question: null }],
    ['#/interviews/7/record/12', { screen: 'record', id: 7, question: 12 }],
    ['#/interviews/7/review', { screen: 'review', id: 7 }],
    ['#/interviews/7/assessment', { screen: 'assessment', id: 7 }],
    ['#interviews/7/review', { screen: 'review', id: 7 }],
    ['#/interviews/7/review/', { screen: 'review', id: 7 }],
    ['#/admin/results', { screen: 'results' }],
    ['#/login', { screen: 'login', next: null }],
    ['#/login?next=%23%2Finterviews%2F7%2Freview', { screen: 'login', next: '#/interviews/7/review' }],
  ])('%s', (hash, route) => {
    expect(parse(hash)).toEqual(route)
  })

  it.each([
    '#/interviews/0/review', '#/interviews/-3/review', '#/interviews/abc/review',
    '#/interviews/1.5/review', '#/interviews/7', '#/interviews/7/unknown', '#/nowhere',
    '#/admin', '#/admin/results/x', '#/login/x',
  ])('falls back to the list for %s', (hash) => {
    expect(parse(hash)).toEqual({ screen: 'list' })
  })

  it('ignores a question number that is not a positive integer', () => {
    for (const n of ['0', '-1', '2.5', 'x']) {
      expect(parse(`#/interviews/7/record/${n}`)).toEqual({ screen: 'record', id: 7, question: null })
    }
  })
})

describe('paths', () => {
  it('builds the hashes the screens link to', () => {
    expect(paths.list()).toBe('#/')
    expect(paths.record(3)).toBe('#/interviews/3/record')
    expect(paths.record(3, 40)).toBe('#/interviews/3/record/40')
    expect(paths.review(3)).toBe('#/interviews/3/review')
    expect(paths.assessment(3)).toBe('#/interviews/3/assessment')
  })

  it('round-trips through parse', () => {
    expect(parse(paths.list())).toEqual({ screen: 'list' })
    expect(parse(paths.record(5, 9))).toEqual({ screen: 'record', id: 5, question: 9 })
    expect(parse(paths.review(5))).toEqual({ screen: 'review', id: 5 })
    expect(parse(paths.assessment(5))).toEqual({ screen: 'assessment', id: 5 })
  })
})
