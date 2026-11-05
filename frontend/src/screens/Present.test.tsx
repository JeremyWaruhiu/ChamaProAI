// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import type { PresentDetail, PresentTurn, StaffExplain } from '../api/types'
import { ToastProvider } from '../components/Toast'
import { AuthContext } from '../lib/auth'
import { canOpen } from '../lib/auth'
import { evaluationsOf, featureRows, previousEvaluation, shapRows, sourceKind, towardsFavour } from '../lib/present'
import { setPresentationMode } from '../lib/presentation'
import { parse, paths } from '../lib/router'
import { FeatureTable, PresentList, PresentOne, RiskBars, ShapChart } from './Present'

const explain = (over: Partial<StaffExplain> = {}): StaffExplain => ({
  outcome: 'clarify', reason_code: 'clarify', reason: 'We need a little more.', risk_class: 'Medium',
  probabilities: { Low: 0.3, Medium: 0.5, High: 0.2 },
  contributions: [{ feature: 'log_monthly_income', value: 9.8, shap: 0.3, in_favour: false },
                  { feature: 'children', value: 4, shap: -0.1, in_favour: true }],
  shap_error: null,
  features: { monthly_income_kes: 18000, household_size: 6, income_sources: { employed: 1 }, sacco_loan_use: 0, age: 38, is_female: 1, lost_as_guarantor: { sacco: 0, chama: null } },
  provenance: { monthly_income_kes: 'declared', household_size: 'verified', sacco_loan_use: 'records', term_months: 'conversation', age: 'verified', 'lost_as_guarantor.chama': 'missing' },
  overrides: { term_months: 12 }, questions: ['C2'], amount_kes: null, term_months: 12, instalment_kes: 5332, policy_version: '2026.11.3',
  trace: { checks: [{ check: 'affordability', passed: false, values: { instalment_kes: 5332, limit_kes: 6000 } },
                    { check: 'guarantor_capacity', passed: true, values: { need_kes: 0, guarantors: [{ member_no: 'M-1' }] } }] },
  ...over,
})
const AFTER = explain({
  risk_class: 'Low', outcome: 'approve_reduced', reason_code: 'reduced_rule', questions: [], amount_kes: 45000,
  probabilities: { Low: 0.46, Medium: 0.28, High: 0.26 },
  contributions: [{ feature: 'log_monthly_income', value: 10, shap: 0.47, in_favour: true }, { feature: 'children', value: 4, shap: 0.04, in_favour: true }],
  provenance: { monthly_income_kes: 'conversation', household_size: 'verified', sacco_loan_use: 'records', term_months: 'conversation', age: 'verified' },
  features: { monthly_income_kes: 22000, household_size: 6, income_sources: { employed: 1 }, sacco_loan_use: 0, age: 38, is_female: 1 },
})
const bot = (seq: number, e: StaffExplain | null = null): PresentTurn => ({
  seq, speaker: 'bot', template_id: 'C2', text: 'Your income on record is 18,000 shillings a month.', text_en: null, kik_pending: false, audio_url: null, input_mode: null,
  asr_transcript: null, asr_model: null, translation: null, extraction: null, explain: e,
  latency_ms: { asr: null, translate_extract: null, evaluate: null, tts: null }, created_at: '2026-11-05T06:00:00Z',
})
const spoke = (seq: number): PresentTurn => ({
  ...bot(seq), speaker: 'member', template_id: 'C2', text: 'Aca, nĩ ngiri mĩrongo ĩĩrĩ na igĩrĩ', input_mode: 'voice', asr_transcript: 'Aca, nĩ ngiri mĩrongo ĩĩrĩ na igĩrĩ',
  translation: 'No, it is twenty two thousand.', audio_url: `/api/present/conversations/5/turns/${seq}/audio`,
  extraction: { question_id: 'C2', parser: {}, model: { fields: {}, confidence: 0.9 }, model_error: null, amount_conflict: null, used: { monthly_income_kes: 22000 } },
  latency_ms: { asr: 3200, translate_extract: 800, evaluate: 150, tts: 0 },
})
const detail = (over: Partial<PresentDetail> = {}): PresentDetail => ({
  row: { id: 5, member_id: 2, member_no: 'M-1002', member_name: 'Njeri Mwangi', language: 'kik', status: 'open', state: 'CONFIRM', turn_count: 8, busy: false, stage: null,
         started_at: '2026-11-05T06:00:00Z', last_activity_at: '2026-11-05T06:00:00Z' },
  consent_given: true, consent_version: 'consent-x', policy_version: '2026.11.3', application_id: null,
  turns: [bot(1, explain()), spoke(2), bot(3, AFTER)], outcome: null, ...over,
})

