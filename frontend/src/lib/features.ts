import { t } from '../strings'

// Plain-language labels for the classifier's 40 features and the extracted
// facts. Display only: the feature mapping itself lives in
// scripts/score_interview.py and is not changed here. Words are in strings.ts.

const F = t.features
const ksh = (n: number) => t.common.ksh(n)
const yesNo = (v: number) => (v >= 0.5 ? F.yes : F.no)

type Spec = { label: string; value: (v: number) => string }

const flag = (label: string): Spec => ({ label, value: yesNo })
const count = (key: string): Spec => ({ label: F.labels[key], value: (v) => String(Math.round(v)) })

const SPECS: Record<string, Spec> = {
  age: { label: F.labels.age, value: (v) => F.years(Math.round(v)) },
  household_size: { label: F.labels.household_size, value: (v) => F.people(Math.round(v)) },
  children: count('children'),
  children_under5: count('children_under5'),
  children_in_school: count('children_in_school'),
  log_monthly_income: { label: F.labels.log_monthly_income, value: (v) => ksh(Math.expm1(v)) },
  income_missing: { label: F.labels.income_missing, value: (v) => (v >= 0.5 ? F.notGiven : F.given) },
  log_agri_income: { label: F.labels.log_agri_income, value: (v) => ksh(Math.expm1(v)) },
  education: { label: F.labels.education, value: (v) => F.education[Math.round(v)] ?? String(v) },
  sacco_loan_use: { label: F.labels.sacco_loan_use, value: (v) => F.loanUse[Math.round(v)] ?? String(v) },
  chama_loan_use: { label: F.labels.chama_loan_use, value: (v) => F.loanUse[Math.round(v)] ?? String(v) },
  is_female: { label: F.labels.is_female, value: (v) => (v >= 0.5 ? F.female : F.male) },
}
for (const key of ['marital_married', 'marital_single', 'marital_widowed', 'marital_divorced',
  'E3B__3', 'E3B__7', 'B3A__11']) SPECS[key] = flag(F.labels[key])
F.incomeSources.forEach((s, i) => { SPECS[`B3A__${i + 1}`] = flag(F.incomeFrom(s)) })
F.savings.forEach((s, i) => { SPECS[`F1__${i + 1}`] = flag(s) })
F.purchases.forEach((s, i) => { SPECS[`B1L__${i + 1}`] = flag(F.bought(s)) })

export function featureLabel(feature: string): string {
  return SPECS[feature]?.label ?? feature
}

/** "KSh 8,000", "42 years", "yes" — or "not stated" when the interview did not say. */
export function featureValue(feature: string, value: number | null): string {
  if (value === null || Number.isNaN(value)) return F.notStated
  return SPECS[feature]?.value(value) ?? String(value)
}

// --- Extracted facts (the typed object returned by the extraction step) -----

export interface Fact { label: string; value: string }

type Obj = Record<string, unknown>
const asObj = (v: unknown): Obj => (v && typeof v === 'object' ? (v as Obj) : {})
const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
const picked = (o: Obj, names: Record<string, string>) =>
  Object.entries(names).filter(([k]) => Number(o[k]) === 1).map(([, n]) => n)

// Fields the applicant form fills (score_interview.FORM_FIELDS).
const FORM_FIELDS = new Set(['age', 'is_female', 'education_level', 'marital_status'])

/**
 * What the system heard, as label/value pairs, plus the facts the interview
 * did not give. Flags at 0 are reported as "none mentioned": the extraction
 * prompt sets 0 when a fact was not stated. With an applicant form, the facts
 * it supplied are listed apart (fromForm), not as heard or as not stated.
 */
export function extractedFacts(extracted: Obj, form?: Obj | null): { heard: Fact[]; notStated: string[]; fromForm: Fact[] } {
  const heard: Fact[] = []
  const notStated: string[] = []
  const fromForm: Fact[] = []
  const L = F.facts
  const num = (key: string, label: string, fmt: (n: number) => string) => {
    if (form && FORM_FIELDS.has(key)) {
      const v = form[key]
      fromForm.push({ label, value: isNum(v) ? fmt(v) : F.notEntered })
      return
    }
    const v = extracted[key]
    if (isNum(v)) heard.push({ label, value: fmt(v) })
    else notStated.push(label)
  }
  const list = (key: string, label: string, names: Record<string, string>) => {
    const found = picked(asObj(extracted[key]), names)
    heard.push({ label, value: found.length ? found.join(', ') : F.noneMentioned })
  }

  num('age', L.age, F.years)
  num('household_size', L.household, F.people)
  num('children', L.children, String)
  num('children_in_school', L.inSchool, String)
  num('children_under5', L.under5, String)
  num('monthly_income_kes', L.income, ksh)
  num('agri_income_kes', L.farm, ksh)
  list('income_sources', L.sources, F.sourceNames)
  list('non_monetary_savings', L.owns, F.assetNames)
  list('purchases_last_12m', L.bought, F.purchaseNames)
  num('sacco_loan_use', L.sacco, (n) => F.loanUse[n] ?? String(n))
  num('chama_loan_use', L.chama, (n) => F.loanUse[n] ?? String(n))
  list('lost_as_guarantor', L.lost, F.lostNames)
  num('education_level', L.education, (n) => F.education[n] ?? String(n))
  const marital = (form ?? extracted).marital_status
  if (form) fromForm.push({ label: L.marital, value: typeof marital === 'string' && marital ? marital : F.notEntered })
  else if (typeof marital === 'string' && marital) heard.push({ label: L.marital, value: marital })
  else notStated.push(L.marital)
  num('is_female', L.sex, (n) => (n === 1 ? F.female : F.male))
  return { heard, notStated, fromForm }
}
