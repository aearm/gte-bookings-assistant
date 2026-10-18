// Inside a dialog that changes something shared: the content once signed in as admin, else why the
// admin password is needed and the sign-in form (the dialog stays open after signing in).
import type { ReactNode } from 'react'
import { Group, Text } from '@mantine/core'
import { IconLock } from '../icons'
import SignInForm from './SignInForm'
import { useSession } from './useSession'

export default function AdminGate({ what, children }: { what: string; children: ReactNode }) {
  const { isAdmin, isLoading } = useSession()
  if (isAdmin) return <>{children}</>
  if (isLoading) return null
  return (
    <>
      <Group gap={6} mb="sm" wrap="nowrap" align="flex-start">
        <IconLock size={16} style={{ marginTop: 2 }} />
        <Text size="sm" c="dimmed">Dashboards are shared with everyone, so {what} needs the admin password.</Text>
      </Group>
      <SignInForm />
    </>
  )
}
