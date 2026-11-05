import type { ConversationDetail, Language, MemberExplain, ServerStage, Turn } from '../api/types'
import { t } from '../strings'
import type { ChatStrings } from './chatStrings'

// --- What a reply is doing -------------------------------------------------------------------

export type Stage = 'listening' | 'transcribing' | 'understanding' | 'deciding'

export const VOICE_STAGES: Stage[] = ['listening', 'transcribing', 'understanding', 'deciding']
export const TEXT_STAGES: Stage[] = ['understanding', 'deciding']

/** The server's stage as the member's four. Speech comes with the decision: they are waiting for one answer. */
export function memberStage(stage: ServerStage | null): Stage | null {
  return stage === 'speaking' ? 'deciding' : stage
}

/** A poll that arrives late never moves the indicator backwards. */
export function laterStage(stages: Stage[], current: Stage | null, next: Stage | null): Stage | null {
  if (!next) return current
  return current && stages.indexOf(next) < stages.indexOf(current) ? current : next
}

// --- Answers that can be tapped ---------------------------------------------------------------

const TAPPABLE = new Set(['CHECK_AMOUNT', 'CONSENT', 'CONFIRM'])

/** The label is whatever has been translated. What goes to the server stays the word lexicon.py reads. */
export function quickReplies(state: string, language: Language, C: ChatStrings = t.chat): { label: string; send: string }[] {
  if (!TAPPABLE.has(state)) return []
  return [{ label: C.yes[language], send: t.chat.yes[language] }, { label: C.no[language], send: t.chat.no[language] }]
}

// --- What was understood ----------------------------------------------------------------------

const money = (v: unknown) => t.common.ksh(Number(v))
const ORDER = ['answer', 'amount_kes', 'purpose_text', 'term_months', 'monthly_income_kes', 'expected_monthly_return_kes',
  'chama_loan_active', 'chama_instalment_kes', 'household_size', 'children']

function chipValue(key: string, value: unknown, C: ChatStrings): string {
  switch (key) {
    case 'amount_kes': case 'monthly_income_kes': case 'expected_monthly_return_kes': case 'chama_instalment_kes':
      return money(value)
    case 'term_months': return C.months(Number(value))
    case 'answer': return value === 'yes' ? C.answerYes : C.answerNo
    case 'chama_loan_active': return value ? C.answerYes : C.answerNo
    default: return String(value)
  }
}

export interface Chip { key: string; label: string; value: string }

/** "Amount: KSh 40,000", from what the machine acted on. A correction at G2 is shown as its own fields. */
export function understood(used: Record<string, unknown> | null | undefined, C: ChatStrings = t.chat): Chip[] {
  if (!used) return []
  const flat: Record<string, unknown> = { ...used, ...((used.corrections as Record<string, unknown> | undefined) ?? {}) }
  return ORDER.filter((k) => flat[k] !== undefined && flat[k] !== null)
    .map((k) => ({ key: k, label: C.chip[k], value: chipValue(k, flat[k], C) }))
}

// --- Reading a conversation --------------------------------------------------------------------

/** The bot turns since the member last spoke: what they have not yet heard after a reload. */
export function lastBotTurns(turns: Turn[]): Turn[] {
  const i = turns.map((x) => x.speaker).lastIndexOf('member')
  return turns.slice(i + 1).filter((x) => x.speaker === 'bot')
}

export function latestExplain(turns: Turn[]): MemberExplain | null {
  for (let i = turns.length - 1; i >= 0; i--) {
    if (turns[i].explain) return turns[i].explain
  }
  return null
}

export function closingActions(detail: Pick<ConversationDetail, 'turns'>) {
  return detail.turns.flatMap((x) => x.actions)
}
