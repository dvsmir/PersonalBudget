import { useState } from 'react'
import { Alert, Badge, Button, FileButton, Group, Select, SimpleGrid, Stack, Table, Text, TextInput, Title } from '@mantine/core'
import { Dropzone } from '@mantine/dropzone'
import { IconFileSpreadsheet, IconUpload } from '@tabler/icons-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import dayjs from 'dayjs'
import { request, type ImportBatch } from '../api/client'
import { LEDGER_KEYS, notifyError, useLookups } from '../api/hooks'
import { AccountSelect, Section } from '../components/common'
import { formatMoney } from '../lib/money'

const SOURCES = ['abn_mt940', 'abn_xls', 'bunq_csv', 'bunq_mt940', 'ics_pdf']

export default function ImportPage() {
  const { t } = useTranslation()
  const nav = useNavigate()
  const qc = useQueryClient()
  const lk = useLookups()
  const [source, setSource] = useState<string | null>(null)
  const [accountId, setAccountId] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [years, setYears] = useState('')
  const [migrationResult, setMigrationResult] = useState<string | null>(null)
  const batches = useQuery({ queryKey: ['imports'], queryFn: () => request<ImportBatch[]>('GET', '/api/v1/imports') })

  async function upload(files: File[]) {
    if (!files.length) return
    setBusy(true)
    try {
      for (const file of files) {
        const fd = new FormData()
        fd.append('file', file)
        if (source) fd.append('source', source)
        if (accountId) fd.append('account_id', String(accountId))
        const batch = await request<ImportBatch>('POST', '/api/v1/imports', fd)
        if (files.length === 1) nav(`/import/${batch.id}`)
      }
      qc.invalidateQueries({ queryKey: ['imports'] })
    } catch (e) {
      notifyError(e)
    } finally {
      setBusy(false)
    }
  }

  async function uploadSheet(file: File | null) {
    if (!file) return
    setBusy(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      if (years.trim()) fd.append('years', years)
      const batch = await request<ImportBatch>('POST', '/api/v1/imports/sheet', fd)
      nav(`/import/${batch.id}`)
    } catch (e) {
      notifyError(e)
    } finally {
      setBusy(false)
    }
  }

  async function anchors(file: File | null) {
    if (!file) return
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await request<Record<string, number>>('POST', '/api/v1/migration/anchors', fd)
      setMigrationResult(JSON.stringify(res))
      LEDGER_KEYS.forEach((k) => qc.invalidateQueries({ queryKey: k }))
    } catch (e) {
      notifyError(e)
    }
  }

  async function balancing() {
    try {
      const res = await request<{ account: string; date: string; kind: string; amount: number }[]>('POST', '/api/v1/migration/balance')
      setMigrationResult(res.map((r) => `${r.date} ${r.account}: ${t(`kinds.${r.kind}`)} ${formatMoney(r.amount, lk.accounts.get([...lk.accounts.values()].find((a) => a.name === r.account)?.id ?? 0)?.currency)}`).join('\n') || '—')
      LEDGER_KEYS.forEach((k) => qc.invalidateQueries({ queryKey: k }))
    } catch (e) {
      notifyError(e)
    }
  }

  return (
    <Stack>
      <Title order={3}>{t('nav.import')}</Title>
      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        <Section title={t('imp.upload')}>
          <Stack>
            <Group grow>
              <Select label={t('imp.source')} placeholder={t('imp.autodetect')} clearable data={SOURCES} value={source} onChange={setSource} />
              <AccountSelect label={t('common.account')} placeholder={t('imp.autodetect')} clearable value={accountId} onChange={setAccountId} />
            </Group>
            <Dropzone onDrop={upload} loading={busy} maxSize={10 * 1024 * 1024}>
              <Group justify="center" mih={110} style={{ pointerEvents: 'none' }}>
                <IconUpload size={32} stroke={1.5} />
                <Text size="sm" c="dimmed" maw={260} ta="center">{t('imp.drop')}</Text>
              </Group>
            </Dropzone>
          </Stack>
        </Section>
        <Section title={t('imp.migration')}>
          <Stack gap="sm">
            <Text size="sm" c="dimmed">{t('imp.sheetHelp')}</Text>
            <Group align="flex-end">
              <TextInput label={t('imp.years')} placeholder="2021,2022" value={years} onChange={(e) => setYears(e.currentTarget.value)} w={160} />
              <FileButton onChange={uploadSheet} accept=".xlsx">
                {(props) => <Button {...props} leftSection={<IconFileSpreadsheet size={16} />} loading={busy}>{t('imp.sheet')}</Button>}
              </FileButton>
            </Group>
            <Group>
              <FileButton onChange={anchors} accept=".xlsx">
                {(props) => <Button {...props} variant="default">{t('imp.anchors')}</Button>}
              </FileButton>
              <Button variant="default" onClick={balancing}>{t('imp.balancing')}</Button>
            </Group>
            {migrationResult && <Alert color="gray"><Text size="xs" style={{ whiteSpace: 'pre-wrap' }}>{migrationResult}</Text></Alert>}
          </Stack>
        </Section>
      </SimpleGrid>

      <Section title={t('imp.batches')}>
        <Table.ScrollContainer minWidth={600}>
          <Table highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>#</Table.Th>
                <Table.Th>{t('common.date')}</Table.Th>
                <Table.Th>{t('imp.source')}</Table.Th>
                <Table.Th>File</Table.Th>
                <Table.Th>{t('imp.rows')}</Table.Th>
                <Table.Th>{t('common.status')}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {(batches.data ?? []).map((b) => {
                const stats = JSON.parse(b.stats || '{}')
                return (
                  <Table.Tr key={b.id}>
                    <Table.Td><Link to={`/import/${b.id}`}>{b.id}</Link></Table.Td>
                    <Table.Td>{dayjs(b.created_at).format('DD-MM-YY HH:mm')}</Table.Td>
                    <Table.Td>{b.source}{b.mode && <Text span size="xs" c="dimmed"> · {b.mode}</Text>}</Table.Td>
                    <Table.Td><Text size="sm" truncate maw={220}>{b.file_name}</Text></Table.Td>
                    <Table.Td>
                      <Group gap={4}>
                        {Object.entries((stats.status_counts ?? {}) as Record<string, number>).map(([k, v]) => (
                          <Badge key={k} variant="light" size="sm" color={k === 'committed' ? 'teal' : k === 'duplicate' || k === 'skipped' ? 'gray' : 'blue'}>
                            {t(`imp.status.${k}`)} {v}
                          </Badge>
                        ))}
                      </Group>
                    </Table.Td>
                    <Table.Td>{b.error ? <Text c="red" size="sm">{b.error}</Text> : b.status}</Table.Td>
                  </Table.Tr>
                )
              })}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Section>
    </Stack>
  )
}
