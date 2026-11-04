// The System Usability Scale. The API computes the stored score with the same rule.

/** Brooke's scoring: odd items a - 1, even items 5 - a, the sum times 2.5. */
export function susScore(answers: number[]): number {
  return answers.reduce((sum, a, i) => sum + (i % 2 === 0 ? a - 1 : 5 - a), 0) * 2.5
}

/** Ten answers, each on the 1-5 scale. */
export const susComplete = (answers: (number | null)[]): answers is number[] =>
  answers.length === 10 && answers.every((a) => a !== null && a >= 1 && a <= 5)
