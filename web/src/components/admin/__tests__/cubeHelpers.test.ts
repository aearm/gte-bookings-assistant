import { describe, expect, it } from 'vitest'
import type { Decision } from '../../../api/types'
import { cubeLabeller, openItems, openProposals, openQuestions, orderEnabled, setupProgress } from '../cubeHelpers'
import { answerUsed, decisionChoices } from '../decisionHelpers'
import { money, percent, plural, secondsText, shortCubeLabel, whenText } from '../format'
import type { CubeInfo, SetupItem, SetupState } from '../types'

describe('orderEnabled', () => {
  it("keeps the admin's order and adds new cubes at the end", () => {
    expect(orderEnabled(['B', 'A', 'C'], ['A', 'D', 'B'])).toEqual(['B', 'A', 'D'])
    expect(orderEnabled([], ['X', 'Y'])).toEqual(['X', 'Y'])
    expect(orderEnabled(['A'], [])).toEqual([])
    expect(orderEnabled(['A'], ['A', 'A', 'B'])).toEqual(['A', 'B'])
  })
})

describe('cube names', () => {
  it('shortens "Company - Bookings" to "Bookings", as cubes.label', () => {
    expect(shortCubeLabel('Company - Bookings')).toBe('Bookings')
    expect(shortCubeLabel('Bookings')).toBe('Bookings')
  })

  it("prefers the data layer's label for connected cubes", () => {
    const info: CubeInfo = { name: 'Co - Sales', label: 'Sales and payments', ready: true, setup: 'Ready', usable: true, coverage: '' }
    const label = cubeLabeller({ cubes: [info] })
    expect(label('Co - Sales')).toBe('Sales and payments')
    expect(label('Co - Searches')).toBe('Searches')
  })

  it("uses the server's labels for cubes not connected yet", () => {
    const label = cubeLabeller({ cubes: [], server_cubes_detail: [{ name: 'Co - Web', label: 'Web requests', updated: '' }] })
    expect(label('Co - Web')).toBe('Web requests')
  })
})

const item = (over: Partial<SetupItem>): SetupItem => ({
  term: 't', kind: 'number', clear: true, meaning: '', in_data: '', date_to_use: '', question: '', options: [],
  state: 'proposal', done: '', ...over,
})

describe('cube setup', () => {
  const state: SetupState = {
    drafted: '2026-10-16T10:00:00', summary: 'Bookings by day.',
    items: [
      item({ term: 'Bookings', state: 'question', done: 'answered' }),
      item({ term: 'Booking date', state: 'question' }),
      item({ term: 'Sales' }),
      item({ term: 'Valid', done: 'confirmed' }),
      item({ term: 'Destination' }),
    ],
  }

  it('lists the open items with their position in the list', () => {
    expect(openItems(state, 'question').map(([i, it]) => [i, it.term])).toEqual([[1, 'Booking date']])
    expect(openItems(state, 'proposal').map(([i]) => i)).toEqual([2, 4])
    expect(openItems(undefined, 'proposal')).toEqual([])
  })

  it('turns the full item list into open questions and proposals', () => {
    expect(openQuestions(state)).toEqual([{ index: 1, term: 'Booking date', question: '', options: [] }])
    expect(openProposals(state).map((p) => [p.index, p.term])).toEqual([[2, 'Sales'], [4, 'Destination']])
  })

  it("prefers the server's lists of open questions and proposals", () => {
    const server: SetupState = {
      summary: 'x',
      questions: [{ index: 3, term: 'Valid', question: 'Which bookings count as valid?', options: [] }],
      proposals: [{ index: 5, term: 'Sales', meaning: 'Final sales', in_data: '[Final Sales]' }],
    }
    expect(openQuestions(server).map((q) => q.index)).toEqual([3])
    expect(openProposals(server).map((p) => p.index)).toEqual([5])
    expect(setupProgress(server, true)).toEqual({ structure: true, drafted: true, questions: 1, proposals: 1, ready: false })
  })

  it("works out the progress when the server doesn't send it", () => {
    expect(setupProgress(state, true)).toEqual({ structure: true, drafted: true, questions: 1, proposals: 2, ready: false })
    expect(setupProgress({}, true)).toEqual({ structure: true, drafted: false, questions: 0, proposals: 0, ready: false })
    const done: SetupState = { ...state, items: state.items!.map((it) => ({ ...it, done: 'x' })) }
    expect(setupProgress(done, true).ready).toBe(true)
    expect(setupProgress(done, false).ready).toBe(false)
  })

  it("uses the server's progress when it sends it", () => {
    const progress = { structure: false, drafted: false, questions: 0, proposals: 0, ready: false }
    expect(setupProgress({ ...state, progress }, true)).toBe(progress)
  })
})

describe('decisions', () => {
  const d: Decision = {
    id: 'd1', cube: 'c', question: 'Which date?', why: '', options: ['Create date', 'Travel date'],
    proposed: 'Create date', answer: '', status: 'proposed',
  }

  it('uses the proposed answer until one is agreed', () => {
    expect(answerUsed(d)).toBe('Create date')
    expect(answerUsed({ ...d, answer: 'Travel date', status: 'agreed' })).toBe('Travel date')
  })

  it('offers the options, plus the proposed and current answers when missing, once each', () => {
    expect(decisionChoices(d)).toEqual(['Create date', 'Travel date'])
    expect(decisionChoices({ ...d, options: [], proposed: 'A', answer: 'B' })).toEqual(['A', 'B'])
    expect(decisionChoices({ ...d, options: ['X'], proposed: 'Y' })).toEqual(['X', 'Y'])
  })
})

describe('format', () => {
  it('writes amounts, shares, times and dates', () => {
    expect(money(1234.5)).toBe('$1,234.50')
    expect(money(0.0123, 3)).toBe('$0.012')
    expect(percent(0.756)).toBe('76%')
    expect(percent(null)).toBe('–')
    expect(secondsText(4.25)).toBe('4.3 s')
    expect(secondsText(14.6)).toBe('15 s')
    expect(whenText('2026-10-16T14:05:09')).toBe('16 Oct 14:05')
    expect(whenText('2026-10-06', true)).toBe('6 Oct 2026')
    expect(plural(1, 'cube')).toBe('1 cube')
    expect(plural(3, 'cube')).toBe('3 cubes')
  })
})
