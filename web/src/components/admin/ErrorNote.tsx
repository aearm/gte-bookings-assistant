// A failed call shown the way the current app shows it: the plain-English message, and the technical
// text folded away "for support". A 401 (signed out meanwhile) offers the sign-in button.
import { Alert, Code, Collapse, Stack, UnstyledButton, Text } from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { ApiError } from '../../api/client'
import SignInButton from '../auth/SignInButton'
import { ErrorIcon } from './icons'

export default function ErrorNote({ error, testId }: { error: unknown; testId?: string }) {
  const [open, { toggle }] = useDisclosure(false)
  if (!error) return null
  const message = error instanceof Error ? error.message : String(error)
  const details = error instanceof ApiError ? error.details : undefined
  const signedOut = error instanceof ApiError && error.status === 401
  return (
    <Alert color="red" icon={<ErrorIcon />} data-testid={testId ?? 'error-note'}>
      <Stack gap={6}>
        <Text size="sm">{message || 'Something went wrong.'}</Text>
        {signedOut && <div><SignInButton label="Sign in" variant="button" /></div>}
        {details && (
          <>
            <UnstyledButton onClick={toggle}>
              <Text size="xs" c="dimmed" td="underline">Technical details (for support)</Text>
            </UnstyledButton>
            <Collapse expanded={open}>
              <Code block style={{ whiteSpace: 'pre-wrap' }}>{details}</Code>
            </Collapse>
          </>
        )}
      </Stack>
    </Alert>
  )
}
