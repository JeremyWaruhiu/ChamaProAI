import type { ReactNode } from 'react'
import { paths } from '../lib/router'
import styles from './Shell.module.css'

export type Step = 'record' | 'review' | 'assessment'

const STEPS: { key: Step; label: string; href: (id: number) => string }[] = [
  { key: 'record', label: 'Record answers', href: (id) => paths.record(id) },
  { key: 'review', label: 'Review transcripts', href: paths.review },
  { key: 'assessment', label: 'Assessment', href: paths.assessment },
]

interface Props {
  title: ReactNode
  aside?: ReactNode
  /** Interview screens show the back link and the three-step flow. */
  interviewId?: number
  step?: Step
  children: ReactNode
}

export function Shell({ title, aside, interviewId, step, children }: Props) {
  return (
    <>
      <header className={styles.bar}>
        <div className={styles.barInner}>
          <h1 className={styles.title}>{title}</h1>
          {aside && <div className={styles.aside}>{aside}</div>}
        </div>
      </header>
      {interviewId !== undefined && (
        <nav className={styles.steps} aria-label="Interview steps">
          <div className={styles.stepsInner}>
            <a className={styles.back} href={paths.list()}>← All interviews</a>
            <ol className={styles.stepList}>
              {STEPS.map((s, i) => (
                <li key={s.key}>
                  <a href={s.href(interviewId)} className={styles.step}
                     aria-current={s.key === step ? 'step' : undefined}>
                    <span className={styles.stepNo}>{i + 1}</span>{s.label}
                  </a>
                </li>
              ))}
            </ol>
          </div>
        </nav>
      )}
      <main className={styles.main}>{children}</main>
    </>
  )
}
