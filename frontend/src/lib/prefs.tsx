import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { setNumberStyle, type NumberStyle } from './money'

/** Per-viewer display preferences (localStorage; never financial data). */
export type CurrencyMode = 'reference' | 'native'

type Prefs = {
  currencyMode: CurrencyMode
  setCurrencyMode: (m: CurrencyMode) => void
  numberStyle: NumberStyle
  setNumberStyle: (s: NumberStyle) => void
}

const Ctx = createContext<Prefs | null>(null)

function load<T extends string>(key: string, fallback: T): T {
  try {
    return (localStorage.getItem(key) as T) || fallback
  } catch {
    return fallback
  }
}
function save(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* private mode */
  }
}

export function PrefsProvider({ children }: { children: ReactNode }) {
  const [currencyMode, setMode] = useState<CurrencyMode>(() => load('budget.currencyMode', 'reference'))
  const [style, setStyle] = useState<NumberStyle>(() => load('budget.numberStyle', 'en'))
  setNumberStyle(style)
  useEffect(() => save('budget.currencyMode', currencyMode), [currencyMode])
  useEffect(() => save('budget.numberStyle', style), [style])
  return (
    <Ctx.Provider value={{ currencyMode, setCurrencyMode: setMode, numberStyle: style, setNumberStyle: setStyle }}>
      {children}
    </Ctx.Provider>
  )
}

export function usePrefs(): Prefs {
  const v = useContext(Ctx)
  if (!v) throw new Error('PrefsProvider missing')
  return v
}
