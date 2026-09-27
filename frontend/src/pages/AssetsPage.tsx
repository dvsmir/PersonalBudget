import { useState } from 'react'
import { Button, Card, Group, Modal, Select, SimpleGrid, Stack, Table, Text, TextInput, Title } from '@mantine/core'
import { DateInput } from '@mantine/dates'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import dayjs from 'dayjs'
import { request, type Asset } from '../api/client'
import { LEDGER_KEYS, useApiMutation, useAssets, useLookups, useSecurities } from '../api/hooks'
import { Empty, Money, MoneyInput, Section } from '../components/common'

type Holding = { account_id: number; security_id: number; symbol: string; name: string; currency: string; units: string; price: string; price_date: string | null; value: number; value_ref: number; invested: number }

export default function AssetsPage() {
  const { t } = useTranslation()
  const { data: assets } = useAssets()
  const lk = useLookups()
  const { data: securities } = useSecurities()
  const holdings = useQuery({ queryKey: ['report', 'holdings'], queryFn: () => request<Holding[]>('GET', '/api/v1/investments/holdings') })
  const [valuing, setValuing] = useState<Asset | null>(null)
  const [creating, setCreating] = useState(false)
  const [secId, setSecId] = useState<string | null>(null)
  const [priceDate, setPriceDate] = useState(dayjs().format('YYYY-MM-DD'))
  const [price, setPrice] = useState('')
  const addPrice = useApiMutation(() => request('POST', `/api/v1/securities/${secId}/prices`, { date: priceDate, price }), LEDGER_KEYS, t('common.saved'))

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>{t('nav.assets')}</Title>
        <Button onClick={() => setCreating(true)}>{t('wealth.newAsset')}</Button>
      </Group>
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
        {(assets ?? []).map((a) => (
          <Card key={a.id} withBorder>
            <Text fw={600}>{a.name}</Text>
            <Text size="xs" c="dimmed">{a.type}</Text>
            <Text fz={22} fw={650} className="num" mt={4}><Money value={a.value} currency={a.currency} /></Text>
            <Text size="xs" c="dimmed">{t('wealth.valuedOn')} {a.valued_on ? dayjs(a.valued_on).format('DD-MM-YYYY') : '—'}</Text>
            <Button size="compact-xs" variant="subtle" mt={6} onClick={() => setValuing(a)}>{t('wealth.addValuation')}</Button>
          </Card>
        ))}
      </SimpleGrid>

      <Section title={t('wealth.holdings')}>
        {holdings.data?.length ? (
          <Table.ScrollContainer minWidth={600}>
            <Table>
              <Table.Thead>
                <Table.Tr><Table.Th>{t('txn.security')}</Table.Th><Table.Th>{t('common.account')}</Table.Th><Table.Th ta="right">{t('txn.units')}</Table.Th><Table.Th ta="right">{t('txn.price')}</Table.Th><Table.Th ta="right">{t('common.value')}</Table.Th><Table.Th ta="right">{t('wealth.invested')}</Table.Th><Table.Th ta="right">{t('wealth.gain')}</Table.Th></Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {holdings.data.map((h) => (
                  <Table.Tr key={`${h.account_id}-${h.security_id}`}>
                    <Table.Td>{h.name} <Text span size="xs" c="dimmed">{h.symbol}</Text></Table.Td>
                    <Table.Td>{lk.accounts.get(h.account_id)?.name}</Table.Td>
                    <Table.Td ta="right" className="num">{Number(h.units).toLocaleString()}</Table.Td>
                    <Table.Td ta="right" className="num">{Number(h.price).toFixed(2)} {h.price_date && <Text span size="xs" c="dimmed">{dayjs(h.price_date).format('DD-MM')}</Text>}</Table.Td>
                    <Table.Td ta="right"><Money value={h.value} currency={h.currency} /></Table.Td>
                    <Table.Td ta="right"><Money value={h.invested} currency={h.currency} /></Table.Td>
                    <Table.Td ta="right"><Money value={h.value - h.invested} currency={h.currency} colored sign /></Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        ) : <Empty />}
        <Group mt="md" align="flex-end">
          <Select label={t('txn.security')} data={(securities ?? []).map((s) => ({ value: String(s.id), label: `${s.name} (${s.symbol})` }))} value={secId} onChange={setSecId} w={260} searchable />
          <DateInput label={t('common.date')} value={priceDate} onChange={(v) => v && setPriceDate(v)} valueFormat="DD-MM-YYYY" w={140} />
          <TextInput label={t('txn.price')} value={price} onChange={(e) => setPrice(e.currentTarget.value.replace(',', '.'))} w={120} />
          <Button variant="default" disabled={!secId || !price} onClick={() => addPrice.mutate(undefined)}>{t('common.add')}</Button>
        </Group>
      </Section>
      {valuing && <ValuationModal asset={valuing} onClose={() => setValuing(null)} />}
      {creating && <AssetModal onClose={() => setCreating(false)} />}
    </Stack>
  )
}

function ValuationModal({ asset, onClose }: { asset: Asset; onClose: () => void }) {
  const { t } = useTranslation()
  const [date, setDate] = useState(dayjs().format('YYYY-MM-DD'))
  const [value, setValue] = useState<number | null>(asset.value ?? null)
  const history = useQuery({ queryKey: ['assets', asset.id, 'val'], queryFn: () => request<{ date: string; value: number; source: string }[]>('GET', `/api/v1/assets/${asset.id}/valuations`) })
  const save = useApiMutation(async () => {
    await request('POST', `/api/v1/assets/${asset.id}/valuations`, { date, value, source: 'manual' })
    onClose()
  }, LEDGER_KEYS, t('common.saved'))
  return (
    <Modal opened onClose={onClose} title={asset.name}>
      <Stack>
        <Group grow>
          <DateInput label={t('common.date')} value={date} onChange={(v) => v && setDate(v)} valueFormat="DD-MM-YYYY" />
          <MoneyInput label={t('common.value')} value={value} onChange={setValue} currency={asset.currency} />
        </Group>
        <Table>
          <Table.Tbody>
            {(history.data ?? []).slice().reverse().map((v) => (
              <Table.Tr key={v.date}><Table.Td>{dayjs(v.date).format('DD-MM-YYYY')}</Table.Td><Table.Td>{v.source}</Table.Td><Table.Td ta="right"><Money value={v.value} currency={asset.currency} /></Table.Td></Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        <Group justify="flex-end"><Button onClick={() => save.mutate(undefined)} disabled={value === null}>{t('common.save')}</Button></Group>
      </Stack>
    </Modal>
  )
}

function AssetModal({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const [type, setType] = useState('other')
  const [currency, setCurrency] = useState('EUR')
  const save = useApiMutation(async () => {
    await request('POST', '/api/v1/assets', { name, type, currency })
    onClose()
  }, LEDGER_KEYS, t('common.saved'))
  return (
    <Modal opened onClose={onClose} title={t('wealth.newAsset')}>
      <Stack>
        <TextInput label={t('common.name')} value={name} onChange={(e) => setName(e.currentTarget.value)} />
        <Group grow>
          <Select label={t('common.type')} data={['real_estate', 'vehicle', 'other']} value={type} onChange={(v) => setType(v ?? 'other')} />
          <Select label={t('common.currency')} data={['EUR', 'RUB', 'USD']} value={currency} onChange={(v) => setCurrency(v ?? 'EUR')} />
        </Group>
        <Group justify="flex-end"><Button onClick={() => save.mutate(undefined)} disabled={!name}>{t('common.save')}</Button></Group>
      </Stack>
    </Modal>
  )
}
