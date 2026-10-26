import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'

/**
 * Fetch on mount (and whenever `load` changes), with an error to show and a
 * reload for Retry. `load` should be stable (useCallback). A slower, older
 * request never overwrites a newer one.
 */
export function useLoad<T>(load: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const seq = useRef(0)

  const reload = useCallback(async () => {
    const mine = ++seq.current
    try {
      const next = await load()
      if (mine === seq.current) { setData(next); setError(null) }
    } catch (e) {
      if (mine === seq.current) setError(e instanceof ApiError ? e : new ApiError(0, String(e)))
    }
  }, [load])

  // oxlint-disable-next-line react/set-state-in-effect -- fetch on mount; state is set after the await
  useEffect(() => { reload() }, [reload])

  return { data, error, reload, setData }
}
