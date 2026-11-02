// The deployed classifier against the RandomForest trained on the same split,
// in words: which is better on each headline metric, and by how much.
import type { Versus, VersusMetric } from '../api/types'
import { t } from '../strings'
import { NOT_MEASURED, isMeasured } from './measure'

const C = t.results.compare
export const VERSUS_METRICS: VersusMetric[] = ['auc_macro_ovr', 'macro_f1', 'high_recall']

/** One metric as a sentence, e.g. "Macro-F1: the RandomForest is higher by 0.0312." */
export function verdict(metric: VersusMetric, v: Versus | null | undefined): string {
  const name = C.metric[metric]
  if (!v || !v.better || !isMeasured(v.difference)) return `${name}: ${NOT_MEASURED}`
  if (v.better === 'tie') return C.level(name)
  const by = Math.abs(v.difference).toFixed(4)
  return v.better === 'random_forest' ? C.rfHigher(name, by) : C.deployedHigher(name, by)
}

/** The overall reading: one model ahead on every metric, or a trade-off. */
export function overall(versus: Partial<Record<VersusMetric, Versus>> | null | undefined): string | null {
  const winners = VERSUS_METRICS.map((m) => versus?.[m]?.better)
  if (!winners.every(Boolean)) return null
  const ahead = new Set(winners.filter((w) => w !== 'tie'))
  if (ahead.size === 0) return C.allLevel
  if (ahead.size === 1) return ahead.has('random_forest') ? C.rfEverywhere : C.deployedEverywhere
  return C.tradeOff
}
