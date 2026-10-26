import type { ApplicationSummary, AuditFilter, InterviewState, InterviewSummary, Question } from '../api/types'
import { applicantName } from './format'
import { paths } from './router'

// Pure helpers behind the list screens and the search box.

/** Where opening an interview should land: the next thing the officer has to do. */
export function interviewDestination(iv: InterviewSummary): string {
  if (iv.status === 'assessed') return paths.assessment(iv.id)
  if (iv.responses_recorded >= iv.questions_total) return paths.review(iv.id)
  return paths.record(iv.id)
}

/** The question to resume at: the first one without an answer. */
export function firstUnanswered(questions: Question[], iv: InterviewState | null): number | undefined {
  if (!iv) return undefined
  const done = new Set(iv.responses.map((r) => r.sentence_no))
  return questions.find((q) => !done.has(q.order))?.order
}

export type InterviewFilter = 'all' | 'open' | 'assessed' | 'practice'

export function filterInterviews(items: InterviewSummary[], q: string, filter: InterviewFilter): InterviewSummary[] {
  const term = q.trim().toLowerCase()
  return items.filter((iv) => {
    if (filter === 'open' && iv.status !== 'open') return false
    if (filter === 'assessed' && iv.status !== 'assessed') return false
    if (filter === 'practice' && iv.mode !== 'practice') return false
    return !term || applicantName(iv.applicant_name).toLowerCase().includes(term) || String(iv.id) === term.replace(/^#/, '')
  })
}

/** Does an application match a search by member name, member number or "#id"? */
export function matchesApplication(a: ApplicationSummary, q: string): boolean {
  const term = q.trim().toLowerCase().replace(/^#/, '')
  return !term || a.member_name.toLowerCase().includes(term) || a.member_no.toLowerCase().includes(term)
    || String(a.id) === term
}

/** The first few matches for the search box; none for an empty search. */
export function matchApplications(apps: ApplicationSummary[], q: string, limit = 5): ApplicationSummary[] {
  return q.trim() ? apps.filter((a) => matchesApplication(a, q)).slice(0, limit) : []
}

/** The audit form's dates as the API's since/until: from the start of one day to the end of another. */
export function auditFilter(f: { actor: string; action: string; entity: string; since: string; until: string }): AuditFilter {
  const nextDay = (ymd: string) => {
    const [y, m, d] = ymd.split('-').map(Number)
    return new Date(Date.UTC(y, m - 1, d + 1)).toISOString().slice(0, 10)
  }
  return {
    actor_user_id: f.actor ? Number(f.actor) : undefined,
    action: f.action || undefined,
    entity: f.entity || undefined,
    since: f.since || undefined,
    until: f.until ? nextDay(f.until) : undefined,
  }
}
