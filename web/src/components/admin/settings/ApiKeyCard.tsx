// "Claude API key": whether one is saved (never the key itself), saving a new one, and testing it.
import { useState } from 'react'
import { Alert, Button, Group, PasswordInput, Stack, Text } from '@mantine/core'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../../../api/client'
import ErrorNote from '../ErrorNote'
import { CheckIcon, KeyIcon, WarnIcon } from '../icons'
import type { SettingsStatus } from '../types'

function modelsText(models: Record<string, unknown> | undefined): string {
  const named = Object.entries(models ?? {}).filter(([, v]) => typeof v === 'string' && v)
  return named.map(([k, v]) => `${k.replace(/_/g, ' ')}: ${v}`).join(' · ')
}

export default function ApiKeyCard({ status }: { status: SettingsStatus }) {
  const qc = useQueryClient()
  const [key, setKey] = useState('')
  const [problem, setProblem] = useState('')
  const [saved, setSaved] = useState(false)
  const save = useMutation({
    mutationFn: (value: string) => api.put('/settings/api-key', { key: value }),
    onSuccess: () => {
      setKey('')
      setSaved(true)
      void qc.invalidateQueries({ queryKey: ['settings'] })
      void qc.invalidateQueries({ queryKey: ['info'] })
    },
  })
  const test = useMutation({
    mutationFn: () => api.post<{ ok: boolean; model?: string; detail?: string; details?: string }>('/settings/api-key/test'),
  })
  const where = status.api_key_where ?? status.api_key

  const submit = () => {
    const value = key.trim()
    setSaved(false)
    test.reset()
    if (!value.startsWith('sk-ant-')) {
      setProblem("That doesn't look like a Claude API key. They start with sk-ant-.")
      return
    }
    setProblem('')
    save.mutate(value)
  }
  const models = modelsText(status.models)

  return (
    <Stack gap="sm">
      {where === 'set' || where === 'saved' ? (
        <Alert color="teal" icon={<CheckIcon />} data-testid="api-key-status" data-status="set">A key is saved securely.</Alert>
      ) : where === 'env' ? (
        <Alert color="yellow" icon={<WarnIcon />} data-testid="api-key-status" data-status="env">
          The key is currently read from the .env file as plain text. Save it here to store it securely; the copy in .env
          is then removed.
        </Alert>
      ) : (
        <Alert color="red" icon={<KeyIcon />} data-testid="api-key-status" data-status="missing">
          No key is saved. Questions can't be answered until you add one.
        </Alert>
      )}
      <form onSubmit={(e) => { e.preventDefault(); submit() }}>
        <Stack gap="xs" maw={520}>
          <PasswordInput label="New API key" placeholder="sk-ant-..." autoComplete="off" value={key}
                         description="Create one at https://platform.claude.com/settings/keys"
                         onChange={(e) => setKey(e.currentTarget.value)} error={problem || undefined}
                         data-testid="api-key-input" />
          <Group gap="sm">
            <Button type="submit" loading={save.isPending} disabled={!key.trim()} data-testid="api-key-save">Save key</Button>
            <Button variant="default" onClick={() => { setSaved(false); test.mutate() }} loading={test.isPending}
                    data-testid="api-key-test">
              Test the key
            </Button>
          </Group>
        </Stack>
      </form>
      {saved && <Text size="sm" c="teal" data-testid="api-key-saved">Saved. Use <b>Test the key</b> to check it works.</Text>}
      <ErrorNote error={save.error} />
      {test.data && (test.data.ok ? (
        <Alert color="teal" icon={<CheckIcon />} data-testid="api-key-test-result" data-ok="true">
          The key works{test.data.model ? ` (model: ${test.data.model})` : ''}.
        </Alert>
      ) : (
        <ErrorNote testId="api-key-test-result"
                   error={new ApiError(400, test.data.detail || "The key didn't work.", test.data.details)} />
      ))}
      <ErrorNote error={test.error} testId="api-key-test-error" />
      {models && <Text size="xs" c="dimmed">Models: {models}</Text>}
    </Stack>
  )
}
