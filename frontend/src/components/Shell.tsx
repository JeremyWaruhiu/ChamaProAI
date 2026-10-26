import type { ReactNode } from 'react'
import { paths } from '../lib/router'
import { t } from '../strings'
import { Icon } from './Icon'
import styles from './Shell.module.css'
import { PracticeBadge } from './ui'

export type Step = 'record' | 'review' | 'assessment'

const STEPS: { key: Step; label: string; href: (id: number) => string }[] = [
  { key: 'record', label: t.shell.stepRecord, href: (id) => paths.record(id) },
  { key: 'review', label: t.shell.stepReview, href: paths.review },
  { key: 'assessment', label: t.shell.stepAssessment, href: paths.assessment },
]

interface Props {
  title: ReactNode
  aside?: ReactNode
  /** Interview screens show the back link and the three-step flow. */
  interviewId?: number
  step?: Step
  /** The loan application the interview belongs to, for the back link. */
  applicationId?: number | null
  /** A practice interview: every screen of it says so. */
  practice?: boolean
  children: ReactNode
}

/** The frame of an interview screen inside the staff layout: steps, title, practice banner. */
export function Shell({ title, aside, interviewId, step, applicationId, practice, children }: Props) {
  return (
    <div className={styles.shell}>
      {interviewId !== undefined && (
        <nav className={styles.steps} aria-label={t.shell.steps}>
          <a className={styles.back} href={applicationId ? paths.application(applicationId) : paths.interviews()}>
            <Icon name="arrowLeft" size={18} />
            {applicationId ? t.shell.application(applicationId) : t.shell.allInterviews}
          </a>
          <ol className={styles.stepList}>
            {STEPS.map((s, i) => (
              <li key={s.key}>
                <a href={s.href(interviewId)} className={styles.step} aria-current={s.key === step ? 'step' : undefined}>
                  <span className={styles.stepNo}>{i + 1}</span>{s.label}
                </a>
              </li>
            ))}
          </ol>
        </nav>
      )}
      <header className={styles.head}>
        <h1 className={`display ${styles.title}`}>{title}</h1>
        {practice && <PracticeBadge />}
        {aside && <div className={styles.aside}>{aside}</div>}
      </header>
      {practice && <PracticeBanner />}
      <div className={styles.body}>{children}</div>
    </div>
  )
}

export function PracticeBanner() {
  return (
    <div className={styles.practice} role="note">
      <Icon name="sparkle" size={18} />
      <p><strong>{t.shell.practiceBanner}</strong> {t.shell.practiceBannerBody}</p>
    </div>
  )
}
