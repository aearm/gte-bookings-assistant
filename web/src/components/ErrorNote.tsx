// An error in plain words, with the technical text one click away (for support).
import { useState } from 'react'
import { Alert, Code } from '@mantine/core'
import { IconAlert } from './icons'

export default function ErrorNote({ message, details, title }: { message: string; details?: string | null; title?: string }) {
  const [open, setOpen] = useState(false)
  return (
    <Alert color="red" variant="light" radius="md" title={title} icon={<IconAlert size={18} />} data-testid="error-note">
      {message}
      {details ? (
        <div>
          <button type="button" className="details-toggle" onClick={() => setOpen((o) => !o)}>
            {open ? 'Hide technical details' : 'Technical details (for support)'}
          </button>
          {open && <Code block className="details-code">{details}</Code>}
        </div>
      ) : null}
    </Alert>
  )
}
