// Mirrors src/chamapro/api/schemas.py. Keep the two in step.

export type ResponseStatus = 'queued' | 'transcribing' | 'transcribed' | 'failed'
export type InterviewStatus = 'open' | 'assessed'
export type DecisionValue = 'approve' | 'decline' | 'refer'
export type Outcome = 'approve' | 'approve_with_guarantor' | 'approve_reduced' | 'refer' | 'decline' | 'not_now'
export type Role = 'officer' | 'admin' | 'member'
export type QuestionSet = 'v1' | 'v2'
export type Language = 'kik' | 'en'
export type Mode = 'live' | 'practice' | 'self_service'
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

/** GET /api/health: the speech engine actually in use, and what is configured. */
export interface Health {
  status: 'ok' | 'degraded'
  asr_decoding: string
  asr: Record<Language, AsrStatus> // English loads on first use
  classifier_present?: boolean
  api_key_configured?: boolean
  extraction_model?: string
}

/** The signed-in user (GET /api/auth/me). */
export interface Me {
  username: string
  role: Role
  display_name?: string | null // shown beside the role; null shows the username
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
  comparator?: Comparator | null // the SACCO rule, when the interview has a loan application
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
  application_id?: number | null // its loan application; null for interviews without one
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

export type VersusMetric = 'auc_macro_ovr' | 'macro_f1' | 'high_recall'

/** One metric for both models; difference is RandomForest minus deployed. */
export interface Versus {
  deployed: number | null
  random_forest: number | null
  difference: number | null
  better: 'deployed' | 'random_forest' | 'tie' | null
}

/** The RandomForest trained on the deployed model's split, scored on the same held-out rows. */
export interface RandomForestSummary extends Section {
  estimator?: string | null
  trained_on?: string | null
  auc_macro_ovr?: number | null
  macro_f1?: number | null
  per_class?: Record<string, PrecisionRecall> | null
  per_class_recall?: Record<string, number> | null
  versus_deployed?: Partial<Record<VersusMetric, Versus>> | null
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
  computed_at?: string // when these were read from the database; the server keeps them a minute
}

export interface Results {
  generated_at: string
  generator?: string
  model_card?: ModelCard
  held_out?: HeldOut
  class_balance?: ClassBalance
  random_forest?: RandomForestSummary
  shap?: ShapSummary
  asr?: AsrComparison
  live: LiveStats
}

// --- Your own account ---------------------------------------------------------

/** GET /api/auth/profile */
export interface Profile {
  username: string
  role: Role
  display_name?: string | null
  email: string | null // the Google account linked for sign-in
  google_sign_in_available: boolean
  member: { member_no: string; full_name: string } | null
  signed_in_with: string | null // password | google, this session
  active_sessions: number
  created_at: string
}

// --- Members, applications, guarantors -----------------------------------------

export type ApplicationStatus = 'draft' | 'interview_pending' | 'interview_complete' | 'assessed'
  | 'decided' | 'guarantor_required' | 'guarantor_submitted' | 'approved' | 'declined' | 'offered' | 'reversed'
export type GuarantorStatus = 'pending' | 'verified' | 'rejected'
export type ConditionResult = 'pass' | 'fail' | 'pending'
export type Agreement = 'agree' | 'diverge' | 'pending' | 'undetermined'

export interface Member {
  id: number
  member_no: string
  full_name: string
  phone: string | null
  joined_on: string // YYYY-MM-DD
  user_id: number | null
  created_at: string
  email?: string | null
  savings_kes?: number | null
  savings_verified_by?: string | null
  savings_verified_at?: string | null
  self_signed_up?: boolean
}

export interface MemberCreate {
  member_no: string
  full_name: string
  phone: string | null
  joined_on: string
}

export interface ApplicationCreate {
  member_id: number
  amount_requested_kes: number
  purpose: string
  term_months: number
  sacco_savings_kes: number
  interview_id?: number
}

export interface RuleCondition {
  name: 'savings_multiple' | 'guarantors' | 'tenure'
  label: string
  result: ConditionResult
  detail: string
  agreement: Agreement
}

/** The SACCO's own rule, computed live beside the model (never stored with it). */
export interface Comparator {
  rule: string
  max_borrowable_kes: number
  amount_requested_kes: number
  tenure_months: number
  verified_guarantors: number
  conditions: RuleCondition[]
  result: ConditionResult
  rule_recommendation: 'approve' | 'approve_with_guarantors' | 'decline'
  model_recommendation: DecisionValue | null
  agreement: Agreement
  mode: Mode
}

export interface TimelineEntry {
  status: ApplicationStatus
  label: string
  at: string
}

export interface Guarantor {
  id: number
  full_name: string
  member_no: string
  phone: string
  relationship: string
  amount_guaranteed_kes: number
  status: GuarantorStatus
  submitted_at: string
  verified_by: string | null
  verified_at: string | null
}

export interface ApplicationSummary {
  id: number
  member_id: number
  member_no: string
  member_name: string
  amount_requested_kes: number
  term_months: number
  status: ApplicationStatus
  interview_id: number | null
  mode?: Mode | null // its interview's mode; null before it has one
  risk_class: string | null
  outcome: Outcome | null
  created_at: string
  updated_at: string
}

export interface ApplicationDetail extends ApplicationSummary {
  purpose: string
  sacco_savings_kes: number
  savings_self_declared?: boolean
  savings_from_ledger?: boolean
  booking?: Booking | null
  practice_interviews?: PracticeBrief[]
  created_by: string
  member: Member
  interview: { id: number; status: InterviewStatus; question_set: QuestionSet; language: Language; mode: Mode; created_at: string } | null
  assessment: Assessment | null
  decision: Decision | null
  comparator: Comparator | null
  guarantors: Guarantor[]
  timeline: TimelineEntry[]
}

/** POST .../decision: `outcome` is the decision; the rest depend on it. */
export interface DecisionCreate {
  outcome: Outcome
  approved_amount_kes?: number
  guarantors_required?: number
  officer_notes?: string | null
  member_message?: string | null
}

// --- A member's own view: never probabilities, risk class or officer notes -------

export interface GuarantorIn {
  full_name: string
  member_no: string
  phone: string
  relationship: string
  amount_guaranteed_kes: number
}

export interface MyGuarantor extends GuarantorIn {
  status: GuarantorStatus
  submitted_at: string
}

export interface MyApplicationSummary {
  id: number
  amount_requested_kes: number
  purpose: string
  term_months: number
  status: ApplicationStatus
  status_label: string
  mode?: Mode
  created_at: string
  updated_at: string
}

export interface MyApplication extends MyApplicationSummary {
  timeline: TimelineEntry[]
  history?: { label: string; at: string }[]
  booking?: MyBooking | null
  practice?: MyPracticeBrief[]
  outcome: Outcome | null
  approved_amount_kes: number | null
  guarantors_required: number | null
  guarantors_still_needed: number
  member_message: string | null
  reasons: string[]
  guarantors: MyGuarantor[]
}

// --- Administration ----------------------------------------------------------------

export interface UserOut {
  id: number
  username: string
  display_name?: string | null
  role: Role
  email: string | null
  is_active: boolean
  created_at: string
  member_id: number | null
  member_no: string | null
}

export interface UserCreate {
  username: string
  password: string
  role: Role
  display_name: string | null
  email: string | null
  member_id: number | null
}

export interface AuditEntry {
  id: number
  actor_user_id: number | null
  actor: string | null // null for shell scripts
  action: string
  entity: string
  entity_id: number | null
  details: Record<string, unknown>
  created_at: string
}

export interface AuditFilter {
  actor_user_id?: number
  action?: string // exact, or a prefix ending in "."
  entity?: string
  since?: string
  until?: string
  limit?: number
  offset?: number
}

// --- Sign-up, a member's own record, bookings, practice, events, the pilot -----

export interface SignupInfo {
  enabled: boolean
  consent_version: string
  consent_text: string[]
}

export interface SignupBody {
  full_name: string
  phone: string
  email: string | null
  password: string
  password_confirm: string
  invite_code: string
  consent: boolean
  consent_version: string
  member_no?: string | null
}

export type SavingsStatus = 'none' | 'self_declared' | 'verified' | 'ledger'

export interface MyMember {
  member_no: string
  full_name: string
  phone: string | null
  email: string | null
  savings_kes: number | null
  savings_status: SavingsStatus
  savings_label: string
  savings_limit_kes: number | null
  joined_on: string
  tenure_months: number
  age: number | null
  sex: Sex | null
  education: number | null
  marital_status: MaritalStatus | null
  applicant_complete: boolean
  consent_current: boolean
  from_ledger?: boolean
}

export interface MyMemberUpdate {
  phone?: string
  email?: string | null
  savings_kes?: number
  applicant?: ApplicantForm
}

export interface ApplyOptions extends ApplicantFormOptions {
  purposes: string[]
  savings_multiplier: number
  min_tenure_months: number
  max_term_months: number
}

/** POST /me/applications. What the member types and nothing else: the API refuses any other field. */
export interface MyApplicationCreate {
  amount_requested_kes: number
  purpose: string
  purpose_other?: string
  term_months: number
  language: Language
  date: string
  time: string
  declared_savings_kes?: number
  applicant?: ApplicantForm
}

export type BookingStatus = 'requested' | 'confirmed' | 'started' | 'cancelled'

export interface MyBooking {
  id: number
  application_id: number
  starts_at: string
  language: Language
  status: BookingStatus
}

export interface Booking extends MyBooking {
  member_id: number
  member_no: string
  member_name: string
  member_phone: string | null
  amount_requested_kes: number
  purpose: string
  term_months: number
  interview_id: number | null
}

export interface BookingCalendar {
  today: string
  last_date: string
  holidays: { date: string; name: string }[]
  times: string[]
  timezone: string
}

export interface SlotOut {
  time: string
  starts_at: string
  available: boolean
  reason: 'booked' | 'past' | null
}

export interface DaySlots {
  date: string
  blocked_reason: string | null
  slots: SlotOut[]
}

export type EventType = 'agm' | 'member_meeting' | 'training' | 'loan_deadline' | 'other'

export interface SaccoEvent {
  id: number
  title: string
  event_type: EventType
  starts_at: string
  location: string | null
  online_link: string | null
  description: string | null
}

export interface EventBody {
  title: string
  event_type: EventType
  date: string
  time: string
  location: string | null
  online_link: string | null
  description: string | null
}

export interface MemberHome {
  events: SaccoEvent[]
  next_interview: MyBooking | null
  applications: MyApplicationSummary[]
}

export interface MyPracticeBrief {
  id: number
  language: Language
  status: InterviewStatus
  mode: 'practice'
  answered: number
  questions_total: number
  created_at: string
}

export interface PracticeBrief {
  interview_id: number
  language: Language
  status: InterviewStatus
  answered: number
  risk_class: string | null
  created_at: string
  submitted_at: string | null
}

export interface MyQuestion {
  order: number
  topic: string
  text_en: string
  text_kik: string
}

export interface MyResponse {
  id: number
  sentence_no: number
  source: Source
  status: ResponseStatus
  transcript: string | null
  edited: boolean
  duration_s: number | null
}

/** What a member sees of a practice interview: never a class, score or probability. */
export interface MyPractice {
  id: number
  application_id: number
  language: Language
  mode: 'practice'
  status: InterviewStatus
  created_at: string
  questions: MyQuestion[]
  responses: MyResponse[]
  result: { message: string; reasons: string[] } | null
  sus_answered: boolean
  limits: { remaining_today: number; allowed_per_day: number; pilot_full_today: boolean }
}

export interface PilotStats {
  volunteers: number
  practice_by_language: Record<string, number>
  completed_assessments: number
  answers_total: number
  answers_per_member: { member_no: string; answers: number; interviews: number }[]
  sus_mean: number | null
  sus_n: number
  sus_members: number
  comments: { member_no: string; comment: string; score: number; created_at: string }[]
  signup_open: boolean
  per_member_cap: number
  daily_cap: number
  used_today: number
}

// --- A member's profile, ledger, loans and standing guarantors ---------------------------------

export type AccountKind = 'deposits' | 'share_capital' | 'transactional'
export type EntryType = 'deposit' | 'withdrawal' | 'loan_disbursement' | 'loan_repayment' | 'guarantee_recovery' | 'dividend'
export type LoanStatus = 'active' | 'repaid' | 'defaulted' | 'reversed'

/** What a member says about themselves. sacco_loan_use and lost_as_guarantor.sacco are derived and refused. */
export interface ProfileBody {
  date_of_birth?: string | null
  sex?: Sex | null
  education?: number | null
  marital_status?: MaritalStatus | null
  household_size?: number | null
  children?: number | null
  children_under5?: number | null
  children_in_school?: number | null
  monthly_income_kes?: number | null
  agri_income_kes?: number | null
  income_sources?: Record<string, number> | null
  non_monetary_savings?: Record<string, number> | null
  purchases_last_12m?: Record<string, number> | null
  chama_loan_use?: 0 | 1 | 2 | null
  lost_as_guarantor_chama?: 0 | 1 | null
}

export interface ProfileGroupOut {
  source: 'registration' | 'member_update' | 'officer_verified' | 'seed' | null
  updated_at: string | null
  verified: boolean
}

export interface ProfileOut extends Omit<ProfileBody, 'chama_loan_use' | 'lost_as_guarantor_chama'> {
  age?: number | null
  chama_loan_use?: number | null
  lost_as_guarantor_chama?: number | null
  confirmed_at?: string | null
  days_since_confirmed?: number | null
  groups: Record<string, ProfileGroupOut>
  provenance?: Record<string, 'records' | 'declared' | 'verified' | 'missing'> | null
  checks?: Record<string, { by: string; at: string }> | null
}

export interface EntryOut {
  id: number
  entry_type: EntryType
  amount_kes: number
  posted_at: string
  reference: string
}

export interface AccountOut {
  kind: AccountKind
  balance_kes: number
  entries: EntryOut[]
}

export interface PledgeOut {
  id: number
  member_no: string
  full_name: string
  created_at: string
  has_capacity?: boolean | null
  capacity_kes?: number | null
  guaranteed_kes?: number | null
}

export interface LoanOut {
  id: number
  application_id: number | null
  principal_kes: number
  disbursed_on: string
  term_months: number
  monthly_instalment_kes: number
  status: LoanStatus
  paid_kes: number
  days_in_arrears: number
}

export interface SaccoView {
  member_id: number
  member_no: string
  full_name: string
  joined_on: string
  profile: ProfileOut
  accounts: AccountOut[]
  guarantee: { deposits_kes: number; guaranteed_kes: number; committed_kes: number; capacity_kes: number }
  my_guarantors: PledgeOut[]
  i_guarantee: PledgeOut[]
  loans: LoanOut[]
}

export interface GuarantorOffers {
  share_kes: number
  needed: number
  offers: { pledge_id: number; full_name: string; member_no: string }[]
}

// --- Automatic decisions --------------------------------------------------------------------

export interface AutomaticDecision {
  id: number
  application_id: number
  member_id: number
  member_no: string
  member_name: string
  trigger: 'commit' | 'acceptance'
  outcome: Outcome
  amount_requested_kes: number
  amount_kes: number | null
  risk_class: string
  policy_version: string
  application_status: ApplicationStatus
  loan_id: number | null
  loan_status: LoanStatus | null
  reversible_until: string | null
  created_at: string
}

export interface PolicyCheck {
  check: string
  passed: boolean | null
  values: Record<string, unknown>
}

export interface PolicyTrace {
  policy_version?: string
  evaluated_on?: string
  reason_code?: string
  thresholds?: Record<string, number>
  checks?: PolicyCheck[]
  maximums?: { rule_kes: number; affordable_kes: number | null }
  effective?: { amount_kes: number; term_months: number | null }
  clarifications?: { conditions: Record<string, boolean>; asked: string[]; answered: string[]; returned: string[] }
}

export interface AutomaticDecisionDetail extends AutomaticDecision {
  probabilities: Record<string, number>
  contributions: Contribution[] | string
  feature_vector: Record<string, number | null>
  features: Record<string, unknown>
  provenance: Record<string, string>
  overrides: Record<string, unknown>
  trace: PolicyTrace
  member_message: string | null
  model_file: string
  model_sha256: string
}
