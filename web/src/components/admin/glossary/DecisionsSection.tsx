// "Decisions" of the meaning layer for one cube: questions only a person can answer. Until someone agrees,
// Claude uses the proposed answer. Admins pick an answer and press Agree (POST /decisions/{id}); everyone
// else sees the answer used.
import { useState } from 'react'
import { Badge, Button, Group, Paper, Radio, Stack, Text } from '@mantine/core'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../../../api/client'
import type { Decision } from '../../../api/types'
import SignInButton from '../../auth/SignInButton'
import { Section } from '../PageHeader'
import ErrorNote from '../ErrorNote'
import { answerUsed, decisionChoices } from '../decisionHelpers'
import { LockIcon } from '../icons'

function DecisionCard({ decision, isAdmin }: { decision: Decision; isAdmin: boolean }) {
  const qc = useQueryClient()
  const current = answerUsed(decision)
  const [choice, setChoice] = useState(current)
  const agree = useMutation({
    mutationFn: () => api.post<Decision>(`/decisions/${encodeURIComponent(decision.id)}`, { answer: choice }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['decisions'] }),   // this cube's, and the open count
  })
  const agreed = decision.status === 'agreed'
  return (
    <Paper withBorder p="md" radius="md" data-testid={`decision-${decision.id}`} data-status={decision.status}>
      <Stack gap="xs">
        <Group gap="xs" wrap="wrap">
          <Text fw={600}>{decision.question}</Text>
          {agreed ? <Badge color="teal" variant="light">Agreed</Badge> : <Badge color="orange" variant="light">Proposed</Badge>}
        </Group>
        {decision.why && <Text size="sm" c="dimmed">{decision.why}</Text>}
        {isAdmin ? (
          <>
            <Radio.Group value={choice} onChange={setChoice} aria-label="Answer">
              <Stack gap={6}>
                {decisionChoices(decision).map((o, i) => (
                  <Radio key={o} value={o} label={o} data-testid={`decision-option-${decision.id}-${i}`} />
                ))}
              </Stack>
            </Radio.Group>
            <Group>
              <Button variant={agreed ? 'default' : 'filled'} onClick={() => agree.mutate()} loading={agree.isPending}
                      data-testid={`decision-agree-${decision.id}`}>
                Agree
              </Button>
            </Group>
            <ErrorNote error={agree.error} />
          </>
        ) : (
          <Text size="sm" c="dimmed" data-testid={`decision-answer-${decision.id}`}>Answer used: {current}</Text>
        )}
      </Stack>
    </Paper>
  )
}

export default function DecisionsSection({ items, open, isAdmin }: { items: Decision[]; open: number; isAdmin: boolean }) {
  if (!items.length) return null
  return (
    <Section title="Decisions" testId="decisions"
             caption={`Questions only a person can answer. Until someone agrees, Claude uses the proposed answer. ${open} decision${open === 1 ? '' : 's'} still open across all cubes.`}>
      {items.map((d) => (
        // keyed by the answer too, so the choice starts again from the server's answer after agreeing
        <DecisionCard key={`${d.id}:${d.status}:${answerUsed(d)}`} decision={d} isAdmin={isAdmin} />
      ))}
      {!isAdmin && (
        <Group gap={8}>
          <Text c="dimmed" span lh={0}><LockIcon size={16} /></Text>
          <Text size="sm" c="dimmed">Agreeing to decisions needs the admin password.</Text>
          <SignInButton label="Sign in" variant="button" />
        </Group>
      )}
    </Section>
  )
}
