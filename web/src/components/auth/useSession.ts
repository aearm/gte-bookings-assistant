// Who is using the app: everyone can view; admins (signed in) can change things.
// Query keys used across the app: ['session'], ['info'], ['dashboards'], ['dashboard', id],
// ['results', id, params], ['periods', params], ['conversation', id], ['glossary', cube],
// ['decisions', cube], ['cubes'], ['settings'], ['updates'], ['usage', days], ['job', id], ['history'].
import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'
import { api } from '../../api/client'
import type { Session } from '../../api/types'
import { sessionQuery } from '../../lib/queries'

export function useSession() {
  const q = useQuery(sessionQuery)
  return { data: q.data, isAdmin: !!q.data?.admin, isLoading: q.isLoading }
}

/** After signing in or out: the new session, and queries that failed (admin pages) asked again. */
export function sessionChanged(client: QueryClient, session: Session): void {
  client.setQueryData(['session'], session)
  void client.invalidateQueries({ queryKey: ['session'] })
  void client.refetchQueries({ predicate: (q) => q.state.status === 'error' })
}

export function useSignOut() {
  const client = useQueryClient()
  return useCallback(async () => {
    await api.del('/session')
    sessionChanged(client, { admin: false, has_admin_password: true })
  }, [client])
}
