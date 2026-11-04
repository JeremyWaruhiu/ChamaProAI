import type { EventType, SaccoEvent } from '../api/types'
import { t } from '../strings'
import { nairobiDay, nairobiTime } from './nairobi'

// The event form: its draft and what stops it being saved.

const E = t.events

export type EventDraft = { title: string; event_type: EventType; date: string; time: string; location: string; online_link: string; description: string }

export function draftOf(e: SaccoEvent | null): EventDraft {
  return e
    ? { title: e.title, event_type: e.event_type, date: nairobiDay(e.starts_at), time: nairobiTime(e.starts_at),
        location: e.location ?? '', online_link: e.online_link ?? '', description: e.description ?? '' }
    : { title: '', event_type: 'member_meeting', date: '', time: '', location: '', online_link: '', description: '' }
}

export function eventErrors(d: EventDraft): Partial<Record<keyof EventDraft, string>> {
  const X = E.errors
  const out: Partial<Record<keyof EventDraft, string>> = {}
  if (!d.title.trim()) out.title = X.title
  if (!d.date) out.date = X.date
  if (!d.time) out.time = X.time
  if (d.online_link.trim() && !/^https?:\/\/\S+$/i.test(d.online_link.trim())) out.online_link = X.link
  return out
}
