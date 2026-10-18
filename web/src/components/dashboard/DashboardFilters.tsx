// The dashboard's own filters, first in the row above its charts (e.g. which client the Client view shows):
// a list to type into, of the clients or markets with sales in the last year, biggest first. Nothing
// picked: the dashboard shows the first (the server says which it used).
import { Select } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'
import type { FilterChoices, FilterMeta } from '../../api/types'
import { dashboardPath } from '../../lib/queries'

type Props = {
  dashboardId: string
  filters: FilterMeta[]
  picked: Record<string, string> // in the address
  used: Record<string, string> | undefined // what the last results were for
  onChange: (key: string, value: string) => void
}

export default function DashboardFilters({ dashboardId, filters, picked, used, onChange }: Props) {
  const choices = useQuery<FilterChoices[]>({
    queryKey: ['filters', dashboardId],
    queryFn: () => api.get<FilterChoices[]>(`${dashboardPath(dashboardId)}/filters`),
    staleTime: 60 * 60_000, // the lists change slowly (the server keeps them for hours)
  })
  return (
    <>
      {filters.map((f) => {
        const choice = choices.data?.find((c) => c.key === f.key)
        const value = picked[f.key] || used?.[f.key] || choice?.default || null
        return (
          <Select key={f.key} data-testid={`filter-${f.key}`} aria-label={f.label} w={300} searchable
                  allowDeselect={false} limit={60} maxDropdownHeight={360} nothingFoundMessage="Nothing matches"
                  placeholder={choices.isLoading ? `Loading the ${f.label.toLowerCase()} list…` : f.label}
                  error={choice?.error || undefined}
                  data={choice?.options ?? (value ? [{ value, label: value }] : [])}
                  value={value} onChange={(v) => v && onChange(f.key, v)}
                  onFocus={(e) => e.currentTarget.select()} // typing replaces the name shown, to search
                  comboboxProps={{ withinPortal: true }} />
        )
      })}
    </>
  )
}
