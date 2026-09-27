import { useState } from 'react'
import { Alert, Badge, Button, Checkbox, Group, Menu, Pagination, SegmentedControl, Select, Stack, Table, Text, TextInput, Title, Tooltip } from '@mantine/core'
import { IconChevronDown, IconSparkles } from '@tabler/icons-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { notifications } from '@mantine/notifications'
import { useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import dayjs from 'dayjs'
import { ApiError, request, type ImportBatch } from '../api/client'
import { LEDGER_KEYS, notifyError, useLookups } from '../api/hooks'
import type { ImportRowView } from '../api/reports'
import { CategorySelect, KindBadge, Money } from '../components/common'

type Filter = 'open' | 'all' | 'done'
const PAGE = 100

export default function ImportBatchPage() {
  const { batchId } = useParams()
  const { t } = useTranslation()
  const qc = useQueryClient()
  const nav = useNavigate()
  const lk = useLookups()
  const [filter, setFilter] = useState<Filter>('open')
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [busy, setBusy] = useState<string | null>(null)
  const batch = useQuery({ queryKey: ['imports', batchId], queryFn: () => request<ImportBatch>('GET', `/api/v1/imports/${batchId}`) })
  const [needsCat, setNeedsCat] = useState(false)
  const [year, setYear] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const params = new URLSearchParams({ view: filter, offset: String((page - 1) * PAGE), limit: String(PAGE) })
  if (needsCat) params.set('needs_category', 'true')
  if (year) params.set('year', year)
  if (search) params.set('q', search)
  const rows = useQuery({
    queryKey: ['imports', batchId, 'rows', params.toString()],
    queryFn: () => request<{ total: number; items: ImportRowView[] }>('GET', `/api/v1/imports/${batchId}/rows?${params}`),
    placeholderData: (prev) => prev,
  })
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['imports'] })
  }
  const stats = JSON.parse(batch.data?.stats || '{}')
  const visible = rows.data?.items ?? []
  const total = rows.data?.total ?? 0
  const acceptedCount: number = stats.status_counts?.accepted ?? 0
  const resetPage = <T,>(fn: (v: T) => void) => (v: T) => {
    fn(v)
    setPage(1)
    setSelected(new Set())
  }

  async function run(key: string, fn: () => Promise<unknown>) {
    setBusy(key)
    try {
      await fn()
      refresh()
    } catch (e) {
      if (e instanceof ApiError && e.code === 'ai_unavailable') notifications.show({ color: 'orange', message: t('imp.aiUnavailable') })
      else notifyError(e)
    } finally {
      setBusy(null)
    }
  }

  const patchRow = (row: ImportRowView, body: object) => run(`row${row.id}`, () => request('PATCH', `/api/v1/imports/${batchId}/rows/${row.id}`, body))
  const bulk = (body: object) => run('bulk', () => request('POST', `/api/v1/imports/${batchId}/rows/bulk`, body))

  async function commit() {
    if (!confirm(t('imp.commitConfirm', { count: acceptedCount }))) return
    await run('commit', async () => {
      const res = await request<{ committed: number; errors: { row_no: number; message: string }[] }>('POST', `/api/v1/imports/${batchId}/commit`, {})
      notifications.show({ color: 'teal', message: t('imp.committed', { count: res.committed }) })
      if (res.errors.length) notifications.show({ color: 'orange', message: `${t('imp.errors', { count: res.errors.length })}: ${res.errors.slice(0, 3).map((e) => `#${e.row_no} ${e.message}`).join('; ')}` })
      LEDGER_KEYS.forEach((k) => qc.invalidateQueries({ queryKey: k }))
    })
  }

  const setCategory = (row: ImportRowView, category_id: number | null) => {
    const splits = (row.proposed.splits ?? []).map((s, i) => (i === 0 || !s.debt_id ? { ...s, category_id } : s))
    const kind = category_id && lk.categories.get(category_id)?.kind === 'income' ? 'income' : row.proposed.kind === 'income' || row.proposed.kind === 'expense' ? (row.amount < 0 ? 'expense' : 'income') : row.proposed.kind
    patchRow(row, { proposed: { splits, kind }, status: 'accepted' })
  }

  const counterpartLabel = (r: ImportRowView) => {
    const legs = r.proposed.legs ?? []
    const other = legs.find((l) => l.account_id !== r.account_id)
    return other ? `→ ${lk.accounts.get(other.account_id)?.name ?? '?'}` : ''
  }

  return (
    <Stack>
      <Group justify="space-between">
        <div>
          <Title order={3}>{t('imp.review')} #{batchId}</Title>
          <Text size="sm" c="dimmed">{batch.data?.source} · {batch.data?.file_name} · {batch.data?.status}</Text>
        </div>
        <Group>
          <Button variant="light" leftSection={<IconSparkles size={16} />} loading={busy === 'ai'}
            onClick={() => run('ai', () => request('POST', `/api/v1/imports/${batchId}/suggest`, { row_ids: selected.size ? [...selected] : null }))}>
            {t('imp.suggest')}
          </Button>
          <Menu>
            <Menu.Target>
              <Button variant="default" rightSection={<IconChevronDown size={14} />} loading={busy === 'bulk'}>{t('imp.accept')}</Button>
            </Menu.Target>
            <Menu.Dropdown>
              <Menu.Item disabled={!selected.size} onClick={() => bulk({ row_ids: [...selected], status: 'accepted' })}>{t('imp.acceptSelected')}</Menu.Item>
              <Menu.Item onClick={() => bulk({ filter: { status: 'suggested', min_confidence: 0.85 }, status: 'accepted' })}>{t('imp.acceptHigh')}</Menu.Item>
              <Menu.Item onClick={() => bulk({ filter: { status: 'suggested' }, status: 'accepted' })}>{t('imp.status.suggested')} → {t('imp.status.accepted')}</Menu.Item>
              <Menu.Item disabled={!selected.size} color="gray" onClick={() => bulk({ row_ids: [...selected], status: 'skipped' })}>{t('imp.skip')}</Menu.Item>
            </Menu.Dropdown>
          </Menu>
          <Button onClick={commit} loading={busy === 'commit'} disabled={!acceptedCount || batch.data?.status !== 'reviewing'}>
            {t('imp.commit')} ({acceptedCount})
          </Button>
          <Button variant="subtle" color="red" onClick={() => run('discard', async () => {
            await request('DELETE', `/api/v1/imports/${batchId}`)
            nav('/import')
          })}>{t('imp.discard')}</Button>
        </Group>
      </Group>

      {batch.data?.error && <Alert color="red">{batch.data.error}</Alert>}
      {stats.unknown_accounts?.length > 0 && <Alert color="orange">Unknown account identifiers: {stats.unknown_accounts.join(', ')}</Alert>}
      {stats.meta && 'balance_check_ok' in stats.meta && (
        <Alert color={stats.meta.balance_check_ok ? 'teal' : 'red'}>{t('imp.statementCheck')}: {stats.meta.balance_check_ok ? '✓' : '✗'}</Alert>
      )}

      <Group justify="space-between">
        <Group gap="sm">
          <SegmentedControl value={filter} onChange={resetPage((v: string) => setFilter(v as Filter))} data={[
            { value: 'open', label: t('imp.review') }, { value: 'done', label: t('imp.showDone') }, { value: 'all', label: t('common.all') },
          ]} />
          <Checkbox label={t('imp.needsCategory')} checked={needsCat} onChange={(e) => resetPage(setNeedsCat)(e.currentTarget.checked)} />
          <Select placeholder={t('imp.years')} clearable w={100} value={year} onChange={resetPage(setYear)}
            data={Array.from({ length: dayjs().year() - 2019 }, (_, i) => String(dayjs().year() - i))} />
          <TextInput placeholder={t('common.search')} w={180} defaultValue={search}
            onKeyDown={(e) => e.key === 'Enter' && resetPage(setSearch)(e.currentTarget.value)}
            onBlur={(e) => e.currentTarget.value !== search && resetPage(setSearch)(e.currentTarget.value)} />
        </Group>
        <Group gap={4}>
          {Object.entries((stats.status_counts ?? {}) as Record<string, number>).map(([k, v]) => (
            <Badge key={k} variant="light" color={k === 'committed' ? 'teal' : 'gray'}>{t(`imp.status.${k}`)} {v}</Badge>
          ))}
        </Group>
      </Group>

      <Table.ScrollContainer minWidth={900}>
        <Table verticalSpacing={4} highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th w={32}><Checkbox size="xs" checked={visible.length > 0 && selected.size === visible.length}
                onChange={(e) => setSelected(e.currentTarget.checked ? new Set(visible.map((r) => r.id)) : new Set())} /></Table.Th>
              <Table.Th>{t('common.date')}</Table.Th>
              <Table.Th>{t('common.description')}</Table.Th>
              <Table.Th ta="right">{t('common.amount')}</Table.Th>
              <Table.Th w={280}>{t('common.category')}</Table.Th>
              <Table.Th>{t('imp.suggestion')}</Table.Th>
              <Table.Th>{t('common.status')}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {visible.map((r) => {
              const p = r.proposed
              const firstSplit = p.splits?.[0]
              const done = ['committed', 'skipped', 'duplicate'].includes(r.status)
              const categorisable = !done && (p.kind === 'expense' || p.kind === 'income' || p.update_txn_id)
              return (
                <Table.Tr key={r.id} className={done ? 'row-muted' : undefined}>
                  <Table.Td><Checkbox size="xs" checked={selected.has(r.id)} disabled={done} onChange={(e) => {
                    const next = new Set(selected)
                    if (e.currentTarget.checked) next.add(r.id)
                    else next.delete(r.id)
                    setSelected(next)
                  }} /></Table.Td>
                  <Table.Td className="num">{dayjs(r.date).format('DD-MM-YY')}</Table.Td>
                  <Table.Td maw={320}>
                    <Text size="sm" truncate>{r.counterparty || r.description}</Text>
                    <Text size="xs" c="dimmed" truncate>
                      {[r.counterparty && r.description !== r.counterparty ? r.description : null, lk.accounts.get(r.account_id ?? 0)?.name, p.sheet, p.sheet_category && `sheet: ${p.sheet_category}`, p.note, p.skip, p.skip_reason].filter(Boolean).join(' · ')}
                    </Text>
                  </Table.Td>
                  <Table.Td ta="right"><Money value={r.amount} currency={r.currency} colored={r.amount > 0} /></Table.Td>
                  <Table.Td>
                    {categorisable ? (
                      <CategorySelect size="xs" value={firstSplit?.category_id} onChange={(v) => setCategory(r, v)}
                        kind={r.amount < 0 ? 'expense' : undefined} error={p.needs_category && !done ? ' ' : undefined} />
                    ) : (
                      <Group gap={4}>
                        {p.kind && <KindBadge kind={p.kind} />}
                        <Text size="xs">{counterpartLabel(r)}{p.splits?.some((s) => s.debt_id) ? ` ${lk.debts.get(p.splits.find((s) => s.debt_id)!.debt_id!)?.name ?? ''}` : ''}</Text>
                      </Group>
                    )}
                    {p.rule && <Text size="xs" c="dimmed">{t('imp.rule')}: {p.rule}{p.mode ? ` · ${p.mode}` : ''}{p.update_txn_id ? ` · txn ${p.update_txn_id}` : ''}</Text>}
                  </Table.Td>
                  <Table.Td>
                    {r.suggestion && (
                      <Tooltip label={r.suggestion.rationale} disabled={!r.suggestion.rationale} multiline w={260}>
                        <Group gap={4} wrap="nowrap">
                          <Badge size="xs" variant="dot" color={r.suggestion.confidence >= 0.85 ? 'teal' : r.suggestion.confidence >= 0.6 ? 'yellow' : 'red'}>
                            {Math.round(r.suggestion.confidence * 100)}%
                          </Badge>
                          <Text size="xs" truncate maw={160}>{lk.categoryPath(r.suggestion.category_id) || '—'}</Text>
                        </Group>
                      </Tooltip>
                    )}
                    {p.ai_agrees_with_sheet === false && <Text size="xs" c="orange">≠ sheet</Text>}
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4} wrap="nowrap">
                      <Badge size="sm" variant={r.status === 'accepted' ? 'filled' : 'light'} color={r.status === 'accepted' ? 'teal' : r.status === 'committed' ? 'teal' : 'gray'}>
                        {t(`imp.status.${r.status}`)}
                      </Badge>
                      {!done && r.status !== 'accepted' && <Button size="compact-xs" variant="subtle" onClick={() => patchRow(r, { status: 'accepted' })}>{t('imp.accept')}</Button>}
                      {!done && <Button size="compact-xs" variant="subtle" color="gray" onClick={() => patchRow(r, { status: 'skipped' })}>{t('imp.skip')}</Button>}
                    </Group>
                  </Table.Td>
                </Table.Tr>
              )
            })}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      <Group justify="space-between">
        <Text size="sm" c="dimmed">{total} {t('imp.rows').toLowerCase()}</Text>
        {total > PAGE && <Pagination total={Math.ceil(total / PAGE)} value={page} onChange={(p) => { setPage(p); setSelected(new Set()) }} />}
      </Group>
    </Stack>
  )
}
