import type { Transition } from 'motion/react'
import { useEffect, useState } from 'react'

// Motion durations, mirrored from the --dur-* tokens in index.css. Motion is
// for entrances and state changes only; with prefers-reduced-motion it is
// removed, not just shortened: nothing moves, content appears at once.

export const DURATION = { fast: 0.12, base: 0.2, slow: 0.36 } as const
export const EASE_OUT: [number, number, number, number] = [0.2, 0.8, 0.2, 1]

const QUERY = '(prefers-reduced-motion: reduce)'

/** True when the user asked the system for less motion. Safe without a window (tests, SSR). */
export function prefersReducedMotion(win: Pick<Window, 'matchMedia'> | null | undefined =
  typeof window === 'undefined' ? undefined : window): boolean {
  return !!win?.matchMedia?.(QUERY).matches
}

/** prefersReducedMotion, kept up to date if the setting changes while the page is open. */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => prefersReducedMotion())
  useEffect(() => {
    const mq = window.matchMedia?.(QUERY)
    if (!mq) return
    const onChange = () => setReduced(mq.matches)
    mq.addEventListener?.('change', onChange)
    return () => mq.removeEventListener?.('change', onChange)
  }, [])
  return reduced
}

export interface Preset {
  initial: { opacity: number; y?: number; scale?: number }
  animate: { opacity: number; y?: number; scale?: number }
  exit?: { opacity: number; y?: number; scale?: number }
  transition: Transition
}

/** Fade in while rising a little: page and card entrances. */
export function fadeUp(reduced: boolean, delay = 0, distance = 8): Preset {
  if (reduced) return { initial: { opacity: 1, y: 0 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0 } }
  return {
    initial: { opacity: 0, y: distance },
    animate: { opacity: 1, y: 0 },
    exit: { opacity: 0, y: -distance / 2 },
    transition: { duration: DURATION.slow, delay, ease: EASE_OUT },
  }
}

/** Fade only: swapping one state for another in place (status chips, steps). */
export function fade(reduced: boolean): Preset {
  if (reduced) return { initial: { opacity: 1 }, animate: { opacity: 1 }, transition: { duration: 0 } }
  return {
    initial: { opacity: 0 },
    animate: { opacity: 1 },
    exit: { opacity: 0 },
    transition: { duration: DURATION.base, ease: EASE_OUT },
  }
}

/** Stagger for lists: the nth item's delay, capped so long lists do not crawl in. */
export function stagger(reduced: boolean, index: number, step = 0.04, cap = 0.3): number {
  return reduced ? 0 : Math.min(index * step, cap)
}
