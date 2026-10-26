import type { ApplicationCreate, InterviewCreate, Language, MaritalStatus, Member, MemberCreate, Mode, Sex } from '../api/types'
import { t } from '../strings'
import { applicantProblems } from './applicant'
import { parseShillings, todayYmd } from './format'

// The start-interview wizard: its draft, the steps, and what each step needs
// before the officer can move on. Pure, so it can be tested on its own.

export const STEPS = ['member', 'loan', 'applicant', 'setup', 'review'] as const
export type Step = typeof STEPS[number]

export type NewMember = { member_no: string; full_name: string; phone: string; joined_on: string }

export interface WizardDraft {
  memberMode: 'existing' | 'new'
  member: Member | null
  newMember: NewMember
  amount: string
  purpose: string
  term: string
  savings: string
  age: string
  sex: Sex | ''
  education: string
  marital: MaritalStatus | ''
  language: Language
  mode: Mode
}

export const EMPTY_WIZARD: WizardDraft = {
  memberMode: 'existing', member: null,
  newMember: { member_no: '', full_name: '', phone: '', joined_on: '' },
  amount: '', purpose: '', term: '', savings: '',
  age: '', sex: '', education: '', marital: '',
  language: 'kik', mode: 'live',
}

/** The same patterns the API checks (schemas.py). */
export const MEMBER_NO = /^[A-Za-z0-9][A-Za-z0-9/-]{0,31}$/
export const KENYAN_MOBILE = /^(\+254|0)[17]\d{8}$/
export const cleanPhone = (s: string) => s.replace(/[\s-]/g, '')

export type Errors = Partial<Record<string, string>>

const E = t.wizard.errors

function memberErrors(d: WizardDraft, today: string): Errors {
  if (d.memberMode === 'existing') return d.member ? {} : { member: E.chooseMember }
  const m = d.newMember
  const out: Errors = {}
  if (!MEMBER_NO.test(m.member_no.trim())) out.member_no = E.memberNo
  if (!m.full_name.trim() || m.full_name.trim().length > 200) out.full_name = E.fullName
  if (m.phone.trim() && !KENYAN_MOBILE.test(cleanPhone(m.phone))) out.phone = E.phone
  if (!/^\d{4}-\d{2}-\d{2}$/.test(m.joined_on) || m.joined_on > today) out.joined_on = E.joinedOn
  return out
}

function loanErrors(d: WizardDraft): Errors {
  const out: Errors = {}
  const amount = parseShillings(d.amount)
  if (amount === null || amount <= 0 || amount > 100_000_000) out.amount = E.amount
  if (!d.purpose.trim() || d.purpose.trim().length > 500) out.purpose = E.purpose
  const term = Number(d.term)
  if (!d.term.trim() || !Number.isInteger(term) || term < 1 || term > 120) out.term = E.term
  const savings = parseShillings(d.savings)
  if (savings === null || savings > 1_000_000_000) out.savings = E.savings
  return out
}

function applicantErrors(d: WizardDraft): Errors {
  return Object.fromEntries(applicantProblems(d).map((f) => [f, E[f]]))
}

/** What stops the officer leaving this step; {} when it is complete. */
export function stepErrors(step: Step, d: WizardDraft, today: string = todayYmd()): Errors {
  switch (step) {
    case 'member': return memberErrors(d, today)
    case 'loan': return loanErrors(d)
    case 'applicant': return applicantErrors(d)
    case 'setup': return {}
    case 'review': return { ...memberErrors(d, today), ...loanErrors(d), ...applicantErrors(d) }
  }
}

/** The first step with something missing, or null when the whole draft is ready. */
export function firstIncomplete(d: WizardDraft, today: string = todayYmd()): Step | null {
  return STEPS.find((s) => s !== 'review' && Object.keys(stepErrors(s, d, today)).length > 0) ?? null
}

/** The maximum the SACCO rule allows: three times savings (comparator.SAVINGS_MULTIPLIER). */
export const ruleCeiling = (savings: number) => savings * 3

// --- What the wizard sends ---------------------------------------------------------

export function memberBody(m: NewMember): MemberCreate {
  return {
    member_no: m.member_no.trim(),
    full_name: m.full_name.trim(),
    phone: m.phone.trim() ? cleanPhone(m.phone) : null,
    joined_on: m.joined_on,
  }
}

export function interviewBody(d: WizardDraft, memberName: string): InterviewCreate {
  if (!d.sex || !d.marital) throw new Error('applicant form incomplete')
  return {
    applicant_name: memberName,
    applicant: { age: Number(d.age), sex: d.sex, education: Number(d.education), marital_status: d.marital },
    language: d.language,
    mode: d.mode,
  }
}

export function applicationBody(d: WizardDraft, memberId: number, interviewId: number): ApplicationCreate {
  return {
    member_id: memberId,
    amount_requested_kes: parseShillings(d.amount)!,
    purpose: d.purpose.trim(),
    term_months: Number(d.term),
    sacco_savings_kes: parseShillings(d.savings)!,
    interview_id: interviewId,
  }
}
