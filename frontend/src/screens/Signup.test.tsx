// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Signup, SignupForm } from './Signup'

const INFO = { enabled: true, consent_version: 'pilot-2026-11',
               consent_text: ['Your interview answers are recorded and stored on Supabase.', 'Please invent a fictional applicant.'] }
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const type = (label: RegExp, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } })

function fill({ invite = 'the-code' } = {}) {
  type(/Full name/, 'Fictional Volunteer')
  type(/Mobile number/, '0712345678')
  type(/^Password/, 'long enough password')
  type(/Repeat the password/, 'long enough password')
  if (invite) type(/Invite code/, invite)
}

describe('the sign-up form', () => {
  it('shows the consent text in full, with the box unticked', () => {
    render(<SignupForm info={INFO} onSignedIn={() => {}} />)
    expect(screen.getByText(/stored on Supabase/)).toBeTruthy()
    expect(screen.getByText(/invent a fictional applicant/)).toBeTruthy()
    expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(false)
  })

  it('sends nothing without consent', () => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    render(<SignupForm info={INFO} onSignedIn={() => {}} />)
    fill()
    fireEvent.click(screen.getByRole('button', { name: /Create my account/ }))
    expect(screen.getByRole('checkbox').getAttribute('aria-invalid')).toBe('true')
    expect(screen.getByText(/tick the box/)).toBeTruthy()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('sends nothing without an invite code', () => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    render(<SignupForm info={INFO} onSignedIn={() => {}} />)
    fill({ invite: '' })
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: /Create my account/ }))
    expect(document.getElementById('su-invite')!.getAttribute('aria-invalid')).toBe('true')
    expect(fetch).not.toHaveBeenCalled()
  })

  it('sends the normalised phone and the consent version, then signs in', async () => {
    const me = { username: 'V-00001', role: 'member', display_name: 'F', member_no: 'V-00001' }
    const fetch = vi.fn(async () => new Response(JSON.stringify(me), { status: 201 }))
    vi.stubGlobal('fetch', fetch)
    const onSignedIn = vi.fn()
    render(<SignupForm info={INFO} onSignedIn={onSignedIn} />)
    fill()
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: /Create my account/ }))
    await waitFor(() => expect(onSignedIn).toHaveBeenCalled())
    const body = JSON.parse((fetch.mock.calls[0] as unknown as [string, RequestInit])[1].body as string)
    expect(body.phone).toBe('+254712345678')
    expect(body.invite_code).toBe('the-code')
    expect(body.consent).toBe(true)
    expect(body.consent_version).toBe('pilot-2026-11')
  })

  it('shows the server’s refusal of a wrong code or a registered number', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'that invite code is not valid' }), { status: 403 })))
    render(<SignupForm info={INFO} onSignedIn={() => {}} />)
    fill()
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: /Create my account/ }))
    expect(await screen.findByText(/invite code is not valid/)).toBeTruthy()
  })

  it('opens the phone keypad', () => {
    render(<SignupForm info={INFO} onSignedIn={() => {}} />)
    expect(screen.getByLabelText(/Mobile number/).getAttribute('type')).toBe('tel')
  })
})

describe('when the pilot is closed', () => {
  it('says so and offers no form', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ ...INFO, enabled: false }), { status: 200 })))
    render(<Signup onSignedIn={() => {}} />)
    expect(await screen.findByText(/Sign-up is not open/)).toBeTruthy()
    expect(screen.queryByLabelText(/Invite code/)).toBeNull()
  })
})

describe('after signing up', () => {
  const answer = (over: object) => vi.fn(async () => new Response(JSON.stringify({
    username: 'V-1', role: 'member', member_no: 'V-1', claimed: false, profile_due: false, ...over }), { status: 201 }))

  function sign(extra?: () => void) {
    const onSignedIn = vi.fn()
    render(<SignupForm info={INFO} onSignedIn={onSignedIn} />)
    fill()
    extra?.()
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: /Create my account/ }))
    return onSignedIn
  }

  it('someone new goes to the registration form', async () => {
    vi.stubGlobal('fetch', answer({ profile_due: true }))
    window.location.hash = '#/signup'
    const onSignedIn = sign()
    await waitFor(() => expect(onSignedIn).toHaveBeenCalled())
    expect(window.location.hash).toBe('#/my/registration')
  })

  it('someone claiming their record sends the number and skips the form', async () => {
    const fetch = answer({ claimed: true })
    vi.stubGlobal('fetch', fetch)
    window.location.hash = '#/signup'
    const onSignedIn = sign(() => type(/Member number/, 'M-2001'))
    await waitFor(() => expect(onSignedIn).toHaveBeenCalled())
    expect(JSON.parse((fetch.mock.calls[0] as unknown as [string, RequestInit])[1].body as string).member_no).toBe('M-2001')
    expect(window.location.hash).toBe('#/signup')
  })
})
