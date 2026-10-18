// What an admin page shows when nobody is signed in (as admin.locked_page): "Admins only" and the
// sign-in button. Signed in, it shows the page.
import type { ReactNode } from 'react'
import { Center, Group, Loader, Paper, Stack, Text, Title } from '@mantine/core'
import SignInButton from '../auth/SignInButton'
import { useSession } from '../auth/useSession'
import { LockIcon } from './icons'

export function LockedPanel({ what }: { what: string }) {
  return (
    <Center py="xl">
      <Paper withBorder p="lg" radius="md" maw={460} w="100%" data-testid="admin-locked">
        <Stack gap="sm">
          <Group gap={8}>
            <LockIcon />
            <Title order={4}>Admins only</Title>
          </Group>
          <Text c="dimmed" size="sm">{what} is for admins. Sign in with the admin password to continue.</Text>
          <div><SignInButton label="Sign in" variant="button" /></div>
        </Stack>
      </Paper>
    </Center>
  )
}

/** The page's content for admins; the locked panel for everyone else. `what` names the page,
 * e.g. "The Cubes page". */
export default function AdminOnly({ what, children }: { what: string; children: ReactNode }) {
  const { isAdmin, isLoading } = useSession()
  if (isLoading) return <Center py="xl"><Loader size="sm" /></Center>
  if (!isAdmin) return <LockedPanel what={what} />
  return <>{children}</>
}
