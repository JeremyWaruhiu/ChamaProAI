import { m } from 'motion/react'
import { EASE_OUT, useReducedMotion } from '../lib/motion'
import { t } from '../strings'
import styles from './PipelineHero.module.css'

// The landing page's illustration: a spoken answer becomes a transcript, then
// facts, then a risk band with its reason. It plays once as the page opens;
// with reduced motion it is drawn complete, with nothing moving. The
// transcript is drawn as lines, not words: no Kikuyu text is invented.

const L = t.landing
const WAVE = [10, 22, 34, 18, 40, 26, 14, 30, 20, 36, 16, 24, 12, 28, 18, 8]

export function PipelineHero() {
  const reduced = useReducedMotion()
  // Each element appears at its moment in the sequence; reduced motion skips straight to the end.
  // Only the properties an element starts from are animated back to rest.
  const REST: Record<string, number> = { x: 0, y: 0, scaleX: 1, scaleY: 1 }
  const at = (delay: number, from: Record<string, number> = {}) => reduced
    ? { initial: false as const }
    : { initial: { opacity: 0, ...from },
        animate: { opacity: 1, ...Object.fromEntries(Object.keys(from).map((k) => [k, REST[k]])) },
        transition: { delay, duration: 0.5, ease: EASE_OUT } }

  return (
    <figure className={styles.figure}>
      <svg viewBox="0 0 480 580" role="img" aria-label={L.pipelineLabel} className={styles.svg}>
        <defs>
          <linearGradient id="ph-band" x1="0" x2="1">
            <stop offset="0" stopColor="var(--low)" />
            <stop offset="0.5" stopColor="var(--ochre-500)" />
            <stop offset="1" stopColor="var(--high)" />
          </linearGradient>
          <filter id="ph-shadow" x="-10%" y="-10%" width="120%" height="140%">
            <feDropShadow dx="0" dy="4" stdDeviation="8" floodColor="#281f0e" floodOpacity="0.10" />
          </filter>
        </defs>

        {/* connectors */}
        {['M150 118 C150 150, 270 132, 290 156', 'M290 274 C290 300, 160 286, 150 314', 'M150 430 C150 456, 290 440, 300 462']
          .map((d, i) => (
            <m.path key={d} d={d} className={styles.flow} {...at(0.5 + i * 0.9)} />
          ))}

        {/* 1. spoken answer */}
        <m.g {...at(0, { y: 10 })}>
          <rect x="20" y="20" width="260" height="98" rx="16" className={styles.card} filter="url(#ph-shadow)" />
          <circle cx="56" cy="69" r="20" className={styles.mic} />
          <path d="M56 58a5 5 0 0 0-5 5v7a5 5 0 0 0 10 0v-7a5 5 0 0 0-5-5ZM48 69a8 8 0 0 0 16 0M56 77v4"
                className={styles.micGlyph} />
          <text x="88" y="46" className={styles.label}>{L.pipeVoice}</text>
          <g transform="translate(88 69)">
            {WAVE.map((h, i) => (
              <m.rect key={i} x={i * 11} y={-h / 2} width="5" height={h} rx="2.5" className={styles.wave}
                           style={{ originY: '50%' }} {...at(0.15 + i * 0.03, { scaleY: 0.2 })} />
            ))}
          </g>
        </m.g>

        {/* 2. transcript */}
        <m.g {...at(0.9, { y: 10 })}>
          <rect x="180" y="156" width="280" height="118" rx="16" className={styles.card} filter="url(#ph-shadow)" />
          <text x="204" y="186" className={styles.label}>{L.pipeTranscript}</text>
          <text x="436" y="186" className={styles.lang} textAnchor="end">KIK</text>
          {[212, 184, 132].map((w, i) => (
            <m.rect key={w} x="204" y={204 + i * 20} width={w} height="9" rx="4.5" className={styles.line}
                         style={{ originX: 0 }} {...at(1.1 + i * 0.25, { scaleX: 0 })} />
          ))}
        </m.g>

        {/* 3. facts */}
        <m.g {...at(1.8, { y: 10 })}>
          <rect x="20" y="314" width="270" height="116" rx="16" className={styles.card} filter="url(#ph-shadow)" />
          <text x="44" y="344" className={styles.label}>{L.pipeFacts}</text>
          {[L.pipeFact1, L.pipeFact2, L.pipeFact3].map((f, i) => (
            <m.g key={f} {...at(2.0 + i * 0.2, { x: -6 })}>
              <circle cx="50" cy={366 + i * 22} r="4" className={styles.factDot} />
              <text x="62" y={370 + i * 22} className={styles.fact}>{f}</text>
            </m.g>
          ))}
        </m.g>

        {/* 4. risk band */}
        <m.g {...at(2.7, { y: 10 })}>
          <rect x="150" y="462" width="310" height="104" rx="16" className={styles.cardStrong} filter="url(#ph-shadow)" />
          <text x="172" y="490" className={styles.labelOnDark}>{L.pipeBand}</text>
          <text x="438" y="491" className={styles.band} textAnchor="end">{L.pipeBandValue}</text>
          <rect x="172" y="506" width="266" height="10" rx="5" fill="url(#ph-band)" opacity="0.9" />
          <m.circle cx="190" cy="511" r="8" className={styles.marker} {...at(3.0, { x: 180 })} />
          <text x="172" y="548" className={styles.why}>{L.pipeBandWhy}</text>
        </m.g>
      </svg>
      <figcaption className={styles.caption}>{L.pipelineCaption}</figcaption>
    </figure>
  )
}
