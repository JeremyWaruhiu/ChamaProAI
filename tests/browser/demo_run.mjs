// The demonstration in a real browser: Chromium's fake microphone plays a corpus clip, a
// phone page completes Wanjiru's conversation by voice and Njeri's by typing, and a second
// page follows on the presenter view. Gemini is a stand-in (serve_scratch.py). Writes
// docs/screenshots/chat-*.png and present-*.png, and fails on sideways scrolling or any page error.
//
//   python tests/browser/serve_scratch.py <scratch> 8123 &
//   PLAYWRIGHT=~/.npm/_npx/<hash>/node_modules/playwright node tests/browser/demo_run.mjs <scratch> 8123 <clip.wav>
import { mkdirSync, readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, resolve } from 'node:path'

const [scratch, port, clip] = process.argv.slice(2)
const base = process.env.BASE_URL ?? `http://localhost:${port}`
const { chromium } = createRequire(import.meta.url)(process.env.PLAYWRIGHT)
const logins = JSON.parse(readFileSync(join(scratch, 'logins.json'), 'utf8'))
const shots = resolve('docs/screenshots')
mkdirSync(shots, { recursive: true })

const problems = []
const timings = []
const note = (m) => console.log(m)
const WIDTHS = [360, 390, 430]

function watch(page, name) {
  page.on('pageerror', (e) => problems.push(`${name}: page error: ${e.message}`))
  page.on('console', (m) => {
    if (m.type() === 'error' && !/status of (401|404|409)/.test(m.text())) problems.push(`${name}: console: ${m.text()}`)
  })
}

async function signIn(page, username) {
  await page.goto(`${base}/#/login`)
  await page.getByLabel(/username|phone/i).first().fill(username)
  await page.getByLabel(/password/i).first().fill(logins[username])
  await page.getByRole('button', { name: /sign in/i }).first().click()
  await page.waitForFunction(() => !location.hash.startsWith('#/login'))
}

async function overflow(page, label) {
  const was = page.viewportSize()
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: was.height })
    const bad = await page.evaluate(() => {
      const w = document.documentElement.clientWidth
      const wide = document.documentElement.scrollWidth > w
      const out = [...document.querySelectorAll('body *')].filter((e) => {
        const r = e.getBoundingClientRect()
        return r.width > 0 && !e.closest('[aria-hidden="true"]') && r.right > w + 1 && getComputedStyle(e).position !== 'fixed'
      }).slice(0, 3).map((e) => e.tagName + '.' + e.className)
      return wide || out.length ? { scrollWidth: document.documentElement.scrollWidth, w, out } : null
    })
    if (bad) problems.push(`${label} at ${width}px scrolls sideways: ${JSON.stringify(bad)}`)
  }
  await page.setViewportSize(was)
}

async function shot(page, name, { check = true } = {}) {
  await page.waitForTimeout(250)
  await page.screenshot({ path: join(shots, `${name}.png`) })
  if (check) await overflow(page, name)
  note(`  ${name}`)
}

async function idle(page) {
  await page.waitForFunction(() => !document.querySelector('[data-testid="stages"]'), null, { timeout: 120000 })
  await page.waitForTimeout(150)
}

const lastBot = (page) => page.getByTestId('bot-bubble').last().innerText()

async function expectSaying(page, words) {
  await page.waitForFunction((w) => {
    const all = [...document.querySelectorAll('[data-testid="bot-bubble"]')]
    return all.some((b) => b.innerText.includes(w))
  }, words, { timeout: 120000 })
}

async function hold(page, ms) {
  const box = await page.getByTestId('mic').boundingBox()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down()
  await page.waitForFunction(() => document.querySelector('[data-testid="mic"]')?.getAttribute('aria-pressed') === 'true', null, { timeout: 8000 })
  return async (after) => {
    await page.waitForTimeout(ms)
    if (after) await after()
    const started = Date.now()
    await page.mouse.up()
    return started
  }
}

async function speak(page, ms, label) {
  const release = await hold(page, ms)
  const started = await release()
  await page.waitForFunction(() => document.querySelector('[data-testid="stages"]'), null, { timeout: 5000 }).catch(() => {})
  await idle(page)
  timings.push(`${label}: ${((Date.now() - started) / 1000).toFixed(1)} s from release to the reply on screen`)
}

