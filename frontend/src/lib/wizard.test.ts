import { describe, expect, it } from 'vitest'
import type { Member } from '../api/types'
import {
  EMPTY_WIZARD, applicationBody, firstIncomplete, interviewBody, memberBody, ruleCeiling, stepErrors, type WizardDraft,
} from './wizard'

const TODAY = '2026-10-26'
const member: Member = { id: 4, member_no: 'M-0412', full_name: 'Grace Wanjiku', phone: null, joined_on: '2024-01-10',
  user_id: null, created_at: '2026-01-01T00:00:00Z' }
const complete: WizardDraft = {
  ...EMPTY_WIZARD, member, amount: '60,000', purpose: 'Dairy cow', term: '12', savings: '25000',
  age: '38', sex: 'female', education: '0', marital: 'married',
}

describe('wizard step: member', () => {
  it('needs an existing member chosen', () => {
    expect(stepErrors('member', EMPTY_WIZARD, TODAY)).toEqual({ member: expect.any(String) })
    expect(stepErrors('member', { ...EMPTY_WIZARD, member }, TODAY)).toEqual({})
  })

  it('checks every field of a new member', () => {
    const d: WizardDraft = { ...EMPTY_WIZARD, memberMode: 'new' }
    expect(Object.keys(stepErrors('member', d, TODAY)).sort()).toEqual(['full_name', 'joined_on', 'member_no'])
  })

  it('accepts a new member without a phone, and refuses a bad phone or a future date', () => {
    const ok: WizardDraft = { ...EMPTY_WIZARD, memberMode: 'new',
      newMember: { member_no: 'M-77', full_name: 'Peter Kamau', phone: '', joined_on: '2025-03-01' } }
    expect(stepErrors('member', ok, TODAY)).toEqual({})
    expect(stepErrors('member', { ...ok, newMember: { ...ok.newMember, phone: '0712 345 678' } }, TODAY)).toEqual({})
    expect(stepErrors('member', { ...ok, newMember: { ...ok.newMember, phone: '12345' } }, TODAY)).toHaveProperty('phone')
    expect(stepErrors('member', { ...ok, newMember: { ...ok.newMember, joined_on: '2026-10-27' } }, TODAY)).toHaveProperty('joined_on')
    expect(stepErrors('member', { ...ok, newMember: { ...ok.newMember, member_no: '-bad' } }, TODAY)).toHaveProperty('member_no')
  })
})

describe('wizard step: loan details', () => {
  it('lists every missing loan field', () => {
    expect(Object.keys(stepErrors('loan', EMPTY_WIZARD)).sort()).toEqual(['amount', 'purpose', 'savings', 'term'])
  })

  it.each([['0'], ['-5'], ['12.5'], ['abc'], ['100000001']])('refuses amount %j', (amount) => {
    expect(stepErrors('loan', { ...complete, amount })).toHaveProperty('amount')
  })

  it.each([['0'], ['121'], ['']])('refuses term %j', (term) => {
    expect(stepErrors('loan', { ...complete, term })).toHaveProperty('term')
  })

  it('accepts shillings typed with commas or spaces, and zero savings', () => {
    expect(stepErrors('loan', { ...complete, amount: '60 000', savings: '0' })).toEqual({})
  })
})

describe('wizard step: applicant form', () => {
  it('needs age 16-110, sex, education and marital status; education code 0 counts', () => {
    expect(Object.keys(stepErrors('applicant', EMPTY_WIZARD)).sort()).toEqual(['age', 'education', 'marital', 'sex'])
    expect(stepErrors('applicant', complete)).toEqual({})
    expect(stepErrors('applicant', { ...complete, age: '15' })).toEqual({ age: expect.any(String) })
  })
})

describe('the whole wizard', () => {
  it('finds the first unfinished step, and none when complete', () => {
    expect(firstIncomplete(EMPTY_WIZARD, TODAY)).toBe('member')
    expect(firstIncomplete({ ...complete, purpose: ' ' }, TODAY)).toBe('loan')
    expect(firstIncomplete(complete, TODAY)).toBeNull()
    expect(stepErrors('review', complete, TODAY)).toEqual({})
  })

  it('builds the member, interview and application the API expects', () => {
    expect(memberBody({ member_no: ' M-9 ', full_name: ' Ann ', phone: '0712-345-678', joined_on: '2025-01-01' }))
      .toEqual({ member_no: 'M-9', full_name: 'Ann', phone: '0712345678', joined_on: '2025-01-01' })
    expect(interviewBody({ ...complete, mode: 'practice', language: 'en' }, member.full_name)).toEqual({
      applicant_name: 'Grace Wanjiku', language: 'en', mode: 'practice',
      applicant: { age: 38, sex: 'female', education: 0, marital_status: 'married' },
    })
    expect(applicationBody(complete, 4, 17)).toEqual({
      member_id: 4, amount_requested_kes: 60000, purpose: 'Dairy cow', term_months: 12, sacco_savings_kes: 25000,
      interview_id: 17,
    })
  })

  it('knows the SACCO rule ceiling', () => {
    expect(ruleCeiling(25000)).toBe(75000)
  })
})
