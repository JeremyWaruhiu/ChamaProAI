import { createContext, useContext } from 'react'
import { t } from '../strings'
import kikuyu from '../strings.kik.json'
import type { Language } from '../api/types'

export type ChatStrings = typeof t.chat

const filled = kikuyu as Record<string, string>

/** t.chat with whatever has been translated in place of the English, leaf by leaf. Ids are as in
 * translations/kikuyu.csv, and a row left empty there stays in English. */
function translated<T>(english: T, path: string): T {
  if (typeof english === 'string') return (filled[path] || english) as T
  if (typeof english !== 'object' || english === null) return english
  return Object.fromEntries(Object.entries(english).map(([k, v]) => [k, translated(v, `${path}.${k}`)])) as T
}

function kikuyuChat(): ChatStrings {
  const months = (n: number) => (n === 1 ? filled['chat.months.one'] : filled['chat.months.many'])?.replace('{n}', String(n))
    ?? t.chat.months(n)
  return {
    ...translated(t.chat, 'chat'),
    months,
    // Each language's own word, whichever the screen is in; the Kikuyu ones may have been reworded.
    yes: { ...t.chat.yes, kik: filled['button.yes'] || t.chat.yes.kik },
    no: { ...t.chat.no, kik: filled['button.no'] || t.chat.no.kik },
  }
}

const KIKUYU = kikuyuChat()

export function chatStrings(language: Language | null | undefined): ChatStrings {
  return language === 'kik' ? KIKUYU : t.chat
}

export const ChatText = createContext<ChatStrings>(t.chat)
export const useChatText = () => useContext(ChatText)
