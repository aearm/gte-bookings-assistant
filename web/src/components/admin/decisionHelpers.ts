// Decisions of the meaning layer: until a person agrees, Claude uses the proposed answer.
import type { Decision } from '../../api/types'

/** The answer Claude uses now. */
export const answerUsed = (d: Decision): string => d.answer || d.proposed

/** The choices to offer: the decision's options, then the proposed and current answers if they are
 * not among them (no duplicates, no blanks). */
export function decisionChoices(d: Decision): string[] {
  return [...new Set([...(d.options ?? []), d.proposed, answerUsed(d)].filter((o): o is string => !!o))]
}
