import { useEffect, useState } from 'react'

// A hash router is all four screens need, and it keeps the dashboard free of
// a routing dependency. Routes:
//   #/                               interviews list
//   #/interviews/:id/record[/:n]     recording, question n
//   #/interviews/:id/review          transcript review
//   #/interviews/:id/assessment      credit assessment
//   #/admin/results                  model & evaluation (read-only)

export type Route =
  | { screen: 'list' }
  | { screen: 'record'; id: number; question: number | null }
  | { screen: 'review'; id: number }
  | { screen: 'assessment'; id: number }
  | { screen: 'results' }

export function parse(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean)
  const id = Number(parts[1])
  if (parts[0] === 'admin' && parts[1] === 'results' && parts.length === 2) return { screen: 'results' }
  if (parts[0] === 'interviews' && Number.isInteger(id) && id > 0) {
    if (parts[2] === 'record') {
      const n = Number(parts[3])
      return { screen: 'record', id, question: Number.isInteger(n) && n > 0 ? n : null }
    }
    if (parts[2] === 'review') return { screen: 'review', id }
    if (parts[2] === 'assessment') return { screen: 'assessment', id }
  }
  return { screen: 'list' }
}

export const paths = {
  list: () => '#/',
  record: (id: number, n?: number) => `#/interviews/${id}/record${n ? `/${n}` : ''}`,
  review: (id: number) => `#/interviews/${id}/review`,
  assessment: (id: number) => `#/interviews/${id}/assessment`,
  results: () => '#/admin/results',
}

export function navigate(hash: string) {
  if (window.location.hash !== hash) window.location.hash = hash
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parse(window.location.hash))
  useEffect(() => {
    const onChange = () => {
      setRoute(parse(window.location.hash))
      window.scrollTo(0, 0)
    }
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return route
}
