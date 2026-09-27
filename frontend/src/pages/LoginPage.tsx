import { useState } from 'react'
import { Alert, Button, Center, Paper, PasswordInput, Stack, TextInput, Title } from '@mantine/core'
import { IconWallet } from '@tabler/icons-react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../auth'
import { ApiError } from '../api/client'

export function LoginPage() {
  const { t } = useTranslation()
  const { login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [totp, setTotp] = useState('')
  const [needTotp, setNeedTotp] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(email, password, totp || undefined)
    } catch (err) {
      if (err instanceof ApiError && err.code === 'totp_required') setNeedTotp(true)
      else setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Center mih="100vh" p="md">
      <Paper withBorder p="xl" w={360} maw="100%">
        <form onSubmit={submit}>
          <Stack>
            <Center><IconWallet size={36} color="var(--mantine-color-teal-6)" /></Center>
            <Title order={3} ta="center">{t('login.title')}</Title>
            <TextInput label={t('login.email')} type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.currentTarget.value)} required />
            <PasswordInput label={t('login.password')} autoComplete="current-password" value={password} onChange={(e) => setPassword(e.currentTarget.value)} required />
            {needTotp && (
              <TextInput label={t('login.totp')} inputMode="numeric" autoComplete="one-time-code" value={totp} onChange={(e) => setTotp(e.currentTarget.value)} autoFocus />
            )}
            {error && <Alert color="red">{error}</Alert>}
            <Button type="submit" loading={busy}>{t('login.submit')}</Button>
          </Stack>
        </form>
      </Paper>
    </Center>
  )
}
