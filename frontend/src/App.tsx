import { domAnimation, LazyMotion, MotionConfig } from 'motion/react'
import { Suspense, lazy, useCallback, useEffect, useMemo, useState, type ComponentType, type ReactNode } from 'react'
import { ApiError, api, setUnauthorizedHandler } from './api/client'
import type { Me } from './api/types'
import { MemberLayout, StaffLayout } from './components/Layout'
import { ErrorBoundary, ErrorNotice, Loading } from './components/Notice'
import { ToastProvider } from './components/Toast'
import { SkeletonPage } from './components/ui'
import { AuthContext, isStaff, redirectFor } from './lib/auth'
import { parse, paths, redirect, useRoute, type Route } from './lib/router'
import { t } from './strings'

// Each screen is its own chunk, so the landing page and the member portal
// never download the staff screens, and a slow line loads only what it needs.
function screen<K extends string>(load: () => Promise<Record<K, ComponentType<never>>>, name: K) {
  return lazy(() => load().then((m) => ({ default: m[name] as ComponentType<Record<string, unknown>> })))
}

const Landing = screen(() => import('./screens/Landing'), 'Landing')
const Login = screen(() => import('./screens/Login'), 'Login')
const Profile = screen(() => import('./screens/Profile'), 'Profile')
const OfficerHome = screen(() => import('./screens/OfficerHome'), 'OfficerHome')
const StartInterview = screen(() => import('./screens/StartInterview'), 'StartInterview')
const InterviewList = screen(() => import('./screens/InterviewList'), 'InterviewList')
const Recording = screen(() => import('./screens/Recording'), 'Recording')
const Review = screen(() => import('./screens/Review'), 'Review')
const Assessment = screen(() => import('./screens/Assessment'), 'Assessment')
const Applications = screen(() => import('./screens/Applications'), 'Applications')
const ApplicationDetail = screen(() => import('./screens/ApplicationDetail'), 'ApplicationDetail')
const Members = screen(() => import('./screens/Members'), 'Members')
const MemberDetail = screen(() => import('./screens/MemberDetail'), 'MemberDetail')
const AdminHome = screen(() => import('./screens/AdminHome'), 'AdminHome')
const Users = screen(() => import('./screens/Users'), 'Users')
const AuditLog = screen(() => import('./screens/AuditLog'), 'AuditLog')
const Results = screen(() => import('./screens/Results'), 'Results')
const MyApplications = screen(() => import('./screens/MyApplications'), 'MyApplications')
const MyApplication = screen(() => import('./screens/MyApplication'), 'MyApplication')

type Session = { status: 'checking' } | { status: 'failed'; error: ApiError } | { status: 'ready'; user: Me | null }

/** The screen for a route; key: each screen and record starts from fresh state. */
function screenFor(route: Route, onSignedIn: (me: Me) => void): ReactNode {
  switch (route.screen) {
    case 'landing': return <Landing />
    case 'login': return <Login onSignedIn={onSignedIn} />
    case 'profile': return <Profile />
    case 'home': return <OfficerHome />
    case 'start': return <StartInterview key={`s${route.memberId}`} memberId={route.memberId} />
    case 'interviews': return <InterviewList />
    case 'record': return <Recording key={`r${route.id}`} id={route.id} question={route.question} />
    case 'review': return <Review key={`v${route.id}`} id={route.id} />
    case 'assessment': return <Assessment key={`a${route.id}`} id={route.id} />
    case 'applications': return <Applications key={`l${route.status}`} status={route.status} />
    case 'application': return <ApplicationDetail key={`p${route.id}`} id={route.id} />
    case 'members': return <Members />
    case 'member': return <MemberDetail key={`m${route.id}`} id={route.id} />
    case 'admin': return <AdminHome />
    case 'users': return <Users />
    case 'audit': return <AuditLog />
    case 'results': return <Results />
    case 'my': return <MyApplications />
    case 'myApplication': return <MyApplication key={`y${route.id}`} id={route.id} />
    case 'notFound': return null
  }
}

export default function App() {
  useRoute() // re-render on every hash change
  // Render from the live hash: it can be ahead of the hashchange event after a redirect.
  const route = parse(window.location.hash)
  const [session, setSession] = useState<Session>({ status: 'checking' })

  const check = useCallback(async () => {
    setSession({ status: 'checking' })
    try {
      setSession({ status: 'ready', user: await api.me() })
    } catch (e) {
      const err = e as ApiError
      // 401 is "not signed in"; anything else (server down) is shown with Retry
      setSession(err.status === 401 ? { status: 'ready', user: null } : { status: 'failed', error: err })
    }
  }, [])

  // oxlint-disable-next-line react/set-state-in-effect -- ask the server who is signed in, once on load
  useEffect(() => { check() }, [check])

  // Any 401 from the API means the session has gone: back to login.
  useEffect(() => {
    setUnauthorizedHandler(() => setSession({ status: 'ready', user: null }))
    return () => setUnauthorizedHandler(null)
  }, [])

  const user = session.status === 'ready' ? session.user : null
  const pending = session.status === 'ready' ? redirectFor(window.location.hash, user) : null
  useEffect(() => { if (pending) redirect(pending) }, [pending])

  const signOut = useCallback(async () => {
    setSession({ status: 'ready', user: null })
    redirect(paths.login())
    try { await api.logout() } catch { /* already signed out, or the server is down; the screen is locked either way */ }
  }, [])
  const auth = useMemo(() => ({ user, signOut }), [user, signOut])
  const onSignedIn = useCallback((me: Me) => setSession({ status: 'ready', user: me }), [])

  if (session.status === 'checking') return <div className="boot"><Loading what={t.app.loadingApp} /></div>
  if (session.status === 'failed') {
    return <div className="boot"><ErrorNotice doing={t.app.unreachable} error={session.error} onRetry={check} /></div>
  }
  if (pending) return <div className="boot"><Loading what={t.app.loadingApp} /></div>

  const content = (
    <ErrorBoundary key={window.location.hash}>
      <Suspense fallback={<SkeletonPage what={t.app.loadingApp} />}>{screenFor(route, onSignedIn)}</Suspense>
    </ErrorBoundary>
  )
  const publicPage = route.screen === 'landing' || route.screen === 'login'
  let page: ReactNode = content
  if (user && !publicPage) {
    page = isStaff(user.role)
      ? <StaffLayout user={user} screen={route.screen}>{content}</StaffLayout>
      : <MemberLayout user={user} screen={route.screen}>{content}</MemberLayout>
  }

  return (
    <LazyMotion features={domAnimation} strict>
      <MotionConfig reducedMotion="user">
        <AuthContext.Provider value={auth}>
          <ToastProvider>{page}</ToastProvider>
        </AuthContext.Provider>
      </MotionConfig>
    </LazyMotion>
  )
}
