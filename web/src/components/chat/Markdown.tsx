// The little Markdown Claude's written answers use: paragraphs, "- " lists, **bold**, *italic*, `code`.
// Built as React elements (no HTML injection).
import { Fragment, memo, type ReactNode } from 'react'
import { Code, List, Text } from '@mantine/core'

const INLINE = /(\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\*[^*\s][^*]*\*|_[^_\s][^_]*_)/g

function inline(text: string): ReactNode[] {
  return text.split(INLINE).filter(Boolean).map((part, i) => {
    if ((part.startsWith('**') && part.endsWith('**')) || (part.startsWith('__') && part.endsWith('__')))
      return <strong key={i}>{part.slice(2, -2)}</strong>
    if (part.startsWith('`') && part.endsWith('`')) return <Code key={i}>{part.slice(1, -1)}</Code>
    if (part.length > 2 && ((part.startsWith('*') && part.endsWith('*')) || (part.startsWith('_') && part.endsWith('_'))))
      return <em key={i}>{part.slice(1, -1)}</em>
    return <Fragment key={i}>{part}</Fragment>
  })
}

type Block = { kind: 'p'; lines: string[] } | { kind: 'ul'; items: string[] } | { kind: 'h'; text: string }

function blocks(text: string): Block[] {
  const out: Block[] = []
  for (const raw of text.replace(/\r\n/g, '\n').split('\n')) {
    const line = raw.trimEnd()
    const last = out[out.length - 1]
    const bullet = /^\s*(?:[-*•]|\d+[.)])\s+(.*)$/.exec(line)
    const heading = /^#{1,6}\s+(.*)$/.exec(line)
    if (!line.trim()) out.push({ kind: 'p', lines: [] })
    else if (heading) out.push({ kind: 'h', text: heading[1] })
    else if (bullet) {
      if (last?.kind === 'ul') last.items.push(bullet[1])
      else out.push({ kind: 'ul', items: [bullet[1]] })
    } else if (last?.kind === 'p') last.lines.push(line)
    else out.push({ kind: 'p', lines: [line] })
  }
  return out.filter(b => b.kind !== 'p' || b.lines.length)
}

function Markdown({ text, testId }: { text: string; testId?: string }) {
  if (!text?.trim()) return null
  return (
    <div data-testid={testId}>
      {blocks(text).map((b, i) => {
        if (b.kind === 'h') return <Text key={i} fw={600} mb={4}>{inline(b.text)}</Text>
        if (b.kind === 'ul') {
          return (
            <List key={i} size="sm" mb="xs" spacing={2}>
              {b.items.map((item, j) => <List.Item key={j}>{inline(item)}</List.Item>)}
            </List>
          )
        }
        return <Text key={i} size="sm" mb="xs">{inline(b.lines.join(' '))}</Text>
      })}
    </div>
  )
}

export default memo(Markdown)
