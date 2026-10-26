import type { Contribution } from '../api/types'
import { featureLabel, featureValue } from './features'

/**
 * Which way a contribution pushed, for the applicant. SHAP values are for the
 * predicted class: for Low, positive pushed towards Low (in favour); for
 * Medium and High, positive pushed towards that riskier class (against).
 * The same rule as member_text.in_favour on the server.
 */
export function inFavour(riskClass: string, shap: number): boolean {
  return riskClass === 'Low' ? shap > 0 : shap < 0
}

const phrase = (c: Contribution) => {
  const label = featureLabel(c.feature)
  return `${label.charAt(0).toLowerCase()}${label.slice(1)} (${featureValue(c.feature, c.value)})`
}

/** The strongest contributions, split into what counted for and against the applicant. */
export function explain(riskClass: string, contributions: Contribution[] | string, n = 3): { favour: string[]; against: string[] } {
  if (typeof contributions === 'string') return { favour: [], against: [] }
  const top = [...contributions].filter((c) => c.shap).sort((a, b) => Math.abs(b.shap) - Math.abs(a.shap)).slice(0, n * 2)
  const favour = top.filter((c) => inFavour(riskClass, c.shap)).slice(0, n).map(phrase)
  const against = top.filter((c) => !inFavour(riskClass, c.shap)).slice(0, n).map(phrase)
  return { favour, against }
}
