import type { ResponseStatus } from '../api/types'
import { riskTone } from '../lib/risk'
import styles from './Badges.module.css'

const STATUS_TEXT: Record<ResponseStatus, string> = {
  queued: 'Waiting',
  transcribing: 'Transcribing',
  transcribed: 'Transcribed',
  failed: 'Not transcribed',
}

export function StatusBadge({ status }: { status: ResponseStatus }) {
  return (
    <span className={`${styles.badge} ${styles[status]}`}>
      {status === 'transcribing' && <span className={styles.pulse} aria-hidden />}
      {status === 'transcribed' && <span aria-hidden>✓</span>}
      {STATUS_TEXT[status]}
    </span>
  )
}

export function RiskBadge({ risk }: { risk: string }) {
  return <span className={`${styles.risk} ${styles[riskTone(risk)]}`}>{risk} risk</span>
}

export function EditedBadge() {
  return <span className={`${styles.badge} ${styles.edited}`}>Edited</span>
}

/** An answer the officer typed: no recording, nothing to transcribe. */
export function TypedBadge() {
  return <span className={`${styles.badge} ${styles.typed}`}>Typed</span>
}
