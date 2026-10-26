import { AnimatePresence, m } from 'motion/react'
import { useEffect, useId, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { cx } from '../lib/cx'
import { fade, fadeUp, useReducedMotion } from '../lib/motion'
import type { StageState } from '../lib/status'
import type { Tone } from '../lib/status'
import { t } from '../strings'
import { Icon, type IconName } from './Icon'
import styles from './ui.module.css'

// The shared building blocks every screen is made from.

// --- Badge -------------------------------------------------------------------------

export function Badge({ tone = 'neutral', icon, children, title }: {
  tone?: Tone; icon?: IconName; children: ReactNode; title?: string
}) {
  return (
    <span className={cx(styles.badge, styles[`tone-${tone}`])} title={title}>
      {icon && <Icon name={icon} size={14} />}
      {children}
    </span>
  )
}

/** On every practice interview and application, wherever it is shown. */
export function PracticeBadge() {
  return <Badge tone="practice" icon="sparkle" title={t.common.practiceTitle}>{t.common.practice}</Badge>
}

// --- Page header -------------------------------------------------------------------

export function PageHeader({ eyebrow, title, lead, actions, badges }: {
  eyebrow?: ReactNode; title: ReactNode; lead?: ReactNode; actions?: ReactNode; badges?: ReactNode
}) {
  const reduced = useReducedMotion()
  return (
    <m.header className={styles.pageHeader} {...fadeUp(reduced)}>
      <div className={styles.pageHeaderText}>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <div className={styles.titleRow}>
          <h1 className={cx('display', styles.pageTitle)}>{title}</h1>
          {badges}
        </div>
        {lead && <p className={styles.lead}>{lead}</p>}
      </div>
      {actions && <div className={styles.pageActions}>{actions}</div>}
    </m.header>
  )
}

// --- Card ---------------------------------------------------------------------------

export function Card({ title, eyebrow, actions, children, className, delay = 0, as = 'section', id }: {
  title?: ReactNode; eyebrow?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string
  delay?: number; as?: 'section' | 'div' | 'article'; id?: string
}) {
  const reduced = useReducedMotion()
  const headingId = useId()
  const Tag = m[as]
  return (
    <Tag className={cx('card', styles.card, className)} aria-labelledby={title ? headingId : undefined} id={id}
         {...fadeUp(reduced, delay)}>
      {(title || actions || eyebrow) && (
        <div className={styles.cardHead}>
          <div>
            {eyebrow && <p className="eyebrow">{eyebrow}</p>}
            {title && <h2 id={headingId} className={styles.cardTitle}>{title}</h2>}
          </div>
          {actions && <div className={styles.cardActions}>{actions}</div>}
        </div>
      )}
      {children}
    </Tag>
  )
}

// --- Stat (KPI) ---------------------------------------------------------------------

export function Kpi({ label, value, note, icon, tone = 'neutral', href }: {
  label: string; value: ReactNode; note?: ReactNode; icon?: IconName; tone?: Tone; href?: string
}) {
  const body = (
    <>
      <span className={styles.kpiTop}>
        {icon && <span className={cx(styles.kpiIcon, styles[`tone-${tone}`])}><Icon name={icon} size={18} /></span>}
        <span className={styles.kpiLabel}>{label}</span>
      </span>
      <span className={cx(styles.kpiValue, 'num')}>{value}</span>
      {note && <span className={styles.kpiNote}>{note}</span>}
    </>
  )
  return href
    ? <a className={cx('card', styles.kpi, styles.kpiLink)} href={href}>{body}</a>
    : <div className={cx('card', styles.kpi)}>{body}</div>
}

// --- Empty state ---------------------------------------------------------------------

export function EmptyState({ icon = 'list', title, children, action }: {
  icon?: IconName; title: string; children?: ReactNode; action?: ReactNode
}) {
  return (
    <div className={styles.empty}>
      <svg className={styles.emptyArt} viewBox="0 0 120 80" aria-hidden focusable="false">
        <ellipse cx="60" cy="70" rx="44" ry="6" fill="var(--surface-sunken)" />
        <rect x="26" y="14" width="68" height="48" rx="8" fill="var(--surface)" stroke="var(--line-strong)" />
        <path d="M26 26h68" stroke="var(--line)" />
        <circle cx="34" cy="20" r="2" fill="var(--clay-200)" /><circle cx="41" cy="20" r="2" fill="var(--ochre-300)" />
        <circle cx="48" cy="20" r="2" fill="var(--green-200)" />
      </svg>
      <span className={styles.emptyIcon}><Icon name={icon} size={22} /></span>
      <p className={styles.emptyTitle}>{title}</p>
      {children && <div className={styles.emptyBody}>{children}</div>}
      {action && <div className={styles.emptyAction}>{action}</div>}
    </div>
  )
}

// --- Skeletons -----------------------------------------------------------------------

export function Skeleton({ width = '100%', height = 16, radius }: { width?: number | string; height?: number; radius?: number }) {
  return <span className="skeleton" style={{ width, height, borderRadius: radius }} aria-hidden />
}

/** Placeholder rows while a list or page loads. Announced once, politely. */
export function SkeletonList({ rows = 4, what }: { rows?: number; what: string }) {
  return (
    <div className={styles.skeletonList} role="status" aria-label={t.app.loading(what)}>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className={styles.skeletonRow}>
          <Skeleton width={40} height={40} radius={10} />
          <div className={styles.skeletonLines}>
            <Skeleton width={`${60 - (i % 3) * 12}%`} height={14} />
            <Skeleton width={`${35 + (i % 2) * 15}%`} height={12} />
          </div>
        </div>
      ))}
    </div>
  )
}

