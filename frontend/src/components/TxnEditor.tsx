import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  ActionIcon, Alert, Button, Drawer, Group, SegmentedControl, Select, Stack, Switch, Text, TextInput, Textarea,
} from '@mantine/core'
import { DateInput } from '@mantine/dates'
import { IconPlus, IconTrash } from '@tabler/icons-react'
import { useQueryClient } from '@tanstack/react-query'
import { notifications } from '@mantine/notifications'
import { useTranslation } from 'react-i18next'
import dayjs from 'dayjs'
import { ApiError, request, type Txn } from '../api/client'
import { LEDGER_KEYS, notifyError, useAccounts, useCategories, useDebts, useEarmarks, useSecurities } from '../api/hooks'
import { AccountSelect, CategorySelect, MoneyInput, ProjectSelect } from './common'
import { formatMoney } from '../lib/money'

type Kind = 'expense' | 'income' | 'transfer' | 'debt_payment' | 'investment' | 'earmark' | 'adjustment'
type Line = { amount: number | null; category_id: number | null; cost_type: string | null; project_id: number | null; debt_id?: number | null; note?: string | null }

type Form = {
  kind: Kind
  date: string
  description: string
  notes: string
  account_id: number | null
  amount: number | null // absolute value entered by the user
  lines: Line[]
  split: boolean
  to_account_id: number | null
  amount_in: number | null
  debt_id: number | null
  security_id: number | null
  action: 'buy' | 'sell'
  units: string
  price: string
  fees: number | null
  earmark_id: number | null
  earmark_dir: 'allocate' | 'release'
  sign: 'out' | 'in'
}

const LAST_ACCOUNT = 'budget.lastAccount'
const emptyLine = (): Line => ({ amount: null, category_id: null, cost_type: null, project_id: null })

function blank(kind: Kind = 'expense'): Form {
  let acc: number | null = null
  try {
    acc = Number(localStorage.getItem(LAST_ACCOUNT)) || null
  } catch { /* ignore */ }
  return {
    kind, date: dayjs().format('YYYY-MM-DD'), description: '', notes: '', account_id: acc, amount: null,
    lines: [emptyLine()], split: false, to_account_id: null, amount_in: null, debt_id: null, security_id: null,
    action: 'buy', units: '', price: '', fees: 0, earmark_id: null, earmark_dir: 'allocate', sign: 'out',
  }
}

function fromTxn(t: Txn): Form {
  const f = blank(t.kind as Kind)
  f.date = t.date
  f.description = t.description
  f.notes = t.notes ?? ''
  const leg = t.legs[0]
  if (leg) {
    f.account_id = leg.account_id
    f.amount = Math.abs(leg.amount)
    f.sign = leg.amount < 0 ? 'out' : 'in'
  }
  if (t.kind === 'transfer' && t.legs.length === 2) {
    const out = t.legs.find((l) => l.amount < 0) ?? t.legs[0]
    const inn = t.legs.find((l) => l !== out)!
    f.account_id = out.account_id
    f.amount = Math.abs(out.amount)
    f.to_account_id = inn.account_id
    f.amount_in = Math.abs(inn.amount)
  }
  const moneySplits = t.splits.filter((s) => !s.earmark_id)
  f.lines = moneySplits.map((s) => ({
    amount: Math.abs(s.amount), category_id: s.category_id ?? null, cost_type: s.cost_type ?? null,
    project_id: s.project_id ?? null, debt_id: s.debt_id ?? null, note: s.note ?? null,
  }))
  if (!f.lines.length) f.lines = [emptyLine()]
  f.split = moneySplits.length > 1
  if (t.kind === 'debt_payment') {
    f.debt_id = t.splits.find((s) => s.debt_id)?.debt_id ?? null
  }
  if (t.kind === 'earmark') {
    const s = t.splits[0]
    f.earmark_id = s?.earmark_id ?? null
    f.amount = Math.abs(s?.amount ?? 0)
    f.earmark_dir = (s?.amount ?? 0) >= 0 ? 'allocate' : 'release'
  }
  if (t.kind === 'investment' && t.trades[0]) {
    const tr = t.trades[0]
    f.security_id = tr.security_id
    f.action = Number(tr.units) < 0 ? 'sell' : 'buy'
    f.units = String(Math.abs(Number(tr.units)))
    f.price = String(tr.price)
    f.fees = tr.fees
  }
  return f
}

