// The frame of every page: the menu (dashboards, Chat, Glossary, admin pages) and the sign-in pill.
import { Suspense, useState, type ReactNode } from 'react'
import { AppShell as Frame, Burger, Group, Loader, Menu, Skeleton, Text } from '@mantine/core'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, Outlet, matchPath, useLocation } from 'react-router-dom'
import { notifyError } from '../lib/notify'
import { preloadPage, type PageName } from '../lib/pages'
import { dashboardQuery, dashboardsQuery } from '../lib/queries'
import { useUiStore } from '../lib/uiStore'
import { usePeriodStore } from '../lib/usePeriodStore'
import SignInButton from './auth/SignInButton'
import { useSession, useSignOut } from './auth/useSession'
import { NewDashboardDialog } from './dashboard/dialogs/DashboardDialogs'
import {
  IconBook, IconChat, IconCube, IconDashboard, IconLock, IconLogout, IconPlus, IconSettings, IconShield, IconUsage,
} from './icons'

export default function AppShell() {
  const { pathname } = useLocation()
  // on a phone the menu is open for the page it was opened on: picking a page closes it
  const [openOn, setOpenOn] = useState<string | null>(null)
  const opened = openOn === pathname
  const toggle = () => setOpenOn(opened ? null : pathname)
  const newDashboard = useUiStore((s) => s.newDashboard)
  const closeNewDashboard = useUiStore((s) => s.closeNewDashboard)

  return (
    <Frame header={{ height: 52 }} navbar={{ width: 248, breakpoint: 'sm', collapsed: { mobile: !opened } }} padding="lg"
           withBorder={false}>
      <Frame.Header className="app-header">
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" aria-label="Menu" />
            <Link to="/" className="app-brand">Bookings Assistant</Link>
          </Group>
          <AuthPill />
        </Group>
      </Frame.Header>
      <Frame.Navbar className="app-nav">
        <NavMenu />
      </Frame.Navbar>
      <Frame.Main className="app-main">
        <Suspense fallback={<div className="page-loader"><Loader size="sm" /></div>}>
          <Outlet />
        </Suspense>
      </Frame.Main>
      <NewDashboardDialog opened={newDashboard} onClose={closeNewDashboard} />
    </Frame>
  )
}

function NavMenu() {
  const { pathname } = useLocation()
  const { isAdmin } = useSession()
  const boards = useQuery(dashboardsQuery)
  const client = useQueryClient()
  const periodSearch = usePeriodStore((s) => s.search)
  const openNew = useUiStore((s) => s.openNewDashboard)
  const current = matchPath('/dashboard/:id', pathname)?.params.id ?? (pathname === '/' ? boards.data?.[0]?.id : undefined)
  const locked = !isAdmin

  return (
    <nav className="nav" aria-label="Pages">
      <div className="nav-heading">
        <span>Dashboards</span>
        <button type="button" className="nav-add" title="New dashboard" aria-label="New dashboard" onClick={openNew}
                data-testid="nav-new-dashboard">
          <IconPlus size={16} />
        </button>
      </div>
      {boards.isLoading && [0, 1, 2].map((i) => <Skeleton key={i} height={26} radius="md" my={3} />)}
      {boards.isError && <div className="nav-empty">The dashboards could not be loaded.</div>}
      {boards.data?.length === 0 && <div className="nav-empty">No dashboards yet.</div>}
      {boards.data?.map((b) => (
        <NavItem key={b.id} to={`/dashboard/${encodeURIComponent(b.id)}${periodSearch ? `?${periodSearch}` : ''}`}
                 active={b.id === current} icon={<IconDashboard size={17} />} label={b.name}
                 onHover={() => void client.prefetchQuery(dashboardQuery(b.id))} testId={`nav-dashboard-${b.id}`} />
      ))}

      <div className="nav-heading"><span>Ask</span></div>
      <PageItem page="chat" path="/chat" label="Chat" icon={<IconChat size={17} />} pathname={pathname} />
      <PageItem page="glossary" path="/glossary" label="Glossary" icon={<IconBook size={17} />} pathname={pathname} />

      <div className="nav-heading">
        <span>Admin{locked && <span className="note"> · sign in to open</span>}</span>
      </div>
      <PageItem page="cubes" path="/cubes" label="Cubes" pathname={pathname} icon={locked ? <IconLock size={17} /> : <IconCube size={17} />} />
      <PageItem page="settings" path="/settings" label="Settings" pathname={pathname}
                icon={locked ? <IconLock size={17} /> : <IconSettings size={17} />} />
      <PageItem page="usage" path="/usage" label="Usage" pathname={pathname} icon={locked ? <IconLock size={17} /> : <IconUsage size={17} />} />
    </nav>
  )
}

function PageItem({ page, path, label, icon, pathname }: { page: PageName; path: string; label: string; icon: ReactNode; pathname: string }) {
  return <NavItem to={path} label={label} icon={icon} active={pathname === path} onHover={() => preloadPage(page)}
                  testId={`nav-${page}`} />
}

function NavItem({ to, label, icon, active, onHover, testId }: {
  to: string; label: string; icon: ReactNode; active: boolean; onHover?: () => void; testId?: string
}) {
  return (
    <Link to={to} className={`nav-link${active ? ' active' : ''}`} aria-current={active ? 'page' : undefined}
          onMouseEnter={onHover} onFocus={onHover} data-testid={testId}>
      {icon}<span className="label">{label}</span>
    </Link>
  )
}

/** Top right: "View only · Sign in", or "Admin" with Sign out. */
function AuthPill() {
  const { isAdmin, isLoading } = useSession()
  const signOut = useSignOut()
  if (isLoading) return null
  if (!isAdmin) return <SignInButton variant="pill" />
  return (
    <Menu position="bottom-end" width={260}>
      <Menu.Target>
        <button type="button" className="auth-pill auth-pill--admin" data-testid="admin-pill">
          <IconShield size={15} /> Admin
        </button>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label><Text size="sm" fw={600} c="var(--mantine-color-text)">Signed in as admin</Text></Menu.Label>
        <Text size="xs" c="dimmed" px="sm" pb="xs">You can add and change dashboards, cubes, the glossary and settings.</Text>
        <Menu.Item leftSection={<IconLogout size={16} />} onClick={() => signOut().catch((e) => notifyError(e))}
                   data-testid="sign-out">
          Sign out
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  )
}
