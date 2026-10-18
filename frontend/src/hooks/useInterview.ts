import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, api } from '../api/client'
import type { InterviewState } from '../api/types'

const POLL_MS = 3000

export const pending = (s: InterviewState | null) =>
  !!s && s.counts.queued + s.counts.transcribing > 0

/**
 * Load an interview and keep it fresh. Polls every 3 s while any answer is
 * queued or transcribing, and stops as soon as nothing is. Pauses while the
 * tab is hidden.
 */
export function useInterview(id: number) {
  const [data, setData] = useState<InterviewState | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const seq = useRef(0)

  const refresh = useCallback(async () => {
    const mine = ++seq.current
    try {
      const next = await api.interview(id)
      if (mine === seq.current) {
        setData(next)
        setError(null)
      }
    } catch (e) {
      if (mine === seq.current) setError(e instanceof ApiError ? e : new ApiError(0, String(e)))
    }
  }, [id])

  // Screens are keyed by interview id (App.tsx), so a new id is a fresh mount.
  // oxlint-disable-next-line react/set-state-in-effect -- fetch on mount; state is set after the await
  useEffect(() => { refresh() }, [refresh])

  const polling = pending(data)
  useEffect(() => {
    if (!polling) return
    const timer = setInterval(() => {
      if (!document.hidden) refresh()
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [polling, refresh])

  return { data, error, refresh, polling }
}
