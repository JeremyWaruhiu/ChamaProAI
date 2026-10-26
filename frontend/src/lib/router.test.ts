import { describe, expect, it } from 'vitest'
import { parse, paths, type Route } from './router'

describe('parse', () => {
  it.each<[string, Route]>([
    ['', { screen: 'landing' }],
    ['#', { screen: 'landing' }],
    ['#/', { screen: 'landing' }],
    ['#/login', { screen: 'login', next: null }],
    ['#/login?next=%23%2Finterviews%2F7%2Freview', { screen: 'login', next: '#/interviews/7/review' }],
    ['#/profile', { screen: 'profile' }],
    ['#/app', { screen: 'home' }],
    ['#/app/start', { screen: 'start', memberId: null }],
    ['#/app/start?member=12', { screen: 'start', memberId: 12 }],
    ['#/app/start?member=x', { screen: 'start', memberId: null }],
    ['#/interviews', { screen: 'interviews' }],
    ['#/interviews/7/record', { screen: 'record', id: 7, question: null }],
    ['#/interviews/7/record/12', { screen: 'record', id: 7, question: 12 }],
    ['#/interviews/7/review', { screen: 'review', id: 7 }],
    ['#/interviews/7/assessment', { screen: 'assessment', id: 7 }],
    ['#interviews/7/review', { screen: 'review', id: 7 }],
    ['#/interviews/7/review/', { screen: 'review', id: 7 }],
    ['#/applications', { screen: 'applications', status: null }],
    ['#/applications?status=assessed', { screen: 'applications', status: 'assessed' }],
    ['#/applications/4', { screen: 'application', id: 4 }],
    ['#/members', { screen: 'members' }],
    ['#/members/9', { screen: 'member', id: 9 }],
    ['#/admin', { screen: 'admin' }],
    ['#/admin/users', { screen: 'users' }],
    ['#/admin/audit', { screen: 'audit' }],
    ['#/admin/results', { screen: 'results' }],
    ['#/my', { screen: 'my' }],
    ['#/my/applications/3', { screen: 'myApplication', id: 3 }],
  ])('%s', (hash, route) => {
    expect(parse(hash)).toEqual(route)
  })

  it.each([
    '#/interviews/0/review', '#/interviews/-3/review', '#/interviews/abc/review',
    '#/interviews/1.5/review', '#/interviews/7', '#/interviews/7/unknown', '#/nowhere',
    '#/admin/results/x', '#/login/x', '#/applications/0', '#/my/applications', '#/app/x',
  ])('treats %s as not found', (hash) => {
    expect(parse(hash)).toEqual({ screen: 'notFound' })
  })

  it('ignores a question number that is not a positive integer', () => {
    for (const n of ['0', '-1', '2.5', 'x']) {
      expect(parse(`#/interviews/7/record/${n}`)).toEqual({ screen: 'record', id: 7, question: null })
    }
  })
})

describe('paths', () => {
  it('builds the hashes the screens link to', () => {
    expect(paths.landing()).toBe('#/')
    expect(paths.home()).toBe('#/app')
    expect(paths.start()).toBe('#/app/start')
    expect(paths.start(5)).toBe('#/app/start?member=5')
    expect(paths.record(3)).toBe('#/interviews/3/record')
    expect(paths.record(3, 40)).toBe('#/interviews/3/record/40')
    expect(paths.review(3)).toBe('#/interviews/3/review')
    expect(paths.assessment(3)).toBe('#/interviews/3/assessment')
    expect(paths.applications('guarantor_submitted')).toBe('#/applications?status=guarantor_submitted')
    expect(paths.myApplication(2)).toBe('#/my/applications/2')
  })

  it('round-trips through parse', () => {
    expect(parse(paths.landing())).toEqual({ screen: 'landing' })
    expect(parse(paths.record(5, 9))).toEqual({ screen: 'record', id: 5, question: 9 })
    expect(parse(paths.review(5))).toEqual({ screen: 'review', id: 5 })
    expect(parse(paths.assessment(5))).toEqual({ screen: 'assessment', id: 5 })
    expect(parse(paths.application(5))).toEqual({ screen: 'application', id: 5 })
    expect(parse(paths.applications('assessed'))).toEqual({ screen: 'applications', status: 'assessed' })
    expect(parse(paths.start(8))).toEqual({ screen: 'start', memberId: 8 })
    expect(parse(paths.member(5))).toEqual({ screen: 'member', id: 5 })
    expect(parse(paths.myApplication(5))).toEqual({ screen: 'myApplication', id: 5 })
  })
})
