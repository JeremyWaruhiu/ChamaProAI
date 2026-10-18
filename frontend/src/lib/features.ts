// Plain-language labels for the classifier's 40 features and the extracted
// facts. Display only: the feature mapping itself lives in
// scripts/score_interview.py and is not changed here.

const ksh = (n: number) => `KSh ${Math.round(n).toLocaleString('en-KE')}`
const yesNo = (v: number) => (v >= 0.5 ? 'yes' : 'no')

const EDUCATION = [
  'no schooling', 'some primary', 'primary complete', 'some secondary',
  'secondary complete', 'some technical college', 'technical college complete',
  'some university', 'university complete',
]
const LOAN_USE = ['never used', 'used in the past', 'using now']

type Spec = { label: string; value: (v: number) => string }

const flag = (label: string): Spec => ({ label, value: yesNo })

const INCOME_SOURCES = ['farming', 'employment', 'casual work', 'own business',
  'social transfers', 'renting out property', 'investments', 'a pension',
  'remittances', 'other sources']
const SAVINGS = ['Owns land or buildings', 'Owns livestock', 'Owns jewellery',
  'Holds digital assets', 'Has trees or agroforestry']
const PURCHASES = ['land', 'a new house', 'building materials', 'business equipment',
  'farm equipment', 'livestock']

const SPECS: Record<string, Spec> = {
  age: { label: 'Age', value: (v) => `${Math.round(v)} years` },
  household_size: { label: 'Household size', value: (v) => `${Math.round(v)} people` },
  children: { label: 'Children', value: (v) => String(Math.round(v)) },
  children_under5: { label: 'Children under five', value: (v) => String(Math.round(v)) },
  children_in_school: { label: 'Children in school', value: (v) => String(Math.round(v)) },
  log_monthly_income: { label: 'Monthly income', value: (v) => ksh(Math.expm1(v)) },
  income_missing: { label: 'Monthly income figure', value: (v) => (v >= 0.5 ? 'not given' : 'given') },
  log_agri_income: { label: 'Farm income', value: (v) => ksh(Math.expm1(v)) },
  education: { label: 'Education', value: (v) => EDUCATION[Math.round(v)] ?? String(v) },
  sacco_loan_use: { label: 'SACCO loans', value: (v) => LOAN_USE[Math.round(v)] ?? String(v) },
  chama_loan_use: { label: 'Chama loans', value: (v) => LOAN_USE[Math.round(v)] ?? String(v) },
  is_female: { label: 'Sex', value: (v) => (v >= 0.5 ? 'female' : 'male') },
  marital_married: flag('Married'),
  marital_single: flag('Single'),
  marital_widowed: flag('Widowed'),
  marital_divorced: flag('Divorced'),
  E3B__3: flag('Lost money as a SACCO guarantor'),
  E3B__7: flag('Lost money as a chama guarantor'),
  B3A__11: flag('Has no source of income'),
}
INCOME_SOURCES.forEach((s, i) => { SPECS[`B3A__${i + 1}`] = flag(`Income from ${s}`) })
SAVINGS.forEach((s, i) => { SPECS[`F1__${i + 1}`] = flag(s) })
PURCHASES.forEach((s, i) => { SPECS[`B1L__${i + 1}`] = flag(`Bought ${s} in the last year`) })

export function featureLabel(feature: string): string {
  return SPECS[feature]?.label ?? feature
}

/** "KSh 8,000", "42 years", "yes" — or "not stated" when the interview did not say. */
export function featureValue(feature: string, value: number | null): string {
  if (value === null || Number.isNaN(value)) return 'not stated'
  return SPECS[feature]?.value(value) ?? String(value)
}

// --- Extracted facts (the typed object returned by the extraction step) -----

export interface Fact { label: string; value: string }

type Obj = Record<string, unknown>
const asObj = (v: unknown): Obj => (v && typeof v === 'object' ? (v as Obj) : {})
const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
const picked = (o: Obj, names: Record<string, string>) =>
  Object.entries(names).filter(([k]) => Number(o[k]) === 1).map(([, n]) => n)

/**
 * What the system heard, as label/value pairs, plus the facts the interview
 * did not give. Flags at 0 are reported as "none mentioned": the extraction
 * prompt sets 0 when a fact was not stated.
 */
export function extractedFacts(extracted: Obj): { heard: Fact[]; notStated: string[] } {
  const heard: Fact[] = []
  const notStated: string[] = []
  const num = (key: string, label: string, fmt: (n: number) => string) => {
    const v = extracted[key]
    if (isNum(v)) heard.push({ label, value: fmt(v) })
    else notStated.push(label)
  }
  const list = (key: string, label: string, names: Record<string, string>) => {
    const found = picked(asObj(extracted[key]), names)
    heard.push({ label, value: found.length ? found.join(', ') : 'none mentioned' })
  }

  num('age', 'Age', (n) => `${n} years`)
  num('household_size', 'Household size', (n) => `${n} people`)
  num('children', 'Children', String)
  num('children_in_school', 'Children in school', String)
  num('children_under5', 'Children under five', String)
  num('monthly_income_kes', 'Monthly income', ksh)
  num('agri_income_kes', 'Farm income', ksh)
  list('income_sources', 'Income sources', {
    farming: 'farming', employed: 'employment', casual_worker: 'casual work',
    own_business: 'own business', social_transfer: 'social transfers',
    renting_out: 'renting out property', investments: 'investments', pension: 'pension',
    remittances: 'remittances', other: 'other', none: 'no income',
  })
  list('non_monetary_savings', 'Owns', {
    land_or_buildings: 'land or buildings', livestock: 'livestock', jewellery: 'jewellery',
    digital_assets: 'digital assets', agroforestry: 'trees or agroforestry',
  })
  list('purchases_last_12m', 'Bought in the last 12 months', {
    land_or_plot: 'land', new_house: 'new house', house_materials: 'building materials',
    business_equipment: 'business equipment', farm_equipment: 'farm equipment',
    livestock: 'livestock',
  })
  num('sacco_loan_use', 'SACCO loans', (n) => LOAN_USE[n] ?? String(n))
  num('chama_loan_use', 'Chama loans', (n) => LOAN_USE[n] ?? String(n))
  list('lost_as_guarantor', 'Lost money as a guarantor', { sacco: 'SACCO', chama: 'chama' })
  num('education_level', 'Education', (n) => EDUCATION[n] ?? String(n))
  const marital = extracted.marital_status
  if (typeof marital === 'string' && marital) heard.push({ label: 'Marital status', value: marital })
  else notStated.push('Marital status')
  num('is_female', 'Sex', (n) => (n === 1 ? 'female' : 'male'))
  return { heard, notStated }
}