beforeEach(() => {
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: true, addEventListener() {}, removeEventListener() {} })))
  setPresentationMode(false)
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('routes and who may open them', () => {
  it('reaches the list and one conversation, for staff only', () => {
    expect(parse(paths.present())).toEqual({ screen: 'present' })
    expect(parse(paths.presentOne(5))).toEqual({ screen: 'presentOne', id: 5 })
    expect(parse(paths.chat())).toEqual({ screen: 'chat', id: null })
    expect(parse(paths.chat(7))).toEqual({ screen: 'chat', id: 7 })
    expect(canOpen('present', 'officer')).toBe(true)
    expect(canOpen('presentOne', 'admin')).toBe(true)
    expect(canOpen('present', 'member')).toBe(false)
    expect(canOpen('chat', 'member')).toBe(true)
    expect(canOpen('chat', 'officer')).toBe(false)
  })
})

describe('the SHAP chart', () => {
  it('turns every value so that right is in the member\'s favour, across classes', () => {
    expect(towardsFavour({ feature: 'x', value: 1, shap: 0.3, in_favour: false })).toBe(-0.3)
    expect(towardsFavour({ feature: 'x', value: 1, shap: -0.1, in_favour: true })).toBe(0.1)
    const { rows, scale } = shapRows(AFTER, explain())
    expect(rows[0]).toMatchObject({ label: 'Monthly income', now: 0.47, before: -0.3 })
    expect(scale).toBe(0.47)
  })

  it('draws the previous evaluation faintly beside each bar that had one, and moves the C2 bar', () => {
    render(<ShapChart now={AFTER} was={explain()} />)
    expect(within(screen.getByTestId('shap')).getAllByTestId('shap-row')).toHaveLength(2)
    expect(within(screen.getByTestId('shap')).getAllByTestId('shap-was')).toHaveLength(2)
    expect(screen.getByText('Previous evaluation')).toBeTruthy()
    expect(screen.getByText('+0.470')).toBeTruthy()
  })

  it('has no faint bars, and no legend entry, on the first evaluation', () => {
    render(<ShapChart now={explain()} was={null} />)
    expect(screen.queryByTestId('shap-was')).toBeNull()
    expect(screen.queryByText('Previous evaluation')).toBeNull()
  })

  it('says so when SHAP failed', () => {
    render(<ShapChart now={explain({ contributions: [], shap_error: 'unavailable' })} was={null} />)
    expect(screen.getByText('SHAP was not available for this evaluation.')).toBeTruthy()
  })

  it('keeps the movement on screen when the last evaluation only repeats the one before', () => {
    const evaluations = evaluationsOf([bot(1, explain()), spoke(2), bot(3, AFTER), spoke(4), bot(5, AFTER)])
    expect(evaluations).toHaveLength(3)
    expect(previousEvaluation(evaluations, 2)?.risk_class).toBe('Medium')
    expect(previousEvaluation(evaluations, 0)).toBeNull()
  })
})

describe('the risk bars', () => {
  it('names the class and every probability, with where each was', () => {
    render(<RiskBars now={AFTER} was={explain()} />)
    const panel = within(screen.getByTestId('risk'))
    expect(panel.getByText('Low risk')).toBeTruthy()
    expect(panel.getByText('46.0%')).toBeTruthy()
    expect(panel.getByTitle('Previous evaluation: 50.0%')).toBeTruthy()
  })
})

