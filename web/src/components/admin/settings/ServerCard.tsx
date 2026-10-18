// "Server": the Analysis Services server, its database and the login the app uses. Shows only whether a
// login is saved, never the password. A blank password keeps the saved one.
import { useState } from 'react'
import { Alert, Button, Checkbox, Group, PasswordInput, Stack, Text, TextInput } from '@mantine/core'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../../../api/client'
import ErrorNote from '../ErrorNote'
import { CheckIcon, InfoIcon, KeyIcon } from '../icons'
import type { CubesData, SettingsStatus } from '../types'

export default function ServerCard({ status }: { status: SettingsStatus }) {
  const qc = useQueryClient()
  const server = status.server ?? { address: '', database: '', login_saved: false }
  const [address, setAddress] = useState(server.address ?? '')
  const [database, setDatabase] = useState(server.database ?? '')
  const known = server.username ?? ''   // only if the server tells it
  const [username, setUsername] = useState(known)
  const [password, setPassword] = useState('')
  const [windowsLogin, setWindowsLogin] = useState(false)
  const [problem, setProblem] = useState('')
  const [saved, setSaved] = useState(false)

  const save = useMutation({
    mutationFn: (body: Record<string, string>) => api.put('/settings/server', body),
    onSuccess: () => {
      setPassword('')
      setWindowsLogin(false)
      setSaved(true)
      for (const key of ['settings', 'cubes', 'info']) void qc.invalidateQueries({ queryKey: [key] })
    },
  })
  // connects and counts the cubes this login can open; without that call, asks for the cube list afresh
  const test = useMutation({
    mutationFn: async () => {
      try {
        return (await api.post<{ ok: boolean; cubes: number }>('/settings/server/test')).cubes
      } catch (err) {
        if (!(err instanceof ApiError) || (err.status !== 404 && err.status !== 405)) throw err
        const data = await api.get<CubesData>('/cubes?fresh=true')
        if (data.server_error) throw new Error(data.server_error)
        return data.server_cubes?.length ?? 0
      }
    },
  })

  const submit = () => {
    setSaved(false)
    const body: Record<string, string> = { server: address.trim(), database: database.trim() }
    if (!body.server) return setProblem('Enter the server.')
    // no username in the body = keep the saved login; username "" = this computer's Windows login
    const name = username.trim()
    if (windowsLogin) {
      body.username = ''
      body.password = ''
    } else if (name && name !== known) {
      if (!password) return setProblem('Enter the password for the new username too.')
      body.username = name
      body.password = password
    } else if (password) {
      if (name) body.username = name
      body.password = password   // a new password for the saved username
    }
    setProblem('')
    save.mutate(body)
  }

  return (
    <Stack gap="sm">
      {!server.address ? (
        <Alert color="red" icon={<InfoIcon />} data-testid="server-status" data-status="none">No server set yet.</Alert>
      ) : server.login_saved ? (
        <Alert color="teal" icon={<CheckIcon />} data-testid="server-status" data-status="login">
          {server.username ? <>Signed in as <b>{server.username}</b>. </> : 'A login is saved. '}Password saved securely.
        </Alert>
      ) : server.username && !server.windows_login ? (
        <Alert color="red" icon={<KeyIcon />} data-testid="server-status" data-status="no-password">
          No password saved for <b>{server.username}</b>.
        </Alert>
      ) : (
        <Alert color="blue" icon={<InfoIcon />} data-testid="server-status" data-status="windows">
          No username set: the app signs in with this computer's Windows login.
        </Alert>
      )}

      <form onSubmit={(e) => { e.preventDefault(); submit() }}>
        <Stack gap="xs" maw={520}>
          <TextInput label="Server" placeholder="bi.example.com:2383" value={address} data-testid="server-address"
                     description="The Analysis Services server, as shown in Power BI > Data source settings."
                     onChange={(e) => setAddress(e.currentTarget.value)} />
          <TextInput label="Database" value={database} data-testid="server-database"
                     description="The cube to use when none is chosen. Choose the cubes people can ask about on the Cubes page."
                     onChange={(e) => setDatabase(e.currentTarget.value)} />
          <Checkbox label="Sign in with this computer's Windows login (no username)" checked={windowsLogin}
                    onChange={(e) => setWindowsLogin(e.currentTarget.checked)} data-testid="server-windows-login" />
          {!windowsLogin && (
            <>
              <TextInput label="Username" autoComplete="off" value={username} data-testid="server-username"
                         placeholder={server.login_saved ? 'Leave blank to keep the saved login' : undefined}
                         description="Exactly as you type it in Excel or Power BI (often name@domain or DOMAIN\name)."
                         onChange={(e) => setUsername(e.currentTarget.value)} />
              <PasswordInput label="Password" autoComplete="new-password" value={password} data-testid="server-password"
                             placeholder="Leave blank to keep the saved password"
                             onChange={(e) => setPassword(e.currentTarget.value)} />
            </>
          )}
          {problem && <Text size="sm" c="red" data-testid="server-problem">{problem}</Text>}
          <Group gap="sm">
            <Button type="submit" loading={save.isPending} data-testid="server-save">Save</Button>
            <Button variant="default" onClick={() => { setSaved(false); test.mutate() }} loading={test.isPending}
                    data-testid="server-test">
              Test server
            </Button>
          </Group>
        </Stack>
      </form>
      {saved && (
        <Text size="sm" c="teal" data-testid="server-saved">
          Saved. Use <b>Test server</b> to check it works, then choose the cubes to use on the <b>Cubes</b> page.
        </Text>
      )}
      <ErrorNote error={save.error} />
      {test.data !== undefined && (
        <Alert color="teal" icon={<CheckIcon />} data-testid="server-test-result">
          Connected. {test.data} cubes available - choose them on the Cubes page.
        </Alert>
      )}
      <ErrorNote error={test.error} testId="server-test-error" />
    </Stack>
  )
}
