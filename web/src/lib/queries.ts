// The app-wide queries (keys as listed in components/auth/useSession.ts), in one place so pages,
// the menu and the start-up prefetch ask for the same data the same way.
import { queryOptions, type QueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Dashboard, DashboardResults, DashboardSummary, Info, Session } from '../api/types'
import { resultsQuery, type ResultsParams } from './periodState'

export const sessionQuery = queryOptions({
  queryKey: ['session'], queryFn: () => api.get<Session>('/session'), staleTime: 5 * 60_000,
})

export const infoQuery = queryOptions({
  queryKey: ['info'], queryFn: () => api.get<Info>('/info'), staleTime: 10 * 60_000,
})

export const dashboardsQuery = queryOptions({
  queryKey: ['dashboards'], queryFn: () => api.get<DashboardSummary[]>('/dashboards'),
})

export const dashboardPath = (id: string) => `/dashboards/${encodeURIComponent(id)}`

export const dashboardQuery = (id: string) => queryOptions({
  queryKey: ['dashboard', id], queryFn: () => api.get<Dashboard>(dashboardPath(id)),
})

export const resultsKey = (id: string, params?: ResultsParams) =>
  (params ? ['results', id, params] : ['results', id]) as readonly unknown[]

export const fetchResults = (id: string, params: ResultsParams, force = false) =>
  api.get<DashboardResults>(`${dashboardPath(id)}/results?${resultsQuery(params, force)}`)

/** Asked for as soon as the app starts (before React draws): who is signed in, the defaults, the menu. */
export function prefetchStartup(client: QueryClient): void {
  void client.prefetchQuery(sessionQuery)
  void client.prefetchQuery(infoQuery)
  void client.prefetchQuery(dashboardsQuery)
}
