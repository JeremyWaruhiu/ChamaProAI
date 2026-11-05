// The phone's path through a real tunnel: one https origin, sign in, the session cookie, the
// microphone, a voice reply and the bot's audio.
//
//   PLAYWRIGHT=<path> node tests/browser/tunnel_check.mjs <https url> <scratch> <clip.wav>
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join } from 'node:path'

const [base, scratch, clip] = process.argv.slice(2)
const { chromium } = createRequire(import.meta.url)(process.env.PLAYWRIGHT)
const logins = JSON.parse(readFileSync(join(scratch, 'logins.json'), 'utf8'))
const browser = await chromium.launch({ args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', `--use-file-for-fake-audio-capture=${clip}`] })
const context = await browser.newContext({ viewport: { width: 390, height: 844 }, permissions: ['microphone'] })
const page = await context.newPage()
const errors = []
page.on('pageerror', (e) => errors.push(e.message))
const audio = []
page.on('response', (r) => { if (/\/turns\/\d+\/audio/.test(r.url())) audio.push(r.status()) })

await page.goto(`${base}/#/login`, { waitUntil: 'domcontentloaded' })
await page.getByLabel(/username/i).first().fill('n.mwangi')
await page.getByLabel(/password/i).first().fill(logins['n.mwangi'])
await page.getByRole('button', { name: /sign in/i }).first().click()
await page.getByRole('link', { name: 'Request a loan' }).waitFor({ timeout: 30000 })
const cookie = (await context.cookies()).find((c) => c.name === 'chamapro_session')
console.log('cookie', { domain: cookie.domain, path: cookie.path, secure: cookie.secure, httpOnly: cookie.httpOnly, sameSite: cookie.sameSite })
if (!cookie.secure || cookie.sameSite !== 'Strict' || !cookie.httpOnly) throw new Error('the cookie is not as it should be')
console.log('secure context', await page.evaluate(() => window.isSecureContext), 'mediaDevices', await page.evaluate(() => Boolean(navigator.mediaDevices)))

await page.getByRole('link', { name: 'Request a loan' }).click()
await page.getByRole('button', { name: 'English' }).click()
const heard = page.waitForResponse((r) => /\/turns\/\d+\/audio/.test(r.url()), { timeout: 30000 })
await page.getByRole('button', { name: 'Tap to start' }).click()
await heard     // pressing the microphone stops the bot, so let it begin first
await page.getByTestId('mic').waitFor()
const box = await page.getByTestId('mic').boundingBox()
await page.mouse.move(box.x + 20, box.y + 20)
await page.mouse.down()
await page.waitForFunction(() => document.querySelector('[data-testid="mic"]')?.getAttribute('aria-pressed') === 'true', null, { timeout: 8000 })
await page.waitForTimeout(2500)
const t0 = Date.now()
await page.mouse.up()
await page.waitForFunction(() => document.querySelectorAll('[data-testid="member-bubble"]').length === 1, null, { timeout: 90000 })
console.log(`voice reply through the tunnel: ${((Date.now() - t0) / 1000).toFixed(1)} s`)
const after = await page.getByTestId('bot-bubble').last().innerText()
console.log('bot said:', after.slice(0, 60))
await page.reload()
await page.getByTestId('member-bubble').waitFor({ timeout: 15000 })
console.log('still signed in after a reload')
console.log('bot audio', [...new Set(audio)], `(${audio.length})`)
await browser.close()
if (errors.length) throw new Error(errors.join('; '))
if (!audio.some((s) => s === 200 || s === 206)) throw new Error('no audio came through')
console.log('ok')
