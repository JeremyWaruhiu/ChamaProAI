import type { Role } from '../api/types'
import { t } from '../strings'

// Validation for the smaller forms: a new user, and changing your password.

const USERNAME = /^[A-Za-z0-9._@-]{3,64}$/
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

export interface NewUser { username: string; password: string; role: Role; email: string; member_id: string }

/** What stops a new user being created; {} when the form is complete. */
export function newUserErrors(u: NewUser): Partial<Record<keyof NewUser, string>> {
  const E = t.users.errors
  const e: Partial<Record<keyof NewUser, string>> = {}
  if (!USERNAME.test(u.username.trim())) e.username = E.username
  if (u.password.length < 10) e.password = E.password
  if (u.email.trim() && !EMAIL.test(u.email.trim())) e.email = E.email
  if (u.role === 'member' && !u.member_id) e.member_id = E.member
  return e
}

export interface PasswordForm { current: string; next: string; confirm: string }

/** What stops the password change; {} when it can be sent. */
export function passwordErrors(f: PasswordForm): Partial<Record<keyof PasswordForm, string>> {
  const E = t.profile.errors
  const e: Partial<Record<keyof PasswordForm, string>> = {}
  if (!f.current) e.current = E.current
  if (f.next.length < 10) e.next = E.short
  else if (f.next === f.current) e.next = E.same
  if (f.confirm !== f.next) e.confirm = E.match
  return e
}
