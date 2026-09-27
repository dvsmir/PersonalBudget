import { useState } from 'react'
import { ActionIcon, Button, Card, Group, Modal, NumberInput, Progress, Select, SimpleGrid, Stack, Table, Text, TextInput, Title } from '@mantine/core'
import { DateInput } from '@mantine/dates'
import { IconPlus, IconTrash } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import dayjs from 'dayjs'
import { request, type Debt } from '../api/client'
import { LEDGER_KEYS, useApiMutation, useDebts, useReport } from '../api/hooks'
import type { DebtOverview } from '../api/reports'
import { CategorySelect, Money, MoneyInput, Section } from '../components/common'

export default function DebtsPage() {
  const { t } = useTranslation()
  const overview = useReport<DebtOverview[]>(['debts'], '/api/v1/reports/debts')
  const { data: debts } = useDebts()
  const [edit, setEdit] = useState<Partial<Debt> | null>(null)
  const [scheduleFor, setScheduleFor] = useState<number | null>(null)
  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>{t('nav.debts')}</Title>
        <Button onClick={() => setEdit({ type: 'loan', repayment_type: 'annuity', currency: 'EUR', principal_original: 0, start_date: dayjs().format('YYYY-MM-DD'), rate_periods: [] })}>
          {t('wealth.newDebt')}
        </Button>
      </Group>
      <SimpleGrid cols={{ base: 1, md: 2 }}>
        {(overview.data ?? []).map((d) => {
          const repaid = d.original ? Math.max(0, Math.min(100, ((d.original - d.outstanding) / d.original) * 100)) : 0
          const debt = debts?.find((x) => x.id === d.debt_id)
          return (
            <Card key={d.debt_id} withBorder>
              <Group justify="space-between">
                <Text fw={600}>{d.name}</Text>
                <Group gap={4}>
                  <Button size="compact-xs" variant="subtle" onClick={() => setScheduleFor(d.debt_id)}>{t('wealth.schedule')}</Button>
                  {debt && <Button size="compact-xs" variant="subtle" onClick={() => setEdit(debt)}>{t('common.edit')}</Button>}
                </Group>
              </Group>
              <Text fz={22} fw={650} className="num" mt={4}><Money value={d.outstanding} currency={d.currency} /></Text>
              <Progress value={repaid} size="sm" mt={6} />
              <Group justify="space-between" mt={6}>
                <Text size="xs" c="dimmed">{t('wealth.original')}: <Money value={d.original} currency={d.currency} /></Text>
                <Text size="xs" c="dimmed">{t('wealth.payoff')}: {d.payoff_date ? dayjs(d.payoff_date).format('MM-YYYY') : '—'}</Text>
              </Group>
              <Text size="sm" mt={6}>{t('wealth.repaidYtd')}: <Money value={d.ytd.principal_repaid} currency={d.currency} /> · {t('wealth.interestYtd')}: <Money value={d.ytd.interest_paid} currency={d.currency} /></Text>
              {d.parts.length > 0 && (
                <Table mt="xs">
                  <Table.Tbody>
                    {d.parts.map((p) => {
                      const part = debts?.find((x) => x.id === p.debt_id)
                      return (
                        <Table.Tr key={p.debt_id} className="clickable" onClick={() => part && setEdit(part)}>
                          <Table.Td><Text size="sm">{p.name}</Text></Table.Td>
                          <Table.Td ta="right"><Text size="sm">{(Number(p.rate) * 100).toFixed(2)}%</Text></Table.Td>
                          <Table.Td ta="right"><Money value={p.outstanding} currency={d.currency} /></Table.Td>
                        </Table.Tr>
                      )
                    })}
                  </Table.Tbody>
                </Table>
              )}
            </Card>
          )
        })}
      </SimpleGrid>
      {scheduleFor && <Schedule debtId={scheduleFor} />}
      {edit && <DebtForm initial={edit} onClose={() => setEdit(null)} />}
    </Stack>
  )
}

