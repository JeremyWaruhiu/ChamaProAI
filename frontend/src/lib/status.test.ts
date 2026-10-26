import { describe, expect, it } from 'vitest'
import type { TimelineEntry } from '../api/types'
import { memberStages } from './status'

const states = (s: ReturnType<typeof memberStages>) => s.map((x) => x.state)

describe("a member's timeline", () => {
  it('names the six stages in order', () => {
    expect(memberStages('draft').map((s) => s.label))
      .toEqual(['Applied', 'Interview', 'Assessment', 'Decision', 'Guarantors', 'Approved'])
  })

  it.each([
    ['interview_pending', ['done', 'current', 'upcoming', 'upcoming', 'upcoming', 'upcoming']],
    ['interview_complete', ['done', 'done', 'current', 'upcoming', 'upcoming', 'upcoming']],
    ['assessed', ['done', 'done', 'done', 'current', 'upcoming', 'upcoming']],
    ['guarantor_required', ['done', 'done', 'done', 'done', 'current', 'upcoming']],
    ['guarantor_submitted', ['done', 'done', 'done', 'done', 'current', 'upcoming']],
    ['declined', ['done', 'done', 'done', 'failed', 'skipped', 'skipped']],
  ] as const)('%s', (status, expected) => {
    expect(states(memberStages(status, [], 2))).toEqual(expected)
  })

  it('skips the guarantor stage when none were needed', () => {
    expect(states(memberStages('approved'))).toEqual(['done', 'done', 'done', 'done', 'skipped', 'done'])
    expect(states(memberStages('approved', [], 2))).toEqual(['done', 'done', 'done', 'done', 'done', 'done'])
  })

  it('dates each finished stage from the timeline', () => {
    const tl: TimelineEntry[] = [
      { status: 'draft', label: '', at: '2026-10-01T08:00:00Z' },
      { status: 'interview_complete', label: '', at: '2026-10-01T09:00:00Z' },
      { status: 'assessed', label: '', at: '2026-10-01T09:30:00Z' },
      { status: 'approved', label: '', at: '2026-10-02T10:00:00Z' },
    ]
    const s = memberStages('approved', tl)
    expect(s.map((x) => x.at)).toEqual(['2026-10-01T08:00:00Z', '2026-10-01T09:00:00Z', '2026-10-01T09:30:00Z',
      '2026-10-02T10:00:00Z', null, '2026-10-02T10:00:00Z'])
  })
})
