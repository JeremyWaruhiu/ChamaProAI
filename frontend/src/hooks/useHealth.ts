import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Health } from '../api/types'

/**
 * GET /api/health once per mount, for the speech engine actually in use.
 * null until it answers, and stays null if it fails: callers then make no
 * claim about timing rather than show an error.
 */
export function useHealth() {
  const [health, setHealth] = useState<Health | null>(null)
  useEffect(() => {
    let live = true
    api.health().then((h) => { if (live) setHealth(h) }, () => {})
    return () => { live = false }
  }, [])
  return health
}
