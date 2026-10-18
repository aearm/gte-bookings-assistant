// The period last picked on a dashboard (the address query), so links in the menu open other
// dashboards on the same dates - as the period carried over between dashboards in the old app.
import { create } from 'zustand'

type PeriodStore = { search: string; setSearch: (search: string) => void }

export const usePeriodStore = create<PeriodStore>((set) => ({
  search: '',
  setSearch: (search) => set((state) => (state.search === search ? state : { search })),
}))
