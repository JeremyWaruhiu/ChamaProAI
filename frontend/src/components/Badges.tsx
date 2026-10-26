import type { ApplicationStatus, Outcome, ResponseStatus } from '../api/types'
import { riskTone } from '../lib/risk'
import { OUTCOME_TONE, STATUS_TONE, outcomeLabel, statusLabel, type Tone } from '../lib/status'
import { t } from '../strings'
import styles from './Badges.module.css'
import { Badge } from './ui'

const RESPONSE_TONE: Record<ResponseStatus, Tone> = {
  queued: 'wait', transcribing: 'wait', transcribed: 'low', failed: 'high',
}

/** A transcription status chip: waiting, transcribing (pulsing), transcribed, failed. */
export function StatusBadge({ status }: { status: ResponseStatus }) {
  return (
    <Badge tone={RESPONSE_TONE[status]} icon={status === 'transcribed' ? 'check' : status === 'failed' ? 'alert' : undefined}>
      {status === 'transcribing' && <span className={styles.pulse} aria-hidden />}
      {t.status[status]}
    </Badge>
  )
}

export function RiskBadge({ risk }: { risk: string }) {
  const tone = riskTone(risk)
  return <Badge tone={tone === 'none' ? 'neutral' : tone}>{t.risk.badge(risk)}</Badge>
}

export function EditedBadge() {
  return <Badge tone="info" icon="edit">{t.status.edited}</Badge>
}

/** An answer the officer typed: no recording, nothing to transcribe. */
export function TypedBadge() {
  return <Badge tone="neutral" icon="keyboard">{t.status.typed}</Badge>
}

export function ApplicationStatusBadge({ status }: { status: ApplicationStatus }) {
  return <Badge tone={STATUS_TONE[status]}>{statusLabel(status)}</Badge>
}

export function OutcomeBadge({ outcome }: { outcome: Outcome }) {
  return <Badge tone={OUTCOME_TONE[outcome]}>{outcomeLabel(outcome)}</Badge>
}
