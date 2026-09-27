import { useState } from 'react'
import { Group, NumberInput, SegmentedControl, SimpleGrid, Stack, Table, Text, Title } from '@mantine/core'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import dayjs from 'dayjs'
import type { EChartsOption } from 'echarts'
import { useReport } from '../api/hooks'
import type { CatNode, YearReport } from '../api/reports'
import { Chart, SEQ_BLUE, axisStyle, useChartColors } from '../components/Chart'
import { Money, Section, Totals } from '../components/common'
import { formatMoney } from '../lib/money'
import { usePrefs } from '../lib/prefs'

export default function YearPage() {
  const { t } = useTranslation()
  const [year, setYear] = useState(dayjs().year())
  const [view, setView] = useState<'chart' | 'table'>('chart')
  const { currencyMode } = usePrefs()
  const native = currencyMode === 'native'
  const { data } = useReport<YearReport>(['year', year, native], `/api/v1/reports/year/${year}?native=${native}`)
  const currencies = data ? [...new Set(data.months.flatMap((m) => [...Object.keys(m.income), ...Object.keys(m.expenses)]))] : []
  const ccys = currencies.length ? currencies : ['EUR']

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>{t('nav.year')}</Title>
        <NumberInput value={year} onChange={(v) => setYear(Number(v) || year)} min={2019} max={2100} w={110} />
      </Group>

      <Section title={t('year.months')} right={
        <SegmentedControl size="xs" value={view} onChange={(v) => setView(v as 'chart' | 'table')}
          data={[{ value: 'chart', label: t('common.chart') }, { value: 'table', label: t('common.table') }]} />
      }>
        {data && view === 'chart' && <IncomeVsCosts data={data} ccy={ccys[0]} />}
        {data && view === 'table' && (
          <Table.ScrollContainer minWidth={600}>
            <Table striped>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t('common.month')}</Table.Th>
                  {ccys.map((c) => <Table.Th key={'i' + c} ta="right">{t('common.income')} {ccys.length > 1 && c}</Table.Th>)}
                  {ccys.map((c) => <Table.Th key={'e' + c} ta="right">{t('common.expenses')} {ccys.length > 1 && c}</Table.Th>)}
                  {ccys.map((c) => <Table.Th key={'b' + c} ta="right">{t('common.balance')} {ccys.length > 1 && c}</Table.Th>)}
                  <Table.Th ta="right">{t('year.funds')}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {data.months.map((m) => (
                  <Table.Tr key={m.month}>
                    <Table.Td>{dayjs(m.month + '-01').format('MMMM')}</Table.Td>
                    {ccys.map((c) => <Table.Td key={'i' + c} ta="right"><Money value={m.income[c] ?? 0} currency={c} /></Table.Td>)}
                    {ccys.map((c) => <Table.Td key={'e' + c} ta="right"><Money value={m.expenses[c] ?? 0} currency={c} abs /></Table.Td>)}
                    {ccys.map((c) => <Table.Td key={'b' + c} ta="right"><Money value={m.balance[c] ?? 0} currency={c} colored sign /></Table.Td>)}
                    <Table.Td ta="right"><Money value={m.funds_end_ref} /></Table.Td>
                  </Table.Tr>
                ))}
                <Table.Tr fw={700}>
                  <Table.Td>{t('common.total')}</Table.Td>
                  {ccys.map((c) => <Table.Td key={'i' + c} ta="right"><Money value={data.totals.income[c] ?? 0} currency={c} /></Table.Td>)}
                  {ccys.map((c) => <Table.Td key={'e' + c} ta="right"><Money value={data.totals.expense[c] ?? 0} currency={c} abs /></Table.Td>)}
                  {ccys.map((c) => <Table.Td key={'b' + c} ta="right"><Money value={(data.totals.income[c] ?? 0) + (data.totals.expense[c] ?? 0)} currency={c} colored sign /></Table.Td>)}
                  <Table.Td />
                </Table.Tr>
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
      </Section>

      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        <Section title={`${t('common.income')} — ${t('year.categories')}`}>{data && <CatTable nodes={data.income} year={year} />}</Section>
        <Section title={`${t('common.expenses')} — ${t('year.categories')}`}>{data && <CatTable nodes={data.expense} year={year} abs />}</Section>
      </SimpleGrid>

      <Section title={t('year.heatmap')}>{data && <Heatmap data={data} />}</Section>
    </Stack>
  )
}

