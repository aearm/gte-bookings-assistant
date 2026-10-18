// The title and one-line explanation at the top of an admin or reference page.
import type { ReactNode } from 'react'
import { Stack, Text, Title } from '@mantine/core'

export default function PageHeader({ title, caption, children }: { title: string; caption?: ReactNode; children?: ReactNode }) {
  return (
    <Stack gap={4} mb="lg">
      <Title order={2}>{title}</Title>
      {caption && <Text c="dimmed" size="sm">{caption}</Text>}
      {children}
    </Stack>
  )
}

/** A section heading inside a page, with an optional caption under it. */
export function Section({ title, caption, children, testId }: {
  title: string; caption?: ReactNode; children?: ReactNode; testId?: string
}) {
  return (
    <Stack gap="sm" mt="xl" data-testid={testId}>
      <Stack gap={2}>
        <Title order={3}>{title}</Title>
        {caption && <Text c="dimmed" size="sm">{caption}</Text>}
      </Stack>
      {children}
    </Stack>
  )
}
