import { AnimatePresence, m } from 'motion/react'
import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { api } from '../api/client'
import type { ApplicationSummary, Me, Member } from '../api/types'
import { ROLE_LABEL, useAuth } from '../lib/auth'
import { fade, useReducedMotion } from '../lib/motion'
import { navigate, paths, type Screen } from '../lib/router'
import { matchApplications } from '../lib/selectors'
import { t } from '../strings'
import { Brand } from './Brand'
import { Icon, type IconName } from './Icon'
import styles from './Layout.module.css'
import { cx } from '../lib/cx'
import { Badge } from './ui'

// --- Navigation ------------------------------------------------------------------

interface NavItem { key: string; label: string; href: string; icon: IconName; screens: Screen[] }

const WORK: NavItem[] = [
  { key: 'home', label: t.nav.home, href: paths.home(), icon: 'home', screens: ['home'] },
  { key: 'interviews', label: t.nav.interviews, href: paths.interviews(), icon: 'mic', screens: ['interviews', 'record', 'review', 'assessment'] },
  { key: 'applications', label: t.nav.applications, href: paths.applications(), icon: 'file', screens: ['applications', 'application'] },
  { key: 'members', label: t.nav.members, href: paths.members(), icon: 'users', screens: ['members', 'member'] },
]
const ADMIN: NavItem[] = [
  { key: 'admin', label: t.nav.adminHome, href: paths.admin(), icon: 'overview', screens: ['admin'] },
  { key: 'users', label: t.nav.users, href: paths.users(), icon: 'user', screens: ['users'] },
  { key: 'audit', label: t.nav.audit, href: paths.audit(), icon: 'scroll', screens: ['audit'] },
  { key: 'results', label: t.nav.results, href: paths.results(), icon: 'chart', screens: ['results'] },
]

const COLLAPSE_KEY = 'chamapro.nav.collapsed'
function readCollapsed(): boolean {
  try { return window.localStorage.getItem(COLLAPSE_KEY) === '1' } catch { return false }
}
function writeCollapsed(v: boolean) {
  try { window.localStorage.setItem(COLLAPSE_KEY, v ? '1' : '0') } catch { /* private mode: not remembered */ }
}

function NavList({ items, screen, collapsed, onNavigate }: {
  items: NavItem[]; screen: Screen; collapsed: boolean; onNavigate?: () => void
}) {
  return (
    <ul className={styles.navList}>
      {items.map((it) => {
        const active = it.screens.includes(screen)
        return (
          <li key={it.key}>
            <a href={it.href} className={cx(styles.navLink, active && styles.navActive)}
               aria-current={active ? 'page' : undefined} title={collapsed ? it.label : undefined}
               onClick={onNavigate}>
              <Icon name={it.icon} />
              <span className={collapsed ? 'visually-hidden' : styles.navLabel}>{it.label}</span>
            </a>
          </li>
        )
      })}
    </ul>
  )
}

function Sidebar({ user, screen, collapsed, onToggle, onNavigate, drawer = false }: {
  user: Me; screen: Screen; collapsed: boolean; onToggle?: () => void; onNavigate?: () => void; drawer?: boolean
}) {
  return (
    <div className={cx(styles.sidebarInner, collapsed && styles.collapsed)}>
      <div className={styles.sidebarTop}>
        <a href={paths.home()} className={styles.sidebarBrand} onClick={onNavigate}>
          <Brand compact={collapsed} onDark />
        </a>
      </div>
      <nav aria-label={t.nav.main} className={styles.nav}>
        <a href={paths.start()} className={cx('btn btn-accent', styles.startBtn, screen === 'start' && styles.startActive)}
           aria-current={screen === 'start' ? 'page' : undefined} title={collapsed ? t.nav.startInterview : undefined}
           onClick={onNavigate}>
          <Icon name="mic" />
          <span className={collapsed ? 'visually-hidden' : undefined}>{t.nav.startInterview}</span>
        </a>
        <p className={cx(styles.navHeading, collapsed && 'visually-hidden')}>{t.nav.work}</p>
        <NavList items={WORK} screen={screen} collapsed={collapsed} onNavigate={onNavigate} />
        {user.role === 'admin' && (
          <>
            <p className={cx(styles.navHeading, collapsed && 'visually-hidden')}>{t.nav.admin}</p>
            <NavList items={ADMIN} screen={screen} collapsed={collapsed} onNavigate={onNavigate} />
          </>
        )}
      </nav>
      {!drawer && onToggle && (
        <button type="button" className={styles.collapseBtn} onClick={onToggle}
                aria-label={collapsed ? t.nav.expand : t.nav.collapse} aria-expanded={!collapsed}>
          <Icon name={collapsed ? 'chevronRight' : 'chevronLeft'} />
          <span className={collapsed ? 'visually-hidden' : undefined}>{collapsed ? t.nav.expand : t.nav.collapse}</span>
        </button>
      )}
    </div>
  )
}

// --- Search -----------------------------------------------------------------------------

