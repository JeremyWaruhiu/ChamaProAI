import type {
  Assessment, Decision, DecisionValue, InterviewState, InterviewSummary,
  AuthConfig, Me, Question, ResponseOut, ResponseQueued, Results,
} from './types'

/** No request may leave the dashboard waiting longer than this. */
export const REQUEST_TIMEOUT_MS = 15_000
/** Assessment translates, extracts and scores in one call: about 30 s, so it gets longer. */
export const ASSESS_TIMEOUT_MS = 90_000

/** Every failure, network or HTTP, arrives as one of these with a readable message. */
export class ApiError extends Error {
  readonly status: number
  readonly retryAfter: number | null
  readonly timedOut: boolean

  constructor(status: number, message: string, retryAfter: number | null = null, timedOut = false) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.retryAfter = retryAfter
    this.timedOut = timedOut
  }
}

let onUnauthorized: (() => void) | null = null

/** Paths whose 401 is a refused sign-in, shown on the login form, not a lost session. */
const SIGN_IN_PATHS = new Set(['/auth/login', '/auth/google'])

/** Called on any 401 except a failed sign-in: the session is gone, so go back to login. */
export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler
}

/** Abandon the request after timeoutMs, so no screen can spin forever. */
async function request<T>(path: string, init?: RequestInit, timeoutMs = REQUEST_TIMEOUT_MS): Promise<T> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    return await send<T>(path, { ...init, signal: ctrl.signal })
  } catch (e) {
    if (ctrl.signal.aborted) {
      throw new ApiError(0, `The ChamaPro server did not answer within ${timeoutMs / 1000} seconds. `
        + 'Check that it is running, then retry.', null, true)
    }
    throw e
  } finally {
    clearTimeout(timer)
  }
}

async function send<T>(path: string, init: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`/api${path}`, init)
  } catch {
    throw new ApiError(0, 'Cannot reach the ChamaPro server. Check that it is running, then try again.')
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      // not JSON (e.g. the proxy could not reach the backend); keep the status line
      if (res.status === 502 || res.status === 504) {
        detail = 'The ChamaPro server is not responding. Check that it is running.'
      }
    }
    const ra = Number(res.headers.get('Retry-After'))
    // A failed sign-in is a 401 too, but that one belongs to the login form.
    if (res.status === 401 && !SIGN_IN_PATHS.has(path)) onUnauthorized?.()
    throw new ApiError(res.status, detail, Number.isFinite(ra) && ra > 0 ? ra : null)
  }
  if (res.status === 204) return null as T
  return await (res.json() as Promise<T>)  // awaited, so the timeout covers the body too
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

export const api = {
  me: () => request<Me>('/auth/me'),
  login: (username: string, password: string) =>
    request<Me>('/auth/login', json('POST', { username: username.trim(), password })),
  logout: () => request<null>('/auth/logout', { method: 'POST' }),
  authConfig: () => request<AuthConfig>('/auth/config'),
  googleLogin: (credential: string) => request<Me>('/auth/google', json('POST', { credential })),
  questions: () => request<Question[]>('/questions'),
  interviews: () => request<InterviewSummary[]>('/interviews'),
  interview: (id: number) => request<InterviewState>(`/interviews/${id}`),
  createInterview: (applicantName: string) =>
    request<{ id: number; status: string }>('/interviews',
      json('POST', { applicant_name: applicantName.trim() || null })),

  uploadResponse(interviewId: number, sentenceNo: number, audio: Blob, filename: string) {
    const form = new FormData()
    form.append('sentence_no', String(sentenceNo))
    form.append('file', audio, filename)
    return request<ResponseQueued>(`/interviews/${interviewId}/responses`, { method: 'POST', body: form })
  },

  /**
   * Delete a response so it can be recorded again. While the server is
   * transcribing it, the API answers 409 with Retry-After; wait that long
   * and try again, telling the caller each time it has to wait.
   */
  async deleteResponse(responseId: number, onWait?: (seconds: number) => void, maxTries = 12) {
    for (let attempt = 1; ; attempt++) {
      try {
        return await request<{ id: number }>(`/responses/${responseId}`, { method: 'DELETE' })
      } catch (e) {
        if (!(e instanceof ApiError) || e.status !== 409 || e.retryAfter === null || attempt >= maxTries) throw e
        onWait?.(e.retryAfter)
        await sleep(e.retryAfter * 1000)
      }
    }
  },

  saveTranscript: (responseId: number, transcript: string) =>
    request<ResponseOut>(`/responses/${responseId}`, json('PATCH', { transcript })),
  assess: (interviewId: number) =>
    request<Assessment>(`/interviews/${interviewId}/assess`, { method: 'POST' }, ASSESS_TIMEOUT_MS),
  decide: (interviewId: number, decision: DecisionValue, note: string) =>
    request<Decision>(`/interviews/${interviewId}/decision`,
      json('POST', { decision, note: note.trim() || null })),
  audioUrl: (responseId: number) => `/api/responses/${responseId}/audio`,
  results: () => request<Results>('/results'),
}