async function type(page, words, label) {
  const started = Date.now()
  await page.getByLabel('Type your answer').fill(words)
  await page.getByRole('button', { name: 'Send', exact: true }).click()
  await page.waitForFunction(() => !document.querySelector('[data-testid="stages"]'), null, { timeout: 60000 })
  await page.waitForTimeout(150)
  timings.push(`${label}: ${((Date.now() - started) / 1000).toFixed(1)} s, typed`)
}

// As on the day: wait until the server says the Kikuyu model has warmed.
for (let i = 0; ; i++) {
  const health = await fetch(`${base}/api/health`).then((r) => r.json())
  if (health.asr.kik.warmed) break
  if (i > 120) throw new Error('the Kikuyu model never warmed')
  await new Promise((r) => setTimeout(r, 1000))
}

const browser = await chromium.launch({
  args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', `--use-file-for-fake-audio-capture=${clip}`],
})
const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, permissions: ['microphone'], hasTouch: false })
const room = await browser.newContext({ viewport: { width: 1366, height: 768 } })
const member = await phone.newPage()
const present = await room.newPage()
watch(member, 'phone')
watch(present, 'presenter')
const audioHeard = []
member.on('response', (r) => { if (/\/turns\/\d+\/audio/.test(r.url())) audioHeard.push(r.status()) })

await signIn(present, 'j.mwangi')
await present.goto(`${base}/present`)
await present.waitForFunction(() => location.hash === '#/present')
await present.getByTestId('present-list').waitFor()

// --- Wanjiru, by voice, in Kikuyu -------------------------------------------------------------
note('Wanjiru: voice')
await signIn(member, 'w.kamau')
await member.getByRole('link', { name: 'Request a loan' }).waitFor()
await shot(member, 'chat-01-home')
await member.getByRole('link', { name: 'Request a loan' }).click()
await member.getByRole('button', { name: 'Gĩkũyũ' }).waitFor()
await shot(member, 'chat-02-language')
await member.getByRole('button', { name: 'Gĩkũyũ' }).click()
await member.getByRole('button', { name: 'Tap to start' }).waitFor()
await shot(member, 'chat-03-tap-to-start')
await member.getByRole('button', { name: 'Tap to start' }).click()
await member.waitForFunction(() => !document.body.innerText.includes('Tap to start'))
await member.waitForTimeout(600)
if (!audioHeard.includes(200) && !audioHeard.includes(206)) problems.push('no bot audio was fetched after Tap to start')
const playing = await member.evaluate(() => [...document.querySelectorAll('[aria-label="Hear this again"]')].length)
if (playing < 2) problems.push('the opening bot turns have no replay button')
await shot(member, 'chat-04-consent')

await present.getByRole('link', { name: 'Follow Wanjiru Kamau' }).waitFor({ timeout: 8000 })
await shot(present, 'present-01-list', { check: false })
await present.getByRole('link', { name: 'Follow Wanjiru Kamau' }).click()
await present.getByTestId('present-one').waitFor()

const release = await hold(member, 2500)
await member.waitForTimeout(800)
await shot(member, 'chat-05-listening', { check: false })
const started = await release()
await member.waitForFunction(() => /Transcribing|Understanding|Deciding/.test(document.querySelector('[data-testid="stages"] [aria-current="step"]')?.innerText ?? ''), null, { timeout: 8000 })
await member.screenshot({ path: join(shots, 'chat-06-transcribing.png') })
await present.getByTestId('present-working').waitFor({ timeout: 8000 }).catch(() => problems.push('the presenter view never showed the reply being worked on'))
await present.screenshot({ path: join(shots, 'present-02-working.png') })
await idle(member)
timings.push(`CONSENT: ${((Date.now() - started) / 1000).toFixed(1)} s from release to the reply on screen`)
await expectSaying(member, 'let us check your details')
await shot(member, 'chat-07-understood')

