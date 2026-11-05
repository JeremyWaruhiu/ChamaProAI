// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from '../api/client'
import type { ConversationBrief, ConversationDetail, ConversationOutcome, MemberExplain, Turn } from '../api/types'
import { ToastProvider } from '../components/Toast'
import { laterStage, memberStage, quickReplies, TEXT_STAGES, understood, VOICE_STAGES } from '../lib/conversation'
import css from './Chat.module.css?raw'
import { BotBubble, Chat, MemberBubble, OutcomeCard, StageIndicator, WhySheet } from './Chat'

const turn = (over: Partial<Turn>): Turn => ({
  seq: 1, speaker: 'bot', template_id: 'G1', text: 'Good morning, Wanjiru.', text_en: null, kik_pending: false, audio_url: null,
  input_mode: null, asr_transcript: null, asr_model: null, translation: null, extraction: null, explain: null, actions: [],
  latency_ms: { asr: null, translate_extract: null, evaluate: null, tts: null }, created_at: '2026-11-05T06:00:00Z', ...over,
})
const brief = (over: Partial<ConversationBrief> = {}): ConversationBrief => ({
  id: 7, language: 'kik', status: 'open', state: 'CONSENT', consent_given: null, consent_version: null, policy_version: '2026.11.3',
  application_id: null, self_service_run_id: null, started_at: '2026-11-05T06:00:00Z', ended_at: null, busy: false, ...over,
})
const detail = (over: Partial<ConversationDetail> = {}): ConversationDetail => ({
  conversation: brief(),
  turns: [turn({ seq: 1, audio_url: '/a/1' }), turn({ seq: 2, template_id: 'CONSENT', text: 'Do you agree?', audio_url: '/a/2' })],
  outcome: null, ...over,
})
const EXPLAIN: MemberExplain = {
  reason: 'You can have KSh 40,000 now.',
  checks: [{ passed: true, text: 'Your deposits on record are KSh 30,000.' }, { passed: false, text: 'You have a loan payment outstanding.' },
           { passed: null, text: 'We could not yet work out what you can afford.' }],
  drivers: ['Your regular farm income counts in your favour.'],
}
const OUTCOME: ConversationOutcome = {
  decision: 'approved', application_id: 3, requested_kes: 40000, amount_kes: 40000, term_months: 12, instalment_kes: 3554,
  guarantors: ['Lucy Nduta', 'Anne Wairimu'], balance_before_kes: 0, balance_after_kes: 40000, review_requested: false,
}

// A browser's audio, recorded so a test can say what played and when.
class FakeAudio {
  static made: FakeAudio[] = []
  static allowed = true
  src = ''
  paused = true
  played: string[] = []
  onended: (() => void) | null = null
  onerror: (() => void) | null = null
  oncanplay: (() => void) | null = null
  onplaying: (() => void) | null = null
  constructor() { FakeAudio.made.push(this) }
  play() {
    if (!FakeAudio.allowed) return Promise.reject(new DOMException('needs a tap', 'NotAllowedError'))
    this.paused = false
    this.played.push(this.src)
    this.onplaying?.()
    return Promise.resolve()
  }
  pause() { this.paused = true }
}

beforeEach(() => {
  FakeAudio.made = []
  FakeAudio.allowed = true
  vi.stubGlobal('Audio', FakeAudio)
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true, addEventListener() {}, removeEventListener() {} })))
  vi.stubGlobal('MediaRecorder', class { static isTypeSupported = () => true })
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia: vi.fn() } })
  window.location.hash = '#/my/chat/7'
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

const show = (id: number | null = 7) => render(<ToastProvider><Chat id={id} /></ToastProvider>)
const played = () => FakeAudio.made.flatMap((a) => a.played)

