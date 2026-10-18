// The admin sign-in form, or the first-time "create an admin password" form when none exists yet.
import { useState, type FormEvent } from 'react'
import { Alert, Button, Checkbox, PasswordInput, Stack, Text } from '@mantine/core'
import { useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../../api/client'
import { errorText } from '../../lib/notify'
import { sessionChanged, useSession } from './useSession'

export const KEEP_DAYS = 30

export default function SignInForm({ onDone }: { onDone?: () => void }) {
  const { data } = useSession()
  return data && !data.has_admin_password ? <CreatePasswordForm onDone={onDone} /> : <PasswordForm onDone={onDone} />
}

function PasswordForm({ onDone }: { onDone?: () => void }) {
  const client = useQueryClient()
  const [password, setPassword] = useState('')
  const [keep, setKeep] = useState(true)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState('')

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setProblem('')
    try {
      await api.post('/session', { password, keep })
      sessionChanged(client, { admin: true, has_admin_password: true })
      onDone?.()
    } catch (error) {
      setProblem(error instanceof ApiError && error.status === 401
        ? "That password isn't right. (Forgotten it? Run reset_admin_password.py on the server.)"
        : errorText(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} data-testid="signin-form">
      <Stack gap="sm">
        <PasswordInput placeholder="Admin password" aria-label="Admin password" value={password} autoFocus
                       onChange={(e) => setPassword(e.currentTarget.value)} />
        <Checkbox label="Keep me signed in on this computer" checked={keep} onChange={(e) => setKeep(e.currentTarget.checked)}
                  description={`For ${KEEP_DAYS} days, or until you sign out or the admin password changes.`} />
        {problem && <Text c="red" size="sm">{problem}</Text>}
        <Button type="submit" fullWidth loading={busy} disabled={!password}>Sign in</Button>
      </Stack>
    </form>
  )
}

function CreatePasswordForm({ onDone }: { onDone?: () => void }) {
  const client = useQueryClient()
  const [password, setPassword] = useState('')
  const [again, setAgain] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState('')

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (password.length < 8) return setProblem('Use at least 8 characters.')
    if (password !== again) return setProblem("The two passwords don't match.")
    setBusy(true)
    setProblem('')
    try {
      await api.post('/session/first-password', { password })
      sessionChanged(client, { admin: true, has_admin_password: true })
      onDone?.()
    } catch (error) {
      setProblem(errorText(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} data-testid="create-password-form">
      <Stack gap="sm">
        <Alert color="apple" variant="light" radius="md">
          First, create an admin password. Only people who know it can change dashboards, keys and the glossary.{' '}
          <b>Do this before you share the app link with others.</b>
        </Alert>
        <PasswordInput label="New admin password" value={password} autoFocus onChange={(e) => setPassword(e.currentTarget.value)} />
        <PasswordInput label="Type it again" value={again} onChange={(e) => setAgain(e.currentTarget.value)} />
        {problem && <Text c="red" size="sm">{problem}</Text>}
        <Button type="submit" fullWidth loading={busy} disabled={!password}>Create admin password</Button>
      </Stack>
    </form>
  )
}
