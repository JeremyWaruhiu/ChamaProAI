import { Component, type ErrorInfo, type ReactNode } from 'react'
import { t } from '../strings'
import { Icon, type IconName } from './Icon'
import styles from './Notice.module.css'

type Tone = 'error' | 'info' | 'warning' | 'calm'

const ICON: Record<Tone, IconName> = { error: 'alert', info: 'info', warning: 'alert', calm: 'clock' }

interface NoticeProps {
  tone?: Tone
  title?: ReactNode
  children?: ReactNode
  action?: ReactNode
}

export function Notice({ tone = 'info', title, children, action }: NoticeProps) {
  return (
    <div className={`${styles.notice} ${styles[tone]}`} role={tone === 'error' ? 'alert' : 'status'}>
      <Icon name={ICON[tone]} className={styles.icon} />
      <div className={styles.body}>
        {title && <p className={styles.title}>{title}</p>}
        {children && <div className={styles.text}>{children}</div>}
      </div>
      {action && <div className={styles.action}>{action}</div>}
    </div>
  )
}

/** An API failure: what we were doing, then the server's own detail message. */
export function ErrorNotice({ doing, error, onRetry }: { doing: string; error: { message: string }; onRetry?: () => void }) {
  return (
    <Notice tone="error" title={doing} action={onRetry &&
      <button className="btn btn-secondary" onClick={onRetry}>{t.common.retry}</button>}>
      {error.message}
    </Notice>
  )
}

export function Loading({ what }: { what: string }) {
  return (
    <div className={styles.loading} role="status">
      <span className="spinner" aria-hidden /> {t.app.loading(what)}
    </div>
  )
}

/** Last line of defence: a rendering bug shows a message, never a blank page. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Dashboard error', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className={styles.crash}>
        <Notice tone="error" title={t.notice.crashTitle}
                action={<button className="btn btn-primary" onClick={() => window.location.reload()}>{t.notice.reload}</button>}>
          {t.notice.crashBody(this.state.error.message)}
        </Notice>
      </div>
    )
  }
}
