// The backup demo video: each conversation recorded twice over, the member's phone (390x844) and
// /present in presentation mode (960x1080), with when each bot bubble appeared. compose.py then lays
// the cached speech at those moments, adds the caption bar and writes one H.264/AAC mp4.
//
//   PLAYWRIGHT=... node tests/browser/capture/video.mjs <scratch> [--gemini-live] [--out <file.mp4>]
//
// Gemini is off unless --gemini-live, which uses the key in .env and calls Gemini for every answer.
// Every spoken line must already be in data/tts_cache (python scripts/warm_demo.py); the run stops
// on a line that is not, on a transcript that differs from what was typed, or on a bot line the
// script does not expect.
import { execFileSync } from 'node:child_process'
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { checkConversation, chromium, freshServer, HERE, quiet, ROOT, RUNS, signIn } from './common.mjs'

const args = process.argv.slice(2)
if (!args[0]) { console.error('usage: video.mjs <scratch> [--gemini-live] [--out <file.mp4>]'); process.exit(2) }
const scratch = path.resolve(args[0])
const geminiLive = args.includes('--gemini-live')
const outAt = args.indexOf('--out')
const OUT = path.resolve(outAt > 0 ? args[outAt + 1] : path.join(ROOT, 'docs', 'demo', 'backup_demo.mp4'))
const WORK = path.join(scratch, 'video')
const CACHE = path.join(ROOT, 'data', 'tts_cache')
const STEP = { CONSENT: 'Consent', G2: 'Profile check', G2_NO_INCOME: 'Profile check', R1: 'Amount and purpose',
               C1: 'Loan term', C2: 'Income check', CONFIRM: 'Confirm the offer', O1: 'Paid out', O2: 'Paid out' }

const cached = new Map(fs.readdirSync(CACHE).filter((f) => f.endsWith('.mp3'))
  .map((f) => [crypto.createHash('sha256').update(fs.readFileSync(path.join(CACHE, f))).digest('hex'), f]))
