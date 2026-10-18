// Glossary: what the business words mean in a cube (its map). Everyone can read it, admins can edit it and
// agree to the meaning layer's decisions, and Claude follows it for every question about that cube.
import { Alert, Anchor, Box, Center, Divider, Group, Loader, Select, Stack, Text, Title } from '@mantine/core'
import { Link, useSearchParams } from 'react-router-dom'
import SignInButton from '../../components/auth/SignInButton'
import { useSession } from '../../components/auth/useSession'
import ErrorNote from '../../components/admin/ErrorNote'
import PageHeader from '../../components/admin/PageHeader'
import DecisionsSection from '../../components/admin/glossary/DecisionsSection'
import GlossaryEditor from '../../components/admin/glossary/GlossaryEditor'
import TermCards from '../../components/admin/glossary/TermCards'
import { isAgreed, normalizeRow } from '../../components/admin/glossaryRows'
import { InfoIcon, LockIcon, WarnIcon } from '../../components/admin/icons'
import { useDecisions, useGlossary, useInfo } from '../../components/admin/queries'

function GlossaryContent({ cube, label }: { cube: string; label: string }) {
  const { isAdmin } = useSession()
  const glossary = useGlossary(cube)
  const decisions = useDecisions(cube)

  if (glossary.isLoading) return <Center py="xl"><Loader size="sm" /></Center>
  if (glossary.error || !glossary.data) return <ErrorNote error={glossary.error ?? 'The glossary could not be read.'} />
  const data = glossary.data
  const rows = (data.rows ?? []).map(normalizeRow)
  const drafts = rows.filter((r) => !isAgreed(r))

  return (
    <Stack gap="md">
      <Text size="sm" c="dimmed">
        What the words mean in <b>{data.label || label}</b>. Claude follows these definitions in every answer, so everyone
        gets the same numbers for the same question.
      </Text>
      {data.summary && <Text data-testid="glossary-summary">{data.summary}</Text>}

      {decisions.error ? <ErrorNote error={decisions.error} /> : decisions.data && (
        <DecisionsSection items={decisions.data.items ?? []} open={decisions.data.open ?? 0} isAdmin={isAdmin} />
      )}

      {rows.length === 0 ? (
        <Alert color="blue" icon={<InfoIcon />} data-testid="glossary-empty">
          <Text size="sm">Nothing here yet. An admin sets up this cube on the Cubes page, which fills in the glossary.</Text>
          <Anchor component={Link} to="/cubes" size="sm">Open the Cubes page</Anchor>
        </Alert>
      ) : drafts.length > 0 && (
        <Alert color="yellow" icon={<WarnIcon />} data-testid="glossary-drafts">
          <b>{drafts.length} of {rows.length} definitions are drafts.</b> When a question depends on one, Claude asks or
          says which option it used.
        </Alert>
      )}

      {rows.length > 0 && <TermCards rows={rows} />}
      {data.updated && <Text size="xs" c="dimmed">Last updated {data.updated}</Text>}

      <Divider my="md" />
      <Title order={3}>Edit</Title>
      {isAdmin ? (
        <GlossaryEditor key={cube} cube={cube} rows={rows} />
      ) : (
        <Group gap={8} data-testid="glossary-locked">
          <Text c="dimmed" span lh={0}><LockIcon size={16} /></Text>
          <Text size="sm" c="dimmed">You're not signed in. Editing the glossary needs the admin password.</Text>
          <SignInButton label="Sign in" variant="button" />
        </Group>
      )}
    </Stack>
  )
}

export default function GlossaryPage() {
  const info = useInfo()
  const [params, setParams] = useSearchParams()
  const cubes = (info.data?.scopes ?? []).filter((s) => s.value)
  const asked = params.get('cube')
  const cube = cubes.find((c) => c.value === asked) ?? cubes[0]

  return (
    <Box data-testid="GlossaryPage" maw={1100}>
      <PageHeader title="Glossary">
        {cubes.length > 0 && (
          <Select label="Cube" maw={420} mt="xs" allowDeselect={false} data-testid="glossary-cube"
                  data={cubes.map((c) => ({ value: c.value, label: c.label }))} value={cube?.value ?? null}
                  onChange={(v) => v && setParams((p) => { p.set('cube', v); return p }, { replace: true })} />
        )}
      </PageHeader>
      {info.isLoading ? <Center py="xl"><Loader size="sm" /></Center>
        : info.error ? <ErrorNote error={info.error} />
        : !cube ? (
          <Alert color="blue" icon={<InfoIcon />} data-testid="glossary-no-cubes">
            No cube is connected yet. An admin connects cubes on the Cubes page.
          </Alert>
        ) : <GlossaryContent key={cube.value} cube={cube.value} label={cube.label} />}
    </Box>
  )
}
