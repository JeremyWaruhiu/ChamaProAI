// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { StartInterview } from './StartInterview'

const FORM = {
  sex: [{ value: 'female', label: 'Female' }, { value: 'male', label: 'Male' }],
  education: [{ value: 0, label: 'No formal education' }, { value: 4, label: 'Secondary completed' }],
  marital_status: [{ value: 'married', label: 'Married / living with partner' }],
}

let calls: { url: string; init?: RequestInit }[] = []

beforeEach(() => {
  calls = []
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true, addEventListener() {}, removeEventListener() {} })))
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init })
    const body = url.startsWith('/api/applicant-form') ? FORM
      : url === '/api/members' ? { id: 31, member_no: 'M-77', full_name: 'Peter Kamau', phone: null, joined_on: '2025-03-01', user_id: null, created_at: '' }
        : url === '/api/interviews' ? { id: 90, status: 'open' }
          : url === '/api/applications' ? { id: 5 } : []
    return new Response(JSON.stringify(body), { status: url === '/api/applicant-form' || init?.method !== 'POST' ? 200 : 201 })
  }))
  window.location.hash = '#/app/start'
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const next = () => fireEvent.click(screen.getByRole('button', { name: /Continue/ }))
const type = (label: RegExp, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } })

describe('start-interview wizard', () => {
  it('will not leave the member step until a member is chosen or added', async () => {
    render(<StartInterview memberId={null} />)
    expect(screen.getByRole('heading', { name: 'Who is applying?' })).toBeTruthy()
    next()
    expect(screen.getByRole('alert').textContent).toContain('Please fix 1 thing below')
    expect(screen.getByText('Choose a member, or add a new one.')).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Who is applying?' })).toBeTruthy()

    fireEvent.click(screen.getByLabelText('New member'))
    next()
    expect(screen.getByRole('alert').textContent).toContain('Please fix 3 things below')
    expect(screen.getByLabelText('Member number').getAttribute('aria-invalid')).toBe('true')
  })

  it('walks member → loan → applicant → interview → begin, validating each step, and starts the interview', async () => {
    render(<StartInterview memberId={null} />)
    fireEvent.click(screen.getByLabelText('New member'))
    type(/^Member number/, 'M-77')
    type(/^Full name/, 'Peter Kamau')
    type(/^Date joined/, '2025-03-01')
    next()

    expect(await screen.findByRole('heading', { name: 'Loan details' })).toBeTruthy()
    next()
    expect(screen.getByRole('alert').textContent).toContain('Please fix 4 things below')
    type(/Amount requested/, '60,000')
    type(/Repayment term/, '18')
    type(/Purpose of the loan/, 'School fees')
    type(/SACCO savings balance/, '10000')
    expect(screen.getByText(/more than the KSh 30,000 the SACCO rule allows/)).toBeTruthy()
    next()

    expect(await screen.findByRole('heading', { name: 'Applicant form' })).toBeTruthy()
    await screen.findByLabelText('Age')
    next()
    expect(screen.getByRole('alert').textContent).toContain('Please fix 4 things below')
    type(/^Age/, '15')
    fireEvent.click(screen.getByLabelText('Male'))
    fireEvent.change(screen.getByLabelText('Highest level of education'), { target: { value: '0' } })
    fireEvent.change(screen.getByLabelText('Marital status'), { target: { value: 'married' } })
    next()
    expect(screen.getByText('Enter an age from 16 to 110.')).toBeTruthy()
    type(/^Age/, '41')
    next()

    expect(await screen.findByRole('heading', { name: 'Language and mode' })).toBeTruthy()
    fireEvent.click(screen.getByLabelText(/Practice interview/))
    next()

    expect(await screen.findByRole('heading', { name: 'Check and begin' })).toBeTruthy()
    expect(screen.getByText(/Peter Kamau \(M-77\) — new member/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Begin interview/ }))

    await waitFor(() => expect(window.location.hash).toBe('#/interviews/90/record/1'))
    const posts = calls.filter((c) => c.init?.method === 'POST')
    expect(posts.map((c) => c.url)).toEqual(['/api/members', '/api/interviews', '/api/applications'])
    expect(JSON.parse(String(posts[1].init!.body))).toEqual({ applicant_name: 'Peter Kamau', language: 'kik', mode: 'practice',
      applicant: { age: 41, sex: 'male', education: 0, marital_status: 'married' } })
    expect(JSON.parse(String(posts[2].init!.body))).toEqual({ member_id: 31, amount_requested_kes: 60000, purpose: 'School fees',
      term_months: 18, sacco_savings_kes: 10000, interview_id: 90 })
  })
})
