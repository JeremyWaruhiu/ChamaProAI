import type { ReactNode } from 'react'
import { NOT_MEASURED, fmt, isMeasured, pct } from '../lib/measure'
import styles from './Charts.module.css'

// Plain CSS/SVG charts for the read-only results page. No chart dependency.
// A null value is "not yet measured", never drawn or printed as 0.

export function Value({ v, digits = 3, percent = false }: { v: number | null | undefined; digits?: number; percent?: boolean }) {
  if (!isMeasured(v)) return <span className={styles.na}>{NOT_MEASURED}</span>
  return <>{percent ? pct(v, digits) : fmt(v, digits)}</>
}

export function Caption({ source, validation }: { source?: string; validation?: string }) {
  return (
    <p className={styles.caption}>
      <strong>Source:</strong> {source ?? NOT_MEASURED}
      {validation && <><br /><strong>Validation:</strong> {validation}</>}
    </p>
  )
}

export function Notes({ notes }: { notes?: string[] }) {
  if (!notes?.length) return null
  return <ul className={styles.notes}>{notes.map((n) => <li key={n}>{n}</li>)}</ul>
}

/** Rows are the true class, columns the predicted class. Shade is the row share. */
export function ConfusionMatrix({ labels, matrix }: { labels: string[]; matrix: number[][] | null | undefined }) {
  if (!matrix?.length) return <p className={styles.na}>Confusion matrix {NOT_MEASURED}</p>
  return (
    <div className={styles.cm} role="table" aria-label="Confusion matrix: rows true class, columns predicted class"
         style={{ gridTemplateColumns: `auto repeat(${labels.length}, minmax(64px, 1fr))` }}>
      <span role="columnheader" className={styles.cmCorner}>true ↓ / predicted →</span>
      {labels.map((l) => <span key={l} role="columnheader" className={styles.cmHead}>{l}</span>)}
      {matrix.map((row, i) => {
        const total = row.reduce((a, b) => a + b, 0)
        return [
          <span key={`h${i}`} role="rowheader" className={styles.cmHead}>{labels[i]}</span>,
          ...row.map((n, j) => {
            const share = total ? n / total : 0
            const tone = i === j ? 'var(--green-600)' : 'var(--high)'
            return (
              <span key={`${i}-${j}`} role="cell" data-testid={`cm-${i}-${j}`}
                    className={`${styles.cmCell} ${share > 0.45 ? styles.cmDark : ''}`}
                    style={{ background: `color-mix(in srgb, ${tone} ${Math.round(share * 85)}%, white)` }}
                    title={`true ${labels[i]}, predicted ${labels[j]}: ${n} (${(share * 100).toFixed(1)}% of row)`}>
                <strong>{n}</strong>
                <small>{(share * 100).toFixed(0)}%</small>
              </span>
            )
          }),
        ]
      })}
    </div>
  )
}

export interface Bar {
  label: string
  value: number | null | undefined
  tone?: 'model' | 'baseline' | 'low' | 'medium' | 'high'
}

/** Horizontal bars scaled to max (default: the largest value). */
export function HBars({ bars, max, format = (v) => fmt(v) }: { bars: Bar[]; max?: number; format?: (v: number) => string }) {
  const top = max ?? Math.max(0, ...bars.map((b) => (isMeasured(b.value) ? b.value : 0)))
  return (
    <div className={styles.hbars}>
      {bars.map((b) => (
        <div key={b.label} className={styles.hbar}>
          <span className={styles.hbarLabel}>{b.label}</span>
          <span className={styles.hbarTrack}>
            {isMeasured(b.value) && (
              <span className={`${styles.hbarFill} ${styles[b.tone ?? 'model']}`}
                    style={{ width: `${top > 0 ? (100 * b.value) / top : 0}%` }} />
            )}
          </span>
          <span className={styles.hbarValue}>
            {isMeasured(b.value) ? format(b.value) : <span className={styles.na}>{NOT_MEASURED}</span>}
          </span>
        </div>
      ))}
    </div>
  )
}

/** Vertical grouped bars in SVG: one group per category, one bar per series. */
export function GroupedBars({ categories, series, max = 100, height = 220 }: {
  categories: string[]
  series: { name: string; values: (number | null | undefined)[]; color: string }[]
  max?: number
  height?: number
}) {
  const groupW = 26 * series.length + 22
  const width = Math.max(320, categories.length * groupW + 40)
  const plotH = height - 64
  const y = (v: number) => 12 + plotH - (plotH * Math.min(v, max)) / max
  return (
    <figure className={styles.grouped}>
      <svg viewBox={`0 0 ${width} ${height}`} role="img"
           aria-label={`${series.map((s) => s.name).join(' vs ')} by ${categories.join(', ')}`}>
        {[0, 25, 50, 75, 100].filter((t) => t <= max).map((t) => (
          <g key={t}>
            <line x1={34} x2={width} y1={y(t)} y2={y(t)} stroke="var(--line)" />
            <text x={30} y={y(t) + 4} textAnchor="end" fontSize="11" fill="var(--ink-3)">{t}</text>
          </g>
        ))}
        {categories.map((c, ci) => {
          const x0 = 40 + ci * groupW
          return (
            <g key={c}>
              {series.map((s, si) => {
                const v = s.values[ci]
                const x = x0 + si * 26
                return isMeasured(v)
                  ? <rect key={s.name} x={x} y={y(v)} width={22} height={Math.max(0, y(0) - y(v))} fill={s.color}>
                      <title>{`${s.name}, ${c}: ${v.toFixed(2)}`}</title>
                    </rect>
                  : <text key={s.name} x={x + 11} y={y(0) - 4} textAnchor="middle" fontSize="10" fill="var(--ink-3)">
                      n/m<title>{`${s.name}, ${c}: ${NOT_MEASURED}`}</title>
                    </text>
              })}
              <text x={x0 + (series.length * 26) / 2} y={height - 34} textAnchor="end" fontSize="11"
                    fill="var(--ink-2)" transform={`rotate(-30 ${x0 + (series.length * 26) / 2} ${height - 34})`}>
                {c.replace(/_/g, ' ')}
              </text>
            </g>
          )
        })}
      </svg>
      <figcaption className={styles.legend}>
        {series.map((s) => (
          <span key={s.name}><i style={{ background: s.color }} />{s.name}</span>
        ))}
        <span className={styles.na}>n/m = {NOT_MEASURED}</span>
      </figcaption>
    </figure>
  )
}

export function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className={styles.stat}>
      <span className={styles.statLabel}>{label}</span>
      <span className={styles.statValue}>{children}</span>
    </div>
  )
}
