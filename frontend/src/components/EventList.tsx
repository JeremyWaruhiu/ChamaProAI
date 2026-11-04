import type { ReactNode } from 'react'
import type { SaccoEvent } from '../api/types'
import { formatNairobi } from '../lib/nairobi'
import { t } from '../strings'
import { Icon } from './Icon'
import { Badge } from './ui'
import styles from './EventList.module.css'

const E = t.events

/** Upcoming events as members and officers read them; `actions` adds staff's buttons. */
export function EventList({ events, actions }: { events: SaccoEvent[]; actions?: (e: SaccoEvent) => ReactNode }) {
  return (
    <ul className={styles.list}>
      {events.map((e) => (
        <li key={e.id} className={styles.item}>
          <div className={styles.top}>
            <p className={styles.title}>{e.title}</p>
            <Badge tone="info">{E.types[e.event_type] ?? e.event_type}</Badge>
          </div>
          <p className={styles.line}><Icon name="clock" size={16} /> {formatNairobi(e.starts_at)}</p>
          {e.location && <p className={styles.line}><Icon name="home" size={16} /> {e.location}</p>}
          {e.online_link && (
            <p className={styles.line}><Icon name="globe" size={16} /> <a href={e.online_link} target="_blank" rel="noreferrer noopener">{E.join}</a></p>
          )}
          {e.description && <p className="muted small">{e.description}</p>}
          {actions && <div className={styles.actions}>{actions(e)}</div>}
        </li>
      ))}
    </ul>
  )
}
