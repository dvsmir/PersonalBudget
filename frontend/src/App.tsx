import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { Center, Loader } from '@mantine/core'
import { useAuth } from './auth'
import { AppLayout } from './layout/AppLayout'
import { LoginPage } from './pages/LoginPage'
import { TxnEditorProvider } from './components/TxnEditor'

const DashboardPage = lazy(() => import('./pages/DashboardPage'))
const YearPage = lazy(() => import('./pages/YearPage'))
const TransactionsPage = lazy(() => import('./pages/TransactionsPage'))
const ImportPage = lazy(() => import('./pages/ImportPage'))
const ImportBatchPage = lazy(() => import('./pages/ImportBatchPage'))
const BudgetPage = lazy(() => import('./pages/BudgetPage'))
const AccountsPage = lazy(() => import('./pages/AccountsPage'))
const DebtsPage = lazy(() => import('./pages/DebtsPage'))
const AssetsPage = lazy(() => import('./pages/AssetsPage'))
const EarmarksPage = lazy(() => import('./pages/EarmarksPage'))
const ProjectsPage = lazy(() => import('./pages/ProjectsPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))

const Spinner = () => (
  <Center h="60vh">
    <Loader />
  </Center>
)

export function App() {
  const { user, ready } = useAuth()
  if (!ready) return <Spinner />
  if (!user) return <LoginPage />
  return (
    <TxnEditorProvider>
      <AppLayout>
        <Suspense fallback={<Spinner />}>
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/year" element={<YearPage />} />
            <Route path="/transactions" element={<TransactionsPage />} />
            <Route path="/import" element={<ImportPage />} />
            <Route path="/import/:batchId" element={<ImportBatchPage />} />
            <Route path="/budget" element={<BudgetPage />} />
            <Route path="/wealth/accounts" element={<AccountsPage />} />
            <Route path="/wealth/debts" element={<DebtsPage />} />
            <Route path="/wealth/assets" element={<AssetsPage />} />
            <Route path="/wealth/earmarks" element={<EarmarksPage />} />
            <Route path="/projects" element={<ProjectsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </AppLayout>
    </TxnEditorProvider>
  )
}
