// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { MyPractice } from '../api/types'
import { t } from '../strings'
import { PracticeResult, PracticeRunner, QuestionView, ResultView, SubmitPanel, SusForm } from './Practice'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const QUESTIONS = Array.from({ length: 8 }, (_, i) => ({ order: i + 1, topic: 'household', text_en: `Question number ${i + 1}?`, text_kik: '' }))
const PRACTICE: MyPractice = {
  id: 7, application_id: 3, language: 'kik', mode: 'practice', status: 'open', created_at: '2026-11-04T08:00:00Z',
  questions: QUESTIONS, sus_answered: false, result: null,
  responses: QUESTIONS.map((q) => ({ id: q.order, sentence_no: q.order, source: 'typed' as const, status: 'transcribed' as const,
                                     transcript: 'an answer', edited: false, duration_s: null })),
  limits: { remaining_today: 5, allowed_per_day: 5, pilot_full_today: false },
}
const stubApi = (body: unknown, status = 200) =>
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(body), { status })))

describe('every practice screen says it is practice', () => {
  it('on the question screen, with one question per screen', async () => {
    stubApi(PRACTICE)
    render(<PracticeRunner id={7} question={2} />)
    expect((await screen.findAllByText('Practice')).length).toBeGreaterThan(0)
    expect(screen.getByText(/This is a practice interview/)).toBeTruthy()
    expect(screen.getByText('Question number 2?')).toBeTruthy()
    expect(screen.queryByText('Question number 3?')).toBeNull()
    expect(screen.getByRole('link', { name: /Next question/ }).getAttribute('href')).toBe('#/my/practice/7/3')
  })

  it('on the result screen', async () => {
    stubApi({ ...PRACTICE, status: 'assessed', result: { message: 'Practice result text.', reasons: [] } })
    render(<PracticeResult id={7} />)
    expect(await screen.findByText(/This is a practice interview/)).toBeTruthy()
  })
})

describe('a Kikuyu interview while question set v2 has no Kikuyu wording', () => {
  it('shows the English text and says answers may be in Kikuyu', () => {
    render(<QuestionView q={QUESTIONS[0]} n={1} total={8} language="kik" />)
    expect(screen.getByText('Question number 1?').getAttribute('lang')).toBe('en')
    expect(screen.getByText('The question is shown in English. You may answer in Kikuyu.')).toBeTruthy()
  })

  it('has no such note in an English interview', () => {
    render(<QuestionView q={QUESTIONS[0]} n={1} total={8} language="en" />)
    expect(screen.queryByText(/You may answer in Kikuyu/)).toBeNull()
  })
})

