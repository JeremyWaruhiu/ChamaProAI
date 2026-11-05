import { useEffect, useState } from 'react'

// A hash router keeps the app free of a routing dependency. Routes:
//   #/                                 public landing page
//   #/login[?next=<hash>]              sign in, then return to next
//   #/signup                           volunteer sign-up (when the pilot is open)
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
//   #/decisions                        automatic decisions
//   #/decisions/:id                    one of them: its trace and SHAP, and reversing it
//   #/present                          the presenter view: conversations to follow
//   #/present/:id                      one conversation, live, with its whole working
//   #/bookings                         upcoming interviews and the week's calendar
//   #/events                           SACCO events
// Admins:
//   #/admin                            admin home
//   #/admin/users                      users
//   #/admin/audit                      audit log
//   #/admin/results                    model & evaluation (read-only)
//   #/admin/pilot                      the volunteer pilot's figures and exports
// Members:
//   #/my                               my applications
//   #/my/applications/:id              one of my applications
//   #/my/apply                         apply for a loan and book the interview
//   #/my/chat                          request a loan by talking: carry on, or choose a language
//   #/my/chat/:id                      that conversation, and how it came out
//     ...?stage=1                      either of those in a phone-sized frame, large enough for a shared screen
//   #/my/sacco                         my profile, balances, guarantors and loans
//   #/my/registration                  the registration profile form, once after sign-up
//   #/my/practice/:id[/:n]             my practice interview, question n
//   #/my/practice/:id/review           review my transcripts and submit
//   #/my/practice/:id/result           the result in words, and the questionnaire

export type Route =
  | { screen: 'landing' }
  | { screen: 'login'; next: string | null }
  | { screen: 'signup' }
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
  | { screen: 'decisions' }
  | { screen: 'decision'; id: number }
  | { screen: 'present' }
  | { screen: 'presentOne'; id: number }
  | { screen: 'bookings' }
  | { screen: 'events' }
  | { screen: 'admin' }
  | { screen: 'users' }
  | { screen: 'audit' }
  | { screen: 'results' }
  | { screen: 'pilot' }
  | { screen: 'my' }
  | { screen: 'myApplication'; id: number }
  | { screen: 'apply' }
  | { screen: 'chat'; id: number | null }
  | { screen: 'mySacco' }
  | { screen: 'registration' }
  | { screen: 'practice'; id: number; question: number | null }
  | { screen: 'practiceReview'; id: number }
  | { screen: 'practiceResult'; id: number }
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
  if (a === 'signup' && n === 1) return { screen: 'signup' }
  if (a === 'profile' && n === 1) return { screen: 'profile' }
  if (a === 'bookings' && n === 1) return { screen: 'bookings' }
  if (a === 'events' && n === 1) return { screen: 'events' }
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
  if (a === 'decisions') {
    if (n === 1) return { screen: 'decisions' }
    if (id && n === 2) return { screen: 'decision', id }
  }
  if (a === 'present') {
    if (n === 1) return { screen: 'present' }
    if (id && n === 2) return { screen: 'presentOne', id }
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
    if (n === 2 && b === 'pilot') return { screen: 'pilot' }
  }
  if (a === 'my') {
    if (n === 1) return { screen: 'my' }
    if (b === 'applications' && n === 3 && positive(c)) return { screen: 'myApplication', id: positive(c)! }
    if (b === 'apply' && n === 2) return { screen: 'apply' }
    if (b === 'chat' && n === 2) return { screen: 'chat', id: null }
    if (b === 'chat' && n === 3 && positive(c)) return { screen: 'chat', id: positive(c)! }
    if (b === 'sacco' && n === 2) return { screen: 'mySacco' }
    if (b === 'registration' && n === 2) return { screen: 'registration' }
    const practice = positive(c)
    if (b === 'practice' && practice) {
      if (n === 3) return { screen: 'practice', id: practice, question: null }
      if (n === 4 && d === 'review') return { screen: 'practiceReview', id: practice }
      if (n === 4 && d === 'result') return { screen: 'practiceResult', id: practice }
      if (n === 4 && positive(d)) return { screen: 'practice', id: practice, question: positive(d) }
    }
  }
  return { screen: 'notFound' }
}

export const paths = {
  landing: () => '#/',
  login: (next?: string | null) => `#/login${next ? `?next=${encodeURIComponent(next)}` : ''}`,
  signup: () => '#/signup',
  profile: () => '#/profile',
  home: () => '#/app',
  start: (memberId?: number) => `#/app/start${memberId ? `?member=${memberId}` : ''}`,
  interviews: () => '#/interviews',
  record: (id: number, n?: number) => `#/interviews/${id}/record${n ? `/${n}` : ''}`,
  review: (id: number) => `#/interviews/${id}/review`,
  assessment: (id: number) => `#/interviews/${id}/assessment`,
  applications: (status?: string | null) => `#/applications${status ? `?status=${encodeURIComponent(status)}` : ''}`,
  application: (id: number) => `#/applications/${id}`,
  decisions: () => '#/decisions',
  decision: (id: number) => `#/decisions/${id}`,
  present: () => '#/present',
  presentOne: (id: number) => `#/present/${id}`,
  members: () => '#/members',
  member: (id: number) => `#/members/${id}`,
  bookings: () => '#/bookings',
  events: () => '#/events',
  admin: () => '#/admin',
  users: () => '#/admin/users',
  audit: () => '#/admin/audit',
  results: () => '#/admin/results',
  pilot: () => '#/admin/pilot',
  my: () => '#/my',
  myApplication: (id: number) => `#/my/applications/${id}`,
  apply: () => '#/my/apply',
  chat: (id?: number, stage = false) => `#/my/chat${id ? `/${id}` : ''}${stage ? '?stage=1' : ''}`,
  mySacco: () => '#/my/sacco',
  registration: () => '#/my/registration',
  practice: (id: number, n?: number) => `#/my/practice/${id}${n ? `/${n}` : ''}`,
  practiceReview: (id: number) => `#/my/practice/${id}/review`,
  practiceResult: (id: number) => `#/my/practice/${id}/result`,
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

/** Whether this page was opened with ?stage=1. */
export const chatOnStage = () => new URLSearchParams(window.location.hash.split('?')[1] ?? '').get('stage') === '1'
