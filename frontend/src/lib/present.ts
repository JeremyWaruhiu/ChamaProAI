import type { PresentContribution, PresentTurn, StaffExplain } from '../api/types'
import { t } from '../strings'
import { featureLabel, featureValue } from './features'

const P = t.present
const F = t.features

/** The evaluations of a conversation, in order, with the turn that recorded each. */
export function evaluationsOf(turns: PresentTurn[]): PresentTurn[] {
  return turns.filter((x) => x.explain)
}

/** Which way, and how far, on one scale: right is in the member's favour, whichever class it was for. */
export const towardsFavour = (c: PresentContribution) => (c.in_favour ? Math.abs(c.shap) : -Math.abs(c.shap))

const shapKey = (e: StaffExplain) => e.contributions.map((c) => `${c.feature}:${c.shap}`).join()

/** The evaluation to draw faintly: the last before this one that differs. A yes at the end re-scores the
 * same answers, and the movement that matters should stay on the screen. */
export function previousEvaluation(evaluations: PresentTurn[], index: number): StaffExplain | null {
  const current = evaluations[index]?.explain
  if (!current) return null
  for (let i = index - 1; i >= 0; i--) {
    const e = evaluations[i].explain!
    if (shapKey(e) !== shapKey(current) || e.risk_class !== current.risk_class) return e
  }
  return null
}

export interface ShapRow { feature: string; label: string; value: string; now: number; before: number | null }

/** The top ten of this evaluation, largest first. */
export function shapRows(current: StaffExplain, previous: StaffExplain | null): { rows: ShapRow[]; scale: number } {
  const was = new Map((previous?.contributions ?? []).map((c) => [c.feature, c]))
  const rows = [...current.contributions].sort((a, b) => Math.abs(b.shap) - Math.abs(a.shap)).slice(0, 10).map((c) => {
    const old = was.get(c.feature)
    return { feature: c.feature, label: featureLabel(c.feature), value: featureValue(c.feature, c.value), now: towardsFavour(c),
             before: old ? towardsFavour(old) : null }
  })
  const scale = Math.max(0.0001, ...rows.flatMap((r) => [Math.abs(r.now), Math.abs(r.before ?? 0)]))
  return { rows, scale }
}

// --- The feature table ------------------------------------------------------------------------

export type SourceKind = 'records' | 'profile' | 'conversation' | 'missing'

export function sourceKind(provenance: string | undefined): SourceKind {
  if (provenance === 'records' || provenance === 'conversation') return provenance
  return provenance === 'declared' || provenance === 'verified' ? 'profile' : 'missing'
}

const named = (value: unknown, names: Record<string, string>) => {
  const on = Object.entries((value as Record<string, number>) ?? {}).filter(([, v]) => v).map(([k]) => names[k] ?? k)
  return on.length ? on.join(', ') : F.noneMentioned
}
const kes = (v: unknown) => t.common.ksh(Number(v))
const yesNo = (v: unknown) => (v ? F.yes : F.no)

const FORMAT: Record<string, (v: unknown) => string> = {
  age: (v) => F.years(Number(v)),
  education_level: (v) => F.education[Number(v)] ?? String(v),
  is_female: (v) => (v ? F.female : F.male),
  monthly_income_kes: kes,
  agri_income_kes: kes,
  income_sources: (v) => named(v, F.sourceNames),
  non_monetary_savings: (v) => named(v, F.assetNames),
  purchases_last_12m: (v) => named(v, F.purchaseNames),
  sacco_loan_use: (v) => F.loanUse[Number(v)] ?? String(v),
  chama_loan_use: (v) => F.loanUse[Number(v)] ?? String(v),
  'lost_as_guarantor.sacco': yesNo,
  'lost_as_guarantor.chama': yesNo,
  term_months: (v) => t.common.months(Number(v)),
  expected_monthly_return_kes: kes,
  chama_instalment_kes: kes,
  accepted_amount_kes: kes,
}

const CONVERSATION_ONLY = ['term_months', 'expected_monthly_return_kes', 'chama_instalment_kes', 'accepted_amount_kes']
const FEATURE_ORDER = ['monthly_income_kes', 'agri_income_kes', 'income_sources', 'household_size', 'children', 'children_under5',
  'children_in_school', 'sacco_loan_use', 'lost_as_guarantor.sacco', 'chama_loan_use', 'lost_as_guarantor.chama',
  'non_monetary_savings', 'purchases_last_12m', 'age', 'education_level', 'is_female', 'marital_status']

function read(e: StaffExplain, key: string): unknown {
  if (CONVERSATION_ONLY.includes(key)) return e.overrides?.[key]
  if (key.startsWith('lost_as_guarantor.')) return (e.features.lost_as_guarantor as Record<string, unknown> | undefined)?.[key.split('.')[1]]
  return e.features[key]
}

export interface FeatureRow { key: string; label: string; value: string; source: SourceKind }

export function featureRows(e: StaffExplain): FeatureRow[] {
  const said = CONVERSATION_ONLY.filter((k) => e.overrides?.[k] !== undefined && e.overrides[k] !== null)
  return [...said, ...FEATURE_ORDER].map((key) => {
    const value = read(e, key)
    return {
      key, label: P.fieldLabels[key] ?? key, source: sourceKind(e.provenance[key]),
      value: value === null || value === undefined ? F.notStated : (FORMAT[key]?.(value) ?? String(value)),
    }
  })
}