describe('one hand on a phone', () => {
  const px = (rule: string, prop: string) => Number(new RegExp(`\\.${rule} \\{[^}]*?${prop}: (\\d+)px`).exec(css)?.[1] ?? NaN)

  it('the things a thumb reaches for are large', () => {
    expect(px('mic', 'min-height')).toBeGreaterThanOrEqual(72)
    expect(px('quickReply', 'min-height')).toBeGreaterThanOrEqual(56)
    expect(px('language', 'min-height')).toBeGreaterThanOrEqual(72)
    expect(px('replay', 'width')).toBeGreaterThanOrEqual(44)
    expect(px('sendBtn', 'min-height')).toBeGreaterThanOrEqual(48)
  })

  it('a long press on the microphone does not select text or open a menu', () => {
    expect(css).toMatch(/\.mic \{[^}]*touch-action: none/)
    expect(css).toMatch(/\.mic \{[^}]*-webkit-touch-callout: none/)
  })
})

describe('the bubbles', () => {
  it('a bot bubble is its text, with a replay button only if there is audio', () => {
    const onReplay = vi.fn()
    const { rerender } = render(<BotBubble turn={turn({ audio_url: '/a/1' })} playing={false} loading={false} onReplay={onReplay} />)
    fireEvent.click(screen.getByRole('button', { name: 'Hear this again' }))
    expect(onReplay).toHaveBeenCalledWith({ seq: 1, url: '/a/1' })
    rerender(<BotBubble turn={turn({})} playing={false} loading={false} onReplay={onReplay} />)
    expect(screen.queryByRole('button', { name: 'Hear this again' })).toBeNull()
    expect(screen.getByText('Good morning, Wanjiru.')).toBeTruthy()
  })

  it('shows the English of a pending Kikuyu line with no warning', async () => {
    vi.spyOn(api, 'conversation').mockResolvedValue(detail({ turns: [turn({ kik_pending: true, text: 'Do you agree?' })] }))
    show()
    await screen.findByText('Do you agree?')
    expect(document.body.textContent).not.toMatch(/pending|not yet|translat/i)
  })

  it('a member bubble is what was heard, with the English and the chips under it, and can be closed', () => {
    const t = turn({
      seq: 3, speaker: 'member', text: 'Ngũkwenda ngiri mĩrongo ĩna', input_mode: 'voice', translation: 'I want forty thousand for a dairy cow',
      extraction: { question_id: 'R1', parser: {}, model: null, model_error: 'off', amount_conflict: null,
                    used: { amount_kes: 40000, purpose_text: 'dairy cow' } },
    })
    const { container, rerender } = render(<MemberBubble turn={t} latest />)
    expect(screen.getByText('Ngũkwenda ngiri mĩrongo ĩna')).toBeTruthy()
    expect(screen.getByText('Amount: KSh 40,000')).toBeTruthy()
    expect(screen.getByText('Purpose: dairy cow')).toBeTruthy()
    expect(screen.getByText(/I want forty thousand/)).toBeTruthy()
    expect(container.querySelector('details')?.open).toBe(true)
    rerender(<MemberBubble turn={t} latest={false} />)
    expect(container.querySelector('details')?.open).toBe(false)
  })

  it('leaves out an English translation that says the same thing', () => {
    render(<MemberBubble latest turn={turn({ speaker: 'member', text: 'yes', translation: 'yes', extraction: { question_id: 'CONSENT', parser: {}, model: null, model_error: 'off', amount_conflict: null, used: { answer: 'yes' } } })} />)
    expect(screen.queryByText('In English:')).toBeNull()
    expect(screen.getByText('Answer: Yes')).toBeTruthy()
  })
})

describe('what was understood', () => {
  it('names each field as the brief does', () => {
    expect(understood({ amount_kes: 40000, purpose_text: 'dairy cow', term_months: 12, monthly_income_kes: 22000 }).map((c) => `${c.label}: ${c.value}`))
      .toEqual(['Amount: KSh 40,000', 'Purpose: dairy cow', 'Term: 12 months', 'Income: KSh 22,000'])
    expect(understood({ term_months: 1 })[0].value).toBe('1 month')
    expect(understood({ corrections: { household_size: 6 }, answer: 'no' }).map((c) => c.value)).toEqual(['No', '6'])
    expect(understood(null)).toEqual([])
  })
})