function IncomeVsCosts({ data, ccy }: { data: YearReport; ccy: string }) {
  const c = useChartColors()
  const { t } = useTranslation()
  const option: EChartsOption = {
    legend: { bottom: 0, textStyle: { color: c.text }, itemWidth: 12, itemHeight: 12 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (v) => formatMoney(Number(v) * 100, ccy) },
    grid: { left: 8, right: 16, top: 16, bottom: 32, containLabel: true },
    xAxis: { type: 'category', data: data.months.map((m) => dayjs(m.month + '-01').format('MMM')), ...axisStyle(c), splitLine: { show: false } },
    yAxis: { type: 'value', ...axisStyle(c), axisLabel: { color: c.text, formatter: (v: number) => formatMoney(v * 100, ccy, { compact: true }) } },
    series: [
      { name: t('common.income'), type: 'bar', data: data.months.map((m) => (m.income[ccy] ?? 0) / 100), color: c.series[0],
        barGap: '10%', barMaxWidth: 18, itemStyle: { borderRadius: [4, 4, 0, 0] } },
      { name: t('common.expenses'), type: 'bar', data: data.months.map((m) => Math.abs(m.expenses[ccy] ?? 0) / 100), color: c.series[1],
        barMaxWidth: 18, itemStyle: { borderRadius: [4, 4, 0, 0] } },
    ],
  }
  return <Chart option={option} height={300} />
}

function CatTable({ nodes, year, abs }: { nodes: CatNode[]; year: number; abs?: boolean }) {
  const { t } = useTranslation()
  const nav = useNavigate()
  const sorted = [...nodes].sort((a, b) => Math.abs(Object.values(b.totals)[0] ?? 0) - Math.abs(Object.values(a.totals)[0] ?? 0))
  return (
    <Table highlightOnHover>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{t('common.category')}</Table.Th>
          <Table.Th ta="right">{t('common.total')}</Table.Th>
          <Table.Th ta="right">{t('year.avg')}</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {sorted.map((n) => (
          <Table.Tr key={n.category_id} className="clickable" onClick={() => nav(`/transactions?category_id=${n.category_id}&start=${year}-01-01&end=${year}-12-31`)}>
            <Table.Td>{n.name}</Table.Td>
            <Table.Td ta="right"><Totals totals={n.totals} abs={abs} /></Table.Td>
            <Table.Td ta="right" c="dimmed"><Totals totals={n.avg_per_month} abs={abs} /></Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  )
}

function Heatmap({ data }: { data: YearReport }) {
  const c = useChartColors()
  const rows = [...data.heatmap_ref].sort((a, b) => a.months.reduce((s, v) => s + v, 0) - b.months.reduce((s, v) => s + v, 0)).reverse()
  const values = rows.flatMap((r, y) => r.months.map((v, x) => [x, y, Math.abs(v) / 100]))
  const max = Math.max(1, ...values.map((v) => v[2]))
  if (!rows.length) return <Text c="dimmed">—</Text>
  const option: EChartsOption = {
    tooltip: { trigger: 'item', formatter: (p: unknown) => {
      const d = (p as { data: number[] }).data
      return `${rows[d[1]].name} · ${dayjs().month(d[0]).format('MMM')}: ${formatMoney(d[2] * 100)}`
    } },
    grid: { left: 8, right: 16, top: 8, bottom: 48, containLabel: true },
    xAxis: { type: 'category', data: Array.from({ length: 12 }, (_, i) => dayjs().month(i).format('MMM')), ...axisStyle(c), splitLine: { show: false } },
    yAxis: { type: 'category', data: rows.map((r) => r.name), ...axisStyle(c), splitLine: { show: false }, inverse: true },
    visualMap: { min: 0, max, calculable: false, orient: 'horizontal', left: 'center', bottom: 0, inRange: { color: SEQ_BLUE }, textStyle: { color: c.text },
      formatter: (v: unknown) => formatMoney(Number(v) * 100, 'EUR', { compact: true }) },
    series: [{ type: 'heatmap', data: values, itemStyle: { borderColor: c.surface, borderWidth: 2, borderRadius: 3 } }],
  }
  return <Chart option={option} height={Math.max(220, rows.length * 22 + 70)} />
}