await speak(member, 2500, 'G2')
await expectSaying(member, 'How much would you like')
// A reload mid-way carries on where it was.
const before = await member.getByTestId('bot-bubble').count()
await member.reload()
await member.getByTestId('bot-bubble').first().waitFor()
if (await member.getByTestId('bot-bubble').count() !== before) problems.push('a reload lost turns')
await member.getByRole('button', { name: 'Tap to start' }).click()
await shot(member, 'chat-08-after-reload')

await speak(member, 2500, 'R1')
await expectSaying(member, 'Over how many months')
await shot(member, 'chat-09-term')
await present.waitForFunction(() => document.querySelectorAll('[data-testid="present-turn"]').length >= 3, null, { timeout: 8000 })
await shot(present, 'present-03-wanjiru-first-evaluation', { check: false })

await speak(member, 2500, 'C1')
await expectSaying(member, 'You qualify for 40,000')
await shot(member, 'chat-10-confirm')
await speak(member, 2500, 'CONFIRM')
await member.getByTestId('outcome').waitFor()
await member.getByTestId('outcome').scrollIntoViewIfNeeded()
await shot(member, 'chat-11-outcome-approved')
const card = await member.getByTestId('outcome').innerText()
for (const want of ['KSh 40,000', '12 months', 'KSh 3,554', 'Lucy Nduta', 'Before', 'After']) if (!card.includes(want)) problems.push(`the outcome card lacks ${want}: ${card}`)
await member.getByRole('button', { name: 'Why?' }).click()
await member.getByRole('dialog').waitFor()
await shot(member, 'chat-12-why')
const why = await member.getByRole('dialog').innerText()
for (const hidden of ['Low', 'Medium', 'High', 'probab', 'SHAP', 'risk']) if (why.includes(hidden)) problems.push(`the Why? sheet shows ${hidden}: ${why}`)
await member.getByRole('button', { name: 'Close dialog' }).click()
await member.getByRole('button', { name: /Ask an officer/ }).click()
await member.getByText('An officer has been asked to review this.').first().waitFor()
await shot(member, 'chat-13-review-asked')
await present.getByTestId('ledger').getByText('loan_disbursement').waitFor({ timeout: 8000 })
await shot(present, 'present-04-wanjiru-ledger', { check: false })
await member.getByRole('link', { name: 'Go to My SACCO' }).click()
await member.getByText('Transactional').first().waitFor()
await shot(member, 'chat-14-my-sacco')
await member.goto(`${base}/#/my`)
await member.getByRole('button', { name: /Wanjiru|account|Kamau/i }).first().click().catch(() => {})
await member.getByRole('menuitem', { name: /sign out/i }).click()
await member.waitForFunction(() => location.hash.startsWith('#/login'))

