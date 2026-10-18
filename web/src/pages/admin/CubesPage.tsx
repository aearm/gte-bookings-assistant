// Cubes (admins only): connect the cubes people can ask about, build the data layer once (Claude reads
// every cube, learns what each is for and how they join), and optionally set each cube up - let Claude
// draft a map of the business words, answer the few questions that aren't clear, and confirm the rest.
import { useState } from 'react'
import { Alert, Box, Center, Loader, Select, Stack } from '@mantine/core'
import AdminOnly from '../../components/admin/AdminOnly'
import ErrorNote from '../../components/admin/ErrorNote'
import PageHeader, { Section } from '../../components/admin/PageHeader'
import ConnectedCubes from '../../components/admin/cubes/ConnectedCubes'
import CubeSetup from '../../components/admin/cubes/CubeSetup'
import CubeStatusTable from '../../components/admin/cubes/CubeStatusTable'
import DataLayerPanel from '../../components/admin/cubes/DataLayerPanel'
import { cubeLabeller } from '../../components/admin/cubeHelpers'
import { InfoIcon } from '../../components/admin/icons'
import { useCubes, useDecisions, useInfo, useSettings } from '../../components/admin/queries'

function layerModelOf(models: Record<string, unknown> | undefined): string | undefined {
  const value = models?.layer ?? models?.data_layer
  return typeof value === 'string' ? value : undefined
}

function CubesContent() {
  const cubes = useCubes()
  const info = useInfo()
  const settings = useSettings()
  // the meaning layer's counts, only when the cube list doesn't carry them
  const decisions = useDecisions('', cubes.isSuccess && !cubes.data?.meaning)
  const [picked, setPicked] = useState<string | null>(null)

  if (cubes.isLoading) return <Center py="xl"><Loader size="sm" /></Center>
  if (cubes.error || !cubes.data) return <ErrorNote error={cubes.error ?? 'The cubes could not be read.'} testId="cubes-error" />
  const data = cubes.data
  const label = cubeLabeller(data)
  const local = data.local ?? info.data?.data_source === 'local'
  const connected = data.enabled
  const cube = picked && connected.includes(picked) ? picked : connected[0] ?? null
  const cubeInfo = data.cubes.find((c) => c.name === cube)

  return (
    <Stack gap={0}>
      <Section title="Connected cubes">
        {local ? (
          <Alert color="blue" icon={<InfoIcon />} data-testid="cubes-local">
            Local mode: the only data source is the files in data/local.
          </Alert>
        ) : (
          <>
            {data.server_error && <ErrorNote error={new Error(data.server_error)} testId="cubes-server-error" />}
            <ConnectedCubes key={connected.join('\n')} data={data} serverAddress={data.server || settings.data?.server.address} />
          </>
        )}
        {connected.length === 0 ? (
          <Alert color="blue" data-testid="cubes-none">Tick at least one cube above.</Alert>
        ) : <CubeStatusTable data={data} />}
      </Section>

      {connected.length > 0 && (
        <>
          <Section title="Data layer">
            <DataLayerPanel data={data} decisions={decisions.data} layerModel={layerModelOf(settings.data?.models)} />
          </Section>

          <Section title="Business words of a cube"
                   caption={<>Optional, per cube: agree what words like <i>bookings</i> or <i>valid</i> mean, so everyone
                     gets the same numbers.</>}>
            <Select label="Cube" value={cube} onChange={setPicked} allowDeselect={false} maw={520}
                    data-testid="setup-cube"
                    data={connected.map((name) => ({
                      value: name,
                      label: `${label(name)}  ·  ${data.cubes.find((c) => c.name === name)?.setup || 'Not set up'}`,
                    }))} />
            {cube && <CubeSetup key={cube} cube={cube} info={cubeInfo} label={label(cube)} />}
          </Section>
        </>
      )}
    </Stack>
  )
}

export default function CubesPage() {
  return (
    <Box data-testid="CubesPage" maw={1100}>
      <PageHeader title="Cubes"
                  caption="Choose which cubes people can ask about, build the data layer once so Claude understands all of them, and set up each cube's business words." />
      <AdminOnly what="The Cubes page"><CubesContent /></AdminOnly>
    </Box>
  )
}
