import { useMemo, useState } from 'react'
import { Badge, Button, Checkbox, Group, MultiSelect, Paper, Select, Stack, Table, Text, TextInput, Title } from '@mantine/core'
import { DatePickerInput } from '@mantine/dates'
import { IconSearch } from '@tabler/icons-react'
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import dayjs from 'dayjs'
import { request, type Txn } from '../api/client'
import { LEDGER_KEYS, notifyError, useAccounts, useLookups } from '../api/hooks'
import { CategorySelect, Empty, KindBadge, Money, ProjectSelect, Totals } from '../components/common'
import { useTxnEditor } from '../components/TxnEditor'

type Page = { items: Txn[]; next_cursor: string | null; totals: Record<string, number>; totals_ref: number }

export default function TransactionsPage() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const { openEdit } = useTxnEditor()
  const lk = useLookups()
  const { data: accounts } = useAccounts()
  const qc = useQueryClient()
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [bulkCat, setBulkCat] = useState<number | null>(null)
  const [bulkProject, setBulkProject] = useState<number | null>(null)
  const [bulkCost, setBulkCost] = useState<string | null>(null)

  const filter = Object.fromEntries(params.entries())
  const setFilter = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params)
    Object.entries(patch).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)))
    setParams(next, { replace: true })
    setSelected(new Set())
  }
  const qs = params.toString()

  const q = useInfiniteQuery({
    queryKey: ['txns', qs],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => {
      const p = new URLSearchParams(params)
      if (pageParam) p.set('cursor', pageParam)
      p.set('limit', '100')
      return request<Page>('GET', `/api/v1/txns?${p}`)
    },
    getNextPageParam: (last) => last.next_cursor,
  })
  const items = useMemo(() => q.data?.pages.flatMap((p) => p.items) ?? [], [q.data])
  const first = q.data?.pages[0]

  async function bulkApply() {
    try {
      await request('POST', '/api/v1/txns/bulk-update', {
        txn_ids: [...selected], category_id: bulkCat, project_id: bulkProject, cost_type: bulkCost,
      })
      setSelected(new Set())
      LEDGER_KEYS.forEach((k) => qc.invalidateQueries({ queryKey: k }))
    } catch (e) {
      notifyError(e)
    }
  }

  const splitLabel = (tx: Txn) => {
    const cats = tx.splits.filter((s) => s.category_id).map((s) => lk.categoryPath(s.category_id))
    const debts = tx.splits.filter((s) => s.debt_id).map((s) => lk.debts.get(s.debt_id!)?.name)
    const ems = tx.splits.filter((s) => s.earmark_id).map((s) => lk.earmarks.get(s.earmark_id!)?.name)
    return [...new Set([...cats, ...debts, ...ems])].filter(Boolean).join(', ')
  }

  return (
    <Stack>
      <Title order={3}>{t('nav.transactions')}</Title>
      <Paper withBorder p="sm">
        <Group gap="xs" align="flex-end" wrap="wrap">
          <DatePickerInput
            type="range"
            label={t('common.date')}
            value={[filter.start ?? null, filter.end ?? null]}
            onChange={([a, b]) => setFilter({ start: a, end: b })}
            valueFormat="DD-MM-YYYY"
            clearable
            w={230}
          />
          <MultiSelect
            label={t('common.account')}
            data={(accounts ?? []).map((a) => ({ value: String(a.id), label: a.name }))}
            value={params.getAll('account_id')}
            onChange={(v) => {
              const next = new URLSearchParams(params)
              next.delete('account_id')
              v.forEach((x) => next.append('account_id', x))
              setParams(next, { replace: true })
            }}
            w={220}
            clearable
          />
          <CategorySelect label={t('common.category')} value={filter.category_id ? Number(filter.category_id) : null}
            onChange={(v) => setFilter({ category_id: v ? String(v) : null })} w={220} />
          <Select label={t('common.kind')} clearable w={150}
            data={['expense', 'income', 'transfer', 'debt_payment', 'investment', 'earmark', 'adjustment'].map((k) => ({ value: k, label: t(`kinds.${k}`) }))}
            value={filter.kind ?? null} onChange={(v) => setFilter({ kind: v })} />
          <Select label={t('txn.costType')} clearable w={140}
            data={['fixed', 'variable', 'one_time'].map((k) => ({ value: k, label: t(`costType.${k}`) }))}
            value={filter.cost_type ?? null} onChange={(v) => setFilter({ cost_type: v })} />
          <ProjectSelect label={t('common.project')} value={filter.project_id ? Number(filter.project_id) : null}
            onChange={(v) => setFilter({ project_id: v ? String(v) : null })} w={170} />
          <TextInput label={t('common.search')} leftSection={<IconSearch size={14} />} defaultValue={filter.text ?? ''}
            onKeyDown={(e) => e.key === 'Enter' && setFilter({ text: e.currentTarget.value || null })}
            onBlur={(e) => setFilter({ text: e.currentTarget.value || null })} w={180} />
          <Checkbox label={t('txn.uncategorised')} checked={filter.uncategorised === 'true'}
            onChange={(e) => setFilter({ uncategorised: e.currentTarget.checked ? 'true' : null })} mb={8} />
        </Group>
      </Paper>

      <Group justify="space-between">
        <Text size="sm" c="dimmed">{t('common.total')}: <Totals totals={first?.totals} /> {first && Object.keys(first.totals).length > 1 && <>· <Money value={first.totals_ref} /></>}</Text>
        {selected.size > 0 && (
          <Group gap="xs">
            <Badge>{t('txn.bulk', { count: selected.size })}</Badge>
            <CategorySelect size="xs" placeholder={t('txn.setCategory')} value={bulkCat} onChange={setBulkCat} w={200} />
            <Select size="xs" placeholder={t('txn.costType')} clearable w={130} value={bulkCost} onChange={setBulkCost}
              data={['fixed', 'variable', 'one_time'].map((k) => ({ value: k, label: t(`costType.${k}`) }))} />
            <ProjectSelect size="xs" placeholder={t('txn.setProject')} value={bulkProject} onChange={setBulkProject} w={160} />
            <Button size="xs" onClick={bulkApply} disabled={!bulkCat && !bulkProject && !bulkCost}>{t('common.apply')}</Button>
          </Group>
        )}
      </Group>

      <Table.ScrollContainer minWidth={800}>
        <Table highlightOnHover verticalSpacing={6}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th w={32}>
                <Checkbox size="xs" checked={items.length > 0 && selected.size === items.length}
                  onChange={(e) => setSelected(e.currentTarget.checked ? new Set(items.map((i) => i.id)) : new Set())} />
              </Table.Th>
              <Table.Th>{t('common.date')}</Table.Th>
              <Table.Th>{t('common.description')}</Table.Th>
              <Table.Th>{t('common.category')}</Table.Th>
              <Table.Th>{t('common.account')}</Table.Th>
              <Table.Th ta="right">{t('common.amount')}</Table.Th>
              <Table.Th ta="right">EUR</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {items.map((tx) => {
              const legs = tx.legs
              const main = legs.find((l) => l.amount < 0) ?? legs[0]
              const acc = main ? lk.accounts.get(main.account_id) : null
              const cost = tx.splits.find((s) => s.cost_type)?.cost_type
              const project = tx.splits.find((s) => s.project_id)?.project_id
              return (
                <Table.Tr key={tx.id} className="clickable" onClick={() => openEdit(tx)}>
                  <Table.Td onClick={(e) => e.stopPropagation()}>
                    <Checkbox size="xs" checked={selected.has(tx.id)} onChange={(e) => {
                      const next = new Set(selected)
                      if (e.currentTarget.checked) next.add(tx.id)
                      else next.delete(tx.id)
                      setSelected(next)
                    }} />
                  </Table.Td>
                  <Table.Td className="num">{dayjs(tx.date).format('DD-MM-YY')}</Table.Td>
                  <Table.Td maw={320}>
                    <Group gap={6} wrap="nowrap">
                      {tx.kind !== 'expense' && tx.kind !== 'income' && <KindBadge kind={tx.kind} />}
                      <Text size="sm" truncate>{tx.description || tx.counterparty || '—'}</Text>
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{splitLabel(tx) || (tx.kind === 'transfer' ? `→ ${legs.filter((l) => l !== main).map((l) => lk.accounts.get(l.account_id)?.name).join(', ')}` : '')}</Text>
                    {(cost || project) && (
                      <Text size="xs" c="dimmed">{[cost && t(`costType.${cost}`), project && lk.projects.get(project)?.name].filter(Boolean).join(' · ')}</Text>
                    )}
                  </Table.Td>
                  <Table.Td><Text size="sm">{acc?.name}</Text></Table.Td>
                  <Table.Td ta="right"><Money value={main?.amount} currency={acc?.currency} colored={!!main && main.amount > 0} /></Table.Td>
                  <Table.Td ta="right" c="dimmed">{acc?.currency !== 'EUR' && <Money value={main?.amount_ref} />}</Table.Td>
                </Table.Tr>
              )
            })}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {!q.isLoading && items.length === 0 && <Empty />}
      {q.hasNextPage && <Button variant="default" onClick={() => q.fetchNextPage()} loading={q.isFetchingNextPage}>{t('txn.loadMore')}</Button>}
    </Stack>
  )
}
