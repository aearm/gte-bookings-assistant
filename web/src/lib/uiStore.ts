// Small app-wide UI state: the "New dashboard" dialog opens from the menu's + and from a dashboard's
// own menu, and is drawn once by the shell.
import { create } from 'zustand'

type UiStore = { newDashboard: boolean; openNewDashboard: () => void; closeNewDashboard: () => void }

export const useUiStore = create<UiStore>((set) => ({
  newDashboard: false,
  openNewDashboard: () => set({ newDashboard: true }),
  closeNewDashboard: () => set({ newDashboard: false }),
}))
