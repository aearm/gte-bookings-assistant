// The dashboard's ⋯ menu: new dashboard, rename, delete (renaming and deleting need the admin sign-in).
import { ActionIcon, Menu, Text } from '@mantine/core'
import { useUiStore } from '../../lib/uiStore'
import { IconEdit, IconMore, IconNewDashboard, IconTrash } from '../icons'

type Props = { isAdmin: boolean; onRename: () => void; onDelete: () => void }

export default function DashboardMenu({ isAdmin, onRename, onDelete }: Props) {
  const openNew = useUiStore((s) => s.openNewDashboard)
  return (
    <Menu position="bottom-end" withinPortal>
      <Menu.Target>
        <ActionIcon variant="default" size="lg" radius="xl" aria-label="Dashboard options" data-testid="dashboard-menu">
          <IconMore size={18} />
        </ActionIcon>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Item leftSection={<IconNewDashboard size={16} />} onClick={openNew}>New dashboard</Menu.Item>
        <Menu.Item leftSection={<IconEdit size={16} />} onClick={onRename} disabled={!isAdmin}>Rename</Menu.Item>
        <Menu.Item leftSection={<IconTrash size={16} />} onClick={onDelete} disabled={!isAdmin} color="red">Delete dashboard</Menu.Item>
        {!isAdmin && (
          <Text size="xs" c="dimmed" px="sm" py={6} maw={240}>
            Renaming and deleting need the admin sign-in (top of the page).
          </Text>
        )}
      </Menu.Dropdown>
    </Menu>
  )
}
