import { useState } from 'react'
import { Badge, Button, Card, Group, Modal, Select, SimpleGrid, Stack, Table, Text, TextInput, Textarea, Title } from '@mantine/core'
import { DateInput } from '@mantine/dates'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import dayjs from 'dayjs'
import type { EChartsOption } from 'echarts'
import { request, type Account } from '../api/client'
import { LEDGER_KEYS, useAccounts, useApiMutation } from '../api/hooks'
import { Chart, axisStyle, useChartColors } from '../components/Chart'
import { Money, MoneyInput, Section } from '../components/common'
import { formatMoney } from '../lib/money'

type Recon = { date: string | null; source: string; stated: number | null; derived: number | null; difference: number | null; note: string | null }

export default function AccountsPage() {
  const { t } = useTranslation()
  const { data: accounts } = useAccounts()
  const [selected, setSelected] = useState<Account | null>(null)
  const [editing, setEditing] = useState<Partial<Account> | null>(null)
  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>{t('nav.accounts')}</Title>
        <Button onClick={() => setEditing({ type: 'current', currency: 'EUR', opening_date: dayjs().format('YYYY-MM-DD'), opening_balance: 0, identifiers: [] })}>
          {t('wealth.newAccount')}
        </Button>
      </Group>
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
        {(accounts ?? []).map((a) => (
          <Card key={a.id} withBorder className="clickable" onClick={() => setSelected(a)}>
            <Group justify="space-between">
              <Text fw={600}>{a.name}</Text>
              <Badge variant="light" size="sm">{a.type}</Badge>
            </Group>
            <Text fz={22} fw={650} className="num" mt={6}><Money value={a.balance} currency={a.currency} /></Text>
            {a.currency !== 'EUR' && <Text size="xs" c="dimmed"><Money value={a.balance_ref} /></Text>}
            <Text size="xs" c="dimmed" mt={4}>{t('wealth.lastReconciled')}: {a.last_reconciled ? dayjs(a.last_reconciled).format('DD-MM-YYYY') : '—'}</Text>
          </Card>
        ))}
      </SimpleGrid>
      {selected && <AccountDetail account={selected} onEdit={() => setEditing(selected)} />}
      {editing && <AccountForm initial={editing} onClose={() => setEditing(null)} />}
    </Stack>
  )
}

