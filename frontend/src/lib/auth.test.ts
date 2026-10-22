import { describe, expect, it } from 'vitest'
import type { Me } from '../api/types'
import { redirectFor, safeNext } from './auth'
import { parse, paths } from './router'

const officer: Me = { username: 'wanjiru', role: 'officer' }
const admin: Me = { username: 'admin', role: 'admin' }

describe('redirect when unauthenticated', () => {
  it.each(['#/interviews/7/review', '#/interviews/3/record/12', '#/admin/results'])(
    'sends %s to login, remembering it', (hash) => {
      const to = redirectFor(hash, null)
      expect(to).toBe(paths.login(hash))
      expect(parse(to!)).toEqual({ screen: 'login', next: hash })
    })

  it('sends the list to plain login (nothing to return to)', () => {
    expect(redirectFor('#/', null)).toBe('#/login')
    expect(redirectFor('', null)).toBe('#/login')
  })

  it('leaves the login page alone', () => {
    expect(redirectFor('#/login', null)).toBeNull()
    expect(redirectFor(paths.login('#/interviews/7/review'), null)).toBeNull()
  })
})

describe('return to the original route after sign-in', () => {
  it('goes back to where the user was heading', () => {
    expect(redirectFor(paths.login('#/interviews/7/review'), officer)).toBe('#/interviews/7/review')
    expect(redirectFor(paths.login('#/interviews/3/record/12'), officer)).toBe('#/interviews/3/record/12')
  })

  it('goes to the list when there is nowhere to return to', () => {
    expect(redirectFor('#/login', officer)).toBe('#/')
  })

  it('never returns to login itself or leaves the app', () => {
    expect(safeNext('#/login?next=%23%2Flogin')).toBe('#/')
    expect(safeNext('https://evil.example/')).toBe('#/')
    expect(safeNext('//evil.example')).toBe('#/')
    expect(safeNext(null)).toBe('#/')
  })

  it('shows a signed-in user the screen they asked for', () => {
    expect(redirectFor('#/interviews/7/assessment', officer)).toBeNull()
    expect(redirectFor('#/', officer)).toBeNull()
  })
})

describe('admin-only routes', () => {
  it('routes an officer away from Model & Evaluation', () => {
    expect(redirectFor('#/admin/results', officer)).toBe('#/')
  })

  it('lets an admin in', () => {
    expect(redirectFor('#/admin/results', admin)).toBeNull()
  })

  it('returns an admin to the results page after sign-in', () => {
    expect(redirectFor(paths.login('#/admin/results'), admin)).toBe('#/admin/results')
  })

  it('does not return an officer to it after sign-in', () => {
    const next = redirectFor(paths.login('#/admin/results'), officer)!
    expect(redirectFor(next, officer)).toBe('#/')
  })
})
