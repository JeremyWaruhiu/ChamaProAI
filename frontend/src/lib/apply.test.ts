import { describe, expect, it } from 'vitest'
import type { MyMember, MyPractice, MyResponse } from '../api/types'
import { EMPTY_APPLY, applyErrors, applyWarnings, practiceQuestion, ruleLimit, submitBlocked, toApplicationBody, type ApplyDraft } from './apply'

const MEMBER: MyMember = {
  member_no: 'V-00001', full_name: 'Fictional Volunteer', phone: '+254712345678', email: null, savings_kes: 20000,
  savings_status: 'self_declared', savings_label: 'Self-declared, pending verification', savings_limit_kes: 60000,
  joined_on: '2020-01-01', tenure_months: 80, age: 41, sex: 'female', education: 4, marital_status: 'married',
  applicant_complete: true, consent_current: true,
}
const DRAFT: ApplyDraft = { ...EMPTY_APPLY, amount: '30,000', purpose: 'School fees', term: '12', date: '2026-11-10', time: '09:00' }

describe('the savings rule', () => {
  it('is three times the savings on the record, or just typed', () => {
    expect(ruleLimit(DRAFT, MEMBER, 3)).toBe(60000)
    const none = { ...MEMBER, savings_kes: null, savings_status: 'none' as const }
    expect(ruleLimit(DRAFT, none, 3)).toBeNull()
    expect(ruleLimit({ ...DRAFT, savings: '5,000' }, none, 3)).toBe(15000)
  })

  it('warns about too large an amount and short membership, without stopping the form', () => {
    expect(applyWarnings(DRAFT, MEMBER, 3, 6)).toEqual([])
    const over = { ...DRAFT, amount: '60001' }
    const newcomer = { ...MEMBER, tenure_months: 2 }
    expect(applyWarnings(over, MEMBER, 3, 6)[0]).toContain('KSh 60,000')
    expect(applyWarnings(DRAFT, newcomer, 3, 6)[0]).toContain('2 months')
    expect(applyWarnings(over, newcomer, 3, 6)).toHaveLength(2)
    expect(applyErrors(over, newcomer, 120)).toEqual({})    // warned, not blocked
  })
})

describe('what the member must enter', () => {
  it('needs the amount, purpose, term, date and time', () => {
    expect(Object.keys(applyErrors(EMPTY_APPLY, MEMBER, 120)).sort()).toEqual(['amount', 'date', 'purpose', 'term', 'time'])
  })

  it('needs text with Other', () => {
    expect(applyErrors({ ...DRAFT, purpose: 'Other' }, MEMBER, 120).purposeOther).toBeTruthy()
    expect(applyErrors({ ...DRAFT, purpose: 'Other', purposeOther: 'Roof' }, MEMBER, 120)).toEqual({})
  })

  it('asks for savings and the form only when the record has none', () => {
    const fresh: MyMember = { ...MEMBER, savings_kes: null, applicant_complete: false }
    expect(Object.keys(applyErrors(DRAFT, fresh, 120)).sort()).toEqual(['age', 'education', 'marital', 'savings', 'sex'])
  })
})

describe('the request body', () => {
  it('never carries what is already known: the API refuses those fields', () => {
    const body = toApplicationBody(DRAFT, MEMBER)
    expect(Object.keys(body).sort()).toEqual(['amount_requested_kes', 'date', 'language', 'purpose', 'term_months', 'time'])
    expect(body.amount_requested_kes).toBe(30000)
    for (const known of ['full_name', 'member_no', 'phone', 'savings_kes', 'sacco_savings_kes', 'joined_on', 'tenure_months']) {
      expect(body).not.toHaveProperty(known)
    }
  })

  it('declares savings and the form only the first time', () => {
    const fresh: MyMember = { ...MEMBER, savings_kes: null, applicant_complete: false }
    const body = toApplicationBody({ ...DRAFT, savings: '20000', age: '41', sex: 'female', education: '4', marital: 'married' }, fresh)
    expect(body.declared_savings_kes).toBe(20000)
    expect(body.applicant).toEqual({ age: 41, sex: 'female', education: 4, marital_status: 'married' })
  })
})

describe('how a practice question is shown', () => {
  const noKikuyu = { text_en: 'How many people live in your household?', text_kik: '' }

  it('shows English with a note in a Kikuyu interview, while question set v2 has no Kikuyu', () => {
    expect(practiceQuestion(noKikuyu, 'kik')).toEqual({ text: noKikuyu.text_en, lang: 'en', gloss: null, kikuyuNote: true })
  })

  it('needs no note in an English interview', () => {
    expect(practiceQuestion(noKikuyu, 'en').kikuyuNote).toBe(false)
  })

  it('uses Kikuyu wording as soon as it exists', () => {
    const q = { text_en: 'English', text_kik: 'Gĩkũyũ' }
    expect(practiceQuestion(q, 'kik')).toEqual({ text: 'Gĩkũyũ', lang: 'ki', gloss: 'English', kikuyuNote: false })
  })
})

describe('submitBlocked', () => {
  const questions = Array.from({ length: 8 }, (_, i) => ({ order: i + 1, topic: 'x', text_en: 'q', text_kik: '' }))
  const answer = (n: number, over: Partial<MyResponse> = {}): MyResponse =>
    ({ id: n, sentence_no: n, source: 'typed', status: 'transcribed', transcript: 'a', edited: false, duration_s: null, ...over })
  const all = questions.map((q) => answer(q.order))
  const practice = (responses: MyResponse[]) => ({ questions, responses } as unknown as MyPractice)

  it('waits for every answer, its transcription and its text', () => {
    expect(submitBlocked(practice(all), 0)).toBeNull()
    expect(submitBlocked(practice(all.slice(1)), 0)).toContain('remaining question')
    expect(submitBlocked(practice([answer(1, { status: 'queued' }), ...all.slice(1)]), 0)).toContain('transcribed')
    expect(submitBlocked(practice([answer(1, { status: 'failed', transcript: null }), ...all.slice(1)]), 0)).toContain('no text')
    expect(submitBlocked(practice(all), 1)).toContain('corrections')
  })
})