// --- Njeri, typed, in English -----------------------------------------------------------------
note('Njeri: typed')
await present.goto(`${base}/#/present`)
await signIn(member, 'n.mwangi')
await member.getByRole('link', { name: 'Request a loan' }).click()
await member.getByRole('button', { name: 'English' }).click()
await member.getByRole('button', { name: 'Tap to start' }).click()
await present.getByRole('link', { name: 'Follow Njeri Mwangi' }).waitFor({ timeout: 8000 })
await present.getByRole('link', { name: 'Follow Njeri Mwangi' }).click()
await present.getByTestId('present-one').waitFor()
await member.getByRole('button', { name: 'Yes', exact: true }).click()
await expectSaying(member, 'people at home and')
if ((await lastBot(member)).includes('shillings')) problems.push('G2 read a stale income out')
await shot(member, 'chat-15-g2-without-income')
await type(member, 'Yes that is correct', 'G2_NO_INCOME')
await expectSaying(member, 'How much would you like')
await type(member, '60,000 for school fees', 'R1 (misread by the stand-in)')
await expectSaying(member, 'Did you say 66,000')
await shot(member, 'chat-16-check-amount')
await member.getByRole('button', { name: 'No', exact: true }).click()
await expectSaying(member, 'did not catch')
await type(member, '60,000 for school fees', 'R1')
await expectSaying(member, 'Over how many months')
await type(member, '12 months', 'C1')
await expectSaying(member, 'Your income on record is 18,000')
await shot(member, 'chat-17-c2')
await present.waitForFunction(() => document.querySelector('[data-testid="risk"]')?.innerText.includes('Medium risk'), null, { timeout: 8000 })
await shot(present, 'present-05-njeri-before-c2', { check: false })
await type(member, 'It is 22,000 now', 'C2')
await expectSaying(member, 'You qualify for 45,000')
await shot(member, 'chat-18-reduced-offer')
await present.waitForFunction(() => document.querySelector('[data-testid="risk"]')?.innerText.includes('Low risk'), null, { timeout: 8000 })
await present.getByTestId('shap-was').first().waitFor()
await shot(present, 'present-06-njeri-after-c2-bars-move', { check: false })
await present.getByRole('button', { name: 'Presentation mode' }).click()
await shot(present, 'present-07-presentation-mode', { check: false })
await member.getByRole('button', { name: 'Yes', exact: true }).click()
await member.getByTestId('outcome').waitFor()
await member.getByTestId('outcome').scrollIntoViewIfNeeded()
await shot(member, 'chat-19-outcome-reduced')
await present.getByTestId('ledger').getByText('loan_disbursement').waitFor({ timeout: 8000 })
await shot(present, 'present-08-njeri-ledger-presentation', { check: false })
await present.setViewportSize({ width: 1920, height: 1080 })
await shot(present, 'present-09-njeri-ledger-1920', { check: false })
await present.getByRole('button', { name: 'Leave presentation mode' }).click()
await shot(present, 'present-10-njeri-1920-with-navigation', { check: false })
const pageWidth = await present.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
if (pageWidth) problems.push('the presenter view scrolls sideways at 1920')
await present.setViewportSize({ width: 1366, height: 768 })
if (await present.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)) problems.push('the presenter view scrolls sideways at 1366')

// --- Rehearsing again, and a referral -----------------------------------------------------------
note('Reset')
const staff = await browser.newContext({ viewport: { width: 1366, height: 768 } })
const admin = await staff.newPage()
watch(admin, 'admin')
await signIn(admin, 's.achieng')
await admin.goto(`${base}/#/present`)
await admin.getByRole('button', { name: 'Reset demo members' }).waitFor()
await shot(admin, 'present-11-reset', { check: false })
await admin.getByRole('button', { name: 'Reset demo members' }).click()
await admin.getByRole('button', { name: 'Reset them' }).click()
await admin.getByText(/Reset: /).first().waitFor()
await admin.getByText('Wanjiru Kamau: 0 open conversations, 0 active loans').waitFor()
await member.goto(`${base}/#/my/chat`)
await member.getByRole('button', { name: 'English' }).click()
await member.getByRole('button', { name: 'Tap to start' }).click()
await member.getByRole('button', { name: 'Yes', exact: true }).click()
await expectSaying(member, 'people at home and')
await type(member, 'yes', 'rehearsal G2')
await type(member, '60,000 for school fees', 'rehearsal R1')
await type(member, '12 months', 'rehearsal C1')
await type(member, 'It is 30,000 now', 'rehearsal C2 too high')
await member.getByTestId('outcome').waitFor()
await member.getByTestId('outcome').scrollIntoViewIfNeeded()
await shot(member, 'chat-20-outcome-referred')
if (!(await member.getByTestId('outcome').innerText()).includes('Book a time')) problems.push('a referral offers no booking')
await member.getByRole('link', { name: /Book a time/ }).click()
await member.getByRole('button', { name: /^book/i }).first().waitFor({ timeout: 8000 })
await member.getByRole('button', { name: /^book/i }).first().scrollIntoViewIfNeeded()
await shot(member, 'chat-21-book-after-referral')

await browser.close()
console.log('\nTimings over HTTP'); timings.forEach((x) => console.log(`  ${x}`))
console.log(`bot audio responses: ${audioHeard.length}, statuses ${[...new Set(audioHeard)].join(', ')}`)
if (problems.length) { console.error('\nPROBLEMS'); problems.forEach((p) => console.error(`  ${p}`)); process.exit(1) }
console.log('\nno sideways scrolling, no page errors')
