// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApplyOptions, MyMember } from '../api/types'
import { ApplyForm } from './Apply'

const OPTIONS: ApplyOptions = {
  sex: [{ value: 'female', label: 'Female' }, { value: 'male', label: 'Male' }],
  education: [{ value: 4, label: 'Secondary' }],
  marital_status: [{ value: 'married', label: 'Married' }],
  purposes: ['School fees', 'Other'], savings_multiplier: 3, min_tenure_months: 6, max_term_months: 120,
}
const KNOWN: MyMember = {
  member_no: 'V-00042', full_name: 'Fictional Volunteer', phone: '+254712345678', email: null, savings_kes: 20000,
  savings_status: 'self_declared', savings_label: 'Self-declared, pending verification', savings_limit_kes: 60000,
  joined_on: '2020-01-01', tenure_months: 80, age: 41, sex: 'female', education: 4, marital_status: 'married',
  applicant_complete: true, consent_current: true,
}
const CALENDAR = { today: '2026-11-04', last_date: '2027-02-02', times: [], timezone: 'Africa/Nairobi', holidays: [] }

beforeEach(() => { vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(CALENDAR), { status: 200 }))) })
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const field = (label: string | RegExp) => screen.getByLabelText(label) as HTMLInputElement

describe('fields already known', () => {
  it.each([
    ['Name', 'Fictional Volunteer'], ['Member number', 'V-00042'], ['Phone', '+254712345678'],
    ['SACCO savings', 'KSh 20,000'], ['Membership', '80 months, since 1 Jan 2020'],
  ])('%s is pre-filled and read-only', (label, value) => {
    render(<ApplyForm member={KNOWN} options={OPTIONS} />)
    expect(field(label).value).toBe(value)
    expect(field(label).readOnly).toBe(true)
  })

  it('shows savings as self-declared until they are verified', () => {
    render(<ApplyForm member={KNOWN} options={OPTIONS} />)
    expect(screen.getByText('Self-declared, pending verification')).toBeTruthy()
  })

  it('shows verified savings as verified', () => {
    render(<ApplyForm member={{ ...KNOWN, savings_status: 'verified' }} options={OPTIONS} />)
    expect(screen.getByText('Verified by the SACCO')).toBeTruthy()
    expect(screen.queryByText(/pending verification/)).toBeNull()
  })

  it('does not ask for the applicant form again', () => {
    render(<ApplyForm member={KNOWN} options={OPTIONS} />)
    expect(field('Age').readOnly).toBe(true)
    expect(field('Age').value).toBe('41')
    expect(field('Sex').value).toBe('Female')
    expect(field('Sex').tagName).toBe('INPUT')
  })
})

describe('fields not yet known', () => {
  const fresh: MyMember = { ...KNOWN, savings_kes: null, savings_status: 'none', savings_limit_kes: null, age: null, sex: null,
                            education: null, marital_status: null, applicant_complete: false }

  it('asks for savings and the applicant form, once', () => {
    render(<ApplyForm member={fresh} options={OPTIONS} />)
    expect(field(/Your SACCO savings/).readOnly).toBe(false)
    expect(field('Age').readOnly).toBe(false)
    expect(field('Sex').tagName).toBe('SELECT')
    expect(screen.getByText(/saved to your profile/)).toBeTruthy()
  })

  it('works out the limit from the savings typed', () => {
    render(<ApplyForm member={fresh} options={OPTIONS} />)
    expect(screen.getByText(/Enter your savings to see/)).toBeTruthy()
    fireEvent.change(field(/Your SACCO savings/), { target: { value: '10000' } })
    expect(screen.getByText('Your SACCO rule limit is KSh 30,000 (3 x savings)')).toBeTruthy()
  })
})

describe('the live hint and warnings', () => {
  it('states the limit and warns above it without blocking', () => {
    render(<ApplyForm member={KNOWN} options={OPTIONS} />)
    expect(screen.getByText('Your SACCO rule limit is KSh 60,000 (3 x savings)')).toBeTruthy()
    expect(screen.queryByText(/above your SACCO rule limit/)).toBeNull()
    fireEvent.change(field(/Amount/), { target: { value: '70000' } })
    expect(screen.getByText(/above your SACCO rule limit of KSh 60,000/)).toBeTruthy()
    expect((screen.getByRole('button', { name: /Apply and book/ }) as HTMLButtonElement).disabled).toBe(false)
  })

  it('warns about membership under six months', () => {
    render(<ApplyForm member={{ ...KNOWN, tenure_months: 2 }} options={OPTIONS} />)
    expect(screen.getByText(/2 months of membership/)).toBeTruthy()
  })

  it('offers text only with Other', () => {
    render(<ApplyForm member={KNOWN} options={OPTIONS} />)
    expect(screen.queryByLabelText(/What is the loan for/)).toBeNull()
    fireEvent.change(field(/Purpose/), { target: { value: 'Other' } })
    expect(screen.getByLabelText(/What is the loan for/)).toBeTruthy()
  })
})

describe('sending', () => {
  it('sends nothing until the date and time are chosen', () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify(CALENDAR), { status: 200 }))
    vi.stubGlobal('fetch', fetch)
    render(<ApplyForm member={KNOWN} options={OPTIONS} />)
    fireEvent.change(field(/Amount/), { target: { value: '1000' } })
    fireEvent.change(field(/Purpose/), { target: { value: 'School fees' } })
    fireEvent.change(field(/Term/), { target: { value: '6' } })
    fireEvent.click(screen.getByRole('button', { name: /Apply and book/ }))
    expect(screen.getByText(/Please fix 2 things/)).toBeTruthy()
    const posted = fetch.mock.calls.filter((c) => (c as unknown as [string, RequestInit])[1]?.method === 'POST')
    expect(posted).toEqual([])
  })
})
