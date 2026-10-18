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
