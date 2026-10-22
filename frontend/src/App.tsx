import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, api, setUnauthorizedHandler } from './api/client'
import type { Me } from './api/types'
import { ErrorBoundary, ErrorNotice, Loading } from './components/Notice'
import { AuthContext, redirectFor } from './lib/auth'
import { parse, paths, redirect, useRoute } from './lib/router'
import { Assessment } from './screens/Assessment'
import { InterviewList } from './screens/InterviewList'
import { Login } from './screens/Login'
import { Recording } from './screens/Recording'
import { Results } from './screens/Results'
import { Review } from './screens/Review'

type Session = { status: 'checking' } | { status: 'failed'; error: ApiError } | { status: 'ready'; user: Me | null }

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

  if (session.status === 'checking') return <div className="boot"><Loading what="ChamaPro" /></div>
  if (session.status === 'failed') {
    return <div className="boot"><ErrorNotice doing="Could not reach ChamaPro" error={session.error} onRetry={check} /></div>
  }
  if (pending) return <div className="boot"><Loading what="ChamaPro" /></div>

  // key: each screen and interview starts from fresh state
  let screen
  switch (route.screen) {
    case 'login': screen = <Login onSignedIn={(me) => setSession({ status: 'ready', user: me })} />; break
    case 'record': screen = <Recording key={`r${route.id}`} id={route.id} question={route.question} />; break
    case 'review': screen = <Review key={`v${route.id}`} id={route.id} />; break
    case 'assessment': screen = <Assessment key={`a${route.id}`} id={route.id} />; break
    case 'results': screen = <Results />; break
    default: screen = <InterviewList />
  }
  return (
    <AuthContext.Provider value={auth}>
      <ErrorBoundary key={window.location.hash}>{screen}</ErrorBoundary>
    </AuthContext.Provider>
  )
}
