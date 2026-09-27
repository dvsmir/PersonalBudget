import { describe, expect, it } from 'vitest'
import { formatMoney, parseMoney, setNumberStyle } from './money'

describe('money', () => {
  it('parses user input in both decimal styles', () => {
    expect(parseMoney('12,34')).toBe(1234)
    expect(parseMoney('1.234,56')).toBe(123456)
    expect(parseMoney('1,234.56')).toBe(123456)
    expect(parseMoney('-45.2')).toBe(-4520)
    expect(parseMoney('abc')).toBeNull()
  })
  it('formats EUR and RUB', () => {
    setNumberStyle('en')
    expect(formatMoney(-166816, 'EUR')).toBe('−€1,668.16')
    expect(formatMoney(2058900, 'RUB')).toBe('20,589 ₽')
    setNumberStyle('nl')
    expect(formatMoney(123456, 'EUR')).toBe('€1.234,56')
  })
})
