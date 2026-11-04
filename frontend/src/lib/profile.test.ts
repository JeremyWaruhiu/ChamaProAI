import { describe, expect, it } from 'vitest'
import type { ProfileOut } from '../api/types'
import { EMPTY_PROFILE, FLAG_KEYS, profileErrors, profileToDraft, toProfileBody } from './profile'

describe('the profile form', () => {
  it('may be left entirely blank, which sends nothing as known', () => {
    expect(profileErrors(EMPTY_PROFILE)).toEqual({})
    const body = toProfileBody(EMPTY_PROFILE)
    expect(Object.values(body).every((v) => v === null)).toBe(true)
  })

  it('never has a field for what the SACCO derives', () => {
    const body = toProfileBody(EMPTY_PROFILE)
    expect(body).not.toHaveProperty('sacco_loan_use')
    expect(body).not.toHaveProperty('lost_as_guarantor')
    expect(Object.keys(body)).toContain('lost_as_guarantor_chama')
  })

  it('refuses what is not a whole number, and accepts commas', () => {
    expect(profileErrors({ ...EMPTY_PROFILE, monthly_income_kes: 'a lot' }).monthly_income_kes).toBeTruthy()
    expect(profileErrors({ ...EMPTY_PROFILE, children: '-1' }).children).toBeTruthy()
    expect(profileErrors({ ...EMPTY_PROFILE, household_size: '0' }).household_size).toBeTruthy()
    expect(toProfileBody({ ...EMPTY_PROFILE, monthly_income_kes: '18,000' }).monthly_income_kes).toBe(18000)
  })

  it('refuses a birth date under 16', () => {
    expect(profileErrors({ ...EMPTY_PROFILE, date_of_birth: '2020-01-01' }).date_of_birth).toBeTruthy()
    expect(profileErrors({ ...EMPTY_PROFILE, date_of_birth: '1980-01-01' }).date_of_birth).toBeUndefined()
  })

  it('sends every flag of a group once any was touched, and none if none was', () => {
    const body = toProfileBody({ ...EMPTY_PROFILE, income_sources: { farming: true } })
    expect(Object.keys(body.income_sources!)).toEqual([...FLAG_KEYS.income_sources])
    expect(body.income_sources!.farming).toBe(1)
    expect(body.income_sources!.pension).toBe(0)
    expect(body.non_monetary_savings).toBeNull()
  })

  it('reads a saved profile back unchanged', () => {
    const saved: ProfileOut = { date_of_birth: '1982-03-01', sex: 'female', education: 0, marital_status: 'married',
      household_size: 5, children: 0, children_under5: null, children_in_school: null, monthly_income_kes: 18000,
      agri_income_kes: 0, income_sources: { farming: 1, employed: 0 }, non_monetary_savings: null, purchases_last_12m: null,
      chama_loan_use: 0, lost_as_guarantor_chama: 0, groups: {} }
    const d = profileToDraft(saved)
    for (const zero of [d.education, d.children, d.chama_loan_use, d.lost_as_guarantor_chama]) expect(zero).toBe('0')   // an answer, not a blank
    const back = toProfileBody(d)
    expect(back.monthly_income_kes).toBe(18000)
    expect(back.education).toBe(0)
    expect(back.children_under5).toBeNull()
    expect(back.chama_loan_use).toBe(0)
  })
})