describe('the feature table', () => {
  it('says where each value came from, in words and colour', () => {
    render(<FeatureTable now={AFTER} />)
    const row = (name: string) => screen.getByText(name).closest('tr')!
    expect(row('Monthly income').dataset.source).toBe('conversation')
    expect(row('Monthly income').textContent).toContain('KSh 22,000')
    expect(row('Monthly income').textContent).toContain('This conversation')
    expect(row('SACCO loans').dataset.source).toBe('records')
    expect(row('Household size').dataset.source).toBe('profile')
    expect(row('Term').textContent).toContain('12 months')
  })

  it('files declared and verified under the profile, and anything else as missing', () => {
    expect(['verified', 'declared', 'records', 'conversation', 'missing', undefined].map(sourceKind))
      .toEqual(['profile', 'profile', 'records', 'conversation', 'missing', 'missing'])
    expect(featureRows(explain()).find((r) => r.key === 'lost_as_guarantor.chama')).toMatchObject({ source: 'missing', value: 'not stated' })
    expect(featureRows(explain()).find((r) => r.key === 'income_sources')?.value).toBe('employment')
  })
})

describe('following a conversation', () => {
  it('shows the pipeline of each member turn', async () => {
    vi.spyOn(api, 'presentDetail').mockResolvedValue(detail())
    render(<ToastProvider><PresentOne id={5} /></ToastProvider>)
    const turn = within(await screen.findByTestId('present-turn'))
    expect(turn.getByText('Aca, nĩ ngiri mĩrongo ĩĩrĩ na igĩrĩ')).toBeTruthy()
    expect(turn.getByText('No, it is twenty two thousand.')).toBeTruthy()
    expect(turn.getByText(/"monthly_income_kes": 22000/)).toBeTruthy()
    expect(turn.getByText('3.2 s')).toBeTruthy()
    expect(turn.getByText('800 ms')).toBeTruthy()
    expect(document.querySelector('audio')?.getAttribute('src')).toBe('/api/present/conversations/5/turns/2/audio')
    expect(screen.getByText('Approve a reduced amount')).toBeTruthy()
    expect(screen.getByText('Policy 2026.11.3')).toBeTruthy()
    expect(screen.getByText('No money has moved.')).toBeTruthy()
  })

  it('finally shows the ledger entry and the balance change', async () => {
    vi.spyOn(api, 'presentDetail').mockResolvedValue(detail({ outcome: {
      decision: 'approved', application_id: 1, requested_kes: 60000, amount_kes: 45000, term_months: 12, instalment_kes: 3999, guarantors: ['A'],
      balance_before_kes: 0, balance_after_kes: 45000, review_requested: false,
      ledger: { entry_id: 9, loan_id: 3, reference: 'LOAN-3', entry_type: 'loan_disbursement', amount_kes: 45000, posted_at: '2026-11-05T06:00:00Z' },
    } }))
    render(<ToastProvider><PresentOne id={5} /></ToastProvider>)
    const ledger = within(await screen.findByTestId('ledger'))
    expect(ledger.getByText('LOAN-3')).toBeTruthy()
    expect(ledger.getByText('KSh 45,000')).toBeTruthy()
  })

  it('polls while it is open and picks up the new turn and the stage', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const get = vi.spyOn(api, 'presentDetail').mockResolvedValue(detail({ row: { ...detail().row, busy: true, stage: 'transcribing' } }))
    render(<ToastProvider><PresentOne id={5} /></ToastProvider>)
    await screen.findByTestId('present-working')
    expect(screen.getByText('Transcribing')).toBeTruthy()
    const calls = get.mock.calls.length
    get.mockResolvedValue(detail({ turns: [bot(1, explain()), spoke(2), bot(3, AFTER), spoke(4), bot(5, AFTER)] }))
    await act(async () => { await vi.advanceTimersByTimeAsync(1100) })
    expect(get.mock.calls.length).toBeGreaterThan(calls)
    await waitFor(() => expect(screen.getAllByTestId('present-turn')).toHaveLength(2))
    expect(screen.queryByTestId('present-working')).toBeNull()
    vi.useRealTimers()
  })

  it('can go back to an earlier evaluation', async () => {
    vi.spyOn(api, 'presentDetail').mockResolvedValue(detail())
    render(<ToastProvider><PresentOne id={5} /></ToastProvider>)
    await screen.findByText('Approve a reduced amount')
    fireEvent.click(screen.getByRole('button', { name: 'Show evaluation 1' }))
    expect(screen.getByText('Medium risk')).toBeTruthy()
    expect(screen.getByText('Ask a question')).toBeTruthy()
    expect(screen.getByText('Next: C2')).toBeTruthy()
  })

  it('before any evaluation says so', async () => {
    vi.spyOn(api, 'presentDetail').mockResolvedValue(detail({ turns: [bot(1)] }))
    render(<ToastProvider><PresentOne id={5} /></ToastProvider>)
    expect(await screen.findByText(/Nothing has been evaluated yet/)).toBeTruthy()
    expect(screen.getByText('The member has not answered yet.')).toBeTruthy()
  })

  it('presentation mode can be turned on and off', async () => {
    vi.spyOn(api, 'presentDetail').mockResolvedValue(detail())
    render(<ToastProvider><PresentOne id={5} /></ToastProvider>)
    fireEvent.click(await screen.findByRole('button', { name: 'Presentation mode' }))
    expect(document.documentElement.dataset.presentation).toBe('1')
    fireEvent.click(screen.getByRole('button', { name: 'Leave presentation mode' }))
    expect(document.documentElement.dataset.presentation).toBe('0')
  })
})

