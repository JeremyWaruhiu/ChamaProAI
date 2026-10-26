import type {
  ApplicantFormOptions, ApplicationCreate, ApplicationDetail, ApplicationStatus, ApplicationSummary,
  Assessment, AuditEntry, AuditFilter, AuthConfig, Decision, DecisionCreate, Guarantor, GuarantorIn,
  Health, InterviewCreate, InterviewState, InterviewSummary, Me, Member, MemberCreate, MyApplication,
  MyApplicationSummary, Profile, Question, QuestionSet, ResponseOut, ResponseQueued, Results, Role,
  UserCreate, UserOut,
} from './types'
import { t } from '../strings'

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
      throw new ApiError(0, t.api.timedOut(timeoutMs / 1000), null, true)
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
    throw new ApiError(0, t.api.unreachable)
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      // not JSON (e.g. the proxy could not reach the backend); keep the status line
      if (res.status === 502 || res.status === 504) {
        detail = t.api.notResponding
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

/** ?a=1&b=x from the defined, non-empty values only. */
export function query(params: Record<string, string | number | null | undefined>): string {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') q.set(k, String(v))
  }
  const out = q.toString()
  return out ? `?${out}` : ''
}

export const api = {
  health: () => request<Health>('/health'),
  me: () => request<Me>('/auth/me'),
  login: (username: string, password: string) =>
    request<Me>('/auth/login', json('POST', { username: username.trim(), password })),
  logout: () => request<null>('/auth/logout', { method: 'POST' }),
  logoutAll: () => request<null>('/auth/logout-all', { method: 'POST' }),
  profile: () => request<Profile>('/auth/profile'),
  changePassword: (current: string, next: string) =>
    request<null>('/auth/password', json('POST', { current_password: current, new_password: next })),
  authConfig: () => request<AuthConfig>('/auth/config'),
  googleLogin: (credential: string) => request<Me>('/auth/google', json('POST', { credential })),
  questions: (version: QuestionSet) => request<Question[]>(`/questions?version=${version}`),
  applicantForm: () => request<ApplicantFormOptions>('/applicant-form'),
  interviews: () => request<InterviewSummary[]>('/interviews'),
  interview: (id: number) => request<InterviewState>(`/interviews/${id}`),
  createInterview: (body: InterviewCreate) =>
    request<{ id: number; status: string }>('/interviews',
      json('POST', { ...body, applicant_name: body.applicant_name?.trim() || null })),

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

  /** An answer typed instead of recorded: no audio, no transcription wait. */
  typeResponse: (interviewId: number, sentenceNo: number, text: string) =>
    request<ResponseOut>(`/interviews/${interviewId}/responses/typed`,
      json('POST', { sentence_no: sentenceNo, text: text.trim() })),

  saveTranscript: (responseId: number, transcript: string) =>
    request<ResponseOut>(`/responses/${responseId}`, json('PATCH', { transcript })),
  assess: (interviewId: number) =>
    request<Assessment>(`/interviews/${interviewId}/assess`, { method: 'POST' }, ASSESS_TIMEOUT_MS),
  /** The officer's decision on an interview; moves its loan application too, if it has one. */
  decide: (interviewId: number, body: DecisionCreate) =>
    request<Decision>(`/interviews/${interviewId}/decision`, json('POST', body)),
  audioUrl: (responseId: number) => `/api/responses/${responseId}/audio`,
  results: () => request<Results>('/results'),

  // members and loan applications (staff)
  members: (q?: string, limit = 50) => request<Member[]>(`/members${query({ q: q?.trim(), limit })}`),
  member: (id: number) => request<Member>(`/members/${id}`),
  createMember: (body: MemberCreate) => request<Member>('/members', json('POST', body)),
  applications: (filter: { status?: ApplicationStatus; member_id?: number; limit?: number } = {}) =>
    request<ApplicationSummary[]>(`/applications${query(filter)}`),
  application: (id: number) => request<ApplicationDetail>(`/applications/${id}`),
  createApplication: (body: ApplicationCreate) =>
    request<ApplicationDetail>('/applications', json('POST', body)),
  verifyGuarantor: (id: number) => request<Guarantor>(`/guarantors/${id}/verify`, { method: 'POST' }),
  rejectGuarantor: (id: number, reason: string) =>
    request<Guarantor>(`/guarantors/${id}/reject`, json('POST', { reason: reason.trim() || null })),

  // a member's own applications
  myApplications: () => request<MyApplicationSummary[]>('/me/applications'),
  myApplication: (id: number) => request<MyApplication>(`/me/applications/${id}`),
  submitGuarantors: (id: number, guarantors: GuarantorIn[]) =>
    request<MyApplication>(`/me/applications/${id}/guarantors`, json('POST', { guarantors })),

  // administration
  users: () => request<UserOut[]>('/admin/users'),
  createUser: (body: UserCreate) => request<UserOut>('/admin/users', json('POST', body)),
  setUserActive: (id: number, active: boolean) =>
    request<UserOut>(`/admin/users/${id}/${active ? 'activate' : 'deactivate'}`, { method: 'POST' }),
  resetPassword: (id: number, password: string) =>
    request<UserOut>(`/admin/users/${id}/password`, json('PUT', { password })),
  changeRole: (id: number, role: Role) => request<UserOut>(`/admin/users/${id}/role`, json('PUT', { role })),
  linkGoogle: (id: number, email: string | null) =>
    request<UserOut>(`/admin/users/${id}/google-email`, json('PUT', { email: email?.trim() || null })),
  linkMember: (id: number, memberId: number | null) =>
    request<UserOut>(`/admin/users/${id}/member`, json('PUT', { member_id: memberId })),
  audit: (filter: AuditFilter = {}) => request<AuditEntry[]>(`/admin/audit${query({ ...filter })}`),
}
