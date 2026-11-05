import { useSyncExternalStore } from 'react'

// Presentation mode: no navigation, everything larger. Kept per browser, so a reload in
// front of the audience stays in it.
const KEY = 'chamapro.presentation'
const listeners = new Set<() => void>()

function read(): boolean {
  try { return window.localStorage.getItem(KEY) === '1' } catch { return false }
}

let current = typeof window === 'undefined' ? false : read()

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

export function setPresentationMode(on: boolean) {
  current = on
  document.documentElement.dataset.presentation = on ? '1' : '0'
  try { window.localStorage.setItem(KEY, on ? '1' : '0') } catch { /* private mode: not remembered */ }
  listeners.forEach((l) => l())
}

if (typeof document !== 'undefined') document.documentElement.dataset.presentation = current ? '1' : '0'

export function usePresentationMode(): [boolean, (on: boolean) => void] {
  const on = useSyncExternalStore(subscribe, () => current, () => false)
  return [on, setPresentationMode]
}
