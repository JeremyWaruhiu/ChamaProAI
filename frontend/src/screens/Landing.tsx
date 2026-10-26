import { m } from 'motion/react'
import type { ReactNode } from 'react'
import { Brand } from '../components/Brand'
import { Icon, type IconName } from '../components/Icon'
import { PipelineHero } from '../components/PipelineHero'
import { homeFor, useAuth } from '../lib/auth'
import { fadeUp, stagger, useReducedMotion } from '../lib/motion'
import { paths } from '../lib/router'
import { t } from '../strings'
import styles from './Landing.module.css'

const L = t.landing

// In-page links scroll rather than change the hash: the hash is the router's.
function jump(id: string, reduced: boolean) {
  const el = document.getElementById(id)
  el?.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' })
  el?.querySelector<HTMLElement>('h2')?.focus({ preventScroll: true })
}

const SECTIONS = [
  { id: 'how', label: L.navHow },
  { id: 'saccos', label: L.navSaccos },
  { id: 'members', label: L.navMembers },
  { id: 'privacy', label: L.navPrivacy },
]

const STEP_ICONS: IconName[] = ['mic', 'wave', 'list', 'scale']
const SACCO_ICONS: IconName[] = ['globe', 'scale', 'scroll', 'sparkle']
const MEMBER_ICONS: IconName[] = ['phone', 'info', 'users']
const PRIVACY_ICONS: IconName[] = ['user', 'lock', 'shield']

export function Landing() {
  const { user } = useAuth()
  const reduced = useReducedMotion()
  const cta = user
    ? <a className="btn btn-primary btn-large" href={homeFor(user.role)}>{L.openApp} <Icon name="arrowRight" /></a>
    : <a className="btn btn-primary btn-large" href={paths.login()}>{L.signIn} <Icon name="arrowRight" /></a>

  return (
    <div className={styles.page}>
      <a className="skip-link" href="#/" onClick={(e) => { e.preventDefault(); document.getElementById('main')?.focus() }}>
        {t.app.skipToContent}
      </a>
      <header className={styles.header}>
        <div className={styles.headerInner}>
          <a href={paths.landing()} className={styles.brandLink}><Brand /></a>
          <nav aria-label={L.navLabel} className={styles.nav}>
            {SECTIONS.map((s) => (
              <button key={s.id} type="button" className={styles.navLink} onClick={() => jump(s.id, reduced)}>{s.label}</button>
            ))}
          </nav>
          <a className="btn btn-primary btn-sm" href={user ? homeFor(user.role) : paths.login()}>
            {user ? L.openApp : L.signIn}
          </a>
        </div>
      </header>

      <main id="main" tabIndex={-1} className={styles.main}>
        <section className={styles.hero} aria-labelledby="hero-title">
          <div className={styles.heroInner}>
            <m.div className={styles.heroText} {...fadeUp(reduced)}>
              <p className={styles.heroEyebrow}>{L.heroEyebrow}</p>
              <h1 id="hero-title" className={`display ${styles.heroTitle}`}>{L.heroTitle}</h1>
              <p className={styles.heroLead}>{L.heroLead}</p>
              <div className={styles.heroActions}>
                {cta}
                <button type="button" className="btn btn-secondary btn-large" onClick={() => jump('how', reduced)}>
                  {L.heroSecondary}
                </button>
              </div>
            </m.div>
            <div className={styles.heroArt}>
              <PipelineHero />
            </div>
          </div>
        </section>

        <Section id="how" eyebrow={L.howEyebrow} title={L.howTitle}>
          <ol className={styles.steps}>
            {L.steps.map((s, i) => (
              <m.li key={s.title} className={styles.step} {...fadeUp(reduced, stagger(reduced, i, 0.08))}>
                <span className={styles.stepNo} aria-hidden>{i + 1}</span>
                <span className={styles.stepIcon}><Icon name={STEP_ICONS[i]} size={22} /></span>
                <h3 className={styles.itemTitle}>{s.title}</h3>
                <p className={styles.itemBody}>{s.body}</p>
              </m.li>
            ))}
          </ol>
        </Section>

        <div className={styles.split}>
          <Section id="saccos" eyebrow={L.saccosEyebrow} title={L.saccosTitle} tone="cream">
            <Features items={L.saccos} icons={SACCO_ICONS} />
          </Section>
          <Section id="members" eyebrow={L.membersEyebrow} title={L.membersTitle} tone="clay">
            <Features items={L.members} icons={MEMBER_ICONS} />
          </Section>
        </div>

        <section id="privacy" className={styles.privacy} aria-labelledby="privacy-title">
          <div className={styles.inner}>
            <p className={styles.privacyEyebrow}>{L.privacyEyebrow}</p>
            <h2 id="privacy-title" tabIndex={-1} className={`display ${styles.privacyTitle}`}>{L.privacyTitle}</h2>
            <p className={styles.privacyLead}>{L.privacyLead}</p>
            <ul className={styles.privacyGrid}>
              {L.privacy.map((p, i) => (
                <li key={p.title} className={styles.privacyItem}>
                  <Icon name={PRIVACY_ICONS[i]} size={22} />
                  <h3 className={styles.itemTitle}>{p.title}</h3>
                  <p>{p.body}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className={styles.cta} aria-labelledby="cta-title">
          <div className={styles.ctaInner}>
            <div>
              <h2 id="cta-title" className={`display ${styles.ctaTitle}`}>{L.ctaTitle}</h2>
              <p className="muted">{L.ctaBody}</p>
            </div>
            {cta}
          </div>
        </section>
      </main>

      <footer className={styles.footer}>
        <div className={styles.inner}>
          <Brand />
          <p className="subtle small">{L.footer}</p>
        </div>
      </footer>
    </div>
  )
}

function Section({ id, eyebrow, title, tone, children }: {
  id: string; eyebrow: string; title: string; tone?: 'cream' | 'clay'; children: ReactNode
}) {
  return (
    <section id={id} className={`${styles.section} ${tone ? styles[tone] : ''}`} aria-labelledby={`${id}-title`}>
      <div className={styles.inner}>
        <p className="eyebrow">{eyebrow}</p>
        <h2 id={`${id}-title`} tabIndex={-1} className={`display ${styles.sectionTitle}`}>{title}</h2>
        {children}
      </div>
    </section>
  )
}

function Features({ items, icons }: { items: { title: string; body: string }[]; icons: IconName[] }) {
  return (
    <ul className={styles.features}>
      {items.map((f, i) => (
        <li key={f.title} className={styles.feature}>
          <span className={styles.featureIcon}><Icon name={icons[i]} size={20} /></span>
          <div>
            <h3 className={styles.itemTitle}>{f.title}</h3>
            <p className={styles.itemBody}>{f.body}</p>
          </div>
        </li>
      ))}
    </ul>
  )
}
