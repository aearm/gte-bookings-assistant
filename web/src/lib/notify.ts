// Short messages at the bottom right: what went wrong with a change, or that it worked.
import { notifications } from '@mantine/notifications'
import { ApiError } from '../api/client'

export function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message || 'Something went wrong.'
  if (error instanceof Error) return error.message
  return String(error ?? 'Something went wrong.')
}

export function errorDetails(error: unknown): string {
  return error instanceof ApiError ? error.details ?? '' : ''
}

export function notifyError(error: unknown, title = "That didn't work"): void {
  notifications.show({ color: 'red', title, message: errorText(error), autoClose: 8000 })
}

export function notifyDone(message: string): void {
  notifications.show({ color: 'green', message, autoClose: 3000 })
}