function AccountDetail({ account, onEdit }: { account: Account; onEdit: () => void }) {
  const { t } = useTranslation()
  const c = useChartColors()
  const start = dayjs().subtract(23, 'month').startOf('month').format('YYYY-MM-DD')
  const series = useQuery({
    queryKey: ['report', 'acct', account.id],
    queryFn: () => request<{ date: string; balance: number }[]>('GET', `/api/v1/accounts/${account.id}/balance-series?start=${start}&end=${dayjs().format('YYYY-MM-DD')}`),
  })
  const recon = useQuery({ queryKey: ['report', 'recon', account.id], queryFn: () => request<Recon[]>('GET', `/api/v1/accounts/${account.id}/reconciliation`) })
  const [date, setDate] = useState(dayjs().format('YYYY-MM-DD'))
  const [stated, setStated] = useState<number | null>(null)
  const reconcile = useApiMutation(
    () => request('POST', `/api/v1/accounts/${account.id}/reconcile`, { date, stated_balance: stated, create_adjustment: true }),
    LEDGER_KEYS, t('common.saved'),
  )
  const option: EChartsOption = {
    tooltip: { trigger: 'axis', valueFormatter: (v) => formatMoney(Number(v) * 100, account.currency) },
    xAxis: { type: 'category', data: (series.data ?? []).map((p) => dayjs(p.date).format('MMM YY')), ...axisStyle(c), splitLine: { show: false } },
    yAxis: { type: 'value', ...axisStyle(c), axisLabel: { color: c.text, formatter: (v: number) => formatMoney(v * 100, account.currency, { compact: true }) } },
    series: [{ type: 'line', data: (series.data ?? []).map((p) => p.balance / 100), color: c.series[0], lineStyle: { width: 2 }, showSymbol: false, areaStyle: { opacity: 0.08 } }],
  }
  return (
    <Section title={account.name} right={<Button size="xs" variant="default" onClick={onEdit}>{t('common.edit')}</Button>}>
      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        <Chart option={option} height={240} />
        <Stack gap="sm">
          <Group align="flex-end">
            <DateInput label={t('common.date')} value={date} onChange={(v) => v && setDate(v)} valueFormat="DD-MM-YYYY" w={140} />
            <MoneyInput label={t('wealth.statedBalance')} value={stated} onChange={setStated} currency={account.currency} w={160} />
            <Button onClick={() => reconcile.mutate(undefined)} disabled={stated === null} loading={reconcile.isPending}>{t('wealth.reconcile')}</Button>
          </Group>
          <Table>
            <Table.Thead>
              <Table.Tr><Table.Th>{t('common.date')}</Table.Th><Table.Th>{t('imp.source')}</Table.Th><Table.Th ta="right">{t('wealth.statedBalance')}</Table.Th><Table.Th ta="right">{t('wealth.difference')}</Table.Th></Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {(recon.data ?? []).slice(-12).reverse().map((r, i) => (
                <Table.Tr key={i}>
                  <Table.Td>{r.date ? dayjs(r.date).format('DD-MM-YY') : '—'}</Table.Td>
                  <Table.Td>{r.source}{r.note && <Text span size="xs" c="dimmed"> · {r.note}</Text>}</Table.Td>
                  <Table.Td ta="right"><Money value={r.stated} currency={account.currency} /></Table.Td>
                  <Table.Td ta="right">{r.difference === null ? '' : r.difference === 0 ? <Text span c="teal">✓</Text> : <Money value={r.difference} currency={account.currency} colored sign />}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Stack>
      </SimpleGrid>
    </Section>
  )
}

function AccountForm({ initial, onClose }: { initial: Partial<Account>; onClose: () => void }) {
  const { t } = useTranslation()
  const [f, setF] = useState(initial)
  const [idents, setIdents] = useState((initial.identifiers ?? []).map((i) => `${i.kind}:${i.value}`).join('\n'))
  const save = useApiMutation(async () => {
    const identifiers = idents.split('\n').map((l) => l.trim()).filter(Boolean).map((l) => {
      const [kind, value] = l.includes(':') ? l.split(':') : ['iban', l]
      return { kind, value }
    })
    const body = { ...f, identifiers }
    if (f.id) await request('PATCH', `/api/v1/accounts/${f.id}`, {
      name: f.name, institution: f.institution, opening_date: f.opening_date, opening_balance: f.opening_balance,
      include_in_net_worth: !!f.include_in_net_worth, sort_order: f.sort_order, identifiers,
    })
    else await request('POST', '/api/v1/accounts', body)
    onClose()
  }, LEDGER_KEYS, t('common.saved'))
  return (
    <Modal opened onClose={onClose} title={f.id ? f.name : t('wealth.newAccount')}>
      <Stack>
        <TextInput label={t('common.name')} value={f.name ?? ''} onChange={(e) => setF({ ...f, name: e.currentTarget.value })} />
        <Group grow>
          <Select label={t('common.type')} disabled={!!f.id} data={['current', 'savings', 'cash', 'credit_card', 'investment']} value={f.type} onChange={(v) => setF({ ...f, type: v ?? 'current' })} />
          <Select label={t('common.currency')} disabled={!!f.id} data={['EUR', 'RUB', 'USD', 'GBP']} value={f.currency} onChange={(v) => setF({ ...f, currency: v ?? 'EUR' })} />
        </Group>
        <TextInput label="Institution" value={f.institution ?? ''} onChange={(e) => setF({ ...f, institution: e.currentTarget.value })} />
        <Group grow>
          <DateInput label={t('wealth.openingDate')} value={f.opening_date} onChange={(v) => v && setF({ ...f, opening_date: v })} valueFormat="DD-MM-YYYY" />
          <MoneyInput label={t('wealth.openingBalance')} value={f.opening_balance ?? 0} onChange={(v) => setF({ ...f, opening_balance: v ?? 0 })} currency={f.currency} />
        </Group>
        <Textarea label={`${t('wealth.identifiers')} (iban:NL.., account_no:.., card_last4:..; one per line)`} rows={3}
          value={idents} onChange={(e) => setIdents(e.currentTarget.value)} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>{t('common.cancel')}</Button>
          <Button onClick={() => save.mutate(undefined)} loading={save.isPending}>{t('common.save')}</Button>
        </Group>
      </Stack>
    </Modal>
  )
}
