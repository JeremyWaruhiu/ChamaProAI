import { useEffect, useState } from 'react'

// A hash router keeps the app free of a routing dependency. Routes:
//   #/                                 public landing page
//   #/login[?next=<hash>]              sign in, then return to next
//   #/profile                          your own account (every role)
// Staff (officers and admins):
//   #/app                              officer home
//   #/app/start[?member=<id>]          start-interview wizard
//   #/interviews                       every interview
//   #/interviews/:id/record[/:n]       interview runner, question n
//   #/interviews/:id/review            transcript review
//   #/interviews/:id/assessment        assessment and decision
//   #/applications[?status=<s>]        loan applications
//   #/applications/:id                 one application: timeline, guarantors
//   #/members                          members
//   #/members/:id                      one member and their applications
// Admins:
//   #/admin                            admin home
//   #/admin/users                      users
//   #/admin/audit                      audit log
//   #/admin/results                    model & evaluation (read-only)
// Members:
//   #/my                               my applications
//   #/my/applications/:id              one of my applications

export type Route =
  | { screen: 'landing' }
  | { screen: 'login'; next: string | null }
  | { screen: 'profile' }
  | { screen: 'home' }
  | { screen: 'start'; memberId: number | null }
  | { screen: 'interviews' }
  | { screen: 'record'; id: number; question: number | null }
  | { screen: 'review'; id: number }
  | { screen: 'assessment'; id: number }
  | { screen: 'applications'; status: string | null }
  | { screen: 'application'; id: number }
  | { screen: 'members' }
  | { screen: 'member'; id: number }
  | { screen: 'admin' }
  | { screen: 'users' }
  | { screen: 'audit' }
  | { screen: 'results' }
  | { screen: 'my' }
  | { screen: 'myApplication'; id: number }
  | { screen: 'notFound' }

export type Screen = Route['screen']

const positive = (s: string | undefined | null): number | null => {
  const n = Number(s)
  return s && Number.isInteger(n) && n > 0 ? n : null
}

export function parse(hash: string): Route {
  const [path, query = ''] = hash.split('?', 2)
  const parts = path.replace(/^#\/?/, '').split('/').filter(Boolean)
  const params = new URLSearchParams(query)
  const [a, b, c, d] = parts
  const n = parts.length
  const id = positive(b)

  if (n === 0) return { screen: 'landing' }
  if (a === 'login' && n === 1) return { screen: 'login', next: params.get('next') }
  if (a === 'profile' && n === 1) return { screen: 'profile' }
  if (a === 'app') {
    if (n === 1) return { screen: 'home' }
    if (b === 'start' && n === 2) return { screen: 'start', memberId: positive(params.get('member')) }
  }
  if (a === 'interviews') {
    if (n === 1) return { screen: 'interviews' }
    if (id) {
      if (c === 'record' && n <= 4) return { screen: 'record', id, question: positive(d) }
      if (c === 'review' && n === 3) return { screen: 'review', id }
      if (c === 'assessment' && n === 3) return { screen: 'assessment', id }
    }
  }
  if (a === 'applications') {
    if (n === 1) return { screen: 'applications', status: params.get('status') }
    if (id && n === 2) return { screen: 'application', id }
  }
  if (a === 'members') {
    if (n === 1) return { screen: 'members' }
    if (id && n === 2) return { screen: 'member', id }
  }
  if (a === 'admin') {
    if (n === 1) return { screen: 'admin' }
    if (n === 2 && b === 'users') return { screen: 'users' }
    if (n === 2 && b === 'audit') return { screen: 'audit' }
    if (n === 2 && b === 'results') return { screen: 'results' }
  }
  if (a === 'my') {
    if (n === 1) return { screen: 'my' }
    if (b === 'applications' && n === 3 && positive(c)) return { screen: 'myApplication', id: positive(c)! }
  }
  return { screen: 'notFound' }
}

export const paths = {
  landing: () => '#/',
  login: (next?: string | null) => `#/login${next ? `?next=${encodeURIComponent(next)}` : ''}`,
  profile: () => '#/profile',
  home: () => '#/app',
  start: (memberId?: number) => `#/app/start${memberId ? `?member=${memberId}` : ''}`,
  interviews: () => '#/interviews',
  record: (id: number, n?: number) => `#/interviews/${id}/record${n ? `/${n}` : ''}`,
  review: (id: number) => `#/interviews/${id}/review`,
  assessment: (id: number) => `#/interviews/${id}/assessment`,
  applications: (status?: string | null) => `#/applications${status ? `?status=${encodeURIComponent(status)}` : ''}`,
  application: (id: number) => `#/applications/${id}`,
  members: () => '#/members',
  member: (id: number) => `#/members/${id}`,
  admin: () => '#/admin',
  users: () => '#/admin/users',
  audit: () => '#/admin/audit',
  results: () => '#/admin/results',
  my: () => '#/my',
  myApplication: (id: number) => `#/my/applications/${id}`,
}

export function navigate(hash: string) {
  if (window.location.hash !== hash) window.location.hash = hash
}

/** Like navigate, but replaces the history entry: for redirects the back button should skip. */
export function redirect(hash: string) {
  if (window.location.hash !== hash) window.location.replace(hash)
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
