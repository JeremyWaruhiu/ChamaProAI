import type { Question } from '../api/types'
import { t } from '../strings'

// Question topics, keyed as in questions.json and the API. v1 groups its 40
// sentences into the eight domains recorded in data/manifest.csv (not Table
// 3.1's set); v2 has one topic per question. Labels live in strings.ts.
const TOPIC_LABEL: Record<string, string> = t.topics

export function domainLabel(key: string | null | undefined): string {
  return (key && key !== 'other' && TOPIC_LABEL[key]) || t.topics.other
}

/** The topics of a question set, in interview order. */
export function topicsOf(questions: Question[]): { key: string; label: string }[] {
  return [...new Set(questions.map((q) => q.topic))].map((key) => ({ key, label: domainLabel(key) }))
}
