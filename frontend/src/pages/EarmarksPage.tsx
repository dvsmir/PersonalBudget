import { useState } from 'react'
import { Button, Card, Group, Progress, SimpleGrid, Stack, Table, Text, TextInput, Title } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import dayjs from 'dayjs'
import { request } from '../api/client'
import { useApiMutation, useEarmarks } from '../api/hooks'
import { Money, Section } from '../components/common'
import { useTxnEditor } from '../components/TxnEditor'

export default function EarmarksPage() {
  const { t } = useTranslation()
  const { data } = useEarmarks()
  const { openNew } = useTxnEditor()
  const [selected, setSelected] = useState<number | null>(null)
  const [name, setName] = useState('')
  const create = useApiMutation(() => request('POST', '/api/v1/earmarks', { name, currency: 'EUR' }), [['earmarks']])
  const movements = useQuery({
    queryKey: ['earmarks', selected, 'moves'],
    queryFn: () => request<{ txn_id: number; date: string; description: string; amount: number }[]>('GET', `/api/v1/earmarks/${selected}/movements`),
    enabled: !!selected,
  })
  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>{t('nav.earmarks')}</Title>
        <Button onClick={() => openNew('earmark')}>{t('txn.allocate')} / {t('txn.release')}</Button>
      </Group>
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
        {(data ?? []).map((e) => (
          <Card key={e.id} withBorder className="clickable" onClick={() => setSelected(e.id)}>
            <Text fw={600}>{e.name}</Text>
            <Text fz={22} fw={650} className="num"><Money value={e.balance} currency={e.currency} /></Text>
            {e.target_amount ? (
              <>
                <Progress value={Math.min(100, (e.balance / e.target_amount) * 100)} size="sm" mt={6} />
                <Text size="xs" c="dimmed">{t('wealth.target')}: <Money value={e.target_amount} currency={e.currency} /></Text>
              </>
            ) : null}
          </Card>
        ))}
      </SimpleGrid>
      {selected && (
        <Section title={data?.find((e) => e.id === selected)?.name ?? ''}>
          <Table>
            <Table.Tbody>
              {(movements.data ?? []).map((m) => (
                <Table.Tr key={m.txn_id}>
                  <Table.Td>{dayjs(m.date).format('DD-MM-YYYY')}</Table.Td>
                  <Table.Td>{m.description}</Table.Td>
                  <Table.Td ta="right"><Money value={m.amount} colored sign /></Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Section>
      )}
      <Group align="flex-end">
        <TextInput label={t('wealth.newEarmark')} value={name} onChange={(e) => setName(e.currentTarget.value)} />
        <Button variant="default" disabled={!name} onClick={() => { create.mutate(undefined); setName('') }}>{t('common.add')}</Button>
      </Group>
    </Stack>
  )
}