function toPayload(f: Form) {
  const base = { date: f.date, kind: f.kind, description: f.description, notes: f.notes || null }
  const out = (v: number | null) => -(v ?? 0)
  switch (f.kind) {
    case 'expense':
    case 'income': {
      const s = f.kind === 'expense' ? -1 : 1
      const lines = f.split ? f.lines : [{ ...f.lines[0], amount: f.amount }]
      return {
        ...base,
        legs: [{ account_id: f.account_id, amount: s * (f.amount ?? 0) }],
        splits: lines.map((l) => ({ amount: s * (l.amount ?? 0), category_id: l.category_id, cost_type: l.cost_type || null, project_id: l.project_id })),
      }
    }
    case 'transfer':
      return {
        ...base,
        legs: [
          { account_id: f.account_id, amount: out(f.amount) },
          { account_id: f.to_account_id, amount: f.amount_in ?? f.amount ?? 0 },
        ],
      }
    case 'debt_payment':
      return {
        ...base,
        legs: [{ account_id: f.account_id, amount: out(f.amount) }],
        splits: f.lines.map((l) =>
          l.debt_id
            ? { amount: -(l.amount ?? 0), debt_id: l.debt_id, note: l.note }
            : { amount: -(l.amount ?? 0), category_id: l.category_id, cost_type: 'fixed', note: l.note },
        ),
      }
    case 'investment': {
      const units = Number(f.units.replace(',', '.')) * (f.action === 'sell' ? -1 : 1)
      const price = Number(f.price.replace(',', '.'))
      return {
        ...base,
        legs: [{ account_id: f.account_id, amount: f.action === 'buy' ? out(f.amount) : f.amount ?? 0 }],
        trades: [{ account_id: f.account_id, security_id: f.security_id, action: f.action, units, price, fees: f.fees ?? 0 }],
      }
    }
    case 'earmark':
      return { ...base, splits: [{ amount: (f.earmark_dir === 'allocate' ? 1 : -1) * (f.amount ?? 0), earmark_id: f.earmark_id }] }
    case 'adjustment':
      return { ...base, legs: [{ account_id: f.account_id, amount: (f.sign === 'out' ? -1 : 1) * (f.amount ?? 0) }] }
  }
}

type EditorApi = { openNew: (kind?: Kind) => void; openEdit: (txn: Txn) => void }
const Ctx = createContext<EditorApi>({ openNew: () => {}, openEdit: () => {} })
export const useTxnEditor = () => useContext(Ctx)

export function TxnEditorProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ open: boolean; txn: Txn | null; kind?: Kind; nonce: number }>({ open: false, txn: null, nonce: 0 })
  const api = useMemo<EditorApi>(() => ({
    openNew: (kind) => setState((s) => ({ open: true, txn: null, kind, nonce: s.nonce + 1 })),
    openEdit: (txn) => setState((s) => ({ open: true, txn, nonce: s.nonce + 1 })),
  }), [])
  const { t } = useTranslation()
  return (
    <Ctx.Provider value={api}>
      {children}
      <Drawer
        opened={state.open}
        onClose={() => setState((s) => ({ ...s, open: false }))}
        position="right"
        size="lg"
        title={<Text fw={600}>{state.txn ? t('txn.editTitle') : t('txn.new')}</Text>}
      >
        {state.open && (
          <TxnForm
            key={state.nonce}
            txn={state.txn}
            initialKind={state.kind}
            onDone={(again) => (again ? setState((s) => ({ open: true, txn: null, kind: undefined, nonce: s.nonce + 1 })) : setState((s) => ({ ...s, open: false })))}
          />
        )}
      </Drawer>
    </Ctx.Provider>
  )
}