describe('the daily caps', () => {
  it('says how many are left', () => {
    render(<SubmitPanel practice={PRACTICE} unsaved={0} onDone={() => {}} />)
    expect(screen.getByText('5 of 5 practice submissions left today.')).toBeTruthy()
    expect((screen.getByRole('button', { name: /Submit/ }) as HTMLButtonElement).disabled).toBe(false)
  })

  it('stops at the member’s cap, saying their answers are safe', () => {
    render(<SubmitPanel practice={{ ...PRACTICE, limits: { ...PRACTICE.limits, remaining_today: 0 } }} unsaved={0} onDone={() => {}} />)
    expect(screen.getByText(/today’s limit of 5 practice interviews/).textContent).toContain('Your answers are saved')
    expect((screen.getByRole('button', { name: /Submit/ }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('stops when the whole pilot is full', () => {
    render(<SubmitPanel practice={{ ...PRACTICE, limits: { ...PRACTICE.limits, pilot_full_today: true } }} unsaved={0} onDone={() => {}} />)
    expect(screen.getByText(/The pilot has reached today’s limit/)).toBeTruthy()
    expect((screen.getByRole('button', { name: /Submit/ }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('shows the server’s message if the cap is reached after the page loaded', async () => {
    const detail = 'You have reached today\'s limit of 5 practice interviews. Your answers are saved, and you can submit again tomorrow.'
    const fetch = vi.fn(async (url: string) => (url.endsWith('/submit')
      ? new Response(JSON.stringify({ detail }), { status: 429 })
      : new Response(JSON.stringify(PRACTICE), { status: 200 })))
    vi.stubGlobal('fetch', fetch)
    render(<SubmitPanel practice={PRACTICE} unsaved={0} onDone={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /Submit/ }))
    expect(await screen.findByText(new RegExp('limit of 5 practice interviews'))).toBeTruthy()
  })

  it('will not submit past unanswered questions', () => {
    render(<SubmitPanel practice={{ ...PRACTICE, responses: PRACTICE.responses.slice(1) }} unsaved={0} onDone={() => {}} />)
    expect(screen.getByText(/1 remaining question first/)).toBeTruthy()
    expect((screen.getByRole('button', { name: /Submit/ }) as HTMLButtonElement).disabled).toBe(true)
  })
})

describe('members never see scores', () => {
  const RESULT = { message: 'From these practice answers, a loan officer would probably want to look more closely. This is practice only.',
                   reasons: ['Your regular farm income counted in your favour.'] }

  it('shows the result and the reasons in words', () => {
    render(<ResultView result={RESULT} />)
    expect(screen.getByText(/look more closely/)).toBeTruthy()
    expect(screen.getByText(/farm income counted in your favour/)).toBeTruthy()
  })

  it('shows nothing of the numbers, even if a response carried them', () => {
    const leaked = { ...RESULT, risk_class: 'High', probabilities: { Low: 0.1 }, contributions: [{ feature: 'B3A__1', shap: 0.21 }],
                     officer_notes: 'Officer-only note' }
    const { container } = render(<ResultView result={leaked} />)
    const text = container.textContent ?? ''
    for (const never of ['High', 'Low', '0.1', '0.21', 'B3A', 'Officer-only', 'shap', 'risk']) {
      expect(text).not.toContain(never)
    }
  })
})

describe('the System Usability Scale', () => {
  const answerAll = (value: number) => {
    t.sus.statements.forEach((_, i) => {
      const radios = document.getElementsByName(`sus-${i}`)
      fireEvent.click(radios[value - 1])
    })
  }

  it('asks the ten standard statements on a 1-5 scale', () => {
    render(<SusForm id={7} />)
    expect(t.sus.statements).toHaveLength(10)
    expect(screen.getByText(/1\. I think that I would like to use this system frequently/)).toBeTruthy()
    expect(screen.getByText(/10\. I needed to learn a lot of things/)).toBeTruthy()
    expect(document.getElementsByName('sus-0')).toHaveLength(5)
    expect(screen.getByLabelText('1: Strongly disagree', { exact: false, selector: '[name="sus-0"]' })).toBeTruthy()
  })

  it('needs all ten before sending', () => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    render(<SusForm id={7} />)
    fireEvent.click(screen.getByRole('button', { name: /Send my answers/ }))
    expect(screen.getByRole('alert').textContent).toContain('all ten')
    expect(fetch).not.toHaveBeenCalled()
  })

  it('is optional', () => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    render(<SusForm id={7} />)
    fireEvent.click(screen.getByRole('button', { name: /No thanks/ }))
    expect(screen.getByRole('status').textContent).toContain('Thank you for taking part')
    expect(fetch).not.toHaveBeenCalled()
  })

  it('sends the answers and the comment, then shows the score worked out here', async () => {
    const fetch = vi.fn(async () => new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetch)
    render(<SusForm id={7} />)
    answerAll(3)
    fireEvent.change(screen.getByLabelText(/Anything else/), { target: { value: ' Easy enough. ' } })
    fireEvent.click(screen.getByRole('button', { name: /Send my answers/ }))
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('50 out of 100'))
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/me/practice/7/sus')
    expect(JSON.parse(init.body as string)).toEqual({ answers: Array(10).fill(3), comment: 'Easy enough.' })
  })
})
