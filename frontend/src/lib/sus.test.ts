import { describe, expect, it } from 'vitest'
import { susComplete, susScore } from './sus'

describe('susScore', () => {
  // The same cases as tests/test_pilot.py, so the two scorers cannot drift apart.
  it.each<[number[], number]>([
    [Array(10).fill(3), 50],
    [[5, 1, 5, 1, 5, 1, 5, 1, 5, 1], 100],
    [[1, 5, 1, 5, 1, 5, 1, 5, 1, 5], 0],
    [Array(10).fill(5), 50],
    [Array(10).fill(1), 50],
    [[4, 2, 4, 2, 4, 2, 4, 2, 4, 2], 75],
    [[5, 2, 4, 1, 4, 2, 5, 1, 4, 2], 85],
  ])('%j scores %d', (answers, score) => { expect(susScore(answers)).toBe(score) })
})

describe('susComplete', () => {
  it('needs ten answers on the scale', () => {
    expect(susComplete(Array(10).fill(3))).toBe(true)
    expect(susComplete(Array(9).fill(3))).toBe(false)
    expect(susComplete([null, ...Array(9).fill(3)])).toBe(false)
    expect(susComplete([6, ...Array(9).fill(3)])).toBe(false)
    expect(susComplete([0, ...Array(9).fill(3)])).toBe(false)
  })
})
