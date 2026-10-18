// New dashboard, rename, delete (admin).
import { useState, type FormEvent } from 'react'
import { Button, Group, Modal, Stack, Text, TextInput } from '@mantine/core'
import { useNavigate } from 'react-router-dom'
import type { Dashboard } from '../../../api/types'
import { useDashboardActions, useRunner } from '../../../lib/dashboardActions'
import { errorDetails, errorText } from '../../../lib/notify'
import AdminGate from '../../auth/AdminGate'
import ErrorNote from '../../ErrorNote'

function Problem({ error }: { error: unknown }) {
  return error ? <ErrorNote message={errorText(error)} details={errorDetails(error)} /> : null
}

export function NewDashboardDialog({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  return (
    <Modal opened={opened} onClose={onClose} title={<b>New dashboard</b>}>
      <AdminGate what="adding a dashboard">{opened && <NewDashboardForm onClose={onClose} />}</AdminGate>
    </Modal>
  )
}

function NewDashboardForm({ onClose }: { onClose: () => void }) {
  const actions = useDashboardActions()
  const navigate = useNavigate()
  const { busy, error, run } = useRunner()
  const [name, setName] = useState('')
  const create = async (event: FormEvent) => {
    event.preventDefault()
    const board = await run(() => actions.createDashboard(name))
    if (board) {
      onClose()
      navigate(`/dashboard/${encodeURIComponent(board.id)}`)
    }
  }
  return (
    <form onSubmit={create}>
      <Stack gap="sm">
        <TextInput label="Name" placeholder="e.g. Sales overview" value={name} data-autofocus
                   onChange={(e) => setName(e.currentTarget.value)} />
        <Problem error={error} />
        <Group justify="flex-end"><Button type="submit" loading={busy} disabled={!name.trim()}>Create</Button></Group>
      </Stack>
    </form>
  )
}

export function RenameDashboardDialog({ board, opened, onClose }: { board: Dashboard | undefined; opened: boolean; onClose: () => void }) {
  return (
    <Modal opened={opened && !!board} onClose={onClose} title={<b>Rename dashboard</b>}>
      {board && opened && <RenameForm board={board} onClose={onClose} />}
    </Modal>
  )
}

function RenameForm({ board, onClose }: { board: Dashboard; onClose: () => void }) {
  const actions = useDashboardActions()
  const { busy, error, run } = useRunner()
  const [name, setName] = useState(board.name)
  const save = async (event: FormEvent) => {
    event.preventDefault()
    if (await run(() => actions.renameDashboard(board.id, name))) onClose()
  }
  return (
    <form onSubmit={save}>
      <Stack gap="sm">
        <TextInput label="Name" value={name} data-autofocus onChange={(e) => setName(e.currentTarget.value)} />
        <Problem error={error} />
        <Group justify="flex-end"><Button type="submit" loading={busy} disabled={!name.trim()}>Save</Button></Group>
      </Stack>
    </form>
  )
}

export function DeleteDashboardDialog({ board, opened, onClose }: { board: Dashboard | undefined; opened: boolean; onClose: () => void }) {
  const actions = useDashboardActions()
  const navigate = useNavigate()
  const { busy, error, run } = useRunner()
  const remove = async () => {
    if (!board) return
    const done = await run(async () => {
      await actions.deleteDashboard(board.id)
      return true
    })
    if (done) {
      onClose()
      navigate('/', { replace: true })
    }
  }
  return (
    <Modal opened={opened && !!board} onClose={onClose} title={<b>Delete dashboard</b>}>
      <Stack gap="sm">
        <Text size="sm">Delete <b>{board?.name}</b> and its {board?.charts.length ?? 0} chart(s) for everyone?</Text>
        <Problem error={error} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Cancel</Button>
          <Button color="red" onClick={remove} loading={busy} data-testid="confirm-delete-dashboard">Delete dashboard</Button>
        </Group>
      </Stack>
    </Modal>
  )
}
