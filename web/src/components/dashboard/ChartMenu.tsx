// The ⋯ menu of a chart card (admins): edit, restyle, send, reorder, delete.
import { ActionIcon, Menu } from '@mantine/core'
import type { ChartMeta } from '../../api/types'
import { IconArrowDown, IconArrowUp, IconEdit, IconMore, IconPalette, IconSend, IconTrash } from '../icons'

export type CardActionKind = 'edit' | 'restyle' | 'send' | 'up' | 'down' | 'delete'
export type CardAction = { kind: CardActionKind; chart: ChartMeta }

export default function ChartMenu({ chart, onAction }: { chart: ChartMeta; onAction: (action: CardAction) => void }) {
  const act = (kind: CardActionKind) => () => onAction({ kind, chart })
  return (
    <Menu position="bottom-end" withinPortal>
      <Menu.Target>
        <ActionIcon variant="subtle" color="gray" radius="xl" className="card-menu-button" aria-label="Edit this chart"
                    data-testid={`chart-menu-${chart.id}`}>
          <IconMore size={18} />
        </ActionIcon>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Item leftSection={<IconEdit size={16} />} onClick={act('edit')}>Edit</Menu.Item>
        {chart.chart_type !== 'kpi' && (
          <Menu.Item leftSection={<IconPalette size={16} />} onClick={act('restyle')}>Change how it looks</Menu.Item>
        )}
        <Menu.Item leftSection={<IconSend size={16} />} onClick={act('send')}>Send to another dashboard</Menu.Item>
        <Menu.Divider />
        <Menu.Item leftSection={<IconArrowUp size={16} />} onClick={act('up')}>Move earlier</Menu.Item>
        <Menu.Item leftSection={<IconArrowDown size={16} />} onClick={act('down')}>Move later</Menu.Item>
        <Menu.Divider />
        <Menu.Item color="red" leftSection={<IconTrash size={16} />} onClick={act('delete')}>Delete</Menu.Item>
      </Menu.Dropdown>
    </Menu>
  )
}
