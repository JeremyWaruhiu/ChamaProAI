import type { ApplicationStatus, InterviewSummary, Outcome, TimelineEntry } from '../api/types'
import { t } from '../strings'
import { DECISION_LABEL } from './risk'

// Application statuses as staff see them, and the six stages of a member's
// timeline. A badge tone says how much the status needs someone's attention.

export type Tone = 'neutral' | 'wait' | 'info' | 'attention' | 'low' | 'medium' | 'high' | 'practice'

export const STATUS_TONE: Record<ApplicationStatus, Tone> = {
  draft: 'neutral',
  interview_pending: 'wait',
  interview_complete: 'info',
  assessed: 'attention',
  decided: 'info',
  guarantor_required: 'medium',
  guarantor_submitted: 'attention',
  approved: 'low',
  declined: 'high',
}

export const APPLICATION_STATUSES = Object.keys(STATUS_TONE) as ApplicationStatus[]

export const statusLabel = (s: ApplicationStatus) => t.appStatus[s]
export const outcomeLabel = (o: Outcome) => t.outcome[o]

export const OUTCOME_TONE: Record<Outcome, Tone> = {
  approve: 'low', approve_with_guarantor: 'low', approve_reduced: 'low', refer: 'info', decline: 'high',
}

// --- Interviews --------------------------------------------------------------------

export function interviewStatusText(iv: InterviewSummary): string {
  const S = t.interviewStatus
  if (iv.status === 'assessed') {
    return iv.decision ? S.decision(iv.mode === 'practice', DECISION_LABEL[iv.decision]) : S.awaiting
  }
  if (iv.counts.queued + iv.counts.transcribing > 0) return S.transcribing
  if (iv.responses_recorded === 0) return S.notStarted
  if (iv.responses_recorded < iv.questions_total) return S.inProgress
  return S.ready
}

export function interviewTone(iv: InterviewSummary): Tone {
  if (iv.status === 'assessed') return iv.decision ? 'low' : 'attention'
  if (iv.counts.queued + iv.counts.transcribing > 0) return 'wait'
  return iv.responses_recorded >= iv.questions_total ? 'info' : 'neutral'
}

// --- A member's six stages ---------------------------------------------------------

export type StageKey = 'applied' | 'interview' | 'assessment' | 'decision' | 'guarantor' | 'approved'
export type StageState = 'done' | 'current' | 'upcoming' | 'skipped' | 'failed'

export interface Stage {
  key: StageKey
  label: string
  state: StageState
  at: string | null
}

const KEYS: StageKey[] = ['applied', 'interview', 'assessment', 'decision', 'guarantor', 'approved']

// Which stage each status is at, and whether that stage is finished.
const AT: Record<ApplicationStatus, [StageKey, 'current' | 'done']> = {
  draft: ['interview', 'current'],
  interview_pending: ['interview', 'current'],
  interview_complete: ['assessment', 'current'],
  assessed: ['decision', 'current'],
  decided: ['decision', 'current'],
  guarantor_required: ['guarantor', 'current'],
  guarantor_submitted: ['guarantor', 'current'],
  approved: ['approved', 'done'],
  declined: ['decision', 'done'],
}

/**
 * Applied → Interview → Assessment → Decision → Guarantor → Approved, each
 * done, current or still to come. A loan approved without guarantors skips
 * that stage; a declined one fails at the decision. Times come from the
 * application's timeline (its audit rows).
 */
export function memberStages(status: ApplicationStatus, timeline: TimelineEntry[] = [],
  guarantorsRequired: number | null = null): Stage[] {
  const first = (...s: ApplicationStatus[]) => timeline.find((e) => s.includes(e.status))?.at ?? null
  const reached: Record<StageKey, string | null> = {
    applied: first('draft', 'interview_pending'),
    interview: first('interview_complete'),
    assessment: first('assessed'),
    decision: first('decided', 'guarantor_required', 'approved', 'declined'),
    guarantor: guarantorsRequired ? timeline.filter((e) => e.status === 'approved').at(-1)?.at ?? null : null,
    approved: first('approved'),
  }
  const [stage, how] = AT[status]
  const here = KEYS.indexOf(stage)
  return KEYS.map((key, i) => {
    let state: StageState
    if (status === 'declined') state = i < here ? 'done' : i === here ? 'failed' : 'skipped'
    else if (key === 'guarantor' && !guarantorsRequired && i < here) state = 'skipped'
    else if (i < here || (i === here && how === 'done')) state = 'done'
    else state = i === here ? 'current' : 'upcoming'
    return { key, label: t.my.stages[i], state, at: state === 'done' || state === 'failed' ? reached[key] : null }
  })
}
