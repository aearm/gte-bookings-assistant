// "Sign in" button that opens the admin sign-in form (used by the top-right pill and by locked pages).
import { Button, Modal, Text, Tooltip } from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { IconLock } from '../icons'
import SignInForm from './SignInForm'

export type SignInButtonProps = { label?: string; variant?: 'pill' | 'button' }

export default function SignInButton({ label, variant = 'button' }: SignInButtonProps) {
  const [opened, { open, close }] = useDisclosure(false)
  return (
    <>
      {variant === 'pill' ? (
        <Tooltip label="Dashboards and Chat work for everyone. Sign in as admin to add or change things.">
          <button type="button" className="auth-pill auth-pill--signin" onClick={open} data-testid="signin-pill">
            <IconLock size={15} /> {label ?? 'View only · Sign in'}
          </button>
        </Tooltip>
      ) : (
        <Button leftSection={<IconLock size={16} />} onClick={open} data-testid="signin-button">{label ?? 'Sign in'}</Button>
      )}
      <Modal opened={opened} onClose={close} title={<b>Sign in as admin</b>} size="sm">
        <Text size="sm" c="dimmed" mb="md">
          Admins can add and change dashboards, connect cubes and change settings. Everyone can use the dashboards and Chat.
        </Text>
        <SignInForm onDone={close} />
      </Modal>
    </>
  )
}
