import { useCallback, useEffect, useRef, useState } from 'react'

// A browser plays sound without a tap only on an element it has seen tapped: on iOS, that
// same element. So one element plays everything, and a first tap plays this silence on it.
const SILENCE = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA='

export interface Spoken { seq: number; url: string }

/** The bot's lines, one after another. It needs one tap to begin; until then lines wait. */
export function useSpeech() {
  const element = useRef<HTMLAudioElement | null>(null)
  const queue = useRef<Spoken[]>([])
  const live = useRef(false)     // this element has been played from a tap
  const [unlocked, setUnlocked] = useState(false)
  const [playing, setPlaying] = useState<number | null>(null)
  const [loading, setLoading] = useState<number | null>(null)

  const audio = useCallback(() => {
    if (!element.current) element.current = new Audio()
    return element.current
  }, [])

  const playNext = useCallback(function next_line() {
    const next = queue.current.shift()
    if (!next) { setPlaying(null); setLoading(null); return }
    const a = audio()
    setLoading(next.seq)
    setPlaying(null)
    a.oncanplay = () => setLoading((seq) => (seq === next.seq ? null : seq))
    a.onplaying = () => { setLoading(null); setPlaying(next.seq) }
    a.onended = () => { setPlaying(null); next_line() }
    a.onerror = () => { setLoading(null); setPlaying(null); next_line() }
    a.src = next.url
    a.play()?.catch((e: DOMException) => {
      setLoading(null)
      if (e.name === 'NotAllowedError') {     // the browser wants a tap after all: ask again
        queue.current.unshift(next)
        live.current = false
        setUnlocked(false)
      }
    })
  }, [audio])

  /** Call from inside a tap. Whatever was waiting then plays. */
  const unlock = useCallback(() => {
    if (live.current) return
    live.current = true
    setUnlocked(true)
    const a = audio()
    a.onended = null
    a.onerror = null
    a.src = SILENCE
    const begin = () => { if (queue.current.length) playNext() }
    const started = a.play()
    if (started) started.then(begin, begin)
    else begin()
  }, [audio, playNext])

  const enqueue = useCallback((lines: Spoken[]) => {
    const idle = queue.current.length === 0 && (element.current?.paused ?? true)
    queue.current.push(...lines)
    if (live.current && idle) playNext()
  }, [playNext])

  const stop = useCallback(() => {
    queue.current = []
    const a = element.current
    if (a) { a.onended = null; a.onerror = null; a.pause() }
    setPlaying(null)
    setLoading(null)
  }, [])

  const replay = useCallback((line: Spoken) => {
    unlock()
    stop()
    queue.current = [line]
    playNext()
  }, [unlock, stop, playNext])

  useEffect(() => () => {
    queue.current = []
    const a = element.current
    if (a) { a.onended = null; a.onerror = null; a.pause() }
  }, [])

  return { unlocked, playing, loading, unlock, enqueue, stop, replay }
}
