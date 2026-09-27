import { useState } from 'react'
import { ActionIcon, Button, Group, Progress, Select, SimpleGrid, Stack, Table, Text, TextInput, Title } from '@mantine/core'
import { MonthPickerInput } from '@mantine/dates'
import { IconTrash } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import dayjs from 'dayjs'
import { request } from '../api/client'
import { useApiMutation, useLookups, useReport } from '../api/hooks'
import type { BudgetStatus } from '../api/reports'
import { CategorySelect, Empty, Money, MoneyInput, Section } from '../components/common'
import { parseMoney } from '../lib/money'

type Line = { id: number; month: string; category_id: number; amount: number; currency: string; template_line_id: number | null; note: string | null }
type TLine = { id: number; category_id: number; label: string | null; amount: number; currency: string; valid_from: string; valid_to: string | null }

export default function BudgetPage() {
  const { t } = useTranslation()
  const lk = useLookups()
  const [month, setMonth] = useState(dayjs().format('YYYY-MM'))
  const status = useReport<BudgetStatus>(['budget', month], `/api/v1/reports/budget/${month}`)
  const lines = useQuery({ queryKey: ['budget', month], queryFn: () => request<Line[]>('GET', `/api/v1/budget/${month}`) })
  const template = useQuery({ queryKey: ['budget', 'template'], queryFn: () => request<TLine[]>('GET', '/api/v1/budget/template') })
  const keys = [['budget'], ['report']]
  const generate = useApiMutation(() => request('POST', `/api/v1/budget/${month}/generate`), keys)
  const patchLine = useApiMutation((v: { id: number; amount: number }) => request('PATCH', `/api/v1/budget/lines/${v.id}`, { amount: v.amount }), keys)
  const delLine = useApiMutation((id: number) => request('DELETE', `/api/v1/budget/lines/${id}`), keys)
  const addLine = useApiMutation((v: { category_id: number; amount: number; currency: string }) => request('POST', `/api/v1/budget/${month}/lines`, v), keys)
  const addT = useApiMutation((v: Omit<TLine, 'id'>) => request('POST', '/api/v1/budget/template', v), keys)
  const delT = useApiMutation((id: number) => request('DELETE', `/api/v1/budget/template/${id}`), keys)
  const [newCat, setNewCat] = useState<number | null>(null)
  const [newAmount, setNewAmount] = useState<number | null>(null)
  const [newCcy, setNewCcy] = useState('EUR')
  const [tCat, setTCat] = useState<number | null>(null)
  const [tAmount, setTAmount] = useState<number | null>(null)
  const [tLabel, setTLabel] = useState('')
  const [tFrom, setTFrom] = useState(dayjs().format('YYYY-MM'))

  const rows = status.data?.rows ?? []
  const byType = { expense: rows.filter((r) => r.kind === 'expense'), income: rows.filter((r) => r.kind === 'income') }

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>{t('nav.budget')}</Title>
        <Group>
          <MonthPickerInput value={month + '-01'} onChange={(v) => v && setMonth(v.slice(0, 7))} valueFormat="MMMM YYYY" w={180} />
          <Button variant="light" onClick={() => generate.mutate(undefined)} loading={generate.isPending}>{t('budget.generate')}</Button>
        </Group>
      </Group>

      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        {(['expense', 'income'] as const).map((kind) => (
          <Section key={kind} title={kind === 'expense' ? t('common.expenses') : t('common.income')}>
            {byType[kind].length ? (
              <Table>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>{t('common.category')}</Table.Th>
                    <Table.Th ta="right">{t('budget.plan')}</Table.Th>
                    <Table.Th ta="right">{t('budget.actual')}</Table.Th>
                    <Table.Th ta="right">{t('budget.remaining')}</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {byType[kind].map((r) => (
                    <Table.Tr key={`${r.category_id}${r.currency}`}>
                      <Table.Td>
                        <Text size="sm">{r.name}</Text>
                        {r.planned > 0 && <Progress size={4} value={Math.min(100, (r.actual / r.planned) * 100)} color={r.actual > r.planned && kind === 'expense' ? 'red' : 'teal'} />}
                      </Table.Td>
                      <Table.Td ta="right"><Money value={r.planned} currency={r.currency} /></Table.Td>
                      <Table.Td ta="right"><Money value={r.actual} currency={r.currency} /></Table.Td>
                      <Table.Td ta="right"><Money value={r.remaining} currency={r.currency} colored={kind === 'expense' && r.remaining < 0} /></Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            ) : <Empty />}
          </Section>
        ))}
      </SimpleGrid>

      <Section title={`${t('budget.plan')} — ${dayjs(month + '-01').format('MMMM YYYY')}`}>
        <Table>
          <Table.Tbody>
            {(lines.data ?? []).map((l) => (
              <Table.Tr key={l.id}>
                <Table.Td>{lk.categoryPath(l.category_id)}{l.note && <Text span c="dimmed" size="xs"> · {l.note}</Text>}</Table.Td>
                <Table.Td w={160}>
                  <MoneyInput size="xs" value={l.amount} currency={l.currency}
                    onChange={() => {}} onBlur={(e) => {
                      const v = parseMoney(e.currentTarget.value)
                      if (v !== null && v !== l.amount) patchLine.mutate({ id: l.id, amount: Math.abs(v) })
                    }} />
                </Table.Td>
                <Table.Td w={40}><ActionIcon variant="subtle" color="red" onClick={() => delLine.mutate(l.id)}><IconTrash size={14} /></ActionIcon></Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        <Group mt="sm" align="flex-end">
          <CategorySelect label={t('budget.addLine')} value={newCat} onChange={setNewCat} w={260} />
          <MoneyInput label={t('common.amount')} value={newAmount} onChange={setNewAmount} w={130} />
          <Select label={t('common.currency')} data={['EUR', 'RUB']} value={newCcy} onChange={(v) => setNewCcy(v ?? 'EUR')} w={90} />
          <Button disabled={!newCat || !newAmount} onClick={() => { addLine.mutate({ category_id: newCat!, amount: Math.abs(newAmount!), currency: newCcy }); setNewAmount(null) }}>{t('common.add')}</Button>
        </Group>
      </Section>

      <Section title={t('budget.template')}>
        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t('common.category')}</Table.Th>
              <Table.Th>{t('common.description')}</Table.Th>
              <Table.Th ta="right">{t('common.amount')}</Table.Th>
              <Table.Th>{t('budget.validFrom')}</Table.Th>
              <Table.Th>{t('budget.validTo')}</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {(template.data ?? []).map((l) => (
              <Table.Tr key={l.id}>
                <Table.Td>{lk.categoryPath(l.category_id)}</Table.Td>
                <Table.Td>{l.label}</Table.Td>
                <Table.Td ta="right"><Money value={l.amount} currency={l.currency} /></Table.Td>
                <Table.Td>{l.valid_from}</Table.Td>
                <Table.Td>{l.valid_to ?? '—'}</Table.Td>
                <Table.Td w={40}><ActionIcon variant="subtle" color="red" onClick={() => delT.mutate(l.id)}><IconTrash size={14} /></ActionIcon></Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        <Group mt="sm" align="flex-end">
          <CategorySelect label={t('common.category')} value={tCat} onChange={setTCat} w={240} />
          <TextInput label={t('common.description')} value={tLabel} onChange={(e) => setTLabel(e.currentTarget.value)} w={150} />
          <MoneyInput label={t('common.amount')} value={tAmount} onChange={setTAmount} w={120} />
          <TextInput label={t('budget.validFrom')} value={tFrom} onChange={(e) => setTFrom(e.currentTarget.value)} w={110} />
          <Button disabled={!tCat || !tAmount} onClick={() => {
            addT.mutate({ category_id: tCat!, amount: Math.abs(tAmount!), currency: 'EUR', label: tLabel || null, valid_from: tFrom, valid_to: null })
            setTAmount(null)
            setTLabel('')
          }}>{t('common.add')}</Button>
        </Group>
      </Section>
    </Stack>
  )
}
