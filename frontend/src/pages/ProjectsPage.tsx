import { useState } from 'react'
import { Anchor, Button, Card, Group, Modal, Progress, Select, SimpleGrid, Stack, Table, Text, TextInput, Title } from '@mantine/core'
import { DateInput } from '@mantine/dates'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import dayjs from 'dayjs'
import { request, type Project } from '../api/client'
import { useApiMutation, useProjects } from '../api/hooks'
import { Money, MoneyInput } from '../components/common'

type Summary = { project_id: number; total_ref: number; first_date: string | null; last_date: string | null; budget_amount: number | null; budget_currency: string | null; by_category: { category_id: number; name: string; currency: string; amount: number; amount_ref: number }[] }

export default function ProjectsPage() {
  const { t } = useTranslation()
  const { data } = useProjects()
  const [editing, setEditing] = useState<Partial<Project> | null>(null)
  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>{t('nav.projects')}</Title>
        <Button onClick={() => setEditing({ kind: 'renovation' })}>{t('wealth.newProject')}</Button>
      </Group>
      <SimpleGrid cols={{ base: 1, md: 2, lg: 3 }}>
        {(data ?? []).map((p) => <ProjectCard key={p.id} project={p} onEdit={() => setEditing(p)} />)}
      </SimpleGrid>
      {editing && <ProjectForm initial={editing} onClose={() => setEditing(null)} />}
    </Stack>
  )
}

function ProjectCard({ project, onEdit }: { project: Project; onEdit: () => void }) {
  const { t } = useTranslation()
  const { data } = useQuery({ queryKey: ['report', 'project', project.id], queryFn: () => request<Summary>('GET', `/api/v1/projects/${project.id}/summary`) })
  const spent = -(data?.total_ref ?? 0)
  return (
    <Card withBorder opacity={project.archived_at ? 0.6 : 1}>
      <Group justify="space-between">
        <Text fw={600}>{project.name}</Text>
        <Button size="compact-xs" variant="subtle" onClick={onEdit}>{t('common.edit')}</Button>
      </Group>
      <Text size="xs" c="dimmed">{project.kind} · {project.start_date ? dayjs(project.start_date).format('MM-YYYY') : '…'} – {project.end_date ? dayjs(project.end_date).format('MM-YYYY') : '…'}</Text>
      <Text fz={22} fw={650} className="num" mt={4}><Money value={spent} /></Text>
      {project.budget_amount ? (
        <>
          <Progress value={Math.min(100, (spent / project.budget_amount) * 100)} color={spent > project.budget_amount ? 'red' : 'teal'} size="sm" />
          <Text size="xs" c="dimmed"><Money value={project.budget_amount} currency={project.budget_currency ?? 'EUR'} /> {t('wealth.budgetUsed')}</Text>
        </>
      ) : null}
      <Table mt="xs">
        <Table.Tbody>
          {(data?.by_category ?? []).slice(0, 6).map((r) => (
            <Table.Tr key={`${r.category_id}${r.currency}`}><Table.Td><Text size="sm">{r.name}</Text></Table.Td><Table.Td ta="right"><Money value={r.amount} currency={r.currency} abs /></Table.Td></Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <Anchor component={Link} to={`/transactions?project_id=${project.id}`} size="sm">{t('nav.transactions')} →</Anchor>
    </Card>
  )
}

function ProjectForm({ initial, onClose }: { initial: Partial<Project>; onClose: () => void }) {
  const { t } = useTranslation()
  const [f, setF] = useState(initial)
  const save = useApiMutation(async () => {
    const body = { name: f.name, kind: f.kind, start_date: f.start_date || null, end_date: f.end_date || null, budget_amount: f.budget_amount || null, budget_currency: f.budget_amount ? 'EUR' : null, notes: f.notes || null }
    if (f.id) await request('PATCH', `/api/v1/projects/${f.id}`, body)
    else await request('POST', '/api/v1/projects', body)
    onClose()
  }, [['projects'], ['report']], t('common.saved'))
  const archive = useApiMutation(async () => {
    await request('PATCH', `/api/v1/projects/${f.id}`, { archived: !f.archived_at })
    onClose()
  }, [['projects']])
  return (
    <Modal opened onClose={onClose} title={f.name || t('wealth.newProject')}>
      <Stack>
        <TextInput label={t('common.name')} value={f.name ?? ''} onChange={(e) => setF({ ...f, name: e.currentTarget.value })} />
        <Select label={t('common.type')} data={['renovation', 'trip', 'event', 'other']} value={f.kind} onChange={(v) => setF({ ...f, kind: v ?? 'other' })} />
        <Group grow>
          <DateInput label={t('common.from')} value={f.start_date ?? null} onChange={(v) => setF({ ...f, start_date: v })} valueFormat="DD-MM-YYYY" clearable />
          <DateInput label={t('common.to')} value={f.end_date ?? null} onChange={(v) => setF({ ...f, end_date: v })} valueFormat="DD-MM-YYYY" clearable />
        </Group>
        <MoneyInput label={t('nav.budget')} value={f.budget_amount ?? null} onChange={(v) => setF({ ...f, budget_amount: v })} currency="EUR" />
        <Group justify="space-between">
          {f.id ? <Button variant="subtle" color="gray" onClick={() => archive.mutate(undefined)}>{t('common.archive')}</Button> : <span />}
          <Button onClick={() => save.mutate(undefined)} disabled={!f.name}>{t('common.save')}</Button>
        </Group>
      </Stack>
    </Modal>
  )
}
