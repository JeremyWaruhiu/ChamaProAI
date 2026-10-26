// @vitest-environment jsdom
import { act, render, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PipelineHero } from '../components/PipelineHero'
import css from '../index.css?raw'
import { DURATION, fade, fadeUp, prefersReducedMotion, stagger, useReducedMotion } from './motion'

/** A matchMedia whose reduced-motion answer the test controls. */
function stubMotion(reduced: boolean) {
  const listeners = new Set<() => void>()
  const mq = {
    matches: reduced, media: '(prefers-reduced-motion: reduce)',
    addEventListener: (_: string, fn: () => void) => listeners.add(fn),
    removeEventListener: (_: string, fn: () => void) => listeners.delete(fn),
  }
  vi.stubGlobal('matchMedia', vi.fn(() => mq))
  return { set(v: boolean) { mq.matches = v; listeners.forEach((fn) => fn()) } }
}

afterEach(() => vi.unstubAllGlobals())

describe('reduced motion', () => {
  it('reads the system setting, and is off without a window', () => {
    stubMotion(true)
    expect(prefersReducedMotion()).toBe(true)
    expect(prefersReducedMotion(null)).toBe(false)
  })

  it('follows the setting when it changes while the page is open', () => {
    const m = stubMotion(false)
    const { result } = renderHook(() => useReducedMotion())
    expect(result.current).toBe(false)
    act(() => m.set(true))
    expect(result.current).toBe(true)
  })

  it('presets move nothing and take no time when reduced', () => {
    for (const p of [fadeUp(true, 0.3), fade(true)]) {
      expect(p.initial).toEqual(p.animate)
      expect(p.initial.opacity).toBe(1)
      expect(p.transition).toEqual({ duration: 0 })
    }
    expect(stagger(true, 5)).toBe(0)
  })

  it('presets animate briefly otherwise, with the shared durations', () => {
    const p = fadeUp(false)
    expect(p.initial).toEqual({ opacity: 0, y: 8 })
    expect(p.transition.duration).toBe(DURATION.slow)
    expect(stagger(false, 100)).toBe(0.3)          // capped
  })

  it('draws the landing illustration complete, with nothing hidden, when reduced', () => {
    stubMotion(true)
    const { container } = render(<PipelineHero />)
    expect(container.querySelector('svg[role="img"]')).not.toBeNull()
    expect(container.innerHTML).not.toMatch(/opacity:\s*0[;"]/)
  })

  it('starts the illustration hidden, to play in, when motion is allowed', () => {
    stubMotion(false)
    const { container } = render(<PipelineHero />)
    expect(container.innerHTML).toMatch(/opacity:\s*0/)
  })

  it('stops every CSS animation and transition in the stylesheet when reduced', () => {
    const block = css.slice(css.indexOf('@media (prefers-reduced-motion: reduce)'))
    expect(block).toMatch(/animation-duration:\s*0\.01ms !important/)
    expect(block).toMatch(/transition-duration:\s*0\.01ms !important/)
  })
})
