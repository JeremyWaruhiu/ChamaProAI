// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApplyOptions, SaccoView } from '../api/types'
import { api } from '../api/client'
import { ToastProvider } from '../components/Toast'
import { ProfileForm, Registration, SaccoPanels } from './MySacco'

const OPTIONS: ApplyOptions = {
  sex: [{ value: 'female', label: 'Female' }, { value: 'male', label: 'Male' }],
  education: [{ value: 4, label: 'Secondary completed' }],
  marital_status: [{ value: 'married', label: 'Married' }],
  purposes: [], savings_multiplier: 3, min_tenure_months: 6, max_term_months: 120,
}
const entry = (id: number, entry_type: string, amount_kes: number, reference = `R-${id}`) =>
  ({ id, entry_type, amount_kes, posted_at: '2026-10-05T06:00:00+00:00', reference }) as SaccoView['accounts'][number]['entries'][number]
const VIEW: SaccoView = {
  member_id: 7, member_no: 'M-2001', full_name: 'Fictional Member', joined_on: '2020-01-01',
  profile: {
    date_of_birth: '1982-03-01', age: 44, sex: 'female', education: 4, marital_status: 'married', household_size: 5, children: 3,
    children_under5: 1, children_in_school: 2, monthly_income_kes: 18000, agri_income_kes: 0, income_sources: { farming: 1 },
    non_monetary_savings: null, purchases_last_12m: null, chama_loan_use: 2, lost_as_guarantor_chama: 0,
    confirmed_at: '2026-10-01T06:00:00+00:00', days_since_confirmed: 34,
    groups: { income: { source: 'member_update', updated_at: null, verified: false },
              household: { source: 'officer_verified', updated_at: null, verified: true } },
  },
  accounts: [
    { kind: 'deposits', balance_kes: 26000, entries: [entry(1, 'deposit', 500), entry(2, 'guarantee_recovery', -1500)] },
    { kind: 'share_capital', balance_kes: 3000, entries: [] },
    { kind: 'transactional', balance_kes: 0, entries: [entry(3, 'loan_disbursement', 60000)] },
  ],
  guarantee: { deposits_kes: 26000, guaranteed_kes: 10000, committed_kes: 0, capacity_kes: 16000 },
  my_guarantors: [{ id: 1, member_no: 'M-2002', full_name: 'Able Guarantor', created_at: '2026-01-01T00:00:00+00:00', has_capacity: true, capacity_kes: null },
                  { id: 2, member_no: 'M-2003', full_name: 'Tied Guarantor', created_at: '2026-01-01T00:00:00+00:00', has_capacity: false, capacity_kes: null }],
  i_guarantee: [{ id: 3, member_no: 'M-2004', full_name: 'Some Borrower', created_at: '2026-01-01T00:00:00+00:00', guaranteed_kes: 10000 }],
  loans: [{ id: 9, application_id: 3, principal_kes: 60000, disbursed_on: '2026-09-01', term_months: 18, monthly_instalment_kes: 3940,
            status: 'active', paid_kes: 3940, days_in_arrears: 12 }],
  notices: [],
}

