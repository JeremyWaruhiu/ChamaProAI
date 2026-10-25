import type { Language, MaritalStatus, Sex } from '../api/types'

/** The new-interview form as typed, before it becomes an InterviewCreate. */
export type Draft = {
  name: string
  age: string
  sex: Sex | ''
  education: string
  marital: MaritalStatus | ''
  language: Language
  practice: boolean
}

export const EMPTY_DRAFT: Draft = { name: '', age: '', sex: '', education: '', marital: '', language: 'kik', practice: false }

/** What is still missing from the applicant form, in plain words; [] when complete. */
export function missingFields(d: Draft): string[] {
  const age = Number(d.age)
  return [
    !(d.age.trim() && Number.isInteger(age) && age >= 16 && age <= 110) && 'age (16 to 110)',
    !d.sex && 'sex',
    d.education === '' && 'highest education',
    !d.marital && 'marital status',
  ].filter((x): x is string => !!x)
}
