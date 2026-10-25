import { createContext, useContext } from 'react'
import type { Me } from '../api/types'
import { parse, paths, type Route } from './router'

export interface AuthState {
  user: Me | null
  signOut: () => void
}

export const AuthContext = createContext<AuthState>({ user: null, signOut: () => {} })

export function useAuth(): AuthState {
  return useContext(AuthContext)
}

export const ROLE_LABEL: Record<Me['role'], string> = {
  officer: 'Loan officer',
  admin: 'Administrator',
  member: 'Member',
}

/** Where to go after signing in: an in-app route, never back to the login page. */
export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith('#/')) return paths.list()
  return parse(next).screen === 'login' ? paths.list() : next
}

/**
 * The redirect a route needs for this user, or null to show it.
 *   - signed out: to login, remembering the route to come back to
 *   - signed in on the login page: on to where they were going
 *   - an officer on an admin page: to the interview list
 */
export function redirectFor(hash: string, user: Me | null): string | null {
  const route: Route = parse(hash)
  if (!user) {
    if (route.screen === 'login') return null
    return paths.login(route.screen === 'list' ? null : hash)
  }
  if (route.screen === 'login') return safeNext(route.next)
  if (route.screen === 'results' && user.role !== 'admin') return paths.list()
  return null
}
