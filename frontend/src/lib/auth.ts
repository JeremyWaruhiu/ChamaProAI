import { createContext, useContext } from 'react'
import type { Me, Role } from '../api/types'
import { t } from '../strings'
import { parse, paths, type Screen } from './router'

export interface AuthState {
  user: Me | null
  signOut: () => void
}

export const AuthContext = createContext<AuthState>({ user: null, signOut: () => {} })

export function useAuth(): AuthState {
  return useContext(AuthContext)
}

export const ROLE_LABEL: Record<Role, string> = t.roles

// Who may open which screen. The server enforces the same rules; this only
// keeps people from landing on a page that would refuse them.
const PUBLIC = new Set<Screen>(['landing', 'login'])
const EVERY_ROLE = new Set<Screen>(['profile'])
const STAFF = new Set<Screen>(['home', 'start', 'interviews', 'record', 'review', 'assessment',
  'applications', 'application', 'members', 'member'])
const ADMIN = new Set<Screen>(['admin', 'users', 'audit', 'results'])
const MEMBER = new Set<Screen>(['my', 'myApplication'])

/** Where each role starts. */
export function homeFor(role: Role): string {
  if (role === 'admin') return paths.admin()
  if (role === 'member') return paths.my()
  return paths.home()
}

export function canOpen(screen: Screen, role: Role | null): boolean {
  if (PUBLIC.has(screen)) return true
  if (!role) return false
  if (EVERY_ROLE.has(screen)) return true
  if (STAFF.has(screen)) return role === 'officer' || role === 'admin'
  if (ADMIN.has(screen)) return role === 'admin'
  if (MEMBER.has(screen)) return role === 'member'
  return false
}

export const isStaff = (role: Role | null | undefined) => role === 'officer' || role === 'admin'

/** Where to go after signing in: an in-app route this user may open, never back to login. */
export function safeNext(next: string | null | undefined, user: Me): string {
  if (!next || !next.startsWith('#/')) return homeFor(user.role)
  const screen = parse(next).screen
  if (screen === 'login' || screen === 'landing' || !canOpen(screen, user.role)) return homeFor(user.role)
  return next
}

/**
 * The redirect a route needs for this user, or null to show it.
 *   - signed out: public pages show; others go to login, remembering the route
 *   - signed in on the login page: on to where they were going, or their home
 *   - a screen their role cannot open (a member on a staff page, an officer on
 *     an admin page, staff on the member portal): to their home
 *   - an unknown route: home, or the landing page when signed out
 */
export function redirectFor(hash: string, user: Me | null): string | null {
  const route = parse(hash)
  if (route.screen === 'notFound') return user ? homeFor(user.role) : paths.landing()
  if (!user) return PUBLIC.has(route.screen) ? null : paths.login(hash)
  if (route.screen === 'login') return safeNext(route.next, user)
  return canOpen(route.screen, user.role) ? null : homeFor(user.role)
}
