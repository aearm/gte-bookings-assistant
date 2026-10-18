// Cubes page logic that needs no screen: the order of connected cubes, names to show, and the open
// steps of a cube's setup.
import { shortCubeLabel } from './format'
import type { CubesData, OpenProposal, OpenQuestion, SetupItem, SetupProgress, SetupState } from './types'

/** The cubes to save: the admin's existing order kept, newly ticked ones added at the end (as the
 * current app). */
export function orderEnabled(current: string[], picked: string[]): string[] {
  const chosen = new Set(picked)
  return [...current.filter((c) => chosen.has(c)), ...picked.filter((c) => !current.includes(c))]
    .filter((c, i, all) => all.indexOf(c) === i)
}

/** name → label for every cube the page knows about (connected ones carry the data layer's label). */
export function cubeLabeller(data: Pick<CubesData, 'cubes' | 'server_cubes_detail'> | undefined): (name: string) => string {
  const known = new Map((data?.server_cubes_detail ?? []).map((c) => [c.name, c.label || shortCubeLabel(c.name)]))
  for (const c of data?.cubes ?? []) known.set(c.name, c.label || shortCubeLabel(c.name))
  return (name) => known.get(name) ?? shortCubeLabel(name)
}

/** [index, item] of the items still waiting in a state, from the full `items` list (index = position in
 * items, which is what the answer/skip/confirm calls take). */
export function openItems(state: SetupState | undefined, kind: SetupItem['state']): [number, SetupItem][] {
  return (state?.items ?? []).map((it, i) => [i, it] as [number, SetupItem]).filter(([, it]) => it.state === kind && !it.done)
}

/** The questions still to answer (the server's list, or worked out from the items). */
export function openQuestions(state: SetupState | undefined): OpenQuestion[] {
  if (state?.questions) return state.questions
  return openItems(state, 'question').map(([index, it]) => ({ index, term: it.term, question: it.question, options: it.options ?? [] }))
}

/** What Claude understood that is still to confirm (the server's list, or worked out from the items). */
export function openProposals(state: SetupState | undefined): OpenProposal[] {
  if (state?.proposals) return state.proposals
  return openItems(state, 'proposal').map(([index, it]) => ({ index, term: it.term, meaning: it.meaning, in_data: it.in_data }))
}

/** The setup's progress (from the server when it sends it, else worked out from what is open). */
export function setupProgress(state: SetupState | undefined, structureRead: boolean): SetupProgress {
  if (state?.progress) return state.progress
  const drafted = !!state?.items?.length || !!state?.drafted || !!state?.summary
  const questions = openQuestions(state).length, proposals = openProposals(state).length
  return { structure: structureRead, drafted, questions, proposals,
           ready: structureRead && drafted && !questions && !proposals }
}

export const SOMETHING_ELSE = 'Something else…'
