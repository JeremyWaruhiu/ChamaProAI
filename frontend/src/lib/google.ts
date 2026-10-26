import { ApiError } from '../api/client'
import type { AuthConfig, Me } from '../api/types'
import { t } from '../strings'

// "Sign in with Google" through Google Identity Services (GIS). The button is
// the one GIS renders, as Google's branding guidelines require; this module
// only loads the script, wires the callback to our API and reports back.
// The script is fetched only when the server has a client ID configured.

export const GIS_SRC = 'https://accounts.google.com/gsi/client'
const LOAD_TIMEOUT_MS = 10_000

export interface GisCredentialResponse {
  credential: string
}

/** The part of google.accounts.id this app uses. */
export interface GisId {
  initialize(config: {
    client_id: string
    callback: (response: GisCredentialResponse) => void
    ux_mode?: 'popup' | 'redirect'
    auto_select?: boolean
    cancel_on_tap_outside?: boolean
    context?: 'signin' | 'signup' | 'use'
  }): void
  renderButton(parent: HTMLElement, options: GisButtonOptions): void
}

export interface GisButtonOptions {
  type: 'standard' | 'icon'
  theme: 'outline' | 'filled_blue' | 'filled_black'
  size: 'large' | 'medium' | 'small'
  text: 'signin_with' | 'signup_with' | 'continue_with' | 'signin'
  shape: 'rectangular' | 'pill' | 'circle' | 'square'
  logo_alignment: 'left' | 'center'
  width: number
}

declare global {
  interface Window {
    google?: { accounts?: { id?: GisId } }
  }
}

/**
 * 'off': config not known (not fetched yet, or the request failed): show nothing.
 * 'disabled': the server has no client ID: our own placeholder button, no script.
 * 'unavailable': configured, but the GIS script failed to load.
 */
export type GoogleStatus = 'off' | 'disabled' | 'loading' | 'ready' | 'unavailable'

/** Shown when the placeholder button is pressed. */
export const GOOGLE_NOT_ENABLED = t.login.googleNotEnabled

export function googleStatusFor(config: AuthConfig | null): GoogleStatus {
  if (!config) return 'off'
  return config.google_client_id ? 'loading' : 'disabled'
}

// One load per window, shared by every caller until it settles.
const loading = new WeakMap<Window, Promise<GisId>>()

/** Load the GIS script once and resolve with google.accounts.id. */
export function loadGis(win: Window = window, timeoutMs = LOAD_TIMEOUT_MS): Promise<GisId> {
  const ready = () => win.google?.accounts?.id
  const loaded = ready()
  if (loaded) return Promise.resolve(loaded)
  const inFlight = loading.get(win)
  if (inFlight) return inFlight

  const pending = new Promise<GisId>((resolve, reject) => {
    const doc = win.document
    let script = doc.querySelector<HTMLScriptElement>(`script[src="${GIS_SRC}"]`)
    if (!script) {
      script = doc.createElement('script')
      script.src = GIS_SRC
      script.async = true
      doc.head.appendChild(script)
    }
    const fail = (why: string) => {
      clearTimeout(timer)
      script?.remove()       // so a later attempt starts afresh
      loading.delete(win)
      reject(new Error(why))
    }
    const timer = setTimeout(() => fail('Google sign-in did not load in time'), timeoutMs)
    script.addEventListener('load', () => {
      const id = ready()
      if (!id) return fail('Google sign-in loaded without its API')
      clearTimeout(timer)
      loading.delete(win)    // from now on window.google answers directly
      resolve(id)
    }, { once: true })
    script.addEventListener('error', () => fail('Google sign-in could not be loaded'), { once: true })
  })
  loading.set(win, pending)
  return pending
}

/** GIS buttons are 200-400 px wide; fill the form's width within that. */
export function buttonWidth(el: HTMLElement): number {
  return Math.round(Math.max(200, Math.min(400, el.clientWidth || 400)))
}

export interface GoogleButtonOptions {
  clientId: string
  el: HTMLElement
  /** Exchange the Google credential for a session: api.googleLogin. */
  signIn: (credential: string) => Promise<Me>
  /** The same success path as password sign-in. */
  onSignedIn: (me: Me) => void
  onError: (error: ApiError) => void
  onBusy?: (busy: boolean) => void
  load?: () => Promise<GisId>
}

/** Render Google's own button into el and send its credential to our API. */
export async function mountGoogleButton(o: GoogleButtonOptions): Promise<void> {
  const gis = await (o.load ?? loadGis)()
  gis.initialize({
    client_id: o.clientId,
    ux_mode: 'popup',
    auto_select: false,
    cancel_on_tap_outside: true,
    context: 'signin',
    callback: async ({ credential }) => {
      o.onBusy?.(true)
      try {
        o.onSignedIn(await o.signIn(credential))
      } catch (e) {
        o.onError(e instanceof ApiError ? e : new ApiError(0, t.login.googleFailed))
        o.onBusy?.(false)
      }
    },
  })
  o.el.replaceChildren() // StrictMode mounts twice; never show two buttons
  gis.renderButton(o.el, {
    type: 'standard', theme: 'outline', size: 'large', text: 'signin_with',
    shape: 'rectangular', logo_alignment: 'left', width: buttonWidth(o.el),
  })
}
