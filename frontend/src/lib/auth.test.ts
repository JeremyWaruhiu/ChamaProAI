import { describe, expect, it } from 'vitest'
import type { Me } from '../api/types'
import { canOpen, homeFor, redirectFor, safeNext } from './auth'
import { parse, paths } from './router'

const officer: Me = { username: 'wanjiru', role: 'officer' }
const admin: Me = { username: 'admin', role: 'admin' }
const member: Me = { username: 'grace', role: 'member' }

const STAFF_ROUTES = ['#/app', '#/app/start', '#/interviews', '#/interviews/7/record/2', '#/interviews/7/review',
  '#/interviews/7/assessment', '#/applications', '#/applications/3', '#/members', '#/members/4']
const ADMIN_ROUTES = ['#/admin', '#/admin/users', '#/admin/audit', '#/admin/results']
const MEMBER_ROUTES = ['#/my', '#/my/applications/3']

describe('each role starts at its own home', () => {
  it('sends officers, admins and members to different places', () => {
    expect(homeFor('officer')).toBe('#/app')
    expect(homeFor('admin')).toBe('#/admin')
    expect(homeFor('member')).toBe('#/my')
  })
})

describe('signed out', () => {
  it('shows the public landing page and the login page', () => {
    expect(redirectFor('#/', null)).toBeNull()
    expect(redirectFor('', null)).toBeNull()
    expect(redirectFor('#/login', null)).toBeNull()
    expect(redirectFor(paths.login('#/interviews/7/review'), null)).toBeNull()
  })

  it.each([...STAFF_ROUTES, ...ADMIN_ROUTES, ...MEMBER_ROUTES, '#/profile'])('sends %s to login, remembering it', (hash) => {
    const to = redirectFor(hash, null)
    expect(to).toBe(paths.login(hash))
    expect(parse(to!)).toEqual({ screen: 'login', next: hash })
  })

  it('sends an unknown address to the landing page', () => {
    expect(redirectFor('#/nowhere', null)).toBe('#/')
  })
})

describe('a member cannot reach staff or admin routes', () => {
  it.each([...STAFF_ROUTES, ...ADMIN_ROUTES])('redirects a member from %s to the portal', (hash) => {
    expect(redirectFor(hash, member)).toBe('#/my')
    expect(canOpen(parse(hash).screen, 'member')).toBe(false)
  })

  it.each([...MEMBER_ROUTES, '#/profile', '#/'])('lets a member open %s', (hash) => {
    expect(redirectFor(hash, member)).toBeNull()
  })

  it('never returns a member to a staff page after sign-in', () => {
    expect(redirectFor(paths.login('#/applications/3'), member)).toBe('#/my')
    expect(redirectFor(paths.login('#/my/applications/3'), member)).toBe('#/my/applications/3')
  })
})

describe('officers', () => {
  it.each(STAFF_ROUTES)('may open %s', (hash) => {
    expect(redirectFor(hash, officer)).toBeNull()
  })

  it.each(ADMIN_ROUTES)('are routed away from admin page %s', (hash) => {
    expect(redirectFor(hash, officer)).toBe('#/app')
  })

  it.each(MEMBER_ROUTES)('are routed away from member page %s', (hash) => {
    expect(redirectFor(hash, officer)).toBe('#/app')
  })
})

describe('admins', () => {
  it.each([...STAFF_ROUTES, ...ADMIN_ROUTES, '#/profile'])('may open %s', (hash) => {
    expect(redirectFor(hash, admin)).toBeNull()
  })

  it('are routed away from the member portal', () => {
    expect(redirectFor('#/my', admin)).toBe('#/admin')
  })
})

describe('return to the original route after sign-in', () => {
  it('goes back to where the user was heading', () => {
    expect(redirectFor(paths.login('#/interviews/7/review'), officer)).toBe('#/interviews/7/review')
    expect(redirectFor(paths.login('#/interviews/3/record/12'), officer)).toBe('#/interviews/3/record/12')
    expect(redirectFor(paths.login('#/admin/results'), admin)).toBe('#/admin/results')
  })

  it('goes to the role home when there is nowhere to return to', () => {
    expect(redirectFor('#/login', officer)).toBe('#/app')
    expect(redirectFor('#/login', admin)).toBe('#/admin')
    expect(redirectFor('#/login', member)).toBe('#/my')
  })

  it('never returns to login, the landing page, a forbidden page, or off the app', () => {
    expect(safeNext('#/login?next=%23%2Flogin', officer)).toBe('#/app')
    expect(safeNext('#/', officer)).toBe('#/app')
    expect(safeNext('#/admin/users', officer)).toBe('#/app')
    expect(safeNext('https://evil.example/', officer)).toBe('#/app')
    expect(safeNext('//evil.example', admin)).toBe('#/admin')
    expect(safeNext(null, member)).toBe('#/my')
  })

  it('sends a signed-in user from an unknown address to their home', () => {
    expect(redirectFor('#/nowhere', officer)).toBe('#/app')
    expect(redirectFor('#/nowhere', member)).toBe('#/my')
  })
})
