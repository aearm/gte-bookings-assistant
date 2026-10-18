// "Admin password": change it (the current one is asked for first), and sign out of admin.
import { useState } from 'react'
import { Alert, Button, Group, PasswordInput, Stack, Text } from '@mantine/core'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../../../api/client'
import ErrorNote from '../ErrorNote'
import { CheckIcon } from '../icons'

export default function AdminPasswordCard() {
  const qc = useQueryClient()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [again, setAgain] = useState('')
  const [problem, setProblem] = useState('')
  const change = useMutation({
    mutationFn: () => api.put<{ ok: boolean }>('/settings/admin-password', { current, new: next }),
    onSuccess: () => {
      setCurrent('')
      setNext('')
      setAgain('')
      void qc.invalidateQueries({ queryKey: ['session'] })
    },
  })
  const signOut = useMutation({
    mutationFn: () => api.del('/session'),
    onSettled: () => {
      qc.setQueryData(['session'], (s: { admin: boolean } | undefined) => (s ? { ...s, admin: false } : s))
      void qc.invalidateQueries({ queryKey: ['session'] })
    },
  })

  const submit = () => {
    change.reset()
    if (next.length < 8) return setProblem('Use at least 8 characters.')
    if (next !== again) return setProblem("The two passwords don't match.")
    setProblem('')
    change.mutate()
  }

  return (
    <Stack gap="sm">
      <form onSubmit={(e) => { e.preventDefault(); submit() }}>
        <Stack gap="xs" maw={520}>
          <PasswordInput label="Current admin password" autoComplete="current-password" value={current}
                         onChange={(e) => setCurrent(e.currentTarget.value)} data-testid="admin-current" />
          <PasswordInput label="New admin password" autoComplete="new-password" value={next}
                         onChange={(e) => setNext(e.currentTarget.value)} data-testid="admin-new" />
          <PasswordInput label="Type it again" autoComplete="new-password" value={again}
                         onChange={(e) => setAgain(e.currentTarget.value)} data-testid="admin-new2" />
          {problem && <Text size="sm" c="red" data-testid="admin-password-problem">{problem}</Text>}
          <Group>
            <Button type="submit" variant="default" loading={change.isPending} disabled={!current || !next}
                    data-testid="admin-password-save">
              Change admin password
            </Button>
          </Group>
        </Stack>
      </form>
      <ErrorNote error={change.error} />
      {change.isSuccess && (
        <Alert color="teal" icon={<CheckIcon />} data-testid="admin-password-changed">Admin password changed.</Alert>
      )}
      <Group>
        <Button variant="subtle" color="gray" onClick={() => signOut.mutate()} loading={signOut.isPending}
                data-testid="sign-out">
          Sign out of admin
        </Button>
      </Group>
    </Stack>
  )
}
