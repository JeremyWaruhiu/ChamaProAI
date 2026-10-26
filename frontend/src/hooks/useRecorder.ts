import { useCallback, useEffect, useRef, useState } from 'react'
import { t } from '../strings'

export type RecorderState = 'idle' | 'starting' | 'recording'

// webm/Opus is what Chrome and Firefox record; Safari only offers mp4.
// The backend converts either to 16 kHz mono WAV.
const PREFERRED = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']

export const recordingSupported = () =>
  typeof window !== 'undefined' && typeof MediaRecorder !== 'undefined'
  && !!navigator.mediaDevices?.getUserMedia

function pickMime(): string {
  return PREFERRED.find((t) => MediaRecorder.isTypeSupported(t)) ?? ''
}

export const extensionFor = (mime: string) => (mime.includes('mp4') ? 'm4a' : 'webm')

/** Root-mean-square of 8-bit audio samples centred on 128, scaled to 0-1 for a meter. */
export function levelOf(samples: Uint8Array): number {
  if (!samples.length) return 0
  let sum = 0
  for (const v of samples) { const x = (v - 128) / 128; sum += x * x }
  return Math.min(1, Math.sqrt(sum / samples.length) * 3)
}

type AudioCtor = typeof AudioContext

/** Record one answer from the microphone. stop() resolves with the audio; level is the live input level, 0-1. */
export function useRecorder() {
  const [state, setState] = useState<RecorderState>('idle')
  const [elapsed, setElapsed] = useState(0)
  const [level, setLevel] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const recorder = useRef<MediaRecorder | null>(null)
  const chunks = useRef<Blob[]>([])
  const timer = useRef<number | null>(null)
  const audio = useRef<{ ctx: AudioContext; frame: number } | null>(null)

  const release = useCallback(() => {
    if (timer.current) window.clearInterval(timer.current)
    timer.current = null
    if (audio.current) {
      cancelAnimationFrame(audio.current.frame)
      audio.current.ctx.close().catch(() => {})
      audio.current = null
    }
    setLevel(0)
    recorder.current?.stream.getTracks().forEach((tr) => tr.stop())
    recorder.current = null
  }, [])

  /** The level meter: optional, so a browser without Web Audio still records. */
  const meter = useCallback((stream: MediaStream) => {
    const Ctor: AudioCtor | undefined = window.AudioContext
      ?? (window as unknown as { webkitAudioContext?: AudioCtor }).webkitAudioContext
    if (!Ctor) return
    try {
      const ctx = new Ctor()
      const analyser = ctx.createAnalyser()
      analyser.fftSize = 512
      ctx.createMediaStreamSource(stream).connect(analyser)
      const buf = new Uint8Array(analyser.fftSize)
      let last = 0
      let smooth = 0
      const tick = (now: number) => {
        analyser.getByteTimeDomainData(buf)
        smooth = Math.max(levelOf(buf), smooth * 0.85)
        if (now - last > 66) { setLevel(smooth); last = now }   // about 15 updates a second
        if (audio.current) audio.current.frame = requestAnimationFrame(tick)
      }
      audio.current = { ctx, frame: requestAnimationFrame(tick) }
    } catch { /* no meter; recording carries on */ }
  }, [])

  useEffect(() => release, [release])

  const start = useCallback(async () => {
    setError(null)
    setState('starting')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mime = pickMime()
      const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
      chunks.current = []
      rec.ondataavailable = (e) => { if (e.data.size) chunks.current.push(e.data) }
      rec.start()
      recorder.current = rec
      const t0 = Date.now()
      setElapsed(0)
      timer.current = window.setInterval(() => setElapsed((Date.now() - t0) / 1000), 250)
      meter(stream)
      setState('recording')
    } catch (e) {
      release()
      setState('idle')
      const denied = e instanceof DOMException && (e.name === 'NotAllowedError' || e.name === 'SecurityError')
      setError(denied ? t.runner.micDenied : t.runner.micMissing)
    }
  }, [release, meter])

  const stop = useCallback(() => new Promise<Blob | null>((resolve) => {
    const rec = recorder.current
    if (!rec || rec.state === 'inactive') { resolve(null); return }
    rec.onstop = () => {
      const blob = new Blob(chunks.current, { type: rec.mimeType || 'audio/webm' })
      release()
      setState('idle')
      resolve(blob.size ? blob : null)
    }
    rec.stop()
  }), [release])

  const cancel = useCallback(() => {
    const rec = recorder.current
    if (rec && rec.state !== 'inactive') { rec.onstop = null; rec.stop() }
    release()
    setState('idle')
  }, [release])

  return { state, elapsed, level, error, start, stop, cancel, clearError: () => setError(null) }
}
