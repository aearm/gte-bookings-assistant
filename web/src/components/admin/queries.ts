// Reads of the admin and reference pages, under the app's shared query keys (see auth/useSession.ts).
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'
import type { Decision, Info } from '../../api/types'
import type { CubesData, GlossaryData, SettingsStatus, SetupState, UpdatesInfo, UsageData } from './types'

const enc = encodeURIComponent

export function useInfo() {
  return useQuery<Info>({ queryKey: ['info'], queryFn: () => api.get<Info>('/info') })
}

export function useCubes(enabled = true) {
  return useQuery<CubesData>({ queryKey: ['cubes'], queryFn: () => api.get<CubesData>('/cubes'), enabled })
}

export function useCubeSetup(cube: string | null) {
  return useQuery<SetupState>({
    queryKey: ['cube-setup', cube], enabled: !!cube,
    queryFn: () => api.get<SetupState>(`/cubes/${enc(cube!)}/setup`),
  })
}

export function useGlossary(cube: string | null) {
  return useQuery<GlossaryData>({
    queryKey: ['glossary', cube], enabled: !!cube,
    queryFn: () => api.get<GlossaryData>(`/glossary/${enc(cube!)}`),
  })
}

export type DecisionsData = { open: number; items: Decision[] }

/** One cube's decisions (and how many are open across all cubes); '' = every cube's. */
export function useDecisions(cube: string, enabled = true) {
  return useQuery<DecisionsData>({
    queryKey: ['decisions', cube], enabled,
    queryFn: () => api.get<DecisionsData>(cube ? `/decisions?cube=${enc(cube)}` : '/decisions'),
  })
}

export function useSettings(enabled = true) {
  return useQuery<SettingsStatus>({ queryKey: ['settings'], queryFn: () => api.get<SettingsStatus>('/settings'), enabled })
}

/** The version running, an update in progress, the last update's outcome and the newest release (the
 * server asks GitHub at most every few minutes; "Check for updates" asks afresh with ?fresh=true). */
export function useUpdates(enabled = true) {
  return useQuery<UpdatesInfo>({
    queryKey: ['updates'], queryFn: () => api.get<UpdatesInfo>('/updates'), enabled,
    staleTime: 5 * 60_000, retry: false,
  })
}

export function useUsage(days: number, enabled = true) {
  return useQuery<UsageData>({
    queryKey: ['usage', days], queryFn: () => api.get<UsageData>(`/usage?days=${days}`), enabled,
  })
}
