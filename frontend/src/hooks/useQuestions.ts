import { useCallback, useEffect, useState } from 'react'
import { ApiError, api } from '../api/client'
import type { Question, QuestionSet } from '../api/types'

const cache: Partial<Record<QuestionSet, Question[]>> = {}

/** One question set, in order. Fetched once per page load; it does not change. */
export function useQuestions(version: QuestionSet | undefined) {
  const [questions, setQuestions] = useState<Question[] | null>(version ? cache[version] ?? null : null)
  const [error, setError] = useState<ApiError | null>(null)

  const load = useCallback(async () => {
    if (!version) return
    try {
      const qs = await api.questions(version)
      cache[version] = qs
      setQuestions(qs)
      setError(null)
    } catch (e) {
      setError(e as ApiError)
    }
  }, [version])

  // The set is known once the interview has loaded: adopt it from the cache, else fetch it.
  // oxlint-disable-next-line react/set-state-in-effect -- runs when the set becomes known; a fetch sets state after the await
  useEffect(() => { if (version && cache[version]) setQuestions(cache[version] ?? null); else load() }, [version, load])

  return { questions, error, retry: load }
}
