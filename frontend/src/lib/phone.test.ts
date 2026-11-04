import { describe, expect, it } from 'vitest'
import { normalisePhone } from './phone'

describe('normalisePhone', () => {
  it.each(['0712345678', '0712 345 678', '+254712345678', '254712345678', '(0712) 345-678'])(
    'reads %s as one number', (typed) => { expect(normalisePhone(typed)).toBe('+254712345678') })

  it.each(['0112345678', '+254112345678', '254112345678'])(
    'accepts the 01 range: %s', (typed) => { expect(normalisePhone(typed)).toBe('+254112345678') })

  it.each(['', '12345', '0812345678', '071234567', '07123456789', '+255712345678', '2540712345678', '0712345abc'])(
    'refuses %s', (typed) => { expect(normalisePhone(typed)).toBeNull() })
})
