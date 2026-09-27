import { useState } from 'react'
import {
  ActionIcon, Alert, Badge, Button, Code, Group, JsonInput, Modal, PasswordInput, Select, Stack, Table, Tabs, Text, TextInput, Title,
} from '@mantine/core'
import { DateInput } from '@mantine/dates'
import { IconArchive, IconPlus } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { download, request, type Category, type User } from '../api/client'
import { notifyError, useApiMutation, useCategories, useSettings } from '../api/hooks'
import { useAuth } from '../auth'
import { usePrefs } from '../lib/prefs'
import { Section } from '../components/common'

export default function SettingsPage() {
  const { t } = useTranslation()
  const { user } = useAuth()
  return (
    <Stack>
      <Title order={3}>{t('nav.settings')}</Title>
      <Tabs defaultValue="profile" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="profile">{t('settings.profile')}</Tabs.Tab>
          <Tabs.Tab value="categories">{t('settings.categories')}</Tabs.Tab>
          {user?.role === 'admin' && <Tabs.Tab value="users">{t('settings.users')}</Tabs.Tab>}
          <Tabs.Tab value="fx">{t('settings.fx')}</Tabs.Tab>
          <Tabs.Tab value="ai">{t('settings.ai')}</Tabs.Tab>
          <Tabs.Tab value="rules">{t('settings.rules')}</Tabs.Tab>
          <Tabs.Tab value="data">{t('settings.data')}</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="profile" pt="md"><Profile /></Tabs.Panel>
        <Tabs.Panel value="categories" pt="md"><Categories /></Tabs.Panel>
        <Tabs.Panel value="users" pt="md"><Users /></Tabs.Panel>
        <Tabs.Panel value="fx" pt="md"><Fx /></Tabs.Panel>
        <Tabs.Panel value="ai" pt="md"><Ai /></Tabs.Panel>
        <Tabs.Panel value="rules" pt="md"><Rules /></Tabs.Panel>
        <Tabs.Panel value="data" pt="md"><Data /></Tabs.Panel>
      </Tabs>
    </Stack>
  )
}

function Profile() {
  const { t, i18n } = useTranslation()
  const { user, reloadUser } = useAuth()
  const { numberStyle, setNumberStyle } = usePrefs()
  const [cur, setCur] = useState('')
  const [next, setNext] = useState('')
  const [totp, setTotp] = useState<{ secret: string; uri: string } | null>(null)
  const [code, setCode] = useState('')
  const patch = useApiMutation((body: object) => request('PATCH', '/api/v1/me', body), [], t('common.saved'))
  return (
    <Stack maw={520}>
      <Group grow>
        <Select label={t('settings.language')} data={[{ value: 'en', label: 'English' }, { value: 'ru', label: 'Русский' }]} value={user?.locale}
          onChange={async (v) => {
            if (!v) return
            await patch.mutateAsync({ locale: v })
            i18n.changeLanguage(v)
            localStorage.setItem('budget.lang', v)
            reloadUser()
          }} />
        <Select label={t('settings.numberStyle')} data={[{ value: 'en', label: '€1,234.56' }, { value: 'nl', label: '€1.234,56' }]} value={numberStyle}
          onChange={(v) => v && setNumberStyle(v as 'en' | 'nl')} />
      </Group>
      <Section title={t('settings.password')}>
        <Stack>
          <PasswordInput label={t('settings.currentPassword')} value={cur} onChange={(e) => setCur(e.currentTarget.value)} />
          <PasswordInput label={t('settings.newPassword')} value={next} onChange={(e) => setNext(e.currentTarget.value)} />
          <Button onClick={() => patch.mutate({ current_password: cur, new_password: next })} disabled={!cur || next.length < 10}>{t('common.save')}</Button>
        </Stack>
      </Section>
      <Section title={t('settings.twofa')} right={<Badge color={user?.totp_enabled ? 'teal' : 'gray'}>{user?.totp_enabled ? 'on' : 'off'}</Badge>}>
        {user?.totp_enabled ? (
          <Button color="red" variant="light" onClick={async () => { await request('DELETE', '/api/v1/me/totp'); reloadUser() }}>{t('settings.disable2fa')}</Button>
        ) : totp ? (
          <Stack>
            <Text size="sm">{t('settings.scan')}</Text>
            <Code block>{totp.uri}</Code>
            <Text size="sm">Secret: <Code>{totp.secret}</Code></Text>
            <Group>
              <TextInput value={code} onChange={(e) => setCode(e.currentTarget.value)} placeholder="123456" w={120} />
              <Button onClick={async () => {
                try {
                  await request('POST', '/api/v1/me/totp/confirm', { secret: totp.secret, code })
                  setTotp(null)
                  reloadUser()
                } catch (e) { notifyError(e) }
              }}>{t('common.save')}</Button>
            </Group>
          </Stack>
        ) : (
          <Button onClick={async () => setTotp(await request('POST', '/api/v1/me/totp/begin'))}>{t('settings.enable2fa')}</Button>
        )}
      </Section>
    </Stack>
  )
}

