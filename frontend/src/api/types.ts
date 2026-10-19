// Mirrors src/chamapro/api/schemas.py. Keep the two in step.

export type ResponseStatus = 'queued' | 'transcribing' | 'transcribed' | 'failed'
export type InterviewStatus = 'open' | 'assessed'
export type DecisionValue = 'approve' | 'decline' | 'refer'

export interface Question {
  sentence_no: number
  domain: string
  english: string
  kikuyu: string // "" until a native speaker supplies it
}

export interface Counts {
  queued: number
  transcribing: number
  transcribed: number
  failed: number
}

export interface InterviewSummary {
  id: number
  applicant_name: string | null
  created_at: string
  status: InterviewStatus
  responses_recorded: number
  questions_total: number
  counts: Counts
  risk_class: string | null
  decision: DecisionValue | null
}

export interface ResponseOut {
  id: number
  sentence_no: number
  domain: string | null
  status: ResponseStatus
  error: string | null
  duration_s: number | null
  transcript: string | null
  transcript_asr: string | null
  edited: boolean
  edited_at: string | null
  asr_model: string | null
  asr_seconds: number | null
  translation: string | null
  signals: string[] | null
  created_at: string
}

export interface Contribution {
  feature: string
  value: number | null
  shap: number
}

export interface Assessment {
  id: number
  risk_class: string
  probabilities: Record<string, number>
  feature_vector: Record<string, number | null>
  contributions: Contribution[] | string // string = why SHAP was unavailable
  extracted: Record<string, unknown>
  extraction_completeness: number
  features_populated: number
  features_total: number
  features_not_extractable: string[]
  extraction_model: string
  model_file: string
  model_sha256: string
  created_at: string
}

export interface Decision {
  decision: DecisionValue
  note: string | null
  created_at: string
}

export interface InterviewState {
  id: number
  status: InterviewStatus
  created_at: string
  applicant: { id: number; name: string | null }
  counts: Counts
  responses: ResponseOut[]
  assessment: Assessment | null
  decision: Decision | null
}

export interface ResponseQueued {
  id: number
  interview_id: number
  sentence_no: number
  status: ResponseStatus
}

// GET /api/results: results/summary.json (scripts/export_results.py) plus live
// database stats. Any number may be null: not measured, never zero.

export interface Section {
  source: string
  validation?: string
  notes?: string[]
}

export interface ModelCard extends Section {
  estimator: string | null
  frame: string | null
  protocol: string | null
  seed: number | null
  n_train: number | null
  n_features: number | null
  classes: Record<string, string> | null
  trained_on: string | null
  model_file: string | null
  model_sha256: string | null
}

export interface PrecisionRecall {
  precision: number | null
  recall: number | null
}

export interface HeldOut extends Section {
  n_test: number | null
  auc_macro_ovr: number | null
  macro_f1: number | null
  comparator_macro_f1: number | null
  comparator_source?: string
  per_class: Record<string, PrecisionRecall> | null
  confusion_matrix: number[][] | null
  labels: string[]
}

export interface ClassBalance extends Section {
  labels: string[]
  train: Record<string, number> | null
  test: Record<string, number> | null
}

export interface ShapSummary extends Section {
  sample_size: number | null
  top_features: { feature: string; mean_abs_shap: number }[] | null
}

export interface AsrBlock {
  n: number
  collapse_count: number | null
  yield: number | null
  chrf_pp: number | null
  bleu: number | null
}

export interface AsrSystem {
  asr_file: string
  translation_file: string
  overall: AsrBlock | null
  by_domain: Record<string, AsrBlock> | null
}

export interface AsrComparison extends Section {
  collapse_rule?: string
  domains: string[]
  systems: Record<string, AsrSystem>
}

export interface LiveStats {
  source: string
  interview_count: number
  assessment_count: number
  risk_class_distribution: Record<string, number>
  mean_extraction_completeness: number | null
  decision_agreement: { rule: string; decisions: number; agreements: number; rate: number | null }
}

export interface Results {
  generated_at: string
  generator?: string
  model_card?: ModelCard
  held_out?: HeldOut
  class_balance?: ClassBalance
  random_forest?: Section & { per_class_recall?: Record<string, number> | null }
  shap?: ShapSummary
  asr?: AsrComparison
  live: LiveStats
}
