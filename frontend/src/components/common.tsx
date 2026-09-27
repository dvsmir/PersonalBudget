import { Badge, Card, Group, Select, Stack, Text, TextInput, type SelectProps, type TextInputProps } from '@mantine/core'
import { useMemo, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { formatMoney, formatTotals, minorToInput, parseMoney } from '../lib/money'
import { useAccounts, useCategories, useProjects } from '../api/hooks'

/** Signed money in text ink; red for negative when `colored`. Never uses a series colour (dataviz rule). */
export function Money({ value, currency = 'EUR', colored, abs, sign, compact }: {
  value: number | null | undefined; currency?: string; colored?: boolean; abs?: boolean; sign?: boolean; compact?: boolean
}) {
  const cls = colored && value ? (value < 0 ? 'num neg' : 'num pos') : 'num'
  return <span className={cls}>{formatMoney(value, currency, { abs, sign, compact })}</span>
}

export function Totals({ totals, abs }: { totals?: Record<string, number>; abs?: boolean }) {
  return <span className="num">{formatTotals(totals, { abs })}</span>
}

export function StatCard({ label, children, sub }: { label: string; children: ReactNode; sub?: ReactNode }) {
  return (
    <Card withBorder padding="md">
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>{label}</Text>
      <Text fz={24} fw={650} mt={4} className="num">{children}</Text>
      {sub && <Text size="xs" c="dimmed" mt={4}>{sub}</Text>}
    </Card>
  )
}

export function Section({ title, right, children }: { title: string; right?: ReactNode; children: ReactNode }) {
  return (
    <Card withBorder padding="md">
      <Group justify="space-between" mb="sm">
        <Text fw={600}>{title}</Text>
        {right}
      </Group>
      {children}
    </Card>
  )
}

/** Amount input: free text, parsed on blur into minor units. */
export function MoneyInput({ value, onChange, currency, ...rest }: Omit<TextInputProps, 'value' | 'onChange'> & {
  value: number | null; onChange: (v: number | null) => void; currency?: string
}) {
  const [text, setText] = useState<string | null>(null)
  const shown = text ?? (value === null ? '' : minorToInput(value))
  return (
    <TextInput
      {...rest}
      inputMode="decimal"
      value={shown}
      rightSection={currency ? <Text size="xs" c="dimmed">{currency}</Text> : undefined}
      onChange={(e) => {
        setText(e.currentTarget.value)
        onChange(parseMoney(e.currentTarget.value))
      }}
      onBlur={(e) => {
        setText(null)
        rest.onBlur?.(e)
      }}
      classNames={{ input: 'num' }}
    />
  )
}

export function CategorySelect({ kind, value, onChange, ...rest }: Omit<SelectProps, 'data' | 'value' | 'onChange'> & {
  kind?: 'expense' | 'income'; value: number | null | undefined; onChange: (id: number | null) => void
}) {
  const { data: cats } = useCategories()
  const { t } = useTranslation()
  const data = useMemo(() => {
    const groups: { group: string; items: { value: string; label: string }[] }[] = []
    for (const k of kind ? [kind] : (['expense', 'income'] as const)) {
      const tops = (cats ?? []).filter((c) => c.kind === k && !c.parent_id)
      for (const top of tops) {
        const subs = (cats ?? []).filter((c) => c.parent_id === top.id)
        groups.push({
          group: kind ? top.name : `${t(`kinds.${k}`)} · ${top.name}`,
          items: [{ value: String(top.id), label: top.name }, ...subs.map((s) => ({ value: String(s.id), label: `${top.name} › ${s.name}` }))],
        })
      }
    }
    return groups
  }, [cats, kind, t])
  return (
    <Select
      searchable
      clearable
      {...rest}
      data={data}
      value={value ? String(value) : null}
      onChange={(v) => onChange(v ? Number(v) : null)}
      comboboxProps={{ withinPortal: true }}
      limit={400}
    />
  )
}

export function AccountSelect({ value, onChange, currency, ...rest }: Omit<SelectProps, 'data' | 'value' | 'onChange'> & {
  value: number | null | undefined; onChange: (id: number | null) => void; currency?: string
}) {
  const { data } = useAccounts()
  const options = (data ?? []).filter((a) => !currency || a.currency === currency)
    .map((a) => ({ value: String(a.id), label: `${a.name} (${a.currency})` }))
  return <Select {...rest} data={options} value={value ? String(value) : null} onChange={(v) => onChange(v ? Number(v) : null)} />
}

export function ProjectSelect({ value, onChange, ...rest }: Omit<SelectProps, 'data' | 'value' | 'onChange'> & {
  value: number | null | undefined; onChange: (id: number | null) => void
}) {
  const { data } = useProjects()
  const options = (data ?? []).filter((p) => !p.archived_at || p.id === value).map((p) => ({ value: String(p.id), label: p.name }))
  return <Select clearable searchable {...rest} data={options} value={value ? String(value) : null} onChange={(v) => onChange(v ? Number(v) : null)} />
}

export function KindBadge({ kind }: { kind: string }) {
  const { t } = useTranslation()
  const color = { expense: 'gray', income: 'teal', transfer: 'blue', debt_payment: 'grape', adjustment: 'orange',
    investment: 'indigo', earmark: 'pink' }[kind] ?? 'gray'
  return <Badge variant="light" color={color} size="sm">{t(`kinds.${kind}`)}</Badge>
}

export function Empty({ children }: { children?: ReactNode }) {
  const { t } = useTranslation()
  return <Stack align="center" py="xl"><Text c="dimmed">{children ?? t('common.nothing')}</Text></Stack>
}