function Categories() {
  const { t } = useTranslation()
  const { data } = useCategories()
  const [edit, setEdit] = useState<Partial<Category> | null>(null)
  const [merge, setMerge] = useState<Category | null>(null)
  const [target, setTarget] = useState<string | null>(null)
  const keys = [['categories'], ['report'], ['txns']]
  const archive = useApiMutation((c: Category) => request('PATCH', `/api/v1/categories/${c.id}`, { archived: true }), keys)
  const doMerge = useApiMutation(() => request('POST', '/api/v1/categories/merge', { source_id: merge!.id, target_id: Number(target) }), keys, t('common.saved'))
  const save = useApiMutation(async () => {
    if (edit!.id) {
      await request('PATCH', `/api/v1/categories/${edit!.id}`, { name: edit!.name, default_cost_type: edit!.default_cost_type || null, description: edit!.description || null })
    } else {
      await request('POST', '/api/v1/categories', { name: edit!.name, kind: edit!.kind, parent_id: edit!.parent_id ?? null, default_cost_type: edit!.default_cost_type || null, description: edit!.description || null })
    }
    setEdit(null)
  }, keys, t('common.saved'))
  const tops = (kind: string) => (data ?? []).filter((c) => c.kind === kind && !c.parent_id)
  const row = (c: Category, sub: boolean) => (
    <Table.Tr key={c.id}>
      <Table.Td pl={sub ? 32 : undefined}><Text size="sm" fw={sub ? 400 : 600}>{c.name}</Text></Table.Td>
      <Table.Td>{c.default_cost_type && <Badge variant="light" size="sm">{t(`costType.${c.default_cost_type}`)}</Badge>}</Table.Td>
      <Table.Td><Text size="xs" c="dimmed" truncate maw={280}>{c.description}</Text></Table.Td>
      <Table.Td>
        <Group gap={2} justify="flex-end" wrap="nowrap">
          {!sub && <ActionIcon variant="subtle" title={t('common.add')} onClick={() => setEdit({ kind: c.kind, parent_id: c.id })}><IconPlus size={14} /></ActionIcon>}
          <Button size="compact-xs" variant="subtle" onClick={() => setEdit(c)}>{t('common.edit')}</Button>
          <Button size="compact-xs" variant="subtle" onClick={() => setMerge(c)}>{t('settings.merge')}</Button>
          <ActionIcon variant="subtle" color="gray" title={t('common.archive')} onClick={() => archive.mutate(c)}><IconArchive size={14} /></ActionIcon>
        </Group>
      </Table.Td>
    </Table.Tr>
  )
  return (
    <Stack>
      {(['expense', 'income'] as const).map((kind) => (
        <Section key={kind} title={t(`kinds.${kind}`)} right={<Button size="xs" variant="light" onClick={() => setEdit({ kind })}>{t('settings.newCategory')}</Button>}>
          <Table>
            <Table.Tbody>
              {tops(kind).flatMap((top) => [row(top, false), ...(data ?? []).filter((c) => c.parent_id === top.id).map((s) => row(s, true))])}
            </Table.Tbody>
          </Table>
        </Section>
      ))}
      {edit && (
        <Modal opened onClose={() => setEdit(null)} title={edit.id ? edit.name : t('settings.newCategory')}>
          <Stack>
            <TextInput label={t('common.name')} value={edit.name ?? ''} onChange={(e) => setEdit({ ...edit, name: e.currentTarget.value })} />
            {edit.kind === 'expense' && (
              <Select label={t('txn.costType')} clearable data={['fixed', 'variable', 'one_time'].map((v) => ({ value: v, label: t(`costType.${v}`) }))}
                value={edit.default_cost_type ?? null} onChange={(v) => setEdit({ ...edit, default_cost_type: v })} />
            )}
            <TextInput label={t('settings.aiHint')} value={edit.description ?? ''} onChange={(e) => setEdit({ ...edit, description: e.currentTarget.value })} />
            <Group justify="flex-end"><Button onClick={() => save.mutate(undefined)} disabled={!edit.name}>{t('common.save')}</Button></Group>
          </Stack>
        </Modal>
      )}
      {merge && (
        <Modal opened onClose={() => setMerge(null)} title={`${merge.name} → ${t('settings.merge')}`}>
          <Stack>
            <Select searchable data={(data ?? []).filter((c) => c.kind === merge.kind && c.id !== merge.id).map((c) => ({ value: String(c.id), label: c.name }))} value={target} onChange={setTarget} />
            <Button disabled={!target} onClick={async () => { await doMerge.mutateAsync(undefined); setMerge(null) }}>{t('common.apply')}</Button>
          </Stack>
        </Modal>
      )}
    </Stack>
  )
}

