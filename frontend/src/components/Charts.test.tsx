import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { NOT_MEASURED, fmt, pct } from '../lib/measure'
import { ConfusionMatrix, GroupedBars, HBars, Value } from './Charts'

const html = (el: ReactElement) => renderToStaticMarkup(el)
const text = (el: ReactElement) => html(el).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()

describe('null values', () => {
  it('format as "not yet measured", never 0', () => {
    for (const v of [null, undefined, Number.NaN]) {
      expect(fmt(v)).toBe(NOT_MEASURED)
      expect(pct(v)).toBe(NOT_MEASURED)
      expect(text(<Value v={v} />)).toBe(NOT_MEASURED)
    }
  })

  it('keep a real zero as zero', () => {
    expect(fmt(0, 2)).toBe('0.00')
    expect(pct(0)).toBe('0.0%')
    expect(text(<Value v={0} digits={0} />)).toBe('0')
  })

  it('draw no bar for a null value in HBars', () => {
    const out = html(<HBars max={1} bars={[{ label: 'Model', value: 0.37 }, { label: 'Rule', value: null }]} />)
    expect(out).toContain('width:37%')
    expect(out.match(/width:/g)).toHaveLength(1)
    expect(out).toContain(NOT_MEASURED)
    expect(out).not.toMatch(/>0\.000</)
  })

  it('mark a null grouped bar n/m instead of drawing it', () => {
    const out = html(<GroupedBars categories={['income', 'assets']}
      series={[{ name: 'Paza', color: 'green', values: [38.5, null] }]} />)
    expect(out.match(/<rect/g)).toHaveLength(1)
    expect(out).toContain(`Paza, assets: ${NOT_MEASURED}`)
  })
})

describe('ConfusionMatrix', () => {
  const labels = ['Low', 'Medium', 'High']
  const matrix = [[315, 188, 324], [135, 127, 224], [81, 93, 198]]

  it('renders one cell per count with its row share', () => {
    const out = html(<ConfusionMatrix labels={labels} matrix={matrix} />)
    expect(out.match(/role="cell"/g)).toHaveLength(9)
    for (const row of matrix) for (const n of row) expect(out).toContain(`<strong>${n}</strong>`)
    // 315 of 827 true-Low rows
    expect(out).toMatch(/data-testid="cm-0-0"[^>]*title="true Low, predicted Low: 315 \(38\.1% of row\)"/)
  })

  it('labels rows and columns with the class names', () => {
    const out = html(<ConfusionMatrix labels={labels} matrix={matrix} />)
    expect(out.match(/role="columnheader"/g)).toHaveLength(4)
    expect(out.match(/role="rowheader"/g)).toHaveLength(3)
  })

  it('shades the diagonal green and errors red', () => {
    const out = html(<ConfusionMatrix labels={labels} matrix={matrix} />)
    expect(out).toMatch(/data-testid="cm-1-1"[^>]*var\(--green-600\)|var\(--green-600\)[^"]*"[^>]*data-testid="cm-1-1"/)
    expect(out).toMatch(/var\(--high\)[^"]*"[^>]*data-testid="cm-0-2"|data-testid="cm-0-2"[^>]*var\(--high\)/)
  })

  it('handles an all-zero row without dividing by zero', () => {
    const out = html(<ConfusionMatrix labels={['A', 'B']} matrix={[[0, 0], [1, 3]]} />)
    expect(out).not.toContain('NaN')
  })

  it('says "not yet measured" when there is no matrix', () => {
    expect(text(<ConfusionMatrix labels={labels} matrix={null} />)).toContain(NOT_MEASURED)
    expect(html(<ConfusionMatrix labels={labels} matrix={null} />)).not.toContain('role="cell"')
  })
})
