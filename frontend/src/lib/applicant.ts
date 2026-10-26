import type { Language, MaritalStatus, Sex } from '../api/types'
import { t } from '../strings'

/** The applicant form as typed, before it becomes an InterviewCreate. */
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

export type ApplicantField = 'age' | 'sex' | 'education' | 'marital'

/** Whether each required field is filled; the order is the form's. */
export function applicantProblems(d: Pick<Draft, ApplicantField>): ApplicantField[] {
  const age = Number(d.age)
  return ([
    !(d.age.trim() && Number.isInteger(age) && age >= 16 && age <= 110) && 'age',
    !d.sex && 'sex',
    d.education === '' && 'education',
    !d.marital && 'marital',
  ] as const).filter((x): x is ApplicantField => !!x)
}

/** What is still missing from the applicant form, in plain words; [] when complete. */
export function missingFields(d: Draft): string[] {
  return applicantProblems(d).map((f) => t.applicant.missing[f])
}
