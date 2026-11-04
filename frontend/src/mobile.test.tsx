// @vitest-environment jsdom
// Phone layout (360-430px), as far as it can be checked without a layout
// engine: tap-target sizes and stacking rules in the stylesheets, data-label
// on every stacked table cell, phone keypads on the guarantor form, and the
// recording screen's message when the page is not a secure context. Whether
// any page scrolls sideways is measured in a real browser (docs/screenshots).
import { cleanup, render, screen, within } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { InterviewSummary } from './api/types'
import layout from './components/Layout.module.css?raw'
import slots from './components/SlotPicker.module.css?raw'
import practice from './screens/Practice.module.css?raw'
import shell from './components/Shell.module.css?raw'
import ui from './components/ui.module.css?raw'
import { micUnavailable } from './hooks/useRecorder'
import index from './index.css?raw'
import { emptyGuarantor, type GuarantorDraft } from './lib/guarantors'
import { InterviewList } from './screens/InterviewList'
import member from './screens/Member.module.css?raw'
import { GuarantorForm } from './screens/MyApplication'
import { MicUnavailable } from './screens/Recording'
import recording from './screens/Recording.module.css?raw'
import sacco from './screens/MySacco.module.css?raw'
import results from './screens/Results.module.css?raw'
import tables from './screens/Tables.module.css?raw'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const TOUCH = '@media (max-width: 720px), (pointer: coarse)'
const PHONE = '@media (max-width: 720px)'

/** The body of the first `at` block in css (brace-matched), or the whole sheet. */
function block(css: string, at?: string): string {
  if (!at) return css
  const start = css.indexOf(`${at} {`)
  expect(start, `${at} missing`).toBeGreaterThanOrEqual(0)
  let depth = 0
  for (let i = css.indexOf('{', start); i < css.length; i++) {
    if (css[i] === '{') depth++
    if (css[i] === '}' && --depth === 0) return css.slice(css.indexOf('{', start) + 1, i)
  }
  throw new Error(`unbalanced ${at}`)
}

/** The declarations of `selector`'s rule (first match), optionally inside an at-rule. */
function rule(css: string, selector: string, at?: string): string {
  const body = block(css, at)
  const esc = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const m = new RegExp(`(?:^|[\\s,}])${esc}\\s*\\{([^}]*)\\}`).exec(body)
  expect(m, `${selector}${at ? ` in ${at}` : ''} missing`).not.toBeNull()
  return m![1]
}

const px = (decls: string, prop: string) => Number(new RegExp(`${prop}:\\s*(\\d+)px`).exec(decls)?.[1] ?? NaN)

describe('tap targets on a phone are at least 44px', () => {
  it.each([
    ['buttons', index, '.btn', undefined],
    ['text fields and selects', index, '.input, .select', undefined],
    ['small buttons', index, '.btn-sm', TOUCH],
    ['table row links', index, '.table a.row-link', TOUCH],
    ['member portal tabs', layout, '.memberTab', undefined],
    ['the member portal logo link', layout, '.memberBrand', undefined],
    ['the member back link', member, '.back', undefined],
    ['the My SACCO disclosure rows', sacco, '.more > summary', undefined],
    ['skipping the registration form', sacco, '.skip', undefined],
    ['question chips while recording', recording, '.chip', TOUCH],
    ['interview steps', shell, '.step', TOUCH],
    ['list filters', tables, '.segmented button', TOUCH],
    ['calendar days', slots, '.day', undefined],
    ['interview time slots', slots, '.slot', undefined],
    ['the SUS scale', practice, '.susOption', undefined],
  ])('%s', (_, css, selector, at) => {
    expect(px(rule(css, selector, at), 'min-height')).toBeGreaterThanOrEqual(44)
  })
})

describe('nothing is wider than the phone', () => {
  it('turns list tables into stacked cards that can shrink', () => {
    expect(rule(tables, '.stack :global(thead)', PHONE)).toContain('display: none')
    const row = rule(tables, '.stack :global(tr)', PHONE)
    expect(row).toContain('display: grid')
    expect(row).toContain('minmax(0, 1fr)')        // one long cell cannot widen every row
  })

  it('lets a long badge wrap instead of pushing the card wider', () => {
    expect(rule(ui, '.badge', PHONE)).toContain('white-space: normal')
  })

  it('keeps wide evaluation tables scrolling inside their card, never the page', () => {
    expect(rule(results, '.tableScroll')).toContain('overflow-x: auto')
    expect(rule(results, '.card')).toContain('grid-template-columns: minmax(0, 1fr)')
  })
})

describe('the calendar on a phone', () => {
  it('shares the width between seven columns, so it cannot widen the page', () => {
    expect(rule(slots, '.grid')).toContain('repeat(7, minmax(0, 1fr))')
    expect(rule(slots, '.navBtn')).toContain('width: 44px')
  })
})

describe('the interview list on a phone', () => {
  it('labels every cell after the first, so each row reads as a card', async () => {
    const iv: InterviewSummary = {
      id: 11, applicant_name: 'Grace Wanjiku', created_at: '2026-11-02T08:00:00Z', status: 'open',
      question_set: 'v2', language: 'en', mode: 'live', responses_recorded: 3, questions_total: 8,
      counts: { queued: 0, transcribing: 0, transcribed: 3, failed: 0 }, risk_class: null, decision: null,
    }
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify([iv]), { status: 200 })))
    render(<InterviewList />)
    const link = await screen.findByRole('link', { name: 'Grace Wanjiku' })
    const cells = within(link.closest('tr')!).getAllByRole('cell')
    expect(link.closest('.table-wrap')!.className).toMatch(/stack/)
    expect(cells.slice(1).map((c) => c.getAttribute('data-label'))).toEqual(['Date', 'Answers', 'Status', 'Risk band'])
  })
})

describe('the guarantor form on a phone', () => {
  function Form() {
    const [rows, setRows] = useState<GuarantorDraft[]>([emptyGuarantor()])
    return <GuarantorForm rows={rows} setRows={setRows} needed={1} cap={60000} onSubmit={() => {}} />
  }

  it('opens the phone and number keypads and has one full-width submit button', () => {
    render(<Form />)
    expect(screen.getByLabelText(/mobile number/).getAttribute('type')).toBe('tel')
    expect(screen.getByLabelText(/Amount they guarantee/).getAttribute('inputmode')).toBe('numeric')
    expect(screen.getByRole('button', { name: /Submit/ }).className).toMatch(/btn-block/)
  })
})

describe('recording from a phone', () => {
  it('knows an insecure page cannot use the microphone', () => {
    vi.stubGlobal('isSecureContext', false)
    expect(micUnavailable()).toBe('insecure')
    vi.stubGlobal('isSecureContext', true)
    vi.stubGlobal('MediaRecorder', undefined)
    expect(micUnavailable()).toBe('unsupported')
  })

  it('says why, and how to record, instead of failing silently', () => {
    render(<MicUnavailable reason="insecure" />)
    const note = screen.getByRole('status')
    expect(note.textContent).toContain('secure https:// address')
    expect(note.textContent).toContain(window.location.origin)
    expect(note.textContent).toContain('type the answer or upload a recording')
  })
})
