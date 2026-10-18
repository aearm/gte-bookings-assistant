// The jobs an admin started on this page (by purpose: "layer", "draft:<cube>"), kept while moving between
// pages so coming back to the Cubes page still shows the progress of a build that is running.
import { create } from 'zustand'

type JobStore = {
  jobs: Record<string, string>
  setJob: (purpose: string, id: string) => void
  clearJob: (purpose: string) => void
}

export const useAdminJobs = create<JobStore>((set) => ({
  jobs: {},
  setJob: (purpose, id) => set((s) => ({ jobs: { ...s.jobs, [purpose]: id } })),
  clearJob: (purpose) => set((s) => {
    const jobs = { ...s.jobs }
    delete jobs[purpose]
    return { jobs }
  }),
}))
