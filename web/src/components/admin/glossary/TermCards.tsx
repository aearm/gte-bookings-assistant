// The glossary as cards, two per row: the term with its Agreed/Draft badge, what it means, where it is in
// the data and which date it uses, and who agreed it.
import { Badge, Group, Paper, SimpleGrid, Stack, Text, Title } from '@mantine/core'
import { isAgreed } from '../glossaryRows'
import type { GlossaryRow } from '../types'

export default function TermCards({ rows }: { rows: GlossaryRow[] }) {
  return (
    <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md" data-testid="glossary-terms">
      {rows.map((r, i) => {
        const details = [r.Measure, r['Date to use'] && `Date: ${r['Date to use']}`].filter(Boolean).join(' · ')
        return (
          <Paper key={`${r.Term}-${i}`} withBorder p="md" radius="md" data-testid="glossary-term-card"
                 data-term={r.Term} data-status={isAgreed(r) ? 'Agreed' : 'Draft'}>
            <Stack gap={6}>
              <Group gap="xs" wrap="wrap">
                <Title order={4}>{r.Term}</Title>
                {isAgreed(r) ? <Badge color="teal" variant="light">Agreed</Badge> : <Badge color="orange" variant="light">Draft</Badge>}
              </Group>
              {r.Meaning && <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>{r.Meaning}</Text>}
              {details && <Text size="xs" c="dimmed" ff="monospace">{details}</Text>}
              {r['Agreed by'] && <Text size="xs" c="dimmed">Agreed by {r['Agreed by']}</Text>}
            </Stack>
          </Paper>
        )
      })}
    </SimpleGrid>
  )
}
