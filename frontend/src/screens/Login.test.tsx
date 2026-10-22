import { isValidElement, type ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { GOOGLE_NOT_ENABLED } from '../lib/google'
import { GooglePlaceholder, LoginForm } from './Login'

const noop = () => {}
const render = (over: Partial<Parameters<typeof LoginForm>[0]> = {}) => renderToStaticMarkup(
  <LoginForm username="" password="" shown={false} busy={false} error={null}
             onUsername={noop} onPassword={noop} onToggle={noop} onSubmit={noop} {...over} />)

describe('LoginForm', () => {
  it('renders the API error inline in an alert, tied to both fields', () => {
    const html = render({ username: 'wanjiru', error: 'Incorrect username or password.' })
    expect(html).toMatch(/<p id="login-error"[^>]*role="alert"[^>]*>Incorrect username or password\.<\/p>/)
    expect(html.match(/aria-describedby="login-error"/g)).toHaveLength(2)
    expect(html.match(/aria-invalid="true"/g)).toHaveLength(2)
  })

  it('renders a rate-limit message the same way', () => {
    const html = render({ error: 'Too many failed sign-in attempts; try again later.' })
    expect(html).toContain('Too many failed sign-in attempts; try again later.')
  })

  it('has no error text or invalid marking before a failed attempt', () => {
    const html = render()
    expect(html).toMatch(/<p id="login-error"[^>]*role="alert"[^>]*><\/p>/)
    expect(html).not.toContain('aria-invalid')
    expect(html).not.toContain('aria-describedby')
  })

  it('labels both fields visibly and sets autocomplete for password managers', () => {
    const html = render()
    expect(html).toMatch(/<label[^>]*for="login-username"[^>]*>Username</)
    expect(html).toMatch(/<label[^>]*for="login-password"[^>]*>Password</)
    expect(html).toMatch(/id="login-username"[^>]*autoComplete="username"|autoComplete="username"[^>]*id="login-username"/i)
    expect(html).toMatch(/autoComplete="current-password"/i)
  })

  it('hides the password until the toggle is pressed', () => {
    expect(render()).toMatch(/type="password"/)
    expect(render()).toMatch(/aria-pressed="false"[^>]*>Show</)
    const shown = render({ shown: true })
    expect(shown).toMatch(/id="login-password"[^>]*type="text"|type="text"[^>]*id="login-password"/)
    expect(shown).toMatch(/aria-pressed="true"[^>]*>Hide</)
  })

  it('shows a loading state while signing in', () => {
    const html = render({ busy: true, username: 'a', password: 'b' })
    expect(html).toContain('Signing in…')
    expect(html).toContain('aria-busy="true"')
    expect(html).toContain('class="spinner"')
  })
})

describe('Sign in with Google', () => {
  it('shows our own clickable placeholder, not the real button, when not configured', () => {
    const html = render({ google: 'disabled' })
    expect(html).toContain('<span>or</span>')
    expect(html).toMatch(/<button type="button" class="btn btn-secondary btn-block"[^>]*>.*Sign in with Google<\/button>/)
    expect(html).not.toContain('aria-disabled="true"')
    expect(html).not.toMatch(/<button[^>]*\sdisabled/)
    expect(html).not.toContain('not yet enabled')        // no standing caption
    expect(html).not.toContain(GOOGLE_NOT_ENABLED)       // nothing said until it is pressed
    // no slot for Google to render into, so nothing ever mounts the GIS script
    expect(html).not.toContain('google-signin')
    expect(html).not.toContain('accounts.google.com')
    expect(html).not.toMatch(/<img|<svg/)                // a plain "G", no Google artwork
    expect(html).toMatch(/aria-hidden="true"[^>]*>G<\/span>/)
  })

  it('explains, once pressed, that Google sign-in is not set up', () => {
    const html = render({ google: 'disabled', googleError: GOOGLE_NOT_ENABLED })
    expect(html).toMatch(new RegExp(`<p id="google-error"[^>]*role="alert"[^>]*>${GOOGLE_NOT_ENABLED}</p>`))
    expect(html).toMatch(/aria-describedby="google-error"/)
    expect(html).not.toContain('aria-invalid')           // the password fields are not at fault
  })

  it('keeps the placeholder outside the password form', () => {
    const html = render({ google: 'disabled' })
    expect(html.indexOf('</form>')).toBeLessThan(html.indexOf('Sign in with Google'))
  })

  it('shows nothing at all while the config is unknown', () => {
    for (const html of [render(), render({ google: 'off' })]) {
      expect(html).not.toContain('google-signin')
      expect(html).not.toContain('>or<')
      expect(html).not.toContain('Sign in with Google')
    }
  })

  it('shows the divider and the slot GIS renders into when configured', () => {
    for (const google of ['loading', 'ready'] as const) {
      const html = render({ google })
      expect(html).toContain('<span>or</span>')
      expect(html).toMatch(/<div id="google-signin"/)
      expect(html).toContain('aria-label="Sign in with Google"')
    }
  })

  it('puts the Google button outside the password form', () => {
    const html = render({ google: 'ready' })
    expect(html.indexOf('</form>')).toBeLessThan(html.indexOf('id="google-signin"'))
  })

  it('shows a failed Google sign-in inline, without marking the password fields', () => {
    const html = render({ google: 'ready', googleError: 'Incorrect username or password.' })
    expect(html).toMatch(/<p id="google-error"[^>]*role="alert"[^>]*>Incorrect username or password\.<\/p>/)
    expect(html).not.toContain('aria-invalid')
  })

  it('says so while Google sign-in is completing', () => {
    expect(render({ google: 'ready', googleBusy: true })).toContain('Signing in with Google…')
  })

  it('falls back to a plain note when the Google script cannot load', () => {
    const html = render({ google: 'unavailable' })
    expect(html).toContain('Google sign-in could not load')
    expect(html).toMatch(/id="google-signin"[^>]*hidden/)
  })
})

describe('Google placeholder button', () => {
  type ButtonProps = { type: string; disabled?: boolean; 'aria-disabled'?: string; onClick?: () => void }

  function button(onClick?: () => void): ReactElement<ButtonProps> {
    const el = GooglePlaceholder({ onClick })
    expect(isValidElement(el) && el.type).toBe('button')
    return el as ReactElement<ButtonProps>
  }

  afterEach(() => vi.unstubAllGlobals())

  it('is an enabled, ordinary button that cannot submit the password form', () => {
    const { props } = button()
    expect(props.type).toBe('button')
    expect(props.disabled).toBeUndefined()
    expect(props['aria-disabled']).toBeUndefined()
  })

  it('reports each click, and the click itself sends nothing and loads no Google script', () => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    const onClick = vi.fn()
    const before = typeof window === 'undefined' ? undefined : window.google

    button(onClick).props.onClick!()
    button(onClick).props.onClick!()

    expect(onClick).toHaveBeenCalledTimes(2)
    expect(fetch).not.toHaveBeenCalled()
    expect(typeof window === 'undefined' ? undefined : window.google).toBe(before)
  })
})