const seconds = (file) => Number(execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', file]).toString())
const sleepUntil = async (p, t) => { const d = t - Date.now(); if (d > 0) await p.waitForTimeout(d) }

const { base: B, logins } = freshServer(scratch, { geminiLive })
const browser = await chromium.launch({ args: ['--autoplay-policy=no-user-gesture-required'] })
const errors = []

for (const run of RUNS) {
  const dir = path.join(WORK, run.slug)
  fs.rmSync(dir, { recursive: true, force: true })
  fs.mkdirSync(dir, { recursive: true })
  // Video frames are CSS pixels: record at the viewport's size, scale up when composing.
  const mctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
                                          recordVideo: { dir: path.join(dir, 'member'), size: { width: 390, height: 844 } } })
  const pctx = await browser.newContext({ viewport: { width: 960, height: 1080 },
                                          recordVideo: { dir: path.join(dir, 'present'), size: { width: 960, height: 1080 } } })
  await signIn(mctx, B, run.login, logins[run.login])
  await signIn(pctx, B, 'j.mwangi', logins['j.mwangi'])
  await mctx.addInitScript(() => {
    window.__bubbles = []
    new MutationObserver(() => {
      const n = document.querySelectorAll('[data-testid=bot-bubble]').length
      while (window.__bubbles.length < n) window.__bubbles.push(Date.now())
    }).observe(document, { subtree: true, childList: true })
  })
  const m = await mctx.newPage(); const t0Member = Date.now()
  const p = await pctx.newPage(); const t0Present = Date.now()
  for (const [pg, who] of [[m, 'member'], [p, 'present']]) pg.on('pageerror', (e) => errors.push(`${run.slug} ${who}: ${e.message}`))

  // The officer's laptop waits on its home page: the presenter list would flag the unloaded ASR.
  await p.goto(`${B}/#/app`)
  await p.waitForLoadState('networkidle')
  await m.goto(`${B}/#/my/chat`)
  await m.getByRole('button', { name: 'English' }).waitFor()
  await m.waitForTimeout(600)
  const tReady = Date.now()
  const captions = [{ t: tReady, text: run.who }]
  const audio = []
  let audioEnd = 0
  await m.waitForTimeout(2600)

  await m.getByRole('button', { name: run.language === 'kik' ? 'Gĩkũyũ' : 'English' }).click()
  await m.waitForURL(/#\/my\/chat\/\d+/)
  const convId = Number(m.url().match(/chat\/(\d+)/)[1])
  await m.getByTestId('bot-bubble').nth(1).waitFor()
  await m.waitForTimeout(700)
  const tap = m.locator('footer button.btn-accent')
  const tTap = Date.now()
  if (await tap.count()) await tap.click()
  await p.goto(`${B}/#/present/${convId}`)
  await p.getByTestId('present-one').waitFor()
  await p.getByRole('button', { name: /Presentation mode/ }).click()

  /** The bot lines shown since `from`: their audio fetched, found in data/tts_cache, and scheduled
   *  when the bubble appeared, or after the line before it if that is still speaking. */
  async function collect(from, ids, notBefore = 0) {
    const times = await m.evaluate(() => window.__bubbles)
    const d = await (await mctx.request.get(`${B}/api/conversations/${convId}`)).json()
    const bots = d.turns.filter((x) => x.speaker === 'bot')
    for (let i = from; i < bots.length; i++) {
      const t = bots[i]
      if (!t.audio_url) throw new Error(`${run.slug}: turn ${t.seq} has no speech`)
      const body = await (await mctx.request.get(B + t.audio_url)).body()
      const hash = crypto.createHash('sha256').update(body).digest('hex')
      if (!cached.has(hash)) throw new Error(`${run.slug}: "${t.text}" is not in data/tts_cache; run python scripts/warm_demo.py`)
      const file = path.join(CACHE, cached.get(hash))
      const start = Math.max(times[i], notBefore, audioEnd)
      const dur = seconds(file)
      audioEnd = start + dur * 1000
      audio.push({ file, start, dur, text: t.text })
    }
    return { shownAt: Math.max(times[times.length - 1], notBefore), id: ids.find((x) => STEP[x]) }
  }
  const opening = await collect(0, ['CONSENT'], tTap)
  captions.push({ t: opening.shownAt, text: `${run.who}  ·  Consent` })

  const typed = []
  let pendingCaption = null
  for (const [words, want] of run.script) {
    await quiet(m)
    await sleepUntil(m, audioEnd + 1200)
    if (pendingCaption) { captions.push({ t: Date.now(), text: `${run.who}  ·  ${pendingCaption}` }); pendingCaption = null }
    const before = await m.getByTestId('bot-bubble').count()
    const input = m.locator('footer form input')
    await input.pressSequentially(words, { delay: 70 })
    await m.waitForTimeout(500)
    await input.press('Enter')
    typed.push(words)
    await m.waitForFunction((k) => document.querySelectorAll('[data-testid=bot-bubble]').length >= k, before + want.length, { timeout: 90000 })
    await m.waitForTimeout(50)
    await checkConversation(pctx, B, convId, typed, want)
    const got = await collect(before, want)
    if (want[0] === 'CONFIRM' && run.slug === 'njeri') {
      captions.push({ t: got.shownAt, text: `${run.who}  ·  Income update rescored` })
      pendingCaption = STEP.CONFIRM
    } else if (got.id) captions.push({ t: got.shownAt, text: `${run.who}  ·  ${STEP[got.id]}` })
  }

  // The outcome, then the member's reasons
  await quiet(m)
  await sleepUntil(m, audioEnd + 1500)
  await m.getByTestId('outcome').evaluate((el) => el.scrollIntoView({ block: 'end', behavior: 'smooth' }))
  await m.waitForTimeout(3500)
  const tWhy = Date.now()
  await m.getByTestId('outcome').locator('button.btn-secondary').first().click()
  captions.push({ t: tWhy, text: `${run.who}  ·  Paid out: why, in the member's words` })
  await m.getByRole('dialog').waitFor()
  await m.waitForTimeout(6500)
  await m.keyboard.press('Escape')
  await m.waitForTimeout(2500)
  const tEnd = Date.now()

  const memberVideo = m.video(), presentVideo = p.video()
  await mctx.close(); await pctx.close()
  fs.writeFileSync(path.join(dir, 'timeline.json'), JSON.stringify({
    slug: run.slug, t0Member, t0Present, tReady, tEnd, memberVideo: await memberVideo.path(),
    presentVideo: await presentVideo.path(), audio, captions }, null, 2))
  console.log(run.slug, `conversation ${convId}: ${((tEnd - tReady) / 1000).toFixed(1)} s, ${audio.length} lines spoken`)
}
await browser.close()
if (errors.length) { console.error('page errors:\n  ' + errors.join('\n  ')); process.exit(1) }

execFileSync('python3', ['-I', path.join(HERE, 'compose.py'), WORK, OUT, ...RUNS.map((r) => r.slug)], { stdio: 'inherit' })