function Schedule({ debtId }: { debtId: number }) {
  const { t } = useTranslation()
  const { data } = useQuery({
    queryKey: ['report', 'schedule', debtId],
    queryFn: () => request<{ date: string; payment: number; interest: number; principal: number; balance_after: number; actual_principal: number }[]>('GET', `/api/v1/debts/${debtId}/schedule`),
  })
  const today = dayjs()
  const rows = (data ?? []).filter((r) => dayjs(r.date).isAfter(today.subtract(12, 'month')) && dayjs(r.date).isBefore(today.add(24, 'month')))
  return (
    <Section title={t('wealth.schedule')}>
      {!rows.length ? <Text c="dimmed" size="sm">—</Text> : (
        <Table.ScrollContainer minWidth={500}>
          <Table striped>
            <Table.Thead>
              <Table.Tr><Table.Th>{t('common.date')}</Table.Th><Table.Th ta="right">{t('common.amount')}</Table.Th><Table.Th ta="right">{t('txn.interest')}</Table.Th><Table.Th ta="right">{t('txn.principal')}</Table.Th><Table.Th ta="right">{t('budget.actual')}</Table.Th><Table.Th ta="right">{t('wealth.outstanding')}</Table.Th></Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((r) => (
                <Table.Tr key={r.date}>
                  <Table.Td>{dayjs(r.date).format('MM-YYYY')}</Table.Td>
                  <Table.Td ta="right"><Money value={r.payment} /></Table.Td>
                  <Table.Td ta="right"><Money value={r.interest} /></Table.Td>
                  <Table.Td ta="right"><Money value={r.principal} /></Table.Td>
                  <Table.Td ta="right"><Money value={r.actual_principal} /></Table.Td>
                  <Table.Td ta="right"><Money value={r.balance_after} /></Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Section>
  )
}

function DebtForm({ initial, onClose }: { initial: Partial<Debt>; onClose: () => void }) {
  const { t } = useTranslation()
  const { data: debts } = useDebts()
  const [f, setF] = useState<Partial<Debt>>(initial)
  const [rates, setRates] = useState((initial.rate_periods ?? []).map((r) => ({ from_date: r.from_date, pct: Number(r.annual_rate) * 100 })))
  const [snapDate, setSnapDate] = useState(dayjs().format('YYYY-MM-DD'))
  const [snapBal, setSnapBal] = useState<number | null>(null)
  const set = (p: Partial<Debt>) => setF({ ...f, ...p })
  const save = useApiMutation(async () => {
    const rate_periods = rates.filter((r) => r.from_date).map((r) => ({ from_date: r.from_date, annual_rate: (r.pct / 100).toFixed(6) }))
    const body = {
      name: f.name, lender: f.lender, principal_original: f.principal_original, start_date: f.start_date, term_months: f.term_months || null,
      payment_day: f.payment_day || null, interest_category_id: f.interest_category_id, lender_identifier: f.lender_identifier || null,
      repayment_type: f.repayment_type, rate_periods, closed_at: f.closed_at || null,
    }
    if (f.id) await request('PATCH', `/api/v1/debts/${f.id}`, body)
    else await request('POST', '/api/v1/debts', { ...body, currency: f.currency, type: f.type, parent_debt_id: f.parent_debt_id ?? null })
    onClose()
  }, LEDGER_KEYS, t('common.saved'))
  const snapshot = useApiMutation(() => request('POST', `/api/v1/debts/${f.id}/snapshots`, { date: snapDate, balance: snapBal }), LEDGER_KEYS, t('common.saved'))
  const isGroup = f.repayment_type === 'group'
  return (
    <Modal opened onClose={onClose} title={f.name || t('wealth.newDebt')} size="lg">
      <Stack>
        <Group grow>
          <TextInput label={t('common.name')} value={f.name ?? ''} onChange={(e) => set({ name: e.currentTarget.value })} />
          <TextInput label="Lender" value={f.lender ?? ''} onChange={(e) => set({ lender: e.currentTarget.value })} />
        </Group>
        <Group grow>
          <Select label={t('common.type')} disabled={!!f.id} data={['mortgage', 'loan', 'personal', 'other']} value={f.type} onChange={(v) => set({ type: v ?? 'loan' })} />
          <Select label="Repayment" data={['annuity', 'linear', 'interest_only', 'free', 'group']} value={f.repayment_type} onChange={(v) => set({ repayment_type: v ?? 'annuity' })} />
          <Select label={t('common.currency')} disabled={!!f.id} data={['EUR', 'RUB']} value={f.currency} onChange={(v) => set({ currency: v ?? 'EUR' })} />
        </Group>
        {!f.id && (
          <Select label="Part of" clearable data={(debts ?? []).filter((d) => d.repayment_type === 'group').map((d) => ({ value: String(d.id), label: d.name }))}
            value={f.parent_debt_id ? String(f.parent_debt_id) : null} onChange={(v) => set({ parent_debt_id: v ? Number(v) : null })} />
        )}
        {!isGroup && (
          <>
            <Group grow>
              <MoneyInput label={t('wealth.original')} value={f.principal_original ?? 0} onChange={(v) => set({ principal_original: v ?? 0 })} currency={f.currency} />
              <DateInput label={t('common.from')} value={f.start_date} onChange={(v) => v && set({ start_date: v })} valueFormat="DD-MM-YYYY" />
              <NumberInput label={t('wealth.term')} value={f.term_months ?? ''} onChange={(v) => set({ term_months: Number(v) || null })} />
            </Group>
            <Text size="sm" fw={600}>{t('wealth.ratePeriods')}</Text>
            {rates.map((r, i) => (
              <Group key={i} align="flex-end">
                <DateInput label={i === 0 ? t('common.from') : undefined} value={r.from_date} onChange={(v) => setRates(rates.map((x, j) => (j === i ? { ...x, from_date: v ?? '' } : x)))} valueFormat="DD-MM-YYYY" w={150} />
                <NumberInput label={i === 0 ? `${t('wealth.rate')} %` : undefined} value={r.pct} decimalScale={3} onChange={(v) => setRates(rates.map((x, j) => (j === i ? { ...x, pct: Number(v) } : x)))} w={120} />
                <ActionIcon variant="subtle" color="red" mb={4} onClick={() => setRates(rates.filter((_, j) => j !== i))}><IconTrash size={14} /></ActionIcon>
              </Group>
            ))}
            <Button size="xs" variant="subtle" leftSection={<IconPlus size={14} />} onClick={() => setRates([...rates, { from_date: f.start_date ?? '', pct: 0 }])}>{t('common.add')}</Button>
          </>
        )}
        <Group grow>
          <CategorySelect label={`${t('txn.interest')} → ${t('common.category')}`} kind="expense" value={f.interest_category_id} onChange={(v) => set({ interest_category_id: v })} />
          <TextInput label={t('wealth.lenderPattern')} value={f.lender_identifier ?? ''} onChange={(e) => set({ lender_identifier: e.currentTarget.value })} />
        </Group>
        {f.id && !isGroup && (
          <Group align="flex-end">
            <DateInput label={t('wealth.snapshot')} value={snapDate} onChange={(v) => v && setSnapDate(v)} valueFormat="DD-MM-YYYY" w={150} />
            <MoneyInput label={t('wealth.outstanding')} value={snapBal} onChange={setSnapBal} currency={f.currency} w={160} />
            <Button variant="default" disabled={snapBal === null} onClick={() => snapshot.mutate(undefined)}>{t('common.add')}</Button>
          </Group>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>{t('common.cancel')}</Button>
          <Button onClick={() => save.mutate(undefined)} loading={save.isPending}>{t('common.save')}</Button>
        </Group>
      </Stack>
    </Modal>
  )
}
