import { useCallback, useEffect, useRef, useState } from 'react'

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

/** Record one answer from the microphone. stop() resolves with the audio. */
export function useRecorder() {
  const [state, setState] = useState<RecorderState>('idle')
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const recorder = useRef<MediaRecorder | null>(null)
  const chunks = useRef<Blob[]>([])
  const timer = useRef<number | null>(null)

  const release = useCallback(() => {
    if (timer.current) window.clearInterval(timer.current)
    timer.current = null
    recorder.current?.stream.getTracks().forEach((t) => t.stop())
    recorder.current = null
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
      setState('recording')
    } catch (e) {
      release()
      setState('idle')
      const denied = e instanceof DOMException && (e.name === 'NotAllowedError' || e.name === 'SecurityError')
      setError(denied
        ? 'The browser did not allow the microphone. Allow microphone access for this page, or upload a recording instead.'
        : 'No microphone could be used. Check that one is connected, or upload a recording instead.')
    }
  }, [release])

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

  return { state, elapsed, error, start, stop, cancel, clearError: () => setError(null) }
}
