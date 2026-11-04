import { describe, expect, it } from 'vitest'
import { EMPTY_SIGNUP, signupErrors, toSignupBody } from './signup'

const OK = { full_name: 'Fictional Volunteer', phone: '0712 345 678', member_no: '', email: '', password: 'long enough password',
             confirm: 'long enough password', invite: 'code', consent: true }

describe('signupErrors', () => {
  it('has nothing to say about a complete form', () => { expect(signupErrors(OK)).toEqual({}) })

  it('needs every required field, the invite code and consent among them', () => {
    expect(Object.keys(signupErrors(EMPTY_SIGNUP)).sort()).toEqual(['consent', 'full_name', 'invite', 'password', 'phone'])
  })

  it.each([
    ['invite', { invite: '   ' }], ['consent', { consent: false }], ['phone', { phone: '12345' }],
    ['password', { password: 'short', confirm: 'short' }], ['confirm', { confirm: 'something else' }],
    ['email', { email: 'not an email' }],
  ])('catches a bad %s', (field, over) => {
    expect(Object.keys(signupErrors({ ...OK, ...over }))).toContain(field)
  })
})

describe('toSignupBody', () => {
  it('sends the one phone form and the consent version read', () => {
    const body = toSignupBody(OK, 'pilot-2026-11')
    expect(body.phone).toBe('+254712345678')
    expect(body.consent).toBe(true)
    expect(body.consent_version).toBe('pilot-2026-11')
    expect(body.email).toBeNull()
  })
})

describe('claiming an existing member', () => {
  it('sends a member number only when one was typed', () => {
    expect(toSignupBody(OK, 'v1')).not.toHaveProperty('member_no')
    expect(toSignupBody({ ...OK, member_no: '  M-2001 ' }, 'v1').member_no).toBe('M-2001')
  })
})
