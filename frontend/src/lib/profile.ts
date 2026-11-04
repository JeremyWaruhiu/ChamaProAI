import type { MaritalStatus, ProfileBody, ProfileOut, Sex } from '../api/types'
import { t } from '../strings'

// The member's profile form: what they type, before anything is sent. The flag
// keys are score_interview's, in its order; the API refuses any other.

export const FLAG_KEYS = {
  income_sources: ['farming', 'employed', 'casual_worker', 'own_business', 'social_transfer', 'renting_out',
    'investments', 'pension', 'remittances', 'other', 'none'],
  non_monetary_savings: ['land_or_buildings', 'livestock', 'jewellery', 'digital_assets', 'agroforestry'],
  purchases_last_12m: ['land_or_plot', 'new_house', 'house_materials', 'business_equipment', 'farm_equipment', 'livestock'],
} as const

export type FlagGroup = keyof typeof FLAG_KEYS
const NUMBERS = ['household_size', 'children', 'children_under5', 'children_in_school', 'monthly_income_kes', 'agri_income_kes'] as const

export interface ProfileDraft {
  date_of_birth: string
  sex: Sex | ''
  education: string
  marital_status: MaritalStatus | ''
  household_size: string
  children: string
  children_under5: string
  children_in_school: string
  monthly_income_kes: string
  agri_income_kes: string
  income_sources: Record<string, boolean>
  non_monetary_savings: Record<string, boolean>
  purchases_last_12m: Record<string, boolean>
  chama_loan_use: string
  lost_as_guarantor_chama: string
}

export const EMPTY_PROFILE: ProfileDraft = {
  date_of_birth: '', sex: '', education: '', marital_status: '', household_size: '', children: '', children_under5: '',
  children_in_school: '', monthly_income_kes: '', agri_income_kes: '', income_sources: {}, non_monetary_savings: {},
  purchases_last_12m: {}, chama_loan_use: '', lost_as_guarantor_chama: '',
}

const text = (v: number | null | undefined) => (v === null || v === undefined ? '' : String(v))
const ticks = (v: Record<string, number> | null | undefined) =>
  Object.fromEntries(Object.entries(v ?? {}).map(([k, on]) => [k, !!on]))

export function profileToDraft(p: ProfileOut): ProfileDraft {
  return {
    date_of_birth: p.date_of_birth ?? '', sex: p.sex ?? '', education: text(p.education), marital_status: p.marital_status ?? '',
    household_size: text(p.household_size), children: text(p.children), children_under5: text(p.children_under5),
    children_in_school: text(p.children_in_school), monthly_income_kes: text(p.monthly_income_kes),
    agri_income_kes: text(p.agri_income_kes), income_sources: ticks(p.income_sources),
    non_monetary_savings: ticks(p.non_monetary_savings), purchases_last_12m: ticks(p.purchases_last_12m),
    chama_loan_use: text(p.chama_loan_use), lost_as_guarantor_chama: text(p.lost_as_guarantor_chama),
  }
}

/** A whole number from what was typed, commas allowed; null when it is not one. */
const whole = (s: string) => {
  const v = s.replace(/[\s,]/g, '')
  return /^\d+$/.test(v) ? Number(v) : null
}

/** What stops the form being sent; {} when it can go. Everything may be left blank. */
export function profileErrors(d: ProfileDraft): Partial<Record<keyof ProfileDraft, string>> {
  const E = t.sacco.errors
  const out: Partial<Record<keyof ProfileDraft, string>> = {}
  for (const k of NUMBERS) if (d[k].trim() && whole(d[k]) === null) out[k] = E.number
  if (d.household_size.trim() && whole(d.household_size) === 0) out.household_size = E.household
  if (d.date_of_birth) {
    const years = (Date.now() - new Date(d.date_of_birth).getTime()) / (365.25 * 24 * 3600 * 1000)
    if (!(years >= 16 && years <= 110)) out.date_of_birth = E.age
  }
  return out
}

const number = (s: string) => (s.trim() ? whole(s) : null)
const flagsOf = (group: FlagGroup, d: ProfileDraft) => {
  const ticked = d[group]
  if (!Object.values(ticked).some(Boolean) && !Object.keys(ticked).length) return null
  return Object.fromEntries(FLAG_KEYS[group].map((k) => [k, ticked[k] ? 1 : 0]))
}

/** The request body: blank means not given. Call only once profileErrors finds nothing. */
export function toProfileBody(d: ProfileDraft): ProfileBody {
  return {
    date_of_birth: d.date_of_birth || null, sex: d.sex || null, education: number(d.education),
    marital_status: d.marital_status || null,
    household_size: number(d.household_size), children: number(d.children), children_under5: number(d.children_under5),
    children_in_school: number(d.children_in_school), monthly_income_kes: number(d.monthly_income_kes),
    agri_income_kes: number(d.agri_income_kes),
    income_sources: flagsOf('income_sources', d), non_monetary_savings: flagsOf('non_monetary_savings', d),
    purchases_last_12m: flagsOf('purchases_last_12m', d),
    chama_loan_use: number(d.chama_loan_use) as 0 | 1 | 2 | null,
    lost_as_guarantor_chama: number(d.lost_as_guarantor_chama) as 0 | 1 | null,
  }
}
