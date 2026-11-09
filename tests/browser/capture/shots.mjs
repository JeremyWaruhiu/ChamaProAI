// Chapter 5 screenshots, docs/screenshots/final-*.png: both demo conversations typed in Chromium on
// a fresh capture server (Gemini off), the member at 390 px and staff at 1366 px, device scale 2.
// Stops on a transcript that differs from what was typed, a page error, or sideways scrolling.
//
//   PLAYWRIGHT=... node tests/browser/capture/shots.mjs <scratch> [--only <regex>] [--out <dir>]
//
// --only writes just the screenshots whose names match; the whole run is still driven.
import { mkdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { checkConversation, chromium, freshServer, quiet, ROOT, RUNS, signIn } from './common.mjs'

const args = process.argv.slice(2)
const scratch = resolve(args[0] ?? '')
const opt = (name) => { const i = args.indexOf(name); return i > 0 ? args[i + 1] : null }
const only = opt('--only') ? new RegExp(opt('--only')) : null
const OUT = resolve(opt('--out') ?? join(ROOT, 'docs', 'screenshots'))
if (!args[0]) { console.error('usage: shots.mjs <scratch> [--only <regex>] [--out <dir>]'); process.exit(2) }
mkdirSync(OUT, { recursive: true })

const { base: B, logins } = freshServer(scratch)
const browser = await chromium.launch({ args: ['--autoplay-policy=no-user-gesture-required'] })
const problems = []
const watch = (p, who) => {
  p.on('pageerror', (e) => problems.push(`${who}: ${e.message}`))
  p.on('console', (m) => { if (m.type() === 'error') problems.push(`${who}: ${m.text()}`) })
}
async function settle(p, ms = 500) {
  await p.waitForLoadState('networkidle').catch(() => {})
  await p.waitForTimeout(ms)
}
const written = []
async function shot(p, name, opts = {}) {
  if (only && !only.test(name)) return
  await quiet(p, 45000)
  await p.waitForTimeout(200)
  await p.screenshot({ path: join(OUT, `final-${name}.png`), ...opts })
  const over = await p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  if (over > 0) problems.push(`${name}: scrolls sideways by ${over}px`)
  written.push(name)
  console.log('shot', name)
}

const staff = await browser.newContext({ viewport: { width: 1366, height: 768 }, deviceScaleFactor: 2, reducedMotion: 'reduce' })
await signIn(staff, B, 'j.mwangi', logins['j.mwangi'])
const op = await staff.newPage(); watch(op, 'officer')

async function present(convId, name, { height = 768 } = {}) {
  if (only && !only.test(name)) return
  await op.setViewportSize({ width: 1366, height })
  await op.goto(`${B}/#/present/${convId}`)
  await op.getByTestId('present-one').waitFor()
  await settle(op, 1500)       // one poll, and the pipeline's smooth scroll
  await shot(op, name)
}

const pages = {}
for (const run of RUNS) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true,
                                         hasTouch: true, reducedMotion: 'reduce' })
  await signIn(ctx, B, run.login, logins[run.login])
  const p = await ctx.newPage(); watch(p, run.slug)
  const s = (n) => `${run.slug}-${n}`
  await p.goto(`${B}/#/my/chat`)
  await p.getByRole('button', { name: 'English' }).waitFor()
  await settle(p)
  await shot(p, s('01-language'))
  await p.getByRole('button', { name: run.language === 'kik' ? 'Gĩkũyũ' : 'English' }).click()
  await p.waitForURL(/#\/my\/chat\/\d+/)
  const convId = Number(p.url().match(/chat\/(\d+)/)[1])
  const bots = p.getByTestId('bot-bubble')
  await bots.nth(1).waitFor()
  const tap = p.locator('footer button.btn-accent')
  if (await tap.count()) await tap.click()
  await settle(p)
  await shot(p, s('02-consent'))

  const typed = []
  let n = 3
  const next = (label) => s(`${String(n++).padStart(2, '0')}-${label}`)
  for (const [words, want] of run.script) {
    const before = await bots.count()
    const input = p.locator('footer form input')
    await input.fill(words)
    await input.press('Enter')
    typed.push(words)
    await p.waitForFunction((k) => document.querySelectorAll('[data-testid=bot-bubble]').length >= k, before + want.length, { timeout: 60000 })
    await p.waitForFunction(() => !document.querySelector('footer form input')?.disabled
                            || document.querySelector('[data-testid=outcome]'), null, { timeout: 60000 })
    await settle(p, 700)
    await checkConversation(staff, B, convId, typed, want)
    const id = want[0]
    if (id === 'C1') {
      // the answer to R1, its chips open, with the question above it
      await p.getByTestId('member-bubble').last().evaluate((el) => el.scrollIntoView({ block: 'center' }))
      await p.waitForTimeout(300)
      await shot(p, next('r1-chips'))
      await present(convId, `present-${run.slug}-r1-extracted`)
      await p.getByTestId('bot-bubble').last().evaluate((el) => el.scrollIntoView({ block: 'end' }))
      await p.waitForTimeout(300)
      await shot(p, next('c1'))
    } else if (id === 'O1' || id === 'O2') {
      await p.getByTestId('outcome').evaluate((el) => el.scrollIntoView({ block: 'end' }))
      await p.waitForTimeout(300)
      await shot(p, next('outcome'))
      await p.getByTestId('outcome').locator('button.btn-secondary').first().click()
      await p.getByRole('dialog').waitFor()
      await p.waitForTimeout(400)
      await shot(p, next('why'))
      await p.keyboard.press('Escape')
      await present(convId, `present-${run.slug}-paid-out`)
    } else {
      await shot(p, next({ G2: 'g2', G2_NO_INCOME: 'g2', R1: 'r1', C2: 'c2', CONFIRM: 'confirm' }[id]))
      if (id === 'C2') await present(convId, `present-${run.slug}-c2-scored`)
      if (id === 'CONFIRM' && run.slug === 'njeri') {
        await present(convId, `present-${run.slug}-c2-rescored`)
        await present(convId, `present-${run.slug}-c2-rescored-full`, { height: 1100 })
      }
    }
  }
  pages[run.slug] = p
  console.log(run.slug, 'conversation', convId, 'typed and checked:', typed.length, 'answers')
}