function Users() {
  const { t } = useTranslation()
  const users = useQuery({ queryKey: ['users'], queryFn: () => request<User[]>('GET', '/api/v1/users') })
  const [f, setF] = useState({ email: '', display_name: '', password: '', role: 'member', locale: 'en' })
  const create = useApiMutation(() => request('POST', '/api/v1/users', f), [['users']], t('common.saved'))
  const toggle = useApiMutation((u: User) => request('PATCH', `/api/v1/users/${u.id}`, { is_active: !u.is_active }), [['users']])
  return (
    <Stack maw={720}>
      <Table>
        <Table.Tbody>
          {(users.data ?? []).map((u) => (
            <Table.Tr key={u.id}>
              <Table.Td>{u.display_name}</Table.Td><Table.Td>{u.email}</Table.Td><Table.Td>{u.role}</Table.Td>
              <Table.Td>{u.totp_enabled && <Badge size="sm">2FA</Badge>}</Table.Td>
              <Table.Td><Button size="compact-xs" variant="subtle" onClick={() => toggle.mutate(u)}>{u.is_active ? 'deactivate' : 'activate'}</Button></Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <Group align="flex-end" grow>
        <TextInput label="E-mail" value={f.email} onChange={(e) => setF({ ...f, email: e.currentTarget.value })} />
        <TextInput label={t('common.name')} value={f.display_name} onChange={(e) => setF({ ...f, display_name: e.currentTarget.value })} />
        <PasswordInput label={t('login.password')} value={f.password} onChange={(e) => setF({ ...f, password: e.currentTarget.value })} />
        <Select label="Role" data={['member', 'admin']} value={f.role} onChange={(v) => setF({ ...f, role: v ?? 'member' })} />
        <Button onClick={() => create.mutate(undefined)} disabled={!f.email || f.password.length < 10}>{t('common.add')}</Button>
      </Group>
    </Stack>
  )
}

function Fx() {
  const { t } = useTranslation()
  const [date, setDate] = useState<string>(new Date().toISOString().slice(0, 10))
  const [ccy, setCcy] = useState('RUB')
  const rate = useQuery({ queryKey: ['fx', date, ccy], queryFn: () => request<{ rate: string | null; estimated: boolean }>('GET', `/api/v1/fx/rate?date=${date}&currency=${ccy}`) })
  const [result, setResult] = useState<string | null>(null)
  const fetchNow = useApiMutation(async () => setResult(JSON.stringify(await request('POST', '/api/v1/fx/fetch'))), [['fx'], ['report']])
  return (
    <Stack maw={520}>
      <Group align="flex-end">
        <DateInput label={t('common.date')} value={date} onChange={(v) => v && setDate(v)} valueFormat="DD-MM-YYYY" w={150} />
        <Select label={t('common.currency')} data={['RUB', 'USD', 'GBP']} value={ccy} onChange={(v) => setCcy(v ?? 'RUB')} w={100} />
        <Text size="lg" fw={600} className="num">1 EUR = {rate.data?.rate ? Number(rate.data.rate).toFixed(4) : '—'} {ccy}</Text>
        {rate.data?.estimated && <Badge color="orange">estimated</Badge>}
      </Group>
      <Button variant="light" onClick={() => fetchNow.mutate(undefined)} loading={fetchNow.isPending}>{t('settings.fetchFx')}</Button>
      {result && <Code block>{result}</Code>}
    </Stack>
  )
}

function Ai() {
  const { t } = useTranslation()
  const settings = useSettings()
  const usage = useQuery({ queryKey: ['ai'], queryFn: () => request<Record<string, number>>('GET', '/api/v1/ai/usage') })
  const [model, setModel] = useState<string | null>(null)
  const save = useApiMutation(() => request('PATCH', '/api/v1/settings', { ai_model: model || null }), [['settings']], t('common.saved'))
  return (
    <Stack maw={520}>
      <Group align="flex-end">
        <Select label={t('settings.model')} data={['claude-opus-5', 'claude-sonnet-5', 'claude-haiku-4-5']} placeholder="claude-opus-5 (default)"
          value={model ?? (settings.data?.ai_model as string | null) ?? null} onChange={setModel} clearable w={260} />
        <Button onClick={() => save.mutate(undefined)}>{t('common.save')}</Button>
      </Group>
      <Section title={t('settings.usage')}>
        <Text size="sm">Calls: {usage.data?.calls ?? 0} · input {usage.data?.input_tokens ?? 0} · output {usage.data?.output_tokens ?? 0} · cache read {usage.data?.cache_read_tokens ?? 0}</Text>
      </Section>
    </Stack>
  )
}

function Rules() {
  const { t } = useTranslation()
  const rules = useQuery({ queryKey: ['rules'], queryFn: () => request<{ id: number; source: string; priority: number; match: string; action: string; note: string | null; is_active: number }[]>('GET', '/api/v1/import-rules') })
  const [text, setText] = useState<string | null>(null)
  const save = useApiMutation(() => request('PUT', '/api/v1/import-rules', JSON.parse(text!)), [['rules']], t('common.saved'))
  const value = text ?? JSON.stringify(rules.data ?? [], null, 2)
  return (
    <Stack>
      <Alert color="gray">Import.md §5.5 — match: date_from, date_to, category, desc_regex, currency, sign · action: account, kind, counter_account, category</Alert>
      <JsonInput value={value} onChange={setText} autosize minRows={12} formatOnBlur validationError="Invalid JSON" />
      <Group justify="flex-end"><Button onClick={() => save.mutate(undefined)} disabled={text === null}>{t('common.save')}</Button></Group>
    </Stack>
  )
}

function Data() {
  const { t } = useTranslation()
  const settings = useSettings()
  const [patch, setPatch] = useState<Record<string, string | null>>({})
  const save = useApiMutation(() => request('PATCH', '/api/v1/settings', patch), [['settings']], t('common.saved'))
  const val = (k: string) => (patch[k] ?? (settings.data?.[k] as string | null)) ?? null
  return (
    <Stack maw={520}>
      <Group grow>
        <DateInput label={t('settings.historyStart')} value={val('history_start_date')} onChange={(v) => setPatch({ ...patch, history_start_date: v })} valueFormat="DD-MM-YYYY" />
        <DateInput label={t('settings.cardCutover')} value={val('card_cutover_date')} onChange={(v) => setPatch({ ...patch, card_cutover_date: v })} valueFormat="DD-MM-YYYY" />
        <DateInput label={t('settings.cutover')} value={val('bank_cutover_date')} onChange={(v) => setPatch({ ...patch, bank_cutover_date: v })} valueFormat="DD-MM-YYYY" />
      </Group>
      <Button onClick={() => save.mutate(undefined)} disabled={!Object.keys(patch).length}>{t('common.save')}</Button>
      <Section title={t('settings.export')}>
        <Group>
          <Button variant="default" onClick={() => download('/api/v1/export/txns.csv', 'transactions.csv').catch(notifyError)}>transactions.csv</Button>
          <Button variant="default" onClick={() => download('/api/v1/export/full.json', 'budget-export.json').catch(notifyError)}>full.json</Button>
        </Group>
      </Section>
    </Stack>
  )
}
