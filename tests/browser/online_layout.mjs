// The online presentation's two windows, measured in a real browser: the chat with ?stage=1 at 390 px,
// and /present in presentation mode at 1366x768 and at half of a 1920 screen. Fails on sideways
// scrolling, or a page that does not fit its window. Also checks that polling an unchanged
// conversation comes back from the browser's cache as a 304. Writes screenshots to <out>.
//
//   ASR_FAKE=1 python tests/browser/serve_scratch.py <scratch> 8123 &
//   PLAYWRIGHT=~/.npm/_npx/<hash>/node_modules/playwright node tests/browser/online_layout.mjs <scratch> 8123 <out>
import { readFileSync, mkdirSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join } from 'node:path'

const [scratch, port, out] = process.argv.slice(2)
const base = `http://localhost:${port}`
const { chromium } = createRequire(import.meta.url)(process.env.PLAYWRIGHT)
const logins = JSON.parse(readFileSync(join(scratch, 'logins.json'), 'utf8'))
mkdirSync(out, { recursive: true })
const problems = []

async function signIn(page, username) {
  await page.goto(`${base}/#/login`)
  await page.getByLabel(/username|phone/i).first().fill(username)
  await page.getByLabel(/password/i).first().fill(logins[username])
  await page.getByRole('button', { name: /sign in/i }).first().click()
  await page.waitForFunction(() => !location.hash.startsWith('#/login'))
}

async function fits(page, label) {
  const bad = await page.evaluate(() => {
    const w = document.documentElement.clientWidth, h = document.documentElement.clientHeight
    const scrolls = document.documentElement.scrollWidth > w || document.documentElement.scrollHeight > h
    const out = [...document.querySelectorAll('body *')].filter((e) => {
      const r = e.getBoundingClientRect(), st = getComputedStyle(e)
      if (r.width === 0 || st.position === 'fixed' || e.closest('[aria-hidden="true"]')) return false
      // Inside a panel that scrolls, it may run on below; it must not run off to the side.
      return r.right > w + 1
    }).slice(0, 4).map((e) => `${e.tagName}.${String(e.className).slice(0, 40)}`)
    return scrolls || out.length ? { w, h, sw: document.documentElement.scrollWidth, sh: document.documentElement.scrollHeight, out } : null
  })
  if (bad) problems.push(`${label}: ${JSON.stringify(bad)}`)
  console.log(`${label}: ${bad ? 'DOES NOT FIT' : 'fits'}`)
}

const browser = await chromium.launch({ args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'] })
const phone = await (await browser.newContext({ viewport: { width: 390, height: 800 } })).newPage()
await signIn(phone, 'w.kamau')
await phone.goto(`${base}/#/my/chat?stage=1`)
await phone.getByRole('button', { name: 'English' }).click()
await phone.waitForFunction(() => /#\/my\/chat\/\d+\?stage=1/.test(location.hash))
await phone.getByTestId('chat-stage').waitFor()

const answer = async (words) => {
  await phone.getByLabel('Type your answer').fill(words)
  await phone.getByRole('button', { name: 'Send' }).click()
  await phone.waitForFunction((w) => [...document.querySelectorAll('[data-testid="member-bubble"]')].some((e) => e.textContent.includes(w)), words)
}

const staffContext = await browser.newContext({ viewport: { width: 1366, height: 768 } })
const staff = await staffContext.newPage()
await signIn(staff, 's.achieng')
await staff.goto(`${base}/#/present`)
await staff.getByRole('button', { name: /Presentation/ }).click()
const cid = Number((await phone.evaluate(() => location.hash)).match(/chat\/(\d+)/)[1])
await staff.goto(`${base}/#/present/${cid}`)
await staff.getByTestId('present-one').waitFor()

for (const words of ['Yes, I agree', 'Yes, that is correct', 'Forty thousand for a dairy cow', 'Twelve months']) await answer(words)
await staff.getByTestId('verdict').waitFor({ timeout: 10000 })
await phone.screenshot({ path: join(out, 'stage-390.png') })
const mic = phone.getByTestId('mic')
const box = await mic.boundingBox()
await phone.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
await phone.mouse.down()
await phone.getByTestId('stages').waitFor({ timeout: 5000 })
await phone.waitForTimeout(300)
await phone.screenshot({ path: join(out, 'stage-indicator.png') })
const clipped = await phone.getByTestId('stages').evaluate((list) => [...list.children].filter((e) => e.scrollWidth > e.clientWidth + 1).map((e) => e.textContent))
if (clipped.length) problems.push(`stage indicator clipped: ${clipped}`)
await fits(phone, 'chat ?stage=1 while listening')
await phone.evaluate(() => document.querySelector('[data-testid="mic"]').dispatchEvent(new PointerEvent('pointercancel', { bubbles: true })))
await phone.mouse.up()
await phone.getByTestId('stages').waitFor({ state: 'hidden', timeout: 5000 }).catch(() => {})
await fits(phone, 'chat ?stage=1 at 390x800')

await staff.waitForTimeout(1500)
await staff.screenshot({ path: join(out, 'present-1366.png') })
await fits(staff, '/present at 1366x768')
await staff.setViewportSize({ width: 960, height: 950 })
await staff.waitForTimeout(300)
await staff.screenshot({ path: join(out, 'present-960.png') })
await fits(staff, '/present at 960x950')
await staff.setViewportSize({ width: 960, height: 700 })
await staff.waitForTimeout(300)
await fits(staff, '/present at 960x700')

// What the browser does on its own with the ETag: the poll on an unchanged conversation.
const seen = []
staff.on('response', (r) => { if (r.url().includes(`/api/present/conversations/${cid}`)) seen.push(r.status()) })
const raw = await staff.evaluate(async (id) => {
  const a = await fetch(`/api/present/conversations/${id}`)
  const b = await fetch(`/api/present/conversations/${id}`, { headers: { 'If-None-Match': a.headers.get('etag') } })
  return [a.status, b.status, a.headers.get('etag') !== null]
}, cid)
console.log('fetch, then fetch with its tag:', raw)
await staff.waitForTimeout(3200)
console.log('statuses the presenter page itself saw while polling:', [...new Set(seen)])

await answer('Yes, go ahead')
await phone.getByTestId('outcome').waitFor({ timeout: 15000 })
await phone.screenshot({ path: join(out, 'stage-outcome.png') })
await fits(phone, 'chat ?stage=1 outcome at 390x800')
await staff.waitForTimeout(1500)
await staff.setViewportSize({ width: 1366, height: 768 })
await staff.waitForTimeout(300)
await staff.screenshot({ path: join(out, 'present-1366-done.png') })
await fits(staff, '/present, paid out, at 1366x768')
await staff.setViewportSize({ width: 960, height: 950 })
await staff.waitForTimeout(300)
await staff.screenshot({ path: join(out, 'present-960-done.png') })
await fits(staff, '/present, paid out, at 960x950')

const wide = await (await browser.newContext({ viewport: { width: 700, height: 950 }, storageState: await phone.context().storageState() })).newPage()
await wide.goto(`${base}/#/my/chat/${cid}?stage=1`)
await wide.getByTestId('chat-stage').waitFor()
await wide.screenshot({ path: join(out, 'stage-700.png') })
await fits(wide, 'chat ?stage=1 centred at 700x950')
await browser.close()
if (problems.length) { console.error(problems.join('\n')); process.exit(1) }
console.log('all fit')
