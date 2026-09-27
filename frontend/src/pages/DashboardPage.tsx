import { useState } from 'react'
import { Alert, Anchor, Group, Progress, SimpleGrid, Stack, Table, Text, Title, Tooltip } from '@mantine/core'
import { MonthPickerInput } from '@mantine/dates'
import { IconAlertTriangle, IconFileImport } from '@tabler/icons-react'
import { useNavigate, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import dayjs from 'dayjs'
import type { EChartsOption } from 'echarts'
import { useReport } from '../api/hooks'
import type { Balances, Bridge, BudgetStatus, CatNode, MonthReport, Snapshot } from '../api/reports'
import type { ImportBatch } from '../api/client'
import { Chart, axisStyle, useChartColors } from '../components/Chart'
import { Empty, Money, Section, StatCard } from '../components/common'
import { formatMoney } from '../lib/money'
import { usePrefs } from '../lib/prefs'

function delta(cur: number, prev: number) {
  if (!prev) return null
  const pct = ((cur - prev) / Math.abs(prev)) * 100
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(0)}%`
}

export default function DashboardPage() {
  const { t } = useTranslation()
  const [month, setMonth] = useState(dayjs().format('YYYY-MM'))
  const { currencyMode } = usePrefs()
  const native = currencyMode === 'native'
  const start = dayjs(month + '-01')
  const monthEnd = start.endOf('month').format('YYYY-MM-DD')
  const report = useReport<MonthReport>(['month', month, native], `/api/v1/reports/month/${month}?native=${native}`)
  const budget = useReport<BudgetStatus>(['budget', month], `/api/v1/reports/budget/${month}`)
  const balances = useReport<Balances>(['balances', monthEnd], `/api/v1/reports/balances?on=${monthEnd}`)
  const nw = useReport<Snapshot[]>(['nw', month], `/api/v1/reports/net-worth?start=${start.subtract(23, 'month').format('YYYY-MM-DD')}&end=${monthEnd}`)
  const bridge = useReport<Bridge>(['bridge', month], `/api/v1/reports/net-worth-bridge?start=${start.format('YYYY-MM-DD')}&end=${monthEnd}`)
  const batches = useReport<ImportBatch[]>(['imports'], '/api/v1/imports')
  const m = report.data
  const s = m?.summary_ref
  const pendingRows = (batches.data ?? []).filter((b) => b.status === 'reviewing')
    .reduce((n, b) => {
      const st = JSON.parse(b.stats || '{}').status_counts ?? {}
      return n + (st.new ?? 0) + (st.suggested ?? 0) + (st.accepted ?? 0)
    }, 0)

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>{t('nav.dashboard')}</Title>
        <MonthPickerInput value={month + '-01'} onChange={(v) => v && setMonth(v.slice(0, 7))} valueFormat="MMMM YYYY" w={180} />
      </Group>

      {pendingRows > 0 && (
        <Alert color="yellow" icon={<IconFileImport size={18} />}>
          <Anchor component={Link} to="/import">{t('dash.reviewImports', { count: pendingRows })}</Anchor>
        </Alert>
      )}

      <SimpleGrid cols={{ base: 2, md: 4 }}>
        <StatCard label={t('common.income')} sub={s && `${delta(s.income, m!.compare_ref.prev_income) ?? '—'} ${t('dash.vsPrev')}`}>
          <Money value={s?.income} />
        </StatCard>
        <StatCard label={t('common.expenses')} sub={s && `${delta(s.expenses, m!.compare_ref.avg12_expenses) ?? '—'} ${t('dash.vsAvg')}`}>
          <Money value={s?.expenses} abs />
        </StatCard>
        <StatCard label={t('common.balance')}><Money value={s?.balance} colored sign /></StatCard>
        <StatCard label={t('dash.cashFlow')} sub={s && `${t('dash.principal')}: ${formatMoney(s.debt_principal_repaid)}`}>
          <Money value={s?.cash_flow} colored sign />
        </StatCard>
      </SimpleGrid>

      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        <Section title={t('dash.costsByCategory')}>
          {m && m.expense.length ? <CategoryBars nodes={m.expense} month={month} /> : <Empty>{t('dash.noData')}</Empty>}
        </Section>
        <Stack>
          <Section title={t('dash.costsByType')}>{m && <CostTypeBar data={m.by_cost_type} />}</Section>
          <Section title={t('dash.incomeByCategory')}>
            {m && m.income.length ? (
              <Table>
                <Table.Tbody>
                  {m.income.map((n) => (
                    <Table.Tr key={n.category_id}>
                      <Table.Td>{n.name}</Table.Td>
                      <Table.Td ta="right">{Object.entries(n.totals).map(([c, v]) => <div key={c}><Money value={v} currency={c} /></div>)}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            ) : <Empty />}
          </Section>
        </Stack>
      </SimpleGrid>

      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        <Section title={t('dash.budget')} right={<Anchor component={Link} to="/budget" size="sm">{t('nav.budget')}</Anchor>}>
          <BudgetBars data={budget.data} />
        </Section>
        <Section title={t('dash.balances')} right={<Anchor component={Link} to="/wealth/accounts" size="sm">{t('nav.accounts')}</Anchor>}>
          {balances.data && <BalancesList data={balances.data} />}
        </Section>
      </SimpleGrid>

      <Section title={t('dash.netWorth')}>
        <SimpleGrid cols={{ base: 1, lg: 3 }}>
          <Stack gap={4}>
            <Text fz={30} fw={700} className="num">{formatMoney(balances.data?.snapshot.net_worth)}</Text>
            <Components snap={balances.data?.snapshot} />
            <Text fw={600} mt="md" size="sm">{t('dash.bridge')}</Text>
            {bridge.data && <BridgeList data={bridge.data} />}
          </Stack>
          <div style={{ gridColumn: 'span 2' }}>{nw.data && <NetWorthChart data={nw.data} />}</div>
        </SimpleGrid>
      </Section>
    </Stack>
  )
}

function CategoryBars({ nodes, month }: { nodes: CatNode[]; month: string }) {
  const c = useChartColors()
  const nav = useNavigate()
  const currencies = [...new Set(nodes.flatMap((n) => Object.keys(n.totals)))]
  return (
    <Stack>
      {currencies.map((ccy) => {
        const rows = nodes.filter((n) => n.totals[ccy]).map((n) => ({ id: n.category_id, name: n.name, v: Math.abs(n.totals[ccy]) / 100 }))
          .sort((a, b) => a.v - b.v)
        const option: EChartsOption = {
          tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (v) => formatMoney(Number(v) * 100, ccy) },
          xAxis: { type: 'value', ...axisStyle(c), axisLabel: { color: c.text, formatter: (v: number) => formatMoney(v * 100, ccy, { compact: true }) } },
          yAxis: { type: 'category', data: rows.map((r) => r.name), ...axisStyle(c), splitLine: { show: false } },
          series: [{
            type: 'bar', data: rows.map((r) => r.v), barMaxWidth: 16, itemStyle: { color: c.series[0], borderRadius: [0, 4, 4, 0] },
            label: { show: true, position: 'right', color: c.text, formatter: (p) => formatMoney(Number(p.value) * 100, ccy, { compact: true }) },
          }],
          grid: { left: 8, right: 64, top: 8, bottom: 8, containLabel: true },
        }
        return (
          <div key={ccy}>
            {currencies.length > 1 && <Text size="xs" c="dimmed">{ccy}</Text>}
            <Chart option={option} height={Math.max(160, rows.length * 24 + 30)}
              onClick={(i) => nav(`/transactions?category_id=${rows[i].id}&start=${month}-01&end=${dayjs(month + '-01').endOf('month').format('YYYY-MM-DD')}`)} />
          </div>
        )
      })}
    </Stack>
  )
}

function CostTypeBar({ data }: { data: MonthReport['by_cost_type'] }) {
  const { t } = useTranslation()
  const c = useChartColors()
  const types = ['fixed', 'variable', 'one_time'] as const
  const ccys = [...new Set(types.flatMap((k) => Object.keys(data[k] ?? {})))]
  if (!ccys.length) return <Empty />
  const option: EChartsOption = {
    legend: { bottom: 0, textStyle: { color: c.text }, itemWidth: 12, itemHeight: 12 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    xAxis: { type: 'value', show: false },
    yAxis: { type: 'category', data: ccys, ...axisStyle(c), splitLine: { show: false }, axisLine: { show: false }, axisLabel: { color: c.text, margin: 12 } },
    grid: { left: 8, right: 8, top: 4, bottom: 28, containLabel: true },
    series: types.map((k, i) => ({
      name: t(`costType.${k}`),
      type: 'bar' as const,
      stack: 'total',
      barWidth: 22,
      itemStyle: { color: c.series[i], borderColor: c.surface, borderWidth: 2 },
      data: ccys.map((ccy) => Math.abs(data[k]?.[ccy] ?? 0) / 100),
      tooltip: { valueFormatter: (v) => formatMoney(Number(v) * 100, ccys[0]) },
      label: { show: true, color: '#fff', formatter: (p: { value: unknown; dataIndex: number }) => (Number(p.value) > 0 ? formatMoney(Number(p.value) * 100, ccys[p.dataIndex], { compact: true }) : '') },
    })),
  }
  return <Chart option={option} height={60 + ccys.length * 34} />
}

function BudgetBars({ data }: { data?: BudgetStatus }) {
  const { t } = useTranslation()
  const rows = (data?.rows ?? []).filter((r) => r.kind === 'expense')
  if (!rows.length) return <Empty>{t('budget.template')}: —</Empty>
  return (
    <Stack gap={8}>
      {rows.map((r) => {
        const over = r.planned > 0 && r.actual > r.planned
        return (
          <div key={`${r.category_id}-${r.currency}`}>
            <Group justify="space-between" gap={4}>
              <Text size="sm">{r.name}{!r.planned_line && <Text span c="dimmed" size="xs"> · {t('budget.unplanned')}</Text>}</Text>
              <Group gap={4}>
                {over && <Tooltip label={t('budget.over')}><IconAlertTriangle size={14} color="var(--mantine-color-red-6)" /></Tooltip>}
                <Text size="sm" className="num">{formatMoney(r.actual, r.currency)} / {formatMoney(r.planned, r.currency)}</Text>
              </Group>
            </Group>
            <Progress value={r.planned ? Math.min(100, (r.actual / r.planned) * 100) : 100} color={over ? 'red' : r.planned ? 'teal' : 'gray'} size="sm" />
          </div>
        )
      })}
    </Stack>
  )
}

function BalancesList({ data }: { data: Balances }) {
  const { t } = useTranslation()
  const byCcy = new Map<string, Balances['accounts']>()
  data.accounts.forEach((a) => byCcy.set(a.currency, [...(byCcy.get(a.currency) ?? []), a]))
  return (
    <Stack gap="xs">
      <Table>
        <Table.Tbody>
          {[...byCcy.entries()].map(([ccy, accs]) => accs.map((a) => (
            <Table.Tr key={a.account_id}>
              <Table.Td>{a.name}</Table.Td>
              <Table.Td ta="right"><Money value={a.balance} currency={ccy} colored={a.balance < 0} /></Table.Td>
              <Table.Td ta="right" c="dimmed">{ccy !== 'EUR' && <Money value={a.balance_ref} />}</Table.Td>
            </Table.Tr>
          )))}
        </Table.Tbody>
      </Table>
      <Group justify="space-between">
        <Text size="sm" fw={600}>{t('dash.available')}</Text>
        <Text size="sm" fw={600} className="num">{formatMoney(data.snapshot.available_funds)}</Text>
      </Group>
    </Stack>
  )
}

function Components({ snap }: { snap?: Snapshot }) {
  const { t } = useTranslation()
  if (!snap) return null
  const rows: [string, number][] = [
    [t('dash.funds'), snap.funds], [t('dash.investments'), snap.investments], [t('dash.assets'), snap.assets], [t('dash.debts'), -snap.debts],
  ]
  return (
    <Table>
      <Table.Tbody>
        {rows.map(([k, v]) => (
          <Table.Tr key={k}><Table.Td>{k}</Table.Td><Table.Td ta="right"><Money value={v} /></Table.Td></Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  )
}

function BridgeList({ data }: { data: Bridge }) {
  const { t } = useTranslation()
  const items = Object.entries(data.components).filter(([, v]) => v !== 0)
  if (!items.length) return <Text size="sm" c="dimmed">—</Text>
  return (
    <Table>
      <Table.Tbody>
        {items.map(([k, v]) => (
          <Table.Tr key={k}>
            <Table.Td><Text size="sm">{t(`dash.bridgeParts.${k}`)}</Text></Table.Td>
            <Table.Td ta="right"><Money value={v} sign colored /></Table.Td>
          </Table.Tr>
        ))}
        <Table.Tr>
          <Table.Td fw={600}>Δ</Table.Td>
          <Table.Td ta="right" fw={600}><Money value={data.net_worth_end - data.net_worth_start} sign /></Table.Td>
        </Table.Tr>
      </Table.Tbody>
    </Table>
  )
}

function NetWorthChart({ data }: { data: Snapshot[] }) {
  const c = useChartColors()
  const { t } = useTranslation()
  const option: EChartsOption = {
    tooltip: { trigger: 'axis', valueFormatter: (v) => formatMoney(Number(v) * 100) },
    legend: { bottom: 0, textStyle: { color: c.text }, itemWidth: 12, itemHeight: 12 },
    grid: { left: 8, right: 16, top: 16, bottom: 32, containLabel: true },
    xAxis: { type: 'category', data: data.map((d) => dayjs(d.date).format('MMM YY')), ...axisStyle(c), splitLine: { show: false } },
    yAxis: { type: 'value', ...axisStyle(c), axisLabel: { color: c.text, formatter: (v: number) => formatMoney(v * 100, 'EUR', { compact: true }) } },
    series: [
      { name: t('dash.netWorth'), type: 'line', data: data.map((d) => d.net_worth / 100), lineStyle: { width: 2 }, symbolSize: 8, showSymbol: false, color: c.series[0] },
      { name: t('dash.available'), type: 'line', data: data.map((d) => d.available_funds / 100), lineStyle: { width: 2 }, symbolSize: 8, showSymbol: false, color: c.series[1] },
    ],
  }
  return <Chart option={option} height={300} />
}
