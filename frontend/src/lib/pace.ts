import type { Health, Language } from '../api/types'
import { t } from '../strings'

/**
 * Seconds of transcription per second of audio (mean real-time factor),
 * measured by scripts/benchmark_asr.py on the 40-clip corpus
 * (results/asr_benchmark.json). The English model is the same
 * whisper-large-v3-turbo architecture, so it runs at the same pace.
 */
const RTF: Record<string, number> = {
  'openvino:GPU:timestamps': 0.45,
  'openvino:GPU:plain': 0.47,
  'openvino:CPU:timestamps': 1.14,
  'openvino:CPU:plain': 1.72,
  'torch:CPU:timestamps': 3.9,
  'torch:CPU:plain': 3.69,
}

/** Used for a clip whose length is not known yet. */
const TYPICAL_CLIP_SECONDS = 10

/**
 * Seconds of transcription per second of audio for this interview's
 * language, or null when it cannot be stated honestly: health unavailable,
 * the model not loaded yet (the first clip then also waits for it to load),
 * or an engine and device that were never measured.
 */
export function realTimeFactor(health: Health | null, language: Language): number | null {
  if (!health) return null
  const asr = health.asr[language]
  if (!asr?.loaded || !asr.engine || !asr.device) return null
  return RTF[`${asr.engine}:${asr.device}:${health.asr_decoding}`] ?? null
}

/** Expected transcription time for clips of these lengths, one after another. */
export function transcriptionSeconds(rtf: number, durations: (number | null)[]): number {
  return durations.reduce<number>((sum, d) => sum + rtf * (d ?? TYPICAL_CLIP_SECONDS), 0)
}

/** "a few seconds", "about 20 seconds", "about a minute", "about 3 minutes". */
export function describeSeconds(seconds: number): string {
  if (seconds <= 10) return t.pace.fewSeconds
  if (seconds < 45) return t.pace.seconds(Math.max(15, Math.round(seconds / 5) * 5))
  if (seconds < 90) return t.pace.minute
  return t.pace.minutes(Math.round(seconds / 60))
}
