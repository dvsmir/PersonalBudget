/** Money is an integer in minor units + currency code everywhere (Backend.md §7). */

const SYMBOL: Record<string, string> = { EUR: '€', RUB: '₽', USD: '$', GBP: '£' }
const DECIMALS: Record<string, number> = { RUB: 0 } // RUB shown without decimals (Frontend.md §4)

export type NumberStyle = 'en' | 'nl'

let numberStyle: NumberStyle = 'en'
export function setNumberStyle(s: NumberStyle) {
  numberStyle = s
}

export function formatMoney(
  minor: number | null | undefined,
  currency = 'EUR',
  opts: { abs?: boolean; sign?: boolean; compact?: boolean } = {},
): string {
  if (minor === null || minor === undefined) return '—'
  let value = minor / 100
  if (opts.abs) value = Math.abs(value)
  const decimals = opts.compact ? 0 : (DECIMALS[currency] ?? 2)
  const locale = numberStyle === 'nl' ? 'nl-NL' : 'en-GB'
  const num = new Intl.NumberFormat(locale, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
    notation: opts.compact && Math.abs(value) >= 10000 ? 'compact' : 'standard',
  }).format(Math.abs(value))
  const sign = value < 0 ? '−' : opts.sign && value > 0 ? '+' : ''
  const sym = SYMBOL[currency] ?? currency + ' '
  return currency === 'RUB' ? `${sign}${num} ${sym}` : `${sign}${sym}${num}`
}

export function formatTotals(totals: Record<string, number> | undefined, opts: { abs?: boolean } = {}): string {
  if (!totals || Object.keys(totals).length === 0) return formatMoney(0)
  return Object.entries(totals)
    .map(([ccy, v]) => formatMoney(v, ccy, opts))
    .join(' · ')
}

/** '12,34' / '12.34' / '1 234,5' → 1234 minor units. Returns null when not a number. */
export function parseMoney(input: string): number | null {
  const s = input.trim().replace(/\s| /g, '').replace('−', '-')
  if (!s) return null
  let norm = s
  if (s.includes(',') && s.includes('.')) {
    norm = s.lastIndexOf(',') > s.lastIndexOf('.') ? s.replace(/\./g, '').replace(',', '.') : s.replace(/,/g, '')
  } else if (s.includes(',')) {
    const tail = s.split(',').pop() ?? ''
    norm = s.split(',').length === 2 && tail.length <= 2 ? s.replace(',', '.') : s.replace(/,/g, '')
  }
  const n = Number(norm)
  if (!Number.isFinite(n)) return null
  return Math.round(n * 100)
}

export function minorToInput(minor: number): string {
  return (minor / 100).toFixed(2)
}

export const currencySymbol = (ccy: string) => SYMBOL[ccy] ?? ccy
