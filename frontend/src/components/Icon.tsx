// A small inline icon set: 24 px grid, 1.75 stroke, currentColor. Inline
// SVG keeps the app free of an icon dependency and of extra requests.

const PATHS = {
  home: 'M3 10.5 12 3l9 7.5M5.5 9v11h13V9',
  mic: 'M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3ZM5 11a7 7 0 0 0 14 0M12 18v3',
  list: 'M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01',
  file: 'M14 3H6v18h12V7l-4-4ZM14 3v4h4M9 13h6M9 17h6',
  users: 'M16 20v-1.5a3.5 3.5 0 0 0-3.5-3.5h-5A3.5 3.5 0 0 0 4 18.5V20M10 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7ZM20 20v-1.5a3.5 3.5 0 0 0-2.5-3.35M15.5 4.15a3.5 3.5 0 0 1 0 6.7',
  user: 'M20 21v-1.5A4.5 4.5 0 0 0 15.5 15h-7A4.5 4.5 0 0 0 4 19.5V21M12 11.5a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z',
  chart: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
  shield: 'M12 3 4.5 6v5.5c0 4.6 3.2 8.4 7.5 9.5 4.3-1.1 7.5-4.9 7.5-9.5V6L12 3ZM9 12l2 2 4-4',
  scroll: 'M8 21h10a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2H8M8 21a2 2 0 0 1-2-2V5a2 2 0 0 0-2-2h4M8 21a2 2 0 0 0 2-2M10 8h6M10 12h6M10 16h4',
  overview: 'M3 3h8v8H3zM13 3h8v5h-8zM13 10h8v11h-8zM3 13h8v8H3z',
  search: 'M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14ZM20 20l-4-4',
  logout: 'M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3M10 17l5-5-5-5M15 12H4',
  chevronLeft: 'M15 18l-6-6 6-6',
  chevronRight: 'M9 18l6-6-6-6',
  chevronDown: 'M6 9l6 6 6-6',
  menu: 'M4 6h16M4 12h16M4 18h16',
  x: 'M18 6 6 18M6 6l12 12',
  check: 'M20 6 9 17l-5-5',
  clock: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM12 7v5l3 2',
  alert: 'M12 9v4M12 17h.01M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z',
  info: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM12 16v-4M12 8h.01',
  plus: 'M12 5v14M5 12h14',
  play: 'M7 4v16l13-8L7 4Z',
  stop: 'M6 6h12v12H6z',
  upload: 'M12 16V4M7 9l5-5 5 5M4 20h16',
  keyboard: 'M3 6h18v12H3zM7 10h.01M11 10h.01M15 10h.01M7 14h10',
  key: 'M15 7.5a3.5 3.5 0 1 1-3.4 4.3L4 19.5V22h3v-2h2v-2h2l1.2-1.2A3.5 3.5 0 0 1 15 7.5ZM16.5 6.5h.01',
  arrowRight: 'M5 12h14M13 6l6 6-6 6',
  arrowLeft: 'M19 12H5M11 18l-6-6 6-6',
  sparkle: 'M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z',
  wave: 'M2 12h2M6 8v8M10 5v14M14 9v6M18 7v10M22 12h-2',
  scale: 'M12 3v18M7 21h10M5 7h14M5 7l-3 7a3 3 0 0 0 6 0L5 7ZM19 7l-3 7a3 3 0 0 0 6 0l-3-7Z',
  phone: 'M8 3H6a2 2 0 0 0-2 2c0 8.8 7.2 16 16 16a2 2 0 0 0 2-2v-2l-4-2-2 2a12 12 0 0 1-6-6l2-2-2-4Z',
  lock: 'M6 11h12v10H6zM8.5 11V7.5a3.5 3.5 0 0 1 7 0V11',
  globe: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3Z',
  edit: 'M4 20h4L19 9l-4-4L4 16v4ZM14 6l4 4',
  activity: 'M3 12h4l3-8 4 16 3-8h4',
  cpu: 'M7 7h10v10H7zM10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4',
} as const

export type IconName = keyof typeof PATHS

export function Icon({ name, size = 20, className, label }: {
  name: IconName
  size?: number
  className?: string
  /** Give a label only when the icon stands alone and means something. */
  label?: string
}) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round"
         role={label ? 'img' : undefined} aria-label={label} aria-hidden={label ? undefined : true}
         focusable="false">
      <path d={PATHS[name]} />
    </svg>
  )
}
