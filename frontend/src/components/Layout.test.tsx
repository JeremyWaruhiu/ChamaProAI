// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { InterviewSummary, Me } from '../api/types'
import { AuthContext } from '../lib/auth'
import { filterInterviews, matchApplications } from '../lib/selectors'
import { MemberLayout, StaffLayout } from './Layout'

beforeEach(() => vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true, addEventListener() {}, removeEventListener() {} }))))
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

function staff(user: Me, signOut = () => {}) {
  return render(
    <AuthContext.Provider value={{ user, signOut }}>
      <StaffLayout user={user} screen="home"><p>content</p></StaffLayout>
    </AuthContext.Provider>)
}

describe('staff layout', () => {
  it('shows who is signed in and their role badge, with profile and sign out in the menu', () => {
    const signOut = vi.fn()
    staff({ username: 'wanjiru', role: 'officer' }, signOut)
    const button = screen.getByRole('button', { name: 'Account menu for wanjiru' })
    expect(button.textContent).toContain('Loan officer')
    fireEvent.click(button)
    const menu = screen.getByRole('menu')
    expect(within(menu).getByRole('menuitem', { name: /Your profile/ }).getAttribute('href')).toBe('#/profile')
    fireEvent.click(within(menu).getByRole('menuitem', { name: /Sign out/ }))
    expect(signOut).toHaveBeenCalledOnce()
  })

  it('shows the administration section to an admin only', () => {
    staff({ username: 'admin', role: 'admin' })
    const nav = screen.getAllByRole('navigation', { name: 'Main navigation' })[0]
    expect(within(nav).getByRole('link', { name: /Model & Evaluation/ }).getAttribute('href')).toBe('#/admin/results')
    expect(within(nav).getByRole('link', { name: /Audit log/ })).toBeTruthy()
    cleanup()
    staff({ username: 'wanjiru', role: 'officer' })
    const officerNav = screen.getAllByRole('navigation', { name: 'Main navigation' })[0]
    expect(within(officerNav).queryByRole('link', { name: /Model & Evaluation/ })).toBeNull()
    expect(within(officerNav).queryByRole('link', { name: /Users/ })).toBeNull()
  })

  it('puts Start interview first and marks the current page', () => {
    staff({ username: 'wanjiru', role: 'officer' })
    const nav = screen.getAllByRole('navigation', { name: 'Main navigation' })[0]
    const links = within(nav).getAllByRole('link')
    expect(links[0].textContent).toContain('Start interview')
    expect(within(nav).getByRole('link', { name: /Home/ }).getAttribute('aria-current')).toBe('page')
  })

  it('collapses the sidebar to icons, keeping every link named', () => {
    staff({ username: 'wanjiru', role: 'officer' })
    fireEvent.click(screen.getByRole('button', { name: 'Collapse navigation' }))
    expect(screen.getByRole('button', { name: 'Expand navigation' }).getAttribute('aria-expanded')).toBe('false')
    const nav = screen.getAllByRole('navigation', { name: 'Main navigation' })[0]
    expect(within(nav).getByRole('link', { name: /Applications/ })).toBeTruthy()
  })
})

describe('member layout', () => {
  it('has no staff navigation at all', () => {
    const user: Me = { username: 'grace', role: 'member' }
    const { container } = render(
      <AuthContext.Provider value={{ user, signOut: () => {} }}>
        <MemberLayout user={user} screen="my"><p>x</p></MemberLayout>
      </AuthContext.Provider>)
    for (const h of ['#/app', '#/interviews', '#/applications', '#/members', '#/admin']) {
      expect(container.querySelector(`a[href^="${h}"]`)).toBeNull()
    }
    expect(screen.getByRole('link', { name: /My applications/ }).getAttribute('href')).toBe('#/my')
  })
})

describe('list filtering', () => {
  const iv = (id: number, over: Partial<InterviewSummary>): InterviewSummary => ({
    id, applicant_name: `Name ${id}`, created_at: '2026-10-26T08:00:00Z', status: 'open', question_set: 'v2',
    language: 'kik', mode: 'live', responses_recorded: 0, questions_total: 8,
    counts: { queued: 0, transcribing: 0, transcribed: 0, failed: 0 }, risk_class: null, decision: null, ...over,
  })
  const items = [iv(1, {}), iv(2, { status: 'assessed' }), iv(3, { mode: 'practice', applicant_name: 'Mary Wambui' })]

  it('filters interviews by status, practice and name', () => {
    expect(filterInterviews(items, '', 'open').map((x) => x.id)).toEqual([1, 3])
    expect(filterInterviews(items, '', 'assessed').map((x) => x.id)).toEqual([2])
    expect(filterInterviews(items, '', 'practice').map((x) => x.id)).toEqual([3])
    expect(filterInterviews(items, 'wambui', 'all').map((x) => x.id)).toEqual([3])
    expect(filterInterviews(items, '#2', 'all').map((x) => x.id)).toEqual([2])
  })

  it('finds applications by member name, number or id', () => {
    const apps = [{ id: 7, member_name: 'Peter Kamau', member_no: 'M-0412' }, { id: 8, member_name: 'Grace', member_no: 'M-9' }]
      .map((a) => ({ ...a, member_id: 1, amount_requested_kes: 1, term_months: 1, status: 'draft' as const,
        interview_id: null, risk_class: null, outcome: null, created_at: '', updated_at: '' }))
    expect(matchApplications(apps, 'kamau').map((a) => a.id)).toEqual([7])
    expect(matchApplications(apps, 'm-9').map((a) => a.id)).toEqual([8])
    expect(matchApplications(apps, '#8').map((a) => a.id)).toEqual([8])
    expect(matchApplications(apps, ' ')).toEqual([])
  })
})
