import { t } from '../strings'
import styles from './Layout.module.css'

/** The mark: a voice wave whose tallest bar grows a leaf — speech becoming growth. */
export function BrandMark({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden focusable="false">
      <rect width="32" height="32" rx="9" fill="var(--green-800)" />
      <rect x="0.75" y="0.75" width="30.5" height="30.5" rx="8.25" fill="none" stroke="rgb(255 255 255 / 14%)" />
      <g stroke="#f7f1e3" strokeWidth="2.6" strokeLinecap="round">
        <path d="M8 15v4M12.5 12v10M21 13v8M25 16v2" />
        <path d="M16.75 24V13" />
      </g>
      <path d="M16.75 13c0-3.6 2.4-6 6.2-6.2-.1 3.7-2.5 6.1-6.2 6.2Z" fill="var(--ochre-500)" />
    </svg>
  )
}

export function Brand({ compact = false, onDark = false }: { compact?: boolean; onDark?: boolean }) {
  return (
    <span className={`${styles.brand} ${onDark ? styles.brandDark : ''}`}>
      <BrandMark />
      {compact
        ? <span className="visually-hidden">{t.app.name}</span>
        : <span className={styles.brandWord}>ChamaPro<span className={styles.brandAi}> AI</span></span>}
    </span>
  )
}