beforeEach(() => vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true, addEventListener() {}, removeEventListener() {} }))))
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('My SACCO', () => {
  it('shows a guarantor the notice, and not to staff reading the same page', () => {
    const text = "You are now guaranteeing Wanjiru Kamau's loan of KSh 40,000."
    const view = { ...VIEW, notices: [{ id: 1, kind: 'guarantee_started', text, created_at: '2026-11-04T06:00:00+00:00' }] }
    render(<SaccoPanels view={view} options={OPTIONS} />)
    expect(screen.getByText('For your attention')).toBeTruthy()
    expect(screen.getByText(text)).toBeTruthy()
    cleanup()
    render(<SaccoPanels view={view} options={OPTIONS} staff />)
    expect(screen.queryByText(text)).toBeNull()
  })

  it('lets a guarantor set their own limit, and refuses a bad one', async () => {
    const saved = { ...VIEW, i_guarantee: [{ ...VIEW.i_guarantee[0], max_amount_kes: 12000 }] }
    const patch = vi.spyOn(api, 'setPledgeCeiling').mockResolvedValue(saved)
    const onView = vi.fn()
    render(<ToastProvider><SaccoPanels view={VIEW} options={OPTIONS} onView={onView} /></ToastProvider>)
    expect(screen.getByText('No limit set: not used for automatic loans')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Set limit' }))
    const input = screen.getByLabelText(/The most you will guarantee for Some Borrower/)
    fireEvent.change(input, { target: { value: 'lots' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(screen.getByText('Enter an amount of at least KSh 1.')).toBeTruthy()
    expect(patch).not.toHaveBeenCalled()
    fireEvent.change(input, { target: { value: '12000' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(onView).toHaveBeenCalledWith(saved))
    expect(patch).toHaveBeenCalledWith(3, 12000)
    patch.mockRestore()
  })

  it('shows staff the limit but no way to change it', () => {
    const view = { ...VIEW, i_guarantee: [{ ...VIEW.i_guarantee[0], max_amount_kes: 12000 }] }
    render(<SaccoPanels view={view} options={OPTIONS} staff />)
    expect(screen.getByText('Up to KSh 12,000')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Change' })).toBeNull()
  })

  it('says when the profile was last confirmed, and what has been checked', () => {
    render(<SaccoPanels view={VIEW} options={OPTIONS} />)
    expect(screen.getByText(/Last confirmed .* \(34 days ago\)/)).toBeTruthy()
    expect(screen.getByText('Your income: not yet checked')).toBeTruthy()
    expect(screen.getByText('Your household: checked')).toBeTruthy()
    expect(screen.getByText('18,000', { exact: false })).toBeTruthy()
    expect(screen.getByText('Use now')).toBeTruthy()
  })

  it('shows three balances with their entries, money out marked', () => {
    render(<SaccoPanels view={VIEW} options={OPTIONS} />)
    for (const name of ['Deposits', 'Share capital', 'Transactional']) expect(screen.getByText(name)).toBeTruthy()
    expect(screen.getAllByText('KSh 26,000').length).toBeGreaterThan(0)
    expect(screen.getByText('Recovered for a guarantee')).toBeTruthy()
    expect(screen.getByText('−KSh 1,500')).toBeTruthy()
    expect(screen.getByText('Last 2 entries')).toBeTruthy()
    expect(screen.getByText('No entries yet.')).toBeTruthy()
  })

  it('tells a member whether a guarantor can guarantee, never how much', () => {
    render(<SaccoPanels view={VIEW} options={OPTIONS} />)
    const able = screen.getByText('Able Guarantor').closest('li')!
    expect(within(able).getByText('Can guarantee')).toBeTruthy()
    expect(within(screen.getByText('Tied Guarantor').closest('li')!).getByText('Cannot guarantee now')).toBeTruthy()
    expect(screen.queryByText(/Capacity KSh/)).toBeNull()
    expect(screen.getByText('KSh 16,000')).toBeTruthy()      // their own
    expect(within(screen.getByText('Some Borrower').closest('li')!).getByText('KSh 10,000 on active loans')).toBeTruthy()
  })

  it('shows an officer the figures, who checked what, and what is missing', () => {
    const staff: SaccoView = { ...VIEW,
      my_guarantors: [{ ...VIEW.my_guarantors[0], capacity_kes: 42000 }],
      profile: { ...VIEW.profile, provenance: { age: 'verified', children: 'missing', chama_loan_use: 'missing' },
                 checks: { household: { by: 'j.mwangi', at: '2026-10-01T06:00:00+00:00' } } } }
    render(<SaccoPanels view={staff} options={OPTIONS} staff />)
    expect(screen.getByText('Capacity KSh 42,000')).toBeTruthy()
    expect(screen.getByText(/^j\.mwangi,/)).toBeTruthy()
    expect(screen.getByText(/2 details the classifier would read are still missing/)).toBeTruthy()
  })

  it('shows loan history with paid so far and arrears computed by the server', () => {
    render(<SaccoPanels view={VIEW} options={OPTIONS} />)
    expect(screen.getByText('KSh 3,940 repaid so far', { exact: false })).toBeTruthy()
    expect(screen.getByText('12 days behind')).toBeTruthy()
    expect(screen.getByText('Active')).toBeTruthy()
  })

  it('says so when there are no loans or guarantors yet', () => {
    render(<SaccoPanels view={{ ...VIEW, my_guarantors: [], i_guarantee: [], loans: [] }} options={OPTIONS} />)
    expect(screen.getByText('No loans yet.')).toBeTruthy()
    expect(screen.getByText(/Nobody has pledged/)).toBeTruthy()
  })
})

describe('the profile form', () => {
  it('sends what was typed, and has nowhere to type what the SACCO derives', async () => {
    const onSubmit = vi.fn(async () => {})
    render(<ProfileForm initial={{ ...emptyDraft() }} options={OPTIONS} submit="Save" failed="Failed" onSubmit={onSubmit} />)
    expect(screen.queryByLabelText(/SACCO loan/i)).toBeNull()
    fireEvent.change(screen.getByLabelText(/Total monthly income/), { target: { value: '18000' } })
    fireEvent.click(screen.getByRole('checkbox', { name: 'Farming' }))
    fireEvent.click(screen.getByRole('button', { name: /Save/ }))
    await waitFor(() => expect(onSubmit).toHaveBeenCalledOnce())
    const body = (onSubmit.mock.calls[0] as unknown as [Record<string, unknown>])[0]
    expect(body.monthly_income_kes).toBe(18000)
    expect((body.income_sources as Record<string, number>).farming).toBe(1)
  })

  it('stops on what cannot be sent', () => {
    const onSubmit = vi.fn(async () => {})
    render(<ProfileForm initial={{ ...emptyDraft() }} options={OPTIONS} submit="Save" failed="Failed" onSubmit={onSubmit} />)
    fireEvent.change(screen.getByLabelText(/Children under five/), { target: { value: 'two' } })
    fireEvent.click(screen.getByRole('button', { name: /Save/ }))
    expect(onSubmit).not.toHaveBeenCalled()
    expect(screen.getByText(/Enter a whole number/)).toBeTruthy()
  })
})

describe('the registration form', () => {
  it('saves once and goes on to My SACCO, or can be skipped', async () => {
    const fetch = vi.fn(async (url: string) => new Response(JSON.stringify(String(url).includes('apply-options') ? OPTIONS : VIEW), { status: 201 }))
    vi.stubGlobal('fetch', fetch)
    window.location.hash = '#/my/registration'
    render(<Registration />)
    const skip = await screen.findByRole('link', { name: 'Skip for now' })
    expect(skip.getAttribute('href')).toBe('#/my')
    fireEvent.click(screen.getByRole('button', { name: /Save my details/ }))
    await waitFor(() => expect(window.location.hash).toBe('#/my/sacco'))
    expect(fetch.mock.calls.some(([u]) => String(u).endsWith('/api/me/profile'))).toBe(true)
  })
})

function emptyDraft() {
  return { date_of_birth: '', sex: '' as const, education: '', marital_status: '' as const, household_size: '', children: '',
           children_under5: '', children_in_school: '', monthly_income_kes: '', agri_income_kes: '', income_sources: {},
           non_monetary_savings: {}, purchases_last_12m: {}, chama_loan_use: '', lost_as_guarantor_chama: '' }
}