type Hit = { id: string; label: string; meta: string; href: string; group: 'members' | 'applications' }

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const id = window.setTimeout(() => setV(value), ms)
    return () => window.clearTimeout(id)
  }, [value, ms])
  return v
}

function SearchBox() {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const [members, setMembers] = useState<Member[]>([])
  const [loading, setLoading] = useState(false)
  const apps = useRef<ApplicationSummary[] | null>(null)
  const [appHits, setAppHits] = useState<ApplicationSummary[]>([])
  const debounced = useDebounced(q, 250)
  const listId = useId()
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const term = debounced.trim()
    // oxlint-disable-next-line react/set-state-in-effect -- clear the results as soon as the search is too short
    if (term.length < 2) { setMembers([]); setAppHits([]); return }
    let live = true
    setLoading(true)
    const loadApps = apps.current ? Promise.resolve(apps.current)
      : api.applications({ limit: 500 }).then((a) => (apps.current = a)).catch(() => [])
    Promise.all([api.members(term, 6).catch(() => []), loadApps]).then(([m, a]) => {
      if (!live) return
      setMembers(m)
      setAppHits(matchApplications(a, term))
      setActive(0)
      setLoading(false)
    })
    return () => { live = false }
  }, [debounced])

  useEffect(() => {
    const close = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  const hits: Hit[] = [
    ...members.map((m) => ({ id: `m${m.id}`, label: m.full_name, meta: m.member_no, href: paths.member(m.id), group: 'members' as const })),
    ...appHits.map((a) => ({ id: `a${a.id}`, label: t.topbar.application(a.id, a.member_name), meta: t.appStatus[a.status],
      href: paths.application(a.id), group: 'applications' as const })),
  ]
  const show = open && q.trim().length >= 2

  function go(h: Hit) {
    setOpen(false)
    setQ('')
    navigate(h.href)
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Escape') { setOpen(false); return }
    if (!hits.length) return
    if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); setActive((i) => (i + 1) % hits.length) }
    if (e.key === 'ArrowUp') { e.preventDefault(); setActive((i) => (i - 1 + hits.length) % hits.length) }
    if (e.key === 'Enter' && show) { e.preventDefault(); go(hits[active]) }
  }

  return (
    <div className={styles.search} ref={box}>
      <Icon name="search" className={styles.searchIcon} />
      <input className={styles.searchInput} type="search" value={q} placeholder={t.topbar.searchPlaceholder}
             aria-label={t.topbar.searchLabel} role="combobox" aria-expanded={show} aria-controls={listId}
             aria-autocomplete="list" aria-activedescendant={show && hits[active] ? `${listId}-${hits[active].id}` : undefined}
             onChange={(e) => { setQ(e.target.value); setOpen(true) }} onFocus={() => setOpen(true)} onKeyDown={onKey} />
      {show && (
        <div className={styles.searchPanel}>
          <ul id={listId} role="listbox" aria-label={t.topbar.searchLabel} className={styles.searchList}>
            {hits.map((h, i) => (
              <li key={h.id} id={`${listId}-${h.id}`} role="option" aria-selected={i === active}
                  className={cx(styles.searchHit, i === active && styles.searchActive)}
                  onMouseDown={(e) => { e.preventDefault(); go(h) }} onMouseEnter={() => setActive(i)}>
                <Icon name={h.group === 'members' ? 'user' : 'file'} size={18} />
                <span className={styles.hitLabel}>{h.label}</span>
                <span className={styles.hitMeta}>{h.meta}</span>
              </li>
            ))}
          </ul>
          {!hits.length && (
            <p className={styles.searchEmpty} role="status">
              {loading ? t.topbar.searching : t.topbar.noResults(q.trim())}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

// --- User menu ---------------------------------------------------------------------------

export function UserMenu({ user, onDark = false }: { user: Me; onDark?: boolean }) {
  const { signOut } = useAuth()
  const [open, setOpen] = useState(false)
  const menu = useRef<HTMLDivElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const menuId = useId()
  const reduced = useReducedMotion()

  const close = useCallback((focusButton = false) => {
    setOpen(false)
    if (focusButton) button.current?.focus()
  }, [])

  useEffect(() => {
    if (!open) return
    menu.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus()
    const onDown = (e: MouseEvent) => {
      if (!menu.current?.contains(e.target as Node) && !button.current?.contains(e.target as Node)) close()
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open, close])

  function onKey(e: KeyboardEvent<HTMLDivElement>) {
    const items = [...(menu.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])]
    const i = items.indexOf(document.activeElement as HTMLElement)
    if (e.key === 'Escape') { e.preventDefault(); close(true) }
    if (e.key === 'ArrowDown') { e.preventDefault(); items[(i + 1) % items.length]?.focus() }
    if (e.key === 'ArrowUp') { e.preventDefault(); items[(i - 1 + items.length) % items.length]?.focus() }
    if (e.key === 'Tab') close()
  }

  return (
    <div className={styles.userMenu}>
      <button ref={button} type="button" className={cx(styles.userButton, onDark && styles.userOnDark)}
              aria-haspopup="menu" aria-expanded={open} aria-controls={open ? menuId : undefined}
              aria-label={t.topbar.userMenu(user.username)} onClick={() => setOpen((v) => !v)}>
        <span className={styles.avatar} aria-hidden>{user.username.slice(0, 1).toUpperCase()}</span>
        <span className={styles.userText}>
          <span className={styles.userName}>{user.username}</span>
          <span className={styles.userRole}>{ROLE_LABEL[user.role]}</span>
        </span>
        <Icon name="chevronDown" size={16} />
      </button>
      <AnimatePresence>
        {open && (
          <m.div ref={menu} id={menuId} role="menu" className={styles.menu} onKeyDown={onKey} {...fade(reduced)}>
            <p className={styles.menuHead}>
              <span className="subtle small">{t.topbar.signedInAs}</span>
              <strong>{user.username}</strong>
              <Badge tone={user.role === 'admin' ? 'attention' : user.role === 'member' ? 'info' : 'low'}>{ROLE_LABEL[user.role]}</Badge>
            </p>
            <a role="menuitem" href={paths.profile()} className={styles.menuItem} onClick={() => close()}>
              <Icon name="user" size={18} /> {t.common.profile}
            </a>
            <button role="menuitem" type="button" className={styles.menuItem} onClick={() => { close(); signOut() }}>
              <Icon name="logout" size={18} /> {t.common.signOut}
            </button>
          </m.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// --- Staff layout -------------------------------------------------------------------------

export function StaffLayout({ user, screen, children }: { user: Me; screen: Screen; children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const [drawer, setDrawer] = useState(false)
  const reduced = useReducedMotion()
  const drawerRef = useRef<HTMLDivElement>(null)
  const menuButton = useRef<HTMLButtonElement>(null)

  const toggle = () => setCollapsed((c) => { writeCollapsed(!c); return !c })

  useEffect(() => {
    if (!drawer) return
    drawerRef.current?.querySelector<HTMLElement>('a, button')?.focus()
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') { setDrawer(false); menuButton.current?.focus() }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [drawer])

  return (
    <div className={cx(styles.staff, collapsed && styles.staffCollapsed)}>
      <a className="skip-link" href="#main" onClick={(e) => { e.preventDefault(); document.getElementById('main')?.focus() }}>
        {t.app.skipToContent}
      </a>
      <aside className={styles.sidebar}>
        <Sidebar user={user} screen={screen} collapsed={collapsed} onToggle={toggle} />
      </aside>

      <AnimatePresence>
        {drawer && (
          <m.div className={styles.drawerOverlay} {...fade(reduced)}
                      onMouseDown={(e) => { if (e.target === e.currentTarget) setDrawer(false) }}>
            <m.div ref={drawerRef} className={styles.drawer} role="dialog" aria-modal="true" aria-label={t.nav.main}
                        initial={reduced ? false : { x: -24, opacity: 0 }} animate={{ x: 0, opacity: 1 }}
                        exit={reduced ? undefined : { x: -24, opacity: 0 }} transition={{ duration: reduced ? 0 : 0.2 }}>
              <button type="button" className={styles.drawerClose} onClick={() => setDrawer(false)} aria-label={t.nav.closeMenu}>
                <Icon name="x" />
              </button>
              <Sidebar user={user} screen={screen} collapsed={false} drawer onNavigate={() => setDrawer(false)} />
            </m.div>
          </m.div>
        )}
      </AnimatePresence>

      <div className={styles.column}>
        <header className={styles.topbar}>
          <button ref={menuButton} type="button" className={styles.menuButton} onClick={() => setDrawer(true)}
                  aria-label={t.nav.openMenu} aria-expanded={drawer}>
            <Icon name="menu" />
          </button>
          <SearchBox />
          <UserMenu user={user} />
        </header>
        <main id="main" tabIndex={-1} className={styles.main}>{children}</main>
      </div>
    </div>
  )
}

// --- Member layout (mobile first) -------------------------------------------------------------

export function MemberLayout({ user, screen, children }: { user: Me; screen: Screen; children: ReactNode }) {
  return (
    <div className={styles.member}>
      <a className="skip-link" href="#main" onClick={(e) => { e.preventDefault(); document.getElementById('main')?.focus() }}>
        {t.app.skipToContent}
      </a>
      <header className={styles.memberBar}>
        <a href={paths.my()} className={styles.memberBrand}><Brand onDark /></a>
        <UserMenu user={user} onDark />
      </header>
      <nav className={styles.memberNav} aria-label={t.nav.main}>
        <a href={paths.my()} className={cx(styles.memberTab, (screen === 'my' || screen === 'myApplication') && styles.memberTabActive)}
           aria-current={screen === 'my' ? 'page' : undefined}>
          <Icon name="file" size={18} /> {t.nav.myApplications}
        </a>
        <a href={paths.profile()} className={cx(styles.memberTab, screen === 'profile' && styles.memberTabActive)}
           aria-current={screen === 'profile' ? 'page' : undefined}>
          <Icon name="user" size={18} /> {t.common.profile}
        </a>
      </nav>
      <main id="main" tabIndex={-1} className={styles.memberMain}>{children}</main>
    </div>
  )
}
