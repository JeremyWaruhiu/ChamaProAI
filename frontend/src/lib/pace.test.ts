import { describe, expect, it } from 'vitest'
import type { AsrStatus, Health } from '../api/types'
import { describeSeconds, realTimeFactor, transcriptionSeconds } from './pace'

const asr = (over: Partial<AsrStatus> = {}): AsrStatus => ({
  loaded: true, engine: 'openvino', device: 'GPU', model: 'paza-ov-int8 (openvino GPU)',
  language: 'sw', error: null, ...over,
})
const health = (kik: Partial<AsrStatus> = {}, en: Partial<AsrStatus> = { loaded: false, engine: null, device: null },
  decoding = 'timestamps'): Health =>
  ({ status: 'ok', asr_decoding: decoding, asr: { kik: asr(kik), en: asr(en) } })

describe('realTimeFactor', () => {
  it('reads the engine and device actually in use for the interview language', () => {
    expect(realTimeFactor(health(), 'kik')).toBe(0.45)
    expect(realTimeFactor(health({ device: 'CPU' }), 'kik')).toBe(1.14)
    expect(realTimeFactor(health({ engine: 'torch', device: 'CPU' }), 'kik')).toBe(3.9)
    expect(realTimeFactor(health({}, {}, 'plain'), 'kik')).toBe(0.47)
  })

  it('makes no claim without health, before the model loads, or for an unmeasured setup', () => {
    expect(realTimeFactor(null, 'kik')).toBeNull()
    expect(realTimeFactor(health(), 'en')).toBeNull()             // English loads on first use
    expect(realTimeFactor(health({ engine: 'torch', device: 'GPU' }), 'kik')).toBeNull()
  })
})

describe('transcriptionSeconds', () => {
  it('scales each clip by the real-time factor, assuming 10 s when the length is unknown', () => {
    expect(transcriptionSeconds(0.5, [4, 6])).toBe(5)
    expect(transcriptionSeconds(1, [null])).toBe(10)
    expect(transcriptionSeconds(2, [])).toBe(0)
  })
})

describe('describeSeconds', () => {
  it('stays vague for short waits and rounds longer ones', () => {
    expect(describeSeconds(2.3)).toBe('a few seconds')
    expect(describeSeconds(10)).toBe('a few seconds')
    expect(describeSeconds(11)).toBe('about 15 seconds')
    expect(describeSeconds(37)).toBe('about 35 seconds')
    expect(describeSeconds(60)).toBe('about a minute')
    expect(describeSeconds(200)).toBe('about 3 minutes')
  })
})
