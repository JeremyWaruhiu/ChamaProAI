import type { ApplicantForm, Language, MaritalStatus, MyApplicationCreate, MyMember, MyPractice, MyResponse, Sex } from '../api/types'
import { t } from '../strings'
import { applicantProblems } from './applicant'
import { parseShillings } from './format'

// The member's loan application: what they type, the live hint and warnings,
// and the request body. Their name, number, phone, savings and tenure are not
// here: the API takes them from their record and refuses them in the body.

export interface ApplyDraft {
  amount: string
  purpose: string
  purposeOther: string
  term: string
  language: Language
  date: string
  time: string
  savings: string
  age: string
  sex: Sex | ''
  education: string
  marital: MaritalStatus | ''
}

export const EMPTY_APPLY: ApplyDraft = {
  amount: '', purpose: '', purposeOther: '', term: '', language: 'kik', date: '', time: '',
  savings: '', age: '', sex: '', education: '', marital: '',
}

export type ApplyField = keyof ApplyDraft

/** The form as it opens: what the profile already says about the applicant is filled in. */
export function draftFor(member: MyMember): ApplyDraft {
  return {
    ...EMPTY_APPLY, age: member.age === null ? '' : String(member.age), sex: member.sex ?? '',
    education: member.education === null ? '' : String(member.education), marital: member.marital_status ?? '',
  }
}

const E = t.apply.errors

/** The savings the limit is worked out from: on the record, or just typed. */
export function savingsFor(d: ApplyDraft, member: MyMember): number | null {
  return member.savings_kes ?? parseShillings(d.savings)
}

/** KSh limit under the SACCO rule, or null until savings are known. */
export function ruleLimit(d: ApplyDraft, member: MyMember, multiplier: number): number | null {
  const savings = savingsFor(d, member)
  return savings === null ? null : savings * multiplier
}

/** Warnings only: an amount over the limit or short membership never stops the form. */
export function applyWarnings(d: ApplyDraft, member: MyMember, multiplier: number, minTenure: number): string[] {
  const out: string[] = []
  const amount = parseShillings(d.amount)
  const limit = ruleLimit(d, member, multiplier)
  if (amount !== null && limit !== null && amount > limit) out.push(t.apply.overLimit(limit))
  if (member.tenure_months < minTenure) out.push(t.apply.shortTenure(member.tenure_months, minTenure))
  return out
}

/** What stops the application being sent; {} when it can go. */
export function applyErrors(d: ApplyDraft, member: MyMember, maxTerm: number): Partial<Record<ApplyField, string>> {
  const e: Partial<Record<ApplyField, string>> = {}
  const amount = parseShillings(d.amount)
  if (amount === null || amount <= 0) e.amount = E.amount
  if (!d.purpose) e.purpose = E.purpose
  if (d.purpose === 'Other' && !d.purposeOther.trim()) e.purposeOther = E.purposeOther
  const term = Number(d.term)
  if (!Number.isInteger(term) || term < 1 || term > maxTerm) e.term = E.term(maxTerm)
  if (!d.date) e.date = E.date
  if (!d.time) e.time = E.time
  if (member.savings_kes === null && parseShillings(d.savings) === null) e.savings = E.savings
  if (!member.applicant_complete) {
    for (const f of applicantProblems(d)) e[f] = t.applicant.missing[f]
  }
  return e
}

/** The request body; call only once applyErrors finds nothing. */
export function toApplicationBody(d: ApplyDraft, member: MyMember): MyApplicationCreate {
  const body: MyApplicationCreate = {
    amount_requested_kes: parseShillings(d.amount)!, purpose: d.purpose, term_months: Number(d.term),
    language: d.language, date: d.date, time: d.time,
  }
  if (d.purpose === 'Other') body.purpose_other = d.purposeOther.trim()
  if (member.savings_kes === null) body.declared_savings_kes = parseShillings(d.savings)!
  if (!member.applicant_complete) body.applicant = toApplicantForm(d)
  return body
}

export const toApplicantForm = (d: Pick<ApplyDraft, 'age' | 'sex' | 'education' | 'marital'>): ApplicantForm => ({
  age: Number(d.age), sex: d.sex as Sex, education: Number(d.education), marital_status: d.marital as MaritalStatus,
})

/** How a question is shown: Kikuyu where it exists; otherwise English, saying Kikuyu answers are fine. */
export function practiceQuestion(q: { text_en: string; text_kik: string }, language: Language):
  { text: string; lang: 'ki' | 'en'; gloss: string | null; kikuyuNote: boolean } {
  const kikuyu = q.text_kik.trim()
  if (language === 'en') return { text: q.text_en, lang: 'en', gloss: null, kikuyuNote: false }
  return kikuyu
    ? { text: kikuyu, lang: 'ki', gloss: q.text_en, kikuyuNote: false }
    : { text: q.text_en, lang: 'en', gloss: null, kikuyuNote: true }
}

export const waiting = (r: MyResponse) => r.status === 'queued' || r.status === 'transcribing'

/** Why the interview cannot be submitted yet, or null. */
export function submitBlocked(p: MyPractice, unsaved: number): string | null {
  const missing = p.questions.length - p.responses.length
  if (missing > 0) return t.practice.blockedMissing(missing)
  if (p.responses.some(waiting)) return t.practice.blockedWaiting
  if (p.responses.some((r) => r.status === 'failed' || !r.transcript?.trim())) return t.practice.blockedText
  if (unsaved > 0) return t.practice.blockedUnsaved
  return null
}
