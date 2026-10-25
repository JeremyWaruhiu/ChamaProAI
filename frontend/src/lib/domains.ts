import type { Question } from '../api/types'

// Question topics, keyed as in questions.json and the API. v1 groups its 40
// sentences into the eight domains recorded in data/manifest.csv (not Table
// 3.1's set); v2 has one topic per question.
const TOPIC_LABEL: Record<string, string> = {
  // v1
  household: 'Household',
  income: 'Income',
  expenditure: 'Spending',
  assets: 'Assets',
  debt_repayment: 'Debts and repayment',
  sacco_history: 'SACCO history',
  chama: 'Chama',
  intent_planning: 'Loan plans',
  // v2
  income_sources: 'Other income',
  savings_in_kind: 'Savings in kind',
  purchases: 'Purchases',
  guarantorship: 'Guaranteeing loans',
  sacco_borrowing: 'SACCO loans',
  chama_borrowing: 'Chama loans',
}

export function domainLabel(key: string | null | undefined): string {
  return (key && TOPIC_LABEL[key]) || 'Other'
}

/** The topics of a question set, in interview order. */
export function topicsOf(questions: Question[]): { key: string; label: string }[] {
  return [...new Set(questions.map((q) => q.topic))].map((key) => ({ key, label: domainLabel(key) }))
}