export function SkeletonPage({ what }: { what: string }) {
  return (
    <div className={styles.skeletonPage} role="status" aria-label={t.app.loading(what)}>
      <Skeleton width="40%" height={30} />
      <Skeleton width="65%" height={16} />
      <div className={styles.skeletonGrid}>
        <Skeleton height={120} radius={12} />
        <Skeleton height={120} radius={12} />
        <Skeleton height={120} radius={12} />
      </div>
      <Skeleton height={220} radius={12} />
    </div>
  )
}

// --- Stepper -------------------------------------------------------------------------

export function Stepper({ steps, current, label, onStep }: {
  steps: string[]; current: number; label: string
  /** Lets the user go back to an earlier step. */
  onStep?: (index: number) => void
}) {
  return (
    <nav aria-label={label} className={styles.stepperNav}>
      <ol className={styles.stepper}>
        {steps.map((s, i) => {
          const state = i < current ? 'done' : i === current ? 'current' : 'upcoming'
          const inner = (
            <>
              <span className={styles.stepDot} aria-hidden>{state === 'done' ? <Icon name="check" size={14} /> : i + 1}</span>
              <span className={styles.stepLabel}>{s}</span>
            </>
          )
          return (
            <li key={s} className={cx(styles.step, styles[`step-${state}`])} aria-current={state === 'current' ? 'step' : undefined}>
              {state === 'done' && onStep
                ? <button type="button" className={styles.stepButton} onClick={() => onStep(i)}>{inner}</button>
                : <span className={styles.stepButton}>{inner}</span>}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

// --- Timeline ------------------------------------------------------------------------

export interface TimelineItem {
  key: string
  title: ReactNode
  meta?: ReactNode
  state: StageState
  /** Read out with the title, e.g. "done", "in progress". */
  stateLabel?: string
}

export function Timeline({ items, label, compact = false }: { items: TimelineItem[]; label: string; compact?: boolean }) {
  return (
    <ol className={cx(styles.timeline, compact && styles.timelineCompact)} aria-label={label}>
      {items.map((it) => (
        <li key={it.key} className={cx(styles.tlItem, styles[`tl-${it.state}`])}
            aria-current={it.state === 'current' ? 'step' : undefined}>
          <span className={styles.tlDot} aria-hidden>
            {it.state === 'done' && <Icon name="check" size={12} />}
            {it.state === 'failed' && <Icon name="x" size={12} />}
          </span>
          <div className={styles.tlBody}>
            <span className={styles.tlTitle}>
              {it.title}
              {it.stateLabel && <span className="visually-hidden">, {it.stateLabel}</span>}
            </span>
            {it.meta && <span className={styles.tlMeta}>{it.meta}</span>}
          </div>
        </li>
      ))}
    </ol>
  )
}

// --- Field ---------------------------------------------------------------------------

/** A label, the control, a hint and an error, wired together for screen readers. */
export function Field({ id, label, hint, error, children, optional = false }: {
  id: string; label: ReactNode; hint?: ReactNode; error?: string | null; optional?: boolean
  children: (props: { id: string; 'aria-invalid'?: true; 'aria-describedby'?: string }) => ReactNode
}) {
  const describedBy = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(' ') || undefined
  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>
        {label}{optional && <span className="subtle"> {t.common.optional}</span>}
      </label>
      {children({ id, 'aria-invalid': error ? true : undefined, 'aria-describedby': describedBy })}
      {hint && <p id={`${id}-hint`} className="field-hint">{hint}</p>}
      {error && <p id={`${id}-error`} className="field-error">{error}</p>}
    </div>
  )
}

// --- Modal ---------------------------------------------------------------------------

/** A dialog that traps focus, closes on Escape, and returns focus where it came from. */
export function Modal({ open, title, onClose, children, actions }: {
  open: boolean; title: string; onClose: () => void; children?: ReactNode; actions?: ReactNode
}) {
  const reduced = useReducedMotion()
  const panel = useRef<HTMLDivElement>(null)
  const titleId = useId()

  useEffect(() => {
    if (!open) return
    const before = document.activeElement as HTMLElement | null
    const focusables = () => panel.current?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])') ?? []
    ;(focusables()[0] ?? panel.current)?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); onClose() }
      if (e.key !== 'Tab') return
      const f = [...focusables()]
      if (!f.length) return
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus() }
      else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus() }
    }
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('keydown', onKey); before?.focus?.() }
  }, [open, onClose])

  if (typeof document === 'undefined') return null
  return createPortal(
    <AnimatePresence>
      {open && (
        <m.div className={styles.overlay} {...fade(reduced)} onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
          <m.div ref={panel} className={styles.modal} role="dialog" aria-modal="true" aria-labelledby={titleId}
                      tabIndex={-1} {...fadeUp(reduced, 0, 12)}>
            <div className={styles.modalHead}>
              <h2 id={titleId} className={styles.modalTitle}>{title}</h2>
              <button type="button" className={cx('btn btn-quiet btn-sm', styles.modalClose)} onClick={onClose}
                      aria-label={t.modal.close}>
                <Icon name="x" />
              </button>
            </div>
            {children && <div className={styles.modalBody}>{children}</div>}
            {actions && <div className={styles.modalActions}>{actions}</div>}
          </m.div>
        </m.div>
      )}
    </AnimatePresence>,
    document.body,
  )
}

// --- Definition list ------------------------------------------------------------------

export function DetailList({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <dl className={styles.details}>
      {items.map(([k, v], i) => (
        <div key={i} className={styles.detailRow}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  )
}

