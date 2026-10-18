import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ASSESS_TIMEOUT_MS, ApiError, REQUEST_TIMEOUT_MS, api } from './client'

/** A fetch that never answers until its signal aborts, like a server stuck restarting. */
function hangingFetch() {
  return vi.fn((_url: string, init?: RequestInit) => new Promise<Response>((_, reject) => {
    init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
  }))
}

describe('request timeout', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('gives up after 15 seconds with a timed-out ApiError', async () => {
    expect(REQUEST_TIMEOUT_MS).toBe(15_000)
    vi.stubGlobal('fetch', hangingFetch())
    const result = api.interviews().catch((e: unknown) => e)
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS)
    const e = await result
    expect(e).toBeInstanceOf(ApiError)
    expect((e as ApiError).timedOut).toBe(true)
    expect((e as ApiError).message).toMatch(/did not answer within 15 seconds/)
  })

  it('allows the assessment longer, but still a bounded time', async () => {
    vi.stubGlobal('fetch', hangingFetch())
    let settled = false
    const result = api.assess(1).catch((e: unknown) => e).finally(() => { settled = true })
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS)
    expect(settled).toBe(false)
    await vi.advanceTimersByTimeAsync(ASSESS_TIMEOUT_MS - REQUEST_TIMEOUT_MS)
    expect(((await result) as ApiError).timedOut).toBe(true)
  })

  it('does not time out a request that answered', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('[]', { status: 200 })))
    await expect(api.interviews()).resolves.toEqual([])
  })

  it('reports an unreachable server as not timed out', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    const e = await api.interviews().catch((err: unknown) => err) as ApiError
    expect(e.timedOut).toBe(false)
    expect(e.message).toMatch(/Cannot reach the ChamaPro server/)
  })
})