describe('the quick replies', () => {
  it.each(['CHECK_AMOUNT', 'CONSENT', 'CONFIRM'])('%s offers yes and no', (state) => {
    expect(quickReplies(state, 'en').map((r) => r.label)).toEqual(['Yes', 'No'])
    expect(quickReplies(state, 'kik').map((r) => r.label)).toEqual(['Ĩĩ', 'Aca'])
  })

  it.each(['G2', 'R1', 'C1', 'C2', 'END'])('%s does not', (state) => {
    expect(quickReplies(state, 'en')).toEqual([])
  })

  it('tapping one sends it and takes the buttons away while it is worked on', async () => {
    vi.spyOn(api, 'conversation').mockResolvedValue(detail())
    vi.spyOn(api, 'conversationStage').mockResolvedValue({ stage: null, busy: true })
    let finish!: (v: Awaited<ReturnType<typeof api.replyToConversation>>) => void
    const reply = vi.spyOn(api, 'replyToConversation').mockImplementation(() => new Promise((r) => { finish = r }))
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Ĩĩ' }))
    expect(reply).toHaveBeenCalledWith(7, { text: 'Ĩĩ' })
    expect(screen.queryByRole('button', { name: 'Ĩĩ' })).toBeNull()
    expect(screen.getByRole('button', { name: /Hold to talk/ })).toHaveProperty('disabled', true)
    expect(screen.getByLabelText('Type your answer')).toHaveProperty('disabled', true)
    await act(async () => finish({
      conversation: brief({ state: 'G2' }), member_turn: turn({ seq: 3, speaker: 'member', text: 'Ĩĩ' }),
      bot_turns: [turn({ seq: 4, template_id: 'G2', text: 'Is that still correct?' })], explain: null, outcome: null,
    }))
    expect(screen.getByText('Is that still correct?')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Ĩĩ' })).toBeNull()      // G2 is spoken or typed
    expect(screen.getByLabelText('Type your answer')).toHaveProperty('disabled', false)
  })
})

describe('the stage indicator', () => {
  it('marks where it has got to', () => {
    render(<StageIndicator stages={VOICE_STAGES} current="understanding" />)
    const steps = within(screen.getByTestId('stages')).getAllByRole('listitem')
    expect(steps.map((s) => s.textContent)).toEqual(['Listening', 'Transcribing', 'Understanding', 'Deciding'])
    expect(steps[2].getAttribute('aria-current')).toBe('step')
  })

  it('a typed answer has only the last two', () => {
    render(<StageIndicator stages={TEXT_STAGES} current="deciding" />)
    expect(within(screen.getByTestId('stages')).getAllByRole('listitem').map((s) => s.textContent)).toEqual(['Understanding', 'Deciding'])
  })

  it('never goes backwards, and speech counts as deciding', () => {
    expect(laterStage(VOICE_STAGES, 'deciding', 'understanding')).toBe('deciding')
    expect(laterStage(VOICE_STAGES, 'transcribing', 'understanding')).toBe('understanding')
    expect(laterStage(VOICE_STAGES, 'understanding', null)).toBe('understanding')
    expect(memberStage('speaking')).toBe('deciding')
  })
})

describe('audio', () => {
  it('waits for the one tap, then plays what is waiting in order, on one element', async () => {
    vi.spyOn(api, 'conversation').mockResolvedValue(detail())
    show()
    const tap = await screen.findByRole('button', { name: 'Tap to start' })
    expect(played()).toEqual([])
    await act(async () => { fireEvent.click(tap) })
    expect(screen.queryByRole('button', { name: 'Tap to start' })).toBeNull()
    await waitFor(() => expect(played().filter((u) => u.startsWith('/a'))).toEqual(['/a/1']))
    await act(async () => { FakeAudio.made[0].onended?.() })
    expect(played().filter((u) => u.startsWith('/a'))).toEqual(['/a/1', '/a/2'])
    expect(FakeAudio.made).toHaveLength(1)
    expect(played()[0]).toMatch(/^data:audio/)    // the silence that unlocks it, inside the tap
  })

  it('asks for the tap again if the browser refuses', async () => {
    vi.spyOn(api, 'conversation').mockResolvedValue(detail())
    show()
    const tap = await screen.findByRole('button', { name: 'Tap to start' })
    await act(async () => { fireEvent.click(tap) })
    FakeAudio.allowed = false
    await act(async () => { FakeAudio.made[0].onended?.() })
    expect(await screen.findByRole('button', { name: 'Tap to start' })).toBeTruthy()
  })

  it('after a reload only what was said since the member last spoke is queued', async () => {
    vi.spyOn(api, 'conversation').mockResolvedValue(detail({
      conversation: brief({ state: 'R1' }),
      turns: [turn({ seq: 1, audio_url: '/a/1' }), turn({ seq: 2, speaker: 'member', text: 'yes' }), turn({ seq: 3, template_id: 'R1', audio_url: '/a/3', text: 'How much?' })],
    }))
    show()
    const tap = await screen.findByRole('button', { name: 'Tap to start' })
    await act(async () => { fireEvent.click(tap) })
    await waitFor(() => expect(played().filter((u) => u.startsWith('/a'))).toEqual(['/a/3']))
  })
})

describe('starting and carrying on', () => {
  it('with nothing open it asks for a language, and starts in it', async () => {
    vi.spyOn(api, 'currentConversation').mockResolvedValue(null)
    const start = vi.spyOn(api, 'startConversation').mockResolvedValue({ conversation: brief(), resumed: false, turns: [] })
    show(null)
    fireEvent.click(await screen.findByRole('button', { name: 'Gĩkũyũ' }))
    expect(screen.getByRole('button', { name: 'English' })).toBeTruthy()
    await waitFor(() => expect(start).toHaveBeenCalledWith('kik'))
  })

  it('an open conversation is carried on, not started again', async () => {
    vi.spyOn(api, 'currentConversation').mockResolvedValue(detail())
    const start = vi.spyOn(api, 'startConversation')
    show(null)
    await waitFor(() => expect(window.location.hash).toBe('#/my/chat/7'))
    expect(start).not.toHaveBeenCalled()
  })

  it('says what is wrong when it cannot start', async () => {
    vi.spyOn(api, 'currentConversation').mockResolvedValue(null)
    vi.spyOn(api, 'startConversation').mockRejectedValue(new ApiError(409, 'You already have an application being decided.'))
    show(null)
    fireEvent.click(await screen.findByRole('button', { name: 'English' }))
    expect(await screen.findByText(/already have an application/)).toBeTruthy()
  })

  it('a conversation left too long offers to start again', async () => {
    vi.spyOn(api, 'conversation').mockResolvedValue(detail({ conversation: brief({ status: 'abandoned' }) }))
    show()
    expect(await screen.findByRole('button', { name: 'Start again' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Hold to talk/ })).toBeNull()
  })

  it('without a microphone it can still be typed', async () => {
    vi.stubGlobal('MediaRecorder', undefined)
    vi.spyOn(api, 'conversation').mockResolvedValue(detail())
    show()
    expect(await screen.findByLabelText('Type your answer')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Hold to talk/ })).toBeNull()
  })
})

