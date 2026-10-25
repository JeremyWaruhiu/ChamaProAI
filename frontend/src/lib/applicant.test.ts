import { describe, expect, it } from 'vitest'
import { EMPTY_DRAFT, missingFields } from './applicant'

const complete = { ...EMPTY_DRAFT, age: '42', sex: 'female' as const, education: '0', marital: 'widowed' as const }

describe('missingFields', () => {
  it('lists every required field of an empty form', () => {
    expect(missingFields(EMPTY_DRAFT)).toEqual(['age (16 to 110)', 'sex', 'highest education', 'marital status'])
  })

  it('accepts a complete form, including education code 0 (none)', () => {
    expect(missingFields(complete)).toEqual([])
  })

  it.each(['15', '111', '4.5', ' '])('refuses age %j', (age) => {
    expect(missingFields({ ...complete, age })).toEqual(['age (16 to 110)'])
  })

  it('does not need the name', () => {
    expect(missingFields({ ...complete, name: '' })).toEqual([])
  })
})
