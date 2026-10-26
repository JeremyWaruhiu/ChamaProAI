import { AnimatePresence, m } from 'motion/react'
import { useCallback, useMemo, useRef, useState, type ReactNode } from 'react'
import { fadeUp, useReducedMotion } from '../lib/motion'
import { t } from '../strings'
import { Icon } from './Icon'
import { ToastContext, type ToastTone } from './toastContext'
import styles from './ui.module.css'

interface ToastItem { id: number; tone: ToastTone; text: string }

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const next = useRef(1)
  const reduced = useReducedMotion()

  const dismiss = useCallback((id: number) => setItems((xs) => xs.filter((x) => x.id !== id)), [])
  const show = useCallback((text: string, tone: ToastTone = 'success') => {
    const id = next.current++
    setItems((xs) => [...xs.slice(-2), { id, tone, text }])
    window.setTimeout(() => dismiss(id), tone === 'error' ? 8000 : 4500)
  }, [dismiss])
  const value = useMemo(() => show, [show])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className={styles.toasts} role="region" aria-label={t.toast.region}>
        <div aria-live="polite" aria-atomic="false">
          <AnimatePresence initial={false}>
            {items.map((x) => (
              <m.div key={x.id} className={`${styles.toast} ${styles[`toast-${x.tone}`]}`}
                          {...fadeUp(reduced, 0, 12)}>
                <Icon name={x.tone === 'error' ? 'alert' : x.tone === 'info' ? 'info' : 'check'} size={18} />
                <span className={styles.toastText}>{x.text}</span>
                <button type="button" className={styles.toastClose} onClick={() => dismiss(x.id)} aria-label={t.toast.dismiss}>
                  <Icon name="x" size={16} />
                </button>
              </m.div>
            ))}
          </AnimatePresence>
        </div>
      </div>
    </ToastContext.Provider>
  )
}