describe('the outcome card', () => {
  const closing = [turn({ seq: 8, explain: EXPLAIN }), turn({ seq: 9, actions: [{ id: 'request_review', label: 'Ask an officer to review this', kik_pending: false, application_id: 3 }] })]

  it('shows the loan, the guarantors and the balance before and after', () => {
    render(<ToastProvider><ul><OutcomeCard outcome={OUTCOME} turns={closing} onChanged={() => {}} /></ul></ToastProvider>)
    const card = screen.getByTestId('outcome').textContent
    for (const want of ['KSh 40,000', '12 months', 'KSh 3,554', 'Lucy Nduta, Anne Wairimu', 'Before', 'KSh 0', 'After']) expect(card).toContain(want)
    expect(screen.getByRole('link', { name: 'Go to My SACCO' })).toBeTruthy()
    expect(screen.queryByRole('link', { name: /Book a time/ })).toBeNull()
  })

  it('asks for a review once, keeping its key if asked again', async () => {
    const review = vi.spyOn(api, 'requestReview').mockRejectedValueOnce(new ApiError(503, 'Try again')).mockResolvedValue({})
    const onChanged = vi.fn()
    render(<ToastProvider><ul><OutcomeCard outcome={OUTCOME} turns={closing} onChanged={onChanged} /></ul></ToastProvider>)
    fireEvent.click(screen.getByRole('button', { name: 'Ask an officer to review this' }))
    await screen.findByText('Could not ask for a review')
    fireEvent.click(screen.getByRole('button', { name: 'Ask an officer to review this' }))
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
    expect(review.mock.calls[0][1]).toBe(review.mock.calls[1][1])
    expect(review.mock.calls[0][0]).toBe(3)
  })

  it('once a review is asked for, says so and does not offer it again', () => {
    render(<ToastProvider><ul><OutcomeCard outcome={{ ...OUTCOME, review_requested: true }} turns={closing} onChanged={() => {}} /></ul></ToastProvider>)
    expect(screen.queryByRole('button', { name: 'Ask an officer to review this' })).toBeNull()
    expect(screen.getByText('An officer has been asked to review this.')).toBeTruthy()
  })

  it('a referral offers a booking, on its application, and no loan figures', () => {
    const referred = { ...OUTCOME, decision: 'referred' as const, amount_kes: null, instalment_kes: null, guarantors: [], balance_before_kes: null, balance_after_kes: null }
    const turns = [turn({ seq: 9, actions: [{ id: 'book_interview', label: 'Book a time with an officer', kik_pending: false, application_id: 3 }] })]
    render(<ToastProvider><ul><OutcomeCard outcome={referred} turns={turns} onChanged={() => {}} /></ul></ToastProvider>)
    expect(screen.getByRole('link', { name: 'Book a time with an officer' }).getAttribute('href')).toBe('#/my/applications/3')
    expect(screen.queryByText('Before')).toBeNull()
    expect(screen.getByText('You asked for')).toBeTruthy()
  })

  it('with nothing to apply against, a booking starts a new application', () => {
    const none = { ...OUTCOME, decision: 'none' as const, application_id: null, requested_kes: null, amount_kes: null, term_months: null, instalment_kes: null, guarantors: [], balance_before_kes: null, balance_after_kes: null }
    render(<ToastProvider><ul><OutcomeCard outcome={none} turns={[turn({ actions: [{ id: 'book_interview', label: 'Book', kik_pending: false, application_id: null }] })]} onChanged={() => {}} /></ul></ToastProvider>)
    expect(screen.getByRole('link', { name: 'Book' }).getAttribute('href')).toBe('#/my/apply')
    expect(screen.queryByRole('button', { name: 'Why?' })).toBeNull()
  })

  it('Why? opens the plain reasons', () => {
    render(<ToastProvider><ul><OutcomeCard outcome={OUTCOME} turns={closing} onChanged={() => {}} /></ul></ToastProvider>)
    fireEvent.click(screen.getByRole('button', { name: 'Why?' }))
    expect(within(screen.getByRole('dialog')).getByText('Your regular farm income counts in your favour.')).toBeTruthy()
  })
})

describe('the Why? sheet', () => {
  it('has the reason, each check with how it went, and the drivers', () => {
    render(<WhySheet explain={EXPLAIN} onClose={() => {}} />)
    const sheet = within(screen.getByRole('dialog'))
    expect(sheet.getByText('You can have KSh 40,000 now.')).toBeTruthy()
    expect(sheet.getByText('Passed')).toBeTruthy()
    expect(sheet.getByText('Not met')).toBeTruthy()
    expect(sheet.getByText('Not worked out')).toBeTruthy()
    expect(document.body.textContent).not.toMatch(/\b(Low|Medium|High|risk|probabilit|SHAP)\b/i)
  })
})
