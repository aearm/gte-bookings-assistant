// One line per connected cube: read or not, in the data layer or not, its setup, and whether it has data.
import { Badge, Table, Text } from '@mantine/core'
import { cubeLabeller } from '../cubeHelpers'
import type { CubesData } from '../types'

export default function CubeStatusTable({ data }: { data: CubesData }) {
  const label = cubeLabeller(data)
  const info = new Map(data.cubes.map((c) => [c.name, c]))
  const inLayer = new Set(data.layer?.cubes ?? [])
  return (
    <Table.ScrollContainer minWidth={640}>
      <Table striped withTableBorder verticalSpacing="xs" data-testid="cube-status-table">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Cube</Table.Th>
            <Table.Th>Structure and values</Table.Th>
            <Table.Th>In the data layer</Table.Th>
            <Table.Th>Business words</Table.Th>
            <Table.Th>Data</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {data.enabled.map((name) => {
            const c = info.get(name)
            return (
              <Table.Tr key={name} data-testid={`cube-status-${name}`}>
                <Table.Td><Text size="sm" fw={500} title={name}>{label(name)}</Text></Table.Td>
                <Table.Td>
                  {c?.ready ? <Badge color="teal" variant="light">Read</Badge> : <Badge color="gray" variant="light">Not yet</Badge>}
                </Table.Td>
                <Table.Td>{(c?.in_layer ?? inLayer.has(name)) ? 'Yes' : 'Not yet'}</Table.Td>
                <Table.Td>
                  {c?.setup === 'Ready' ? <Badge color="teal" variant="light">Ready</Badge>
                    : <Text size="sm">{c?.setup || 'Not set up'}</Text>}
                </Table.Td>
                <Table.Td>
                  {c && !c.usable
                    ? <><Badge color="red" variant="light">No data</Badge>{c.coverage && <Text size="xs" c="dimmed">{c.coverage}</Text>}</>
                    : <Text size="sm">{c?.coverage || '–'}</Text>}
                </Table.Td>
              </Table.Tr>
            )
          })}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  )
}
