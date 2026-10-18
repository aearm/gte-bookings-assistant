// A failed answer: the plain message, and the technical text behind a toggle (ui.show_error).
import { useState } from 'react'
import { Alert, Anchor, Code, Collapse, Stack } from '@mantine/core'
import { AlertIcon } from './icons'

export default function ErrorBlock({ message, details }: { message: string; details?: string }) {
  const [open, setOpen] = useState(false)
  return (
    <Alert color="red" variant="light" icon={<AlertIcon />} data-testid="chat-error">
      <Stack gap={6}>
        <div data-testid="chat-error-message">{message}</div>
        {details && (
          <>
            <Anchor component="button" type="button" size="sm" onClick={() => setOpen(o => !o)}
                    data-testid="chat-error-details-toggle" style={{ alignSelf: 'flex-start' }}>
              {open ? 'Hide technical details' : 'Technical details (for support)'}
            </Anchor>
            <Collapse expanded={open}>
              <Code block data-testid="chat-error-details" style={{ whiteSpace: 'pre-wrap', maxHeight: 300, overflow: 'auto' }}>
                {details}
              </Code>
            </Collapse>
          </>
        )}
      </Stack>
    </Alert>
  )
}
