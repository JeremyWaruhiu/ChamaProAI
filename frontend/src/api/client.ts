import type {
  Assessment, Decision, DecisionValue, InterviewState, InterviewSummary,
  Question, ResponseOut, ResponseQueued,
} from './types'

/** Every failure, network or HTTP, arrives as one of these with a readable message. */
export class ApiError extends Error {
  readonly status: number
  readonly retryAfter: number | null

  constructor(status: number, message: string, retryAfter: number | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.retryAfter = retryAfter
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
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
    throw new ApiError(res.status, detail, Number.isFinite(ra) && ra > 0 ? ra : null)
  }
  return res.json() as Promise<T>
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

export const api = {
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
    request<Assessment>(`/interviews/${interviewId}/assess`, { method: 'POST' }),
  decide: (interviewId: number, decision: DecisionValue, note: string) =>
    request<Decision>(`/interviews/${interviewId}/decision`,
      json('POST', { decision, note: note.trim() || null })),
  audioUrl: (responseId: number) => `/api/responses/${responseId}/audio`,
}