function TxnForm({ txn, initialKind, onDone }: { txn: Txn | null; initialKind?: Kind; onDone: (again: boolean) => void }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [f, setF] = useState<Form>(() => (txn ? fromTxn(txn) : blank(initialKind)))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { data: accounts } = useAccounts()
  const { data: cats } = useCategories()
  const { data: debts } = useDebts()
  const { data: earmarks } = useEarmarks()
  const { data: securities } = useSecurities()
  const set = (patch: Partial<Form>) => setF((p) => ({ ...p, ...patch }))
  const acc = accounts?.find((a) => a.id === f.account_id)
  const toAcc = accounts?.find((a) => a.id === f.to_account_id)
  const conversion = f.kind === 'transfer' && acc && toAcc && acc.currency !== toAcc.currency
  const [market, setMarket] = useState<string | null>(null)
  const editable = !txn || ['expense', 'income', 'transfer', 'debt_payment', 'investment', 'earmark', 'adjustment'].includes(txn.kind)

  useEffect(() => {
    if (!conversion) return
    const foreign = acc!.currency === 'EUR' ? toAcc!.currency : acc!.currency
    request<{ rate: string | null }>('GET', `/api/v1/fx/rate?date=${f.date}&currency=${foreign}`).then((r) => setMarket(r.rate)).catch(() => setMarket(null))
  }, [conversion, f.date, acc, toAcc])

  const remaining = (f.amount ?? 0) - f.lines.reduce((s, l) => s + (l.amount ?? 0), 0)
  const catKind = f.kind === 'income' ? 'income' : 'expense'
  const defaultCostType = (id: number | null) => {
    const c = cats?.find((x) => x.id === id)
    const parent = c?.parent_id ? cats?.find((x) => x.id === c.parent_id) : null
    return c?.default_cost_type ?? parent?.default_cost_type ?? 'variable'
  }

  async function suggestDebt() {
    if (!f.debt_id || !f.amount) return
    try {
      const splits = await request<{ amount: number; category_id?: number; debt_id?: number; note?: string }[]>(
        'POST', '/api/v1/debts/suggest-split', { debt_id: f.debt_id, date: f.date, amount: f.amount })
      set({ lines: splits.map((s) => ({ amount: -s.amount, category_id: s.category_id ?? null, debt_id: s.debt_id ?? null, cost_type: 'fixed', project_id: null, note: s.note ?? null })) })
    } catch (e) {
      notifyError(e)
    }
  }

  async function save(again: boolean) {
    setBusy(true)
    setError(null)
    try {
      const payload = toPayload(f)
      if (txn) {
        await request('PUT', `/api/v1/txns/${txn.id}`, payload)
      } else {
        await request('POST', '/api/v1/txns', payload)
      }
      if (f.account_id) localStorage.setItem(LAST_ACCOUNT, String(f.account_id))
      LEDGER_KEYS.forEach((k) => qc.invalidateQueries({ queryKey: k }))
      notifications.show({ color: 'teal', message: t('common.saved') })
      onDone(again)
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        notifications.show({ color: 'orange', message: t('txn.conflict') })
        LEDGER_KEYS.forEach((k) => qc.invalidateQueries({ queryKey: k }))
        onDone(false)
      } else setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    if (!txn || !confirm(`${t('common.delete')}?`)) return
    try {
      await request('DELETE', `/api/v1/txns/${txn.id}`)
      LEDGER_KEYS.forEach((k) => qc.invalidateQueries({ queryKey: k }))
      notifications.show({ message: t('txn.deleted') })
      onDone(false)
    } catch (e) {
      notifyError(e)
    }
  }

  const kinds: Kind[] = ['expense', 'income', 'transfer', 'debt_payment', 'investment', 'earmark', 'adjustment']
  const selectableDebts = (debts ?? []).filter((d) => !d.parent_debt_id)

  if (!editable) {
    return (
      <Stack>
        <Alert color="gray">{t(`kinds.${txn!.kind}`)}: {txn!.description}</Alert>
        <Button color="red" variant="light" onClick={remove}>{t('common.delete')}</Button>
      </Stack>
    )
  }

  return (
    <Stack gap="sm">
      <Select
        label={t('common.kind')}
        data={kinds.map((k) => ({ value: k, label: t(`kinds.${k}`) }))}
        value={f.kind}
        onChange={(v) => v && set({ kind: v as Kind, lines: [emptyLine()], split: false })}
        allowDeselect={false}
        disabled={!!txn}
      />
      <Group grow>
        <DateInput label={t('common.date')} value={f.date} onChange={(v) => v && set({ date: v })} valueFormat="DD-MM-YYYY" />
        {f.kind !== 'earmark' && (
          <MoneyInput
            label={f.kind === 'transfer' ? t('txn.amountOut') : t('common.amount')}
            value={f.amount}
            onChange={(v) => set({ amount: v === null ? null : Math.abs(v) })}
            currency={acc?.currency}
            data-autofocus
            required
          />
        )}
      </Group>

      {f.kind !== 'earmark' && (
        <AccountSelect
          label={f.kind === 'transfer' ? t('txn.fromAccount') : t('common.account')}
          value={f.account_id}
          onChange={(v) => set({ account_id: v })}
          required
        />
      )}

      {(f.kind === 'expense' || f.kind === 'income') && (
        <>
          {!f.split ? (
            <>
              <CategorySelect label={t('common.category')} kind={catKind} value={f.lines[0].category_id}
                onChange={(v) => set({ lines: [{ ...f.lines[0], category_id: v }] })} required />
              <Group grow>
                {f.kind === 'expense' && (
                  <Select
                    label={t('txn.costType')}
                    placeholder={`${t('txn.defaultCostType')}: ${t(`costType.${defaultCostType(f.lines[0].category_id)}`)}`}
                    data={['fixed', 'variable', 'one_time'].map((v) => ({ value: v, label: t(`costType.${v}`) }))}
                    value={f.lines[0].cost_type}
                    onChange={(v) => set({ lines: [{ ...f.lines[0], cost_type: v }] })}
                    clearable
                  />
                )}
                <ProjectSelect label={t('common.project')} value={f.lines[0].project_id}
                  onChange={(v) => set({ lines: [{ ...f.lines[0], project_id: v }] })} />
              </Group>
            </>
          ) : (
            <Stack gap={6}>
              {f.lines.map((l, i) => (
                <Group key={i} gap={6} wrap="nowrap" align="flex-end">
                  <MoneyInput w={110} label={i === 0 ? t('common.amount') : undefined} value={l.amount}
                    onChange={(v) => set({ lines: f.lines.map((x, j) => (j === i ? { ...x, amount: v === null ? null : Math.abs(v) } : x)) })} />
                  <CategorySelect style={{ flex: 1 }} label={i === 0 ? t('common.category') : undefined} kind={catKind} value={l.category_id}
                    onChange={(v) => set({ lines: f.lines.map((x, j) => (j === i ? { ...x, category_id: v } : x)) })} />
                  <ActionIcon variant="subtle" color="red" mb={4} onClick={() => set({ lines: f.lines.filter((_, j) => j !== i) })} disabled={f.lines.length < 2}>
                    <IconTrash size={16} />
                  </ActionIcon>
                </Group>
              ))}
              <Group justify="space-between">
                <Button size="xs" variant="subtle" leftSection={<IconPlus size={14} />} onClick={() => set({ lines: [...f.lines, { ...emptyLine(), amount: Math.max(0, remaining) }] })}>
                  {t('txn.addSplit')}
                </Button>
                <Text size="sm" c={remaining === 0 ? 'dimmed' : 'red'}>{t('txn.remaining')}: {formatMoney(remaining, acc?.currency)}</Text>
              </Group>
            </Stack>
          )}
          <Switch label={t('txn.split')} checked={f.split}
            onChange={(e) => set({ split: e.currentTarget.checked, lines: e.currentTarget.checked ? [{ ...f.lines[0], amount: f.amount }] : [f.lines[0]] })} />
        </>
      )}

      {f.kind === 'transfer' && (
        <>
          <AccountSelect label={t('txn.toAccount')} value={f.to_account_id} onChange={(v) => set({ to_account_id: v })} required />
          {conversion && (
            <>
              <MoneyInput label={t('txn.amountIn')} value={f.amount_in} onChange={(v) => set({ amount_in: v === null ? null : Math.abs(v) })} currency={toAcc?.currency} required />
              <Text size="sm" c="dimmed">
                {t('txn.impliedRate')}: {f.amount && f.amount_in ? (acc!.currency === 'EUR' ? f.amount_in / f.amount : f.amount / f.amount_in).toFixed(4) : '—'}
                {' · '}{t('txn.marketRate')}: {market ? Number(market).toFixed(4) : '—'}
              </Text>
            </>
          )}
        </>
      )}

      {f.kind === 'debt_payment' && (
        <>
          <Group grow align="flex-end">
            <Select label={t('txn.debt')} data={selectableDebts.map((d) => ({ value: String(d.id), label: d.name }))}
              value={f.debt_id ? String(f.debt_id) : null} onChange={(v) => set({ debt_id: v ? Number(v) : null })} />
            <Button variant="light" onClick={suggestDebt} disabled={!f.debt_id || !f.amount}>{t('txn.suggest')}</Button>
          </Group>
          {f.lines.filter((l) => l.amount !== null).map((l, i) => (
            <Group key={i} gap={6} wrap="nowrap">
              <MoneyInput w={120} value={l.amount} onChange={(v) => set({ lines: f.lines.map((x, j) => (j === i ? { ...x, amount: v === null ? null : Math.abs(v) } : x)) })} />
              <Text size="sm">{l.note ?? (l.debt_id ? t('txn.principal') : t('txn.interest'))}</Text>
            </Group>
          ))}
          {f.lines.some((l) => l.amount !== null) && (
            <Text size="sm" c={remaining === 0 ? 'dimmed' : 'red'}>{t('txn.remaining')}: {formatMoney(remaining, acc?.currency)}</Text>
          )}
        </>
      )}

      {f.kind === 'investment' && (
        <>
          <Group grow>
            <SegmentedControl value={f.action} onChange={(v) => set({ action: v as 'buy' | 'sell' })}
              data={[{ value: 'buy', label: t('txn.buy') }, { value: 'sell', label: t('txn.sell') }]} />
            <Select label={t('txn.security')} data={(securities ?? []).map((s) => ({ value: String(s.id), label: `${s.name} (${s.symbol})` }))}
              value={f.security_id ? String(f.security_id) : null} onChange={(v) => set({ security_id: v ? Number(v) : null })} searchable />
          </Group>
          <Group grow>
            <TextInput label={t('txn.units')} value={f.units} onChange={(e) => set({ units: e.currentTarget.value })} />
            <TextInput label={t('txn.price')} value={f.price} onChange={(e) => set({ price: e.currentTarget.value })} />
            <MoneyInput label={t('txn.fees')} value={f.fees} onChange={(v) => set({ fees: v })} />
          </Group>
        </>
      )}

      {f.kind === 'earmark' && (
        <>
          <SegmentedControl value={f.earmark_dir} onChange={(v) => set({ earmark_dir: v as 'allocate' | 'release' })}
            data={[{ value: 'allocate', label: t('txn.allocate') }, { value: 'release', label: t('txn.release') }]} />
          <Group grow>
            <Select label={t('txn.earmark')} data={(earmarks ?? []).map((e) => ({ value: String(e.id), label: e.name }))}
              value={f.earmark_id ? String(f.earmark_id) : null} onChange={(v) => set({ earmark_id: v ? Number(v) : null })} />
            <MoneyInput label={t('common.amount')} value={f.amount} onChange={(v) => set({ amount: v === null ? null : Math.abs(v) })} />
          </Group>
        </>
      )}

      {f.kind === 'adjustment' && (
        <SegmentedControl value={f.sign} onChange={(v) => set({ sign: v as 'out' | 'in' })}
          data={[{ value: 'out', label: t('txn.sign') }, { value: 'in', label: t('txn.signIn') }]} />
      )}

      <TextInput label={t('common.description')} value={f.description} onChange={(e) => set({ description: e.currentTarget.value })} />
      <Textarea label={t('common.notes')} value={f.notes} onChange={(e) => set({ notes: e.currentTarget.value })} autosize minRows={1} />
      {txn && txn.legs.some((l) => l.inferred) && <Text size="xs" c="dimmed">↔ {t('txn.inferred')}</Text>}
      {error && <Alert color="red">{error}</Alert>}
      <Group justify="space-between" mt="sm">
        {txn ? <Button color="red" variant="subtle" onClick={remove}>{t('common.delete')}</Button> : <span />}
        <Group>
          {!txn && <Button variant="default" onClick={() => save(true)} loading={busy}>{t('txn.saveAndNew')}</Button>}
          <Button onClick={() => save(false)} loading={busy}>{t('common.save')}</Button>
        </Group>
      </Group>
    </Stack>
  )
}
