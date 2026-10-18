import { useCallback, useEffect, useState } from 'react'
import { ApiError, api } from '../api/client'
import type { Question } from '../api/types'

let cache: Question[] | null = null

/** The 40-question script. Fetched once per page load; it does not change. */
export function useQuestions() {
  const [questions, setQuestions] = useState<Question[] | null>(cache)
  const [error, setError] = useState<ApiError | null>(null)

  const load = useCallback(async () => {
    try {
      cache = await api.questions()
      setQuestions(cache)
      setError(null)
    } catch (e) {
      setError(e as ApiError)
    }
  }, [])

  // oxlint-disable-next-line react/set-state-in-effect -- fetch on mount; state is set after the await
  useEffect(() => { if (!cache) load() }, [load])

  return { questions, error, retry: load }
}
