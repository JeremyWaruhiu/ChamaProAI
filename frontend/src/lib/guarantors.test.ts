import { describe, expect, it } from 'vitest'
import { checkGuarantors, emptyGuarantor, toGuarantorIn, type GuarantorDraft } from './guarantors'

const g = (n: number, over: Partial<GuarantorDraft> = {}): GuarantorDraft => ({
  full_name: `Guarantor ${n}`, member_no: `M-10${n}`, phone: '0712345678', relationship: 'neighbour', amount: '20000', ...over,
})

describe('guarantor form validation', () => {
  it('accepts the right number of complete, different guarantors', () => {
    expect(checkGuarantors([g(1), g(2)], 2, 60000)).toEqual({ rows: [{}, {}], form: null, count: 0 })
  })

  it('flags every empty field', () => {
    const check = checkGuarantors([emptyGuarantor()], 1, 60000)
    expect(Object.keys(check.rows[0]).sort()).toEqual(['amount', 'full_name', 'member_no', 'phone', 'relationship'])
    expect(check.count).toBe(5)
  })

  it('needs exactly the number still required', () => {
    expect(checkGuarantors([g(1)], 2, 60000).form).toMatch(/exactly 2 guarantors/)
    expect(checkGuarantors([g(1), g(2), g(3)], 2, 60000).form).toMatch(/exactly 2 guarantors/)
    expect(checkGuarantors([g(1)], 1, 60000).form).toBeNull()
  })

  it('refuses the same member twice, whatever the case', () => {
    const check = checkGuarantors([g(1), g(2, { member_no: 'm-101' })], 2, 60000)
    expect(check.rows[0]).toEqual({})
    expect(check.rows[1].member_no).toMatch(/different member/)
  })

  it.each(['12345', '0812345678', '+25571234567', ''])('refuses phone %j', (phone) => {
    expect(checkGuarantors([g(1, { phone })], 1, 60000).rows[0]).toHaveProperty('phone')
  })

  it.each(['0712 345 678', '+254712345678', '0112-345-678'])('accepts phone %j', (phone) => {
    expect(checkGuarantors([g(1, { phone })], 1, 60000).rows[0]).toEqual({})
  })

  it('caps the amount guaranteed at the loan', () => {
    expect(checkGuarantors([g(1, { amount: '60,000' })], 1, 60000).rows[0]).toEqual({})
    expect(checkGuarantors([g(1, { amount: '60001' })], 1, 60000).rows[0].amount).toMatch(/KSh 60,000/)
    expect(checkGuarantors([g(1, { amount: '0' })], 1, 60000).rows[0]).toHaveProperty('amount')
  })

  it('sends clean values', () => {
    expect(toGuarantorIn([g(1, { full_name: '  Jane  ', phone: '0712 345 678', amount: '20,000' })])).toEqual([
      { full_name: 'Jane', member_no: 'M-101', phone: '0712345678', relationship: 'neighbour', amount_guaranteed_kes: 20000 },
    ])
  })
})
