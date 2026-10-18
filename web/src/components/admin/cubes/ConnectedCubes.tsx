// "Connected cubes": tick the cubes on the server people can ask about (PUT /cubes/enabled).
// Key this component by the saved list so it starts again from the server's answer after saving.
import { useMemo, useState } from 'react'
import { Button, Checkbox, Group, SimpleGrid, Stack, Text } from '@mantine/core'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../../../api/client'
import ErrorNote from '../ErrorNote'
import { cubeLabeller, orderEnabled } from '../cubeHelpers'
import type { CubesData } from '../types'

export default function ConnectedCubes({ data, serverAddress }: { data: CubesData; serverAddress?: string }) {
  const qc = useQueryClient()
  const label = cubeLabeller(data)
  const updated = new Map((data.server_cubes_detail ?? []).map((c) => [c.name, c.updated]))
  const available = useMemo(() => [...data.server_cubes].sort((a, b) => a.localeCompare(b)), [data.server_cubes])
  const [picked, setPicked] = useState<string[]>(data.enabled)
  const save = useMutation({
    mutationFn: (names: string[]) => api.put<CubesData>('/cubes/enabled', { names }),
    onSuccess: (next) => {
      if (next && Array.isArray(next.enabled)) qc.setQueryData(['cubes'], next)
      else void qc.invalidateQueries({ queryKey: ['cubes'] })
      void qc.invalidateQueries({ queryKey: ['info'] })   // the cube pickers of Chat and the Glossary
    },
  })
  const changed = orderEnabled(data.enabled, picked).join('\n') !== data.enabled.join('\n')

  return (
    <Stack gap="sm" data-testid="connected-cubes">
      <Text size="sm" c="dimmed">
        {available.length} cube{available.length === 1 ? '' : 's'} on {serverAddress ? <code>{serverAddress}</code> : 'the server'}.
        {' '}Tick the ones to use.
      </Text>
      <Checkbox.Group value={picked} onChange={setPicked}>
        <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }} spacing="xs" verticalSpacing="xs">
          {available.map((name) => (
            <Checkbox key={name} value={name} label={label(name)} title={name}
                      description={[label(name) !== name ? name : '', updated.get(name) ? `updated ${updated.get(name)}` : '']
                        .filter(Boolean).join(' · ') || undefined}
                      data-testid={`cube-enable-${name}`} />
          ))}
        </SimpleGrid>
      </Checkbox.Group>
      <Group gap="sm">
        <Button onClick={() => save.mutate(orderEnabled(data.enabled, picked))} loading={save.isPending}
                disabled={!changed} data-testid="cubes-save">
          Save
        </Button>
        <Button variant="default" disabled={save.isPending} data-testid="cubes-use-all"
                onClick={() => { setPicked(available); save.mutate(orderEnabled(data.enabled, available)) }}>
          Use all cubes
        </Button>
      </Group>
      <ErrorNote error={save.error} />
    </Stack>
  )
}