// My SACCO for Wanjiru, after the payout
await pages.wanjiru.goto(`${B}/#/my/sacco`)
await settle(pages.wanjiru, 900)
await shot(pages.wanjiru, 'wanjiru-my-sacco', { fullPage: true })

// The officer: automatic decisions, a trace each, the member page
await op.setViewportSize({ width: 1366, height: 768 })
const list = await (await staff.request.get(`${B}/api/automatic-decisions?limit=500`)).json()
await op.goto(`${B}/#/decisions`)
await op.locator('tbody tr').first().waitFor()
await settle(op, 700)
await shot(op, 'decisions-01-list', { fullPage: true })
for (const run of RUNS) {
  await op.goto(`${B}/#/decisions`)
  await op.locator('tbody tr').first().waitFor()
  await op.locator(`a[aria-label="Open the decision on ${run.name}"]`).first().click()
  await op.getByText('Every check the policy ran').waitFor()
  await settle(op, 700)
  await shot(op, `decisions-02-trace-${run.slug}`, { fullPage: true })
}
await op.goto(`${B}/#/members/${list.find((x) => x.member_name === 'Wanjiru Kamau').member_id}`)
await settle(op, 900)
await shot(op, 'officer-member-wanjiru', { fullPage: true })

await browser.close()
console.log(`${written.length} screenshots in ${OUT}`)
if (problems.length) {
  console.error('problems:\n  ' + problems.join('\n  '))
  process.exit(1)
}
