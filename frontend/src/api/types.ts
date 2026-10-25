// Mirrors src/chamapro/api/schemas.py. Keep the two in step.

export type ResponseStatus = 'queued' | 'transcribing' | 'transcribed' | 'failed'
export type InterviewStatus = 'open' | 'assessed'
export type DecisionValue = 'approve' | 'decline' | 'refer'
export type Outcome = 'approve' | 'approve_with_guarantor' | 'approve_reduced' | 'refer' | 'decline'
export type Role = 'officer' | 'admin' | 'member'
export type QuestionSet = 'v1' | 'v2'
export type Language = 'kik' | 'en'
export type Mode = 'live' | 'practice'
export type Source = 'audio' | 'typed'
export type Sex = 'female' | 'male'
export type MaritalStatus = 'married' | 'single' | 'widowed' | 'divorced'

/** GET /api/auth/config: what the login page needs before sign-in. */
export interface AuthConfig {
  google_client_id: string | null // null: Google sign-in not configured
}

export interface AsrStatus {
  loaded: boolean
  engine: string | null // openvino | torch, as actually loaded after any fallback
  device: string | null // GPU | CPU, as actually loaded after any fallback
  model: string | null
  language: string
  error: string | null
}

/** GET /api/health; the dashboard reads only the speech engine from it. */
export interface Health {
  status: 'ok' | 'degraded'
  asr_decoding: string
  asr: Record<Language, AsrStatus> // English loads on first use
}

/** The signed-in user (GET /api/auth/me). */
export interface Me {
  username: string
  role: Role
}

export interface Question {
  id: string
  version: QuestionSet
  topic: string
  order: number // a response's sentence_no
  text_en: string
  text_kik: string // "" until a native speaker supplies it
  features: string[] // classifier features the question is asked for
}

/** Entered by the officer when the interview is created (question set v2). */
export interface ApplicantForm {
  age: number
  sex: Sex
  education: number // code on the classifier's education ladder, 0-8
  marital_status: MaritalStatus
}

export interface Option<T extends string | number = string | number> {
  value: T
  label: string
}

/** GET /api/applicant-form: the form's choices, with the codes the classifier uses. */
export interface ApplicantFormOptions {
  sex: Option<Sex>[]
  education: Option<number>[]
  marital_status: Option<MaritalStatus>[]
}

export interface InterviewCreate {
  applicant_name: string | null
  applicant: ApplicantForm
  language: Language
  mode: Mode
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
  question_set: QuestionSet
  language: Language
  mode: Mode
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
  source: Source // typed answers have no audio and skip ASR
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
  applicant_form?: Record<string, unknown> | null // form values merged into the vector
  extraction_completeness: number
  features_populated: number
  features_total: number
  features_not_extractable: string[]
  extraction_model: string
  model_file: string
  model_sha256: string
  assessed_by?: string | null // null on assessments made before sign-in existed
  created_at: string
}

export interface Decision {
  decision: DecisionValue // approve | decline | refer, on every decision
  outcome?: Outcome // equal to decision on decisions made before outcomes existed
  approved_amount_kes?: number | null
  guarantors_required?: number | null
  note: string | null // same as officer_notes
  officer_notes?: string | null // never shown to members
  member_message?: string | null
  decided_by?: string | null
  created_at: string
}

export interface Applicant extends Partial<{ [K in keyof ApplicantForm]: ApplicantForm[K] | null }> {
  id: number
  name: string | null
}

export interface InterviewState {
  id: number
  status: InterviewStatus
  question_set: QuestionSet
  language: Language
  mode: Mode
  created_at: string
  applicant: Applicant
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
  interview_count: number // live interviews only
  practice_interview_count?: number
  assessment_count: number
  risk_class_distribution: Record<string, number>
  mean_extraction_completeness: number | null
  decision_agreement: { rule: string; decisions: number; agreements: number; rate: number | null }
  // The SACCO rule (savings x 3, two guarantors, six months) against the model, live applications only.
  rule_agreement?: {
    rule: string
    applications: number
    agreements: number
    divergences: number
    undetermined: number
    rate: number | null
  }
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
