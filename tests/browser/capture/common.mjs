// What shots.mjs and video.mjs share: the repository, Playwright, and a fresh capture server.
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

export const HERE = dirname(fileURLToPath(import.meta.url))
export const ROOT = resolve(HERE, '../../..')

if (!process.env.PLAYWRIGHT) {
  console.error('set PLAYWRIGHT to a playwright package, e.g. ~/.npm/_npx/<hash>/node_modules/playwright (README.md here)')
  process.exit(2)
}
export const { chromium } = createRequire(import.meta.url)(process.env.PLAYWRIGHT)

/** Rebuild the scratch database from the seed and start its server; its address and logins. */
export function freshServer(scratch, { geminiLive = false } = {}) {
  execFileSync(join(HERE, 'fresh.sh'), [scratch, ...(geminiLive ? ['--gemini-live'] : [])], { stdio: 'inherit' })
  const server = JSON.parse(readFileSync(join(scratch, 'server.json'), 'utf8'))
  if (server.gemini_live !== geminiLive) throw new Error(`the server's Gemini setting is ${server.gemini_live}, not ${geminiLive}`)
  return { base: `http://127.0.0.1:${server.port}`, logins: JSON.parse(readFileSync(join(scratch, 'logins.json'), 'utf8')) }
}

/** The two conversations of scripts/demo_scripts.py the demo uses, as each is typed. */
export const RUNS = [
  { slug: 'wanjiru', name: 'Wanjiru Kamau', who: 'Wanjiru Kamau, English', login: 'w.kamau', language: 'en', script: [
    ['Yes, I agree', ['G2']], ['Yes, that is correct', ['R1']], ['Forty thousand for a dairy cow', ['C1']],
    ['Twelve months', ['CONFIRM']], ['Yes, go ahead', ['O1', 'END']]] },
  { slug: 'njeri', name: 'Njeri Mwangi', who: 'Njeri Mwangi, Gĩkũyũ mode', login: 'n.mwangi', language: 'kik', script: [
    ['Ĩĩ', ['G2_NO_INCOME']], ['Nĩ guo', ['R1']], ['Ngũkwenda ngiri mĩrongo ĩtandatũ cia cukuru', ['C1']],
    ['Mĩeri ikũmi na igĩrĩ', ['C2']], ['Aca, nĩ ngiri mĩrongo ĩĩrĩ na igĩrĩ', ['CONFIRM']], ['Ĩĩ', ['O2', 'END']]] },
]

/** Signs a context in through the API, so no password is typed on screen. */
export async function signIn(ctx, base, username, password) {
  const r = await ctx.request.post(base + '/api/auth/login', { data: { username, password } })
  if (!r.ok()) throw new Error(`${username} sign-in: ${r.status()}`)
}

/** No bot line loading or playing: the bubbles at rest. */
export const quiet = (page, timeout = 60000) => page.waitForFunction(
  () => !document.querySelector('[data-testid=bot-bubble] [role=status], [data-testid=bot-bubble] [class*=replayOn]'),
  null, { timeout })

/** Every member turn's transcript is exactly what was typed, and the bot said what the script expects. */
export async function checkConversation(staff, base, convId, typed, wantSaid = null) {
  const d = await (await staff.request.get(`${base}/api/present/conversations/${convId}`)).json()
  const said = d.turns.filter((x) => x.speaker === 'member').map((m) => m.asr_transcript ?? m.text)
  if (JSON.stringify(said) !== JSON.stringify(typed)) {
    throw new Error(`conversation ${convId}: transcripts differ from what was typed:\n${JSON.stringify(said)}\n${JSON.stringify(typed)}`)
  }
  if (wantSaid) {
    const got = d.turns.filter((x) => x.speaker === 'bot').slice(-wantSaid.length).map((x) => x.template_id)
    if (JSON.stringify(got) !== JSON.stringify(wantSaid)) {
      throw new Error(`conversation ${convId}: after "${typed[typed.length - 1]}" the bot said ${got}, not ${wantSaid}`)
    }
  }
  return d
}
