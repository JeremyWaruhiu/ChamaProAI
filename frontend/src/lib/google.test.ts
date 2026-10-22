import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api, setUnauthorizedHandler } from '../api/client'
import type { Me } from '../api/types'
import { redirectFor } from './auth'
import {
  GIS_SRC, buttonWidth, googleStatusFor, loadGis, mountGoogleButton,
  type GisButtonOptions, type GisCredentialResponse, type GisId,
} from './google'
import { paths } from './router'

/** Stands in for the GIS script's google.accounts.id. */
function fakeGis() {
  let callback: ((r: GisCredentialResponse) => void) | null = null
  const gis = {
    initialize: vi.fn((cfg: Parameters<GisId['initialize']>[0]) => { callback = cfg.callback }),
    renderButton: vi.fn((_el: HTMLElement, _opts: GisButtonOptions) => {}),
    /** What Google does when the user picks an account in the popup. */
    async choose(credential: string) {
      callback!({ credential })
      await new Promise((r) => setTimeout(r, 0))
    },
  }
  return gis
}

const el = () => ({ clientWidth: 380, replaceChildren: vi.fn() }) as unknown as HTMLElement
const me: Me = { username: 'admin', role: 'admin' }

afterEach(() => {
  setUnauthorizedHandler(null)
  vi.unstubAllGlobals()
})

describe('whether to offer Google sign-in', () => {
  it('is a disabled placeholder when the server has no client ID', () => {
    expect(googleStatusFor({ google_client_id: null })).toBe('disabled')
  })

  it('shows nothing while the config is unknown or could not be fetched', () => {
    expect(googleStatusFor(null)).toBe('off')
  })

  it('is on when a client ID is configured', () => {
    expect(googleStatusFor({ google_client_id: 'abc.apps.googleusercontent.com' })).toBe('loading')
  })
})

describe('mountGoogleButton', () => {
  it("renders Google's own button with the branded options", async () => {
    const gis = fakeGis()
    const container = el()
    await mountGoogleButton({ clientId: 'cid', el: container, load: async () => gis,
                              signIn: vi.fn(), onSignedIn: vi.fn(), onError: vi.fn() })
    expect(gis.initialize).toHaveBeenCalledWith(expect.objectContaining({
      client_id: 'cid', ux_mode: 'popup', auto_select: false }))
    expect(gis.renderButton).toHaveBeenCalledTimes(1)
    const [target, opts] = gis.renderButton.mock.calls[0]
    expect(target).toBe(container)
    expect(opts).toEqual({ type: 'standard', theme: 'outline', size: 'large', text: 'signin_with',
                           shape: 'rectangular', logo_alignment: 'left', width: 380 })
    expect(container.replaceChildren).toHaveBeenCalled()
  })

  it('posts the credential and follows the password sign-in success path', async () => {
    const gis = fakeGis()
    const fetch = vi.fn(async () => new Response(JSON.stringify(me), { status: 200 }))
    vi.stubGlobal('fetch', fetch)
    const onSignedIn = vi.fn()
    await mountGoogleButton({ clientId: 'cid', el: el(), load: async () => gis,
                              signIn: api.googleLogin, onSignedIn, onError: vi.fn() })
    await gis.choose('the-id-token')

    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/auth/google')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({ credential: 'the-id-token' })
    expect(onSignedIn).toHaveBeenCalledWith(me)

    // App handles onSignedIn the same way for both methods: back to where the user was going.
    expect(redirectFor(paths.login('#/interviews/7/review'), me)).toBe('#/interviews/7/review')
    expect(redirectFor(paths.login('#/admin/results'), me)).toBe('#/admin/results')
  })

  it('reports a refused Google sign-in without treating it as a lost session', async () => {
    const gis = fakeGis()
    vi.stubGlobal('fetch', vi.fn(async () =>
      new Response(JSON.stringify({ detail: 'incorrect username or password' }), { status: 401 })))
    const onUnauthorized = vi.fn()
    setUnauthorizedHandler(onUnauthorized)
    const onError = vi.fn()
    const onSignedIn = vi.fn()
    const onBusy = vi.fn()
    await mountGoogleButton({ clientId: 'cid', el: el(), load: async () => gis,
                              signIn: api.googleLogin, onSignedIn, onError, onBusy })
    await gis.choose('a-token')

    expect(onSignedIn).not.toHaveBeenCalled()
    expect(onError).toHaveBeenCalledTimes(1)
    const e = onError.mock.calls[0][0] as ApiError
    expect(e).toBeInstanceOf(ApiError)
    expect(e.status).toBe(401)
    expect(e.message).toBe('incorrect username or password')
    expect(onUnauthorized).not.toHaveBeenCalled()
    expect(onBusy.mock.calls).toEqual([[true], [false]])
  })

  it('fails when the script cannot load, so the page can fall back', async () => {
    await expect(mountGoogleButton({
      clientId: 'cid', el: el(), load: async () => { throw new Error('offline') },
      signIn: vi.fn(), onSignedIn: vi.fn(), onError: vi.fn(),
    })).rejects.toThrow('offline')
  })

  it('keeps the button within the 200-400 px Google allows', () => {
    const w = (n: number) => buttonWidth({ clientWidth: n } as HTMLElement)
    expect(w(150)).toBe(200)
    expect(w(320)).toBe(320)
    expect(w(900)).toBe(400)
    expect(w(0)).toBe(400)
  })
})

describe('loadGis (the GIS script tag)', () => {
  /** A window whose document records the script tag and lets the test fire its events. */
  function fakeWindow() {
    const listeners: Record<string, () => void> = {}
    const script = {
      src: '', async: false, remove: vi.fn(),
      addEventListener: (type: string, fn: () => void) => { listeners[type] = fn },
    }
    const head = { appendChild: vi.fn() }
    const win = {
      google: undefined as Window['google'],
      document: { querySelector: vi.fn(() => null), createElement: vi.fn(() => script), head },
    }
    return { win: win as unknown as Window, raw: win, script, head, fire: (t: string) => listeners[t]() }
  }

  it('adds the official script once and resolves with google.accounts.id', async () => {
    const f = fakeWindow()
    const loading = loadGis(f.win)
    void loadGis(f.win)                              // a second caller shares the same load
    expect(f.head.appendChild).toHaveBeenCalledTimes(1)
    expect(f.script.src).toBe(GIS_SRC)
    expect(f.script.src).toBe('https://accounts.google.com/gsi/client')
    const id = fakeGis() as unknown as GisId
    f.raw.google = { accounts: { id } }
    f.fire('load')
    await expect(loading).resolves.toBe(id)
  })

  it('does not load again when GIS is already present', async () => {
    const f = fakeWindow()
    const id = fakeGis() as unknown as GisId
    f.raw.google = { accounts: { id } }
    await expect(loadGis(f.win)).resolves.toBe(id)
    expect(f.head.appendChild).not.toHaveBeenCalled()
  })

  it('rejects and removes the tag when the script fails, so a retry starts afresh', async () => {
    const f = fakeWindow()
    const loading = loadGis(f.win)
    f.fire('error')
    await expect(loading).rejects.toThrow('could not be loaded')
    expect(f.script.remove).toHaveBeenCalled()
    const retry = loadGis(f.win)                     // same window, new attempt
    expect(f.head.appendChild).toHaveBeenCalledTimes(2)
    f.fire('error')
    await expect(retry).rejects.toThrow()
  })
})
