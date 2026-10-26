import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { t } from '../strings'
import { Icon } from './Icon'

/** Play back a stored answer. One large toggle, as in Figure 4.10. */
export function ReplayButton({ responseId, className = 'btn btn-secondary' }: { responseId: number; className?: string }) {
  const audio = useRef<HTMLAudioElement | null>(null)
  const [playing, setPlaying] = useState(false)
  const [failed, setFailed] = useState(false)

  useEffect(() => () => { audio.current?.pause() }, [])

  async function toggle() {
    if (playing) {
      audio.current?.pause()
      if (audio.current) audio.current.currentTime = 0
      setPlaying(false)
      return
    }
    if (!audio.current) {
      const a = new Audio(api.audioUrl(responseId))
      a.onended = () => setPlaying(false)
      a.onerror = () => { setPlaying(false); setFailed(true) }
      audio.current = a
    }
    try {
      setFailed(false)
      await audio.current.play()
      setPlaying(true)
    } catch {
      setFailed(true)
    }
  }

  return (
    <button type="button" className={className} onClick={toggle} aria-pressed={playing}
            title={failed ? t.replay.failed : undefined}>
      <Icon name={playing ? 'stop' : 'play'} size={18} /> {playing ? t.replay.stop : failed ? t.replay.unavailable : t.replay.play}
    </button>
  )
}
