import type { SignupBody } from '../api/types'
import { t } from '../strings'
import { normalisePhone } from './phone'

// The volunteer sign-up form, before anything is sent.

const S = t.signup

export interface SignupDraft {
  full_name: string; phone: string; email: string; password: string; confirm: string; invite: string; consent: boolean
}

export const EMPTY_SIGNUP: SignupDraft = { full_name: '', phone: '', email: '', password: '', confirm: '', invite: '', consent: false }

/** What stops the form being sent; {} when it can go. The API checks all of it again. */
export function signupErrors(d: SignupDraft): Partial<Record<keyof SignupDraft, string>> {
  const E = S.errors
  const e: Partial<Record<keyof SignupDraft, string>> = {}
  if (!d.full_name.trim()) e.full_name = E.fullName
  if (!normalisePhone(d.phone)) e.phone = E.phone
  if (d.email.trim() && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(d.email.trim())) e.email = E.email
  if (d.password.length < 10) e.password = E.password
  if (d.confirm !== d.password) e.confirm = E.confirm
  if (!d.invite.trim()) e.invite = E.invite
  if (!d.consent) e.consent = E.consent
  return e
}

export function toSignupBody(d: SignupDraft, version: string): SignupBody {
  return {
    full_name: d.full_name.trim(), phone: normalisePhone(d.phone) ?? d.phone, email: d.email.trim() || null,
    password: d.password, password_confirm: d.confirm, invite_code: d.invite.trim(), consent: d.consent,
    consent_version: version,
  }
}
