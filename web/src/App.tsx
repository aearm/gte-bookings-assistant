// Routes of the app. The shell (menu, sign-in pill) is components/AppShell.tsx. Dashboards are the
// first page and load with the app; the other pages load in their own files when first opened.
import { lazy } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import AppShell from './components/AppShell'
import DashboardPage from './pages/DashboardPage'
import { pageLoaders } from './lib/pages'

const ChatPage = lazy(pageLoaders.chat)
const GlossaryPage = lazy(pageLoaders.glossary)
const CubesPage = lazy(pageLoaders.cubes)
const SettingsPage = lazy(pageLoaders.settings)
const UsagePage = lazy(pageLoaders.usage)

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="dashboard/:id" element={<DashboardPage />} />
        <Route path="chat" element={<ChatPage />} />
        <Route path="glossary" element={<GlossaryPage />} />
        <Route path="cubes" element={<CubesPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="usage" element={<UsagePage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
