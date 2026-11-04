import styles from '../screens/Recording.module.css'
import { t } from '../strings'
import { Notice } from './Notice'

const R = t.runner

/** In place of the Record button when this page cannot use the microphone. */
export function MicUnavailable({ reason }: { reason: 'insecure' | 'unsupported' }) {
  if (reason === 'unsupported') return <p className="muted">{R.noMic}</p>
  return <Notice tone="warning" title={R.insecureTitle}>{R.insecureBody(window.location.origin)}</Notice>
}

/** Twenty segments that light up with the microphone's level. */
export function LevelMeter({ level, segments = 20 }: { level: number; segments?: number }) {
  const lit = Math.round(Math.max(0, Math.min(1, level)) * segments)
  return (
    <div className={styles.meter} role="meter" aria-label={R.level} aria-valuemin={0} aria-valuemax={100}
         aria-valuenow={Math.round(level * 100)}>
      {Array.from({ length: segments }, (_, i) => (
        <span key={i} className={i < lit ? (i >= segments * 0.85 ? styles.segHot : styles.segOn) : undefined} />
      ))}
    </div>
  )
}
