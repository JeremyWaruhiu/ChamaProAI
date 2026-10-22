import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { Me } from '../api/types'
import { AuthContext } from '../lib/auth'
import { InterviewList } from './InterviewList'

function render(user: Me | null) {
  return renderToStaticMarkup(
    <AuthContext.Provider value={{ user, signOut: () => {} }}>
      <InterviewList />
    </AuthContext.Provider>)
}

describe('Model & Evaluation link', () => {
  it('is shown to an admin', () => {
    const html = render({ username: 'admin', role: 'admin' })
    expect(html).toMatch(/<a href="#\/admin\/results"[^>]*>Model &amp; Evaluation<\/a>/)
  })

  it('is hidden from an officer', () => {
    const html = render({ username: 'wanjiru', role: 'officer' })
    expect(html).not.toContain('#/admin/results')
    expect(html).not.toContain('Model &amp; Evaluation')
  })
})

describe('header', () => {
  it('shows who is signed in, their role and a Sign out button', () => {
    const html = render({ username: 'wanjiru', role: 'officer' })
    expect(html).toContain('wanjiru')
    expect(html).toContain('Loan officer')
    expect(html).toMatch(/<button[^>]*>Sign out<\/button>/)
  })

  it('labels an admin as Administrator', () => {
    expect(render({ username: 'admin', role: 'admin' })).toContain('Administrator')
  })
})
