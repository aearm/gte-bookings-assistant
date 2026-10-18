// Settings (admins only): Claude API key, the cube server and its login, the admin password, and the app
// version with updates. Keys and passwords are only ever sent, never shown.
import { Alert, Box, Center, Divider, Loader, Stack } from '@mantine/core'
import AdminOnly from '../../components/admin/AdminOnly'
import ErrorNote from '../../components/admin/ErrorNote'
import PageHeader, { Section } from '../../components/admin/PageHeader'
import { InfoIcon } from '../../components/admin/icons'
import { useInfo, useSettings } from '../../components/admin/queries'
import AdminPasswordCard from '../../components/admin/settings/AdminPasswordCard'
import ApiKeyCard from '../../components/admin/settings/ApiKeyCard'
import AppVersionCard from '../../components/admin/settings/AppVersionCard'
import ServerCard from '../../components/admin/settings/ServerCard'

function SettingsContent() {
  const settings = useSettings()
  const info = useInfo()
  if (settings.isLoading) return <Center py="xl"><Loader size="sm" /></Center>
  if (settings.error || !settings.data) return <ErrorNote error={settings.error ?? 'The settings could not be read.'} />
  const status = settings.data
  const local = (status.data_source ?? info.data?.data_source) === 'local'

  return (
    <Stack gap={0}>
      <Section title="Claude API key" testId="settings-api-key">
        <ApiKeyCard status={status} />
      </Section>
      <Divider mt="xl" />
      <Section title="Server" testId="settings-server">
        {local ? (
          <Alert color="blue" icon={<InfoIcon />} data-testid="server-local">
            The app is using local data files, so no server is needed.
          </Alert>
        ) : (
          <ServerCard status={status} />
        )}
      </Section>
      <Divider mt="xl" />
      <Section title="App version" testId="settings-version">
        <AppVersionCard version={info.data?.version} />
      </Section>
      <Divider mt="xl" />
      <Section title="Admin password" testId="settings-admin">
        <AdminPasswordCard />
      </Section>
    </Stack>
  )
}

export default function SettingsPage() {
  return (
    <Box data-testid="SettingsPage" maw={900}>
      <PageHeader title="Settings"
                  caption="Keys and passwords are saved in Windows Credential Manager on the computer running the app, never in a text file. They are never shown again after saving." />
      <AdminOnly what="The Settings page"><SettingsContent /></AdminOnly>
    </Box>
  )
}
