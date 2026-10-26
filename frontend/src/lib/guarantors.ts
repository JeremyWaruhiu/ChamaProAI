import type { GuarantorIn } from '../api/types'
import { t } from '../strings'
import { parseShillings } from './format'
import { KENYAN_MOBILE, MEMBER_NO, cleanPhone } from './wizard'

// The member's guarantor form: exactly the number still needed, each a
// different SACCO member, each guaranteeing no more than the loan. The API
// checks the same rules and also refuses the member's own number.

export interface GuarantorDraft {
  full_name: string
  member_no: string
  phone: string
  relationship: string
  amount: string
}

export type GuarantorField = keyof GuarantorDraft

export const emptyGuarantor = (): GuarantorDraft =>
  ({ full_name: '', member_no: '', phone: '', relationship: '', amount: '' })

export interface GuarantorCheck {
  /** Per guarantor, the fields with a problem. */
  rows: Partial<Record<GuarantorField, string>>[]
  /** A problem with the form as a whole (the count). */
  form: string | null
  /** How many problems in all. */
  count: number
}

const E = t.guarantorForm.errors

export function checkGuarantors(rows: GuarantorDraft[], needed: number, cap: number): GuarantorCheck {
  const seen = new Set<string>()
  const out = rows.map((g) => {
    const e: Partial<Record<GuarantorField, string>> = {}
    const name = g.full_name.trim()
    if (!name || name.length > 200) e.full_name = E.fullName
    const no = g.member_no.trim()
    if (!MEMBER_NO.test(no)) e.member_no = E.memberNo
    else if (seen.has(no.toUpperCase())) e.member_no = E.duplicate
    else seen.add(no.toUpperCase())
    if (!KENYAN_MOBILE.test(cleanPhone(g.phone))) e.phone = E.phone
    const rel = g.relationship.trim()
    if (!rel || rel.length > 60) e.relationship = E.relationship
    const amount = parseShillings(g.amount)
    if (amount === null || amount <= 0 || amount > cap) e.amount = E.amount(cap)
    return e
  })
  const form = rows.length !== needed ? E.count(needed) : null
  const count = out.reduce((n, e) => n + Object.keys(e).length, 0) + (form ? 1 : 0)
  return { rows: out, form, count }
}

/** The body to submit; call only once checkGuarantors finds nothing. */
export function toGuarantorIn(rows: GuarantorDraft[]): GuarantorIn[] {
  return rows.map((g) => ({
    full_name: g.full_name.trim(),
    member_no: g.member_no.trim(),
    phone: cleanPhone(g.phone),
    relationship: g.relationship.trim(),
    amount_guaranteed_kes: parseShillings(g.amount)!,
  }))
}
