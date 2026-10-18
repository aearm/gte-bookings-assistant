// Every change to dashboards and their charts (admin), and the cached data each change makes stale.
import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useCallback, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { ChartMeta, Dashboard, DashboardSummary } from '../api/types'
import { dashboardPath } from './queries'

export type NewChart = {
  question: string; title: string; chart_type: string; width: 'half' | 'full'; cube: string; date_column: string
  period_mode: 'dashboard' | 'own' | 'fixed'; chart_request?: string
}
export type ChartChanges = Partial<{
  title: string; chart_type: string; width: 'half' | 'full'; date_column: string; period_mode: 'dashboard' | 'own' | 'fixed'
  compare: boolean; question: string; chart_request: string
}>

const chartPath = (id: string, chartId: string) => `${dashboardPath(id)}/charts/${encodeURIComponent(chartId)}`

function stale(client: QueryClient, ids: string[], { menu = false, results = true } = {}) {
  for (const id of ids) {
    void client.invalidateQueries({ queryKey: ['dashboard', id] })
    if (results) void client.invalidateQueries({ queryKey: ['results', id] })
  }
  if (menu) void client.invalidateQueries({ queryKey: ['dashboards'] })
}

export function dashboardActions(client: QueryClient) {
  return {
    async createDashboard(name: string): Promise<Dashboard> {
      const board = await api.post<Dashboard>('/dashboards', { name: name.trim() })
      client.setQueryData(['dashboard', board.id], board)
      client.setQueryData<DashboardSummary[]>(['dashboards'], (list) =>
        list && [...list, { id: board.id, name: board.name, charts: board.charts.length }])
      stale(client, [], { menu: true })
      return board
    },
    async renameDashboard(id: string, name: string): Promise<Dashboard> {
      const board = await api.patch<Dashboard>(dashboardPath(id), { name: name.trim() })
      client.setQueryData(['dashboard', id], board)
      stale(client, [], { menu: true })
      return board
    },
    async deleteDashboard(id: string): Promise<void> {
      await api.del(dashboardPath(id))
      client.setQueryData<DashboardSummary[]>(['dashboards'], (list) => list?.filter((b) => b.id !== id))
      client.removeQueries({ queryKey: ['dashboard', id] })
      client.removeQueries({ queryKey: ['results', id] })
      stale(client, [], { menu: true })
    },
    async addChart(id: string, chart: NewChart): Promise<ChartMeta> {
      const meta = await api.post<ChartMeta>(`${dashboardPath(id)}/charts`, chart)
      stale(client, [id], { menu: true })
      return meta
    },
    async updateChart(id: string, chartId: string, changes: ChartChanges): Promise<ChartMeta> {
      const meta = await api.patch<ChartMeta>(chartPath(id, chartId), changes)
      stale(client, [id])
      return meta
    },
    async restyleChart(id: string, chartId: string, request: string): Promise<ChartMeta> {
      const meta = await api.post<ChartMeta>(`${chartPath(id, chartId)}/restyle`, { request })
      stale(client, [id])
      return meta
    },
    async sendChart(id: string, chartId: string, to: string, move: boolean): Promise<void> {
      await api.post(`${chartPath(id, chartId)}/send`, { to, move })
      stale(client, move ? [id, to] : [to], { menu: true })
    },
    async moveChart(id: string, chartId: string, step: -1 | 1): Promise<void> {
      const board = await api.post<Dashboard>(`${chartPath(id, chartId)}/move`, { step })
      client.setQueryData(['dashboard', id], board) // the same numbers, in a new order
    },
    async deleteChart(id: string, chartId: string): Promise<void> {
      await api.del(chartPath(id, chartId))
      client.setQueryData<Dashboard>(['dashboard', id], (board) =>
        board && { ...board, charts: board.charts.filter((c) => c.id !== chartId) })
      stale(client, [id], { menu: true, results: false })
    },
  }
}

export function useDashboardActions() {
  const client = useQueryClient()
  return useMemo(() => dashboardActions(client), [client])
}

/** Busy state and the error of one change made from a dialog. */
export function useRunner() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const run = useCallback(async <T,>(work: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true)
    setError(null)
    try {
      return await work()
    } catch (e) {
      setError(e)
      return undefined
    } finally {
      setBusy(false)
    }
  }, [])
  const reset = useCallback(() => setError(null), [])
  return { busy, error, run, reset }
}
