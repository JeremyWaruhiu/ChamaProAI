import type { ReactNode } from 'react'
import { ROLE_LABEL, useAuth } from '../lib/auth'
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
  /** A practice interview: every screen of it says so. */
  practice?: boolean
  children: ReactNode
}

export function Shell({ title, aside, interviewId, step, practice, children }: Props) {
  return (
    <>
      <header className={styles.bar}>
        <div className={styles.barInner}>
          <h1 className={styles.title}>{title}</h1>
          <div className={styles.barEnd}>
            {aside && <div className={styles.aside}>{aside}</div>}
            <SignedIn />
          </div>
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
      {practice && <PracticeBanner />}
      <main className={styles.main}>{children}</main>
    </>
  )
}

export function PracticeBanner() {
  return (
    <div className={styles.practice} role="note">
      <p className={styles.practiceInner}>
        <strong>Practice interview.</strong> For training only: not a real application. Its results are
        left out of the live statistics and its decision is labelled practice.
      </p>
    </div>
  )
}

/** Who is signed in, and the way out. */
function SignedIn() {
  const { user, signOut } = useAuth()
  if (!user) return null
  return (
    <div className={styles.user}>
      <span className={styles.userName}>
        <span className="visually-hidden">Signed in as </span>{user.username}
        <span className={styles.role}>{ROLE_LABEL[user.role]}</span>
      </span>
      <button type="button" className={`btn ${styles.signOut}`} onClick={signOut}>Sign out</button>
    </div>
  )
}
