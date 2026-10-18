// The eight domains as recorded in data/manifest.csv (not Table 3.1's set),
// in interview order. Keys match questions.json and the API.
export const DOMAINS = [
  { key: 'household', label: 'Household' },
  { key: 'income', label: 'Income' },
  { key: 'expenditure', label: 'Spending' },
  { key: 'assets', label: 'Assets' },
  { key: 'debt_repayment', label: 'Debts and repayment' },
  { key: 'sacco_history', label: 'SACCO history' },
  { key: 'chama', label: 'Chama' },
  { key: 'intent_planning', label: 'Loan plans' },
] as const

export function domainLabel(key: string | null | undefined): string {
  return DOMAINS.find((d) => d.key === key)?.label ?? 'Other'
}

export function domainIndex(key: string | null | undefined): number {
  return DOMAINS.findIndex((d) => d.key === key)
}
