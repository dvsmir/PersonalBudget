import type { ReactNode } from 'react'
import { AppShell, Burger, Button, Group, Menu, NavLink, SegmentedControl, Text, Tooltip, ActionIcon, useMantineColorScheme } from '@mantine/core'
import { useDisclosure, useHotkeys } from '@mantine/hooks'
import {
  IconBuildingBank, IconCalendarStats, IconChartPie, IconCoin, IconFileImport, IconFolders, IconHome, IconList,
  IconLogout, IconMoon, IconPigMoney, IconPlus, IconReceipt2, IconSettings, IconSun, IconUser, IconWallet,
} from '@tabler/icons-react'
import { Link, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../auth'
import { usePrefs } from '../lib/prefs'
import { useTxnEditor } from '../components/TxnEditor'

const NAV = [
  { to: '/', key: 'dashboard', icon: IconHome },
  { to: '/year', key: 'year', icon: IconCalendarStats },
  { to: '/transactions', key: 'transactions', icon: IconList },
  { to: '/import', key: 'import', icon: IconFileImport },
  { to: '/budget', key: 'budget', icon: IconChartPie },
]
const WEALTH = [
  { to: '/wealth/accounts', key: 'accounts', icon: IconBuildingBank },
  { to: '/wealth/debts', key: 'debts', icon: IconReceipt2 },
  { to: '/wealth/assets', key: 'assets', icon: IconCoin },
  { to: '/wealth/earmarks', key: 'earmarks', icon: IconPigMoney },
]

export function AppLayout({ children }: { children: ReactNode }) {
  const [opened, { toggle, close }] = useDisclosure()
  const { t, i18n } = useTranslation()
  const { pathname } = useLocation()
  const { user, logout } = useAuth()
  const { currencyMode, setCurrencyMode } = usePrefs()
  const { openNew } = useTxnEditor()
  const { colorScheme, setColorScheme } = useMantineColorScheme()
  useHotkeys([['n', () => openNew()]])

  const link = (item: { to: string; key: string; icon: typeof IconHome }) => (
    <NavLink
      key={item.to}
      component={Link}
      to={item.to}
      label={t(`nav.${item.key}`)}
      leftSection={<item.icon size={18} stroke={1.6} />}
      active={item.to === '/' ? pathname === '/' : pathname.startsWith(item.to)}
      onClick={close}
    />
  )

  return (
    <AppShell header={{ height: 56 }} navbar={{ width: 230, breakpoint: 'sm', collapsed: { mobile: !opened } }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" aria-label="menu" />
            <IconWallet size={24} color="var(--mantine-color-teal-6)" />
            <Text fw={700} visibleFrom="xs">Budget</Text>
          </Group>
          <Group gap="xs" wrap="nowrap">
            <Tooltip label={currencyMode === 'reference' ? 'All amounts in EUR' : 'Each currency separately'}>
              <SegmentedControl
                size="xs"
                value={currencyMode}
                onChange={(v) => setCurrencyMode(v as 'reference' | 'native')}
                data={[{ value: 'reference', label: t('common.reference') }, { value: 'native', label: t('common.native') }]}
              />
            </Tooltip>
            <Button size="xs" leftSection={<IconPlus size={16} />} onClick={() => openNew()}>
              <Text span size="xs" visibleFrom="xs">{t('common.add')}</Text>
            </Button>
            <ActionIcon variant="subtle" aria-label="theme" onClick={() => setColorScheme(colorScheme === 'dark' ? 'light' : 'dark')}>
              {colorScheme === 'dark' ? <IconSun size={18} /> : <IconMoon size={18} />}
            </ActionIcon>
            <Menu position="bottom-end">
              <Menu.Target>
                <ActionIcon variant="subtle" aria-label="user"><IconUser size={18} /></ActionIcon>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Label>{user?.display_name}</Menu.Label>
                <Menu.Item onClick={() => { i18n.changeLanguage('en'); localStorage.setItem('budget.lang', 'en') }}>English</Menu.Item>
                <Menu.Item onClick={() => { i18n.changeLanguage('ru'); localStorage.setItem('budget.lang', 'ru') }}>Русский</Menu.Item>
                <Menu.Divider />
                <Menu.Item component={Link} to="/settings" leftSection={<IconSettings size={16} />}>{t('nav.settings')}</Menu.Item>
                <Menu.Item color="red" leftSection={<IconLogout size={16} />} onClick={logout}>{t('common.logout')}</Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="xs">
        {NAV.map(link)}
        <Text size="xs" c="dimmed" fw={600} tt="uppercase" mt="md" mb={4} px="sm">{t('nav.wealth')}</Text>
        {WEALTH.map(link)}
        <Text size="xs" c="dimmed" fw={600} tt="uppercase" mt="md" mb={4} px="sm"> </Text>
        {link({ to: '/projects', key: 'projects', icon: IconFolders })}
        {link({ to: '/settings', key: 'settings', icon: IconSettings })}
      </AppShell.Navbar>
      <AppShell.Main>{children}</AppShell.Main>
    </AppShell>
  )
}
