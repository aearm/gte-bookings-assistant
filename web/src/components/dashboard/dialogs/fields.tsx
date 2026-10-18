// Form fields the chart dialogs share: chart type, size, which date the period filters, period mode.
import { Radio, SegmentedControl, Select, Stack, Text, Textarea } from '@mantine/core'
import type { Info } from '../../../api/types'
import { AUTO_DATE, PERIOD_MODES, PERIOD_MODE_HELP, chartTypeOptions, dateLabel } from '../../../lib/labels'

export function ChartTypeField({ value, onChange, allowAuto }: { value: string; onChange: (v: string) => void; allowAuto: boolean }) {
  return (
    <Select label="Chart type" data={chartTypeOptions(allowAuto)} value={value} allowDeselect={false}
            onChange={(v) => v && onChange(v)} comboboxProps={{ withinPortal: true }} />
  )
}

export function ChartRequestField({ value, onChange, label = 'Describe the chart' }: {
  value: string; onChange: (v: string) => void; label?: string
}) {
  return (
    <Textarea label={label} value={value} onChange={(e) => onChange(e.currentTarget.value)} autosize minRows={2}
              placeholder="e.g. bars for sales by month with a line for profit % on a second axis"
              description="Combos, two axes, stacked percentages, funnels, sunbursts, waterfalls... Claude draws it from the chart's data." />
  )
}

export function WidthField({ value, onChange }: { value: 'half' | 'full'; onChange: (v: 'half' | 'full') => void }) {
  return (
    <div>
      <Text size="sm" fw={500} mb={4}>Size</Text>
      <SegmentedControl value={value} onChange={(v) => onChange(v as 'half' | 'full')} radius="xl"
                        data={[{ value: 'half', label: 'Half width' }, { value: 'full', label: 'Full width' }]} />
    </div>
  )
}

const NONE = '__none__'
export const ALL_DATA = '__all__' // the cube picker's "All data" (sent as cube "")

/** Which data a new chart uses: one cube, or all the data (Claude picks the cubes). */
export function CubeField({ info, value, onChange }: { info: Info | undefined; value: string; onChange: (v: string) => void }) {
  const data = (info?.scopes ?? [{ value: '', label: 'All data' }]).map((s) => ({
    value: s.value || ALL_DATA, label: s.value ? s.label : 'All data (Claude picks the cubes)',
  }))
  return (
    <Select label="Data" data={data} value={value || ALL_DATA} allowDeselect={false} comboboxProps={{ withinPortal: true }}
            onChange={(v) => onChange(!v || v === ALL_DATA ? '' : v)} />
  )
}

type Scope = Info['scopes'][number] & { date_columns?: (string | { value: string; label?: string })[] }

/** Which date the dashboard's period filters. The cube's date columns when /api/info lists them;
 * else the cube's main date ("auto") or none. */
export function DateColumnField({ info, cube, value, onChange }: {
  info: Info | undefined; cube: string; value: string; onChange: (v: string) => void
}) {
  const scope = info?.scopes.find((s) => s.value === cube) as Scope | undefined
  const listed = (scope?.date_columns ?? []).map((c) => typeof c === 'string' ? { value: c, label: dateLabel(c) }
    : { value: c.value, label: c.label ?? dateLabel(c.value) })
  const data = [
    ...(listed.length ? listed : [{ value: AUTO_DATE, label: cube ? "The cube's main date" : "Each cube's main date" }]),
    { value: NONE, label: 'Nothing (always show all dates)' },
  ]
  const shown = value || NONE // Select needs a non-empty value for "nothing"
  if (!data.some((d) => d.value === shown)) data.unshift({ value: shown, label: dateLabel(shown) })
  return (
    <Select label="The dashboard's dates apply to" data={data} value={shown} allowDeselect={false}
            onChange={(v) => onChange(!v || v === NONE ? '' : v)} comboboxProps={{ withinPortal: true }}
            description="Which date the period picked on the dashboard filters, e.g. when the booking was made." />
  )
}

export function PeriodModeField({ value, onChange, current }: {
  value: string; onChange: (v: 'dashboard' | 'own' | 'fixed') => void; current?: { mode: string; label: string }
}) {
  return (
    <Radio.Group label="Dates" description={PERIOD_MODE_HELP} value={value} onChange={(v) => onChange(v as 'dashboard' | 'own' | 'fixed')}>
      <Stack gap={6} mt={6}>
        {PERIOD_MODES.map((m) => (
          <Radio key={m.value} value={m.value} label={m.label}
                 description={current && current.mode === m.value && current.label ? `Now: ${current.label}` : undefined} />
        ))}
      </Stack>
    </Radio.Group>
  )
}
