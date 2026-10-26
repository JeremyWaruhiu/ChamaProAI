// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { MyApplication as Mine } from '../api/types'
import { emptyGuarantor, type GuarantorDraft } from '../lib/guarantors'
import { GuarantorForm, MyApplication } from './MyApplication'

beforeEach(() => vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true, addEventListener() {}, removeEventListener() {} }))))
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

function Harness({ needed, onSubmit }: { needed: number; onSubmit: () => void }) {
  const [rows, setRows] = useState<GuarantorDraft[]>(() => Array.from({ length: needed }, emptyGuarantor))
  return <GuarantorForm rows={rows} setRows={setRows} needed={needed} cap={60000} onSubmit={onSubmit} />
}

function fill(i: number, values: Partial<Record<'name' | 'no' | 'phone' | 'rel' | 'amount', string>>) {
  const set = (k: string, v: string) => fireEvent.change(document.getElementById(`g${i}-${k}`)!, { target: { value: v } })
  Object.entries(values).forEach(([k, v]) => set(k, v!))
}

describe('guarantor form', () => {
  it('asks for exactly the number still needed', () => {
    render(<Harness needed={3} onSubmit={() => {}} />)
    expect(screen.getAllByRole('group').map((g) => g.querySelector('legend')!.textContent))
      .toEqual(['Guarantor 1 of 3', 'Guarantor 2 of 3', 'Guarantor 3 of 3'])
    expect(screen.getByRole('button', { name: 'Submit 3 guarantors' })).toBeTruthy()
  })

  it('shows every problem and sends nothing until the form is right', () => {
    const onSubmit = vi.fn()
    render(<Harness needed={2} onSubmit={onSubmit} />)
    fireEvent.click(screen.getByRole('button', { name: 'Submit 2 guarantors' }))
    expect(onSubmit).not.toHaveBeenCalled()
    expect(screen.getByRole('alert').textContent).toContain('Please fix 10 things in the form.')
    expect(document.getElementById('g0-phone')!.getAttribute('aria-invalid')).toBe('true')

    fill(0, { name: 'Jane Njeri', no: 'M-201', phone: '0712 345 678', rel: 'Sister', amount: '30000' })
    fill(1, { name: 'John Mwangi', no: 'm-201', phone: '0798765432', rel: 'Neighbour', amount: '70000' })
    fireEvent.click(screen.getByRole('button', { name: 'Submit 2 guarantors' }))
    expect(onSubmit).not.toHaveBeenCalled()
    const second = screen.getAllByRole('group')[1]
    expect(within(second).getByText('Each guarantor must be a different member.')).toBeTruthy()
    expect(within(second).getByText(/up to KSh 60,000/)).toBeTruthy()

    fill(1, { no: 'M-202', amount: '30000' })
    fireEvent.click(screen.getByRole('button', { name: 'Submit 2 guarantors' }))
    expect(onSubmit).toHaveBeenCalledOnce()
  })
})

const mine = (over: Partial<Mine> = {}): Mine => ({
  id: 4, amount_requested_kes: 60000, purpose: 'School fees and farm inputs', term_months: 18,
  status: 'guarantor_required', status_label: 'Guarantors needed', mode: 'practice',
  created_at: '2026-10-20T08:00:00Z', updated_at: '2026-10-21T08:00:00Z',
  timeline: [{ status: 'draft', label: 'Application started', at: '2026-10-20T08:00:00Z' }],
  outcome: 'approve_with_guarantor', approved_amount_kes: 60000, guarantors_required: 2, guarantors_still_needed: 2,
  member_message: 'Please add two guarantors who are SACCO members.',
  reasons: ['Your regular farm income counted in your favour.', 'Not owning land or buildings counted against your application.'],
  guarantors: [], ...over,
})

describe('member application detail', () => {
  it('shows the outcome, the officer’s message, the reasons and what happens next, never a score', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(mine()), { status: 200 })))
    render(<MyApplication id={4} />)
    expect(await screen.findByRole('heading', { name: 'School fees and farm inputs' })).toBeTruthy()
    const page = document.body.textContent!
    for (const s of ['Approved with guarantors', 'From your loan officer', 'Please add two guarantors who are SACCO members.',
      'Your regular farm income counted in your favour.', 'What happens next', 'Add your guarantors below.',
      'This is a practice application']) {
      expect(page).toContain(s)
    }
    for (const forbidden of [/probabilit/i, /risk/i, /shap/i, /%/, /officer notes/i]) expect(page).not.toMatch(forbidden)
    expect(screen.getByRole('list', { name: 'Progress of your application' })).toBeTruthy()
  })

  it('submits the guarantors and shows the confirmation, then each one being checked', async () => {
    const after = mine({ status: 'guarantor_submitted', status_label: 'Guarantors being checked', guarantors_still_needed: 0,
      guarantors: [
        { full_name: 'Jane Njeri', member_no: 'M-201', phone: '0712345678', relationship: 'Sister', amount_guaranteed_kes: 30000, status: 'pending', submitted_at: '' },
        { full_name: 'John Mwangi', member_no: 'M-202', phone: '0798765432', relationship: 'Neighbour', amount_guaranteed_kes: 30000, status: 'pending', submitted_at: '' },
      ] })
    const fetch = vi.fn(async (_url: string, init?: RequestInit) =>
      new Response(JSON.stringify(init?.method === 'POST' ? after : mine()), { status: init?.method === 'POST' ? 201 : 200 }))
    vi.stubGlobal('fetch', fetch)
    render(<MyApplication id={4} />)
    await screen.findByRole('heading', { name: 'Add 2 guarantors' })
    fill(0, { name: 'Jane Njeri', no: 'M-201', phone: '0712345678', rel: 'Sister', amount: '30000' })
    fill(1, { name: 'John Mwangi', no: 'M-202', phone: '0798765432', rel: 'Neighbour', amount: '30000' })
    fireEvent.click(screen.getByRole('button', { name: 'Submit 2 guarantors' }))

    expect(await screen.findByText('Guarantors submitted')).toBeTruthy()
    const [url, init] = fetch.mock.calls.at(-1)!
    expect(url).toBe('/api/me/applications/4/guarantors')
    expect(JSON.parse(String(init!.body)).guarantors).toHaveLength(2)
    await waitFor(() => expect(screen.getAllByText('Being checked')).toHaveLength(2))
    expect(screen.queryByRole('button', { name: /Submit/ })).toBeNull()
  })
})