describe('the list', () => {
  const row = { ...detail().row }
  const asRole = (role: 'admin' | 'officer') => ({ user: { username: 'x', role } as never, signOut() {} })

  it('links to each conversation and says whether the speech model is warm', async () => {
    vi.spyOn(api, 'presentList').mockResolvedValue([row])
    vi.spyOn(api, 'health').mockResolvedValue({ status: 'ok', asr_decoding: 'x', asr: { kik: { loaded: true, warmed: true, engine: 'openvino', device: 'GPU', model: 'm', language: 'sw', error: null }, en: { loaded: false, engine: null, device: null, model: null, language: 'en', error: null } } })
    render(<AuthContext.Provider value={asRole('officer')}><ToastProvider><PresentList /></ToastProvider></AuthContext.Provider>)
    expect((await screen.findByRole('link', { name: 'Follow Njeri Mwangi' })).getAttribute('href')).toBe('#/present/5')
    expect(await screen.findByText('Kikuyu speech model warmed')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Reset demo members' })).toBeNull()
  })

  it('offers an admin the reset only where there are demo members, and asks first', async () => {
    vi.spyOn(api, 'presentList').mockResolvedValue([])
    vi.spyOn(api, 'health').mockRejectedValue(new Error('down'))
    const status = vi.spyOn(api, 'demoStatus').mockResolvedValue({ available: false, people: [] })
    const reset = vi.spyOn(api, 'demoReset').mockResolvedValue({ conversations_closed: 1, loans_reversed: 1, applications_closed: 0, problems: [], people: [] })
    const { unmount } = render(<AuthContext.Provider value={asRole('admin')}><ToastProvider><PresentList /></ToastProvider></AuthContext.Provider>)
    await screen.findByText('No conversations yet')
    expect(screen.queryByRole('button', { name: 'Reset demo members' })).toBeNull()
    unmount()
    status.mockResolvedValue({ available: true, people: [{ member_id: 1, full_name: 'Wanjiru Kamau', open_conversations: 1, active_loans: 1, open_applications: 0 }] })
    render(<AuthContext.Provider value={asRole('admin')}><ToastProvider><PresentList /></ToastProvider></AuthContext.Provider>)
    fireEvent.click(await screen.findByRole('button', { name: 'Reset demo members' }))
    expect(reset).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Reset them' }))
    await waitFor(() => expect(reset).toHaveBeenCalledOnce())
    expect(await screen.findByText(/Reset: 1 conversation closed, 1 loan reversed/)).toBeTruthy()
  })
})
